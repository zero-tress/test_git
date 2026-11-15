"""Induce auditable pre-decision branch candidates; choice negatives are not failures."""

from collections import defaultdict

from .task_causality import observed_facts


def _changes(predicate, action):
    function = action.get("functional_role", {}).get("function", "")
    if predicate in {"holding", "stable_holding", "gripper_empty", "hand_open"}:
        return function in {"抓取", "抓握", "释放", "打开"}
    if predicate == "accessible":
        return function in {"清障", "移动", "带载移动", "无载移动", "推", "拉"}
    if predicate in {"at_destination", "stationary", "supported"}:
        return function in {"移动", "带载移动", "推", "拉", "释放"}
    if predicate == "at_grasp_position":
        return function in {"靠近", "移动", "带载移动", "无载移动", "撤回"}
    return True


def features_before(sample, unit, decision_time):
    facts = []
    for row in sample.get("condition_observations", []):
        if (
            not isinstance(row.get("at_sec"), (int, float))
            or row["truth"] == "U"
            or row["at_sec"] > decision_time + 1e-6
        ):
            continue
        if row["phase"] == "post":
            continue
        if any(
            _changes(row["predicate"], a) and a["start"] >= row["at_sec"] and a["end"] <= decision_time
            for a in unit.get("observed_process", [])
        ):
            continue
        facts.append(
            {
                "predicate": row["predicate"],
                "truth": row["truth"],
                "at_sec": row["at_sec"],
                "evidence": row["evidence"],
                "source": "model_video_review",
            }
        )
    for phase in ["pre", "post"]:
        for fact in observed_facts(unit.get("observed_process", []), unit, phase):
            if any(str(a).startswith(("other_", "context_", "unresolved_")) for a in fact["args"]):
                continue
            time = fact["evidence"]["at_sec"]
            if time > decision_time + 1e-6:
                continue
            if any(
                _changes(fact["predicate"], a) and a["start"] >= time and a["end"] <= decision_time
                for a in unit.get("observed_process", [])
            ):
                continue
            facts.append(
                {
                    "predicate": fact["predicate"],
                    "truth": "T" if fact["truth"] else "F",
                    "at_sec": time,
                    "evidence": [fact["evidence"]],
                    "source": "model_extracted_state",
                }
            )
    latest = {}
    for row in sorted(facts, key=lambda r: r["at_sec"]):
        old = latest.get(row["predicate"])
        if old and old["at_sec"] == row["at_sec"] and old["truth"] != row["truth"]:
            latest[row["predicate"]] = {**row, "truth": "U"}
        else:
            latest[row["predicate"]] = row
    return latest


def entry_nodes(path):
    nodes = set(path["source_node_map"].values())
    incoming = {e["to"] for e in path["relations"] if e["relation"] == "sequence"}
    return sorted(nodes - incoming)


def induce(knowledge, samples, minimum_videos=2):
    instances = {i["instance_id"]: i for i in knowledge["instances"]}
    by_id = {s["instance_id"]: s for s in samples}
    results = []
    for skill in knowledge["skills"]:
        graph = skill["general_operation_graph"]
        outgoing = defaultdict(set)
        for edge in graph["relations"]:
            if edge["relation"] == "sequence":
                outgoing[edge["from"]].add(edge["to"])
        for path in graph["alternatives"]:
            roots = entry_nodes(path)
            if len(roots) == 1:
                outgoing["START"].add(roots[0])
        for node, targets in outgoing.items():
            if len(targets) < 2:
                continue
            decisions = []
            excluded = []
            for path in graph["alternatives"]:
                following = [e["to"] for e in path["relations"] if e["from"] == node and e["relation"] == "sequence"]
                if node == "START":
                    following = entry_nodes(path)
                if len(following) != 1:
                    excluded.append(
                        {"instance_ids": path["instance_ids"], "reason": "no_unique_observed_choice_at_this_branch"}
                    )
                    continue
                iid = path["instance_ids"][0]
                unit = instances[iid]
                if iid not in by_id or not by_id[iid].get("eligible_for_rule_learning", False):
                    continue
                local_nodes = [key for key, value in path["source_node_map"].items() if value == following[0]]
                refs = {
                    r
                    for n in unit["operation_subgraph"]["nodes"]
                    if n["node_id"] in local_nodes
                    for r in n["selected_atomic_refs"]
                }
                time = min((a["start"] for a in unit["observed_process"] if a["id"] in refs), default=None)
                if time is None:
                    continue
                decisions.append(
                    {
                        "instance_id": iid,
                        "video_uid": unit["video_uid"],
                        "choice": following[0],
                        "decision_time": time,
                        "features": features_before(by_id[iid], unit, time),
                    }
                )
            rules = []
            insufficient = []
            for target in sorted(targets):
                positive = [d for d in decisions if d["choice"] == target]
                negative = [d for d in decisions if d["choice"] != target]
                predicates = {p for d in decisions for p in d["features"]}
                for predicate in sorted(predicates):
                    for value in ["T", "F"]:
                        support = [d for d in positive if d["features"].get(predicate, {}).get("truth") == value]
                        counter = [
                            d
                            for d in positive
                            if d["features"].get(predicate, {}).get("truth") in {"T", "F"}
                            and d["features"][predicate]["truth"] != value
                        ]
                        alternatives = [
                            d
                            for d in negative
                            if d["features"].get(predicate, {}).get("truth") in {"T", "F"}
                            and d["features"][predicate]["truth"] != value
                        ]
                        against = [d for d in negative if d["features"].get(predicate, {}).get("truth") == value]
                        if (
                            len({d["video_uid"] for d in support}) < minimum_videos
                            or len({d["video_uid"] for d in alternatives}) < minimum_videos
                        ):
                            if support:
                                insufficient.append(
                                    {
                                        "target": target,
                                        "predicate": predicate,
                                        "expected_truth": value,
                                        "support_video_count": len({d["video_uid"] for d in support}),
                                        "contrast_video_count": len({d["video_uid"] for d in alternatives}),
                                        "counterexample_count": len(counter + against),
                                        "status": "insufficient_independent_contrasts",
                                    }
                                )
                            continue
                        rules.append(
                            {
                                "target": target,
                                "predicate": predicate,
                                "expected_truth": value,
                                "status": "contradicted_candidate"
                                if counter or against
                                else "observational_candidate",
                                "support": support,
                                "alternative_choice_contrasts": alternatives,
                                "counterexamples": counter + against,
                                "unknown_instances": [
                                    d["instance_id"]
                                    for d in decisions
                                    if d["features"].get(predicate, {}).get("truth", "U") == "U"
                                ],
                                "causally_verified": False,
                                "execution_enabled": False,
                            }
                        )
            results.append(
                {
                    "skill_id": skill["skill_id"],
                    "branch_node": node,
                    "choices": sorted(targets),
                    "decisions": decisions,
                    "excluded_paths": excluded,
                    "rules": rules,
                    "insufficient_candidates": insufficient,
                    "status": "candidate_rules" if rules else "unknown_insufficient_predecision_contrasts",
                    "policy": "Alternative choices are not failed executions; outcome contrasts are separate.",
                }
            )
    return {
        "schema_version": "branch_guard_induction.v1",
        "branches": results,
        "minimum_distinct_videos_per_side": minimum_videos,
        "automatic_execution_rules": 0,
    }
