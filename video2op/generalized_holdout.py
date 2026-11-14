"""Frozen structural explanations; routing applicability remains a separate claim."""
from .cross_video_alignment import compatible, node_features, structure

PREPARATIONS = {"靠近", "打开", "撤回", "清障"}


def method(instance):
    """A candidate comparison, never a verified functional equivalence."""
    profile = structure(instance)
    return {"nodes": [{"operation": n["operation"], "transitions": [
                {k: t[k] for k in ["actor", "object", "mode"]} for t in n["transitions"]]}
                     for n in profile["nodes"]],
            "relations": profile["relations"]}


def core(instance):
    return [(n["operation"], n["actor_role"], n["target_role"]) for n in node_features(instance)
            if n["operation"] not in PREPARATIONS]


def explain(knowledge, holdout):
    seen = {s["video_uid"] for s in knowledge["sources"]}
    if seen & {s["video_uid"] for s in holdout["sources"]}:
        raise ValueError("Holdout video leaked into development")
    skills = {s["goal_key"]: s for s in knowledge["skills"]}
    training = {i["instance_id"]: i for i in knowledge["instances"]}
    results = []
    for item in holdout["instances"]:
        skill = skills.get(item["goal_key"])
        comparisons = []
        if not skill or not compatible(item, skill):
            decision = "goal_mismatch"
        elif not item["operation_subgraph"]["nodes"] or not item["observed_process"]:
            decision = "insufficient_evidence"
        else:
            for r in skill["realizations"]:
                for iid in r["instance_ids"]:
                    known = training[iid]
                    comparisons.append({
                        "realization_id": r["realization_id"], "instance_id": iid,
                        "exact_role_state_structure": structure(item) == structure(known),
                        "same_method_structure": method(item) == method(known),
                        "same_core_operations": bool(core(item)) and core(item) == core(known),
                        "object_category_matches": item["target"]["category"] == known["target"]["category"]})
            eligible = [c for c in comparisons if c["object_category_matches"]]
            if any(c["exact_role_state_structure"] for c in eligible):
                decision = "existing_path_candidate"
            elif any(c["same_method_structure"] for c in eligible):
                decision = "requires_condition_review"
            elif any(c["same_core_operations"] for c in eligible):
                decision = "requires_new_branch"
            else:
                decision = "requires_new_realization"
        results.append({"instance_id": item["instance_id"], "video_uid": item["video_uid"],
                        "goal_key": item["goal_key"], "decision": decision, "comparisons": comparisons,
                        "applicability_verified": False, "semantic_reuse_verified": False,
                        "reference_labels_used_for_matching": False,
                        "scope": "historical_holdout_regression_not_new_independent_generalization"})
    return results
