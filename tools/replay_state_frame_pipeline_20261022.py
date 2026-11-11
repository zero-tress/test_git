"""Replay saved model answers to verify the full new media path offline.

This validates integration, NOT new model recognition accuracy.
"""
from datetime import datetime
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from video2op import config, pipeline

cv2.setNumThreads(2)
saved = ROOT / "output/抓取1_semantic_v3/stages"
out = ROOT / "output" / ("state_frame_pipeline_replay_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
config.OUTPUT_DIR = out
config.WORK_DIR = out / "_clips"

class ReplayClient:
    def __init__(self, *args, **kwargs):
        self.stats = {"calls": 0, "cache_hits": 0, "failures": 0, "seconds": 0,
                      "attempts": [], "mode": "offline_saved_response_replay"}

    def ask(self, **kwargs):
        stage = kwargs["stage"]
        if stage.startswith("s02r_"):
            result = {"state_checks": [], "missing_actions": [],
                      "notes": "Offline replay: no new model evidence asserted"}
        elif stage.startswith("s02b_atomic_w"):
            window = int(stage.split("_w")[-1]) - 1
            result = json.loads((saved / "s02b_atomic.json").read_text())["windows"][window]
        elif stage == "s04_conditions":
            matches = sorted((saved.parent / "cache").glob("s04_conditions_*.json"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
            result = next(json.loads(p.read_text())["result"] for p in matches
                          if "items" in json.loads(p.read_text()).get("result", {}))
        else:
            result = json.loads((saved / (stage + ".json")).read_text())
        if kwargs.get("validator"):
            kwargs["validator"](result)
        self.stats["attempts"].append({"stage": stage, "video_attached": bool(kwargs.get("video")),
                                       "state_image_count": len(kwargs.get("images") or []),
                                       "mode": "offline_replay"})
        return result

pipeline.VLMClient = ReplayClient
bundle = pipeline.run_case(ROOT / "data/抓取1.mp4", verbose=False)
assert bundle["validation"]["passed"]
assert bundle["sampling"]["status"] == "ok"
attempts = bundle["pipeline"]["llm_stats"]["attempts"]
assert any(p["stage"].startswith("s02b_atomic_w") and p["video_attached"] and p["state_image_count"] > 0
           for p in attempts)
assert any(p["stage"].startswith("s02r_") and p["video_attached"] and p["state_image_count"] >= 2
           for p in attempts)
target = out / "抓取1_semantic_v3"
assert (target / "workbench.html").exists()
assert (target / "local_review/review_report.json").exists()
print(json.dumps({"output": str(target), "validation": bundle["validation"]["summary"],
                  "requests": attempts, "mode": "offline replay, not fresh VLM"}, ensure_ascii=False))
