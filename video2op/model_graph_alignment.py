"""Model-only semantic alignment after source-instance interpretation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from . import config
from .llm import VLMClient
from .skill_clips import save, sha256

PROMPT = Path(__file__).parent / "prompts/cross_video_graph_alignment.system.md"


def read_requirements(root):
    file = Path(root) / "graph_requirements.json"
    return json.loads(file.read_text()) if file.exists() else {}


def requirements_hash(root):
    file = Path(root) / "graph_requirements.json"
    return sha256(file) if file.exists() else None


def alignment_is_current(record, root):
    return (
        record.get("graph_stage") == "semantic_merged"
        and record.get("alignment_prompt_sha256") == sha256(PROMPT)
        and record.get("alignment_requirements_sha256") == requirements_hash(root)
    )


def validate_alignment(graph, instance, cases, evidence, requirements=None):
    from .model_merged_graph import validate_graph

    validate_graph(graph, cases, evidence, requirements)
    for key in [
        "source_decisions",
        "contrastive_examples",
        "simplifications",
        "learning_policy",
        "end_policy",
        "execution_enabled",
        "approach_policy",
    ]:
        if graph.get(key) != instance.get(key):
            raise ValueError("Semantic alignment must retain instance judgments unchanged: " + key)
    before = {r["case_id"]: len(r["occurrences"]) for r in instance["approach_review"]}
    after = {r["case_id"]: len(r["occurrences"]) for r in graph["approach_review"]}
    if before != after:
        raise ValueError("Semantic alignment must preserve every source's approach occurrence count")
    grasp = [n for n in graph["nodes"] if n.get("action_role") == "grasp_target"]
    participants = {cid for n in grasp for cid in n["source_case_ids"]}
    if len(participants) > 1 and not any(len(n["source_case_ids"]) > 1 for n in grasp):
        raise ValueError("Same-goal grasp instances must share a parameterized semantic node")
    return graph


def align(root, record, cases, evidence, digest):
    u = urlparse(config.BASE_URL)
    if u.hostname not in {"127.0.0.1", "localhost", "::1"} or u.port != 8032:
        raise ValueError("Only the currently authorized existing loopback 8032 service is allowed")
    root = Path(root)
    canonical = root / "success_process_model/result.json"
    if canonical.exists():
        from .model_merged_graph import archive_model_record

        archive_model_record(canonical.parent, canonical)
    folder = root / "semantic_alignment_model"
    instance_key = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    instance_path = root / "instance_graph_model/records" / (instance_key + ".json")
    save(instance_path, record)
    save(root / "instance_graph_model/result.json", record)
    system = PROMPT.read_text()
    requirements = read_requirements(root)
    packet = {
        "source_instance_graph": record["response"],
        "user_graph_requirements": requirements,
        "previous_success_graph_candidate": None,
        "required_source_video_approach_counts": {
            r["case_id"]: len(r["occurrences"]) for r in record["response"]["approach_review"]
        },
        "allowed_evidence": evidence,
        "requested_model": config.MODEL,
    }
    # Locate the previously delivered model record by provenance, not semantic heuristics.
    revision_path = root / "merged_visualization_revision.json"
    if revision_path.exists():
        revision = json.loads(revision_path.read_text())
        delivered_hash = revision.get("records", {}).get("success_process_model", {}).get("sha256")
        for f in (root / "success_process_model/history").glob("*/result.json"):
            if sha256(f) != delivered_hash:
                continue
            old = json.loads(f.read_text())
            input_path = f.parent / "inputs.json"
            if not input_path.exists():
                continue
            old_inputs = json.loads(input_path.read_text())
            videos = old_inputs.get("packet", {}).get("source_videos", [])
            if {str(v["case_id"]): v["sha256"] for v in videos} != {k: v["sha256"] for k, v in cases.items()}:
                continue
            if old.get("analysis_origin") == "deployed_model":
                packet["previous_success_graph_candidate"] = {
                    "response": old["response"],
                    "model": old["model"],
                    "sha256": sha256(f),
                }
            break
    client = VLMClient(folder / "cache" / hashlib.sha256(config.MODEL.encode()).hexdigest()[:12])
    client.session.trust_env = False
    post = client.session.post
    client.session.post = lambda *a, **kw: post(*a, **{**kw, "allow_redirects": False})
    save(
        folder / "inputs.json",
        {
            "system": system,
            "packet": packet,
            "input_fingerprint": digest,
            "model": config.MODEL,
            "source_instance_record_sha256": sha256(instance_path),
        },
    )
    try:
        response = client.ask(
            stage="semantic_graph_alignment_v3",
            system=system,
            user_text=json.dumps(packet, ensure_ascii=False),
            max_tokens=10000,
            attempts=2,
            timeout=500,
            validator=lambda x: validate_alignment(x, record["response"], cases, evidence, requirements),
        )
    except Exception as exc:
        save(
            folder / "failure.json",
            {
                "errors": getattr(exc, "errors", []),
                "raw_outputs": getattr(exc, "raw", []),
                "policy": "No host semantic merge fallback.",
            },
        )
        raise
    result = {
        "response": deepcopy(response),
        "analysis_origin": "deployed_model",
        "model": config.MODEL,
        "endpoint": config.BASE_URL,
        "input_fingerprint": digest,
        "graph_stage": "semantic_merged",
        "alignment_prompt_sha256": sha256(PROMPT),
        "alignment_requirements_sha256": requirements_hash(root),
        "model_stats": client.stats,
        "instance_model_stats": record["model_stats"],
        "instance_record": str(instance_path.relative_to(root)),
        "instance_record_sha256": sha256(instance_path),
        "human_verified": False,
    }
    save(folder / "result.json", result)
    canonical = root / "success_process_model/result.json"
    if canonical.exists():
        from .model_merged_graph import archive_model_record

        archive_model_record(canonical.parent, canonical)
    save(canonical, result)
    return result
