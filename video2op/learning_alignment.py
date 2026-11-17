"""Preserve learned claims through node splitting/merging, without promoting them to facts."""
from __future__ import annotations

import math
from copy import deepcopy

KINDS = ("C_pre", "C_post", "C_const")


def apply_intent_updates(bundle: dict) -> None:
    """Update every identified hypothesis; legacy scalars only apply to a single candidate."""
    intents = (bundle.get("intents") or {}).get("intents") or []
    sync = bundle.get("sync") or {}
    rows = sync.get("intent_updates") or []
    for index, item in enumerate(intents, 1):
        item.setdefault("id", f"intent_{index}")
    from .intent_hierarchy import items, validate_updates
    children = [s for task in intents for s in task.get("subtasks") or []]
    if children and sync:
        try:
            # Sync reviewed source nodes before deterministic splitting/merging.
            source = bundle.get("task_nodes_source") or bundle.get("task_nodes") or {}
            validate_updates(sync, bundle.get("intents") or {}, source.get("task_nodes") or [],
                             (bundle.get("atomic") or {}).get("atomic_actions") or [])
        except (ValueError, KeyError, TypeError) as exc:
            bundle["intent_alignment"] = {"updated_ids": [], "retained_ids": [i["id"] for i in items(bundle["intents"])],
                                         "issues": [{"reason": "invalid_hierarchical_sync", "detail": str(exc)}],
                                         "graph_revisions": deepcopy(sync.get("revisions") or {})}
            return
    by_id = {i["id"]: i for i in items({"intents": intents})}
    rows = list(rows) + list(sync.get("subtask_updates") or [])
    if not children and not rows and len(intents) == 1 and sync.get("intent_confidence_after") is not None:
        rows = [{"intent_id": intents[0]["id"], "confidence": sync["intent_confidence_after"],
                 "reason": sync.get("confidence_rationale", ""), "basis": "legacy_single_candidate"}]
    applied, issues = [], []
    seen = set()
    for row in rows:
        key = row.get("intent_id")
        if key not in by_id or key in seen:
            issues.append({"intent_id": key, "reason": "unknown_or_duplicate_hypothesis"})
            continue
        seen.add(key)
        try:
            if isinstance(row["confidence"], bool):
                raise ValueError()
            confidence = float(row["confidence"])
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            issues.append({"intent_id": key, "reason": "invalid_confidence"})
            continue
        item = by_id[key]
        item.setdefault("confidence_before_sync", item.get("confidence"))
        item["confidence"] = confidence
        item["confidence_after_sync"] = confidence
        item["sync_checks"] = deepcopy(row.get("checks") or [])
        if "status" in row:
            item["observation_status"] = row["status"]
        item["sync_reason"] = row.get("reason", "")
        item["confidence_kind"] = "model_assessment_not_calibrated_probability"
        applied.append(key)
    # Keep all hypotheses, including low-confidence / contradicted candidates.
    intents.sort(key=lambda x: (-float(x.get("confidence", 0)), x["id"]))
    bundle["intent_alignment"] = {
        "updated_ids": applied, "retained_ids": [x["id"] for x in items({"intents": intents})], "issues": issues,
        "graph_revisions": deepcopy(sync.get("revisions") or {}),
        "revision_policy": "Suggestions require evidence-grounded scope; no fabricated actions.",
    }


def align(bundle: dict, nodes: list[dict]) -> dict:
    source = (bundle.get("task_nodes_source") or {}).get("task_nodes") or []
    source_by_id = {n["id"]: n for n in source}
    analysis = bundle.get("source_analysis") or {}
    rules = analysis.get("rules") or {}
    conditions = analysis.get("conditions") or bundle.get("conditions") or {}
    mapping = {s["id"]: [n["id"] for n in nodes if s["id"] in n.get("source_node_ids", [])]
               for s in source}
    target_by_id = {n["id"]: n for n in nodes}
    # State-goal preparation nodes have no observed action ID. Match only a unique
    # same-operation, same-actor, same-local-object goal; never invent releases.
    for source_node in source:
        sid = source_node["id"]
        if mapping[sid] or source_node.get("atomic_refs"):
            continue
        t = source_node.get("tuple") or {}
        actor = (t.get("X") or {}).get("subject")
        objects = set(t.get("O") or [])
        candidates = [n for n in nodes if n["name"] == source_node["name"]
                      and n["tuple"]["X"]["subject"] == actor
                      and objects and set(n["tuple"].get("O") or []) == objects]
        if len(candidates) == 1:
            mapping[sid] = [candidates[0]["id"]]
            candidates[0]["source_node_ids"].append(sid)
    records = []

    def put(sid, kind, value, claim=None):
        s = source_by_id.get(sid)
        candidates = [target_by_id[nid] for nid in mapping.get(sid, [])]
        srefs = (s or {}).get("atomic_refs") or []
        for n in candidates:
            refs = n.get("atomic_refs") or []
            exact = bool(srefs and refs == srefs)
            at_start = bool(srefs and refs and srefs[0] == refs[0])
            at_end = bool(srefs and refs and srefs[-1] == refs[-1])
            actor = (s or {}).get("tuple", {}).get("X", {})
            source_actor = (actor.get("parts") or [actor.get("subject")])[0] if len(actor.get("parts") or []) <= 1 else actor.get("subject")
            same_actor = source_actor == n["tuple"]["X"]["subject"]
            single_owner = len(candidates) == 1
            scoped = (exact or (same_actor and (kind in ("process", "failure_signals", "C_const")
                      or (kind == "C_pre" and at_start)
                      or (kind in ("C_post", "completion") and at_end))))
            if not srefs:
                scoped = single_owner and same_actor
            scope = "node" if scoped else "source_internal_or_ambiguous"
            record = {"source_node_id": sid, "node_id": n["id"], "kind": kind,
                      "text": str(value), "scope": scope, "status": "learned_candidate",
                      "claim": deepcopy(claim or {})}
            records.append(record)
            n.setdefault("learning_annotations", []).append(deepcopy(record))
            # Evaluators describe desired criteria, never observations or satisfied gates.
            if scoped and kind in ("C_pre", "C_post") and not claim:
                bucket = n["tuple"][kind]
                if value not in bucket:
                    bucket.append(value)
            elif scoped and kind in ("process", "completion", "failure_signals"):
                bucket = n["tuple"]["E"].setdefault(kind, [])
                if value not in bucket:
                    bucket.append(value)
            elif scoped and kind == "C_const":
                # Existing event-scoped grip requirements are maintained by arm_hand.
                from .arm_hand import grip_constraint
                if not any(grip_constraint(str(value), hand, "")
                           for hand in ("左手", "右手")):
                    bucket = n["tuple"]["C_const"]
                    if value not in bucket:
                        bucket.append(value)
        if not candidates:
            hypothesis = bool(s and s.get("inferred") and not srefs)
            records.append({"source_node_id": sid, "node_id": None, "kind": kind,
                            "text": str(value), "scope": "uninstantiated_hypothesis" if hypothesis else "unmapped",
                            "status": "hypothesis_not_inserted" if hypothesis else "needs_review",
                            "claim": deepcopy(claim or {})})

    for s in source:
        t = s.get("tuple") or {}
        for kind in KINDS:
            for value in t.get(kind) or []:
                put(s["id"], kind, value)
        for realization in t.get("R") or []:
            put(s["id"], "realization", realization.get("name", ""), {"candidate": realization})
        for kind in ("process", "completion", "failure_signals"):
            for value in (t.get("E") or {}).get(kind) or []:
                put(s["id"], kind, value)
    for item in conditions.get("condition_learning") or []:
        for kind in ("C_pre", "C_post"):
            for entry in item.get(kind + "_learning") or []:
                claim = deepcopy(entry)
                claim["evidence_kind"] = "model_counterfactual_review"
                claim["empirically_verified"] = False
                put(item["node_id"], kind, entry.get("condition", ""), claim)
    for ev in rules.get("evaluators") or []:
        for kind in ("process", "completion", "failure_signals"):
            for value in ev.get(kind) or []:
                put(ev["node_id"], kind, value, {"origin": "s05_rules"})
    for ct in rules.get("constraints") or []:
        for sid in ct.get("applies_to") or []:
            put(sid, "C_const", ct.get("statement", ""), ct)
    for n in nodes:
        t = n["tuple"]
        for kind in ("C_pre", "C_post", "C_const"):
            t[kind] = list(dict.fromkeys(t.get(kind) or []))
        for kind in ("process", "completion", "failure_signals"):
            if kind in t["E"]:
                t["E"][kind] = list(dict.fromkeys(t["E"][kind]))
    return {"source_to_final": mapping, "records": records,
            "unmapped_count": sum(r["scope"] == "unmapped" for r in records),
            "uninstantiated_hypothesis_count": sum(r["scope"] == "uninstantiated_hypothesis" for r in records),
            "policy": "Retain source scope; model judgments never constitute observed success."}
