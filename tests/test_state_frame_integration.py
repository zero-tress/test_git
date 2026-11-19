from copy import deepcopy
from pathlib import Path

import cv2
import numpy as np
import pytest
from test_arm_hand_scope import example
from test_operation_v2 import Response

from video2op import config, local_review, media, sampling, workbench
from video2op.llm import VLMClient
from video2op.single_video.pipeline import build_learning_graph
from video2op.single_video.stages import s02b_atomic


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "source.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20, (160, 120))
    for i in range(60):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        cv2.rectangle(frame, (20 + i, 40), (40 + i, 65), (240, 240, 240), -1)
        writer.write(frame)
    writer.release()
    return path


def context(video, tmp_path):
    b = example()
    return {"video": video, "video_id": "test-source", "meta": {"duration": 8.0},
            "out_dir": tmp_path / "case", "atomic": deepcopy(b["atomic"]),
            "relations": [], "windows": {"windows": []}}


def frames(tmp_path):
    out = []
    for i, stamp in enumerate([0.5, 1.0, 1.5, 2.0]):
        p = tmp_path / f"f{i}.jpg"
        p.write_bytes(b"image" + bytes([i]))
        out.append({"frame_id": f"f{i}", "timestamp": stamp, "path": str(p)})
    return out


def proposal():
    return {"id": "r1", "start": 0.0, "end": 2.0, "atomic_refs": [2], "reasons": ["test"]}


def test_multimodal_request_keeps_video_and_image_and_hashes_image_metadata(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    f = frames(tmp_path)[:1]
    client, calls = VLMClient(tmp_path / "cache"), []
    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        return Response()
    monkeypatch.setattr(client.session, "post", post)
    def ask():
        return client.ask(stage="t", system="s", user_text="u", video=video, images=f)
    ask()
    ask()
    assert len(calls) == 1
    content = calls[0]["messages"][1]["content"]
    assert {part["type"] for part in content} == {"video_url", "image_url", "text"}
    assert any("全局时间 0.500000s" in p.get("text", "") for p in content)
    Path(f[0]["path"]).write_bytes(b"changed-image")
    ask()
    f[0]["timestamp"] = 0.6
    ask()
    assert len(calls) == 3


def test_image_only_request_uses_multimodal_content(tmp_path, monkeypatch):
    client, captured = VLMClient(tmp_path / "cache"), []
    def post(*args, **kwargs):
        captured.append(kwargs["json"])
        return Response()
    monkeypatch.setattr(client.session, "post", post)
    client.ask(stage="images", system="s", user_text="u", images=frames(tmp_path))
    assert any(x["type"] == "image_url" for x in captured[0]["messages"][1]["content"])


def test_real_source_frame_indices_and_bounded_local_export(video, tmp_path):
    exported = sampling.export_frames(video, 0.5, 1.5, tmp_path / "review", fps=16, maximum=8)
    assert 2 <= len(exported) <= 8
    assert len({f["frame_id"] for f in exported}) == len(exported)
    for frame in exported:
        assert frame["timestamp"] == frame["source_frame_index"] / 20
        assert 0.5 <= frame["timestamp"] <= 1.5
        assert cv2.imread(frame["path"]) is not None


def test_prepare_motion_context_and_gallery_on_real_video(video, tmp_path):
    ctx = context(video, tmp_path)
    ctx["meta"]["duration"] = 3.0
    report = sampling.prepare(ctx)
    assert report["status"] == "ok"
    assert not report["uses_learned_detector"]
    assert report["candidate_frame_count"] >= 20
    out = Path(report["directory"])
    assert (out / "sampling_report.json").exists()
    assert (out / "index.html").exists()
    selected = sampling.frames_for_window(report, 0, 3, maximum=6)
    assert 2 <= len(selected) <= 6
    assert all(0 <= f["timestamp"] <= 3 for f in selected)
    assert all(Path(f["path"]).exists() for f in selected)


def test_sampling_failure_is_explicit_and_keeps_video_path_usable(tmp_path):
    invalid = tmp_path / "bad.mp4"
    invalid.write_bytes(b"invalid")
    ctx = context(invalid, tmp_path)
    report = sampling.prepare(ctx)
    assert report["status"] == "failed"
    assert report["reason"] and not sampling.frames_for_window(report, 0, 8)


def test_sampling_can_be_disabled_without_side_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "KEYFRAMES_ENABLED", False)
    assert sampling.prepare({})["status"] == "disabled"


def test_review_plan_targets_unknown_grasp_and_has_explicit_budget(tmp_path, monkeypatch):
    ctx = context(tmp_path / "v.mp4", tmp_path)
    ctx["atomic"]["atomic_actions"][1]["state_before"] = ""
    ctx["sampling"] = {"refinement": {"proposals": [
        {"start_time": float(i), "end_time": i + 0.25, "reason": "short_event"}
        for i in range(8)]}}
    monkeypatch.setattr(config, "LOCAL_REVIEW_MAX_WINDOWS", 1)
    plan = local_review.plan(ctx)
    assert plan[0]["priority"] == 0
    assert 2 in plan[0]["atomic_refs"]
    assert all(p.get("status") == "skipped_budget" for p in plan[1:])


@pytest.mark.parametrize("bad", ["invented_frame", "unknown_action", "duplicate_check"])
def test_review_rejects_fabricated_references_and_duplicate_conclusions(tmp_path, bad):
    f = frames(tmp_path)
    check = {"atomic_ref": 2, "field": "state_before", "status": "observed",
             "state": "右手已张开", "evidence_frames": ["f0"]}
    checks = [check]
    if bad == "invented_frame":
        check["evidence_frames"] = ["fake"]
    elif bad == "unknown_action":
        check["atomic_ref"] = 999
    else:
        checks.append(deepcopy(check))
    with pytest.raises(ValueError):
        local_review.validate({"state_checks": checks, "missing_actions": []}, proposal(), f)


def test_review_fills_unknown_but_does_not_overwrite_observation(tmp_path):
    ctx = context(tmp_path / "v.mp4", tmp_path)
    a = next(a for a in ctx["atomic"]["atomic_actions"] if a["id"] == 2)
    a["state_before"] = ""
    data = {"state_checks": [{"atomic_ref": 2, "field": "state_before", "status": "observed",
                             "state": "右手已张开", "evidence_frames": ["f0"]}], "missing_actions": []}
    f = frames(tmp_path)
    local_review.validate(data, proposal(), f)
    result = local_review.apply(ctx, data, proposal(), f)
    assert result["state_updates"]
    assert a["state_before"] == "右手已张开"
    assert a["visual_state_evidence"][0]["frames"][0]["frame_id"] == "f0"
    data["state_checks"][0]["state"] = "右手闭合"
    result = local_review.apply(ctx, data, proposal(), f)
    assert result["conflicts"] and a["state_before"] == "右手已张开"


def test_wrong_boundary_frame_is_not_state_evidence(tmp_path):
    ctx = context(tmp_path / "v.mp4", tmp_path)
    a = next(a for a in ctx["atomic"]["atomic_actions"] if a["id"] == 2)
    a["state_before"] = ""
    data = {"state_checks": [{"atomic_ref": 2, "field": "state_before", "status": "observed",
                             "state": "右手已张开", "evidence_frames": ["f3"]}], "missing_actions": []}
    outcome = local_review.apply(ctx, data, proposal(), frames(tmp_path))
    assert outcome["conflicts"] and not a["state_before"]


def test_reviewed_missing_transition_needs_multiple_actual_frames(tmp_path):
    action = {"id": 1, "executor": "右手", "action": "右手张开手指", "mode": "transition",
              "start": 0.5, "end": 1.0, "world_before": [], "world_after": [],
              "state_before": "", "state_after": "右手已张开", "confidence": 0.8,
              "evidence_frames": ["f0"]}
    data = {"state_checks": [], "missing_actions": [action]}
    f = frames(tmp_path)
    with pytest.raises(ValueError, match="两个"):
        local_review.validate(data, proposal(), f)
    action["evidence_frames"] = ["f0", "f1"]
    local_review.validate(data, proposal(), f)
    ctx = context(tmp_path / "v.mp4", tmp_path)
    outcome = local_review.apply(ctx, data, proposal(), f)
    assert len(outcome["added_refs"]) == 1
    added = next(a for a in ctx["atomic"]["atomic_actions"] if a["id"] == outcome["added_refs"][0])
    assert added["origin"] == "video_local_review" and not added["inferred"]
    assert added["start"] == 0.5 and len(added["visual_evidence"]) == 2


def test_local_review_model_failure_keeps_atomic_evidence(video, tmp_path, monkeypatch):
    ctx = context(video, tmp_path)
    ctx["meta"]["duration"] = 3.0
    ctx["atomic"]["atomic_actions"][1]["state_before"] = ""
    original = deepcopy(ctx["atomic"])
    monkeypatch.setattr(config, "LOCAL_REVIEW_MAX_WINDOWS", 1)
    monkeypatch.setattr(media, "make_clip", lambda *args, **kwargs: video)
    class Offline:
        def ask(self, **kwargs):
            raise RuntimeError("model unavailable")
    report = local_review.run(Offline(), ctx)
    assert report["status"] == "partial"
    assert ctx["atomic"] == original
    assert report["proposals"][0]["status"] == "failed"
    assert (ctx["out_dir"] / "local_review/review_report.json").exists()


def test_local_review_success_calls_video_with_frames_and_saves_provenance(video, tmp_path, monkeypatch):
    ctx = context(video, tmp_path)
    ctx["meta"]["duration"] = 3.0
    ctx["atomic"]["atomic_actions"][1]["state_before"] = ""
    monkeypatch.setattr(config, "LOCAL_REVIEW_MAX_WINDOWS", 1)
    monkeypatch.setattr(media, "make_clip", lambda *args, **kwargs: video)
    captured = []
    class Model:
        def ask(self, **kwargs):
            captured.append(kwargs)
            image = next(f for f in kwargs["images"] if f["timestamp"] < 1.0)
            response = {"state_checks": [{"atomic_ref": 2, "field": "state_before", "status": "observed",
                         "state": "右手已张开", "evidence_frames": [image["frame_id"]]}], "missing_actions": []}
            kwargs["validator"](response)
            return response
    report = local_review.run(Model(), ctx)
    assert report["status"] == "ok"
    assert captured[0]["video"] == video and len(captured[0]["images"]) >= 2
    assert report["results"][0]["applied"]["state_updates"]
    assert (ctx["out_dir"] / "local_review/review_1/review.json").exists()


def test_atomic_stage_sends_state_images_alongside_video(tmp_path, monkeypatch):
    ctx = context(tmp_path / "v.mp4", tmp_path)
    f = frames(tmp_path)
    ctx.update(profile={}, intents={"intents": []}, viewpoint={},
               sampling={"windows": [{"selected_frames": f}]})
    monkeypatch.setattr(media, "make_clip", lambda *args, **kwargs: ctx["video"])
    class Model:
        def ask(self, **kwargs):
            assert kwargs["video"] == ctx["video"] and len(kwargs["images"]) == 4
            assert "全局时间" in kwargs["user_text"]
            value = deepcopy(example()["atomic"])
            kwargs["validator"](value)
            return value
    out = s02b_atomic.run(Model(), ctx)
    assert out["windows"][0]["input_frame_ids"] == [x["frame_id"] for x in f]


def test_workbench_exposes_sampling_gallery_without_changing_graph(tmp_path):
    b = example()
    build_learning_graph(b)
    case = tmp_path / "case"
    gallery = case / "sampling/unique"
    gallery.mkdir(parents=True)
    b["sampling"] = {"directory": str(gallery), "status": "ok"}
    b["local_review"] = {"proposals": [{"status": "reviewed"}, {"status": "skipped_budget"}]}
    data = workbench.build(case, bundle=b)
    page = workbench.render(data)
    assert "sampling/unique/index.html" in page
    assert "局部复查 1 次" in page and "未完成 1 项" in page
    assert 'class="gs-node"' in page and "七元组" in page
