"""Conservative state evidence. Similar wording proposes a link, never proves it.

Free-text paraphrases remain unknown until a reviewer or predicate grounding layer
confirms them. Generated/inherited states and intended actions are not observations.
"""
from __future__ import annotations

from .operations import _norm


def matches(expected: str, observed: str) -> bool:
    return bool(_norm(expected)) and _norm(expected) == _norm(observed)


def observed_state(action: dict, key: str = "state_after") -> str:
    if action.get("media_coverage_status") == "outside_decoded_coverage" or action.get("inferred") or action.get(f"{key}_from", "observed") != "observed":
        return ""
    return str(action.get(key) or "")


def observed_states(action: dict, key: str = "state_after") -> list[str]:
    if action.get("media_coverage_status") == "outside_decoded_coverage":
        return []
    world_key = "world_before" if key == "state_before" else "world_after"
    world = action.get(world_key) or []
    if (action.get("inferred") or action.get(world_key + "_from", "observed") != "observed"
            or not isinstance(world, list)):
        world = []
    return [s for s in [observed_state(action, key), *world] if isinstance(s, str) and s]


def support(condition: str, op: dict, atomic: list[dict]) -> list[dict]:
    refs = set(op.get("atomic_refs") or [])
    candidates = [a for a in atomic if a.get("id") in refs
            and float(a.get("end", 0)) <= float(op.get("end", 0)) + 0.05
            and any(matches(condition, s) for s in observed_states(a))]
    # An earlier success cannot prove completion if a later state for that same
    # executor differs. Without state fluents we conservatively request review.
    return [a for a in candidates if not any(
        b.get("id") in refs and b.get("executor") == a.get("executor")
        and float(a.get("end", 0)) < float(b.get("end", 0)) <= float(op.get("end", 0)) + 0.05
        and observed_states(b) and not any(matches(condition, s) for s in observed_states(b))
        for b in atomic)]


def audit_effects(bundle: dict, reviewed=None) -> dict:
    """Add verification metadata without treating model-observed as reviewed."""
    import hashlib
    from .review import validate_reviewed
    from .knowledge import extract, video_identity
    uid, _ = video_identity(bundle)
    records = validate_reviewed(reviewed or [], extract(bundle, "<evidence-audit>")["instances"])
    bundle["effect_review_records"] = records
    reviewed_evidence = [e for r in records for e in r.get("outcome_evidence", [])]
    actions = {a["id"]: a for a in bundle.get("atomic", {}).get("atomic_actions", [])}
    report = []
    for node in bundle.get("operations", {}).get("nodes", []):
        for j, ev in enumerate(node.get("effect_evidence", [])):
            condition = ev.get("condition", "")
            refs = ev.get("atomic_refs", [])
            confirmed = [e for e in reviewed_evidence if e.get("atomic_ref") in refs
                         and matches(condition, e.get("quote", ""))]
            impossible = bool(refs) and all(
                r not in actions or actions[r].get("inferred")
                or actions[r].get("media_coverage_status") == "outside_decoded_coverage" for r in refs)
            status = "verified" if confirmed else "unverifiable" if impossible else "unverified"
            evidence_id = "effect_" + hashlib.sha256(
                (uid + str(node["id"]) + str(j) + condition).encode()).hexdigest()[:20]
            basis = ("scoped_reviewed_state_quote" if confirmed else
                     "no_observable_source_in_current_actions" if impossible else
                     "state_goal_needs_grounding" if not refs else "model_observation_requires_review")
            ev.update(evidence_id=evidence_id, verification_status=status, verification_basis=basis)
            report.append({"evidence_id": evidence_id, "node_id": node["id"], "condition": condition,
                           "observation_status": ev.get("status"), "verification_status": status,
                           "verification_basis": basis, "atomic_refs": refs, "video_sha256": uid})
    return {"schema_version": "effect_evidence_audit.v1", "records": report,
            "policy": "Observation status, review status and causal status are distinct."}
