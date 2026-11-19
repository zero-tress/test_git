"""Contract tests use synthetic records, never substitute video judgments."""
import json
from copy import deepcopy

import pytest

from video2op.cross_video.semantic_aggregation import export, validate_conditions, validate_graph
from video2op.presentation.semantic_skill_render import svg


def fixture():
    node = {"id": "S1", "name": "synthetic skill", "purpose": "test effect", "expected_effects": ["effect"],
            "X": {}, "O": {}, "C_pre": ["ready"], "C_const": [], "C_post": ["effect"],
            "E": {"binding_status": "unbound"}, "R": [{"id": "r1", "name": "test implementation",
                "operation_refs": ["step_1"], "atomic_refs": [1], "status": "observed"}],
            "outcome": "success", "evidence_refs": [1]}
    cases = [{"case_id": "C1", "video_uid": "video-one", "source": "/source/result.json", "source_sha256": "hash",
              "workbench": "/source/workbench.html", "operations_svg": "/source/operations.svg",
              "graph": {"nodes": [node], "relations": [], "task_outcome": "success"},
              "operations": {"nodes": [{"id": "step_1", "name": "test action"}], "edges": []},
              "atomic": [{"id": 1}], "local_observation_records": {}}]
    conditions = {"condition_decisions": [{"id": "D1", "condition": "ready", "kind": "C_pre",
        "source_condition_refs": ["C1:S1:C_pre:0"], "decision": "keep_under_realization", "reason": "insufficient contrast",
        "comparison_context": "synthetic", "evidence": [{"member_ref": "C1:S1", "truth": "T", "phase": "pre", "outcome": "success", "atomic_refs": [1]}],
        "causal_status": "not_established"}], "unresolved": ["negative samples missing"]}
    rules = {"constraints": [], "evaluators": [], "temporal_rules": [], "unresolved": []}
    graph = {"schema_version": "semantic_operation_graph.v1", "title": "test <unsafe>", "purpose": "test & effect",
        "skills": [{"id": "K1", "name": "test <unsafe>", "purpose": "effect", "expected_effects": ["effect"],
            "X": {}, "O": {}, "C_pre": [], "C_const": [], "C_post": ["effect"],
            "E": {"binding_status": "unbound", "detector_ref": None, "controller_ref": None,
                  "completion": [], "process_constraint": [], "implementation_applicability": []}, "R": ["R1"],
            "source_members": ["C1:S1"], "status": "candidate"}],
        "task_nodes": [{"id": "T1", "skill_id": "K1", "source_members": ["C1:S1"]}], "relations": [],
        "realizations": [{"id": "R1", "name": "source realization", "skill_id": "K1", "source_realization_refs": ["C1:S1:r1"],
                          "effect_alignment_reason": "synthetic effect aligned", "condition_decision_refs": ["D1"]}],
        "branch_merges": [], "functional_merges": [], "unresolved": ["unbound"],
        "condition_learning": conditions, "semantic_rules": rules, "provenance": {"model": "qwen3.8-27b"}}
    return cases, conditions, rules, graph


def test_complete_source_path_export_keeps_outcomes(tmp_path):
    cases, conditions, rules, graph = fixture()
    assert validate_graph(graph, cases, conditions, rules)["passed"]
    export(graph, cases, tmp_path)
    saved = json.loads((tmp_path / "G_semantic.json").read_text())
    assert saved["source_paths"][0]["source_node_ids"] == ["S1"]
    assert saved["source_instances"][0]["node"]["outcome"] == "success"
    assert saved["realizations"][0]["source_subgraphs"][0]["nodes"][0]["id"] == "step_1"
    assert saved["execution_enabled"] is False
    assert "&lt;unsafe&gt;" in (tmp_path / "workbench.html").read_text()
    assert "<unsafe>" not in svg(saved)


def test_nonexecution_is_not_failure():
    cases, conditions, _, _ = fixture()
    cases[0]["graph"]["nodes"][0]["outcome"] = "not_executed"
    conditions["condition_decisions"][0]["evidence"][0]["outcome"] = "failure"
    with pytest.raises(ValueError, match="relabel"):
        validate_conditions(conditions, cases)


def test_promotion_requires_real_independent_contrast():
    cases, conditions, _, _ = fixture()
    conditions["condition_decisions"][0]["decision"] = "promote_to_skill"
    with pytest.raises(ValueError, match="independent"):
        validate_conditions(conditions, cases)


@pytest.mark.parametrize("mutation", ["inferred", "outside", "other_skill"])
def test_condition_evidence_stays_with_observed_local_attempt(mutation):
    cases, conditions, _, _ = fixture()
    if mutation == "inferred":
        cases[0]["atomic"][0]["inferred"] = True
    elif mutation == "outside":
        cases[0]["atomic"][0]["media_coverage_status"] = "outside_decoded_coverage"
    else:
        cases[0]["atomic"].append({"id": 2})
        conditions["condition_decisions"][0]["evidence"][0]["atomic_refs"] = [2]
    with pytest.raises(ValueError, match="local skill"):
        validate_conditions(conditions, cases)


def test_unknown_evaluator_reference_is_rejected():
    cases, conditions, rules, graph = fixture()
    graph["skills"][0]["E"]["completion"] = ["missing-rule"]
    with pytest.raises(ValueError, match="Evaluator references"):
        validate_graph(graph, cases, conditions, rules)


def test_canonical_graph_must_reconstruct_source_temporal_edges():
    cases, conditions, rules, graph = fixture()
    second = deepcopy(cases[0]["graph"]["nodes"][0])
    second["id"] = "S2"
    cases[0]["graph"]["nodes"].append(second)
    cases[0]["graph"]["relations"] = [{"from": "S1", "to": "S2", "relation": "sequence", "basis": "observed_order"}]
    graph["skills"][0]["source_members"].append("C1:S2")
    graph["realizations"][0]["source_realization_refs"].append("C1:S2:r1")
    graph["task_nodes"].append({"id": "T2", "skill_id": "K1", "source_members": ["C1:S2"]})
    with pytest.raises(ValueError, match="reconstructable"):
        validate_graph(graph, cases, conditions, rules)
    graph["relations"] = [{"from": "T1", "to": "T2", "relation": "sequence", "basis": "observed_order",
                            "reason": "source relation", "source_relation_refs": ["C1:e0"], "status": "candidate"}]
    assert validate_graph(graph, cases, conditions, rules)["passed"]


def test_false_success_refutes_necessary_precondition():
    cases, conditions, _, _ = fixture()
    other = deepcopy(cases[0])
    other.update(case_id="C2", video_uid="video-two")
    cases.append(other)
    decision = conditions["condition_decisions"][0]
    decision["decision"] = "promote_to_skill"
    decision["source_condition_refs"].append("C2:S1:C_pre:0")
    decision["evidence"][0].update(truth="F", outcome="success")
    cases[1]["graph"]["nodes"][0]["outcome"] = "failure"
    decision["evidence"].append({"member_ref": "C2:S1", "truth": "T", "phase": "pre", "outcome": "failure", "atomic_refs": [1]})
    with pytest.raises(ValueError, match="violation"):
        validate_conditions(conditions, cases)


@pytest.mark.parametrize("change", ["missing_member", "missing_realization", "invented_binding", "unsupported_condition"])
def test_rejects_lost_sources_and_unearned_claims(change):
    cases, conditions, rules, graph = fixture()
    if change == "missing_member":
        graph["skills"][0]["source_members"] = ["C9:invented"]
    elif change == "missing_realization":
        graph["realizations"][0]["source_realization_refs"] = ["C1:S1:invented"]
    elif change == "invented_binding":
        graph["skills"][0]["E"]["controller_ref"] = "not_observed"
    else:
        graph["skills"][0]["C_pre"] = ["D1"]
    with pytest.raises(ValueError):
        validate_graph(graph, cases, conditions, rules)


def test_evaluator_rule_may_span_instances_owned_by_another_skill():
    cases, conditions, rules, graph = fixture()
    second = deepcopy(cases[0])
    second["case_id"] = "C2"
    second["video_uid"] = "video-two"
    cases.append(second)
    rules["evaluators"] = [{"id": "E1", "name": "完成判据", "completion": ["effect"],
        "process_constraint": [], "implementation_applicability": [],
        "source_members": ["C1:S1", "C2:S1"], "condition_decision_refs": [],
        "detector_ref": None, "controller_ref": None, "unknown_policy": "U_remains_unknown",
        "verification_status": "candidate", "causal_status": "not_established"}]
    graph["skills"][0]["E"]["completion"] = ["E1"]
    graph["realizations"].append({"id": "R2", "name": "unassigned source", "skill_id": "unassigned",
        "source_realization_refs": ["C2:S1:r1"], "effect_alignment_reason": "kept for review",
        "condition_decision_refs": []})
    graph["unassigned_members"] = [{"member_ref": "C2:S1", "reason": "另一个视频的实例暂不归类"}]
    graph["unassigned_realizations"] = [{"realization_ref": "R2", "reason": "同左"}]
    result = validate_graph(graph, cases, conditions, rules)
    assert result["evaluator_coverage"]["K1"]["E.completion"][0]["rule"] == "E1"
    assert result["unassigned_members"] == 1 and result["unassigned_realizations"] == 1


def test_unassigned_instance_requires_reason_instead_of_silent_drop():
    cases, conditions, rules, graph = fixture()
    second = deepcopy(cases[0])
    second["case_id"] = "C2"
    second["video_uid"] = "video-two"
    cases.append(second)
    graph["realizations"].append({"id": "R2", "name": "unassigned source", "skill_id": "unassigned",
        "source_realization_refs": ["C2:S1:r1"], "effect_alignment_reason": "kept",
        "condition_decision_refs": []})
    graph["unassigned_realizations"] = [{"realization_ref": "R2", "reason": "同左"}]
    graph["unassigned_members"] = [{"member_ref": "C2:S1"}]
    with pytest.raises(ValueError, match="unassigned instance"):
        validate_graph(graph, cases, conditions, rules)
    graph["unassigned_members"] = [{"member_ref": "C2:S1", "reason": "暂不归类"}]
    assert validate_graph(graph, cases, conditions, rules)["passed"]


def test_rule_only_task_node_requires_entry_policy():
    cases, conditions, rules, graph = fixture()
    graph["skills"][0]["role"] = "approach_target"
    graph["task_nodes"].append({"id": "T0", "skill_id": "K1", "source_members": [],
                                "occurrence": "rule_only", "reason": "入口政策补初始靠近，无独立来源观察"})
    graph["relations"] = [{"from": "T0", "to": "T1", "relation": "sequence",
                           "basis": "inferred_dependency", "reason": "policy entry",
                           "source_relation_refs": [], "status": "candidate"}]
    with pytest.raises(ValueError, match="task policy"):
        validate_graph(graph, cases, conditions, rules)
    assert validate_graph(graph, cases, conditions, rules,
                          {"cross_video": {"entry_role": "approach"}})["passed"]
    graph["task_nodes"][-1]["source_members"] = ["C1:S1"]
    graph["task_nodes"][-1]["source_members"] = ["C1:S1"]
    with pytest.raises(ValueError, match="may only claim other rule-only instances"):
        validate_graph(graph, cases, conditions, rules,
                       {"cross_video": {"entry_role": "approach"}})


def test_relation_rewrite_requires_branch_policy_and_keeps_source_refs():
    cases, conditions, rules, graph = fixture()
    second = deepcopy(cases[0]["graph"]["nodes"][0])
    second["id"] = "S2"
    cases[0]["graph"]["nodes"].append(second)
    cases[0]["graph"]["relations"] = [{"from": "S1", "to": "S2", "relation": "sequence", "basis": "observed_order"}]
    graph["skills"][0]["source_members"].append("C1:S2")
    graph["realizations"][0]["source_realization_refs"].append("C1:S2:r1")
    graph["task_nodes"].append({"id": "T2", "skill_id": "K1", "source_members": ["C1:S2"]})
    graph["relations"] = [{"from": "T1", "to": "T2", "relation": "branch",
                           "basis": "inferred_dependency", "reason": "condition branch",
                           "source_relation_refs": ["C1:e0"], "status": "candidate",
                           "guard": "grasp condition", "guard_truth": "U", "gate_outcome": "F",
                           "rewrite": {"reason": "prepare only when the condition fails", "policy": "branch_policy"}}]
    with pytest.raises(ValueError, match="branch policy"):
        validate_graph(graph, cases, conditions, rules)
    result = validate_graph(graph, cases, conditions, rules, {"branch_policy": {"mode": "clearance"}})
    assert result["relation_rewrites"][0]["source_relation_refs"] == ["C1:e0"]
    bad = deepcopy(graph)
    bad["relations"][0]["source_relation_refs"] = []
    with pytest.raises(ValueError, match="retain its source relation refs"):
        validate_graph(bad, cases, conditions, rules, {"branch_policy": {"mode": "clearance"}})


def test_cross_video_merge_requires_one_node_per_skill_occurrence():
    cases, conditions, rules, graph = fixture()
    second = deepcopy(cases[0])
    second.update(case_id="C2", video_uid="video-two")
    cases.append(second)
    graph["skills"][0]["source_members"] = ["C1:S1", "C2:S1"]
    graph["realizations"][0]["source_realization_refs"] = ["C1:S1:r1", "C2:S1:r1"]
    graph["task_nodes"] = [
        {"id": "T1", "skill_id": "K1", "source_members": ["C1:S1"]},
        {"id": "T2", "skill_id": "K1", "source_members": ["C2:S1"]},
    ]
    policy = {"semantic_merge_policy": {"share_nodes_across_videos": True}}
    with pytest.raises(ValueError, match="跨视频合并要求技能"):
        validate_graph(graph, cases, conditions, rules, policy)
    graph["task_nodes"] = [{"id": "T1", "skill_id": "K1", "source_members": ["C1:S1", "C2:S1"]}]
    assert validate_graph(graph, cases, conditions, rules, policy)["passed"]


def test_same_video_repeats_stay_separate_under_merge_policy():
    cases, conditions, rules, graph = fixture()
    duplicate = deepcopy(cases[0]["graph"]["nodes"][0])
    duplicate["id"] = "S2"
    cases[0]["graph"]["nodes"].append(duplicate)
    cases[0]["atomic"].append({"id": 2})
    cases[0]["operations"]["nodes"].append({"id": "step_2", "name": "test action"})
    duplicate["evidence_refs"] = [2]
    duplicate["R"] = [{"id": "r1", "name": "impl", "operation_refs": ["step_2"],
                       "atomic_refs": [2], "status": "observed"}]
    graph["skills"][0]["source_members"] = ["C1:S1", "C1:S2"]
    graph["realizations"][0]["source_realization_refs"] = ["C1:S1:r1", "C1:S2:r1"]
    graph["task_nodes"] = [{"id": "T1", "skill_id": "K1", "source_members": ["C1:S1", "C1:S2"]}]
    policy = {"semantic_merge_policy": {"share_nodes_across_videos": True}}
    with pytest.raises(ValueError, match="same-video occurrences|同一视频"):
        validate_graph(graph, cases, conditions, rules, policy)
