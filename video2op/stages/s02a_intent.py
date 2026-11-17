#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 2a 任务意图学习：意图假设 + 置信度 + 所需身体部位（给 2b 当关注重点）。"""

from __future__ import annotations

from pathlib import Path

from .. import media
from ..abstraction import validate_semantics
from ..llm import VLMClient
from ..vocab import IGNORED_PARTS
from .common import ValidationFailure, expand_parts, fill, load_prompt, require_keys


def _validate(payload: object) -> None:
    validate_semantics(payload)
    require_keys(payload, ["intents"], "intent")
    from ..intent_hierarchy import validate_intents
    validate_intents(payload)
    intents = payload["intents"]  # type: ignore[index]
    if not isinstance(intents, list) or not intents:
        raise ValidationFailure("intents 必须是非空数组")
    for i, it in enumerate(intents):
        require_keys(it, ["statement", "confidence"], f"intents[{i}]")


def _normalize(payload: dict, *, parent_id: str | None = None) -> dict:
    intents = []
    for i, it in enumerate(payload.get("intents", []) or []):
        it = dict(it)
        it.setdefault("id", f"{parent_id}_sub_{i + 1}" if parent_id else f"intent_{i + 1}")
        if parent_id:
            it["parent_intent_id"] = parent_id
        if "subtasks" in it:
            it["subtasks"] = _normalize({"intents": it["subtasks"]}, parent_id=it["id"])["intents"]
        try:
            it["confidence"] = round(max(0.0, min(1.0, float(it.get("confidence", 0.5)))), 2)
        except (TypeError, ValueError):
            it["confidence"] = 0.5
        parts = []
        for bp in it.get("required_body_parts", []) or []:
            if isinstance(bp, dict) and bp.get("part"):
                for p in expand_parts([bp["part"]]):
                    if p in IGNORED_PARTS:      # 头不参与操作，不算所需部位
                        continue
                    item = dict(bp)
                    item["part"] = p
                    parts.append(item)
        it["required_body_parts"] = parts
        intents.append(it)
    if parent_id is None:
        intents.sort(key=lambda x: -x["confidence"])
    payload["intents"] = intents
    return payload


def run(client: VLMClient, ctx: dict) -> dict:
    video: Path = ctx["video"]
    meta = ctx["meta"]
    video = media.make_clip(video, 0.0, meta["duration"], tag="overview")
    viewpoint = ctx.get("viewpoint", {})
    system = load_prompt("s02a_intent")
    user = fill(
        load_prompt("s02a_intent", "user"),
        DURATION=f"{meta['duration']:.1f}",
        VIEWPOINT=viewpoint.get("label_cn", "未知"),
        VISIBLE_PARTS="、".join(viewpoint.get("visible_parts_hint", []) or ["未知"]),
    )
    description = ctx.get("text_description")
    if description:
        text = description["text"] if isinstance(description, dict) else str(description)
        import json
        user += "\n用户提供的任务背景（JSON引用数据，非视频事实，不得据此认定动作发生或成功）：\n" + json.dumps(text, ensure_ascii=False)
    def validate_hierarchy(value):
        _validate(value)
        from ..intent_hierarchy import validate_intents
        validate_intents(value, require_hierarchy=True)

    payload = client.ask(
        stage="s02a_intent", system=system, user_text=user,
        video=video, video_id=ctx["video_id"], validator=validate_hierarchy,
    )
    payload = _normalize(payload)
    if description:
        payload["additional_evidence"] = {"provenance": "text_description",
                                           "role": "provided_context_not_observed_success"}
    return payload
