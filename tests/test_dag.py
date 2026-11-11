#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作依赖图（DAG）的确定性测试：分层、剔环、并行同层、SVG 渲染。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op import graph, render


def _act(i: int, part: str, action: str, start: float, end: float,
         mode: str = "motion") -> dict:
    return {"id": i, "executor": part, "action": action, "mode": mode,
            "start": start, "end": end}


def _layers_of(g: dict) -> dict[int, int]:
    return {n["id"]: n["layer"] for n in g["nodes"]}


def test_sequence_edge_points_forward():
    acts = [_act(1, "左手", "左手抓握纸箱", 0.0, 0.5, "transition"),
            _act(2, "左臂", "左臂向上抬起托举", 0.5, 2.0)]
    g = graph.build(acts, [{"relation": "sequence", "from": 1, "to": 2, "note": ""}])
    lay = _layers_of(g)
    assert lay[2] > lay[1]
    assert g["edges"] == [{"from": 1, "to": 2, "relation": "sequence", "note": "",
                           "inferred_by": "vlm_window"}]


def test_soft_relations_do_not_become_edges():
    acts = [_act(1, "左臂", "左臂向上抬起", 0.0, 2.0),
            _act(2, "右臂", "右臂向上抬起", 0.0, 2.0)]
    g = graph.build(acts, [{"relation": "parallel", "from": 1, "to": 2}])
    assert g["edges"] == []
    assert g["stats"]["soft_pairs"] == 1


def test_parallel_members_share_layer():
    acts = [_act(1, "左臂", "左臂向上抬起", 0.0, 2.0),
            _act(2, "右臂", "右臂向上抬起", 0.0, 2.0),
            _act(3, "左手", "左手抓握纸箱", 2.0, 2.4, "transition")]
    rels = [{"relation": "parallel", "from": 1, "to": 2},
            {"relation": "sequence", "from": 1, "to": 3},
            {"relation": "sequence", "from": 2, "to": 3}]
    g = graph.build(acts, rels)
    lay = _layers_of(g)
    assert lay[1] == lay[2]
    assert lay[3] > lay[1]


def test_parallel_conflicting_with_sequence_is_ignored():
    """同一对节点既有先后又有并行时，并行同层约束应被放弃（否则层号会被无限推高）。"""
    acts = [_act(1, "左手", "左手抓握纸箱", 0.0, 0.5, "transition"),
            _act(2, "左臂", "左臂向上抬起", 0.5, 2.0)]
    rels = [{"relation": "sequence", "from": 1, "to": 2},
            {"relation": "parallel", "from": 1, "to": 2}]
    g = graph.build(acts, rels)
    lay = _layers_of(g)
    assert lay[2] == lay[1] + 1
    assert max(lay.values()) < 10


def test_back_edge_dropped_and_reported():
    """构成环的边必须被剔除，输出保证是 DAG。"""
    acts = [_act(1, "左臂", "左臂向前伸出", 0.0, 1.0),
            _act(2, "左手", "左手抓握纸箱", 1.0, 1.5, "transition"),
            _act(3, "左臂", "左臂收回", 1.5, 2.5)]
    rels = [{"relation": "sequence", "from": 1, "to": 2},
            {"relation": "sequence", "from": 2, "to": 3},
            {"relation": "sequence", "from": 3, "to": 1}]  # 3 → 1 会成环
    g = graph.build(acts, rels)
    assert len(g["dropped_edges"]) == 1
    assert g["dropped_edges"][0]["from"] == 3
    lay = _layers_of(g)
    for e in g["edges"]:
        assert lay[e["to"]] > lay[e["from"]], e


def test_layers_are_compact_and_grouped():
    acts = [_act(1, "左腿", "左腿向前迈步", 0.0, 1.0),
            _act(2, "左手", "左手抓握纸箱", 1.0, 1.5, "transition")]
    g = graph.build(acts, [{"relation": "sequence", "from": 1, "to": 2}])
    assert g["layers"] == [[1], [2]]
    assert sorted(set(_layers_of(g).values())) == [0, 1]


def test_stronger_relation_wins_on_same_pair():
    acts = [_act(1, "左臂", "左臂保持伸出", 0.0, 2.0, "maintain"),
            _act(2, "左手", "左手松开纸箱", 2.0, 2.4, "transition")]
    rels = [{"relation": "sequence", "from": 1, "to": 2},
            {"relation": "maintain_until", "from": 1, "to": 2}]
    g = graph.build(acts, rels)
    assert len(g["edges"]) == 1
    assert g["edges"][0]["relation"] == "maintain_until"


def test_empty_actions():
    g = graph.build([], [])
    assert g["nodes"] == [] and g["layers"] == []
    assert g["stats"]["nodes"] == 0


def test_dag_svg_renders_nodes_and_arrows():
    acts = [_act(1, "左手", "左手抓握纸箱", 0.0, 0.5, "transition"),
            _act(2, "左臂", "左臂保持伸出", 0.5, 2.0, "maintain"),
            _act(3, "左腿", "左腿向前迈步", 0.0, 0.5)]
    rels = [{"relation": "sequence", "from": 1, "to": 2, "note": "接触后抬臂"},
            {"relation": "parallel", "from": 3, "to": 1}]
    g = graph.build(acts, rels)
    svg = render.dag_svg(g)
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert "#1" in svg and "#2" in svg and "#3" in svg
    assert "marker-end" in svg
    assert "操作依赖图" in svg


def test_dag_svg_handles_empty_graph():
    svg = render.dag_svg({})
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
