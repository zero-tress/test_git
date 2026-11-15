import pytest

from tools import reanalyze_sixteen_8032 as runner


def media():
    return {
        "media": [{"id": f"{i:02d}", "sha256": f"sha{i}", "kind": "current_case"} for i in range(1, 17)]
        + [{"id": "historical_01", "sha256": "other", "kind": "historical"}]
    }


def test_only_the_sixteen_dataset_videos_are_selected():
    selected = runner.selected_media(media())
    assert len(selected) == 16
    assert [r["id"] for r in selected] == [f"{i:02d}" for i in range(1, 17)]


def test_duplicate_video_bytes_cannot_inflate_dataset_size():
    rows = media()
    rows["media"][1]["sha256"] = rows["media"][0]["sha256"]
    with pytest.raises(ValueError, match="16 unique"):
        runner.selected_media(rows)


def test_task_audit_cannot_reference_an_unprovided_frame():
    response = {
        "attempted": "T",
        "final_region": "B",
        "final_stationary": "T",
        "hand_separated_final": "T",
        "goal_satisfied_final": "T",
        "drop": "F",
        "method": "Push",
        "evidence": [{"field": "attempted", "truth": "T", "evidence_frames": ["invented"]}],
    }
    with pytest.raises(ValueError, match="Invented"):
        runner.validate_task(response, [{"frame_id": "real"}])


def test_analysis_cannot_use_an_unapproved_model_endpoint(monkeypatch):
    monkeypatch.setattr(runner.config, "BASE_URL", "http://example.org:8032")
    with pytest.raises(ValueError, match="loopback"):
        runner.endpoint_check()


def test_task_validation_feedback_names_the_invalid_node_and_allowed_functions():
    from video2op.stages.common import ValidationFailure
    from video2op.stages.s02c_task import _validate

    payload = {
        "task_nodes": [
            {
                "id": "bad_push",
                "name": "推",
                "intent_role": "使物体移动",
                "required_capabilities": ["推"],
                "tuple": {
                    "X": {"subject": "左手", "parts": ["左手"]},
                    "O": ["盒子"],
                    "C_pre": [],
                    "C_const": [],
                    "E": {},
                    "C_post": [],
                    "R": [],
                },
            }
        ]
    }
    with pytest.raises(ValidationFailure) as error:
        _validate(payload)
    message = str(error.value)
    assert "id=bad_push" in message and "actor=左手" in message and "接触" in message


def test_dense_execution_review_does_not_turn_goal_failure_into_success(tmp_path):
    import json

    from tools.build_reanalysis_sixteen import dense_execution_evidence

    folder = tmp_path / "output"
    source = tmp_path / "process_review/04_execution_dense/result.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "status": "completed",
                "response": {
                    "target_displaced": "T",
                    "hand_caused_target_motion": "T",
                    "target_reached_B": "F",
                    "movement_method": "Push",
                },
            }
        )
    )
    b = {
        "task_observation": {
            "attempted": "F",
            "outcome": "not_executed",
            "goal_satisfied_final": "F",
            "method": "None",
            "evidence": [],
        }
    }
    dense_execution_evidence(b, {"id": "04", "sha256": "video"}, tmp_path, folder)
    assert b["task_observation"]["attempted"] == "T"
    assert b["task_observation"]["outcome"] == "failure"
    assert b["task_observation"]["goal_satisfied_final"] == "F"
    assert b["task_observation"]["initial_task_audit_attempted"] == "F"


def test_dense_drop_review_preserves_whole_task_success(tmp_path):
    import json

    from tools.build_reanalysis_sixteen import dense_process_evidence

    source = tmp_path / "process_review/09_dense/result.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({"status": "completed", "response": {"drop": "T", "events": []}, "frames": []}))
    b = {"task_observation": {"drop": "F", "outcome": "success", "goal_satisfied_final": "T", "evidence": []}}
    dense_process_evidence(b, {"id": "09", "sha256": "video"}, tmp_path, tmp_path / "output")
    assert b["task_observation"]["drop"] == "T"
    assert b["task_observation"]["outcome"] == "success"
    assert b["task_observation"]["goal_satisfied_final"] == "T"
    assert b["task_observation"]["initial_task_audit_drop"] == "F"
