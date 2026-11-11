import json

import pytest

from video2op import config, media, pipeline


def patch_media(tmp_path, monkeypatch):
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"synthetic fixture, not a playable video")
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(media, "probe", lambda _: {
        "name": "sample", "path": str(video), "duration": 4.0, "width": 32,
        "height": 32, "fps": 1, "size_bytes": 10, "nb_frames": 4})
    monkeypatch.setattr(media, "motion_profile",
                        lambda _: {"change_points": [], "hot_segments": []})
    return video


def test_pipeline_stops_after_failed_model_stage_and_saves_diagnostics(tmp_path, monkeypatch):
    video = patch_media(tmp_path, monkeypatch)
    calls = []
    def fail(*args):
        raise ValueError("unavailable model")
    monkeypatch.setattr(pipeline.s01_viewpoint, "run", fail)
    monkeypatch.setattr(pipeline.s02a_intent, "run", lambda *a: calls.append("unexpected"))
    with pytest.raises(ValueError, match="unavailable"):
        pipeline.run_case(video, verbose=False)
    out = config.OUTPUT_DIR / "sample_semantic_v3"
    assert not calls
    assert not (out / "result.json").exists()
    assert json.loads((out / "failure.json").read_text())["failed_stage"] == "s01_viewpoint"


def test_complete_offline_pipeline_exports_overall_motion_and_timing(tmp_path, monkeypatch):
    video = patch_media(tmp_path, monkeypatch)
    old = config.OUTPUT_DIR / "sample"
    old.mkdir(parents=True)
    (old / "result.json").write_text("original")
    actors = [
        (1, "整体", "向目标移动", 0, 1),
        (2, "整体", "下降", 1, 2),
        (3, "整体", "上升", 2, 3),
        (4, "右臂", "向前伸出", 3, 4),
    ]
    actions = [dict(id=i, executor=ex, action=name, mode="motion", start=s, end=e,
                    object="工作台", state_before="", state_after="", world_before=[],
                    world_after=[], inferred=False, confidence=0.8)
               for i, ex, name, s, e in actors]
    nodes = [dict(id=f"n{i}", name=name, atomic_refs=[i], time_range=[s, e],
                  intent_role="调整操作位置", required_capabilities=[name],
                  tuple={"X": {"subject": "操作者", "parts": [ex]}, "O": ["工作台"],
                         "C_pre": [], "C_const": [], "C_post": [],
                         "E": {"process": [], "completion": []}, "R": []})
             for i, ex, name, s, e in actors]
    replacements = [
        (pipeline.s01_viewpoint, {"viewpoint": "third_person", "label_cn": "第三人称"}),
        (pipeline.s02a_intent, {"intents": []}),
        (pipeline.s02b_atomic, {"windows": [{"window": {"index": 1, "start": 0, "duration": 4},
                                            "atomic_actions": actions, "temporal_relations": []}]}),
        (pipeline.s02c_task, {"task_nodes": nodes}),
        (pipeline.s02d_link, {"links": [], "missing_actions": []}),
        (pipeline.s03_sync, {}),
        (pipeline.s04_conditions, {}),
        (pipeline.s05_rules, {}),
    ]
    for stage, payload in replacements:
        monkeypatch.setattr(stage, "run", lambda *a, value=payload: value)
    bundle = pipeline.run_case(video, verbose=False)
    out = config.OUTPUT_DIR / "sample_semantic_v3"
    for name in ("result.json", "operations.svg", "report.html", "workbench.html",
                 "semantic_graph.yaml", "action_catalog.json", "performance.json"):
        assert (out / name).is_file(), name
    assert not (out / "program.json").exists()
    assert not (out / "execution_policy.yaml").exists()
    assert (old / "result.json").read_text() == "original"
    stored = json.loads((out / "result.json").read_text())
    performance = json.loads((out / "performance.json").read_text())
    assert stored["pipeline"] == performance
    assert "render_export" in performance["stage_seconds"]
    assert performance["wall_seconds"] >= performance["stage_seconds"]["render_export"]
    names = [n["name"] for n in bundle["operations"]["nodes"]]
    assert {"向目标移动", "上升", "下降"}.issubset(names)
    svg = (out / "operations.svg").read_text()
    assert all(word not in svg for word in ("腰部", "左腿", "右腿", "膝关节", "左脚", "右脚"))
