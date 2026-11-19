#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""词表与归一化的单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op.single_video.stages.common import expand_parts, normalize_force, normalize_part


def test_force_role_of_head_part_dropped():
    """头部的"视觉定位"不是给力，应清空并且不给力。"""
    a = {"executor": "头", "action": "观察货架", "exerts_force": True, "force_role": "视觉定位"}
    normalize_force(a)
    assert a["exerts_force"] is False
    assert a["force_role"] is None


def test_force_role_alias_and_whitelist():
    a = {"executor": "左臂", "action": "抬起", "exerts_force": True, "force_role": "提举"}
    normalize_force(a)
    assert a["force_role"] == "托举"
    b = {"executor": "左臂", "action": "抬起", "exerts_force": True, "force_role": "莫名其妙的力"}
    normalize_force(b)
    assert b["force_role"] == "给力"


def test_force_role_cleared_when_not_exerting():
    c = {"executor": "左手", "action": "抓", "exerts_force": False, "force_role": "抓握"}
    normalize_force(c)
    assert c["force_role"] is None


def test_normalize_and_expand_parts():
    assert normalize_part("手臂") == "左臂"
    assert normalize_part("左脚") == "左腿"  # 腿脚一体
    assert normalize_part("右脚") == "右腿"
    assert normalize_part("腰部") == "腰部"  # 未收录的写法原样返回（由上层校验发现）
    assert expand_parts(["双腿", "腰"]) == ["左腿", "右腿", "腰"]
    assert expand_parts(["双脚"]) == ["左腿", "右腿"]
    assert expand_parts(["左手"]) == ["左手"]
