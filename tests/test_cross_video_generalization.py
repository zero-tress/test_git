"""Examples exercise intended semantics, not counts or self-mirroring serialization."""
import json
from copy import deepcopy

import pytest

from video2op.cross_video_alignment import compatible, realization_signature
from video2op.cross_video_delivery import export, refine
from video2op.general_graph import accepts_path, build, validate_reconstruction
from video2op.generalized_holdout import explain
from video2op.goal_semantics import contract
from video2op.skill_clips import intervals


def instance(iid, operations, *, target="盒子", uid=None, goal="grasp_object"):
    actions, nodes, relations = [], [], []
    for n, operation in enumerate(operations, 1):
        actor = "右手" if operation == "抓取" else "右臂"
        actions.append({"id": n, "executor": actor, "action": operation+target, "object": target,
                        "mode": "transition" if operation == "抓取" else "motion",
                        "start": n-1., "end": float(n), "state_before": operation+"前",
                        "state_after": operation+"后", "world_before": [], "world_after": [],
                        "functional_role": {"function": operation, "atomic_capability": "test_capability"}})
        nodes.append({"node_id": str(n), "name": operation, "selected_atomic_refs": [n], "partial_node": False})
        if n > 1:
            relations.append({"from": str(n-1), "to": str(n), "relation": "sequence", "basis": "observed_order"})
    return {"instance_id": iid, "video_uid": uid or iid, "identity_kind": "observation_fingerprint_only",
            "source": "fixture/result.json", "subtask_id": iid, "goal_key": goal,
            "target": {"local_entity": target, "category": "box"}, "bindings": {"target": target},
            "expected": contract(goal), "observed_process": actions,
            "operation_subgraph": {"nodes": nodes, "relations": relations},
            "atomic_refs": list(range(1, len(actions)+1)), "candidate_conditions": [], "realization_label": iid,
            "outcome": "unknown", "outcome_status": "unverified", "goal_effect_audit": {"status": "needs_review"}}


def skill(items, same_r=False):
    return {**contract(items[0]["goal_key"]), "skill_id": "skill_"+items[0]["goal_key"],
            "instance_ids": [i["instance_id"] for i in items], "causally_verified": False,
            "realizations": ([{"realization_id": "R", "instance_ids": [i["instance_id"] for i in items],
                              "label": "test", "applicability": {}}] if same_r else [
                {"realization_id": "R"+str(n), "instance_ids": [i["instance_id"]], "label": "test",
                 "applicability": {}} for n, i in enumerate(items)])}


def knowledge(items):
    s = skill(items)
    s["source_video_count"] = len(items)
    s["object_categories"] = ["box"]
    s["general_operation_graph"] = build(s, {i["instance_id"]: i for i in items})
    return {"schema_version": "goal_effect_knowledge.v1", "instances": items, "skills": [s],
            "sources": [{"video_uid": i["video_uid"], "identity_kind": i["identity_kind"],
                         "source_files": [i["source"]], "intent_hypotheses": {}} for i in items],
            "task_families": [], "condition_induction": {"conditions": [], "rejected": [], "policy": "test"},
            "policy": {}}


def graph(items, same_r=False):
    return build(skill(items, same_r), {i["instance_id"]: i for i in items})


def test_direct_and_clearance_routes_preserve_repeated_approach():
    a = instance("a", ["靠近", "抓取"])
    b = instance("b", ["靠近", "清障", "靠近", "抓取"])
    g = graph([a, b])
    direct, detour = g["alternatives"]
    assert len(direct["nodes"]) == 2
    assert len(detour["nodes"]) == 4
    assert detour["nodes"][0] != detour["nodes"][2]
    assert direct["nodes"][0] == detour["nodes"][0]
    assert direct["nodes"][-1] == detour["nodes"][-1]
    assert not any(e["from"] == e["to"] for e in g["relations"])
    assert g["reconstruction_validation"]["passed"]
    assert all(p["selection_guard"]["truth"] == "U" for p in g["alternatives"])


def test_every_instance_in_one_realization_has_its_own_graph_mapping():
    a = instance("a", ["靠近", "抓取"])
    b = instance("b", ["靠近", "清障", "抓取"])
    g = graph([a, b], same_r=True)
    assert len(g["alternatives"]) == 2
    assert g["reconstruction_validation"]["instances_checked"] == 2
    assert {i for p in g["alternatives"] for i in p["instance_ids"]} == {"a", "b"}


def test_all_edges_existing_does_not_authorize_a_cross_spliced_route():
    a = instance("a", ["A", "B", "D"])
    b = instance("b", ["A", "C", "D", "E"])
    g = graph([a, b])
    p, q = g["alternatives"]
    invented = p["nodes"]+q["nodes"][-1:]
    assert p["nodes"][-1] == q["nodes"][-2]
    assert accepts_path(g, p["nodes"])
    assert accepts_path(g, q["nodes"])
    assert not accepts_path(g, invented)


def test_opposite_orders_do_not_create_a_union_sequence_loop():
    g = graph([instance("a", ["A", "B"]), instance("b", ["B", "A"])])
    assert g["reconstruction_validation"]["passed"]
    assert g["alternatives"][1]["alignment_issues"] == ["opposite_order_kept_separate"]


@pytest.mark.parametrize("difference", ["state", "object"])
def test_same_action_names_do_not_collapse_different_states_or_object_roles(difference):
    a, b = instance("a", ["抓取"]), instance("b", ["抓取"])
    if difference == "state":
        b["observed_process"][0]["state_after"] = "未握住目标"
    else:
        b["observed_process"][0]["object"] = "另一物体"
    assert len(graph([a, b])["nodes"]) == 2


def test_method_signature_distinguishes_parallel_and_sequential_relations():
    a = instance("a", ["靠近", "抓取"])
    b = deepcopy(a)
    b["operation_subgraph"]["relations"][0]["relation"] = "parallel"
    assert realization_signature(a) != realization_signature(b)


def test_state_variants_remain_paths_of_same_method_without_forcing_conditions():
    a, b = instance("a", ["靠近", "抓取"]), instance("b", ["靠近", "抓取"])
    b["observed_process"][0]["state_before"] = "目标起点不同"
    assert realization_signature(a) == realization_signature(b)
    g = graph([a, b], same_r=True)
    assert len(g["alternatives"]) == 2
    assert g["reconstruction_validation"]["passed"]


def test_effect_conflict_is_not_functionally_merged():
    a = instance("a", ["抓取"])
    b = deepcopy(a)
    b["expected"]["expected_effects"][0]["value"] = False
    assert not compatible(b, skill([a]))
    assert realization_signature(a) != realization_signature(b)
    with pytest.raises(ValueError, match="Goal/effect"):
        refine(knowledge([b]))


def test_object_role_difference_is_not_hidden_by_replacing_every_object_as_target():
    a, b = instance("a", ["抓取"]), instance("b", ["抓取"])
    b["observed_process"][0]["object"] = "障碍物"
    assert realization_signature(a) != realization_signature(b)


def test_bilateral_hand_relationship_is_preserved_when_normalizing_sides():
    a = instance("a", ["抓取", "抓取"])
    b = deepcopy(a)
    b["observed_process"][1]["executor"] = "左手"
    assert realization_signature(a) != realization_signature(b)


def test_reconstruction_check_detects_corrupted_node_or_removed_edge():
    a = instance("a", ["靠近", "抓取"])
    g = graph([a])
    g["alternatives"][0]["relations"].clear()
    assert not validate_reconstruction(g, {"a": a})["passed"]


def test_clips_keep_gaps_merge_overlaps_and_clamp_context():
    actions = [{"id": 1, "start": 0, "end": 1}, {"id": 2, "start": .8, "end": 1.5},
               {"id": 3, "start": 4, "end": 5}]
    core, spans, issues = intervals(actions, 5, .25)
    assert len(core) == 3
    assert [(r["start"], r["end"]) for r in spans] == [(0, 1.75), (3.75, 5)]
    assert not issues


@pytest.mark.parametrize("start,end", [(float("nan"), 1), (2, 1), (9, 10)])
def test_invalid_timestamps_cannot_create_evidence_clips(start, end):
    core, spans, issues = intervals([{"id": 1, "start": start, "end": end}], 5)
    assert not core and not spans and issues


def test_inferred_steps_are_not_exported_as_observed_clips():
    core, spans, issues = intervals([{"id": 1, "start": 0, "end": 1, "inferred": True}], 5)
    assert not core and not spans
    assert issues[0]["reason"] == "inferred_action_not_clip_evidence"


def test_unknown_effects_and_conditions_stay_unknown_in_delivery(tmp_path):
    k = knowledge([instance("a", ["靠近", "抓取"])])
    summary = export(k, tmp_path)
    assert summary["confirmed_routing_guards"] == 0
    assert summary["semantic_members_needing_review"] == 1
    tuples = json.loads((tmp_path/"skill_tuples.json").read_text())
    r = tuples["skills"][0]["R"][0]
    assert r["capability_binding_status"] == "unbound"
    assert r["path_ids"]
    assert (tmp_path/r["implementation_graph_ref"]).exists()
    assert "cross_video_review" not in r["implementation_graph_ref"]


def test_holdout_never_enters_training_or_becomes_execution_verification():
    k = knowledge([instance("a", ["靠近", "抓取"])])
    held = knowledge([instance("b", ["靠近", "抓取"])])
    row = explain(k, held)[0]
    assert row["decision"] == "existing_path_candidate"
    assert not row["applicability_verified"]
    assert not row["reference_labels_used_for_matching"]
    with pytest.raises(ValueError, match="leaked"):
        explain(k, k)


def test_changed_starting_state_requires_condition_review_not_false_verified_hit():
    k = knowledge([instance("a", ["靠近", "抓取"])])
    b = instance("b", ["靠近", "抓取"])
    b["observed_process"][0]["state_before"] = "被遮挡"
    assert explain(k, knowledge([b]))[0]["decision"] == "requires_condition_review"


def test_missing_preparation_is_reported_as_new_branch_candidate():
    k = knowledge([instance("a", ["靠近", "抓取"])])
    held = knowledge([instance("b", ["靠近", "清障", "靠近", "抓取"])])
    assert explain(k, held)[0]["decision"] == "requires_new_branch"


def test_other_goal_is_not_a_new_realization_of_the_old_goal():
    k = knowledge([instance("a", ["抓取"])])
    held = knowledge([instance("b", ["打开"], goal="open_object")])
    assert explain(k, held)[0]["decision"] == "goal_mismatch"


def test_union_edge_loss_is_detected_even_if_private_source_paths_survive():
    a = instance("a", ["靠近", "抓取"])
    g = graph([a])
    g["relations"].clear()
    assert not validate_reconstruction(g, {"a": a})["passed"]


def test_all_objects_and_actors_have_explicit_path_local_bindings():
    a = instance("a", ["靠近", "抓取"])
    a["observed_process"][0]["object"] = "障碍物"
    p = graph([a])["alternatives"][0]
    assert p["role_bindings"]["objects"]["target"] == "盒子"
    assert p["role_bindings"]["objects"]["other_1"] == "障碍物"
    assert "右手" in p["role_bindings"]["actors"].values()


def test_parallel_relation_remains_parallel_after_branch_merging():
    a = instance("a", ["靠近", "抓取"])
    a["operation_subgraph"]["relations"][0]["relation"] = "parallel"
    g = graph([a])
    assert g["relations"][0]["relation"] == "parallel"
    assert not any(e["relation"] == "sequence" for e in g["relations"])
    assert g["reconstruction_validation"]["passed"]


def test_resume_refuses_changed_inputs_and_padding(tmp_path):
    from video2op.skill_clips import export as export_clips
    empty = {"instances": [], "sources": []}
    export_clips(empty, tmp_path, {"media": []}, include_actions=False)
    with pytest.raises(ValueError, match="settings differ"):
        export_clips(empty, tmp_path, {"media": []}, padding=2, include_actions=False, resume=True)


def test_export_refuses_overwriting_an_existing_directory(tmp_path):
    from video2op.skill_clips import export as export_clips
    (tmp_path / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        export_clips({"instances": [], "sources": []}, tmp_path, {"media": []})
    assert (tmp_path / "keep.txt").read_text() == "keep"


def test_model_review_rejects_cross_video_claim_evidence():
    from tools.review_cross_video_samples import validate
    result = {"observations": [{"case_id": "01", "claims": [
        {"claim": "接触", "truth": "T", "evidence_frames": ["case_07_f1"]}]}],
        "comparison": {"same_semantic_goal": "U", "same_observed_effect": "U",
                       "same_method": "U", "boundary_sufficient": "U", "evidence_frames": []}}
    with pytest.raises(ValueError, match="Cross-video"):
        validate(result, ["01","07"], [{"frame_id": "case_07_f1"}], {"01": 2, "07": 2})


def test_model_review_rejects_assertions_without_visual_evidence():
    from tools.review_cross_video_samples import validate
    result = {"observations": [{"case_id": "01", "claims": [
        {"claim": "接触", "truth": "T", "evidence_frames": []}]}],
        "comparison": {"same_semantic_goal": "U", "same_observed_effect": "U",
                       "same_method": "U", "boundary_sufficient": "U", "evidence_frames": []}}
    with pytest.raises(ValueError, match="requires actual frames"):
        validate(result, ["01"], [], {"01": 2})
