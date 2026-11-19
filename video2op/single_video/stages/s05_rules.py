#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⑤ 语义层规则学习：时序结构（Sequence/Parallel/Alternation）、语义约束、评价器。"""

from __future__ import annotations

from ...abstraction import validate_semantics
from ...llm import VLMClient
from .common import ValidationFailure, atomic_table, fill, intents_table, load_prompt, relation_table, require_keys

PATTERNS = {"Sequence", "Parallel", "Alternation", "Branch", "Synchronization"}
LEVELS = {"task", "action", "executor"}
CTYPES = {"空间约束", "接触约束", "支撑约束", "顺序约束", "保持约束", "力需求约束", "安全约束"}


def _validate(payload: object) -> None:
    validate_semantics(payload)
    require_keys(payload, ["temporal_structures", "constraints", "evaluators"], "rules")
    for row in payload["temporal_structures"]:
        if row.get("pattern") not in PATTERNS:
            raise ValidationFailure("未登记的时序关系，不能默认为并行")
    for key in ("temporal_structures", "constraints", "evaluators"):
        if not isinstance(payload[key], list):  # type: ignore[index]
            raise ValidationFailure(f"{key} 必须是数组")


def _normalize(payload: dict) -> dict:
    ts = []
    for i, x in enumerate(payload.get("temporal_structures", []) or []):
        if not isinstance(x, dict):
            continue
        p = str(x.get("pattern") or "").strip()
        if p not in PATTERNS:
            raise ValidationFailure("unknown temporal pattern")
        lv = str(x.get("level") or "").strip()
        if lv not in LEVELS:
            lv = "action"
        ts.append({**x, "id": str(x.get("id") or f"ts_{i + 1}"), "level": lv, "pattern": p,
                   "members": [str(m) for m in (x.get("members") or [])],
                   "statement": str(x.get("statement") or ""),
                   "evidence": str(x.get("evidence") or "")})
    ct = []
    for i, x in enumerate(payload.get("constraints", []) or []):
        if not isinstance(x, dict):
            continue
        t = str(x.get("type") or "").strip()
        if t not in CTYPES:
            t = "安全约束"
        ct.append({"id": str(x.get("id") or f"ct_{i + 1}"), "type": t,
                   "statement": str(x.get("statement") or ""),
                   "applies_to": [str(a) for a in (x.get("applies_to") or [])],
                   "reason": str(x.get("reason") or ""),
                   "violation_consequence": str(x.get("violation_consequence") or ""),
                   "confidence": float(x.get("confidence") or 0.6)})
    ev = []
    for x in payload.get("evaluators", []) or []:
        if not isinstance(x, dict):
            continue
        ev.append({"node_id": str(x.get("node_id") or ""),
                   "process": [str(s) for s in (x.get("process") or [])],
                   "completion": [str(s) for s in (x.get("completion") or [])],
                   "failure_signals": [str(s) for s in (x.get("failure_signals") or [])]})
    return {"temporal_structures": ts, "constraints": ct, "evaluators": ev}


def run(client: VLMClient, ctx: dict) -> dict:
    atomic = ctx["atomic"]
    relations = ctx.get("relations", [])
    nodes = ctx.get("task_nodes", {}).get("task_nodes", [])
    intents = ctx.get("intents", {}).get("intents", [])
    conditions = ctx.get("conditions", {})
    system = load_prompt("s05_rules")
    user = fill(
        load_prompt("s05_rules", "user"),
        INTENTS=intents_table(intents),
        TASK_NODES="\n".join(f"{n['id']} | {n.get('name')} | {n['tuple'].get('E')}" for n in nodes) or "（空）",
        ATOMIC_TABLE=atomic_table(atomic["atomic_actions"]),
        RELATIONS=relation_table(relations, atomic["atomic_actions"]),
        CONDITIONS=str(conditions.get("effective_conditions_summary") or []),
    )
    payload = client.ask(stage="s05_rules", system=system, user_text=user, validator=_validate)
    return _normalize(payload)
