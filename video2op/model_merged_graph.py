"""Deployed-model analysis contract. The host validates structure; it does not infer graph semantics."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from . import config
from .llm import VLMClient
from .skill_clips import save, sha256

FIELDS = ("X", "O", "C_pre", "C_const", "E", "C_post", "R")
SCHEMA = "model_success_graph.v2"
PROMPT = Path(__file__).parent / "prompts/cross_video_success_graph.system.md"


def validate_seven_tuple(value):
    if not isinstance(value, dict) or not set(FIELDS) <= set(value):
        raise ValueError("Model must supply all seven tuple fields")
    evaluator = value["E"]
    if not isinstance(evaluator, dict) or not {
        "metric",
        "success_condition",
        "failure_condition",
        "unknown_condition",
    } <= set(evaluator):
        raise ValueError("Seven-tuple E must define evaluation criteria, not an action label")


def validate_graph(graph, cases, evidence):
    if not isinstance(graph, dict) or graph.get("schema_version") != SCHEMA:
        raise ValueError("Expected " + SCHEMA)
    required_policy = {
        "whole_task_success_required": True,
        "exclude_failed_steps_from_main_graph": True,
        "retain_failures_for_contrastive": True,
        "simplification_by_model_only": True,
    }
    if graph.get("learning_policy") != required_policy:
        raise ValueError("Keep the user success-only learning policy exactly")
    if graph.get("end_policy") != {"gate_before_end": False, "completion_validation": False}:
        raise ValueError("User policy: no gate or completion validation before END")
    if graph.get("execution_enabled") is not False:
        raise ValueError("Analysis output must not enable execution")

    def refs(row):
        if not set(row.get("evidence_refs", [])) <= set(evidence):
            raise ValueError("Only allowed evidence IDs may be cited")

    def interval(a, b, cid):
        if cid not in cases:
            raise ValueError("Unknown case " + str(cid))
        if (a is None) != (b is None):
            raise ValueError("Both times must be numeric or null")
        if a is not None and (
            isinstance(a, bool)
            or isinstance(b, bool)
            or not isinstance(a, (int, float))
            or not isinstance(b, (int, float))
            or not 0 <= a <= b <= cases[cid]["source_duration"] + 0.05
        ):
            raise ValueError("Source interval out of range")

    decisions = graph.get("source_decisions", [])
    if len(decisions) != len(cases) or {d.get("case_id") for d in decisions} != set(cases):
        raise ValueError("source_decisions must cover every input exactly once")
    selected = set()
    removed = []
    for d in decisions:
        refs(d)
        cid = d["case_id"]
        if d.get("whole_task_outcome") not in {"success", "failure", "not_executed", "unknown"}:
            raise ValueError("Invalid whole task result")
        if not isinstance(d.get("included"), bool):
            raise ValueError("Model must declare source eligibility")
        if d["included"]:
            if d["whole_task_outcome"] != "success":
                raise ValueError("Only whole-task successes may enter the learned graph")
            selected.add(cid)
        for key in ["retained_segments", "removed_failed_segments"]:
            for s in d.get(key, []):
                interval(s.get("start_sec"), s.get("end_sec"), cid)
                refs(s)
                if key == "removed_failed_segments":
                    removed.append((cid, s))
    for cid, segment in removed:
        a, b = segment.get("start_sec"), segment.get("end_sec")
        if a is not None:
            decision = next(d for d in decisions if d["case_id"] == cid)
            for kept in decision.get("retained_segments", []):
                x, y = kept.get("start_sec"), kept.get("end_sec")
                if x is not None and min(b, y) - max(a, x) > 0.05:
                    raise ValueError("Retained source range overlaps a removed failure")
    examples = graph.get("contrastive_examples")
    if not isinstance(examples, list):
        raise ValueError("Model must supply a separate contrastive_examples pool")
    ids = [r.get("id") for r in examples]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Unique contrastive sample IDs required")
    for ex in examples:
        cid = ex.get("case_id")
        refs(ex)
        if not isinstance(ex.get("skill_id"), str) or ex.get("outcome") not in {"success", "failure", "unknown"}:
            raise ValueError("Local outcome/skill must be model-authored")
        interval(ex.get("core_start_sec"), ex.get("core_end_sec"), cid)
        interval(ex.get("context_start_sec"), ex.get("context_end_sec"), cid)
    for cid, segment in removed:
        if not any(
            ex["case_id"] == cid
            and ex["outcome"] == "failure"
            and (
                segment.get("start_sec") is None
                or ex.get("core_start_sec") is None
                or (ex["core_start_sec"] <= segment["end_sec"] and ex["core_end_sec"] >= segment["start_sec"])
            )
            for ex in examples
        ):
            raise ValueError("Every removed failure needs a separate contrastive failure sample")
    if not isinstance(graph.get("simplifications"), list):
        raise ValueError("Model must review simplification, not the host program")
    for item in graph["simplifications"]:
        refs(item)
        if item.get("necessity_status") not in {"proven", "candidate", "unknown"}:
            raise ValueError("Model must distinguish retained steps from proven necessity")
        if (
            item.get("case_id") not in cases
            or item.get("decision") not in {"keep", "remove", "merge", "uncertain"}
            or not item.get("reason")
        ):
            raise ValueError("Invalid simplification review")
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    paths = graph.get("paths", [])
    if not selected:
        if nodes or edges or paths or graph.get("start_node_id") is not None or graph.get("end_node_id") is not None:
            raise ValueError("No eligible success: do not invent a learned graph")
        return graph
    ids = [n.get("id") for n in nodes]
    if not nodes or any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Unique nonempty node IDs required")
    by_id = {n["id"]: n for n in nodes}
    start, end = graph.get("start_node_id"), graph.get("end_node_id")
    if (
        start == end
        or start not in by_id
        or end not in by_id
        or any(by_id[i].get("kind") != "terminal" for i in [start, end])
    ):
        raise ValueError("Distinct start/end terminals required")
    for n in nodes:
        if n.get("kind") not in {"terminal", "operation", "gate"} or not isinstance(n.get("label"), str):
            raise ValueError("Invalid node")
        if not set(n.get("source_case_ids", [])) <= selected:
            raise ValueError("Non-success source in main graph")
        if n["kind"] == "operation":
            if n.get("observed_outcome") != "success":
                raise ValueError("Only successful operations may enter the learned graph")
            validate_seven_tuple(n.get("seven_tuple"))
        if n["kind"] == "gate":
            if (
                n.get("truth") not in {"T", "F", "U"}
                or not isinstance(n.get("predicate"), str)
                or not isinstance(n.get("reason"), str)
            ):
                raise ValueError("Model gate needs predicate/truth/reason")
            if n.get("uses_removed_failure_as_runtime_precondition") is not False:
                raise ValueError("Do not require an omitted failure before executing the success path")
            if n["truth"] != "U" and not any(s.get("evidence_refs") for s in n.get("sources", [])):
                raise ValueError("Asserted gate truth needs evidence or use U")
        for s in n.get("sources", []):
            cid = s.get("case_id")
            interval(s.get("start_sec"), s.get("end_sec"), cid)
            refs(s)
            if cid not in selected:
                raise ValueError("Excluded source cannot support a main node")
            if n["kind"] == "operation" and s.get("start_sec") is not None:
                for rcid, removed_segment in removed:
                    a, b = removed_segment.get("start_sec"), removed_segment.get("end_sec")
                    if rcid == cid and a is not None and min(b, s["end_sec"]) - max(a, s["start_sec"]) > 0.05:
                        raise ValueError("A main operation still overlaps a removed failure segment")
    edge_ids = [e.get("id") for e in edges]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("Duplicate edge IDs")
    by_pair = {}
    successors = {}
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a not in by_id or b not in by_id or a == b or (a, b) in by_pair:
            raise ValueError("Invalid edge endpoints")
        if a == end or b == start:
            raise ValueError("Start/end direction invalid")
        if b == end and by_id[a]["kind"] != "operation":
            raise ValueError("Gate before END is forbidden")
        if not e.get("source_case_ids") or not set(e["source_case_ids"]) <= selected:
            raise ValueError("Edge must have eligible source support")
        by_pair[a, b] = e
        successors.setdefault(a, []).append(b)
    if len(paths) != len(selected) or {p.get("case_id") for p in paths} != selected:
        raise ValueError("One successful-process projection per included source required")
    nm = {i: set() for i in ids}
    em = {pair: set() for pair in by_pair}
    for p in paths:
        cid = p["case_id"]
        walk = p.get("node_ids", [])
        if not walk or walk[0] != start or walk[-1] != end or len(walk) != len(set(walk)):
            raise ValueError("Complete finite successful path required")
        for i in walk:
            if i not in by_id:
                raise ValueError("Unknown path node")
            nm[i].add(cid)
        for pair in zip(walk, walk[1:], strict=False):
            if pair not in by_pair:
                raise ValueError("Missing path edge")
            em[pair].add(cid)
    for i, n in by_id.items():
        if set(n.get("source_case_ids", [])) != nm[i] or not nm[i]:
            raise ValueError("Node/path provenance mismatch: " + i)
    for pair, e in by_pair.items():
        if set(e["source_case_ids"]) != em[pair]:
            raise ValueError("Edge/path provenance mismatch")

    def walks(node, prefix, cid=None):
        if node in prefix:
            raise ValueError("Cycle: separate repeated occurrences")
        path = (*prefix, node)
        if node == end:
            yield path
        else:
            for target in successors.get(node, []):
                if cid is None or cid in by_pair[node, target]["source_case_ids"]:
                    yield from walks(target, path, cid)

    list(walks(start, ()))
    for p in paths:
        if set(walks(start, (), p["case_id"])) != {tuple(p["node_ids"])}:
            raise ValueError("Source guards permit cross-splicing")
    return graph


def prepare(root):
    root = Path(root).resolve()
    prior = root / "跨视频模型分析/result.json"
    saved = json.loads(prior.read_text())
    inputs = json.loads((prior.parent / "inputs.json").read_text())
    cases = {str(r["case_id"]): r for r in inputs["packet"]["video_mapping"]}
    for row in cases.values():
        if sha256(row["source"]) != row["sha256"]:
            raise ValueError("Original video bytes changed")
    frames = inputs["frames"]
    evidence = {
        f["frame_id"]: {
            "kind": "source_frame",
            "case_id": f["case_id"],
            "source_sec": f["timestamp"],
            "path": f["path"],
        }
        for f in frames
    }
    evidence["prior_joint_model"] = {
        "kind": "upstream_deployed_model_result",
        "path": str(prior),
        "model": saved["model"],
        "sha256": sha256(prior),
    }
    packet = {
        "user_task": inputs["packet"]["task"],
        "source_videos": list(cases.values()),
        "prior_model_analysis": {
            "model": saved["model"],
            "response": saved["response"],
            "status": "candidate_requires_video_check",
        },
        "allowed_evidence": evidence,
        "requested_model": config.MODEL,
        "end_policy": {"gate_before_end": False, "completion_validation": False},
        "excluded_inputs": "No agent-authored graph, manual visual annotations, or hardcoded case-specific gate/tuple values are supplied.",
    }
    system = PROMPT.read_text()
    digest = hashlib.sha256(
        json.dumps(
            {
                "packet": packet,
                "system": system,
                "schema": SCHEMA,
                "model": config.MODEL,
                "endpoint": config.BASE_URL,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return root, packet, system, cases, evidence, frames, Path(inputs["joint_video"]), digest


def analyze(root, *, allow_model_service=False, force=False):
    if not allow_model_service:
        raise PermissionError("Model service access must be explicitly enabled for this invocation")
    u = urlparse(config.BASE_URL)
    if u.hostname not in {"127.0.0.1", "localhost", "::1"} or u.port != 8032:
        raise ValueError("Only the currently authorized existing loopback 8032 service is allowed")
    root, packet, system, cases, evidence, frames, video, digest = prepare(root)
    folder = root / "success_process_model"
    file = folder / "result.json"
    if file.exists() and not force:
        current = json.loads(file.read_text())
        if current.get("input_fingerprint") == digest and current.get("model") == config.MODEL:
            validate_graph(current["response"], cases, evidence)
            return current
    client = VLMClient(folder / "cache" / hashlib.sha256(config.MODEL.encode()).hexdigest()[:12], use_cache=not force)
    client.session.trust_env = False
    post = client.session.post
    client.session.post = lambda *a, **kw: post(*a, **{**kw, "allow_redirects": False})
    if file.exists():
        previous = json.loads(file.read_text())
        history = folder / "history" / sha256(file)[:16]
        save(history / "result.json", previous)
        if (folder / "inputs.json").exists():
            save(history / "inputs.json", json.loads((folder / "inputs.json").read_text()))
    save(
        folder / "inputs.json",
        {
            "system": system,
            "packet": packet,
            "frames": frames,
            "joint_video": str(video),
            "model": config.MODEL,
            "endpoint": config.BASE_URL,
            "input_fingerprint": digest,
        },
    )
    try:
        response = client.ask(
            stage="cross_video_success_graph_v2",
            system=system,
            user_text=json.dumps(packet, ensure_ascii=False),
            video=video,
            images=frames,
            max_tokens=14000,
            attempts=2,
            timeout=600,
            validator=lambda x: validate_graph(x, cases, evidence),
        )
    except Exception as exc:
        save(
            folder / "failure.json",
            {
                "errors": getattr(exc, "errors", []),
                "raw_outputs": getattr(exc, "raw", []),
                "policy": "No program or agent substitutes for model analysis.",
            },
        )
        raise
    record = {
        "response": deepcopy(response),
        "model": config.MODEL,
        "endpoint": config.BASE_URL,
        "analysis_origin": "deployed_model",
        "input_fingerprint": digest,
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "model_stats": client.stats,
        "human_verified": False,
    }
    save(file, record)
    return record


def load_model_graph(root):
    root, _packet, _system, cases, evidence, _frames, _video, digest = prepare(root)
    file = root / "success_process_model/result.json"
    if not file.is_file():
        raise FileNotFoundError("No model-authored graph. Run the exporter with --analyze --allow-model-service.")
    record = json.loads(file.read_text())
    if record.get("analysis_origin") != "deployed_model" or record.get("input_fingerprint") != digest:
        raise ValueError("Model graph is stale or not model-authored; rerun its model stage")
    validate_graph(record["response"], cases, evidence)
    return record, cases, evidence
