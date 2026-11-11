#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨窗口合并的确定性测试（不经模型）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op.stages import s02b_merge as m


def _win(index: int, start: float, dur: float, actions: list[dict], rels: list[dict] | None = None):
    return {"window": {"index": index, "start": start, "duration": dur},
            "atomic_actions": actions, "temporal_relations": rels or [],
            "inactive_parts": []}


def _act(aid, executor, action, mode, s, e, force=True, role="支撑", obj=None, until=None):
    return {"id": aid, "executor": executor, "action": action, "mode": mode,
            "start": s, "end": e, "exerts_force": force, "force_role": role,
            "object": obj, "until": until}


def test_overlap_windows_merge_same_action():
    """相邻窗口重叠区的同一个动作应合成一条。"""
    windows = [
        _win(1, 0.0, 8.0, [_act(1, "左腿", "左腿向前迈步", "motion", 6.0, 8.0, role="支撑")]),
        _win(2, 7.4, 8.0, [_act(1, "左腿", "左腿向前迈步", "motion", 0.0, 1.2, role="支撑")]),
    ]
    out = m.run(windows, 15.4)
    assert out["stats"]["raw_actions"] == 2
    assert out["stats"]["merged_actions"] == 1, out["atomic_actions"]
    a = out["atomic_actions"][0]
    assert (a["start"], a["end"]) == (6.0, 8.6)


def test_distinct_actions_not_merged():
    windows = [_win(1, 0.0, 5.0, [
        _act(1, "左手", "左手抓握纸箱", "transition", 1.0, 1.4, role="抓握", obj="纸箱"),
        _act(2, "左手", "左手松开纸箱", "transition", 3.0, 3.4, force=False, role=None, obj="纸箱"),
    ])]
    out = m.run(windows, 5.0)
    assert out["stats"]["merged_actions"] == 2


def test_until_ref_remapped_to_global_id():
    """until.ref 是窗口内局部 id，合并后必须指向正确的全局动作。"""
    windows = [
        _win(1, 0.0, 6.0, [
            _act(1, "左手", "左手抓握纸箱", "transition", 1.0, 1.4, role="抓握", obj="纸箱"),
            _act(2, "左手", "左手保持抓握纸箱", "maintain", 1.4, 2.0, role="抓握", obj="纸箱",
                 until={"type": "action_completed", "ref": 3, "text": "直到左手松开纸箱"}),
            _act(3, "左手", "左手松开纸箱", "transition", 4.0, 4.4, force=False, role=None, obj="纸箱"),
        ]),
    ]
    out = m.run(windows, 6.0)
    acts = {a["action"]: a for a in out["atomic_actions"]}
    keep = acts["左手保持抓握纸箱"]
    release = acts["左手松开纸箱"]
    assert keep["until"]["ref"] == release["id"], (keep["until"], release["id"])


def test_states_filled_and_chained():
    windows = [_win(1, 0.0, 6.0, [
        _act(1, "左手", "左手抓握纸箱", "transition", 1.0, 1.4, role="抓握", obj="纸箱"),
        _act(2, "左手", "左手保持抓握纸箱", "maintain", 1.4, 4.0, role="抓握", obj="纸箱"),
        _act(3, "左手", "左手松开纸箱", "transition", 4.0, 4.4, force=False, role=None, obj="纸箱"),
    ])]
    out = m.run(windows, 6.0)
    acts = sorted(out["atomic_actions"], key=lambda a: a["start"])
    assert all(a.get("state_before") for a in acts)
    assert acts[1]["state_before"] == acts[0]["state_after"]


def test_alternation_detected_for_legs():
    windows = [_win(1, 0.0, 8.0, [
        _act(1, "左腿", "左腿向前迈步", "motion", 0.0, 2.0),
        _act(2, "右腿", "右腿向前迈步", "motion", 0.5, 2.5),
    ])]
    out = m.run(windows, 8.0)
    rels = {(r["relation"], r["from"], r["to"]) for r in out["temporal_relations"]}
    assert any(r[0] == "alternation" for r in rels), rels


def test_relations_not_duplicated():
    """同一对动作不应既有模型给的关系又有规则推导的重复关系。"""
    windows = [_win(1, 0.0, 8.0, [
        _act(1, "左腿", "左腿向前迈步", "motion", 0.0, 2.0),
        _act(2, "右腿", "右腿向前迈步", "motion", 0.0, 2.0),
    ], rels=[{"relation": "parallel", "from": 1, "to": 2, "note": "双腿交替行走"}])]
    out = m.run(windows, 8.0)
    pairs = [frozenset((r["from"], r["to"])) for r in out["temporal_relations"]]
    assert len(pairs) == len(set(pairs)), out["temporal_relations"]


def test_alternation_not_triggered_for_arms():
    """双臂同时抬起、双手同时抓握是并行，不应被误判为交替。"""
    windows = [_win(1, 0.0, 8.0, [
        _act(1, "左臂", "左臂向上抬起托举", "motion", 1.0, 3.0, role="托举"),
        _act(2, "右臂", "右臂向上抬起托举", "motion", 1.0, 3.0, role="托举"),
        _act(3, "左手", "左手抓握纸箱", "transition", 3.0, 3.4, role="抓握"),
        _act(4, "右手", "右手抓握纸箱", "transition", 3.0, 3.4, role="抓握"),
    ])]
    out = m.run(windows, 8.0)
    alts = [r for r in out["temporal_relations"] if r["relation"] == "alternation"]
    assert not alts, alts


def test_boundary_stitch_across_windows_via_core_phrase():
    """被窗口边界切开的同一动作：后段描述更详细、包含了前段的核心短语 → 应合并。"""
    windows = [
        _win(1, 0.0, 8.0, [_act(1, "右腿", "右腿向前迈步", "motion", 6.5, 8.0, role="支撑")]),
        _win(2, 7.4, 8.0, [_act(1, "右腿", "右腿向前迈步，与左腿交替行走", "motion", 0.0, 2.8, role="支撑")]),
    ]
    out = m.run(windows, 15.4)
    assert out["stats"]["merged_actions"] == 1, out["atomic_actions"]


def test_boundary_stitch_does_not_merge_opposite_meaning():
    """“迈步”与“停止迈步”不得被合并。"""
    windows = [
        _win(1, 0.0, 8.0, [_act(1, "右腿", "右腿向前迈步", "motion", 6.5, 8.0, role="支撑")]),
        _win(2, 7.4, 8.0, [_act(1, "右腿", "右腿停止迈步，支撑身体站立", "motion", 0.0, 2.5, role="支撑")]),
    ]
    out = m.run(windows, 15.4)
    assert out["stats"]["merged_actions"] == 2, out["atomic_actions"]


def test_trim_maintain_overlap_with_later_motion():
    """保持抬起托举与随后的前伸重叠时，保持应截断到前伸开始前。"""
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂保持抬起托举", "mode": "maintain",
         "start": 5.5, "end": 13.5},
        {"id": 2, "executor": "右臂", "action": "右臂向前伸出放置", "mode": "motion",
         "start": 10.0, "end": 13.5},
    ]
    trimmed = m.trim_maintain_overlaps(actions)
    assert actions[0]["end"] == 10.0, actions
    assert trimmed and trimmed[0]["part"] == "右臂"


def test_trim_keeps_maintain_when_motion_starts_together():
    """同时开始的保持与移动不截断。"""
    actions = [
        {"id": 1, "executor": "左手", "action": "左手保持抓握", "mode": "maintain",
         "start": 1.0, "end": 5.0},
        {"id": 2, "executor": "左手", "action": "左手手指微调", "mode": "motion",
         "start": 1.0, "end": 2.0},
    ]
    trimmed = m.trim_maintain_overlaps(actions)
    assert actions[0]["end"] == 5.0
    assert trimmed == []


def test_stitch_maintains_closes_gap():
    """保持动作与下一次解除之间有空档时，应把保持区间缝合过去。"""
    actions = [
        {"id": 1, "executor": "左手", "action": "左手抓握瓶身", "mode": "transition",
         "start": 1.0, "end": 1.4, "state_before": "张开", "state_after": "抓握瓶身"},
        {"id": 2, "executor": "左手", "action": "左手保持抓握瓶身", "mode": "maintain",
         "start": 1.4, "end": 5.0, "state_before": "抓握瓶身", "state_after": "抓握瓶身"},
        {"id": 3, "executor": "左手", "action": "左手松开瓶身", "mode": "transition",
         "start": 7.0, "end": 7.4, "state_before": "抓握瓶身", "state_after": "张开"},
    ]
    stitched = m.stitch_maintains(actions)
    assert actions[1]["end"] == 7.0
    assert stitched and stitched[0]["part"] == "左手"


def test_stitch_maintains_skips_when_gap_too_large():
    actions = [
        {"id": 2, "executor": "左手", "action": "左手保持抓握瓶身", "mode": "maintain",
         "start": 1.4, "end": 5.0, "state_before": "抓握瓶身", "state_after": "抓握瓶身"},
        {"id": 3, "executor": "左手", "action": "左手松开瓶身", "mode": "transition",
         "start": 20.0, "end": 20.4, "state_before": "抓握瓶身", "state_after": "张开"},
    ]
    stitched = m.stitch_maintains(actions)
    assert actions[0]["end"] == 5.0
    assert stitched == []


def test_long_video_window_plan():
    from video2op import media
    plan = media.window_plan(30.0)
    assert len(plan) >= 3
    assert plan[0][0] == 0.0
    short = media.window_plan(12.0)
    assert short == [(0.0, 12.0)]
