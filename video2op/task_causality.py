"""Ground task-graph effect/precondition bridges without inferring universal necessity."""

from __future__ import annotations

from collections import Counter

from .semantic_state import atoms, entails, opposite


def context(bundle, target=None):
    entities = list(bundle.get("semantic_scope", {}).get("objects", []))
    actions = bundle.get("atomic", {}).get("atomic_actions", [])
    if target is None:
        target = next((r.get("label") for r in entities if r.get("label")), "目标物体")
    category = next((r.get("category", "unknown") for r in entities if r.get("label") == target), "unknown")
    return {
        "target": {"local_entity": target, "category": category},
        "bindings": {"target": target},
        "observed_process": actions,
        "entity_context": entities,
    }


def node_actions(bundle, node_id):
    refs = bundle["semantic_graph"].get("evidence", {}).get(node_id, {}).get("atomic_refs", [])
    actions = {a["id"]: a for a in bundle.get("atomic", {}).get("atomic_actions", [])}
    return [actions[r] for r in refs if r in actions]


def observed_facts(actions, ctx, phase):
    facts = []
    fields = ["state_before", "world_before"] if phase == "pre" else ["state_after", "world_after"]
    for a in actions:
        if a.get("inferred"):
            continue
        for field in fields:
            if a.get(field + "_from") in {"inferred", "inference", "prior", "gap_fill"}:
                continue
            values = a.get(field) or []
            values = values if isinstance(values, list) else [values]
            for j, text in enumerate(values):
                for fact in atoms(text, ctx, a.get("executor"), object_hint=a.get("object")):
                    facts.append(
                        {
                            **fact,
                            "evidence": {
                                "atomic_ref": a["id"],
                                "field": field,
                                "index": j,
                                "quote": text,
                                "at_sec": a.get("start" if phase == "pre" else "end"),
                            },
                            "provenance": "model_extracted_observation",
                        }
                    )
    return facts


def audit(bundle):
    graph = bundle["semantic_graph"]
    rows = []
    for edge in graph.get("relations", []):
        if edge["from"] in {"START", "END"} or edge["to"] in {"START", "END"}:
            continue
        if edge.get("relation") not in {"sequence", "enables", "maintain_until"}:
            continue
        left, right = graph["nodes"][edge["from"]], graph["nodes"][edge["to"]]
        objects = [graph["objects"][o]["label"] for o in right["skill"]["O"] if o in graph["objects"]]
        ctx = context(bundle, objects[0] if objects else None)
        la, ra = node_actions(bundle, edge["from"]), node_actions(bundle, edge["to"])
        source_facts = observed_facts(la, ctx, "post")
        target_facts = observed_facts(ra, ctx, "pre")
        target_time = min((float(a["start"]) for a in ra), default=None)
        actor = right["skill"]["X"].get("subject")
        source_labels = [graph["objects"][o]["label"] for o in left["skill"]["O"] if o in graph["objects"]]
        declared = [
            fact
            for pid in left["skill"]["C_post"]
            for fact in atoms(
                graph["predicates"][pid]["text"],
                ctx,
                left["skill"]["X"].get("subject"),
                requirement=True,
                object_hint=source_labels[0] if source_labels else None,
            )
        ]
        requirements = []
        for pid in right["skill"]["C_pre"]:
            text = graph["predicates"][pid]["text"]
            expected = atoms(text, ctx, actor, requirement=True)
            if not expected:
                requirements.append(
                    {"predicate_ref": pid, "text": text, "status": "unknown_semantics", "evidence": []}
                )
            for required in expected:
                available = [
                    f for f in source_facts if target_time is None or f["evidence"]["at_sec"] <= target_time + 1e-6
                ]
                matching = [f for f in available if entails(f, required)]
                conflicting = [f for f in available if opposite(f, required)]
                future = [f for f in source_facts if entails(f, required) and f not in available]
                already = [f for f in target_facts if entails(f, required)]
                if target_time is None:
                    status, evidence = "target_transition_time_unknown", matching + conflicting
                elif conflicting:
                    status, evidence = "contradicted_observed_effect", conflicting
                elif matching:
                    status, evidence = "observed_support_candidate", matching
                elif future:
                    status, evidence = "future_effect_not_available", future
                elif already:
                    status, evidence = "preexisting_state_not_proof_of_source_cause", already
                elif any(entails(f, required) for f in declared):
                    status, evidence = "contract_only_needs_observation", []
                else:
                    status, evidence = "unknown_effect_entailment", []
                requirements.append(
                    {"predicate_ref": pid, "text": text, "required": required, "status": status, "evidence": evidence}
                )
        statuses = [r["status"] for r in requirements]
        if any(s in {"contradicted_observed_effect", "future_effect_not_available"} for s in statuses):
            status = "conflict"
        elif statuses and all(s == "observed_support_candidate" for s in statuses):
            status = "observed_support_candidate"
        elif any(s == "observed_support_candidate" for s in statuses):
            status = "partial_support"
        else:
            status = "needs_review"
        rows.append(
            {
                "from": edge["from"],
                "to": edge["to"],
                "relation": edge["relation"],
                "basis": edge.get("basis"),
                "status": status,
                "requirements": requirements,
                "target_start_sec": target_time,
                "causal_necessity_verified": False,
            }
        )
    return {
        "schema_version": "task_causal_audit.v1",
        "edges": rows,
        "counts": dict(Counter(r["status"] for r in rows)),
        "causally_verified": False,
        "policy": "Observed effect support, temporal availability and necessary causality are separate claims.",
    }
