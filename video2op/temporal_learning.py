"""Evidence-scoped temporal knowledge: order, concurrency, alternation, branches, joins."""
from __future__ import annotations

from copy import deepcopy

PATTERNS = {"Sequence", "Parallel", "Alternation", "Branch", "Synchronization"}


def has_path(edges: list[dict], start: str, end: str) -> bool:
    todo, seen = [start], set()
    while todo:
        current = todo.pop()
        if current == end:
            return True
        if current in seen:
            continue
        seen.add(current)
        todo.extend(e["to"] for e in edges if e["from"] == current
                    and e["relation"] in {"sequence", "enables"})
    return False


def build(bundle: dict, spec: dict) -> dict:
    nodes = {n["id"] for n in spec["task_nodes"]}
    amap = spec["action_node"]
    mapping = bundle.get("learning_alignment", {}).get("source_to_final", {})
    records, issues = [], []

    def resolve(value):
        if value in nodes:
            return [value]
        if value in mapping:
            return mapping[value]
        if value in amap:
            return [amap[value]]
        if isinstance(value, str) and value.isdigit() and int(value) in amap:
            return [amap[int(value)]]
        return []

    raw = deepcopy((bundle.get("source_analysis", {}).get("rules") or {}).get("temporal_structures") or [])
    for i, r in enumerate(bundle.get("relations") or []):
        pattern = {"sequence": "Sequence", "parallel": "Parallel", "alternation": "Alternation"}.get(r.get("relation"))
        if pattern:
            raw.append({"id": f"observed_relation_{i}", "pattern": pattern,
                        "members": [r["from"], r["to"]], "evidence": r.get("note", ""),
                        "origin": "atomic_relation", "basis": "observed_order"})
    for i, row in enumerate(raw):
        r = deepcopy(row)
        r.setdefault("id", f"temporal_{i}")
        members = list(dict.fromkeys(n for ref in r.get("members", []) for n in resolve(ref)))
        r["source_members"] = r.get("members", [])
        r["members"] = members
        r["status"] = "candidate"
        r["issues"] = []
        if r.get("pattern") not in PATTERNS:
            r["issues"].append("unknown_pattern")
        if len(members) < 2:
            r["issues"].append("members_unresolved_or_collapsed")
        if any(not resolve(ref) for ref in r["source_members"]):
            r["issues"].append("unresolved_member_reference")
        if r.get("pattern") == "Branch":
            alternatives = r.get("alternatives") or []
            converted = []
            for arm in alternatives:
                converted.append({**arm, "members": list(dict.fromkeys(
                    n for ref in arm.get("members", []) for n in resolve(ref)))})
            r["alternatives"] = converted
            if len(converted) < 2 or any(not a.get("when") or not a["members"] for a in converted):
                r["issues"].append("branch_requires_guarded_alternatives")
            r["policy"] = "Alternative paths are hypotheses unless each has observed support."
        if r.get("pattern") == "Synchronization":
            target = resolve(r.get("target"))
            r["target"] = target[0] if len(target) == 1 else None
            if r["target"] is None or r["target"] in members or r.get("join", "all") not in {"all", "any"}:
                r["issues"].append("invalid_synchronization_target_or_join")
            r.setdefault("join", "all")
        if r.get("pattern") in {"Parallel", "Alternation"}:
            if any(has_path(spec["edges"], a, b) or has_path(spec["edges"], b, a)
                   for i, a in enumerate(members) for b in members[i + 1:]):
                r["issues"].append("conflicts_with_required_order")
            elif len(members) == 2 and not r["issues"]:
                relation = "parallel" if r["pattern"] == "Parallel" else "alternation"
                pair = frozenset(members)
                if not any(e["relation"] == relation and frozenset((e["from"], e["to"])) == pair
                           for e in spec["edges"]):
                    spec["edges"].append({"from": members[0], "to": members[1],
                                          "relation": relation, "basis": "observed_order",
                                          "note": "视频关系候选，非强制执行依赖", "mutual": True})
        if r["issues"]:
            r["status"] = "needs_review"
            issues.append({"id": r["id"], "issues": r["issues"]})
        records.append(r)
    return {"patterns": records, "issues": issues,
            "policy": "Observed order is not causal necessity; branches and joins retain explicit guards and scope."}


def validate_graph(graph: dict) -> list[str]:
    nodes, predicates = graph.get("nodes", {}), graph.get("predicates", {})
    errors, hard = [], []
    for nid, node in nodes.items():
        skill = node.get("skill", {})
        for kind in ("C_pre", "C_post", "C_const"):
            for key in skill.get(kind, []):
                if key not in predicates:
                    errors.append(f"{nid}.{kind}: unknown predicate {key}")
    for r in graph.get("relations", []):
        if r["from"] not in nodes or r["to"] not in nodes:
            errors.append("temporal relation references unknown node")
        if r.get("when") and r["when"] not in predicates:
            errors.append("temporal condition references unknown predicate")
        if r["from"] == r["to"]:
            errors.append("self temporal relation")
        if r["relation"] == "sequence":
            if has_path(hard, r["to"], r["from"]):
                errors.append("causal order contains a cycle")
            hard.append(r)
    for r in graph.get("relations", []):
        if r["relation"] in {"parallel", "alternation"} and (
                has_path(hard, r["from"], r["to"]) or has_path(hard, r["to"], r["from"])):
            errors.append("soft temporal relation conflicts with causal order")
    return sorted(set(errors))
