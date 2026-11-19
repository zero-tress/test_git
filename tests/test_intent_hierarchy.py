"""Hierarchical task intents, scoped evidence and visible before/after scores."""
from copy import deepcopy
import xml.etree.ElementTree as ET

import pytest

from video2op.intent_hierarchy import CHECK_KEYS, export_hierarchy, validate_intents, validate_updates
from video2op.learning_alignment import apply_intent_updates
from video2op.render import intent_hierarchy_html, intent_scores_svg
from video2op.single_video.stages import s02a_intent, s03_sync


def case():
    children = [
        {"id": "clear", "parent_intent_id": "task", "statement": "清障", "optional": True, "confidence": 0.7},
        {"id": "grasp", "parent_intent_id": "task", "statement": "抓取目标", "optional": False, "confidence": 0.9},
        {"id": "place", "parent_intent_id": "task", "statement": "放置目标", "optional": False, "confidence": 0.3},
    ]
    actions = [{"id": i, "inferred": False} for i in range(1, 5)]
    nodes = [{"id": f"node_{i}", "atomic_refs": [i]} for i in range(1, 5)]
    def checks(refs):
        return [{"check": key, "verdict": "partial" if refs else "unknown",
                 "evidence_refs": refs, "reason": "证据及限制"} for key in CHECK_KEYS]
    return {
        "intents": {"intents": [{"id": "task", "statement": "桌面取放", "confidence": 0.8, "subtasks": children}]},
        "atomic": {"atomic_actions": actions}, "task_nodes": {"task_nodes": nodes},
        "sync": {
            "checks": checks([1, 2, 3, 4]),
            "intent_updates": [{"intent_id": "task", "confidence": 0.85, "checks": checks([1, 2, 3, 4])}],
            "subtask_updates": [
                {"intent_id": "clear", "parent_intent_id": "task", "status": "observed",
                 "node_refs": ["node_1", "node_2", "node_3"], "atomic_refs": [1, 2, 3],
                 "confidence": 0.6, "checks": checks([1, 2, 3])},
                {"intent_id": "grasp", "parent_intent_id": "task", "status": "observed",
                 "node_refs": ["node_4"], "atomic_refs": [4], "confidence": 0.95, "checks": checks([4])},
                {"intent_id": "place", "parent_intent_id": "task", "status": "not_observed",
                 "node_refs": [], "atomic_refs": [], "confidence": 0.25, "checks": checks([])},
            ],
        },
    }


def validate(bundle):
    validate_updates(bundle["sync"], bundle["intents"], bundle["task_nodes"]["task_nodes"],
                     bundle["atomic"]["atomic_actions"])


def test_parent_and_coexisting_subtasks_update_independently_and_idempotently():
    b = case()
    validate_intents(b["intents"], require_hierarchy=True)
    validate(b)
    apply_intent_updates(b)
    task = b["intents"]["intents"][0]
    assert task["confidence_before_sync"] == 0.8 and task["confidence"] == 0.85
    assert [s["id"] for s in task["subtasks"]] == ["clear", "grasp", "place"]
    assert [s["confidence"] for s in task["subtasks"]] == [0.6, 0.95, 0.25]
    assert sum(s["confidence"] for s in task["subtasks"]) > 1
    before = deepcopy(b)
    apply_intent_updates(b)
    assert before == b


@pytest.mark.parametrize("score", [float("nan"), float("inf"), True, -0.1, 1.1, "0.9"])
def test_invalid_hierarchical_confidence_rejected(score):
    b = case()
    b["intents"]["intents"][0]["subtasks"][0]["confidence"] = score
    with pytest.raises(ValueError):
        validate_intents(b["intents"])


@pytest.mark.parametrize("change", ["duplicate_id", "wrong_parent", "missing_optional"])
def test_hierarchy_integrity(change):
    b = case()
    s = b["intents"]["intents"][0]["subtasks"][0]
    if change == "duplicate_id":
        s["id"] = "task"
    elif change == "wrong_parent":
        s["parent_intent_id"] = "other"
    else:
        s.pop("optional")
    with pytest.raises(ValueError):
        validate_intents(b["intents"])


@pytest.mark.parametrize("change", [
    "missing_child", "duplicate_child", "wrong_parent", "bad_node", "bad_atomic", "scope_leak",
    "repeated_question", "mandatory_skip", "unseen_with_refs", "observed_without_refs", "yes_without_evidence",
    "inferred_only_yes", "mismatched_mapping",
])
def test_invalid_sync_is_rejected_and_cannot_mutate_confidences(change):
    b = case()
    row = b["sync"]["subtask_updates"][0]
    if change == "missing_child":
        b["sync"]["subtask_updates"].pop()
    elif change == "duplicate_child":
        b["sync"]["subtask_updates"].append(deepcopy(row))
    elif change == "wrong_parent":
        row["parent_intent_id"] = "other"
    elif change == "bad_node":
        row["node_refs"] = ["invented"]
    elif change == "bad_atomic":
        row["atomic_refs"] = [99]
    elif change == "scope_leak":
        row["checks"][0]["evidence_refs"] = [4]
    elif change == "repeated_question":
        row["checks"][0]["check"] = CHECK_KEYS[1]
    elif change == "mandatory_skip":
        b["sync"]["subtask_updates"][2]["status"] = "not_applicable"
    elif change == "unseen_with_refs":
        row["status"] = "not_observed"
    elif change == "observed_without_refs":
        row.update(node_refs=[], atomic_refs=[])
    elif change == "yes_without_evidence":
        row["checks"][0].update(verdict="yes", evidence_refs=[])
    elif change == "inferred_only_yes":
        b["atomic"]["atomic_actions"][0]["inferred"] = True
        row["checks"][0].update(verdict="yes", evidence_refs=[1])
    else:
        row["atomic_refs"] = [1]
    with pytest.raises(ValueError):
        validate(b)
    original = deepcopy(b["intents"])
    apply_intent_updates(b)
    assert b["intents"] == original
    assert b["intent_alignment"]["issues"]


def test_optional_skip_does_not_force_parent_score_down():
    b = case()
    row = b["sync"]["subtask_updates"][0]
    row.update(status="not_applicable", node_refs=[], atomic_refs=[])
    for check in row["checks"]:
        check.update(verdict="unknown", evidence_refs=[])
    validate(b)
    apply_intent_updates(b)
    assert b["intents"]["intents"][0]["confidence"] == 0.85


def test_export_maps_composite_subtask_through_split_and_merge():
    b = case()
    apply_intent_updates(b)
    b["learning_alignment"] = {"source_to_final": {
        "node_1": ["final_a", "final_b"], "node_2": ["final_c"], "node_3": ["final_c"], "node_4": ["final_d"]}}
    b["task_nodes"] = {"task_nodes": [{"id": key} for key in ["final_a", "final_b", "final_c", "final_d"]]}
    hierarchy = export_hierarchy(b, {key: f"N{i}" for i, key in enumerate(["final_a", "final_b", "final_c", "final_d"], 1)})
    clear, grasp, place = hierarchy["tasks"][0]["subtasks"]
    assert clear["operation_mapping"]["node_refs"] == ["N1", "N2", "N3"]
    assert clear["operation_mapping"]["atomic_refs"] == [1, 2, 3]
    assert place["operation_mapping"]["node_refs"] == []
    assert place["operation_mapping"]["status"] == "not_observed"
    assert grasp["operation_mapping"]["node_refs"] == ["N4"]


def test_normalization_keeps_child_order_and_filters_child_body_hints():
    b = case()
    b["intents"]["intents"][0]["subtasks"][0]["required_body_parts"] = [
        {"part": "头", "role": "观察"}, {"part": "双手", "role": "操作"}]
    normalized = s02a_intent._normalize(b["intents"])
    children = normalized["intents"][0]["subtasks"]
    assert [s["id"] for s in children] == ["clear", "grasp", "place"]
    assert [r["part"] for r in children[0]["required_body_parts"]] == ["左手", "右手"]


def test_no_scalar_is_invented_for_multi_level_sync():
    normalized = s03_sync._normalize(case()["sync"])
    assert normalized["intent_confidence_after"] is None
    assert normalized["intent_confidence_before"] is None


def test_html_svg_include_every_intent_before_after_and_escape_text():
    b = case()
    apply_intent_updates(b)
    b["intents"]["intents"][0]["statement"] += '<script>alert(1)</script>'
    html = intent_hierarchy_html(b)
    svg = intent_scores_svg('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="300" viewBox="0 0 800 300"></svg>', b)
    ET.fromstring(svg)
    for doc in [html, svg]:
        assert "0.80 → 0.85" in doc
        assert "0.70 → 0.60" in doc
        assert "0.90 → 0.95" in doc
        assert "0.30 → 0.25" in doc
        assert "清障" in doc and "放置目标" in doc and "未观察" in doc
        assert "<script>" not in doc
    assert float(ET.fromstring(svg).attrib["height"]) > 300


def test_unsynchronized_scores_are_shown_as_pending():
    b = case()
    assert "0.80 → 待校验" in intent_hierarchy_html(b)


def test_mapping_list_preserves_state_goal_provenance_without_implying_sequence():
    from video2op.render import _intent_mapping
    b = {"semantic_graph": {"nodes": {"N1": {"name": "打开"}, "N2": {"name": "靠近"}},
                            "evidence": {"N1": {"atomic_refs": []}, "N2": {"atomic_refs": [1]}}}}
    text = _intent_mapping({"operation_mapping": {"node_refs": ["N1", "N2"]}}, b)
    assert "状态目标" in text
    assert "→" not in text
