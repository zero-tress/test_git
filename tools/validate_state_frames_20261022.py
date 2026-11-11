"""Offline real-video verification; no model/network/GPU and no existing output writes."""
from datetime import datetime
from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from video2op import config, local_review, media, sampling

cv2.setNumThreads(2)
out = ROOT / "output" / ("state_frames_validation_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
out.mkdir()
config.WORK_DIR = out / "_clips"
summaries = []
for name in ("燕麦杯", "抓取1", "抓取2"):
    begin = time.perf_counter()
    video = ROOT / "data" / (name + ".mp4")
    original = ROOT / "output" / (name + "_semantic_v3") / "result.json"
    bundle = json.loads(original.read_text())
    ctx = {"video": video, "video_id": media.file_sha1(video), "meta": media.probe(video),
           "out_dir": out / name, "atomic": bundle["atomic"], "relations": bundle["relations"],
           "windows": {}}
    report = sampling.prepare(ctx)
    assert report["status"] == "ok", report.get("reason")
    ctx["sampling"] = report
    selected = sampling.frames_for_window(report, 0, ctx["meta"]["duration"])
    assert selected and all(Path(f["path"]).exists() for f in selected)
    plan = local_review.plan(ctx)
    for p in plan[:config.LOCAL_REVIEW_MAX_WINDOWS]:
        frames = sampling.export_frames(video, p["start"], p["end"],
                                        ctx["out_dir"] / "review_preview" / p["id"],
                                        fps=config.LOCAL_REVIEW_FPS, maximum=config.LOCAL_REVIEW_MAX_FRAMES)
        assert frames and all(p["start"] - 0.05 <= f["timestamp"] <= p["end"] + 0.05 for f in frames)
        clip = media.make_clip(video, p["start"], p["end"] - p["start"],
                               tag="validation", fps=config.LOCAL_REVIEW_FPS)
        assert abs(media.probe(clip)["fps"] - config.LOCAL_REVIEW_FPS) < 0.1
        p["preview_frame_ids"] = [f["frame_id"] for f in frames]
    sampling._save(ctx["out_dir"] / "review_plan_preview.json", plan)
    item = {"video": name, "candidate_frames": report["candidate_frame_count"],
            "events": len(report["events"]), "sampling_windows": len(report["windows"]),
            "unique_selected_frames": len({f["frame_id"] for w in report["windows"] for f in w["selected_frames"]}),
            "review_requests": min(len(plan), config.LOCAL_REVIEW_MAX_WINDOWS),
            "unreviewed_budget": max(0, len(plan) - config.LOCAL_REVIEW_MAX_WINDOWS),
            "seconds": round(time.perf_counter() - begin, 3),
            "gallery": str(Path(report["directory"]) / "index.html")}
    summaries.append(item)
    print(json.dumps(item, ensure_ascii=False), flush=True)
sampling._save(out / "validation_summary.json", summaries)
print("Verification output:", out, flush=True)
