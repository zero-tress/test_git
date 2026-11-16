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
    graph.update(nodes=[], edges=[], paths=[], start_node_id=None, end_node_id=None)
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
