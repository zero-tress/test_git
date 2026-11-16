"""Synthetic graph contracts: no real-video interpretation or model calls."""

import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest

from video2op.cross_video_render import SVG_NS, layout, svg
from video2op.cross_video_workbench import render
from video2op.model_graph_alignment import validate_semantic_merge_policy
from video2op.model_merged_graph import FIELDS
from video2op.workbench import CSS, JS


@pytest.fixture
def graph():
    spec = [
        ("s", "terminal", None, "开始"),
        ("a", "operation", "approach_target", "靠近"),
        ("g", "gate", None, "抓取条件"),
        ("p", "operation", "preparation", "清障"),
        ("b", "operation", "approach_target", "靠近"),
        ("h", "gate", None, "抓取条件"),
        ("z", "operation", "grasp_target", "抓取"),
        ("e", "terminal", None, "结束"),
    ]
    nodes = []
    for key, kind, role, display in spec:
        n = {
            "id": key,
            "kind": kind,
            "label": "synthetic full label " + key,
            "display_label": display,
            "source_case_ids": ["alpha", "beta"],
            "sources": [],
        }
        if kind == "operation":
            n.update(action_role=role, seven_tuple={f: {"synthetic_field": f} for f in FIELDS})
        if kind == "gate":
            n.update(truth="U" if key == "g" else "T", predicate="synthetic predicate", reason="synthetic evidence")
        nodes.append(n)
    edges = []
    for index, (a, b, outcome) in enumerate(
        [
            ("s", "a", None),
            ("a", "g", None),
            ("g", "z", "T"),
            ("g", "p", "F"),
            ("p", "b", None),
            ("b", "h", None),
            ("h", "z", "T"),
            ("z", "e", None),
        ]
    ):
        row = {
            "id": "edge" + str(index),
            "from": a,
            "to": b,
            "label": "满足" if outcome == "T" else "不满足" if outcome == "F" else "transition",
            "source_case_ids": ["alpha", "beta"],
        }
        if outcome:
            row["gate_outcome"] = outcome
        edges.append(row)
    return {
        "title": "合成测试图",
        "start_node_id": "s",
        "end_node_id": "e",
        "nodes": nodes,
        "edges": edges,
        "paths": [],
        "contrastive_examples": [],
    }


def test_svg_keeps_model_data_and_has_no_source_text(graph):
    before = deepcopy(graph)
    root = ET.fromstring(svg(graph))
    assert graph == before
    assert {e.get("data-node-id") for e in root.iter() if e.get("data-node-id")} == {n["id"] for n in graph["nodes"]}
    visible = "".join(t.text or "" for t in root.iter() if t.tag.endswith("}text"))
    assert "来源" not in visible and "alpha" not in visible and "beta" not in visible
    assert visible.count("靠近") == 2 and visible.count("清障") == 1


def test_unsatisfied_detour_is_above_direct_route(graph):
    p, _ = layout(graph)
    assert len({p[n][1] for n in ["s", "a", "g", "z", "e"]}) == 1
    assert p["p"][1] < p["g"][1] and p["b"][1] < p["z"][1]
    assert p["b"][1] < p["h"][1] < p["z"][1]


def test_single_case_node_shapes_and_white_background(graph):
    root = ET.fromstring(svg(graph))
    ns = "{" + SVG_NS + "}"
    assert root.find(ns + "rect").get("fill") == "white"
    by_id = {n.get("data-node-id"): n for n in root.iter() if n.get("data-node-id")}
    assert all(by_id[i].find(ns + "circle") is not None for i in ["a", "p", "b", "z"])
    assert all(by_id[i].find(ns + "path") is not None for i in ["g", "h"])


def test_workbench_reuses_native_style_and_interaction(graph):
    page = render(graph, svg(graph))
    assert CSS in page and JS in page
    assert 'data-id="a"' in page and 'data-gate="g"' in page
    assert all(f + " · " in page for f in FIELDS)
    assert "__NATIVE_" not in page and "__GRAPH_SVG__" not in page
    assert "path-buttons" not in page


def policy():
    return {"semantic_merge_policy": {"operation_role": "preparation", "node_count": 1}}


def test_shared_preparation_accepts_parameterized_model_node(graph):
    validate_semantic_merge_policy(graph, graph, None, policy())


def test_shared_preparation_rejects_per_video_duplicate(graph):
    instance = deepcopy(graph)
    extra = deepcopy(next(n for n in graph["nodes"] if n.get("action_role") == "preparation"))
    extra["id"] = "other-instance"
    graph["nodes"].append(extra)
    with pytest.raises(ValueError, match="one shared preparation"):
        validate_semantic_merge_policy(graph, instance, None, policy())


def test_shared_preparation_retains_all_model_source_support(graph):
    instance = deepcopy(graph)
    next(n for n in graph["nodes"] if n.get("action_role") == "preparation")["source_case_ids"] = ["alpha"]
    with pytest.raises(ValueError, match="all model-observed source support"):
        validate_semantic_merge_policy(graph, instance, None, policy())


def test_display_labels_must_come_from_model(graph):
    instance = deepcopy(graph)
    del graph["nodes"][1]["display_label"]
    with pytest.raises(ValueError, match="supply source-free semantic display_label"):
        validate_semantic_merge_policy(graph, instance, None, policy())
