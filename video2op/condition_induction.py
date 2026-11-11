"""Contrastive evidence counts; counterfactual prose and abstentions are not failure trials."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy


def induce(observations: list[dict]) -> dict:
    groups, rejected, seen = defaultdict(list), [], set()
    for row in observations:
        r = deepcopy(row)
        if r.get("provenance") not in {"model_grounded_candidate", "reviewed_observation"}:
            rejected.append({"row": r, "reason": "not_observed_evidence"})
            continue
        if r.get("provenance") == "reviewed_observation" and not r.get("reviewer"):
            rejected.append({"row": r, "reason": "reviewer_required"})
            continue
        if r.get("truth") not in {"T", "F", "U"} or r.get("outcome") not in {
                "success", "failure", "not_executed", "unknown"}:
            rejected.append({"row": r, "reason": "invalid_truth_or_outcome"})
            continue
        if not isinstance(r.get("goal_key"), str) or r.get("at", "pre") not in {"pre", "post"} or not r.get("video_uid") or not r.get("instance_id") or not r.get("condition_key"):
            rejected.append({"row": r, "reason": "missing_identity"})
            continue
        if r.get("truth") != "U" and not r.get("evidence"):
            rejected.append({"row": r, "reason": "truth_requires_evidence"})
            continue
        if r.get("outcome") in {"success", "failure"} and not r.get("outcome_evidence"):
            rejected.append({"row": r, "reason": "outcome_requires_evidence"})
            continue
        identity = (r["video_uid"], r["instance_id"], r["condition_key"], r.get("at", "pre"),
                    r.get("comparison_context", "unstratified"))
        if identity in seen:
            # Conflicting duplicate annotations cannot silently inflate support.
            original = next((v for values in groups.values() for v in values
                             if v.get("_identity") == identity), None)
            if original and r["provenance"] == "reviewed_observation" and original["provenance"] != "reviewed_observation":
                prior = {k: v for k, v in original.items() if k != "_identity"}
                original.clear()
                original.update(r, _identity=identity, replaced_model_assessment=prior)
            elif original and original["provenance"] == r["provenance"] and (original["truth"], original["outcome"]) != (r["truth"], r["outcome"]):
                original["annotation_conflict"] = True
            continue
        seen.add(identity)
        r["_identity"] = identity
        groups[(r.get("goal_key"), r["condition_key"], r.get("at", "pre"),
                r.get("comparison_context", "unstratified"))].append(r)
    results = []
    for (goal, key, phase, context), rows in sorted(groups.items()):
        counts = {f"{truth}_{outcome}": 0 for truth in ("T", "F", "U")
                  for outcome in ("success", "failure", "not_executed", "unknown")}
        reviewed = dict(counts)
        usable = []
        for r in rows:
            if r.get("annotation_conflict"):
                continue
            counts[f"{r['truth']}_{r['outcome']}"] += 1
            if r["provenance"] == "reviewed_observation":
                reviewed[f"{r['truth']}_{r['outcome']}"] += 1
            usable.append(r)
        necessity = ("counterexample_observed" if reviewed["F_success"] else
                     "model_counterexample_candidate" if counts["F_success"] else
                     "needs_negative_trials")
        if phase == "post":
            necessity = "effect_outcome_association_not_precondition_necessity"
        results.append({"goal_key": goal, "condition_key": key, "phase": phase,
                        "comparison_context": context, "counts": counts,
                        "reviewed_counts": reviewed, "necessity_status": necessity,
                        "causal_status": "not_established",
                        "distinct_video_count": len({r["video_uid"] for r in usable}),
                        "empirical_assessment": {
                            "condition_refuted_as_necessary": bool(reviewed["F_success"]),
                            "failure_trials": sum(reviewed[f"{t}_failure"] for t in ("T", "F", "U")),
                            "nonexecution_is_censored": True,
                            "next_step": "needs_controlled_contrast_trials",
                            "causal_established": False},
                        "conflicted_annotations": sum(bool(r.get("annotation_conflict")) for r in rows),
                        "examples": [{k: v for k, v in r.items() if k != "_identity"} for r in rows],
                        "missing_evidence": [
                            *([] if counts["F_success"] or counts["F_failure"] else ["condition_violated_trials"]),
                            *([] if counts["T_failure"] or counts["F_failure"] else ["real_failure_trials"])],
                        "policy": "Nonexecution is censored; failure is not proof of a single cause; unstratified data cannot identify causality."})
    return {"conditions": results, "rejected": rejected,
            "policy": "Counts report evidence. No empirical necessity or causal rule is fabricated from counterfactuals."}
