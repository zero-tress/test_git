"""Freeze source media identities and an immutable copy of the previous experiment."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main():
    old = ROOT / "output/semantic_16_20261107"
    baseline = ROOT / "output/_baseline_20261111"
    target = ROOT / "eval"
    target.mkdir(exist_ok=True)
    manifest = json.loads((old / "manifest.json").read_text())
    rows = []
    for item in manifest["cases"]:
        actual = sha256(item["source"])
        if actual != item["sha256"] or actual != sha256(item["input"]):
            raise ValueError("Media identity mismatch: " + item["id"])
        rows.append({"id": item["id"], "source": item["source"], "sha256": actual,
                     "split": item["split"], "kind": "current_case"})
    for i, path in enumerate(sorted((ROOT / "data").glob("*.mp4")), 1):
        rows.append({"id": "historical_%02d" % i, "source": str(path),
                     "sha256": sha256(path), "split": "historical", "kind": "historical"})
    if not baseline.exists():
        shutil.copytree(old, baseline)
        # Only the new copy is made read-only. Original cases remain untouched.
        for path in baseline.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o222)
    checks = []
    for path in sorted((old / "cases").glob("*/result.json")):
        b = json.loads(path.read_text())
        checks.append({"case": path.parent.name, "validation": b["validation"],
                       "result_sha256": sha256(path)})
        if sha256(baseline / path.relative_to(old)) != sha256(path):
            raise ValueError("Baseline copy differs: " + str(path))
    test = subprocess.run(["python", "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=ROOT, text=True, capture_output=True)
    report = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "baseline": str(baseline), "pytest_returncode": test.returncode,
              "pytest_output": test.stdout + test.stderr, "cases": checks,
              "policy": "The previous experiment is frozen; changes are generated in a new run."}
    for name, value in [("manifest.json", {"schema_version": "evaluation_manifest.v1", "media": rows,
                                          "holdout_ids": ["02", "06", "14"]}),
                        ("baseline_report.json", report)]:
        p = target / name
        if p.exists():
            raise FileExistsError(p)
        p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"media": len(rows), "baseline": str(baseline),
                      "pytest": test.stdout.strip().splitlines()[-1]}, ensure_ascii=False))
    return test.returncode

if __name__ == "__main__":
    raise SystemExit(main())
