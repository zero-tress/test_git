"""Conservative role/state alignment. Literal evidence is not semantic entailment."""
from __future__ import annotations

import hashlib
import json
import re


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()[:20]


def roles(instance):
    """Keep arm/hand pairing and distinct bilateral actors within a demonstration."""
    sides, actors = [], {}
    for a in instance.get("observed_process", []):
        actor = str(a.get("executor", ""))
        side = "left" if actor.startswith("左") else "right" if actor.startswith("右") else actor
        if side not in sides:
            sides.append(side)
        kind = "gripper" if actor.endswith("手") else "arm" if actor.endswith("臂") else "body"
        actors[actor] = f"{kind}_{sides.index(side)+1}"
    return actors


def objects(instance):
    known = {}
    for role, entity in instance.get("bindings", {}).items():
        if entity:
            known[str(entity)] = role
    target = instance.get("target", {}).get("local_entity")
    if target:
        known[str(target)] = "target"
    others = 0
    for a in instance.get("observed_process", []):
        entity = str(a.get("object") or "")
        if entity and entity not in known:
            others += 1
            known[entity] = f"other_{others}"
    return known


def normalized(text, instance):
    replacements = {**{a: "$"+r for a, r in roles(instance).items()},
                    **{o: "$"+r for o, r in objects(instance).items()}}
    text = str(text)
    # Simultaneous replacement prevents replacing pieces of newly inserted roles.
    words = sorted((w for w in replacements if w), key=lambda w: (-len(w), w))
    if words:
        text = re.sub("|".join(re.escape(w) for w in words), lambda m: replacements[m.group()], text)
    return re.sub(r"\s+", "", text)


def effect_contract(instance):
    expected = instance.get("expected", {})
    return {"goal_key": instance.get("goal_key"),
            "effects": sorted(expected.get("expected_effects", []), key=canonical)}


def compatible(instance, skill):
    return (instance.get("goal_key") == skill.get("goal_key")
            and effect_contract(instance)["effects"] == sorted(skill.get("expected_effects", []), key=canonical))


def node_features(instance):
    amap = {a["id"]: a for a in instance.get("observed_process", [])}
    actors, object_roles = roles(instance), objects(instance)
    result = []
    for node in instance.get("operation_subgraph", {}).get("nodes", []):
        selected = [amap[r] for r in node.get("selected_atomic_refs", []) if r in amap]
        transitions = []
        for a in selected:
            transitions.append({
                "actor": actors.get(a.get("executor"), "unknown"),
                "object": object_roles.get(str(a.get("object") or ""), "unknown"),
                "mode": a.get("mode"), "inferred": bool(a.get("inferred")),
                "state_before": normalized(a.get("state_before") or "", instance),
                "state_after": normalized(a.get("state_after") or "", instance),
                "world_before": sorted(normalized(s, instance) for s in a.get("world_before", [])),
                "world_after": sorted(normalized(s, instance) for s in a.get("world_after", [])),
            })
        result.append({"source_node_id": node["node_id"], "operation": node["name"],
                       "feature": {"operation": node["name"], "transitions": transitions,
                                   "partial_node": bool(node.get("partial_node"))},
                       "actor_role": "+".join(dict.fromkeys(t["actor"] for t in transitions)) or "unknown",
                       "target_role": "+".join(dict.fromkeys(t["object"] for t in transitions)) or "unknown"})
    return result


def structure(instance):
    nodes = node_features(instance)
    index = {n["source_node_id"]: j for j, n in enumerate(nodes)}
    edges = [{"from": index[e["from"]], "to": index[e["to"]], "relation": e["relation"],
              "basis": e.get("basis", "observed_order")}
             for e in instance.get("operation_subgraph", {}).get("relations", [])
             if e["from"] in index and e["to"] in index]
    return {"nodes": [n["feature"] for n in nodes], "relations": sorted(edges, key=canonical),
            "effect_contract": effect_contract(instance)}


def realization_signature(instance):
    # Process wording preserves observed method differences; the graph additionally
    # prevents identical action strings from hiding different roles or partial orders.
    process = [{"actor": roles(instance).get(a.get("executor"), "unknown"),
                "object": objects(instance).get(str(a.get("object") or ""), "unknown"),
                "action": normalized(a.get("action") or "", instance),
                "function": a.get("functional_role", {}).get("function"), "mode": a.get("mode")}
               for a in instance.get("observed_process", [])]
    profile = structure(instance)
    # State/boundary differences are preserved as paths inside an implementation;
    # object roles, temporal topology and the goal effect distinguish methods.
    method_nodes = [{"operation": n["operation"], "partial_node": n["partial_node"],
                     "transitions": [{k: t[k] for k in ["actor", "object", "mode", "inferred"]}
                                     for t in n["transitions"]]} for n in profile["nodes"]]
    return digest({"process": process, "method_nodes": method_nodes,
                   "relations": profile["relations"], "effect_contract": profile["effect_contract"]})
