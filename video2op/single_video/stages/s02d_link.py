#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 2b-4 动作链归属与缺失动作推理补全。

输入：意图 + 任务节点 + 原子动作表。
输出：原子动作 → 节点归属（links）、缺失动作（inferred，带推理理由）。
缺失动作会以 inferred=true 追加进原子动作表，供后续校验与渲染使用。
"""

from __future__ import annotations

from ...abstraction import normalize_overall_action, validate_semantics
from ...llm import VLMClient
from ...vocab import IGNORED_PARTS
from .common import (
    ValidationFailure,
    atomic_table,
    clamp_time,
    enforce_active_force,
    fill,
    intents_table,
    load_prompt,
    normalize_force,
    normalize_part,
    relation_table,
    require_keys,
)


def _validate(payload: object) -> None:
    validate_semantics(payload)
    require_keys(payload, ["links", "missing_actions"], "link")
    if not isinstance(payload["links"], list) or not isinstance(payload["missing_actions"], list):  # type: ignore[index]
        raise ValidationFailure("links / missing_actions 必须是数组")
    from ...arm_hand import function_issues
    issues = function_issues(payload["missing_actions"])
    if issues:
        raise ValidationFailure(issues[0]["message"] + "具体动作：" + str(issues[0]["action"]) + "；功能问题：" + issues[0]["kind"])
    from ...semantic import is_hold
    if any(str(m.get("mode") or "").lower() not in ("transition", "motion")
           for m in payload["missing_actions"]):
        raise ValidationFailure("补全动作只允许 transition / motion")
    if any(is_hold(m) for m in payload["missing_actions"]):
        raise ValidationFailure("不允许补保持动作；请将持续状态写入 C_const")


def _normalize(payload: dict, atomic: list[dict], duration: float) -> dict:
    valid_ids = {a["id"] for a in atomic}
    links = []
    for item in payload.get("links", []) or []:
        if not isinstance(item, dict):
            continue
        ids = [int(i) for i in (item.get("atomic_ids") or []) if str(i).isdigit()]
        links.append({
            "node_id": str(item.get("node_id") or ""),
            "atomic_ids": [i for i in ids if i in valid_ids],
            "chain_comment": str(item.get("chain_comment") or ""),
        })
    missing = []
    next_id = max(valid_ids) if valid_ids else 0
    for m in payload.get("missing_actions", []) or []:
        if not isinstance(m, dict):
            continue
        if normalize_part(m.get("executor", "")) in IGNORED_PARTS:
            continue  # 头不参与操作：模型补的头部动作一律不收
        from ...semantic import is_hold
        if is_hold(m):
            continue
        next_id += 1
        s = clamp_time(m.get("start"), 0.0, duration, 0.0)
        e = clamp_time(m.get("end"), 0.0, duration, s)
        if e < s:
            s, e = e, s
        mode = str(m.get("mode") or "transition").strip().lower()
        if mode not in ("transition", "motion"):
            mode = "transition"
        missing.append({
            "id": next_id,
            "executor": normalize_part(m.get("executor", "")),
            "action": str(m.get("action") or "").strip(),
            "mode": mode,
            "start": s, "end": e,
            "exerts_force": bool(m.get("exerts_force")),
            "force_role": m.get("force_role"),
            "object": m.get("object") or None,
            "state_before": m.get("state_before") or None,
            "state_after": m.get("state_after") or None,
            "until": m.get("until"),
            "inferred": True,
            "inference_reason": str(m.get("reason") or ""),
            "confidence": float(m.get("confidence") or 0.6),
            "node_id": str(m.get("node_id") or ""),
        })
        normalize_overall_action(missing[-1])
        enforce_active_force(missing[-1])
        normalize_force(missing[-1])
    payload["links"] = links
    payload["missing_actions"] = missing
    return payload


def run(client: VLMClient, ctx: dict) -> dict:
    atomic = ctx["atomic"]
    relations = ctx.get("relations", [])
    nodes = ctx.get("task_nodes", {}).get("task_nodes", [])
    intents = ctx.get("intents", {}).get("intents", [])
    duration = ctx["meta"]["duration"]

    system = load_prompt("s02d_link") + "\n缺失动作允许为空。仅为动作建立归属不要求新增动作。推/拉过程中接触目标不能证明发生抓握，不能补出稳定抓握、手型调整等未观察到的动作。无法明确到已登记单主体操作的推理建议保留在chain_comment中，不强行编入missing_actions。"
    user = fill(
        load_prompt("s02d_link", "user"),
        INTENTS=intents_table(intents),
        TASK_NODES="\n".join(
            f"{n['id']} | {n.get('name')} | 部位={n['tuple'].get('X', {}).get('parts', [])} | "
            f"时间={n.get('time_range')} | 对象={n['tuple'].get('O')}" for n in nodes) or "（空）",
        ATOMIC_TABLE=atomic_table(atomic["atomic_actions"]),
        RELATIONS=relation_table(relations, atomic["atomic_actions"]),
    )
    payload = client.ask(stage="s02d_link", system=system, user_text=user, validator=_validate)
    raw = len([m for m in payload.get("missing_actions") or [] if isinstance(m, dict)])
    payload = _normalize(payload, atomic["atomic_actions"], duration)
    dropped = raw - len(payload["missing_actions"])
    if dropped:
        print(f"    [忽略] {dropped} 条补全动作落在不参与操作的部位"
              f"（{'、'.join(sorted(IGNORED_PARTS))}）")
    return payload
