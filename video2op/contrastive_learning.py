"""Local outcome pools and condition contrasts grounded in source clips and review frames."""

from __future__ import annotations

import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path

from .condition_induction import induce
from .knowledge import extract
from .skill_episodes import build

PREDICATES = {
    "holding",
    "stable_holding",
    "hand_open",
    "gripper_empty",
    "accessible",
    "at_grasp_position",
    "at_destination",
    "stationary",
    "supported",
    "off_source_support",
}


def response_of(record):
    if record.get("response") is not None:
        return record["response"], "validated_response"
    for raw in record.get("raw_outputs", []):
        clean = raw.strip()
        fence = chr(96) * 3
        if clean.startswith(fence):
            match = re.search(re.escape(fence) + r"(?:json)?\s*([\s\S]*?)" + re.escape(fence), clean)
            clean = match.group(1) if match else clean
        try:
            obj = json.loads(clean)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("unit_reviews"), list):
            return obj, "salvaged_unit_candidates_original_failure_preserved"
    return {"unit_reviews": [], "causal_reviews": []}, "no_usable_response"


def _review_rows(record, units):
    obj, source = response_of(record)
    ids = {i["instance_id"] for i in units}
    frames = {f["frame_id"]: f for f in record["frames"]}
    accepted = {}
    quarantine = []
    for row in obj["unit_reviews"]:
        iid = row.get("instance_id")
        if iid not in ids or iid in accepted:
            quarantine.append({"row": row, "reason": "unknown_or_duplicate_unit"})
            continue
        referenced = set(row.get("outcome_evidence_frames", []))
        if not referenced <= set(frames):
            quarantine.append({"row": row, "reason": "unknown_outcome_frame"})
            continue
        if (
            row.get("attempted") not in {"T", "F", "U"}
            or row.get("goal_satisfied") not in {"T", "F", "U"}
            or row.get("scope_verdict") not in {"supported", "ambiguous", "requires_extension", "rejected"}
        ):
            quarantine.append({"row": row, "reason": "invalid_review_values"})
            continue
        accepted[iid] = row
    return accepted, quarantine, source


def units_for_review(bundle, source, provided_goal=None):
    case = extract(bundle, source)
    units = [i for i in case["instances"] if i["goal_key"] != "grasp_object"] + build(bundle, source)["episodes"]
    if provided_goal:
        from .learning_tracks import split

        units += split(bundle, source, case, provided_goal)["purpose_case"]["instances"]
    return case, list({u["instance_id"]: u for u in units}.values())


def causal_reviews(record, bundle):
    response, provenance = response_of(record)
    graph = bundle["semantic_graph"]
    edge_map = {
        (e["from"], e["to"]): e
        for e in graph["relations"]
        if e["from"] not in {"START", "END"} and e["to"] not in {"START", "END"}
    }
    facts = {f["frame_id"]: f for f in record["frames"]}
    accepted = []
    quarantine = []
    for row in response.get("causal_reviews", []):
        key = (row.get("from"), row.get("to"))
        refs = row.get("evidence_frames", [])
        reason = None
        if key not in edge_map or row.get("predicate_ref") not in graph["nodes"].get(key[1], {}).get("skill", {}).get(
            "C_pre", []
        ):
            reason = "unknown_edge_or_target_predicate"
        elif row.get("verdict") not in {"supported", "contradicted", "unknown"} or not set(refs) <= set(facts):
            reason = "invalid_verdict_or_frame"
        elif row["verdict"] != "unknown" and not refs:
            reason = "asserted_causal_review_without_frames"
        else:
            refs_actions = graph["evidence"].get(key[1], {}).get("atomic_refs", [])
            target_time = min(
                (a["start"] for a in bundle["atomic"]["atomic_actions"] if a["id"] in refs_actions), default=None
            )
            if row["verdict"] != "unknown" and (
                target_time is None or any(facts[r]["timestamp"] > target_time + 0.05 for r in refs)
            ):
                reason = "future_frame_cannot_prove_precondition_at_transition"
        if reason is None and row.get("verdict") != "unknown":
            source_refs = graph["evidence"].get(key[0], {}).get("atomic_refs", [])
            source_end = max(
                (
                    a["end"]
                    for a in bundle["atomic"]["atomic_actions"]
                    if a["id"] in source_refs and not a.get("inferred")
                ),
                default=None,
            )
            if source_end is None or not any(facts[r]["timestamp"] >= source_end - 0.05 for r in refs):
                reason = "no_frame_after_source_effect_at_transition"
        if reason:
            quarantine.append({"row": deepcopy(row), "reason": reason})
        else:
            accepted.append(
                {
                    **deepcopy(row),
                    "source": provenance,
                    "status": "model_candidate",
                    "causal_necessity_verified": False,
                }
            )
    return {
        "candidates": accepted,
        "quarantine": quarantine,
        "original_record_status": record.get("status"),
        "policy": "Model causal opinions do not replace deterministic effect, object and time checks.",
    }


def enrich(record):
    bundle = json.loads(Path(record["source_analysis"]).read_text())
    case, units = units_for_review(bundle, record["source_analysis"], record.get("provided_goal"))
    reviews, quarantine, provenance = _review_rows(record, units)
    frames = {f["frame_id"]: f for f in record["frames"]}
    samples = []
    for unit in units:
        unit["analysis_source"] = record["source_analysis"]
        unit["entity_context"] = deepcopy(bundle.get("semantic_scope", {}).get("objects", []))
        reviewed = reviews.get(unit["instance_id"], {})
        if "boundary" not in unit:
            unit["boundary"] = {
                "start_sec": min(a["start"] for a in unit["observed_process"]),
                "end_sec": max(a["end"] for a in unit["observed_process"]),
                "context_end_sec": min(
                    bundle["meta"]["duration"], max(a["end"] for a in unit["observed_process"]) + 0.5
                ),
            }
        reviewed = deepcopy(reviewed)
        if unit["goal_key"] == "grasp_object" and set(reviewed.get("preparation_atomic_refs", [])) - set(
            unit["atomic_refs"]
        ):
            reviewed["scope_verdict"] = "requires_extension"
        diagnostics = []
        raw_outcome = unit["outcome"]
        review_frames = [frames[f] for f in reviewed.get("outcome_evidence_frames", []) if f in frames]
        core_ids = set(unit.get("core_atomic_refs", unit["atomic_refs"]))
        core = [a for a in unit["observed_process"] if a["id"] in core_ids]
        core_start = min(a["start"] for a in core)
        core_end = max(a["end"] for a in core)
        stop = min(
            (
                a["start"]
                for a in bundle["atomic"]["atomic_actions"]
                if a.get("functional_role", {}).get("function") == "释放"
                and a["start"] >= core_end
                and a.get("object") == unit["target"]["local_entity"]
            ),
            default=float(bundle["meta"]["duration"]),
        )
        is_grasp = unit["goal_key"] == "grasp_object"
        effect_start = core_end
        if is_grasp:
            valid = [f for f in review_frames if core_end - 0.05 <= f["timestamp"] <= stop + 0.05]
        elif unit["goal_key"] == "acquire_object":
            loaded = [
                a
                for a in unit["observed_process"]
                if a.get("object") == unit["target"]["local_entity"]
                and a.get("functional_role", {}).get("function") in {"带载移动", "移动"}
            ]
            milestone = min((a["start"] for a in loaded), default=unit["boundary"]["end_sec"])
            effect_start = milestone
            valid = [f for f in review_frames if milestone - 0.05 <= f["timestamp"] <= stop + 0.05]
        else:
            valid = [f for f in review_frames if f["timestamp"] >= unit["boundary"]["end_sec"] - 0.05]
        truth = reviewed.get("goal_satisfied", "U")
        attempted = reviewed.get("attempted", "U")
        candidate_outcome = (
            "not_executed"
            if attempted == "F"
            else "success"
            if attempted == "T" and truth == "T"
            else "failure"
            if attempted == "T" and truth == "F"
            else "unknown"
        )
        if candidate_outcome in {"success", "failure"} and not valid:
            diagnostics.append("result_evidence_outside_skill_milestone_or_after_release")
            candidate_outcome = "unknown"
        if is_grasp and attempted == "F" and core:
            candidate_outcome = "unknown"
            diagnostics.append("attempt_flag_conflicts_with_observed_core_candidate")
        available = bundle["meta"].get("media_quality", {}).get("decoded_until_seconds")
        if available is not None and core_end > available + 0.05:
            candidate_outcome = "unknown"
            diagnostics.append("skill_boundary_outside_verified_decode_coverage")
        issues = unit.get("goal_effect_audit", {}).get("issues", [])
        if issues and unit["instance_scope"] != "provided_task":
            candidate_outcome = "unknown"
            diagnostics.append("unresolved_local_goal_contract")
        if reviewed.get("scope_verdict") != "supported":
            candidate_outcome = "unknown"
            diagnostics.append("scope_requires_review_or_extension")
        if unit.get("outcome_status") == "reviewed_reference":
            chosen = unit["outcome"]
            if candidate_outcome not in {chosen, "unknown"}:
                diagnostics.append("model_disagrees_with_scope_specific_reference")
        else:
            chosen = candidate_outcome
            unit["original_model_outcome"] = raw_outcome
            unit["outcome"] = chosen
            unit["outcome_status"] = "model_grounded_candidate" if chosen != "unknown" else "unverified"
            unit["outcome_evidence"] = [
                {"frame_id": f["frame_id"], "timestamp": f["timestamp"], "path": f["path"]} for f in valid
            ]
        unit["contrastive_outcome_review"] = {
            "candidate": candidate_outcome,
            "chosen": chosen,
            "source": provenance,
            "diagnostics": diagnostics,
            "raw_review": deepcopy(reviewed),
            "human_verified": False,
        }
        observations = []
        for fact in reviewed.get("conditions", []):
            if (
                fact.get("predicate") not in PREDICATES
                or fact.get("phase") not in {"entry", "core_entry", "post"}
                or fact.get("truth") not in {"T", "F", "U"}
            ):
                continue
            evidence = [frames[f] for f in fact.get("evidence_frames", []) if f in frames]
            if not evidence or len(evidence) != len(fact.get("evidence_frames", [])):
                continue
            phase = fact["phase"]
            limit = unit["boundary"]["start_sec"] if phase == "entry" else core_start
            temporal = (
                max(f["timestamp"] for f in evidence) <= limit + 0.05
                if phase != "post"
                else min(f["timestamp"] for f in evidence) >= effect_start - 0.05
            )
            value = fact["truth"] if temporal else "U"
            if is_grasp and phase == "post" and any(f["timestamp"] > stop + 0.05 for f in evidence):
                value = "U"
                temporal = False
            if "model_disagrees_with_scope_specific_reference" in diagnostics and phase == "post":
                value = "U"
                temporal = False
            if candidate_outcome == "unknown" and reviewed.get("scope_verdict") != "supported":
                value = "U"
            observations.append(
                {
                    "instance_id": unit["instance_id"],
                    "video_uid": unit["video_uid"],
                    "goal_key": unit["goal_key"],
                    "predicate": fact["predicate"],
                    "condition_key": fact["predicate"],
                    "phase": phase,
                    "at": "post" if phase == "post" else "pre",
                    "truth": value,
                    "claimed_truth": fact["truth"],
                    "at_sec": max(f["timestamp"] for f in evidence),
                    "evidence": [
                        {"frame_id": f["frame_id"], "timestamp": f["timestamp"], "path": f["path"]} for f in evidence
                    ],
                    "outcome": chosen,
                    "outcome_evidence": deepcopy(unit["outcome_evidence"]),
                    "comparison_context": phase + "|" + unit["instance_scope"],
                    "provenance": "model_grounded_candidate",
                    "temporal_status": "valid" if temporal else "future_or_wrong_phase_quarantined",
                    "reason": fact.get("reason", ""),
                }
            )
        unit["condition_observations"] = observations
        verdict = reviewed.get("scope_verdict", "ambiguous")
        sample = {
            "instance_id": unit["instance_id"],
            "video_uid": unit["video_uid"],
            "goal_key": unit["goal_key"],
            "instance_scope": unit["instance_scope"],
            "atomic_instance_ref": unit.get("atomic_instance_ref"),
            "boundary": deepcopy(unit["boundary"]),
            "outcome": chosen,
            "outcome_status": unit["outcome_status"],
            "condition_observations": observations,
            "eligible_for_rule_learning": verdict == "supported" and not issues,
            "review_diagnostics": diagnostics,
            "review_provenance": provenance,
            "scope_verdict": verdict,
            "source_analysis": record["source_analysis"],
            "task_outcome": bundle.get("task_observation", {}).get("outcome"),
        }
        samples.append(sample)
    case["instances"] = units
    case["observations"] = [o for u in units for o in u["condition_observations"]]
    case["review_quarantine"] = quarantine
    case["causal_model_review"] = causal_reviews(record, bundle)
    return case, samples


def pool_summary(samples):
    groups = {}
    for goal in sorted({s["goal_key"] for s in samples}):
        selected = [s for s in samples if s["goal_key"] == goal]
        buckets = {
            name: [s["instance_id"] for s in selected if s["outcome"] == name]
            for name in ["success", "failure", "not_executed", "unknown"]
        }
        groups[goal] = {
            "counts": {k: len(v) for k, v in buckets.items()},
            "buckets": buckets,
            "missing_negative_trials": not buckets["failure"],
            "policy": "Local failure alone is a negative execution example; unknown and nonexecution are separate.",
        }
    return {
        "schema_version": "contrastive_skill_pool.v1",
        "skills": groups,
        "condition_contrasts": induce([o for s in samples for o in s["condition_observations"]]),
        "counts": dict(Counter(s["outcome"] for s in samples)),
    }
