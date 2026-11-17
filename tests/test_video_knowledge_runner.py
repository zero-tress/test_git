"""Workflow safety tests use synthetic files and no model or video interpretation."""
import importlib.util
from pathlib import Path

import pytest


def runner():
    path = Path(__file__).resolve().parents[1] / "tools/learn_video_knowledge.py"
    spec = importlib.util.spec_from_file_location("video_knowledge_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_delivery_cannot_be_overwritten(tmp_path):
    module = runner()
    video = tmp_path / "source.mp4"
    video.write_bytes(b"synthetic")
    output = tmp_path / "delivery"
    output.mkdir()
    sentinel = output / "operations.svg"
    sentinel.write_text("existing graph")
    with pytest.raises(SystemExit):
        module.main(["--videos", str(video), "--out", str(output), "--allow-8032"])
    assert sentinel.read_text() == "existing graph"


def test_duplicate_case_stems_rejected(tmp_path):
    module = runner()
    videos = []
    for folder in ["a", "b"]:
        directory = tmp_path / folder
        directory.mkdir()
        video = directory / "source.mp4"
        video.write_bytes(b"synthetic")
        videos.append(str(video))
    with pytest.raises(SystemExit):
        module.main(["--videos", *videos, "--out", str(tmp_path / "delivery"), "--allow-8032"])
    assert not (tmp_path / "delivery").exists()


def test_resume_refuses_changed_source_before_model_calls(tmp_path, monkeypatch):
    module = runner()
    video = tmp_path / "source.mp4"
    video.write_bytes(b"synthetic")
    output = tmp_path / "delivery"
    def fail(*args, **kwargs):
        raise RuntimeError("interrupted fixture")
    monkeypatch.setattr(module, "run_case", fail)
    monkeypatch.setattr(module.config, "OUTPUT_DIR", module.config.OUTPUT_DIR)
    monkeypatch.setattr(module.config, "WORK_DIR", module.config.WORK_DIR)
    args = ["--videos", str(video), "--out", str(output), "--allow-8032"]
    with pytest.raises(RuntimeError, match="interrupted fixture"):
        module.main(args)
    video.write_bytes(b"changed")
    with pytest.raises(SystemExit):
        module.main([*args, "--resume"])
