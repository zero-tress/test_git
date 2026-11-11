#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""③ 同步因果检验：意图 ↔ 操作图 双向校验，并更新意图置信度。"""

from __future__ import annotations

from ..abstraction import validate_semantics
from ..llm import VLMClient
from .common import ValidationFailure, atomic_table, fill, intents_table, load_prompt, relation_table, require_keys


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
            max(0.0, min(1.0, float(payload.get("intent_confidence_after", 0.5)))), 2)
    except (TypeError, ValueError):
        payload["intent_confidence_after"] = None
    try:
        payload["intent_confidence_before"] = round(
            max(0.0, min(1.0, float(payload.get("intent_confidence_before", 0.5)))), 2)
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
        TASK_NODES="\n".join(
            f"{n['id']} | {n.get('name')} | X={n['tuple'].get('X')} | O={n['tuple'].get('O')} | "
            f"C_pre={n['tuple'].get('C_pre')} | C_post={n['tuple'].get('C_post')}" for n in nodes) or "（空）",
        ATOMIC_TABLE=atomic_table(atomic["atomic_actions"]),
        RELATIONS=relation_table(relations, atomic["atomic_actions"]),
    )
    def validate(value):
        _validate(value)
        updates = value.get("intent_updates")
        if updates is not None:
            import math
            expected = {i["id"] for i in intents}
            seen = set()
            for row in updates:
                key = row.get("intent_id")
                if key not in expected or key in seen:
                    raise ValidationFailure("意图更新引用未知或重复候选")
                seen.add(key)
                checks = row.get("checks")
                if not isinstance(checks, list) or len(checks) != 3:
                    raise ValidationFailure("每个候选需要三项校验")
                for check in checks:
                    if check.get("verdict") not in {"yes", "partial", "no", "unknown"}:
                        raise ValidationFailure("非法校验判定")
                    if any(r not in {a["id"] for a in atomic["atomic_actions"]} for r in check.get("evidence_refs", [])):
                        raise ValidationFailure("校验引用不存在的动作")
                score = row.get("confidence")
                if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValidationFailure("非法置信度")
            if seen != expected:
                raise ValidationFailure("每个意图候选必须分别校验，不能丢弃低置信度候选")
        elif len(intents) > 1:
            raise ValidationFailure("多个意图不能使用单个更新值")
    payload = client.ask(stage="s03_sync", system=system, user_text=user, validator=validate)
    return _normalize(payload)
