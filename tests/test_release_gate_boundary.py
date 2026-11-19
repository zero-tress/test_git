"""Regression checks for release boundaries, graph geometry and later cycles."""
import re
import xml.etree.ElementTree as ET
from copy import deepcopy

import pytest
from test_arm_hand_scope import example
from test_single_actor_v4 import graph

from video2op import semantic
from video2op.single_video.pipeline import build_learning_graph


@pytest.mark.parametrize("overlapping_observation", [False, True])
def test_release_precedes_next_approach_without_losing_parallel_preparation(overlapping_observation):
    b = example()
    extra = deepcopy(b["atomic"]["atomic_actions"])
    for a in extra:
        a["id"] += 10
        a["start"] += 8
        a["end"] += 8
    if overlapping_observation:
        extra[0]["start"] = 5.5  # first release is observed during [5, 6]
    # This scenario switches directly to the next object without a retreat.
    b["atomic"]["atomic_actions"] = [a for a in b["atomic"]["atomic_actions"] if a["id"] != 7]
    b["atomic"]["atomic_actions"].extend(extra)
    build_learning_graph(b)
    tasks = b["task_nodes"]["task_nodes"]
    releases = [n for n in tasks if n["name"] == "释放"]
    approaches = [n for n in tasks if n["name"] == "靠近"]
    openings = [n for n in tasks if n["name"] == "打开"]
    layers = {nid: i for i, col in enumerate(b["operations"]["semantic_columns"]) for nid in col}
    assert layers[releases[0]["id"]] < layers[approaches[1]["id"]]
    assert layers[approaches[1]["id"]] == layers[openings[1]["id"]]
    for release in releases:
        for approach in approaches:
            assert layers[release["id"]] != layers[approach["id"]]
    before = deepcopy(b["operations"])
    build_learning_graph(b)
    assert b["operations"] == before


def test_persistent_arrow_ends_at_pre_release_gate_and_keeps_relation_identity(tmp_path):
    b = graph()
    semantic.render(b, tmp_path)
    tree = ET.fromstring((tmp_path / "operations.svg").read_text())
    ns = {"s": "http://www.w3.org/2000/svg"}
    release = next(n["id"] for n in b["task_nodes"]["task_nodes"] if n["name"] == "释放")
    gate_id = next(g["id"] for g in b["gates"]["gates"] if release in g["to"])
    arrow = tree.find(".//s:path[@class='gs-line hold']", ns)
    assert arrow.get("data-to") == release  # click still opens the grip relation
    assert arrow.get("data-visual-to") == gate_id
    gate = tree.find(f".//s:g[@data-gate='{gate_id}']", ns)
    vertices = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", gate.find("s:path", ns).get("d"))]
    bottom = vertices[4:6]
    match = re.search(r"H ([\d.]+) V ([\d.]+)$", arrow.get("d"))
    assert [float(x) for x in match.groups()] == bottom


def test_gate_dimensions_are_three_quarters_and_labels_stay_centered(tmp_path):
    b = graph()
    semantic.render(b, tmp_path)
    ns = {"s": "http://www.w3.org/2000/svg"}
    tree = ET.fromstring((tmp_path / "operations.svg").read_text())
    for gate in tree.findall(".//s:g[@class='gs-gate']", ns):
        values = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", gate.find("s:path", ns).get("d"))]
        xs, ys = values[::2], values[1::2]
        assert max(xs) - min(xs) == 220 * 0.75
        assert max(ys) - min(ys) == 136 * 0.75
        label = gate.find("s:text", ns)
        assert float(label.get("x")) == (min(xs) + max(xs)) / 2
        assert float(label.get("y")) == (min(ys) + max(ys)) / 2
        assert label.get("text-anchor") == "middle"
        assert label.get("dominant-baseline") == "central"
