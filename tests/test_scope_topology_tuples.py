"""Protect task support, complete source paths and tuple-only presentation."""
from copy import deepcopy

import pytest

from test_semantic_aggregation import fixture
from video2op.single_video.case_scope_review import validate_retained_operations
from video2op.cross_video.cross_video_tuples import inherit_realizations, validate_tuples
from video2op.cross_video.semantic_aggregation import (
    bind_declared_recheck,
    condition_state_index,
    graph_request,
    inherit_condition_atomic_refs,
    model_input,
    sample_selection_input,
    validate_graph,
)
from video2op.cross_video.semantic_selection import SOURCE_FLOW
from video2op.presentation.semantic_skill_render import _visual_flow, svg


def test_reviewed_clearance_must_survive_and_keep_its_release_in_one_implementation():
    review = {"groups": [
        {"scope": "support", "role": "clearance", "reason": "Opens the space to the target",
         "operation_refs": ["hold_aux", "move_aux", "release_aux"], "downstream_refs": ["reach_goal"]},
        {"scope": "goal", "operation_refs": ["reach_goal"], "reason": "Reach goal", "downstream_refs": []},
    ]}
    ops = {"hold_aux", "move_aux", "release_aux", "reach_goal"}
    goal = {"id": "goal", "role": "approach", "R": [{"operation_refs": ["reach_goal"]}]}
    with pytest.raises(ValueError, match="retained support operations"):
        validate_retained_operations(review, [goal], ops)
    clear = {"id": "clear", "role": "clearance",
             "R": [{"operation_refs": ["hold_aux", "move_aux"]}, {"operation_refs": ["release_aux"]}]}
    with pytest.raises(ValueError, match="complete reviewed clearance"):
        validate_retained_operations(review, [clear, goal], ops)
    clear["R"] = [{"operation_refs": ["hold_aux", "move_aux", "release_aux"]}]
    validate_retained_operations(review, [clear, goal], ops)
    review["groups"][0]["operation_refs"].insert(0, "reach_aux")
    with pytest.raises(ValueError, match="approach operations separate"):
        validate_retained_operations(review, [clear, goal], ops | {"reach_aux"}, {"reach_aux"})


def test_visual_conflict_does_not_remove_source_success_from_topology():
    cases, conditions, rules, graph = fixture()
    cases[0]["graph"]["nodes"][0]["role"] = "clearance"
    selection = {"sample_dispositions": [{"member_ref": "C1:S1", "disposition": "unresolved",
                                          "reason": "Visual interpretation differs"}], "unresolved": ["C1:S1"]}
    reviews = {"sample_groups": [], "sample_reviews": [{"member_ref": "C1:S1", "status": "conflict",
                                                        "review_outcome": "unknown", "reason": "Occluded"}]}
    graph["topology_source"] = SOURCE_FLOW
    graph["sample_selection"] = selection
    graph["sample_reviews"] = reviews
    graph["realizations"][0].update(successful_source_refs=["C1:S1:r1"], usage="success_method")
    checks = graph_request(cases, conditions, rules, None, selection, reviews)["contract_checks"]
    assert checks["main_flow_member_refs"] == ["C1:S1"]
    assert checks["source_success_realization_refs"] == ["C1:S1:r1"]
    assert validate_graph(graph, cases, conditions, rules)["passed"]
    graph["task_nodes"] = []
    with pytest.raises(ValueError, match="task nodes"):
        validate_graph(graph, cases, conditions, rules)


def test_tuple_candidates_are_drawn_without_becoming_new_gates():
    _, _, _, graph = fixture()
    before = _visual_flow(graph)
    row = {"skill_id": "K1", "X": {"role": "执行手"}, "O": {"target": "可抓目标"},
           "C_pre": ["目标在执行器可达范围内"], "C_const": ["过程保持有效约束"],
           "E": {"completion": ["执行器到位"], "process_constraint": ["检查过程"],
                 "implementation_applicability": ["运动范围覆盖目标"]},
           "C_post": ["建立可操作状态"], "R": ["R1"], "evidence_gaps": {}}
    row["evidence"] = {key: ["C1:S1"] for key in ("X", "O", "C_pre", "C_const", "E", "C_post", "R")}
    row["evidence"]["R"] = ["R1"]
    assert validate_tuples({"skill_tuples": [row]}, graph["skills"]) == {"K1": row}
    graph["skill_tuples"] = [row]
    assert before == _visual_flow(graph)
    assert "目标在执行器可达范围内" in svg(graph)
    raw = deepcopy(row)
    raw["R"] = ["incorrectly-renamed"]
    raw["evidence"].pop("R")
    inherited = inherit_realizations({"skill_tuples": [raw]}, graph["skills"])
    assert inherited["skill_tuples"][0]["R"] == ["R1"]
    assert "R1" in inherited["skill_tuples"][0]["evidence"]["R"]
    invalid = deepcopy(row)
    invalid["evidence"]["C_pre"] = ["C2:S9"]
    with pytest.raises(ValueError, match="source members"):
        validate_tuples({"skill_tuples": [invalid]}, graph["skills"])


def test_declared_recheck_reuses_positive_guard_with_fresh_context_and_unknown_truth():
    skills = [{"id": role, "role": role} for role in ("approach", "clearance", "grasp")]
    nodes = [{"id": nid, "skill_id": role, "source_members": [f"C1:{nid}"]} for nid, role in
             [("A1", "approach"), ("C", "clearance"), ("A2", "approach"), ("G", "grasp")]]
    relations = [{"from": "A1", "to": "C", "relation": "branch", "gate_outcome": "F"},
                 {"from": "A1", "to": "G", "relation": "branch", "gate_outcome": "T",
                  "guard": "目标可抓", "guard_truth": "T", "check_context": ["C1:A1"]},
                 {"from": "C", "to": "A2", "relation": "sequence"},
                 {"from": "A2", "to": "G", "relation": "sequence"}]
    graph = {"skills": skills, "task_nodes": nodes, "relations": relations}
    bind_declared_recheck(graph, None)
    assert "condition_check" not in relations[3]
    bind_declared_recheck(graph, {"cross_video": {"branch_policy": {"recheck_after_reapproach": True}}})
    check = relations[3]["condition_check"]
    assert (check["guard"], check["guard_truth"], check["check_context"]) == ("目标可抓", "U", ["C1:A2"])
    assert relations[1]["guard_truth"] == "T"


def test_cross_video_requests_keep_local_evidence_without_repeating_full_artifacts():
    cases, _, _, _ = fixture()
    case = cases[0]
    case["operations"]["large_renderer_payload"] = "x" * 100_000
    case["atomic"][0].update(state_before="empty", state_after="holding")
    inputs = model_input(cases)
    assert "operation_graph" not in inputs["cases"][0]
    assert inputs["cases"][0]["atomic_observations"][0]["state_before"] == "empty"
    assert inputs["condition_refs"]["C1:S1:C_pre:0"]["member_ref"] == "C1:S1"
    assert inputs["member_refs"]["C1:S1"]["R"] == ["C1:S1:r1"]
    review = {"sample_reviews": [{"member_ref": "C1:S1", "status": "conflict", "reason": "uncertain"}]}
    selection = sample_selection_input(cases, review, None)
    assert selection["members"][0]["visual_review"]["status"] == "conflict"
    assert selection["members"][0]["task_outcome"] == case["graph"]["task_outcome"]
    assert selection["members"][0]["local_outcome"] == case["graph"]["nodes"][0]["outcome"]


def test_condition_state_refs_repeat_only_valid_local_phased_pointer():
    cases, conditions, _, _ = fixture()
    cases[0]["atomic"][0].update(state_before="empty", state_after="holding")
    options = condition_state_index(cases)
    fact = conditions["condition_decisions"][0]["evidence"][0]
    local = {"atomic_ref": 1, "field": "state_before"}
    fact.update(phase="pre", atomic_refs=[], state_evidence_refs=[local])
    assert options["C1:S1"]["pre"] == [local]
    result = inherit_condition_atomic_refs(conditions, options)
    assert result["condition_decisions"][0]["evidence"][0]["atomic_refs"] == [1]
    assert fact["atomic_refs"] == []
    fact["state_evidence_refs"] = [{"atomic_ref": 1, "field": "state_after"}]
    result = inherit_condition_atomic_refs(conditions, options)
    assert result["condition_decisions"][0]["evidence"][0]["atomic_refs"] == []
