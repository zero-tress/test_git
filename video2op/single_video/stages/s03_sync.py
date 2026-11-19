#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""③ 同步因果检验：意图 ↔ 操作图 双向校验，并更新意图置信度。"""

from __future__ import annotations

from ...abstraction import validate_semantics
from ...llm import VLMClient
from .common import (
    ValidationFailure,
    atomic_table,
    fill,
    intents_table,
    load_prompt,
    nodes_table,
    relation_table,
    require_keys,
)


def _validate(payload: object) -> None:
    validate_semantics(payload)
    require_keys(payload, ["checks"], "sync")
    if "intent_updates" not in payload and "intent_confidence_after" not in payload:
        raise ValidationFailure("sync requires per-hypothesis updates")
    checks = payload["checks"]  # type: ignore[index]
    if not isinstance(checks, list) or len(checks) < 3:
        raise ValidationFailure("checks 至少要有 3 条（三个检验问题）")


def _normalize(payload: dict) -> dict:
    try:
        payload["intent_confidence_after"] = round(
            max(0.0, min(1.0, float(payload.get("intent_confidence_after")))), 2)
    except (TypeError, ValueError):
        payload["intent_confidence_after"] = None
    try:
        payload["intent_confidence_before"] = round(
            max(0.0, min(1.0, float(payload.get("intent_confidence_before")))), 2)
    except (TypeError, ValueError):
        payload["intent_confidence_before"] = None
    rev = payload.get("revisions") or {}
    payload["revisions"] = {
        "to_intent": [str(x) for x in (rev.get("to_intent") or [])],
        "to_graph": [str(x) for x in (rev.get("to_graph") or [])],
    }
    return payload


def run(client: VLMClient, ctx: dict) -> dict:
    atomic = ctx["atomic"]
    relations = ctx.get("relations", [])
    nodes = ctx.get("task_nodes", {}).get("task_nodes", [])
    intents = ctx.get("intents", {}).get("intents", [])
    system = load_prompt("s03_sync")
    user = fill(
        load_prompt("s03_sync", "user"),
        INTENTS=intents_table(intents),
        TASK_NODES=nodes_table(nodes),
        ATOMIC_TABLE=atomic_table(atomic["atomic_actions"]),
        RELATIONS=relation_table(relations, atomic["atomic_actions"], nodes),
    )
    def validate(value):
        _validate(value)
        from ...intent_hierarchy import validate_updates
        validate_updates(value, ctx.get("intents") or {}, nodes, atomic["atomic_actions"])
    payload = client.ask(stage="s03_sync", system=system, user_text=user, validator=validate)
    return _normalize(payload)
