#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⑦ 参数净化：把违反"不带具体参数"纪律的表述改写成定性表述。

触发条件：s06 校验发现文本里出现角度/距离/力值等数值参数。
做法：把违规片段交给模型改写，保持原意、只去数值，然后写回并重新校验。
"""

from __future__ import annotations

from ..llm import VLMClient
from .common import ValidationFailure, fill, load_prompt, require_keys


def _validate(payload: object) -> None:
    require_keys(payload, ["rewrites"], "purify")
    if not isinstance(payload["rewrites"], list):  # type: ignore[index]
        raise ValidationFailure("rewrites 必须是数组")


def run(client: VLMClient, ctx: dict, violations: list[dict]) -> dict:
    items = [{"path": v.get("path"), "text": v.get("text"), "match": v.get("match")}
             for v in violations]
    if not items:
        return {"rewrites": []}
    system = load_prompt("s07_purify")
    user = fill(load_prompt("s07_purify", "user"), ITEMS=_render(items))
    payload = client.ask(stage="s07_purify", system=system, user_text=user, validator=_validate)
    rewrites = []
    for r in payload.get("rewrites", []) or []:
        if isinstance(r, dict) and r.get("path") and isinstance(r.get("new_text"), str):
            rewrites.append({"path": str(r["path"]), "new_text": r["new_text"],
                             "note": str(r.get("note") or "")})
    return {"rewrites": rewrites}


def _render(items: list[dict]) -> str:
    lines = ["path | 原文"]
    for it in items:
        lines.append(f"{it['path']} | {it['text']}")
    return "\n".join(lines)
