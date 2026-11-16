"""Model-only contrastive review. Candidate coverage is checked; semantic labels are never filled by host."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .llm import VLMClient
from .model_merged_graph import load_model_graph, prepare, validate_seven_tuple
from .skill_clips import save, sha256

PROMPT = Path(__file__).parent / "prompts/cross_video_contrastive_review.system.md"


def packet_for(root):
    root, packet, _, cases, evidence, frames, video, _ = prepare(root)
    main, _, _ = load_model_graph(root)
    prior = packet["prior_model_analysis"]["response"].get("contrastive_learning", {}).get("grasp_trials", [])
    candidates = [
        {"candidate_ref": "prior_trial_" + str(i), "prior_model_candidate": deepcopy(t)} for i, t in enumerate(prior)
    ]
    for c in candidates:
        evidence[c["candidate_ref"]] = {
            "kind": "upstream_model_trial_candidate",
            "case_id": c["prior_model_candidate"]["case_id"],
            "candidate": c["prior_model_candidate"],
        }
    payload = {
        "requested_skill_definition": {
            "skill_id": "grasp_object",
            "purpose": "建立对同一目标的稳定握持",
            "not_required": "抬离原支撑",
            "origin": "explicit_user_learning_scope",
        },
        "task": packet["user_task"],
        "source_videos": packet["source_videos"],
        "whole_task_model_observations": [
            {k: d.get(k) for k in ["case_id", "whole_task_outcome", "included", "reason"]}
            for d in main["response"].get("source_decisions", [])
        ],
        "candidate_local_trials": candidates,
        "allowed_evidence": evidence,
        "requested_model": config.MODEL,
    }
    system = PROMPT.read_text()
    digest = hashlib.sha256(
        json.dumps(
            {"payload": payload, "system": system, "model": config.MODEL, "endpoint": config.BASE_URL},
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return root, payload, system, cases, evidence, frames, video, digest


def validate_review(obj, cases, evidence, candidates):
    if not isinstance(obj, dict) or obj.get("schema_version") != "model_contrastive_review.v1":
        raise ValueError("Expected model_contrastive_review.v1")
    defs = obj.get("skill_definitions", [])
    by_id = {d.get("skill_id"): d for d in defs}
    if len(by_id) != len(defs):
        raise ValueError("Duplicate skill IDs")
    for d in defs:
        validate_seven_tuple(d.get("seven_tuple"))
    examples = obj.get("examples", [])
    ids = [e.get("id") for e in examples]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Unique local trial IDs required")
    expected = {c["candidate_ref"]: c["prior_model_candidate"] for c in candidates}
    seen = []

    def interval(a, b, cid):
        if (a is None) != (b is None):
            raise ValueError("Both bounds must be numeric or null")
        if a is not None and (
            isinstance(a, bool)
            or isinstance(b, bool)
            or not isinstance(a, (int, float))
            or not isinstance(b, (int, float))
            or not 0 <= a <= b <= cases[cid]["source_duration"] + 0.05
        ):
            raise ValueError("Trial interval out of source range")

    for e in examples:
        cid = e.get("case_id")
        ref = e.get("candidate_ref")
        if (
            cid not in cases
            or e.get("skill_id") not in by_id
            or e.get("outcome") not in {"success", "failure", "unknown"}
        ):
            raise ValueError("Unknown source, skill or invalid outcome")
        if ref is not None:
            if ref not in expected or expected[ref]["case_id"] != cid:
                raise ValueError("Candidate/source mismatch")
            seen.append(ref)
        if not set(e.get("evidence_refs", [])) <= set(evidence):
            raise ValueError("Use allowed evidence IDs")
        if e.get("skill_id") != "grasp_object" or e.get("scope_verdict") not in {
            "supported",
            "ambiguous",
            "rejected",
        }:
            raise ValueError(
                "Use user requested skill_id=grasp_object and provide scope_verdict; rejected/ambiguous scopes must remain unknown"
            )
        if e["scope_verdict"] != "supported" and e["outcome"] != "unknown":
            raise ValueError("Unconfirmed skill scope cannot be a positive/negative")
        if e["outcome"] != "unknown" and not e.get("evidence_refs"):
            raise ValueError("Local success/failure needs evidence")
        interval(e.get("core_start_sec"), e.get("core_end_sec"), cid)
        interval(e.get("context_start_sec"), e.get("context_end_sec"), cid)
        if (
            e.get("core_start_sec") is not None
            and e.get("context_start_sec") is not None
            and not e["context_start_sec"] <= e["core_start_sec"] <= e["core_end_sec"] <= e["context_end_sec"]
        ):
            raise ValueError("Context must cover its own core")
    if set(seen) != set(expected) or len(seen) != len(set(seen)):
        raise ValueError("Review each candidate_ref exactly once: " + json.dumps(sorted(expected)))
    for c in obj.get("condition_comparisons", []):
        if not set(c.get("positive_example_ids", []) + c.get("negative_example_ids", [])) <= set(ids):
            raise ValueError("Condition comparison cites unknown local trials")
    by_example = {e["id"]: e for e in examples}
    for comparison in obj.get("condition_comparisons", []):
        for key, required in [("positive_example_ids", "success"), ("negative_example_ids", "failure")]:
            if any(by_example[i]["outcome"] != required for i in comparison.get(key, [])):
                raise ValueError("Condition comparison positive/negative refs must match local trial outcomes")
    return obj


def analyze(root, *, allow_model_service=False, force=False):
    if not allow_model_service:
        raise PermissionError("Enable the authorized model service explicitly")
    u = urlparse(config.BASE_URL)
    if u.hostname not in {"127.0.0.1", "localhost", "::1"} or u.port != 8032:
        raise ValueError("Only currently authorized loopback 8032 is allowed")
    root, payload, system, cases, evidence, frames, video, digest = packet_for(root)
    folder = root / "contrastive_process_model"
    file = folder / "result.json"
    if file.exists() and not force:
        record = json.loads(file.read_text())
        if record.get("input_fingerprint") == digest and record.get("model") == config.MODEL:
            validate_review(record["response"], cases, evidence, payload["candidate_local_trials"])
            return record
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
            "packet": payload,
            "frames": frames,
            "joint_video": str(video),
            "model": config.MODEL,
            "input_fingerprint": digest,
        },
    )
    try:
        response = client.ask(
            stage="model_local_contrastive_review_v1",
            system=system,
            user_text=json.dumps(payload, ensure_ascii=False),
            video=video,
            images=frames,
            max_tokens=7000,
            attempts=2,
            timeout=600,
            validator=lambda x: validate_review(x, cases, evidence, payload["candidate_local_trials"]),
        )
    except Exception as exc:
        save(
            folder / "failure.json",
            {
                "errors": getattr(exc, "errors", []),
                "raw_outputs": getattr(exc, "raw", []),
                "policy": "No agent-generated labels are used as fallback.",
            },
        )
        raise
    record = {
        "response": deepcopy(response),
        "analysis_origin": "deployed_model",
        "model": config.MODEL,
        "endpoint": config.BASE_URL,
        "input_fingerprint": digest,
        "model_stats": client.stats,
        "parent_success_graph_sha256": sha256(root / "success_process_model/result.json"),
        "human_verified": False,
    }
    save(file, record)
    return record


def load_review(root):
    root, payload, _, cases, evidence, _, _, digest = packet_for(root)
    path = root / "contrastive_process_model/result.json"
    if not path.is_file():
        raise FileNotFoundError(
            "Missing model contrastive review; run the model stage, no host-label fallback is available"
        )
    record = json.loads(path.read_text())
    if record.get("analysis_origin") != "deployed_model" or record.get("input_fingerprint") != digest:
        raise ValueError("Contrastive model result is stale or has no model provenance")
    validate_review(record["response"], cases, evidence, payload["candidate_local_trials"])
    return record
