#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 视角判别：第一人称 / 第三人称 / 其他。"""

from __future__ import annotations

from pathlib import Path

from ... import media, sampling
from ...llm import VLMClient
from .common import ValidationFailure, fill, load_prompt, require_keys

VALID = {"first_person", "third_person", "other"}


def _validate(payload: object) -> None:
    require_keys(payload, ["viewpoint", "confidence"], "viewpoint")
    vp = payload["viewpoint"]  # type: ignore[index]
    if vp not in VALID:
        # 容忍中文写法
        mapping = {"第一人称": "first_person", "第三人称": "third_person",
                   "其他": "other", "first": "first_person", "third": "third_person"}
        if str(vp).strip() in mapping:
            payload["viewpoint"] = mapping[str(vp).strip()]  # type: ignore[index]
        else:
            raise ValidationFailure(f"viewpoint 取值非法：{vp}")


def run(client: VLMClient, ctx: dict) -> dict:
    video: Path = ctx["video"]
    meta = ctx["meta"]
    video = media.make_clip(video, 0.0, meta["duration"], tag="overview")
    system = load_prompt("s01_viewpoint")
    user = fill(load_prompt("s01_viewpoint", "user"), DURATION=f"{meta['duration']:.1f}")
    payload = client.ask(
        stage="s01_viewpoint", system=system, user_text=user,
        video=video, video_id=ctx["video_id"], validator=_validate,
        images=sampling.frames_for_window(ctx.get("sampling") or {}, 0, meta["duration"], maximum=4),
    )
    payload["label_cn"] = {"first_person": "第一人称", "third_person": "第三人称",
                           "other": "其他视角"}.get(payload.get("viewpoint", ""), "未知")
    return payload
