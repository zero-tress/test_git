from copy import deepcopy

import pytest
from test_arm_hand_scope import action, example
from test_goal_effect_learning import observation, scope_context, scoped_case

from video2op import condition_induction, knowledge, semantic
from video2op.pipeline import build_learning_graph
from video2op.stages import s08_scope
from video2op.stages.common import ValidationFailure


def test_catalog_restores_exact_source_fields_without_copying_model_prose():
    b, scope = scope_context()
    scope["subtasks"][0]["atomic_refs"] = [1, 2]
    scope["subtasks"][0]["outcome"] = "success"
    scope["subtasks"][0]["outcome_evidence"] = ["a2_state_after_0"]
    s08_scope.expand_evidence(scope, b)
    ev = scope["subtasks"][0]["outcome_evidence"][0]
    assert ev["field"] == "state_after"
    assert ev["quote"] == "右手握住杯子"


def test_unknown_evidence_cannot_become_success():
    b, scope = scope_context()
    scope["subtasks"][0].update(outcome="success", outcome_evidence=["fabricated"])
    s08_scope.expand_evidence(scope, b)
    assert scope["subtasks"][0]["outcome"] == "unknown"
    assert scope["evidence_diagnostics"]


def test_future_condition_is_quarantined_without_destroying_valid_subtask():
    b, scope = scope_context()
    scope["condition_observations"] = [
        {"subtask_id": "s", "condition_key": "holding", "at": "pre",
         "truth": "T", "evidence": ["a2_state_after_0"]}]
    s08_scope.expand_evidence(scope, b)
    assert scope["subtasks"][0]["goal_key"] == "acquire_object"
    assert not scope["condition_observations"]
    assert scope["evidence_diagnostics"]


def test_single_target_scope_cannot_swallow_a_different_object():
    b, scope = scope_context()
    b["atomic"]["atomic_actions"][0]["object"] = "笔"
    with pytest.raises(ValidationFailure, match="another object"):
        s08_scope.validate(scope, b)


def test_evidence_must_reference_its_actual_field():
    b, scope = scope_context()
    b["atomic"]["atomic_actions"][1]["world_after"] = ["独有世界状态"]
    scope["subtasks"][0].update(outcome="success", atomic_refs=[1, 2], outcome_evidence=[
        {"atomic_ref": 2, "field": "state_after", "quote": "独有世界状态"}])
    with pytest.raises(ValidationFailure, match="not an observed"):
        s08_scope.validate(scope, b)


def test_reviewer_can_correct_model_without_double_counting():
    model = observation(truth="T", provenance="model_grounded_candidate")
    human = observation(truth="F")
    item = condition_induction.induce([model, human])["conditions"][0]
    assert item["counts"]["F_success"] == 1
    assert item["counts"]["T_success"] == 0
    assert item["reviewed_counts"]["F_success"] == 1
    assert item["necessity_status"] == "counterexample_observed"


@pytest.mark.parametrize("name", ["推", "拉", "旋转", "按压"])
def test_real_builder_supports_generic_arm_interactions(name):
    b = {"meta": {"name": name, "duration": 1},
         "atomic": {"atomic_actions": [
             dict(id=1, executor="右臂", action=name+"目标", semantic_action=name,
                  mode="motion", start=0, end=1, object="盒子",
                  state_before="", state_after="", world_before=[], world_after=[], inferred=False)]},
         "relations": [], "task_nodes": {"task_nodes": []}}
    build_learning_graph(b)
    assert b["task_nodes"]["task_nodes"][0]["name"] == name
    assert semantic.validate(b)["passed"]


def test_observed_alternation_survives_final_graph_when_not_causally_ordered():
    b = example()
    b["atomic"]["atomic_actions"].append(action(12, "左手", "左手抓握杯子", 1, 2,
                                                before="左手已张开", after="左手握住杯子"))
    b["relations"] = [{"from": 2, "to": 12, "relation": "alternation"}]
    build_learning_graph(b)
    assert b["operations"]["alternation_pairs"]
    assert any(r["relation"] == "alternation" for r in b["semantic_graph"]["relations"])


def test_general_graph_keeps_realization_guards_instead_of_one_forced_sequence():
    a, b = scoped_case(), scoped_case(uid="video2")
    b["atomic"]["atomic_actions"][0]["action"] = "从另一方向接近笔"
    result = knowledge.aggregate([knowledge.extract(a, "a/result.json"),
                                  knowledge.extract(b, "b/result.json")])
    skill = next(s for s in result["skills"] if s["goal_key"] == "acquire_object")
    graph = skill["general_operation_graph"]
    assert len(graph["alternatives"]) == 2
    assert all(edge["realization_guards"] for edge in graph["relations"])
    assert all(p["selection_guard"]["status"] == "unresolved" for p in graph["alternatives"])
    assert graph["expected_effects"] == skill["expected_effects"]


def test_same_object_category_does_not_merge_distinct_entities():
    a, b = scoped_case("红笔"), scoped_case("黑笔", uid="video2")
    result = knowledge.aggregate([knowledge.extract(a, "a/result.json"),
                                  knowledge.extract(b, "b/result.json")])
    acquire = [i for i in result["instances"] if i["goal_key"] == "acquire_object"]
    assert {i["target"]["local_entity"] for i in acquire} == {"红笔", "黑笔"}


def test_duplicate_source_conditions_cannot_make_export_schema_fail():
    b = example()
    b["atomic"]["atomic_actions"][4].update(
        state_after="杯底接触桌面", world_after=["杯底接触桌面"])
    build_learning_graph(b)
    assert semantic.validate(b)["passed"]
    for n in b["semantic_graph"]["nodes"].values():
        for key in ("C_pre", "C_post", "C_const"):
            assert len(n["skill"][key]) == len(set(n["skill"][key]))


def test_export_declares_source_final_and_export_namespaces():
    b = scoped_case()
    assert b["semantic_graph"]["x-meta"]["final_to_export"]["step_1"] == "N1"
    assert b["semantic_graph"]["x-meta"]["learning_alignment"]["source_to_final"]


def test_full_pipeline_with_scope_stage_offline(tmp_path, monkeypatch):
    from video2op import config, media, pipeline
    b = example()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fixture")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path/"out")
    monkeypatch.setattr(media, "probe", lambda p: {"name": "v", "duration": 7, "width": 10,
        "height": 10, "fps": 1, "path": str(p)})
    monkeypatch.setattr(media, "motion_profile", lambda p: {"change_points": [], "hot_segments": []})
    monkeypatch.setattr(pipeline.sampling, "prepare", lambda ctx: {})
    monkeypatch.setattr(pipeline.local_review, "run", lambda *args: {})
    replacements = [
        (pipeline.s01_viewpoint, {}),
        (pipeline.s02a_intent, {"intents": [{"id": "i", "statement": "获取杯子", "confidence": 0.7}]}),
        (pipeline.s02b_atomic, {"windows": [{"window": {"index": 1, "start": 0, "duration": 7},
            "atomic_actions": b["atomic"]["atomic_actions"], "temporal_relations": []}]}),
        (pipeline.s02c_task, b["task_nodes"]), (pipeline.s02d_link, {"missing_actions": []}),
        (pipeline.s03_sync, {"intent_updates": [{"intent_id": "i", "confidence": 0.6}]}),
        (pipeline.s04_conditions, {}), (pipeline.s05_rules, {}),
        (pipeline.s08_scope, {"objects": [], "subtasks": []})]
    for stage, payload in replacements:
        monkeypatch.setattr(stage, "run", lambda *args, value=payload: deepcopy(value))
    result = pipeline.run_case(video, verbose=False)
    assert result["validation"]["passed"]
    assert result["intents"]["intents"][0]["confidence"] == 0.6
    assert (tmp_path/"out/v_semantic_v3/stages/s08_scope.json").exists()
