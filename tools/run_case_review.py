"""Isolated real-video validation runner; logs/status persist even on a failed model stage."""
import contextlib
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config
from video2op.single_video.pipeline import run_case

video, destination = Path(sys.argv[1]), Path(sys.argv[2])
destination.mkdir(parents=True, exist_ok=True)
config.OUTPUT_DIR = destination
config.WORK_DIR = destination / "_work"
status = destination / (video.stem + ".status.json")
status.write_text(json.dumps({"state": "running", "video": str(video), "started": time.time()}))
code = 0
with (destination / (video.stem + ".log")).open("w", buffering=1) as f:
    with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
        try:
            b = run_case(video, verbose=True)
            code = 0 if b["validation"]["passed"] else 1
            summary = {"state": "completed" if code == 0 else "needs_review", "validation": b["validation"],
                       "pipeline": b["pipeline"], "scope_count": len(b.get("semantic_scope", {}).get("subtasks") or [])}
        except Exception as e:
            traceback.print_exc()
            summary = {"state": "failed", "error": type(e).__name__ + ": " + str(e)}
            code = 1
status.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print(json.dumps({"video": video.name, "state": summary["state"],
                  "scope_count": summary.get("scope_count"), "error": summary.get("error"),
                  "output": str(destination)}, ensure_ascii=False))
raise SystemExit(code)
