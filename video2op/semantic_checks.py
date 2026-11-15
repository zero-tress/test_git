"""Evidence and condition checks shared by the semantic validation entry point."""
from .temporal_learning import validate_graph

def causal_consistency(bundle):
    actions = {a["id"]: a for a in bundle.get("atomic", {}).get("atomic_actions", [])}
    issues = []
    invalid = []
    for node in bundle.get("operations", {}).get("nodes", []):
        for ev in node.get("effect_evidence", []):
            refs = ev.get("atomic_refs", [])
            if ev.get("status") == "observed" and not refs:
                issues.append({"node": node["id"], "reason": "observed_state_goal_needs_grounded_state_reference"})
            for ref in refs:
                if ref not in actions:
                    invalid.append({"node": node["id"], "reason": "unknown_effect_action", "atomic_ref": ref})
                elif ev.get("status") == "observed" and actions[ref].get("inferred"):
                    invalid.append({"node": node["id"], "reason": "inferred_action_cannot_prove_effect", "atomic_ref": ref})
    from .task_causality import audit
    edge_audit = audit(bundle)
    issues += [{"from": r["from"], "to": r["to"], "reason": r["status"]}
               for r in edge_audit["edges"] if r["status"] != "observed_support_candidate"]
    return {"id": "causal_consistency", "name": "效果来源与任务图因果桥梁",
            "status": "fail" if invalid else "warn" if issues else "pass", "detail": invalid + issues, "edge_audit": edge_audit}

def pre_post_consistency(bundle):
    graph = bundle["semantic_graph"]
    missing = []
    for edge in graph.get("relations", []):
        if edge.get("basis") != "required_dependency" or edge["from"] in {"START", "END"} or edge["to"] in {"START", "END"}:
            continue
        left = graph["nodes"][edge["from"]]["skill"]
        right = graph["nodes"][edge["to"]]["skill"]
        if edge["relation"] == "sequence" and not set(left["C_post"]) & set(right["C_pre"]):
            missing.append({"from": edge["from"], "to": edge["to"], "reason": "required_order_has_no_shared_effect_precondition",
                            "status": "needs_predicate_entailment_review"})
    return {"id": "pre_post_consistency", "name": "前后置条件衔接与待证义蕴",
            "status": "warn" if missing else "pass", "detail": missing}

def temporal_consistency(bundle):
    errors = validate_graph(bundle["semantic_graph"])
    pending = []
    for p in bundle.get("temporal_knowledge", {}).get("patterns", []):
        if p.get("pattern") == "Branch" and any(not a.get("when") for a in p.get("alternatives", [])):
            pending.append({"pattern": p["id"], "reason": "branch_guard_missing"})
        if p.get("status") == "needs_review":
            pending.append({"pattern": p["id"], "issues": p.get("issues", [])})
    return {"id": "temporal_consistency", "name": "时序无环、互斥关系与显式守卫",
            "status": "fail" if errors else "warn" if pending else "pass", "detail": errors + pending}
