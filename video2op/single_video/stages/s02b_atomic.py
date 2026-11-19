#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 2b-1 执行器级原子动作提取（窗口化视频调用）。

设计要点：
  1. 2a 的意图结果只用来生成"重点关注的部位"提示，不给动作剧本；
  2. 每个窗口配一份客观运动证据（帧差分析）帮助时间校准；
  3. 短视频整段分析，长视频切窗（见 media.window_plan）。
"""

from __future__ import annotations

from pathlib import Path

from ... import media, sampling
from ...abstraction import normalize_overall_action, validate_semantics
from ...ignored_parts import clean_text
from ...llm import VLMClient
from ...vocab import BODY_PARTS, IGNORED_PARTS
from .common import (
    ValidationFailure,
    clamp_time,
    enforce_active_force,
    fill,
    intents_table,
    load_prompt,
    normalize_force,
    normalize_part,
    parts_functions,
    require_keys,
)


def _validate(payload: object) -> None:
    validate_semantics(payload)
    require_keys(payload, ["atomic_actions"], "atomic")
    acts = payload["atomic_actions"]  # type: ignore[index]
    if not isinstance(acts, list):
        raise ValidationFailure("atomic_actions 必须是数组")
    from ...arm_hand import function_issues
    issues = function_issues(acts)
    if issues:
        raise ValidationFailure(issues[0]["message"] + "：" + str(issues[0]["action"]))
    for i, a in enumerate(acts):
        require_keys(a, ["executor", "action", "mode", "start", "end"], f"actions[{i}]")
        if not isinstance(a["executor"], str) or normalize_part(a["executor"]) not in BODY_PARTS:
            raise ValidationFailure(f"actions[{i}] 必须只绑定一个明确执行器，双手/双臂需拆成并行操作")
        if str(a["mode"]).strip().lower() not in ("transition", "motion"):
            raise ValidationFailure(f"actions[{i}] mode 非法：{a['mode']}")
        try:
            s, e = float(a["start"]), float(a["end"])
        except (TypeError, ValueError) as exc:
            raise ValidationFailure(f"actions[{i}] 时间非数值") from exc
        if e < s - 1e-6:
            raise ValidationFailure(f"actions[{i}] end < start")
        for key in ("world_before", "world_after"):
            if not isinstance(a.get(key), list) or not all(isinstance(s, str) for s in a[key]):
                raise ValidationFailure(f"actions[{i}] {key} 必须是状态字符串数组，不可见时用 []")


def _validate_upper_limb_coverage(payload: dict, visible_parts: list[str]) -> None:
    """A visible arm must not vanish into a hand-only transport summary."""
    visible = {normalize_part(p) for p in visible_parts}
    actions = payload.get("atomic_actions") or []
    actors = {normalize_part(a.get("executor", "")) for a in actions}
    unclear = str(payload.get("missing_or_unclear") or "")
    for hand, arm in (("左手", "左臂"), ("右手", "右臂")):
        if arm not in visible or arm in actors:
            continue
        transport = any(
            normalize_part(a.get("executor", "")) == hand
            and a.get("mode") == "motion"
            and any(w in str(a.get("action") or "") for w in
                    ("移出", "搬运", "运送", "伸入", "伸出", "抬起", "举起", "向上移动"))
            for a in actions)
        explained = (arm in unclear or arm.replace("臂", "手臂") in unclear) and any(
            w in unclear for w in ("遮挡", "不可见", "看不清", "无法", "不能确认"))
        if transport and not explained:
            raise ValidationFailure(
                f"{arm}在视角观察中可见，但搬移动作全归给{hand}；"
                "请分别记录臂运动与抓握状态变化，持续抓握写约束；无法确认请说明")


def _normalize_window(payload: dict, local_dur: float) -> dict:
    """归一化窗口内动作：时间裁剪到窗口范围、id 补全、部位标准化。"""

    def clean(value: object) -> str:
        """头部内容净化（文本形态）；整句都是头部内容时保留原文，交给下游发现。"""
        text, n = clean_text(value)
        return text if (not n or text) else str(value or "")

    def clean_list(value: object) -> list:
        """世界状态逐条净化：整条都是头部内容的直接丢掉。"""
        out: list = []
        for v in value if isinstance(value, list) else []:
            text, n = clean_text(v)
            if n and not text:
                continue
            out.append(text if n else v)
        return out

    acts = []
    for i, a in enumerate(payload.get("atomic_actions", []) or []):
        if not isinstance(a, dict):
            continue
        a = dict(a)
        from ...semantic import is_hold
        if is_hold(a):
            continue
        a["id"] = int(a.get("id") or (i + 1)) if str(a.get("id") or (i + 1)).isdigit() else i + 1
        a["executor"] = normalize_part(a.get("executor", ""))
        if a["executor"] in IGNORED_PARTS:
            continue  # 头不参与操作：不写进动作表（引用它的时序关系随后按剩余 id 过滤）
        a["mode"] = str(a.get("mode", "motion")).strip().lower()
        if a["mode"] not in ("transition", "motion"):
            a["mode"] = "motion"
        a["start"] = clamp_time(a.get("start"), 0.0, local_dur, 0.0)
        a["end"] = clamp_time(a.get("end"), 0.0, local_dur, a["start"])
        if a["end"] < a["start"]:
            a["start"], a["end"] = a["end"], a["start"]
        a["exerts_force"] = bool(a.get("exerts_force"))
        enforce_active_force(a)
        normalize_force(a)
        a["action"] = clean(str(a.get("action", "")).strip())
        a["state_before"] = clean(a.get("state_before"))
        a["state_after"] = clean(a.get("state_after"))
        a["operation_intent"] = clean(a.get("operation_intent"))
        a["world_before"] = clean_list(a.get("world_before"))
        a["world_after"] = clean_list(a.get("world_after"))
        a["object"] = a.get("object") or None
        normalize_overall_action(a)
        try:
            a["confidence"] = round(max(0.0, min(1.0, float(a.get("confidence", 0.6)))), 2)
        except (TypeError, ValueError):
            a["confidence"] = 0.6
        acts.append(a)
    # 关系：只保留两端都存在的
    ids = {a["id"] for a in acts}
    rels = []
    for r in payload.get("temporal_relations", []) or []:
        if not isinstance(r, dict):
            continue
        try:
            f, t = int(r.get("from")), int(r.get("to"))
        except (TypeError, ValueError):
            continue
        if f in ids and t in ids and f != t:
            rels.append({"relation": str(r.get("relation", "")).strip().lower(),
                         "from": f, "to": t, "note": clean(str(r.get("note") or ""))})
    payload["atomic_actions"] = acts
    payload["temporal_relations"] = rels
    return payload


def run(client: VLMClient, ctx: dict) -> dict:
    video: Path = ctx["video"]
    meta = ctx["meta"]
    profile = ctx["profile"]
    # Independent observation lane: no task hypothesis or intended actor sequence leaks in.
    intents = []
    windows = media.window_plan(meta["duration"])
    hints = "按视角与画面检查所有可见操作部位；此观察分支不接收任务意图提示。"
    funcs = parts_functions()
    system = load_prompt("s02b_atomic")

    out_windows = []
    for idx, (start, dur) in enumerate(windows, 1):
        clip = media.make_clip(video, start, dur, tag="atomic")
        user = fill(
            load_prompt("s02b_atomic", "user"),
            WIN_START=f"{start:.1f}", WIN_END=f"{start + dur:.1f}", WIN_DUR=f"{dur:.1f}",
            PART_HINTS=hints,
            INTENTS=intents_table(intents),
            MOTION_HINTS=media.motion_hint_text(profile, start, dur),
            PART_FUNCTIONS=funcs,
        )
        frames = sampling.frames_for_window(ctx.get("sampling") or {}, start, dur)
        if frames:
            user += ("\n附带关键状态帧：图片标记为源视频全局时间，视频和动作start/end为片段局部时间。"
                     "请对照动作前后手形与物体支撑状态；运动候选不是动作事实。"
                     "不可见请明确说明，不要按前置条件补造打开、抓握或释放。")
        def validate(payload: object) -> None:
            _validate(payload)
            _validate_upper_limb_coverage(
                payload, (ctx.get("viewpoint") or {}).get("visible_parts_hint") or [])

        payload = client.ask(
            stage=f"s02b_atomic_w{idx:02d}", system=system, user_text=user,
            video=clip, video_id=f"{ctx['video_id']}#w{start:.1f}-{dur:.1f}",
            validator=validate, images=frames,
        )
        raw_count = len([a for a in payload.get("atomic_actions") or [] if isinstance(a, dict)])
        payload = _normalize_window(payload, dur)
        payload["input_frame_ids"] = [f["frame_id"] for f in frames]
        # These were sent to the model; input availability is not proof of an action.
        for action in payload["atomic_actions"]:
            action["input_frame_ids"] = payload["input_frame_ids"]
        payload["window"] = {"index": idx, "start": start, "duration": dur}
        out_windows.append(payload)
        ignored = f"（忽略 {raw_count - len(payload['atomic_actions'])} 条不参与操作的部位动作）" \
            if raw_count > len(payload["atomic_actions"]) else ""
        print(f"      窗口 {idx}/{len(windows)} [{start:.1f}-{start + dur:.1f}s] "
              f"动作 {len(payload['atomic_actions'])} 条{ignored}")
    return {"windows": out_windows, "window_plan": windows}
