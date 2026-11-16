"""Contract regressions use synthetic model payloads, never judgments about real videos."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from video2op import merged_workbench as wb
from video2op import model_contrastive_review as cr
from video2op import model_merged_graph as mg


@pytest.fixture
def cases():
    return {"alpha": {"name": "alpha", "source_duration": 10, "source": "/unused.mp4"}}


@pytest.fixture
def graph():
    members = ["alpha"]
    return {
        "schema_version": mg.SCHEMA,
        "title": "任意模型任务",
        "learning_policy": {
            "whole_task_success_required": True,
            "exclude_failed_steps_from_main_graph": True,
            "retain_failures_for_contrastive": True,
            "simplification_by_model_only": True,
        },
        "end_policy": {"gate_before_end": False, "completion_validation": False},
        "execution_enabled": False,
        "approach_policy": deepcopy(mg.APPROACH_POLICY),
        "approach_review": [{"case_id": "alpha", "status": "not_observed", "occurrences": []}],
        "source_decisions": [
            {
                "case_id": "alpha",
                "whole_task_outcome": "success",
                "included": True,
                "evidence_refs": ["frame"],
                "retained_segments": [],
                "removed_failed_segments": [],
            }
        ],
        "simplifications": [
            {
                "case_id": "alpha",
                "decision": "uncertain",
                "necessity_status": "unknown",
                "reason": "模型尚不能证明可省略",
                "evidence_refs": ["frame"],
            }
        ],
        "contrastive_examples": [],
        "start_node_id": "arbitrary_begin",
        "end_node_id": "arbitrary_end",
        "nodes": [
            {"id": "arbitrary_begin", "kind": "terminal", "label": "起始", "source_case_ids": members},
            {
                "id": "model_condition",
                "kind": "gate",
                "label": "模型条件",
                "predicate": "模型自定义谓词",
                "truth": "U",
                "reason": "证据不足",
                "uses_removed_failure_as_runtime_precondition": False,
                "source_case_ids": members,
                "sources": [],
            },
            {
                "id": "unfamiliar_action",
                "kind": "operation",
                "label": "模型新技能XYZ",
                "action_role": "other",
                "observed_outcome": "success",
                "seven_tuple": {
                    **{k: ["模型字段" + k] for k in mg.FIELDS},
                    "E": {
                        k: "模型评价标准"
                        for k in ["metric", "success_condition", "failure_condition", "unknown_condition"]
                    },
                },
                "source_case_ids": members,
                "sources": [{"case_id": "alpha", "start_sec": None, "end_sec": None, "evidence_refs": ["frame"]}],
            },
            {"id": "arbitrary_end", "kind": "terminal", "label": "终点", "source_case_ids": members},
        ],
        "edges": [
            {"id": str(i), "from": a, "to": b, "source_case_ids": members}
            for i, (a, b) in enumerate(
                [
                    ("arbitrary_begin", "model_condition"),
                    ("model_condition", "unfamiliar_action"),
                    ("unfamiliar_action", "arbitrary_end"),
                ]
            )
        ],
        "paths": [
            {
                "case_id": "alpha",
                "node_ids": ["arbitrary_begin", "model_condition", "unfamiliar_action", "arbitrary_end"],
            }
        ],
    }


def test_validator_preserves_arbitrary_model_semantics(graph, cases):
    original = deepcopy(graph)
    assert mg.validate_graph(graph, cases, {"frame": {}}) is graph
    assert graph == original


def test_last_operation_goes_directly_to_end(graph, cases):
    graph["edges"].append(
        {"id": "bad", "from": "model_condition", "to": "arbitrary_end", "source_case_ids": ["alpha"]}
    )
    with pytest.raises(ValueError, match="before END"):
        mg.validate_graph(graph, cases, {"frame": {}})


def test_main_graph_cannot_include_failed_operation(graph, cases):
    graph["nodes"][2]["observed_outcome"] = "failure"
    with pytest.raises(ValueError, match="successful operations"):
        mg.validate_graph(graph, cases, {"frame": {}})


def test_only_whole_task_successes_enter_main_graph(graph, cases):
    graph["source_decisions"][0]["whole_task_outcome"] = "failure"
    with pytest.raises(ValueError, match="whole-task successes"):
        mg.validate_graph(graph, cases, {"frame": {}})


def test_failed_task_can_still_have_local_positive(graph, cases):
    graph["source_decisions"][0].update(whole_task_outcome="failure", included=False)
    graph.update(nodes=[], edges=[], paths=[], start_node_id=None, end_node_id=None, approach_review=[])
    graph["contrastive_examples"] = [
        {
            "id": "local",
            "case_id": "alpha",
            "skill_id": "some_skill",
            "outcome": "success",
            "core_start_sec": 1,
            "core_end_sec": 2,
            "context_start_sec": 0,
            "context_end_sec": 3,
            "evidence_refs": ["frame"],
        }
    ]
    mg.validate_graph(graph, cases, {"frame": {}})


def test_removed_failure_is_retained_as_separate_negative(graph, cases):
    graph["source_decisions"][0]["removed_failed_segments"] = [
        {"start_sec": 1, "end_sec": 2, "evidence_refs": ["frame"]}
    ]
    with pytest.raises(ValueError, match="separate contrastive failure"):
        mg.validate_graph(graph, cases, {"frame": {}})
    graph["contrastive_examples"] = [
        {
            "id": "negative",
            "case_id": "alpha",
            "skill_id": "s",
            "outcome": "failure",
            "core_start_sec": 1,
            "core_end_sec": 2,
            "context_start_sec": 0,
            "context_end_sec": 3,
            "evidence_refs": ["frame"],
        }
    ]
    mg.validate_graph(graph, cases, {"frame": {}})
    graph["nodes"][2]["sources"][0].update(start_sec=1.2, end_sec=2.2)
    with pytest.raises(ValueError, match="overlaps a removed failure"):
        mg.validate_graph(graph, cases, {"frame": {}})


def test_no_host_fills_missing_seven_tuple(graph, cases):
    del graph["nodes"][2]["seven_tuple"]["R"]
    with pytest.raises(ValueError, match="seven tuple"):
        mg.validate_graph(graph, cases, {"frame": {}})
    assert "R" not in graph["nodes"][2]["seven_tuple"]


def test_unknown_gate_is_not_forced_true(graph, cases):
    mg.validate_graph(graph, cases, {"frame": {}})
    assert graph["nodes"][1]["truth"] == "U"
    graph["nodes"][1]["uses_removed_failure_as_runtime_precondition"] = True
    with pytest.raises(ValueError, match="omitted failure"):
        mg.validate_graph(graph, cases, {"frame": {}})


@pytest.fixture
def review():
    return {
        "schema_version": "model_contrastive_review.v1",
        "skill_definitions": [
            {
                "skill_id": "grasp_object",
                "seven_tuple": {
                    **{k: [] for k in mg.FIELDS},
                    "E": {k: None for k in ["metric", "success_condition", "failure_condition", "unknown_condition"]},
                },
            }
        ],
        "examples": [
            {
                "id": "sample",
                "case_id": "alpha",
                "skill_id": "grasp_object",
                "candidate_ref": "candidate",
                "scope_verdict": "supported",
                "outcome": "success",
                "core_start_sec": 1,
                "core_end_sec": 2,
                "context_start_sec": 0,
                "context_end_sec": 3,
                "evidence_refs": ["frame"],
            }
        ],
        "condition_comparisons": [],
    }


def candidates():
    return [{"candidate_ref": "candidate", "prior_model_candidate": {"case_id": "alpha"}}]


def test_contrastive_stage_must_review_all_candidates(review, cases):
    review["examples"] = []
    with pytest.raises(ValueError, match="each candidate_ref"):
        cr.validate_review(review, cases, {"frame": {}}, candidates())


def test_uncertain_skill_scope_remains_unknown(review, cases):
    review["examples"][0].update(scope_verdict="ambiguous", outcome="unknown")
    cr.validate_review(review, cases, {"frame": {}}, candidates())
    review["examples"][0]["outcome"] = "success"
    with pytest.raises(ValueError, match="Unconfirmed skill"):
        cr.validate_review(review, cases, {"frame": {}}, candidates())


def test_lift_scope_cannot_replace_requested_grasp(review, cases):
    review["examples"][0]["skill_id"] = "lift_pen"
    review["skill_definitions"][0]["skill_id"] = "lift_pen"
    with pytest.raises(ValueError, match="requested skill_id"):
        cr.validate_review(review, cases, {"frame": {}}, candidates())


def test_model_failure_has_no_program_fallback(tmp_path, monkeypatch, cases):
    monkeypatch.setattr(mg.config, "BASE_URL", "http://127.0.0.1:8032")
    monkeypatch.setattr(
        mg, "prepare", lambda _: (tmp_path, {}, "prompt", cases, {}, [], tmp_path / "source.mp4", "digest")
    )

    class Broken:
        def __init__(self, *a, **kw):
            self.session = SimpleNamespace(trust_env=True, post=lambda *a, **kw: None)

        def ask(self, **kw):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(mg, "VLMClient", Broken)
    with pytest.raises(RuntimeError, match="model unavailable"):
        mg.analyze(tmp_path, allow_model_service=True)
    assert not (tmp_path / "success_process_model/result.json").exists()
    assert (tmp_path / "success_process_model/failure.json").exists()


def test_model_replacement_invalidates_contrastive_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cr,
        "prepare",
        lambda _: (
            tmp_path,
            {"prior_model_analysis": {"response": {}}, "user_task": "t", "source_videos": []},
            "",
            {},
            {},
            [],
            tmp_path / "v",
            "base",
        ),
    )
    monkeypatch.setattr(cr, "load_model_graph", lambda _: ({"response": {}}, {}, {}))
    monkeypatch.setattr(cr.config, "MODEL", "deployed-A")
    first = cr.packet_for(tmp_path)[-1]
    monkeypatch.setattr(cr.config, "MODEL", "deployed-B")
    assert cr.packet_for(tmp_path)[-1] != first


def test_renderer_keeps_business_fields_exactly(tmp_path, monkeypatch, graph, cases, review):
    graph["nodes"][2]["sources"] = []
    review["examples"][0].update(core_start_sec=None, core_end_sec=None, context_start_sec=None, context_end_sec=None)
    record = {
        "response": graph,
        "model": "synthetic-deployed",
        "analysis_origin": "deployed_model",
        "input_fingerprint": "fingerprint",
    }
    monkeypatch.setattr(wb, "load_model_graph", lambda _: (record, cases, {}))
    monkeypatch.setattr(wb, "load_review", lambda _: {"response": review, "model": "synthetic-deployed"})
    monkeypatch.setattr(wb, "_svg", lambda *a: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>')
    (tmp_path / "summary.json").write_text("{}")
    wb.export(tmp_path)
    assert json.loads((tmp_path / "merged_operation_graph.json").read_text()) == graph
    displayed = json.loads((tmp_path / "merged_operation_view.json").read_text())
    assert displayed["nodes"][2]["seven_tuple"] == graph["nodes"][2]["seven_tuple"]
    for key, value in review["examples"][0].items():
        assert displayed["contrastive_examples"][0][key] == value


def test_retained_ranges_cannot_include_removed_failures(graph, cases):
    decision = graph["source_decisions"][0]
    decision["retained_segments"] = [{"start_sec": 0, "end_sec": 10}]
    decision["removed_failed_segments"] = [{"start_sec": 1, "end_sec": 2}]
    with pytest.raises(ValueError, match="Retained source range"):
        mg.validate_graph(graph, cases, {"frame": {}})


def test_evaluator_is_not_an_action_name(graph, cases):
    graph["nodes"][2]["seven_tuple"]["E"] = {"action": "synthetic action"}
    with pytest.raises(ValueError, match="evaluation criteria"):
        mg.validate_graph(graph, cases, {"frame": {}})


def test_successful_trial_cannot_be_a_negative_comparison(review, cases):
    review["condition_comparisons"] = [{"positive_example_ids": [], "negative_example_ids": ["sample"]}]
    with pytest.raises(ValueError, match="must match local trial outcomes"):
        cr.validate_review(review, cases, {"frame": {}}, candidates())


def test_keep_does_not_imply_proven_necessity(graph, cases):
    graph["simplifications"][0].update(decision="keep", necessity_status="candidate")
    mg.validate_graph(graph, cases, {"frame": {}})
    assert graph["simplifications"][0]["necessity_status"] == "candidate"


@pytest.fixture
def approach_graph(graph):
    """Two successful approach occurrences separated by a false guard and preparation."""
    model_op = deepcopy(graph["nodes"][2])
    model_gate = deepcopy(graph["nodes"][1])

    def operation(node_id, role, context=None):
        n = deepcopy(model_op)
        n.update(id=node_id, action_role=role, label="任意模型标签" + node_id)
        if context is not None:
            n["state_context"] = context
        return n

    def gate(node_id):
        n = deepcopy(model_gate)
        n.update(id=node_id, gate_role="grasp_precondition")
        return n

    nodes = [
        graph["nodes"][0],
        operation("motion_a", "approach_target", "initial_scene"),
        gate("guard_a"),
        operation("prepare", "preparation"),
        operation("motion_b", "approach_target", "after_scene_change"),
        gate("guard_b"),
        operation("target_action", "grasp_target"),
        graph["nodes"][-1],
    ]
    walk = [n["id"] for n in nodes]
    graph["nodes"] = nodes
    graph["edges"] = [
        {
            "id": str(i),
            "from": a,
            "to": b,
            "source_case_ids": ["alpha"],
            **({"gate_outcome": "F"} if a == "guard_a" else {"gate_outcome": "T"} if a == "guard_b" else {}),
        }
        for i, (a, b) in enumerate(zip(walk, walk[1:], strict=False))
    ]
    graph["paths"] = [{"case_id": "alpha", "node_ids": walk}]
    graph["approach_review"] = [
        {
            "case_id": "alpha",
            "status": "observed",
            "reason": "synthetic model declaration",
            "occurrences": [
                {"node_id": "motion_a", "grasp_gate_id": "guard_a", "evidence_refs": ["frame"]},
                {"node_id": "motion_b", "grasp_gate_id": "guard_b", "evidence_refs": ["frame"]},
            ],
        }
    ]
    return graph


def test_repeated_approaches_survive_with_different_state_contexts(approach_graph, cases):
    original = deepcopy(approach_graph)
    mg.validate_graph(approach_graph, cases, {"frame": {}})
    assert approach_graph == original
    motions = [n for n in approach_graph["nodes"] if n.get("action_role") == "approach_target"]
    assert len(motions) == 2 and len({n["id"] for n in motions}) == 2
    assert len({n["state_context"] for n in motions}) == 2
    assert all(n["truth"] == "U" for n in approach_graph["nodes"] if n["kind"] == "gate")


def test_approach_inventory_cannot_omit_first_occurrence(approach_graph, cases):
    approach_graph["approach_review"][0]["occurrences"].pop(0)
    with pytest.raises(ValueError, match="coverage/order"):
        mg.validate_graph(approach_graph, cases, {"frame": {}})


def test_grasp_must_use_true_precondition_branch(approach_graph, cases):
    edge = next(e for e in approach_graph["edges"] if e["from"] == "guard_b")
    edge["gate_outcome"] = "F"
    with pytest.raises(ValueError, match="Grasp requires the T branch"):
        mg.validate_graph(approach_graph, cases, {"frame": {}})


def test_approach_cannot_be_hidden_inside_grasp(approach_graph, cases):
    next(n for n in approach_graph["nodes"] if n["id"] == "motion_b")["action_role"] = "other"
    approach_graph["approach_review"][0]["occurrences"].pop()
    with pytest.raises(ValueError, match="approach"):
        mg.validate_graph(approach_graph, cases, {"frame": {}})


def test_each_approach_needs_its_own_following_grasp_gate(approach_graph, cases):
    approach_graph["approach_review"][0]["occurrences"][1]["grasp_gate_id"] = "guard_a"
    with pytest.raises(ValueError, match="following gate"):
        mg.validate_graph(approach_graph, cases, {"frame": {}})


def test_later_exports_cannot_drop_approach_policy(approach_graph, cases):
    del approach_graph["approach_policy"]
    with pytest.raises(ValueError, match="approach preservation policy"):
        mg.validate_graph(approach_graph, cases, {"frame": {}})


def test_repair_context_uses_only_unchanged_deployed_model_draft(tmp_path):
    from video2op.skill_clips import save, sha256

    source = tmp_path / "synthetic.mp4"
    source.write_bytes(b"synthetic test bytes, not a real video")
    old = tmp_path / "跨视频模型分析"
    save(old / "result.json", {"response": {}, "model": "deployed-test"})
    save(
        old / "inputs.json",
        {
            "packet": {
                "task": "synthetic task",
                "video_mapping": [
                    {"case_id": "alpha", "source": str(source), "sha256": sha256(source), "source_duration": 10}
                ],
            },
            "frames": [],
            "joint_video": str(source),
        },
    )
    candidate = {
        "analysis_origin": "deployed_model_failed_draft",
        "model": "deployed-test",
        "response": {"opaque": "keep unchanged"},
        "validation_errors": ["synthetic contract failure"],
    }
    save(tmp_path / "success_process_model/repair_candidate.json", candidate)
    prepared = mg.prepare(tmp_path)
    assert prepared[1]["prior_model_graph_draft"] == candidate
    first = prepared[-1]
    candidate["response"]["opaque"] = "another model value"
    save(tmp_path / "success_process_model/repair_candidate.json", candidate)
    assert mg.prepare(tmp_path)[-1] != first
    candidate["analysis_origin"] = "agent_authored"
    save(tmp_path / "success_process_model/repair_candidate.json", candidate)
    with pytest.raises(ValueError, match="deployed-model draft"):
        mg.prepare(tmp_path)


def test_failed_request_cannot_replace_valid_historical_inputs(tmp_path):
    from video2op.skill_clips import save

    result = tmp_path / "result.json"
    save(result, {"input_fingerprint": "valid", "response": {"model": "payload"}})
    save(tmp_path / "inputs.json", {"input_fingerprint": "valid", "prompt": "valid prompt"})
    history = mg.archive_model_record(tmp_path, result)
    save(tmp_path / "inputs.json", {"input_fingerprint": "failed", "prompt": "later failed request"})
    mg.archive_model_record(tmp_path, result)
    assert json.loads((history / "inputs.json").read_text())["input_fingerprint"] == "valid"


def test_alignment_preserves_original_task_judgments(graph, cases):
    from video2op.model_graph_alignment import validate_alignment

    output = deepcopy(graph)
    output["source_decisions"][0]["reason"] = "changed by a later stage"
    with pytest.raises(ValueError, match="instance judgments unchanged"):
        validate_alignment(output, graph, cases, {"frame": {}})


def test_alignment_preserves_each_source_approach_count(approach_graph, cases):
    from video2op.model_graph_alignment import validate_alignment

    output = deepcopy(approach_graph)
    keep = {"arbitrary_begin", "motion_b", "guard_b", "target_action", "arbitrary_end"}
    output["nodes"] = [n for n in output["nodes"] if n["id"] in keep]
    walk = ["arbitrary_begin", "motion_b", "guard_b", "target_action", "arbitrary_end"]
    output["paths"][0]["node_ids"] = walk
    output["edges"] = [
        {
            "id": str(i),
            "from": a,
            "to": b,
            "source_case_ids": ["alpha"],
            **({"gate_outcome": "T"} if a == "guard_b" else {}),
        }
        for i, (a, b) in enumerate(zip(walk, walk[1:], strict=False))
    ]
    output["approach_review"][0]["occurrences"].pop(0)
    with pytest.raises(ValueError, match="approach occurrence count"):
        validate_alignment(output, approach_graph, cases, {"frame": {}})


def test_cached_instance_graph_runs_alignment_without_reopening_video(tmp_path, graph, cases, monkeypatch):
    from video2op import model_graph_alignment as alignment
    from video2op.skill_clips import save

    record = {"response": graph, "model": "deployed-test", "input_fingerprint": "digest"}
    save(tmp_path / "success_process_model/result.json", record)
    monkeypatch.setattr(mg.config, "BASE_URL", "http://127.0.0.1:8032")
    monkeypatch.setattr(mg.config, "MODEL", "deployed-test")
    monkeypatch.setattr(
        mg, "prepare", lambda _: (tmp_path, {}, "prompt", cases, {"frame": {}}, [], tmp_path / "v.mp4", "digest")
    )
    calls = []

    def normalize(*args):
        calls.append(args)
        return {"graph_stage": "semantic_merged"}

    monkeypatch.setattr(alignment, "align", normalize)

    def forbidden(*a, **kw):
        raise AssertionError("Reopened the video model stage")

    monkeypatch.setattr(mg, "VLMClient", forbidden)
    assert mg.analyze(tmp_path, allow_model_service=True)["graph_stage"] == "semantic_merged"
    assert len(calls) == 1
