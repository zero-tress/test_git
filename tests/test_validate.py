#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验与纪律的确定性测试（不经模型）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op.single_video.pipeline import set_by_path
from video2op.single_video.stages import s06_validate as v


def _bundle(actions=None, intents=None, nodes=None):
    return {
        "meta": {"duration": 10.0, "name": "t"},
        "atomic": {"atomic_actions": actions or [], "conflicts": []},
        "relations": [],
        "task_nodes": {"task_nodes": nodes or []},
        "link": {"links": [], "missing_actions": []},
        "intents": {"intents": intents or []},
        "rules": {"evaluators": []},
        "conditions": {},
    }


def test_param_discipline_catches_degree():
    b = _bundle(intents=[{"id": "intent_1", "statement": "手臂抬起45度", "confidence": 0.9}])
    rep = v.run(b)
    check = next(c for c in rep["checks"] if c["id"] == "param_discipline")
    assert check["status"] == "fail"
    assert rep["passed"] is False


def test_param_discipline_passes_qualitative():
    b = _bundle(intents=[{"id": "intent_1", "statement": "手臂向上抬起至肩高附近", "confidence": 0.9}])
    rep = v.run(b)
    check = next(c for c in rep["checks"] if c["id"] == "param_discipline")
    assert check["status"] == "pass"


def test_state_chain_detects_break():
    actions = [
        {"id": 1, "executor": "左手", "action": "左手抓握纸箱", "mode": "transition",
         "start": 1.0, "end": 1.4, "state_before": "张开", "state_after": "抓握纸箱"},
        {"id": 2, "executor": "左手", "action": "左手张开手指", "mode": "transition",
         "start": 2.0, "end": 2.2, "state_before": "手是空的", "state_after": "张开"},
    ]
    rep = v.run(_bundle(actions=actions))
    check = next(c for c in rep["checks"] if c["id"] == "state_chain")
    assert check["status"] == "warn"
    assert check["detail"]


def test_maintain_gap_detected():
    """建立抓握后缺少保持动作 → 应报保持缺口。"""
    actions = [
        {"id": 1, "executor": "左手", "action": "左手抓握纸箱", "mode": "transition",
         "start": 1.0, "end": 1.4, "start_end": None, "state_before": "张开",
         "state_after": "抓握纸箱"},
        {"id": 2, "executor": "左手", "action": "左手松开纸箱", "mode": "transition",
         "start": 5.0, "end": 5.4, "state_before": "抓握纸箱", "state_after": "张开"},
    ]
    rep = v.run(_bundle(actions=actions))
    check = next(c for c in rep["checks"] if c["id"] == "maintain_coverage")
    assert check["status"] == "warn", check


def test_maintain_covered_no_issue():
    actions = [
        {"id": 1, "executor": "左手", "action": "左手抓握纸箱", "mode": "transition",
         "start": 1.0, "end": 1.4, "state_before": "张开", "state_after": "抓握纸箱"},
        {"id": 2, "executor": "左手", "action": "左手保持抓握纸箱", "mode": "maintain",
         "start": 1.4, "end": 5.0, "state_before": "抓握纸箱", "state_after": "抓握纸箱"},
        {"id": 3, "executor": "左手", "action": "左手松开纸箱", "mode": "transition",
         "start": 5.0, "end": 5.4, "state_before": "抓握纸箱", "state_after": "张开"},
    ]
    rep = v.run(_bundle(actions=actions))
    check = next(c for c in rep["checks"] if c["id"] == "maintain_coverage")
    assert check["status"] == "pass", check


def test_arm_contact_hold_gap_detected():
    """手接触物体期间手臂没有记录 → 应报接触期手臂缺口。"""
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向下伸出", "mode": "motion",
         "start": 2.0, "end": 3.5},
        {"id": 2, "executor": "右手", "action": "右手接触纸箱", "mode": "transition",
         "start": 3.5, "end": 4.5},
        {"id": 3, "executor": "右臂", "action": "右臂向上抬起", "mode": "motion",
         "start": 5.5, "end": 6.5},
    ]
    rep = v.run(_bundle(actions=actions))
    check = next(c for c in rep["checks"] if c["id"] == "arm_contact_hold")
    assert check["status"] == "warn", check
    assert any(d.get("part") == "右臂" for d in check["detail"])


def test_arm_contact_hold_covered_passes():
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向下伸出", "mode": "motion",
         "start": 2.0, "end": 3.5},
        {"id": 2, "executor": "右臂", "action": "右臂保持伸出", "mode": "maintain",
         "start": 3.5, "end": 5.5},
        {"id": 3, "executor": "右手", "action": "右手接触纸箱", "mode": "transition",
         "start": 3.5, "end": 4.5},
        {"id": 4, "executor": "右臂", "action": "右臂向上抬起", "mode": "motion",
         "start": 5.5, "end": 6.5},
    ]
    rep = v.run(_bundle(actions=actions))
    check = next(c for c in rep["checks"] if c["id"] == "arm_contact_hold")
    assert check["status"] == "pass", check


def test_arm_contact_hold_ignores_release():
    """松开、放下不是接触期，不报缺口。"""
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向下伸出", "mode": "motion",
         "start": 2.0, "end": 3.5},
        {"id": 2, "executor": "右手", "action": "右手松开纸箱", "mode": "transition",
         "start": 3.5, "end": 4.0},
    ]
    rep = v.run(_bundle(actions=actions))
    check = next(c for c in rep["checks"] if c["id"] == "arm_contact_hold")
    assert check["status"] == "pass", check


def test_intent_part_coverage():
    intents = [{"id": "intent_1", "statement": "喝牛奶", "confidence": 0.9,
                "required_body_parts": [{"part": "左手"}, {"part": "腰"}]}]
    actions = [{"id": 1, "executor": "左手", "action": "左手抓握牛奶瓶", "mode": "transition",
                "start": 0.0, "end": 0.4}]
    rep = v.run(_bundle(actions=actions, intents=intents))
    check = next(c for c in rep["checks"] if c["id"] == "intent_part_coverage")
    assert check["status"] == "warn"
    assert any("腰" in str(d) for d in check["detail"])


def test_reference_integrity():
    b = _bundle(nodes=[{"id": "node_1", "name": "n", "tuple": {"X": {}, "O": [], "C_pre": [],
                                                               "C_const": [], "E": {}, "C_post": [],
                                                               "R": []},
                        "atomic_refs": [99]}])
    rep = v.run(b)
    check = next(c for c in rep["checks"] if c["id"] == "references")
    assert check["status"] == "fail"


def test_param_discipline_ignores_purify_metadata():
    """净化记录里的原文摘引不算知识内容，不应触发失败。"""
    b = _bundle()
    b["purify"] = {"applied": 1, "rewrites": [
        {"path": "conditions.x", "new_text": "轻微离地", "note": "将具体数值“10cm”替换为定性描述"}]}
    rep = v.run(b)
    check = next(c for c in rep["checks"] if c["id"] == "param_discipline")
    assert check["status"] == "pass", check


def test_set_by_path():
    obj = {"a": {"b": [{"c": "old"}]}}
    assert set_by_path(obj, "a.b[0].c", "new") is True
    assert obj["a"]["b"][0]["c"] == "new"
    assert set_by_path(obj, "a.x.c", "v") is False
    assert set_by_path(obj, "no.such", "v") is False
