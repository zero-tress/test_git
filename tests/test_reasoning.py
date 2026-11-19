#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推理修正的确定性测试。

守住的核心纪律：
  · 条件不成立时降级的是**依赖关系**，不是删除节点（A 可能确实发生了）；
  · 条件无人提供时只能登记**候选缺口**，不能写成视频事实；
  · 环境默认前提不算缺口；
  · "视频里 A 先于 B"（观测）与"执行 B 必须先完成 A"（依赖）必须区分开。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op import operations, reasoning
from video2op.single_video.stages import s06_validate


def _act(i, part, action, start, end, mode="motion", force=False, role=None,
         state_after=None, world_after=None):
    return {"id": i, "executor": part, "action": action, "mode": mode,
            "start": start, "end": end, "exerts_force": force, "force_role": role,
            "object": None, "state_before": None, "state_after": state_after,
            "world_after": world_after, "inferred": False}


def _node(nid, name, start, end, refs, parts, pre=None, post=None, intent="作用"):
    return {"id": nid, "name": name, "intent_role": intent, "time_range": [start, end],
            "tuple": {"X": {"subject": "操作者", "parts": list(parts)}, "O": [],
                      "C_pre": list(pre or []), "C_post": list(post or [])},
            "atomic_refs": list(refs)}


def _bundle(nodes, actions, relations=None):
    return {"operations": operations.build({"task_nodes": nodes}, actions, relations or []),
            "atomic": {"atomic_actions": actions}}


# ---------------------------------------------------------------
# ① 依赖支撑：A 声称提供的条件，A 能不能产生
# ---------------------------------------------------------------

def test_capability_mismatch_downgrades_edge():
    """腿不具备"握持"能力，却声称提供了握持条件 → 降级为仅观测顺序。"""
    nodes = [_node("n1", "走向杯子", 0.0, 1.0, [1], ["左腿", "右腿"],
                   post=["左手稳定握持杯子"]),
             _node("n2", "举杯", 1.0, 2.0, [2], ["左臂"],
                   pre=["左手稳定握持杯子"])]
    actions = [_act(1, "左腿", "左腿向前迈步", 0.0, 1.0, state_after="站立"),
               _act(2, "左臂", "左臂向上抬起", 1.0, 2.0)]
    b = _bundle(nodes, actions)
    r = reasoning.audit(b)
    assert r["stats"]["downgraded"] == 1
    edge = b["operations"]["edges"][0]
    assert edge["relation"] == "sequence" and edge["downgraded"] is True
    assert edge["basis"] == "observed_order"
    # 节点没有被删掉（A 可能确实发生了）
    assert {n["id"] for n in b["operations"]["nodes"]} == {"n1", "n2"}


def test_observed_effect_keeps_edge_as_dependency():
    nodes = [_node("n1", "抓握杯子", 0.0, 1.0, [1], ["左手", "右手"],
                   post=["左手稳定握持杯子"]),
             _node("n2", "举杯", 1.0, 2.0, [2], ["左臂"],
                   pre=["左手稳定握持杯子"])]
    actions = [_act(1, "左手", "左手建立抓握", 0.0, 1.0, "transition", True, "抓握",
                    state_after="左手稳定握持杯子"),
               _act(2, "左臂", "左臂向上抬起", 1.0, 2.0)]
    b = _bundle(nodes, actions)
    r = reasoning.audit(b)
    assert r["stats"]["downgraded"] == 0
    edge = b["operations"]["edges"][0]
    assert edge["relation"] == "enables"
    assert edge["basis"] == "required_dependency"


def test_legs_can_provide_approach_condition():
    """腿的"迈步"也能产生位置条件——不能因为能力表里只写了"靠近"就误判。"""
    nodes = [_node("n1", "走到桌边", 0.0, 1.0, [1], ["左腿", "右腿"],
                   post=["操作者位于桌边"]),
             _node("n2", "抓握杯子", 1.0, 2.0, [2], ["左手"],
                   pre=["操作者位于桌边"])]
    actions = [_act(1, "左腿", "左腿向前迈步", 0.0, 1.0, state_after="操作者位于桌边"),
               _act(2, "左手", "左手建立抓握", 1.0, 2.0, "transition")]
    b = _bundle(nodes, actions)
    r = reasoning.audit(b)
    assert r["stats"]["downgraded"] == 0


# ---------------------------------------------------------------
# ② 前置覆盖与候选缺口
# ---------------------------------------------------------------

def test_ambient_condition_is_not_a_gap():
    nodes = [_node("n1", "抓握杯子", 0.0, 1.0, [1], ["左手"]),
             _node("n2", "举杯", 1.0, 2.0, [2], ["左臂"],
                   pre=["操作者处于直立站立状态"])]
    actions = [_act(1, "左手", "左手建立抓握", 0.0, 1.0, "transition"),
               _act(2, "左臂", "左臂向上抬起", 1.0, 2.0)]
    actions[1]["state_before"] = "操作者处于直立站立状态"
    r = reasoning.audit(_bundle(nodes, actions))
    assert r["stats"]["gaps"] == 0
    assert any(c["verdict"] == "ambient" for c in r["checks"])


def test_unprovided_condition_becomes_candidate_gap_not_fact():
    nodes = [_node("n1", "抓握杯子", 0.0, 1.0, [1], ["左手"]),
             _node("n2", "举杯", 1.0, 2.0, [2], ["左臂"],
                   pre=["杯子里已经装满了热水"])]
    actions = [_act(1, "左手", "左手建立抓握", 0.0, 1.0, "transition"),
               _act(2, "左臂", "左臂向上抬起", 1.0, 2.0)]
    b = _bundle(nodes, actions)
    r = reasoning.audit(b)
    assert r["stats"]["gaps"] == 1
    g = r["gaps"][0]
    assert g["status"] == "candidate"            # 候选，不是事实
    assert any(x["kind"] == "propose_gap" for x in r["revisions"])
    # 缺口不改变图的结构：节点数、边数不变
    assert len(b["operations"]["nodes"]) == 2


# ---------------------------------------------------------------
# ③ 持续约束
# ---------------------------------------------------------------

def test_hold_gap_flagged_when_no_maintain_covers():
    nodes = [_node("n1", "搬运杯子", 0.0, 4.0, [1], ["左臂", "左腿"],
                   pre=["杯子被左手稳定握持"],
                   post=["杯子到达目标位置"])]
    actions = [_act(1, "左臂", "左臂向前伸出", 0.0, 4.0)]
    r = reasoning.audit(_bundle(nodes, actions))
    holds = [c for c in r["checks"] if c["kind"] == "hold"]
    assert holds and holds[0]["verdict"] == "uncovered"
    assert holds[0]["action"] == "flag"


def test_hold_covered_by_maintain_action():
    nodes = [_node("n1", "搬运杯子", 0.0, 4.0, [1, 2], ["左臂", "左腿"],
                   pre=["杯子被左手稳定握持"], post=["杯子到达目标位置"])]
    actions = [_act(1, "左臂", "左臂向前伸出", 0.0, 4.0),
               _act(2, "左手", "左手保持抓握杯子", 0.0, 4.0, "maintain", True, "抓握",
                    state_after="杯子被左手稳定握持")]
    r = reasoning.audit(_bundle(nodes, actions))
    holds = [c for c in r["checks"] if c["kind"] == "hold"]
    assert holds and holds[0]["verdict"] == "covered"


# ---------------------------------------------------------------
# ④ 预期 vs 证据
# ---------------------------------------------------------------

def test_effect_category_alone_does_not_prove_stable_grasp():
    """抓握类别不证明已经稳定握持指定物体，必须保留待核实。"""
    nodes = [_node("n1", "抓握杯子", 0.0, 1.0, [1], ["左手"],
                   post=["左手稳定握持杯子"])]
    actions = [_act(1, "左手", "左手建立抓握", 0.0, 1.0, "transition", True, "抓握",
                    state_after="抓握")]
    r = reasoning.audit(_bundle(nodes, actions))
    ev = [c for c in r["checks"] if c["kind"] == "evidence"]
    assert ev and ev[0]["verdict"] == "weak"


def test_evidence_weak_flags_mismatch():
    nodes = [_node("n1", "打开阀门", 0.0, 1.0, [1], ["左手"],
                   post=["阀门处于完全打开状态"])]
    actions = [_act(1, "左手", "左手建立抓握", 0.0, 1.0, "transition")]
    r = reasoning.audit(_bundle(nodes, actions))
    ev = [c for c in r["checks"] if c["kind"] == "evidence"]
    assert ev and ev[0]["verdict"] == "weak" and ev[0]["action"] == "flag"


# ---------------------------------------------------------------
# 观测顺序 vs 执行依赖 + 可追溯校验
# ---------------------------------------------------------------

def test_order_only_edge_is_marked_as_observed_order():
    nodes = [_node("n1", "走到桌边", 0.0, 1.0, [1], ["左腿"]),
             _node("n2", "抓握杯子", 1.0, 2.0, [2], ["左手"])]
    actions = [_act(1, "左腿", "左腿向前迈步", 0.0, 1.0),
               _act(2, "左手", "左手建立抓握", 1.0, 2.0, "transition")]
    b = _bundle(nodes, actions)
    r = reasoning.audit(b)
    edge = b["operations"]["edges"][0]
    assert edge["basis"] == "observed_order"        # 不固化成执行约束
    assert r["stats"]["order_only"] == 1


# ---------------------------------------------------------------
# 中间触发条件（“a 执行一半要发 b”的可计算形式）
# ---------------------------------------------------------------

def test_partial_overlap_yields_middle_trigger():
    """源操作尚未结束、但后继有子步骤在源条件产生之后才开始 → 保留因果，并写出触发点。"""
    nodes = [_node("n1", "下蹲弯腰", 2.0, 3.5, [1], ["左腿", "右腿"],
                   post=["男子蹲在纸箱旁"]),
             _node("n2", "抓取纸箱", 2.5, 4.0, [2, 3], ["左臂", "右手"],
                   pre=["男子蹲在纸箱旁"])]
    actions = [_act(1, "右腿", "右腿弯曲下蹲", 2.0, 3.5, world_after=["男子蹲在纸箱旁"]),
               _act(2, "右臂", "右臂向前伸出", 2.5, 3.5),
               _act(3, "右手", "右手抓握纸箱", 3.5, 3.8, "transition")]
    rels = [{"relation": "sequence", "from": 1, "to": 3}]
    b = _bundle(nodes, actions, rels)
    r = reasoning.audit(b)
    assert r["stats"]["partial_triggers"] == 1
    assert r["stats"]["downgraded"] == 0
    e = b["operations"]["edges"][0]
    assert e["relation"] == "enables"            # 因果保留，不是并列
    t = e["trigger"]
    assert t["type"] == "partial"
    assert t["event"]["ref"] == 1                 # 触发点是源动作 #1 完成
    assert 3 in t["unlocks"]                     # 解锁了 #3 抓握


def test_overlap_without_later_step_still_downgrades():
    """源操作未结束、后继也没有之后的子步骤 → 不能伪造完成依赖，只能降级。"""
    nodes = [_node("n1", "举升纸箱", 0.0, 3.0, [1], ["左臂"], post=["纸箱离开地面"]),
             _node("n2", "同时侧移", 0.5, 1.0, [2], ["左腿"], pre=["纸箱离开地面"])]
    actions = [_act(1, "左臂", "左臂向上抬起", 0.0, 3.0, world_after=["纸箱离开地面"]),
               _act(2, "左腿", "左腿向侧方迈步", 0.5, 1.0)]
    rels = [{"relation": "sequence", "from": 1, "to": 2}]
    b = _bundle(nodes, actions, rels)
    r = reasoning.audit(b)
    assert r["stats"]["partial_triggers"] == 0
    assert r["stats"]["downgraded"] == 1


def test_program_prints_after_action_for_partial_trigger():
    """程序文本要把中间触发写成 AFTER_ACTION，而不是整段操作的 COMPLETED。"""
    from video2op import program
    nodes = [_node("n1", "下蹲弯腰", 2.0, 3.5, [1], ["左腿"], post=["男子蹲在纸箱旁"]),
             _node("n2", "抓取纸箱", 2.5, 4.0, [2, 3], ["右手"], pre=["男子蹲在纸箱旁"])]
    actions = [_act(1, "右腿", "右腿弯曲下蹲", 2.0, 3.5, world_after=["男子蹲在纸箱旁"]),
               _act(2, "右臂", "右臂向前伸出", 2.5, 3.5),
               _act(3, "右手", "右手抓握纸箱", 3.5, 3.8, "transition")]
    b = _bundle(nodes, actions, [{"relation": "sequence", "from": 1, "to": 3}])
    b["reasoning"] = reasoning.audit(b)
    p = program.build(b)
    code = "\n".join(p["code"])
    assert "AFTER_ACTION(#1)" in code
    assert "中间触发" in code


def test_validate_reasoning_traceability():
    nodes = [_node("n1", "抓握杯子", 0.0, 1.0, [1], ["左手"], post=["左手稳定握持杯子"]),
             _node("n2", "举杯", 1.0, 2.0, [2], ["左臂"], pre=["左手稳定握持杯子"])]
    actions = [_act(1, "左手", "左手建立抓握", 0.0, 1.0, "transition"),
               _act(2, "左臂", "左臂向上抬起", 1.0, 2.0)]
    b = _bundle(nodes, actions)
    b["reasoning"] = reasoning.audit(b)
    r = s06_validate._check_reasoning(b)
    assert r["status"] == "pass", r["detail"]


def test_validate_reasoning_flags_broken_reference():
    b = {"operations": {"nodes": [{"id": "n1"}], "edges": []},
         "reasoning": {"checks": [{"id": "c1", "kind": "edge_support",
                                   "edge": ["n9", "n8"], "action": "keep"}],
                       "gaps": [{"node": "n7"}]}}
    r = s06_validate._check_reasoning(b)
    assert r["status"] == "warn"
    assert len(r["detail"]) >= 2
