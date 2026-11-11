#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「不参与操作的部位」（头 / 颈 / 口）的文本净化回归。

以操作为节点之后，这些部位只承担朝向、观察与言语，对操作没有作用：
  · 执行器形态（头保持平视 / 颈部转动 / 口张开）由各阶段归一化按 vocab.IGNORED_PARTS
    丢掉，写进动作表之前就没了（见 tests/test_ignored_parts.py）；
  · 文本形态（条件里写"保持视线"、评价里写"头部后仰"、步骤里写"张开嘴"）由
    ignored_parts 按分句删掉，一条内容被清空就整条去掉；
  · 观察证据（画面依据、条件理由）不动——它们不进入操作图。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op import ignored_parts
from video2op.pipeline import build_legacy_execution_graph as build_operation_graph
from video2op.stages import s06_validate
from video2op.vocab import BODY_PARTS, IGNORED_PARTS, IGNORED_TEXT_WORDS


def test_body_parts_excludes_ignored_parts():
    """部位表里没有头 / 颈 / 口；它们进的是"不参与操作"名单。"""
    assert not {"头", "颈", "口"} & set(BODY_PARTS)
    assert {"头", "颈", "口"} <= IGNORED_PARTS


def test_bare_words_not_in_wordlist():
    """"头"与"口"单字不入词表：举过头顶 / 瓶颈 / 瓶口 这些正常表述不能被误伤。"""
    assert "头" not in IGNORED_TEXT_WORDS
    assert "口" not in IGNORED_TEXT_WORDS
    assert not ignored_parts.has_ignored_text("右臂把纸箱举过头顶")
    assert not ignored_parts.has_ignored_text("右手捏住瓶颈")
    assert not ignored_parts.has_ignored_text("瓶口对准货架中层")


def test_clean_text_keeps_operational_clause():
    """同一句里与操作有关的部分保留，只删含不参与操作部位的分句。"""
    text = "在提取物体并回正身体时，应避免物体撞击身体或容器边缘，且视线应关注物体位置。"
    new, removed = ignored_parts.clean_text(text)
    assert new == "在提取物体并回正身体时，应避免物体撞击身体或容器边缘"
    assert removed == 1


def test_clean_text_drops_whole_text_when_only_ignored_content():
    assert ignored_parts.clean_text("视线朝向目标纸箱") == ("", 1)
    assert ignored_parts.clean_text("头部后仰") == ("", 1)
    assert ignored_parts.clean_text("口张开接触瓶口") == ("", 1)


def test_clean_text_drops_text_that_depends_on_removed_clause():
    """删掉的分句是前提时，后面的承接部分也一起去掉。"""
    assert ignored_parts.clean_text("若目标在视线盲区，则不会伸手") == ("", 2)
    assert ignored_parts.clean_text("男子头部平视，随后伸出右手") == ("", 2)


def test_clean_text_drops_orphan_adverbial_clause():
    """只剩一个状语分句（"在准备饮用阶段"）时，它撑不起一条语义——整条去掉。"""
    assert ignored_parts.clean_text(
        "在准备饮用阶段，手臂举升瓶子的动作与头部后仰的动作需协同进行，以实现对齐。") == ("", 3)


def test_clean_text_leaves_operational_text_untouched():
    for text in ("搬运全程保持抓握稳定，纸箱不能滑落",
                 "右手握住瓶颈把瓶子提起来",
                 "纸箱位于货架中层"):
        assert ignored_parts.clean_text(text) == (text, 0)


def test_purge_cleans_task_node_tuple():
    bundle = {"task_nodes": {"task_nodes": [{
        "id": "node_1", "name": "走到纸箱前", "intent_role": "接近目标",
        "tuple": {
            "X": {"subject": "操作者", "parts": ["左腿", "头"]},
            "C_pre": ["纸箱在可及范围内", "操作者视线可及纸箱"],
            "C_const": ["保持身体平衡", "视线朝向目标纸箱"],
            "C_post": ["操作者位于纸箱前"],
            "E": {"process": ["视线朝向纸箱"], "completion": ["双脚站稳"]},
            "R": [{"name": "直线行走", "steps": ["左腿迈步", "抬头看路"]}],
        }}]}}
    stats = ignored_parts.purge(bundle)
    t = bundle["task_nodes"]["task_nodes"][0]["tuple"]
    assert t["C_pre"] == ["纸箱在可及范围内"]
    assert t["C_const"] == ["保持身体平衡"]
    assert t["C_post"] == ["操作者位于纸箱前"]
    assert t["E"] == {"process": [], "completion": ["双脚站稳"]}
    assert t["R"][0]["steps"] == ["左腿迈步"]
    assert t["X"]["parts"] == ["左腿"]
    assert stats["entries_removed"] == 4


def test_purge_filters_world_state_and_parts():
    bundle = {
        "atomic": {
            "atomic_actions": [{"id": 1, "action": "左臂向前伸出",
                                "world_before": ["纸箱位于地面", "视线朝向纸箱"],
                                "world_after": ["头部转向目标"]}],
            "inactive_parts": [{"part": "头", "state": "自然平视"},
                               {"part": "颈", "state": "自然平视"},
                               {"part": "口", "state": "闭合"},
                               {"part": "腰", "state": "直立"}],
        },
        "intents": {"intents": [{"required_body_parts": [
            {"part": "头", "role": "观察目标"}, {"part": "右手", "role": "抓握"}]}]},
    }
    ignored_parts.purge(bundle)
    assert bundle["atomic"]["atomic_actions"][0]["world_before"] == ["纸箱位于地面"]
    assert bundle["atomic"]["atomic_actions"][0]["world_after"] == []
    assert [ip["part"] for ip in bundle["atomic"]["inactive_parts"]] == ["腰"]
    assert [bp["part"] for bp in bundle["intents"]["intents"][0]["required_body_parts"]] == ["右手"]


def test_purge_writes_back_partially_cleaned_entries():
    """列表里"只删掉一半"的条目也要写回（不能只改内存里的副本）。"""
    bundle = {"rules": {"evaluators": [{"node_id": "node_1",
                                        "completion": ["头部处于后仰姿态，准备接收液体"]}]}}
    ignored_parts.purge(bundle)
    assert bundle["rules"]["evaluators"][0]["completion"] == ["准备接收液体"]
    assert ignored_parts.scan(bundle) == []


def test_purge_cleans_conditions_and_rules():
    bundle = {
        "conditions": {"condition_learning": [{"node_id": "node_1", "C_pre_learning": [{
            "condition": "手是空的", "positive": {"text": "男子头部平视，随后伸出右手"},
            "negative_a": {"text": "若手中已有物体，则抓不住", "reason": "握持冲突"},
            "negative_b": {"text": "若目标在视线盲区，则不会伸手", "reason": "感知失败"}}]}]},
        "rules": {"constraints": [{"statement": "瓶口必须与口部对齐，且头部需后仰"}],
                  "evaluators": [{"node_id": "node_1", "process": ["头部同步后仰"],
                                  "completion": ["瓶口对齐"], "failure_signals": []}]},
    }
    ignored_parts.purge(bundle)
    entry = bundle["conditions"]["condition_learning"][0]["C_pre_learning"][0]
    assert entry["positive"]["text"] == ""
    assert entry["negative_a"]["text"] == "若手中已有物体，则抓不住"
    assert entry["negative_b"]["text"] == ""          # 整句都是头部/视觉内容 → 去掉
    assert entry["negative_a"]["reason"] == "握持冲突"   # 理由保留（不进入操作图）
    assert bundle["rules"]["constraints"] == []          # 整条只讲口部 / 头部 → 去掉
    assert bundle["rules"]["evaluators"][0]["process"] == []
    assert bundle["rules"]["evaluators"][0]["completion"] == ["瓶口对齐"]


def test_purge_prunes_entry_whose_condition_was_ignored_only():
    """条件本身只讲头 / 口时，整条学习记录去掉（不留空壳）。"""
    bundle = {
        "conditions": {
            "condition_learning": [{"node_id": "node_5",
                                    "C_pre_learning": [
                                        {"condition": "头处于自然平视状态",
                                         "positive": {"text": "男子头部平视"}},
                                        {"condition": "手是空的",
                                         "positive": {"text": "男子右手空着"}}],
                                    "C_post_learning": []}],
            "rejected_conditions": [{"condition": "口部张开等待接收", "why": "条件过强"},
                                    {"condition": "瓶盖已拧开", "why": ""}],
        },
        "rules": {"temporal_structures": [{"statement": "头部后仰与手臂举升需协同"},
                                          {"statement": "先接触再抓握"}],
                  "constraints": [{"statement": "头部需后仰以配合液体流入"},
                                  {"statement": "必须保持抓握"}]},
    }
    ignored_parts.purge(bundle)
    cl = bundle["conditions"]["condition_learning"][0]
    assert [e["condition"] for e in cl["C_pre_learning"]] == ["手是空的"]
    assert [r["condition"] for r in bundle["conditions"]["rejected_conditions"]] == ["瓶盖已拧开"]
    assert [t["statement"] for t in bundle["rules"]["temporal_structures"]] == ["先接触再抓握"]
    assert [c["statement"] for c in bundle["rules"]["constraints"]] == ["必须保持抓握"]
    assert ignored_parts.scan(bundle) == []


def test_purge_keeps_evidence():
    """观察证据是"为什么这么判断"的溯源信息，不在净化范围。"""
    bundle = {"atomic": {"atomic_actions": [
        {"id": 1, "action": "左臂向前伸出", "evidence": "男子头部平视，随后左手伸出"}]}}
    ignored_parts.purge(bundle)
    assert bundle["atomic"]["atomic_actions"][0]["evidence"] == "男子头部平视，随后左手伸出"


def test_purge_keeps_structural_name_and_reports_it():
    """节点名不能置空：保留原文，交给 s06 的检查提示人工处理。"""
    bundle = {"task_nodes": {"task_nodes": [
        {"id": "n1", "name": "低头看货架", "intent_role": "取物", "tuple": {}}]}}
    stats = ignored_parts.purge(bundle)
    assert bundle["task_nodes"]["task_nodes"][0]["name"] == "低头看货架"
    assert stats["unresolved"]
    assert ignored_parts.scan(bundle)


def test_purge_is_idempotent():
    bundle = {"rules": {"temporal_structures": [{"statement": "手臂举升瓶子时头部同步后仰"},
                                                {"statement": "先接触再抓握"}]}}
    ignored_parts.purge(bundle)
    first = json.dumps(bundle, ensure_ascii=False, sort_keys=True)
    stats = ignored_parts.purge(bundle)
    assert json.dumps(bundle, ensure_ascii=False, sort_keys=True) == first
    assert stats["fields"] == 0 and stats["entries_removed"] == 0


def test_purge_drops_ignored_actions_and_cleans_references():
    """旧数据里残留的头 / 口动作要连引用一起删（关系 / 节点引用 / until.ref）。"""
    bundle = {
        "atomic": {
            "atomic_actions": [
                {"id": 16, "executor": "头", "action": "头向后仰", "mode": "motion",
                 "start": 11.5, "end": 12.5},
                {"id": 17, "executor": "口", "action": "口张开接触瓶口", "mode": "transition",
                 "start": 12.0, "end": 12.5,
                 "until": {"type": "event", "ref": 16, "text": "直到头回正"}},
                {"id": 18, "executor": "左手", "action": "左手保持抓握", "mode": "maintain",
                 "start": 12.5, "end": 14.0},
            ],
            "temporal_relations": [{"relation": "parallel", "from": 15, "to": 16,
                                    "note": "头部后仰"},
                                   {"relation": "enables", "from": 15, "to": 18, "note": ""}],
        },
        "relations": [{"relation": "parallel", "from": 16, "to": 17, "note": ""}],
        "task_nodes": {"task_nodes": [{"id": "node_5", "name": "送到嘴边",
                                       "intent_role": "把瓶口送到嘴边",
                                       "atomic_refs": [16, 17, 18]}]},
    }
    stats = ignored_parts.purge(bundle)
    assert stats["actions_removed"] == 2
    assert [a["id"] for a in bundle["atomic"]["atomic_actions"]] == [18]
    assert bundle["relations"] == []
    assert bundle["atomic"]["temporal_relations"] == [{"relation": "enables", "from": 15,
                                                       "to": 18, "note": ""}]
    assert bundle["task_nodes"]["task_nodes"][0]["atomic_refs"] == [18]
    # 名称/目的清空会破坏结构：原实现保留它们并报告待复核，不能期望静默消失。
    assert {hit["path"] for hit in ignored_parts.scan(bundle)} == {
        "task_nodes[0].name", "task_nodes[0].intent_role"}
    assert len(stats["unresolved"]) == 2


def test_purge_cleans_capability_lists():
    """能力需求里不写不参与操作的部位的功能（"仰头""张嘴"不是操作能力）。"""
    bundle = {"intents": {"intents": [{"statement": "喝牛奶",
                                       "required_capabilities": ["行走接近", "仰头", "饮用"]}]},
              "task_nodes": {"task_nodes": [{"id": "n1", "name": "饮用", "intent_role": "喝",
                                             "required_capabilities": ["举升", "张嘴"],
                                             "tuple": {}}]}}
    ignored_parts.purge(bundle)
    assert bundle["intents"]["intents"][0]["required_capabilities"] == ["行走接近", "饮用"]
    assert bundle["task_nodes"]["task_nodes"][0]["required_capabilities"] == ["举升"]


def test_scan_and_check_agree():
    bundle = {"rules": {"constraints": [{"statement": "保持视线朝向目标"}]}}
    assert s06_validate._check_ignored_parts(bundle)["status"] == "warn"
    ignored_parts.purge(bundle)
    assert ignored_parts.scan(bundle) == []
    assert s06_validate._check_ignored_parts(bundle)["status"] == "pass"


def test_build_operation_graph_purges_ignored_content():
    """在线与离线重建共用建图入口：建图前先净化（机制而不是约定）。"""
    bundle = {
        "task_nodes": {"task_nodes": [{
            "id": "node_1", "name": "搬运纸箱", "intent_role": "把纸箱搬到目标位置",
            "required_capabilities": ["承载移动"],
            "tuple": {"X": {"subject": "操作者", "parts": ["左臂", "右臂"]},
                      "O": ["纸箱"], "C_pre": ["左手已建立抓握"],
                      "C_const": ["保持抓握稳定", "视线朝向目标位置"],
                      "C_post": ["纸箱位于目标位置"],
                      "E": {"process": [], "completion": []}, "R": []},
            "atomic_refs": []}]},
        "atomic": {"atomic_actions": [], "inactive_parts": [{"part": "口", "state": "闭合"}]},
        "relations": [], "intents": {"intents": []},
    }
    build_operation_graph(bundle)
    assert bundle["ignored_parts"]["entries_removed"] == 1   # 视觉约束整条去掉
    assert bundle["ignored_parts"]["parts_removed"] == 1     # 驻留部位表里的口
    assert bundle["operations"]["nodes"][0]["invariants"] == ["保持抓握稳定"]
    assert bundle["atomic"]["inactive_parts"] == []
    assert ignored_parts.scan(bundle) == []
