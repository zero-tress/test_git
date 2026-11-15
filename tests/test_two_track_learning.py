"""Behavioral checks for separate graph learning, local trials, and causal evidence."""

import json

import pytest
from test_goal_effect_learning import scoped_case

from video2op import semantic_state as state
from video2op.branch_guards import features_before, induce
from video2op.contrastive_learning import enrich
from video2op.cross_video_alignment import normalized
from video2op.learning_tracks import split
from video2op.skill_episodes import build, export_clips
from video2op.task_causality import audit


def ctx(labels=("透明塑料盒",)):
    return {
        "target": {"local_entity": labels[0], "category": "box"},
        "bindings": {"target": labels[0]},
        "entity_context": [{"label": v, "category": "box"} for v in labels],
        "observed_process": [{"executor": "右手", "object": v} for v in labels],
    }


def test_aliases_are_video_local_and_ambiguous_boxes_are_unresolved():
    single = ctx()
    assert normalized("右手稳定握持盒子", single) == normalized("右手稳定握持透明塑料盒", single)
    double = ctx(("透明塑料盒", "小塑料盒"))
    assert "盒子" not in state.alias_map(double)
    assert not any(a["args"] == ["gripper_1", "target"] for a in state.atoms("右手握住盒子", double))


def test_stable_holding_is_stronger_than_plain_holding():
    c = ctx()
    plain = state.atoms("右手握住盒子", c)
    stable = state.atoms("右手抓牢盒子", c)
    need = next(a for a in stable if a["predicate"] == "stable_holding")
    assert not any(state.entails(a, need) for a in plain)
    assert any(state.entails(a, plain[0]) for a in stable)


@pytest.mark.parametrize(
    "text,predicate,truth",
    [
        ("右手没有握住盒子", "holding", False),
        ("右手未抓稳盒子", "stable_holding", False),
        ("盒子未离开桌面", "off_source_support", False),
        ("盒子没有静止", "stationary", False),
    ],
)
def test_negative_states_preserve_polarity(text, predicate, truth):
    assert any(a["predicate"] == predicate and a["truth"] == truth for a in state.atoms(text, ctx()))


@pytest.mark.parametrize("text", ["右手可能抓牢盒子", "盒子没有滑落", "如果右手握住盒子"])
def test_uncertainty_and_absence_of_slip_do_not_prove_stability(text):
    assert not any(a["predicate"] == "stable_holding" for a in state.atoms(text, ctx()))


def causal_bundle(after="右手稳定握持笔", end=1, other=False):
    actions = [
        {
            "id": 1,
            "executor": "右手",
            "object": "瓶子" if other else "笔",
            "start": 0,
            "end": end,
            "state_after": after,
            "state_before": "",
            "inferred": False,
        },
        {
            "id": 2,
            "executor": "右臂",
            "object": "笔",
            "start": 1,
            "end": 2,
            "state_before": "",
            "state_after": "",
            "inferred": False,
        },
    ]
    return {
        "atomic": {"atomic_actions": actions},
        "semantic_scope": {"objects": [{"label": "笔", "category": "pen"}, {"label": "瓶子", "category": "bottle"}]},
        "semantic_graph": {
            "nodes": {
                "N1": {
                    "name": "抓取",
                    "skill": {
                        "X": {"subject": "右手"},
                        "O": ["o2" if other else "o1"],
                        "C_post": ["post"],
                        "C_pre": [],
                    },
                },
                "N2": {
                    "name": "移动",
                    "skill": {"X": {"subject": "右手"}, "O": ["o1"], "C_pre": ["pre"], "C_post": []},
                },
            },
            "objects": {"o1": {"label": "笔"}, "o2": {"label": "瓶子"}},
            "predicates": {"pre": {"text": "右手稳定握持笔"}, "post": {"text": "右手稳定握持笔"}},
            "evidence": {"N1": {"atomic_refs": [1]}, "N2": {"atomic_refs": [2]}},
            "relations": [{"from": "N1", "to": "N2", "relation": "sequence", "basis": "required_dependency"}],
        },
    }


def test_actual_effect_support_is_checked_without_claiming_necessity():
    r = audit(causal_bundle())["edges"][0]
    assert r["status"] == "observed_support_candidate"
    assert not r["causal_necessity_verified"]


def test_declared_effect_is_not_observed_effect():
    r = audit(causal_bundle(after="手正在移动"))["edges"][0]
    assert r["requirements"][0]["status"] == "contract_only_needs_observation"


def test_future_effect_cannot_support_earlier_precondition():
    assert audit(causal_bundle(end=1.5))["edges"][0]["status"] == "conflict"


def test_another_object_grasp_does_not_support_target_grasp():
    r = audit(causal_bundle(after="右手稳定握持瓶子", other=True))["edges"][0]
    assert r["status"] != "observed_support_candidate"


def test_holding_false_contradicts_stable_holding_true():
    assert audit(causal_bundle(after="右手没有握住笔"))["edges"][0]["status"] == "conflict"


def test_already_satisfied_state_is_not_source_action_causality():
    b = causal_bundle(after="手正在移动")
    b["atomic"]["atomic_actions"][1]["state_before"] = "右手稳定握持笔"
    assert audit(b)["edges"][0]["requirements"][0]["status"] == "preexisting_state_not_proof_of_source_cause"


def pen_case():
    b = scoped_case()
    b["intents"] = {"intents": [{"id": "i1", "statement": "拿起笔"}]}
    b["semantic_scope"]["subtasks"][0]["intent_ids"] = ["i1"]
    return b


def test_whole_goal_graph_and_grasp_clip_have_different_scope():
    b = pen_case()
    t = split(b, "case/result.json", provided_goal={"goal_key": "acquire_object", "target_category": "pen"})
    tasks = t["purpose_case"]["instances"]
    clips = t["clip_case"]["instances"]
    assert {u["goal_key"] for u in tasks} == {"acquire_object"}
    assert {u["goal_key"] for u in clips} == {"grasp_object"}
    grasp = clips[0]
    assert set(grasp["core_atomic_refs"]) < set(tasks[0]["atomic_refs"])
    assert grasp["parent_task_refs"] == [tasks[0]["instance_id"]]
    assert grasp["classification"]["clip_end_sec"] < tasks[0]["boundary"]["end_sec"]


def test_no_matching_goal_is_reported_without_relabeling_video():
    t = split(
        pen_case(), "case/result.json", provided_goal={"goal_key": "acquire_object", "target_category": "bottle"}
    )
    assert t["unresolved_goal"] and not t["purpose_case"]["instances"]


def test_grasp_preparation_ends_at_grasp_milestone_not_lift():
    u = build(pen_case())["episodes"][0]
    assert 1 in u["atomic_refs"] and 2 in u["atomic_refs"]
    assert 3 not in u["atomic_refs"]
    assert u["boundary"]["end_sec"] == 2
    assert u["atomic_instance_ref"]


def review_record(tmp_path, entry_frame=0, post_frame=2.2):
    b = pen_case()
    b["task_observation"] = {
        "attempted": "T",
        "outcome": "failure",
        "observation_id": "task_review",
        "task_contract": {"destination": "B"},
        "evidence": [{"quote": "目标没有到达B"}],
        "provenance": "existing_annotation",
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(b, ensure_ascii=False))
    unit = build(b)["episodes"][0]
    record = {
        "source_analysis": str(path),
        "frames": [
            {"frame_id": "entry", "timestamp": entry_frame, "path": "entry.jpg"},
            {"frame_id": "post", "timestamp": post_frame, "path": "post.jpg"},
        ],
        "response": {
            "unit_reviews": [
                {
                    "instance_id": unit["instance_id"],
                    "scope_verdict": "supported",
                    "attempted": "T",
                    "goal_satisfied": "T",
                    "outcome_evidence_frames": ["post"],
                    "conditions": [
                        {
                            "predicate": "accessible",
                            "phase": "entry",
                            "truth": "T",
                            "at_sec": 0,
                            "evidence_frames": ["entry"],
                        }
                    ],
                }
            ],
            "causal_reviews": [],
        },
    }
    return record


def test_task_failure_does_not_overwrite_local_grasp_success(tmp_path):
    c, _samples = enrich(review_record(tmp_path))
    assert next(u["outcome"] for u in c["instances"] if u["goal_key"] == "grasp_object") == "success"
    assert next(u["outcome"] for u in c["instances"] if u["instance_scope"] == "provided_task") == "failure"


def test_condition_uses_actual_frame_time_and_quarantines_future_evidence(tmp_path):
    c, _ = enrich(review_record(tmp_path, entry_frame=2.1))
    grasp = next(u for u in c["instances"] if u["goal_key"] == "grasp_object")
    assert grasp["condition_observations"][0]["truth"] == "U"


def test_post_release_frame_cannot_be_grasp_negative(tmp_path):
    c, _ = enrich(review_record(tmp_path, post_frame=6.2))
    assert next(u["outcome"] for u in c["instances"] if u["goal_key"] == "grasp_object") == "unknown"


def test_rejected_skill_scope_cannot_become_positive_trial(tmp_path):
    r = review_record(tmp_path)
    r["response"]["unit_reviews"][0]["scope_verdict"] = "rejected"
    c, _ = enrich(r)
    assert next(u["outcome"] for u in c["instances"] if u["goal_key"] == "grasp_object") == "unknown"


def branch_fixture(counterexample=False):
    instances = []
    samples = []
    paths = []
    for n, choice, truth in [(0, "B", "T"), (1, "B", "T"), (2, "C", "F"), (3, "C", "F")] + (
        [(4, "B", "F")] if counterexample else []
    ):
        iid = f"i{n}"
        uid = f"v{n}"
        u = {
            "instance_id": iid,
            "video_uid": uid,
            "observed_process": [
                {"id": 1, "executor": "右臂", "object": "笔", "start": 0, "end": 1},
                {"id": 2, "executor": "右手", "object": "笔", "start": 2, "end": 3},
            ],
            "operation_subgraph": {
                "nodes": [
                    {"node_id": "a", "selected_atomic_refs": [1]},
                    {"node_id": "b", "selected_atomic_refs": [2]},
                ]
            },
            "target": {"local_entity": "笔"},
            "bindings": {"target": "笔"},
        }
        instances.append(u)
        paths.append(
            {
                "instance_ids": [iid],
                "source_node_map": {"a": "A", "b": choice},
                "relations": [{"from": "A", "to": choice, "relation": "sequence"}],
            }
        )
        samples.append(
            {
                "instance_id": iid,
                "eligible_for_rule_learning": True,
                "condition_observations": [
                    {
                        "predicate": "accessible",
                        "truth": truth,
                        "phase": "entry",
                        "at_sec": 0,
                        "evidence": [{"frame_id": "f0"}],
                    }
                ],
            }
        )
    graph = {"relations": [{"from": "A", "to": v, "relation": "sequence"} for v in ["B", "C"]], "alternatives": paths}
    return {"instances": instances, "skills": [{"skill_id": "s", "general_operation_graph": graph}]}, samples


def test_observed_predecision_contrasts_produce_nonexecuting_candidate_guards():
    k, s = branch_fixture()
    g = induce(k, s)
    rules = g["branches"][0]["rules"]
    assert len(rules) == 2
    assert all(r["status"] == "observational_candidate" and not r["execution_enabled"] for r in rules)


def test_guard_counterexample_is_preserved_and_downgrades_rule():
    k, s = branch_fixture(True)
    assert any(
        r["status"] == "contradicted_candidate" and r["counterexamples"] for r in induce(k, s)["branches"][0]["rules"]
    )


def test_guard_does_not_use_future_or_post_outcome_features():
    k, s = branch_fixture()
    for row in s:
        row["condition_observations"][0]["at_sec"] = 2.1
    assert not induce(k, s)["branches"][0]["rules"]


def test_guard_does_not_treat_holding_other_object_as_target_state():
    c = ctx(("透明塑料盒", "小塑料盒"))
    c["observed_process"][0].update(id=1, start=0, end=1, state_after="右手抓牢小塑料盒")
    c["observed_process"] = c["observed_process"][:1]
    assert "stable_holding" not in features_before({"condition_observations": []}, c, 2)


def test_episode_clip_export_is_idempotent_and_detects_byte_changes(tmp_path, monkeypatch):
    from video2op.skill_clips import sha256

    b = pen_case()
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    b["meta"]["path"] = str(source)
    b["source_video_sha256"] = "uid"
    episodes = build(b)["episodes"]
    (tmp_path / "skill_episodes.json").write_text(json.dumps({"episodes": episodes}))
    calls = []

    def fake_cut(src, target, start, end):
        target.write_bytes(str((start, end)).encode())
        calls.append(target)
        return {"sha256": sha256(target), "duration": end - start}

    monkeypatch.setattr("video2op.skill_clips.cut", fake_cut)
    first = export_clips(b, tmp_path)
    assert export_clips(b, tmp_path) == first and len(calls) == 2
    calls[0].write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        export_clips(b, tmp_path)


def test_same_operation_aligns_success_and_failure_without_losing_states():
    from video2op.knowledge import aggregate

    a, b = pen_case(), pen_case()
    b["source_video_sha256"] = "another_video"
    b["atomic"]["atomic_actions"][1]["state_after"] = "右手没有握住笔"
    tasks = [
        split(v, f"{n}/result.json", provided_goal={"goal_key": "acquire_object", "target_category": "pen"})[
            "purpose_case"
        ]
        for n, v in enumerate([a, b])
    ]
    k = aggregate(tasks)
    g = k["skills"][0]["general_operation_graph"]
    grasp = next(n for n in g["nodes"] if n["operation"] == "抓取")
    assert len(grasp["source_instances"]) == 2
    assert len(grasp["feature_variants"]) == 2
    assert g["reconstruction_validation"]["passed"]


def test_supplied_intent_survives_wrong_model_scope_without_inheriting_success():
    b = pen_case()
    b["semantic_scope"]["subtasks"][0].update(
        goal_key="relocate_object", destination="B", outcome="success", outcome_evidence=[{"quote": "笔移动了"}]
    )
    t = split(b, "case/result.json", provided_goal={"goal_key": "acquire_object", "target_category": "pen"})
    u = t["purpose_case"]["instances"][0]
    assert u["goal_key"] == "acquire_object" and u["outcome"] == "unknown"
    assert u["alternative_model_scope"]["goal_key"] == "relocate_object"
    assert {e["predicate"] for e in u["expected"]["expected_effects"]} == {"holding", "off_source_support"}


def test_implicit_other_object_state_is_not_rebound_to_next_target():
    b = causal_bundle(after="右手稳定握持", other=True)
    assert audit(b)["edges"][0]["status"] != "observed_support_candidate"


def test_episode_source_is_analysis_json_not_video_bytes():
    t = split(
        pen_case(), "analysis/result.json", provided_goal={"goal_key": "acquire_object", "target_category": "pen"}
    )
    assert all(u["source"] == "analysis/result.json" for u in t["clip_case"]["instances"])


def test_invalid_model_causal_id_is_quarantined_independently(tmp_path):
    r = review_record(tmp_path)
    r["response"]["causal_reviews"] = [
        {"from": "invented", "to": "N99", "predicate_ref": "bad", "verdict": "supported", "evidence_frames": ["post"]}
    ]
    c, _ = enrich(r)
    assert next(u["outcome"] for u in c["instances"] if u["goal_key"] == "grasp_object") == "success"
    assert c["causal_model_review"]["quarantine"][0]["reason"] == "unknown_edge_or_target_predicate"


def test_scope_without_matching_category_remains_unresolved():
    t = split(
        pen_case(), "analysis/result.json", provided_goal={"goal_key": "acquire_object", "target_category": "bottle"}
    )
    assert t["unresolved_goal"]


def test_missing_timestamp_cannot_enter_branch_guard():
    k, s = branch_fixture()
    for row in s:
        row["condition_observations"][0]["at_sec"] = None
    assert not induce(k, s)["branches"][0]["rules"]


def test_nonexecution_of_provided_task_does_not_promote_unrelated_goal():
    b = pen_case()
    b["task_observation"] = {"attempted": "F", "outcome": "not_executed", "task_contract": {"destination": "B"}}
    t = split(b, "case/result.json")
    assert not t["purpose_case"]["instances"]
    assert t["clip_case"]["instances"]


def test_unknown_transition_time_does_not_get_observed_causal_support():
    b = causal_bundle()
    b["semantic_graph"]["evidence"]["N2"]["atomic_refs"] = []
    r = audit(b)["edges"][0]
    assert r["requirements"][0]["status"] == "target_transition_time_unknown"
    assert r["status"] != "observed_support_candidate"


def test_inferred_state_field_is_not_actual_effect_evidence():
    b = causal_bundle()
    b["atomic"]["atomic_actions"][0]["state_after_from"] = "inferred"
    r = audit(b)["edges"][0]
    assert r["requirements"][0]["status"] == "contract_only_needs_observation"


def test_no_stable_holding_does_not_assert_plain_holding():
    facts = state.atoms("右手没有稳定握持盒子", ctx())
    assert any(a["predicate"] == "stable_holding" and not a["truth"] for a in facts)
    assert not any(a["predicate"] == "holding" and a["truth"] for a in facts)


def test_permission_to_release_is_not_already_released():
    facts = state.atoms("目标已经受到可靠支撑，允许解除握持", ctx(), requirement=True)
    assert any(a["predicate"] == "supported" and a["truth"] for a in facts)
    assert not any(a["predicate"] == "holding" and not a["truth"] for a in facts)


def test_human_local_review_reaches_episode_without_overwriting_parent():
    from video2op.learning_tracks import apply_reviewed

    b = pen_case()
    t = split(b, "case/result.json", provided_goal={"goal_key": "acquire_object", "target_category": "pen"})
    grasp = next(u for u in t["clip_case"]["instances"] if u["goal_key"] == "grasp_object")
    parent = t["purpose_case"]["instances"][0]["outcome"]
    apply_reviewed(
        [t],
        [
            {
                "instance_id": grasp["atomic_instance_ref"],
                "outcome_review": True,
                "outcome": "failure",
                "outcome_evidence": [{"quote": "人工确认未建立握持"}],
                "reviewer": "reviewer",
            }
        ],
    )
    assert grasp["outcome"] == "failure" and grasp["outcome_status"] == "reviewed_reference"
    assert t["purpose_case"]["instances"][0]["outcome"] == parent
