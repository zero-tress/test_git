"""Use decoded frame timestamps, including when the nominal tail has no frame."""
import subprocess
from pathlib import Path

import pytest

from video2op.cross_video.skill_sample_pool import _frame

@pytest.fixture
def source(tmp_path):
    path = tmp_path / "tiny.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=blue:s=64x64:r=10:d=0.3", "-threads", "1",
                    "-c:v", "libx264", str(path)], check=True, capture_output=True)
    return path

def test_tail_uses_actual_last_frame_instead_of_failing(source, tmp_path):
    target = tmp_path / "tail.jpg"
    assert _frame(source, target, .29) == pytest.approx(.2)
    assert target.stat().st_size > 0

def test_regular_sample_records_actual_decoded_timestamp(source, tmp_path):
    assert _frame(source, tmp_path / "middle.jpg", .05) == pytest.approx(.1)

def test_resuming_frame_preserves_existing_bytes_and_timestamp(source, tmp_path):
    target = tmp_path / "tail.jpg"
    actual = _frame(source, target, .29)
    before = target.read_bytes()
    assert _frame(source, target, .29) == actual
    assert target.read_bytes() == before
