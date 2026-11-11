"""Run requested videos serially in isolated outputs; include every failure in the final manifest."""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
rows = []
for name in sys.argv[2:]:
    p = Path('/home/wj/codex-workspace/videostudy_operation copy/data') / name
    result = subprocess.run([sys.executable, '-u', str(root/'tools/run_case_review.py'),
                             str(p), str(destination)], capture_output=True, text=True)
    rows.append({"video": name, "returncode": result.returncode,
                 "stdout": result.stdout, "stderr": result.stderr})
    (destination/'batch_manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
raise SystemExit(1 if any(r["returncode"] for r in rows) else 0)
