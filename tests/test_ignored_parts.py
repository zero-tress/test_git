#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「不参与操作的部位」（头 / 颈 / 口）的执行器过滤回归。

这些部位只承担朝向 / 观察 / 言语，不产生操作——它们不该出现在动作表、补全动作、
任务节点执行主体、意图所需部位或可见世界状态里（见 vocab.IGNORED_PARTS、
ignored_parts.py）。文本形态的净化见 tests/test_ignored_text.py。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op.single_video.stages import s02a_intent, s02b_atomic, s02b_merge, s02c_task, s02d_link, s02e_prior


def test_s02b_drops_head_actions():
    payload = {"atomic_actions": [
        {"id": 1, "executor": "头", "action": "头保持平视", "mode": "maintain",
         "start": 0.0, "end": 5.0},
        {"id": 2, "executor": "左手", "action": "抓握杯子", "mode": "transition",
         "start": 1.0, "end": 1.5},
    ], "temporal_relations": [{"relation": "sequence", "from": 1, "to": 2}]}
    out = s02b_atomic._normalize_window(payload, 5.0)
    assert [a["executor"] for a in out["atomic_actions"]] == ["左手"]
    assert out["temporal_relations"] == []      # 指向被忽略动作的关系一并去掉


def test_s02a_drops_head_required_parts():
    payload = {"intents": [{"statement": "把杯子拿过来", "confidence": 0.8,
                            "required_body_parts": [
                                {"part": "头", "role": "观察目标"},
                                {"part": "右手", "role": "抓握"}]}]}
    out = s02a_intent._normalize(payload)
    assert [bp["part"] for bp in out["intents"][0]["required_body_parts"]] == ["右手"]


def test_s02c_drops_head_from_subject_parts():
    payload = {"task_nodes": [{"id": "node_1", "name": "抓取",
                               "tuple": {"X": {"subject": "操作者",
                                               "parts": ["头", "右手"]}}}]}
    out = s02c_task._normalize(payload)
    assert out["task_nodes"][0]["tuple"]["X"]["parts"] == ["右手"]


def test_s02d_drops_head_missing_actions():
    atomic = [{"id": 1, "executor": "左手", "action": "抓握杯子", "mode": "transition",
               "start": 0.0, "end": 1.0}]
    payload = {"links": [], "missing_actions": [
        {"executor": "头", "action": "头保持平视", "mode": "maintain",
         "start": 0.0, "end": 1.0},
        {"executor": "左臂", "action": "左臂保持抬起", "mode": "maintain",
         "start": 1.0, "end": 2.0},
    ]}
    out = s02d_link._normalize(payload, atomic, 3.0)
    assert [a["executor"] for a in out["missing_actions"]] == []  # 保持动作已被 v3 禁止，头口与保持均不补全


def test_s02e_prior_skips_head_hold():
    actions = [{"id": 1, "executor": "头", "action": "头抬起", "mode": "motion",
                "start": 0.0, "end": 1.0},
               {"id": 2, "executor": "头", "action": "头保持", "mode": "motion",
                "start": 3.0, "end": 4.0}]
    out = s02e_prior.run(actions, 10.0)
    assert not [a for a in out["inferred_actions"] if a["executor"] == "头"]


def test_s02b_drops_neck_actions():
    """颈部与头同类：也不参与操作。"""
    payload = {"atomic_actions": [
        {"id": 1, "executor": "颈", "action": "颈部转动", "mode": "motion",
         "start": 0.0, "end": 1.0},
        {"id": 2, "executor": "口", "action": "口张开接触瓶口", "mode": "transition",
         "start": 1.0, "end": 1.5},
        {"id": 3, "executor": "右手", "action": "抓握杯子", "mode": "transition",
         "start": 1.0, "end": 1.5},
    ], "temporal_relations": []}
    out = s02b_atomic._normalize_window(payload, 5.0)
    assert [a["executor"] for a in out["atomic_actions"]] == ["右手"]


def test_s02a_drops_mouth_required_parts():
    """意图所需部位里也不留口部。"""
    payload = {"intents": [{"statement": "喝牛奶", "confidence": 0.8,
                            "required_body_parts": [
                                {"part": "口", "role": "接收液体"},
                                {"part": "左手", "role": "持瓶"}]}]}
    out = s02a_intent._normalize(payload)
    assert [bp["part"] for bp in out["intents"][0]["required_body_parts"]] == ["左手"]


def test_s02d_drops_mouth_missing_actions():
    atomic = [{"id": 1, "executor": "左手", "action": "抓握瓶子", "mode": "transition",
               "start": 0.0, "end": 1.0}]
    payload = {"links": [], "missing_actions": [
        {"executor": "口", "action": "口张开", "mode": "transition",
         "start": 0.0, "end": 1.0},
        {"executor": "左臂", "action": "左臂保持抬起", "mode": "maintain",
         "start": 1.0, "end": 2.0},
    ]}
    out = s02d_link._normalize(payload, atomic, 3.0)
    assert [a["executor"] for a in out["missing_actions"]] == []  # 保持动作已被 v3 禁止，头口与保持均不补全


def test_s02b_cleans_head_world_state():
    """可见世界状态里不留头部 / 视线内容（整条都是的丢掉，从句删掉）。"""
    payload = {"atomic_actions": [
        {"id": 1, "executor": "右手", "action": "右手抓握杯子，同时视线追随",
         "mode": "transition", "start": 0.0, "end": 1.0,
         "world_before": ["杯子在桌上", "视线朝向杯子"], "world_after": []}],
        "temporal_relations": []}
    out = s02b_atomic._normalize_window(payload, 5.0)
    a = out["atomic_actions"][0]
    assert a["world_before"] == ["杯子在桌上"]
    assert a["action"] == "右手抓握杯子"


def test_s02b_merge_skips_ignored_inactive_parts():
    """驻留部位表里不保留头 / 颈 / 口（可见世界状态也不写它们）。"""
    windows = [{
        "window": {"index": 1, "start": 0.0, "duration": 5.0},
        "atomic_actions": [{"id": 1, "executor": "右手", "action": "右手抓握杯子",
                            "mode": "transition", "start": 0.0, "end": 1.0,
                            "exerts_force": True, "force_role": "抓握",
                            "object": "杯子", "until": None}],
        "temporal_relations": [],
        "inactive_parts": [{"part": "头", "state": "自然平视"},
                           {"part": "颈", "state": "自然平视"},
                           {"part": "口", "state": "闭合"},
                           {"part": "腰", "state": "直立"}],
    }]
    out = s02b_merge.run(windows, 5.0)
    assert [ip["part"] for ip in out["inactive_parts"]] == ["腰"]
