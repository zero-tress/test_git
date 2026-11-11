"""Variant-guarded general operation graph; a union of demonstrations is not one mandatory sequence."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy


def build(skill: dict, instances: dict) -> dict:
    nodes, edges, paths = {}, {}, []
    for realization in skill["realizations"]:
        exemplar = instances[realization["instance_ids"][0]]
        counts, local = Counter(), {}
        atomic = {a["id"]: a for a in exemplar["observed_process"]}
        side_order = []
        for a in exemplar["observed_process"]:
            side = "left" if str(a.get("executor", "")).startswith("左") else "right" if str(a.get("executor", "")).startswith("右") else "whole"
            if side not in side_order:
                side_order.append(side)
        for projected in exemplar["operation_subgraph"]["nodes"]:
            selected = [atomic[r] for r in projected["selected_atomic_refs"] if r in atomic]
            actor = selected[0].get("executor", "") if selected else ""
            side = "left" if actor.startswith("左") else "right" if actor.startswith("右") else "whole"
            role = ("gripper" if actor.endswith("手") else "arm" if actor.endswith("臂") else "body")
            role += "_" + str(side_order.index(side) + 1 if side in side_order else 1)
            name = projected["name"]
            counts[(name, role)] += 1
            identity = (name, role, counts[(name, role)])
            if identity not in nodes:
                nodes[identity] = {"id": f"G{len(nodes)+1}", "operation": name, "actor_role": role,
                                   "target_role": "target", "occurrence": counts[(name, role)],
                                   "source_instances": [], "status": "pattern_candidate"}
            node = nodes[identity]
            node["source_instances"] += [i for i in realization["instance_ids"]
                                        if i not in node["source_instances"]]
            local[projected["node_id"]] = node["id"]
        path = {"realization_id": realization["realization_id"], "nodes": list(local.values()),
                "instance_ids": realization["instance_ids"],
                "selection_guard": {"status": "unresolved",
                                    "candidate_conditions": deepcopy(realization["applicability"])},
                "relations": []}
        for row in exemplar["operation_subgraph"]["relations"]:
            if row["from"] not in local or row["to"] not in local:
                continue
            edge = {"from": local[row["from"]], "to": local[row["to"]], "relation": row["relation"],
                    "basis": row.get("basis", "observed_order")}
            path["relations"].append(edge)
            key = (edge["from"], edge["to"], edge["relation"], edge["basis"])
            edges.setdefault(key, {**edge, "realization_guards": []})
            edges[key]["realization_guards"].append(realization["realization_id"])
        paths.append(path)
    common = [deepcopy(e) for e in edges.values() if len(set(e["realization_guards"])) == len(paths)]
    return {"goal_key": skill["goal_key"], "expected_effects": skill["expected_effects"],
            "nodes": list(nodes.values()), "relations": list(edges.values()), "alternatives": paths,
            "shared_structure_candidates": common,
            "policy": "Each edge is guarded by its realization. Shared observations are not proven universal causal constraints.",
            "execution_status": "semantic_candidate_requires_applicability_and_binding"}
