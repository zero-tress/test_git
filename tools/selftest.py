#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检：模块导入 + 时序逻辑表达 + 操作依赖图 + 校验纪律（不调用模型）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op import gates, graph, logic, render

acts = [
    {"id": 1, "executor": "左腿", "action": "左腿向前迈步", "mode": "motion",
     "start": 0.0, "end": 2.0},
    {"id": 2, "executor": "左手", "action": "左手保持抓握纸箱", "mode": "maintain",
     "start": 2.0, "end": 5.0, "until": {"text": "直到右手松开纸箱"}},
]
rels = [{"relation": "alternation", "from": 1, "to": 2},
        {"relation": "maintain_until", "from": 2, "to": 1}]
L = logic.build(acts, rels)
print("谓词式:", L["predicates"])
print("PLC式 :", L["plc"])
print("HTML 长度:", len(logic.render_html(L)))

G = graph.build(acts, rels)
print("DAG :", G["stats"], "layers=", G["layers"])
svg = render.dag_svg(G)
print("DAG SVG 长度:", len(svg), "｜含箭头:", "marker-end" in svg)
assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")

print("render 模块函数:", [n for n in ("render_report", "render_timeline", "gantt_svg",
                                        "dag_svg", "render_graph", "gate_svg",
                                        "render_operations") if hasattr(render, n)])
print("gates 模块函数:", [n for n in ("build", "columns") if hasattr(gates, n)])

# 门控图：最小两列输入也要能出图，且 T / U 的线型不同
_min_bundle = {"operations": {"nodes": [
    {"id": "a", "name": "接近", "start": 0.0, "end": 1.0, "executors": ["右臂"],
     "pre": [], "post": ["手到位"], "invariants": []},
    {"id": "b", "name": "抓握", "start": 1.0, "end": 2.0, "executors": ["右手"],
     "pre": ["手到位"], "post": ["抓稳"], "invariants": []},
]}, "atomic": {"atomic_actions": []}, "relations": []}
_gdoc = gates.build(_min_bundle)
_min_bundle["gates"] = _gdoc
_gsvg = render.gate_svg(_min_bundle)
print(f"门控: {_gdoc['stats']['gates']} 个（{_gdoc['stats']['T']}/{_gdoc['stats']['U']}），"
      f"SVG 长度 {len(_gsvg)}，含菱形: {'gs-gate' in _gsvg}")
assert _gsvg.startswith("<svg") and _gsvg.rstrip().endswith("</svg>")
