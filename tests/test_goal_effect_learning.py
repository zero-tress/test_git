from copy import deepcopy

import pytest
from test_arm_hand_scope import example

from video2op import condition_induction, knowledge, learning_alignment, temporal_learning
from video2op.goal_semantics import contract
from video2op.single_video.pipeline import build_learning_graph
from video2op.single_video.stages import s05_rules, s08_scope
from video2op.single_video.stages.common import ValidationFailure


def scoped_case(obj="笔", category="pen", goal="acquire_object", uid="video1"):
    b = example()
    b["source_video_sha256"] = uid
    for a in b["atomic"]["atomic_actions"]:
        a["object"] = obj
    for n in b["task_nodes"]["task_nodes"]:
        n["tuple"]["O"] = [obj]
    b["semantic_scope"] = {
        "objects": [{"label": obj, "category": category}],
        "subtasks": [{"id": "take", "goal_key": goal, "target": obj,
                      "atomic_refs": [1, 2, 3], "outcome": "unknown",
                      "realization": "接近抓握拿起"}]}
    build_learning_graph(b)
    return b


def test_pen_and_cup_share_skill_but_remain_separate_object_task_families():
    a, b = scoped_case(), scoped_case("杯子", "cup", uid="video2")
    out = knowledge.aggregate([knowledge.extract(a, "a/result.json"),
                               knowledge.extract(b, "b/result.json")])
    acquire = next(s for s in out["skills"] if s["goal_key"] == "acquire_object")
    assert acquire["object_categories"] == ["cup", "pen"]
    assert acquire["source_video_count"] == 2
    assert {f["object_category"] for f in out["task_families"]
            if f["goal_key"] == "acquire_object"} == {"pen", "cup"}
    assert out["validation"]["passed"]
    assert not acquire["causally_verified"]


def test_grasp_acquire_and_final_placement_never_collapse_to_one_goal():
    assert contract("grasp_object")["expected_effects"] != contract("acquire_object")["expected_effects"]
    out = knowledge.aggregate([
        knowledge.extract(scoped_case(goal="acquire_object"), "a/result.json"),
        knowledge.extract(scoped_case("杯子", "cup", "place_object", "v2"), "b/result.json")])
    assert {s["goal_key"] for s in out["skills"]} == {"grasp_object", "acquire_object", "place_object"}


def test_unrelated_earlier_cup_movement_is_not_included_in_pen_realization():
    b = scoped_case()
    b["atomic"]["atomic_actions"].insert(0, {
        "id": 99, "executor": "左臂", "action": "移走杯子", "object": "杯子",
        "mode": "motion", "start": -2, "end": -1, "inferred": False})
    item = next(i for i in knowledge.extract(b, "case/result.json")["instances"]
                if i["goal_key"] == "acquire_object")
    assert 99 not in item["atomic_refs"]
    assert not item["preparation_for"]


def test_copying_result_or_renaming_file_does_not_inflate_video_count():
    b = scoped_case()
    out = knowledge.aggregate([knowledge.extract(b, "first/result.json"),
                               knowledge.extract(deepcopy(b), "copy/result.json")])
    assert len(out["sources"]) == 1
    assert all(s["source_video_count"] == 1 for s in out["skills"])
    assert len(out["instances"]) == 2


def test_different_processes_are_retained_under_same_goal():
    a, b = scoped_case(), scoped_case(uid="video2")
    b["atomic"]["atomic_actions"][0]["action"] = "绕开障碍接近笔"
    out = knowledge.aggregate([knowledge.extract(a, "a/result.json"),
                               knowledge.extract(b, "b/result.json")])
    acquire = next(s for s in out["skills"] if s["goal_key"] == "acquire_object")
    assert len(acquire["realizations"]) == 2


def test_push_pull_and_grasp_move_share_relocation_only_when_goal_explicit():
    cases = []
    for idx, method in enumerate(("推", "拉", "抓持搬移")):
        b = scoped_case(goal="relocate_object", uid=f"video{idx}")
        b["atomic"]["atomic_actions"][0]["action"] = method + "目标"
        cases.append(knowledge.extract(b, f"{method}/result.json"))
    out = knowledge.aggregate(cases)
    relocate = next(s for s in out["skills"] if s["goal_key"] == "relocate_object")
    assert len(relocate["realizations"]) == 3
    assert all(i["goal_key"] != "grasp_object" for i in out["instances"]
               if i["instance_id"] in relocate["instance_ids"])


def test_unknown_goal_retained_as_unresolved_instead_of_silently_grasping():
    b = scoped_case()
    b["semantic_scope"]["subtasks"][0]["goal_key"] = "invented"
    extracted = knowledge.extract(b, "a/result.json")
    assert extracted["unresolved"]
    assert all(i["goal_key"] == "grasp_object" for i in extracted["instances"])


def test_full_source_evaluators_and_failure_signals_survive_final_export():
    b = example()
    b["rules"] = {"evaluators": [{"node_id": "n2", "process": ["路径无碰撞"],
                                 "completion": ["目标到达目的区域"], "failure_signals": ["目标掉落"]}]}
    build_learning_graph(b)
    move = next(n for n in b["task_nodes"]["task_nodes"] if n["name"] == "移动")
    assert "路径无碰撞" in move["tuple"]["E"]["process"]
    assert "目标掉落" in move["tuple"]["E"]["failure_signals"]
    exported = next(n for n in b["semantic_graph"]["nodes"].values() if n["name"] == "移动")
    assert {"name": "目标掉落", "target": "失败信号"} in exported["skill"]["E"]
    assert b["learning_alignment"]["records"]


def test_intermediate_effect_is_not_promoted_to_merged_move_final_effect():
    b = example()
    b["task_nodes"]["task_nodes"][1]["tuple"]["C_post"] = ["中间位置"]
    build_learning_graph(b)
    move = next(n for n in b["task_nodes"]["task_nodes"] if n["name"] == "移动")
    assert "中间位置" not in move["tuple"]["C_post"]
    assert any(r["text"] == "中间位置" and r["scope"] == "source_internal_or_ambiguous"
               for r in b["learning_alignment"]["records"])


def test_candidate_confidences_update_separately_reorder_and_retain():
    b = {"intents": {"intents": [{"id": "a", "confidence": 0.9}, {"id": "b", "confidence": 0.4}]},
         "sync": {"intent_updates": [{"intent_id": "a", "confidence": 0.2},
                                    {"intent_id": "b", "confidence": 0.8}]}}
    learning_alignment.apply_intent_updates(b)
    assert [i["id"] for i in b["intents"]["intents"]] == ["b", "a"]
    assert b["intents"]["intents"][1]["confidence_before_sync"] == 0.9
    before = deepcopy(b)
    learning_alignment.apply_intent_updates(b)
    assert b == before


def test_legacy_scalar_does_not_update_multiple_hypotheses():
    b = {"intents": {"intents": [{"id": "a", "confidence": 0.8}, {"id": "b", "confidence": 0.2}]},
         "sync": {"intent_confidence_after": 0.99}}
    learning_alignment.apply_intent_updates(b)
    assert [x["confidence"] for x in b["intents"]["intents"]] == [0.8, 0.2]


def observation(truth="T", outcome="success", **kwargs):
    return {"video_uid": "video1", "instance_id": "instance", "goal_key": "acquire_object",
            "condition_key": "reachable", "truth": truth, "outcome": outcome,
            "evidence": [{"atomic_ref": 1}], "outcome_evidence": [{"atomic_ref": 2}],
            "provenance": "reviewed_observation", "reviewer": "reviewer1", **kwargs}


def test_counterfactuals_never_count_as_failure_observations():
    out = condition_induction.induce([observation(provenance="counterfactual")])
    assert not out["conditions"]
    assert out["rejected"][0]["reason"] == "not_observed_evidence"


def test_nonexecution_is_censored_not_failure_or_false_condition():
    out = condition_induction.induce([observation(outcome="not_executed")])["conditions"][0]
    assert out["counts"]["T_not_executed"] == 1
    assert out["counts"]["T_failure"] == out["counts"]["F_failure"] == 0
    assert out["necessity_status"] == "needs_negative_trials"


def test_reviewed_success_with_condition_false_refutes_necessity():
    out = condition_induction.induce([observation("F")])["conditions"][0]
    assert out["necessity_status"] == "counterexample_observed"
    assert out["causal_status"] == "not_established"


def test_model_evidence_does_not_self_certify_as_reviewed():
    out = condition_induction.induce([observation("F", provenance="model_grounded_candidate")])["conditions"][0]
    assert out["necessity_status"] == "model_counterexample_candidate"
    assert out["reviewed_counts"]["F_success"] == 0


def test_conflicting_duplicate_annotations_are_excluded():
    out = condition_induction.induce([observation(), observation("F")])["conditions"][0]
    assert out["conflicted_annotations"] == 1
    assert sum(out["counts"].values()) == 0


def scope_context():
    b = example()
    return b, {"objects": [], "subtasks": [
        {"id": "s", "goal_key": "acquire_object", "target": "杯子",
         "atomic_refs": [1, 2, 3], "outcome": "unknown"}]}


def test_scope_rejects_fabricated_state_evidence():
    b, s = scope_context()
    s["subtasks"][0].update(outcome="success", outcome_evidence=[
        {"atomic_ref": 2, "field": "state_after", "quote": "杯子已经在另一张桌上"}])
    with pytest.raises(ValidationFailure, match="not an observed"):
        s08_scope.validate(s, b)


def test_scope_rejects_future_state_used_as_precondition():
    b, s = scope_context()
    s["condition_observations"] = [{"subtask_id": "s", "condition_key": "holding",
        "at": "pre", "truth": "T", "evidence": [
            {"atomic_ref": 2, "field": "state_after", "quote": "右手握住杯子"}]}]
    with pytest.raises(ValidationFailure, match="boundary"):
        s08_scope.validate(s, b)


def test_scope_rejects_unknown_object_and_intent_bindings():
    b, s = scope_context()
    s["subtasks"][0]["target"] = "另一个杯子"
    with pytest.raises(ValidationFailure):
        s08_scope.validate(s, b)


def test_graph_validation_checks_predicate_refs_cycles_and_parallel_conflicts():
    graph = {"nodes": {"a": {"skill": {"C_pre": ["missing"]}}, "b": {}},
             "predicates": {}, "relations": [
                 {"from": "a", "to": "b", "relation": "sequence"},
                 {"from": "b", "to": "a", "relation": "sequence"},
                 {"from": "a", "to": "b", "relation": "parallel"}]}
    errors = temporal_learning.validate_graph(graph)
    assert any("predicate" in e for e in errors)
    assert any("cycle" in e for e in errors)
    assert any("conflicts" in e for e in errors)


def test_invalid_temporal_pattern_is_not_defaulted_to_parallel():
    with pytest.raises(ValidationFailure):
        s05_rules._normalize({"temporal_structures": [{"pattern": "nonsense"}]})


def test_branch_and_join_retain_guards_and_targets_without_fabricating_execution():
    b = example()
    b["rules"] = {"temporal_structures": [
        {"id": "branch", "pattern": "Branch", "members": ["n1", "n2"],
         "alternatives": [{"when": "path_clear", "members": ["n1"]},
                          {"when": "path_blocked", "members": ["n2"]}]},
        {"id": "join", "pattern": "Synchronization", "members": ["n1", "n2"],
         "target": "n3", "join": "all"}]}
    build_learning_graph(b)
    patterns = b["temporal_knowledge"]["patterns"]
    assert patterns[0]["alternatives"][1]["when"] == "path_blocked"
    assert patterns[1]["join"] == "all"
    assert not any(e["relation"] == "branch" for e in b["operations"]["edges"])


def test_html_escapes_model_and_video_content():
    b = scoped_case()
    out = knowledge.aggregate([knowledge.extract(b, "<script>/result.json")])
    assert "<script>" not in knowledge.render(out)
