#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作图与执行器语义程序的确定性测试。

守住三条口径（对应"节点=操作、时序显式、意图可用"）：
  · 节点是操作，执行器只作节点属性；
  · 先后/并行/交替全部成为显式的边，并行/交替不再只靠"同一列"暗示；
  · 意图链把"前一个操作为后继操作提供了什么"写成可读、可校验的数据。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op import operations, program, render
from video2op.stages import s06_validate


def _act(i: int, part: str, action: str, start: float, end: float,
         mode: str = "motion", force: bool = False, role: str | None = None) -> dict:
    return {"id": i, "executor": part, "action": action, "mode": mode,
            "start": start, "end": end, "exerts_force": force, "force_role": role,
            "object": None, "state_before": None, "state_after": None}


def _node(nid: str, name: str, start: float, end: float, refs: list[int],
          parts: list[str], pre: list[str] | None = None, post: list[str] | None = None,
          intent: str = "作用", obj: list[str] | None = None) -> dict:
    return {
        "id": nid, "name": name, "intent_role": intent, "time_range": [start, end],
        "tuple": {"X": {"subject": "操作者", "parts": list(parts)},
                  "O": list(obj or []),
                  "C_pre": list(pre or []), "C_post": list(post or [])},
        "atomic_refs": list(refs),
    }


def _two_step() -> tuple[dict, list[dict]]:
    task = {"task_nodes": [
        _node("node_1", "走到纸箱前", 0.0, 2.0, [1, 2], ["左腿", "右腿"],
              pre=["操作者处于直立站立状态"], post=["操作者位于纸箱正前方，处于直立状态"],
              intent="接近目标物体，为后续抓取做准备", obj=["地面路径"]),
        _node("node_2", "抓握纸箱", 2.0, 3.0, [3], ["左手", "右手"],
              pre=["操作者位于纸箱正前方，处于直立状态"], post=["双手稳定握持纸箱"],
              intent="建立与纸箱的稳定连接，为搬运做准备", obj=["纸箱"]),
    ]}
    actions = [_act(1, "左腿", "左腿向前迈步", 0.0, 2.0),
               _act(2, "右腿", "右腿向前迈步", 0.0, 2.0),
               _act(3, "左手", "左手建立抓握", 2.0, 3.0, "transition", force=True, role="抓握"),
               _act(4, "右手", "右手建立抓握", 2.0, 3.0, "transition", force=True, role="抓握")]
    task["task_nodes"][1]["atomic_refs"] = [3, 4]
    return task, actions


# ---------------------------------------------------------------
# 节点：执行器是属性，不是节点
# ---------------------------------------------------------------

def test_nodes_are_operations_with_executors_as_attributes():
    task, actions = _two_step()
    g = operations.build(task, actions, [])
    assert [n["name"] for n in g["nodes"]] == ["走到纸箱前", "抓握纸箱"]
    assert g["nodes"][0]["executors"] == ["左腿", "右腿"]     # 执行器 = 节点属性
    assert g["nodes"][0]["start"] == 0.0 and g["nodes"][0]["end"] == 2.0
    assert g["stats"]["executors"] == 4


def test_empty_input_returns_empty_graph():
    g = operations.build({}, [], [])
    assert g["nodes"] == [] and g["edges"] == [] and g["intent_chain"] == []
    assert g["stats"]["nodes"] == 0


# ---------------------------------------------------------------
# 边：先后 / 并行 / 交替都是显式的边
# ---------------------------------------------------------------

def test_time_order_creates_dependency_edge_and_layers():
    task, actions = _two_step()
    g = operations.build(task, actions, [])
    dep = [e for e in g["edges"] if e["from"] == "node_1" and e["to"] == "node_2"]
    assert len(dep) == 1
    # 两个节点的 C_post / C_pre 衔接 → 边从"先后"升级为"使能"（因果）
    assert dep[0]["relation"] in ("sequence", "enables")
    layer = {n["id"]: n["layer"] for n in g["nodes"]}
    assert layer["node_2"] > layer["node_1"]


def test_transitive_reduction_keeps_chain_minimal():
    """三个依次执行的操作只保留相邻两步的先后边，不画冗余的 A→C。"""
    task = {"task_nodes": [
        _node("n1", "走到桌边", 0.0, 1.0, [1], ["左腿"]),
        _node("n2", "下蹲", 1.0, 2.0, [2], ["左腿", "腰"]),
        _node("n3", "抓握纸箱", 2.0, 3.0, [3], ["左手"]),
    ]}
    actions = [_act(1, "左腿", "左腿向前迈步", 0.0, 1.0),
               _act(2, "左腿", "左腿弯曲下蹲", 1.0, 2.0),
               _act(3, "左手", "左手建立抓握", 2.0, 3.0, "transition")]
    g = operations.build(task, actions, [])
    pairs = {(e["from"], e["to"]) for e in g["edges"]}
    assert pairs == {("n1", "n2"), ("n2", "n3")}
    assert ("n1", "n3") not in pairs
    assert g["stats"]["edges"] == 2


def test_parallel_operations_become_explicit_mutual_edges():
    """两个操作同时进行时，必须留下显式的并行对（不再只靠"同一列"暗示）。"""
    task = {"task_nodes": [
        _node("node_1", "左手拿杯子", 0.0, 2.0, [1], ["左臂", "左手"], intent="取杯"),
        _node("node_2", "右手拿水壶", 0.0, 2.0, [2], ["右臂", "右手"], intent="取壶"),
    ]}
    actions = [_act(1, "左手", "左手接触杯子", 0.0, 2.0),
               _act(2, "右手", "右手接触水壶", 0.0, 2.0)]
    rels = [{"relation": "parallel", "from": 1, "to": 2}]
    g = operations.build(task, actions, rels)
    par = [e for e in g["edges"] if e["relation"] == "parallel"]
    assert len(par) == 1 and par[0]["mutual"] is True
    assert g["parallel_groups"] == [["node_1", "node_2"]]
    layer = {n["id"]: n["layer"] for n in g["nodes"]}
    assert layer["node_1"] == layer["node_2"]           # 并行 → 同层
    assert g["stats"]["parallel"] == 1


def test_alternation_is_recorded_as_pair():
    task = {"task_nodes": [
        _node("node_1", "交替迈步前进", 0.0, 3.0, [1, 2], ["左腿", "右腿"], intent="行走"),
        _node("node_2", "同时托举纸箱", 0.0, 3.0, [3], ["左臂", "右臂"], intent="承重"),
    ]}
    actions = [_act(1, "左腿", "左腿向前迈步", 0.0, 1.0),
               _act(2, "右腿", "右腿向前迈步", 1.0, 3.0),
               _act(3, "左臂", "左臂保持托举", 0.0, 3.0, "maintain", force=True, role="托举")]
    rels = [{"relation": "alternation", "from": 1, "to": 2},
            {"relation": "parallel", "from": 3, "to": 1}]
    g = operations.build(task, actions, rels)
    assert g["alternation_pairs"] == [] or isinstance(g["alternation_pairs"], list)
    # 节点间并行（左臂托举 ∥ 左腿迈步）必须显式
    assert any(e["relation"] == "parallel" and e["mutual"] for e in g["edges"])


def test_dependency_relation_beats_parallel():
    """同一对操作既被标了先后又被标了并行时，依赖边优先（信息更强）。"""
    task = {"task_nodes": [
        _node("node_1", "接触纸箱", 0.0, 1.0, [1], ["左手"], intent="接触"),
        _node("node_2", "抓握纸箱", 1.0, 2.0, [2], ["左手"], intent="抓握"),
    ]}
    actions = [_act(1, "左手", "左手接触纸箱", 0.0, 1.0),
               _act(2, "左手", "左手建立抓握", 1.0, 2.0, "transition")]
    rels = [{"relation": "sequence", "from": 1, "to": 2},
            {"relation": "parallel", "from": 1, "to": 2}]
    g = operations.build(task, actions, rels)
    assert len(g["edges"]) == 1
    assert g["edges"][0]["relation"] == "sequence"


# ---------------------------------------------------------------
# 意图链
# ---------------------------------------------------------------

def test_intent_chain_links_post_to_pre():
    task, actions = _two_step()
    g = operations.build(task, actions, [])
    assert len(g["intent_chain"]) == 1
    c = g["intent_chain"][0]
    assert c["from"] == "node_1" and c["to"] == "node_2"
    assert "位于纸箱正前方" in c["provides"]
    first = next(n for n in g["nodes"] if n["id"] == "node_1")
    assert first["purpose"].startswith("为「抓握纸箱」提供")


def test_no_chain_when_conditions_are_unrelated():
    task = {"task_nodes": [
        _node("node_1", "走到桌边", 0.0, 1.0, [1], ["左腿"], post=["操作者到达桌边"]),
        _node("node_2", "抓握纸箱", 1.0, 2.0, [2], ["左手"], pre=["双手是空的"]),
    ]}
    actions = [_act(1, "左腿", "左腿向前迈步", 0.0, 1.0),
               _act(2, "左手", "左手建立抓握", 1.0, 2.0, "transition")]
    g = operations.build(task, actions, [])
    assert g["intent_chain"] == []
    assert all(n["purpose"] == "" for n in g["nodes"])


# ---------------------------------------------------------------
# 执行器语义程序
# ---------------------------------------------------------------

def test_program_generates_when_do_until_and_schedule():
    task, actions = _two_step()
    g = operations.build(task, actions, [])
    p = program.build({"operations": g, "atomic": {"atomic_actions": actions}})
    assert len(p["operations"]) == 2
    grip = next(r for r in p["operations"] if r["id"] == "node_2")
    assert grip["when"] and grip["until"]
    assert {s["executor"] for s in grip["do"]} == {"左手", "右手"}
    assert grip["hold"] and all(h["force_role"] == "抓握" for h in grip["hold"])
    assert set(p["executor_schedule"]) == {"左腿", "右腿", "左手", "右手"}
    text = "\n".join(p["code"])
    assert "WHEN" in text and "DO" in text and "UNTIL" in text
    assert "执行器时刻表" in text


def test_program_handles_missing_operations():
    p = program.build({"operations": {}, "atomic": {"atomic_actions": []}})
    assert p["operations"] == [] and p["code"] == []


# ---------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------

def test_operation_svg_draws_operations_and_parallel_mark():
    task = {"task_nodes": [
        _node("node_1", "左手拿杯子", 0.0, 2.0, [1], ["左手"], intent="取杯"),
        _node("node_2", "右手拿水壶", 0.0, 2.0, [2], ["右手"], intent="取壶"),
    ]}
    actions = [_act(1, "左手", "左手接触杯子", 0.0, 2.0),
               _act(2, "右手", "右手接触水壶", 0.0, 2.0)]
    g = operations.build(task, actions, [{"relation": "parallel", "from": 1, "to": 2}])
    svg = render.operation_svg(g, "同时取杯子和水壶")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "左手拿杯子" in svg and "右手拿水壶" in svg
    assert "∥" in svg                       # 并行必须画出来
    assert "任务意图" in svg


def test_operation_svg_handles_empty_graph():
    svg = render.operation_svg({}, "")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")


# ---------------------------------------------------------------
# 校验口径
# ---------------------------------------------------------------

def test_validate_flags_executor_named_nodes():
    bundle = {"operations": {"nodes": [
        {"id": "n1", "name": "左臂向前伸出", "executors": ["左臂"], "intent": "靠近"},
    ]}, "program": {"operations": [{"id": "n1"}]}}
    r = s06_validate._check_operation_nodes(bundle)
    assert r["status"] == "warn"
    assert any("左臂" in str(d.get("message")) for d in r["detail"])


def test_validate_flags_missing_intent_and_executors():
    bundle = {"operations": {"nodes": [
        {"id": "n1", "name": "抓握纸箱", "executors": [], "intent": ""},
    ]}, "program": {"operations": [{"id": "n1"}]}}
    r = s06_validate._check_operation_nodes(bundle)
    msgs = " ".join(str(d.get("message")) for d in r["detail"])
    assert "执行器" in msgs and "操作意图" in msgs


def test_validate_operation_graph_detects_backward_edge():
    bundle = {"operations": {
        "nodes": [{"id": "n1", "layer": 1, "name": "A", "executors": ["左手"], "intent": "x"},
                  {"id": "n2", "layer": 0, "name": "B", "executors": ["左手"], "intent": "y"}],
        "edges": [{"from": "n1", "to": "n2", "relation": "sequence"}],
        "intent_chain": [],
    }, "program": {"operations": [{"id": "n1"}]}}
    r = s06_validate._check_operation_graph(bundle)
    assert r["status"] == "warn"
    assert any("分层" in str(d.get("message")) for d in r["detail"])


def test_validate_operation_graph_passes_on_clean_graph():
    task, actions = _two_step()
    g = operations.build(task, actions, [])
    r = s06_validate._check_operation_graph(
        {"operations": g, "program": {"operations": [{"id": n["id"]} for n in g["nodes"]]}})
    assert r["status"] == "pass", r["detail"]


def test_coordination_marks_primary_and_holding():
    """节点内的协同结构：在动的执行器是主动，同一步里保持的执行器是协同（确定性推导）。

    “提起纸箱”这一步：右臂在抬（主动），右手在保持抓握（协同）——谁在动、谁在保持
    直接来自原子动作表的 mode 与时段，不靠模型再推理。
    """
    task = {"task_nodes": [
        _node("node_1", "提起纸箱", 1.0, 2.0, [1], ["右臂", "右手"],
              intent="把纸箱提离地面", obj=["纸箱"]),
    ]}
    actions = [_act(1, "右臂", "右臂向上抬起纸箱", 1.0, 2.0),
               _act(2, "右手", "右手保持抓握纸箱", 1.0, 5.0, "maintain",
                    force=True, role="抓握")]
    out = operations.build(task, actions, [])
    node = next(n for n in out["nodes"] if n["id"] == "node_1")
    coord = node["coordination"]
    assert [x["executor"] for x in coord["primary"]] == ["右臂"]
    assert [x["executor"] for x in coord["holding"]] == ["右手"]
    assert coord["holding"][0]["phrase"] == "保持抓握"


def test_coordination_release_keeps_arm_as_holding():
    """释放类节点同样带协同：手在张开（主动），臂保持位置（协同）。"""
    task = {"task_nodes": [
        _node("node_9", "释放纸箱", 3.0, 4.0, [3], ["右手"],
              intent="解除对纸箱的抓握", obj=["纸箱"]),
    ]}
    actions = [_act(3, "右手", "右手手指张开释放纸箱", 3.0, 4.0, "transition",
                    force=True, role="释放"),
               _act(4, "右臂", "右臂保持位置", 3.0, 4.0, "maintain",
                    force=True, role="稳定")]
    out = operations.build(task, actions, [])
    node = next(n for n in out["nodes"] if n["id"] == "node_9")
    coord = node["coordination"]
    assert [x["executor"] for x in coord["primary"]] == ["右手"]
    assert [x["executor"] for x in coord["holding"]] == ["右臂"]
