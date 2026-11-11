"""Force a fresh VLM run of one requested case; save live logs and final status."""
import contextlib
from datetime import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cv2
from video2op.pipeline import run_case

cv2.setNumThreads(1)
name = sys.argv[1]
assert name in {"燕麦杯", "抓取1", "抓取2"}
run_dir = ROOT / "logs/live_stateframes_20261022_163602"
run_dir.mkdir(parents=True, exist_ok=True)
status_file = run_dir / (name + ".status.json")
log_file = run_dir / (name + ".log")
begin = time.time()
def status(state, **kwargs):
    doc = {"case": name, "state": state, "started_unix": begin,
           "elapsed_seconds": round(time.time() - begin, 2), "log": str(log_file), **kwargs}
    status_file.write_text(json.dumps(doc, ensure_ascii=False, indent=2))
    return doc

status("running")
try:
    with log_file.open("w", encoding="utf-8", buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            bundle = run_case(ROOT / "data" / (name + ".mp4"), force=True)
    passed = bool(bundle.get("validation", {}).get("passed")) and not bundle.get("errors")
    doc = status("completed" if passed else "validation_failed",
                 validation=bundle.get("validation", {}).get("summary"),
                 calls=bundle["pipeline"]["llm_stats"]["calls"],
                 cache_hits=bundle["pipeline"]["llm_stats"]["cache_hits"],
                 review_status=bundle.get("local_review", {}).get("status"),
                 output=str(ROOT / "output" / (name + "_semantic_v3")))
except Exception as exc:
    import traceback
    with log_file.open("a", encoding="utf-8") as log:
        traceback.print_exc(file=log)
    doc = status("failed", error=f"{type(exc).__name__}: {exc}")
    print(json.dumps(doc, ensure_ascii=False), flush=True)
    raise
print(json.dumps(doc, ensure_ascii=False), flush=True)
