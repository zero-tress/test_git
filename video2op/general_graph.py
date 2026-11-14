"""Evidence-guarded graph of every demonstration, with source-path reconstruction."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from .cross_video_alignment import canonical, compatible, digest, node_features, objects, roles


def _cycle(edges):
    adjacent = {}
    for e in edges:
        if e["relation"] == "sequence":
            adjacent.setdefault(e["from"], set()).add(e["to"])
    active, done = set(), set()
    def visit(n):
        if n in active:
            return True
        if n in done:
            return False
        active.add(n)
        if any(visit(v) for v in adjacent.get(n, ())):
            return True
        active.remove(n)
        done.add(n)
        return False
    return any(visit(n) for n in list(adjacent))


def build(skill: dict, instances: dict) -> dict:
    nodes, edges, paths, unresolved = {}, {}, [], []
    seen = set()
    for realization in skill["realizations"]:
        for iid in realization["instance_ids"]:
            if iid in seen:
                raise ValueError("Instance assigned to more than one realization: " + iid)
            seen.add(iid)
            item = instances[iid]
            if not compatible(item, skill):
                unresolved.append({"instance_id": iid, "reason": "goal_effect_contract_mismatch"})
                continue
            features = node_features(item)
            counts, local, pending = Counter(), {}, {}
            pid = "P_" + digest(iid)
            for f in features:
                signature = canonical(f["feature"])
                counts[signature] += 1
                identity = digest([f["feature"], counts[signature]])
                node = nodes.get(identity) or pending.setdefault(identity, {
                    "id": "G_" + identity, "operation": f["operation"], "actor_role": f["actor_role"],
                    "target_role": f["target_role"], "occurrence": counts[signature],
                    "feature": deepcopy(f["feature"]), "source_instances": [], "path_guards": [],
                    "status": "pattern_candidate", "alignment_basis": "literal_role_and_state_candidate"})
                local[f["source_node_id"]] = node["id"]
            original_edges = item["operation_subgraph"]["relations"]
            def mapped_edges(original_edges, local):
                return [{**deepcopy(e), "from": local[e["from"]], "to": local[e["to"]],
                         "basis": e.get("basis", "observed_order")}
                        for e in original_edges if e["from"] in local and e["to"] in local]
            relations = mapped_edges(original_edges, local)
            alignment_issues = []
            if _cycle(list(edges.values()) + relations):
                # Opposite ordering from another demonstration must not invent a loop.
                pending = {}
                for f in features:
                    identity = digest([pid, f["source_node_id"], f["feature"]])
                    pending[identity] = {
                        "id": "G_" + identity, "operation": f["operation"], "actor_role": f["actor_role"],
                        "target_role": f["target_role"], "occurrence": 1, "feature": deepcopy(f["feature"]),
                        "source_instances": [], "path_guards": [], "status": "pattern_candidate",
                        "alignment_basis": "order_conflict_kept_separate"}
                    local[f["source_node_id"]] = pending[identity]["id"]
                relations = mapped_edges(original_edges, local)
                alignment_issues.append("opposite_order_kept_separate")
            nodes.update(pending)
            by_id = {n["id"]: n for n in nodes.values()}
            for nid in local.values():
                node = by_id[nid]
                if iid not in node["source_instances"]:
                    node["source_instances"].append(iid)
                node["path_guards"].append(pid)
            path = {"path_id": pid, "realization_id": realization["realization_id"],
                    "nodes": list(local.values()), "source_node_map": local,
                    "instance_ids": [iid], "video_uid": item["video_uid"],
                    "source": item.get("analysis_source", item.get("source")),
                    "object_bindings": deepcopy(item.get("bindings", {})),
                    "role_bindings": {"objects": {v: k for k, v in objects(item).items()},
                                      "actors": {v: k for k, v in roles(item).items()}},
                    "selection_guard": {"status": "unresolved", "truth": "U",
                                        "candidate_conditions": deepcopy(realization["applicability"]),
                                        "policy": "Observed predecessors do not establish a routing rule."},
                    "alignment_issues": alignment_issues, "relations": relations}
            paths.append(path)
            for edge in relations:
                key = canonical({k: edge[k] for k in ["from", "to", "relation", "basis"]})
                merged = edges.setdefault(key, {**deepcopy(edge), "realization_guards": [], "path_guards": []})
                for field, value in [("realization_guards", realization["realization_id"]), ("path_guards", pid)]:
                    if value not in merged[field]:
                        merged[field].append(value)
    shared = [deepcopy(e) for e in edges.values() if len(e["path_guards"]) == len(paths) and paths]
    graph = {"schema_version": "general_operation_graph.v2", "goal_key": skill["goal_key"],
             "expected_effects": deepcopy(skill["expected_effects"]), "nodes": list(nodes.values()),
             "relations": list(edges.values()), "alternatives": paths, "shared_structure_candidates": shared,
             "unresolved": unresolved, "path_policy": "Only complete recorded paths with their bindings are admissible.",
             "policy": "Shared literal states are candidates, not proven semantic synonymy or universal causal constraints.",
             "execution_status": "semantic_candidate_requires_applicability_and_binding"}
    graph["reconstruction_validation"] = validate_reconstruction(graph, instances)
    return graph


def accepts_path(graph, node_ids, relations=None):
    """Reject cross-splicing even when every separate edge exists in the union."""
    matches = [p for p in graph["alternatives"] if p["nodes"] == list(node_ids)]
    if relations is not None:
        def signature(es):
            return sorted((e["from"], e["to"], e["relation"], e.get("basis", "observed_order")) for e in es)
        matches = [p for p in matches if signature(p["relations"]) == signature(relations)]
    return [p["path_id"] for p in matches]


def validate_reconstruction(graph, instances):
    errors, checked = [], 0
    nodes = {n["id"]: n for n in graph["nodes"]}
    merged_edges = {(e["from"], e["to"], e["relation"], e.get("basis", "observed_order")): e for e in graph["relations"]}
    for path in graph["alternatives"]:
        iid = path["instance_ids"][0]
        item = instances[iid]
        mapping = path["source_node_map"]
        features = node_features(item)
        if set(mapping) != {n["source_node_id"] for n in features} or len(set(mapping.values())) != len(mapping):
            errors.append({"instance_id": iid, "reason": "node_loss_or_collapse"})
        for f in features:
            n = nodes.get(mapping.get(f["source_node_id"]))
            if not n or n["feature"] != f["feature"] or iid not in n["source_instances"]:
                errors.append({"instance_id": iid, "reason": "node_feature_or_source_mismatch"})
        if path["nodes"] != [mapping.get(f["source_node_id"]) for f in features]:
            errors.append({"instance_id": iid, "reason": "path_node_order_changed"})
        for edge in path["relations"]:
            key = (edge["from"], edge["to"], edge["relation"], edge.get("basis", "observed_order"))
            merged = merged_edges.get(key, {})
            if path["path_id"] not in merged.get("path_guards", []):
                errors.append({"instance_id": iid, "reason": "union_lost_guarded_edge"})
        for nid in path["nodes"]:
            if path["path_id"] not in nodes.get(nid, {}).get("path_guards", []):
                errors.append({"instance_id": iid, "reason": "union_lost_guarded_node"})
        expected_roles = {"objects": {v: k for k, v in objects(item).items()},
                          "actors": {v: k for k, v in roles(item).items()}}
        if path.get("role_bindings") != expected_roles:
            errors.append({"instance_id": iid, "reason": "role_binding_changed"})
        inverse = {v: k for k, v in mapping.items()}
        restored = [{**deepcopy(e), "from": inverse.get(e["from"]), "to": inverse.get(e["to"])}
                    for e in path["relations"]]
        original = [{**deepcopy(e), "basis": e.get("basis", "observed_order")}
                    for e in item["operation_subgraph"]["relations"]]
        if sorted(restored, key=canonical) != sorted(original, key=canonical):
            errors.append({"instance_id": iid, "reason": "relation_loss_or_change"})
        if path["object_bindings"] != item.get("bindings", {}):
            errors.append({"instance_id": iid, "reason": "binding_changed"})
        if _cycle(path["relations"]):
            errors.append({"instance_id": iid, "reason": "source_sequence_cycle"})
        checked += 1
    return {"passed": not errors, "instances_checked": checked, "errors": errors,
            "kind": "source_path_preservation_not_semantic_verification"}
