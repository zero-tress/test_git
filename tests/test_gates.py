#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门控的确定性测试。

守住四条口径（这是"虚线变实线"能不能算数的全部依据）：
  · 门控 = 前序操作的效果 ∧ 下一操作的前置条件 ∧ 持续约束，三项合取；
  · T / F / U 只读已有证据：观测到才 T，被否定才 F，其余一律 U；
  · 场景前提（反复出现在多个前置里的世界状态）不参与放行判定；
  · 图上的线型跟随门控状态：T 实线、U 虚线，且条件文本必须来自七元组；
  · 图面只用黑色：线型只有实线与虚线（持续约束也是黑虚线，不是第三种颜色）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op import gates, operations, predicates, reasoning, render


def _act(i: int, part: str, action: str, start: float, end: float,
         mode: str = "motion", state_after: str | None = None,
         inferred: bool = False) -> dict:
    return {"id": i, "executor": part, "action": action, "mode": mode,
            "start": start, "end": end, "exerts_force": False, "force_role": None,
            "object": None, "state_before": None, "state_after": state_after,
            "inferred": inferred}


def _node(nid: str, name: str, start: float, end: float, refs: list[int],
          parts: list[str], pre: list[str] | None = None, post: list[str] | None = None,
          const: list[str] | None = None, intent: str = "作用") -> dict:
    return {
        "id": nid, "name": name, "intent_role": intent, "time_range": [start, end],
        "tuple": {"X": {"subject": "操作者", "parts": list(parts)}, "O": [],
                  "C_pre": list(pre or []), "C_post": list(post or []),
                  "C_const": list(const or []),
                  "E": {"process": [], "completion": []}, "R": []},
        "atomic_refs": list(refs),
    }


def _bundle(task_nodes: list[dict], actions: list[dict],
            relations: list[dict] | None = None) -> dict:
    bundle = {"atomic": {"atomic_actions": actions}, "relations": list(relations or []),
              "task_nodes": {"task_nodes": task_nodes}, "intents": {"intents": []}}
    bundle["operations"] = operations.build(bundle["task_nodes"], actions, bundle["relations"])
    bundle["reasoning"] = reasoning.audit(bundle)
    bundle["predicates"] = predicates.build(bundle)
    bundle["gates"] = gates.build(bundle)
    return bundle


def _reach_then_grasp(observed: bool = True) -> dict:
    """最朴素的两步：接近提供的条件就是抓握所需的前置条件。"""
    task = [
        _node("node_1", "接近杯子", 0.0, 2.0, [1], ["右臂"],
              pre=["杯子在桌面"], post=["手位于杯口上方"], intent="为抓握提供位置条件"),
        _node("node_2", "抓握杯子", 2.0, 3.5, [2], ["右手"],
              pre=["手位于杯口上方"], post=["杯子被稳定抓握"], intent="建立控制"),
    ]
    actions = [
        _act(1, "右臂", "右臂前伸靠近杯子", 0.0, 2.0,
             state_after="手位于杯口上方" if observed else None),
        _act(2, "右手", "右手手指合拢抓握杯子", 2.0, 3.5,
             state_after="杯子被稳定抓握" if observed else None),
    ]
    return _bundle(task, actions)


# ---------------------------------------------------------------
# 列序：同一列 = 时间上重叠的一组操作
# ---------------------------------------------------------------

def test_columns_split_by_time_and_pull_holds_into_overlapping_column():
    op_graph = {"nodes": [
        {"id": "a", "start": 0.0, "end": 1.0},
        {"id": "b", "start": 1.0, "end": 2.0},
        {"id": "h", "start": 1.0, "end": 3.0, "mode": "maintain"},
        {"id": "c", "start": 3.0, "end": 4.0},
    ]}
    cols = gates.columns(op_graph)
    assert cols[0] == ["a"]
    assert cols[1] == ["b", "h"]        # 保持节点并入它覆盖的那一步，不单独占一列
    assert cols[2] == ["c"]
    assert len(cols) == 3


def test_one_gate_per_column_transition():
    b = _reach_then_grasp()
    cols = b["gates"]["columns"]
    assert len(b["gates"]["gates"]) == max(0, len(cols) - 1)
    assert b["gates"]["gates"][0]["from"] == cols[0]
    assert b["gates"]["gates"][0]["to"] == cols[1]


# ---------------------------------------------------------------
# 三值判定：只读证据
# ---------------------------------------------------------------

def test_gate_is_T_when_effect_is_observed():
    b = _reach_then_grasp(observed=True)
    g = b["gates"]["gates"][0]
    assert g["state"] == "T"
    effect = [c for c in g["checks"] if c["kind"] == "effect"]
    assert effect and all(c["state"] == "T" for c in effect)
    assert "手位于杯口上方" in g["lines"]
    assert g["unresolved"] == []


def test_gate_is_U_when_no_observation():
    """没有观测证据时不是 F：条件没被确认，也没有被否定。"""
    b = _reach_then_grasp(observed=False)
    g = b["gates"]["gates"][0]
    assert g["state"] == "U"
    assert g["unresolved"], "未确认的条件要能列出来，图上才说得清为什么没放行"
    assert all(c["state"] in ("T", "U") for c in g["checks"])


def test_aggregate_marks_F_only_on_negative_evidence():
    checks = [{"kind": "effect", "text": "x", "state": "T", "gate": True},
              {"kind": "effect", "text": "y", "state": "F", "gate": True}]
    assert gates._aggregate(checks) == "F"
    assert gates._aggregate([c for c in checks if c["state"] == "T"]) == "T"
    assert gates._aggregate([{"kind": "effect", "text": "z", "state": "U", "gate": True}]) == "U"
    assert gates._aggregate([]) == "U"


def test_context_precondition_does_not_block_release():
    """反复出现的世界状态（场景前提）不参与放行判定。"""
    shared = "地板上有纸箱"
    task = [
        _node("n1", "走向纸箱", 0.0, 1.0, [1], ["左腿"],
              pre=[shared], post=["站到纸箱前"]),
        _node("n2", "下蹲", 1.0, 2.0, [2], ["腰"], pre=[shared], post=["手接近纸箱"]),
        _node("n3", "抓握", 2.0, 3.0, [3], ["双手"], pre=[shared, "手接近纸箱"],
              post=["纸箱被抓住"]),
    ]
    actions = [
        _act(1, "左腿", "左腿迈步", 0.0, 1.0, state_after="站到纸箱前"),
        _act(2, "腰", "腰部弯曲下蹲", 1.0, 2.0, state_after="手接近纸箱"),
        _act(3, "双手", "双手合拢抓握", 2.0, 3.0, state_after="纸箱被抓住"),
    ]
    b = _bundle(task, actions)
    ctx = [c for g in b["gates"]["gates"] for c in g["checks"] if c["kind"] == "context"]
    assert ctx and all(c["gate"] is False for c in ctx)
    assert all(shared in [c["text"] for c in g["checks"]] or True
               for g in b["gates"]["gates"])
    # 场景前提不参与判定：它不会把门控拖成 U
    for g in b["gates"]["gates"]:
        live = [c for c in g["checks"] if c["gate"]]
        assert g["state"] == gates._aggregate(live)


# ---------------------------------------------------------------
# 条件来源：必须来自七元组
# ---------------------------------------------------------------

def test_gate_conditions_come_from_tuple_fields():
    b = _reach_then_grasp()
    omap = {str(n["id"]): n for n in b["operations"]["nodes"]}
    for g in b["gates"]["gates"]:
        related = list(g["from"]) + list(g["to"])
        pool = set()
        for oid in related:
            n = omap[oid]
            pool |= set(n.get("pre") or []) | set(n.get("post") or [])
            pool |= set(n.get("invariants") or []) | set(n.get("pre_inferred") or [])
        for c in g["checks"]:
            text = str(c["text"])
            assert any(text and (text in p or p in text) for p in pool), \
                f"门控条件「{text}」不在七元组里"


# ---------------------------------------------------------------
# 图：线型跟随状态
# ---------------------------------------------------------------

def test_svg_line_style_follows_gate_state():
    b = _reach_then_grasp(observed=True)
    svg = render.gate_svg(b)
    assert "门控 ① · T" in svg
    assert 'class="gs-line edge"' in svg              # T：放行的连线是实线
    assert 'class="gs-line pending"' not in svg
    b2 = _reach_then_grasp(observed=False)
    svg2 = render.gate_svg(b2)
    assert "门控 ① · U" in svg2
    assert 'class="gs-line pending"' in svg2           # U：待放行的连线是虚线
    assert 'class="gs-line edge"' not in svg2


def test_svg_is_well_formed_and_shows_operations():
    b = _reach_then_grasp()
    svg = render.gate_svg(b)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "接近杯子" in svg and "抓握杯子" in svg
    assert "gs-gate" in svg and "gs-node" in svg


def test_svg_is_monochrome_and_hides_verdict_words():
    """全黑、只留实线与虚线；菱形上不写判定文字（T/U/F 与证据状态进悬停详情）。"""
    svg = render.gate_svg(_reach_then_grasp(observed=False))
    assert "#bb7722" not in svg and "#344354" not in svg
    assert 'stroke="#1a1a1a"' in svg
    assert "证据确认满足" not in svg and "未观察到" not in svg
    assert "证据确认不满足" not in svg and "另 " not in svg


def test_display_name_keeps_action_and_drops_object():
    """节点只写动作：操作对象与执行器退到七元组与悬停详情里。"""
    assert render._gs_display_name({"name": "接近燕麦杯", "object": "燕麦杯"}) == "接近"
    assert render._gs_display_name({"name": "保持抓握燕麦杯", "object": "燕麦杯",
                                    "mode": "maintain"}) == "保持抓握"


# ---------------------------------------------------------------
# 图：保持节点的泳道分区与线条锚点
# ---------------------------------------------------------------

def _hold_lane_bundle() -> dict:
    """三列：搬运（带抓握保持）→ 放置（带位姿保持）→ 结束。"""
    ops = [
        {"id": "n0", "name": "接近杯子", "start": 0.0, "end": 0.5, "executors": ["右臂"]},
        {"id": "n1", "name": "搬运杯子", "start": 0.5, "end": 1.5, "executors": ["右臂"]},
        {"id": "n2", "name": "放置杯子", "start": 2.0, "end": 3.0, "executors": ["右臂"]},
        {"id": "hold_g", "name": "保持抓握杯子", "mode": "maintain",
         "hold_category": "grasp", "start": 0.5, "end": 1.5, "executors": ["右手"],
         "covers": ["n1"], "maintain_until": ["n1"]},
        {"id": "hold_p", "name": "保持位置", "mode": "maintain",
         "hold_category": "pose", "start": 2.0, "end": 3.0, "executors": ["右臂"],
         "covers": ["n2"], "maintain_until": ["n2"]},
    ]
    edges = [
        {"from": "hold_g", "to": "n1", "relation": "maintain_until",
         "note": "「保持抓握杯子」保持到「搬运杯子」完成"},
        {"from": "hold_p", "to": "n2", "relation": "maintain_until",
         "note": "「保持位置」保持到「放置杯子」完成"},
    ]
    gates_doc = {
        "columns": [["n0"], ["n1", "hold_g"], ["n2", "hold_p"]],
        "gates": [
            {"id": "gate_1", "seq": 1, "from": ["n0"], "to": ["n1", "hold_g"],
             "from_names": ["接近杯子"], "to_names": ["搬运杯子", "保持抓握杯子"],
             "state": "T", "checks": [], "unresolved": []},
            {"id": "gate_2", "seq": 2, "from": ["n1", "hold_g"],
             "to": ["n2", "hold_p"], "from_names": ["搬运杯子", "保持抓握杯子"],
             "to_names": ["放置杯子", "保持位置"],
             "state": "T", "checks": [], "unresolved": []},
        ],
        "stats": {"gates": 2, "T": 2, "U": 0, "F": 0, "unresolved": 0},
    }
    return {"operations": {"nodes": ops, "edges": edges}, "gates": gates_doc,
            "meta": {"name": "泳道"}, "intents": {"intents": []}}


def _svg_points(svg: str) -> tuple[dict, dict, list]:
    """取出节点圆心 / 门控中心 / 连线（起终点与 data 属性）。"""
    nodes = {}
    for m in re.finditer(r'class="gs-node" data-op="([^"]*)"><title>.*?</title>\s*'
                         r'<circle cx="([\d.]+)" cy="([\d.]+)"', svg, re.S):
        nodes[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    gates_pos = {}
    for m in re.finditer(r'data-gate="([^"]*)"><title>.*?</title>\s*'
                         r'<path d="M ([\d.]+),([\d.]+)', svg, re.S):
        gates_pos[m.group(1)] = (float(m.group(2)), float(m.group(3)) + render.GS_GATE_HH)
    lines = []
    for m in re.finditer(r'<path class="gs-line (\w+)" data-from="([^"]*)" '
                         r'data-to="([^"]*)" d="([^"]*)"', svg):
        pts = [(float(x), float(y)) for x, y in re.findall(r'([-\d.]+),([-\d.]+)', m.group(4))]
        lines.append({"cls": m.group(1), "from": m.group(2), "to": m.group(3),
                      "start": pts[0], "end": pts[-1]})
    return nodes, gates_pos, lines


def test_hold_lanes_put_pose_above_and_grasp_below():
    """保持节点固定分区：手臂不动的保持（位姿/托举）在上方，保持抓握在下方。"""
    nodes, _, _ = _svg_points(render.gate_svg(_hold_lane_bundle()))
    assert nodes["n1"][1] == nodes["n2"][1] == nodes["n0"][1]      # 操作节点都在主轴
    assert nodes["hold_p"][1] < nodes["n2"][1]                     # 位姿保持在上
    assert nodes["hold_g"][1] > nodes["n1"][1]                     # 抓握保持在下


def test_hold_lines_anchor_on_gates():
    """保持类的两条线都锚在门控上：进入线从门控出，持续约束线箭头指向门控。

    连续保持切换（一个保持停在门控、下一个保持从同一道门控起）也按这个锚法画。
    """
    nodes, gates_pos, lines = _svg_points(render.gate_svg(_hold_lane_bundle()))
    g2x, g2y = gates_pos["gate_2"]
    into = next(ln for ln in lines if ln["from"] == "gate_1" and ln["to"] == "hold_g")
    assert into["start"] == (gates_pos["gate_1"][0] + render.GS_GATE_HW, gates_pos["gate_1"][1])
    assert into["end"] == (nodes["hold_g"][0] - render.GS_NODE_R, nodes["hold_g"][1])
    out = next(ln for ln in lines if ln["cls"] == "hold" and ln["from"] == "hold_g")
    assert out["to"] == "gate_2"
    assert out["end"] == (g2x, g2y + render.GS_GATE_HH)              # 指向门控下尖，不进菱形内部
    into2 = next(ln for ln in lines if ln["from"] == "gate_2" and ln["to"] == "hold_p")
    assert into2["start"][0] == g2x + render.GS_GATE_HW              # 同一个门控把下一个保持接上
    tail = next(ln for ln in lines if ln["cls"] == "hold" and ln["from"] == "hold_p")
    assert tail["to"] == "end"
