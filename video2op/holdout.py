"""Offline held-out structural explanation, separate from verified execution applicability."""
from collections import Counter
from .knowledge import extract
from .goal_semantics import contract

def structural_signature(instance):
    nodes = instance["operation_subgraph"]["nodes"]
    index = {n["node_id"]: i for i, n in enumerate(nodes)}
    operations = tuple(n["name"] for n in nodes)
    relations = tuple(sorted((index[e["from"]], index[e["to"]], e["relation"])
                             for e in instance["operation_subgraph"]["relations"]
                             if e["from"] in index and e["to"] in index))
    return operations, relations

def explain(knowledge, holdout_cases):
    seen = {s["video_uid"] for s in knowledge["sources"]}
    skills = {s["goal_key"]: s for s in knowledge["skills"]}
    instances = {i["instance_id"]: i for i in knowledge["instances"]}
    result = []
    for case in holdout_cases:
        uid = case["video_uid"]
        if uid in seen:
            raise ValueError("holdout video leaked into learned knowledge")
        rows = []
        for item in case["instances"]:
            skill = skills.get(item["goal_key"])
            matches, comparisons = [], []
            if skill and skill["expected_effects"] == item["expected"]["expected_effects"]:
                for r in skill["realizations"]:
                    for iid in r["instance_ids"]:
                        exemplar = instances[iid]
                        compatible = item["target"]["category"] in r["object_categories"]
                        same = structural_signature(item) == structural_signature(exemplar)
                        comparisons.append({"realization_id": r["realization_id"], "goal_effect_contract_matches": True,
                                            "object_category_matches": compatible, "operation_relations_match": same})
                        if compatible and same:
                            matches.append(r["realization_id"])
            decision = "miss" if not skill else "hit" if matches else "requires_new_realization"
            rows.append({"instance_id": item["instance_id"], "goal_key": item["goal_key"],
                         "decision": decision, "matched_realizations": sorted(set(matches)),
                         "comparisons": comparisons, "applicability_verified": False,
                         "unresolved": ["Common/realization-specific preconditions and runtime detectors require evidence."]})
        task_rows = [r for r in rows if r["goal_key"] == "relocate_and_release"]
        main = task_rows or rows
        decision = "miss" if not main or any(r["decision"] == "miss" for r in main) else "requires_new_realization" if any(r["decision"] == "requires_new_realization" for r in main) else "hit"
        result.append({"video_uid": uid, "decision": decision, "instances": rows,
                       "evaluation_kind": "offline_goal_object_and_operation_relation_explanation",
                       "semantic_reuse_verified": False, "reference_labels_used_for_matching": False})
    return result

def cluster_observed_instances(knowledge):
    """No declared purpose or expected-effect vector is used as a clustering feature."""
    groups = {}
    for item in knowledge["instances"]:
        states = []
        for action in item["observed_process"]:
            for text in action.get("world_after", []):
                value = str(text).replace(item["target"]["local_entity"], "$target")
                for word in ("左手", "右手", "左臂", "右臂"):
                    value = value.replace(word, "$actor")
                states.append(value)
        key = tuple(sorted(set(states[-2:]))) or ("<no_observed_world_after>", item["instance_id"])
        groups.setdefault(key, []).append(item)
    return {"schema_version": "observed_state_clustering.v1", "declared_goal_features_used": False,
            "feature": "literal_normalized_observed_final_world_states",
            "clusters": [{"cluster_id": "cluster_%03d" % (j+1), "observed_features": list(key),
                          "instance_ids": [i["instance_id"] for i in items],
                          "declared_goal_comparison": dict(Counter(i["goal_key"] for i in items))}
                         for j, (key, items) in enumerate(sorted(groups.items()))],
            "limitation": "Surface-state clustering does not establish semantic synonymy or discover universal skill classes."}
