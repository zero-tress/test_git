"""Offline source, reference, graph and regression verification for the new delivery."""
import argparse
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.cross_video_delivery import save
from video2op.general_graph import validate_reconstruction
from video2op.skill_clips import sha256

ROOT = Path(__file__).resolve().parents[1]


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(value for key, value in attrs if key in {"href", "src"} and value)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--delivery", required=True, type=Path)
    ap.add_argument("--clips", required=True, type=Path)
    args = ap.parse_args(argv)
    out = args.delivery.resolve()
    clips = args.clips.resolve()
    errors = []
    manifest = json.loads(clips.read_text())
    count = 0
    for row in manifest["instances"]:
        for segment in row["segments"]:
            p = clips.parent/segment["path"]
            if sha256(p) != segment["probe"]["sha256"] or not segment["probe"]["decode_verified"]:
                errors.append("clip_hash_or_decode:"+str(p))
            if not 0 <= segment["start"] < segment["end"]:
                errors.append("clip_time:"+str(p))
            count += 1
    for video in manifest["videos"]:
        if sha256(video["source"]) != video["source_sha256"]:
            errors.append("source_video_changed:"+video["case_id"])
    baseline = json.loads((out/"source_hashes.json").read_text())
    for name, expected in baseline.items():
        if sha256(name) != expected:
            errors.append("old_delivery_changed:"+name)
    graph_counts = {}
    for name in ["knowledge_development", "knowledge_all_16", "holdout_observations"]:
        k = json.loads((out/name/"knowledge.json").read_text())
        instances = {i["instance_id"]: i for i in k["instances"]}
        total = 0
        for s in k["skills"]:
            checked = validate_reconstruction(s["general_operation_graph"], instances)
            errors.extend(checked["errors"])
            total += checked["instances_checked"]
        graph_counts[name] = total
        tuples = json.loads((out/name/"skill_tuples.json").read_text())
        for s in tuples["skills"]:
            graph = json.loads((out/name/("general_graphs/"+s["skill_id"]+".json")).read_text())
            paths = {p["path_id"] for p in graph["alternatives"]}
            for r in s["R"]:
                if not (out/name/r["implementation_graph_ref"]).is_file() or not set(r["path_ids"]) <= paths:
                    errors.append("R_graph_reference:"+r["id"])
    html_count = svg_count = 0
    for folder in [out, clips.parent]:
        for p in folder.rglob("*.html"):
            parser = Links()
            parser.feed(p.read_text())
            for url in parser.urls:
                parsed = urlparse(url)
                if parsed.scheme or not parsed.path:
                    continue
                if not (p.parent/unquote(parsed.path)).exists():
                    errors.append("broken_link:"+str(p)+":"+url)
            html_count += 1
        for p in folder.rglob("*.svg"):
            ET.parse(p)
            svg_count += 1
    summary = json.loads((out/"verification_summary.json").read_text())
    if summary["frozen_development_sha256"] != sha256(out/"knowledge_development/knowledge.json"):
        errors.append("frozen_knowledge_changed")
    qa = {"clip_files_verified": count, "source_videos_verified": len(manifest["videos"]),
          "old_delivery_files_unchanged": len(baseline), "source_paths_checked": graph_counts,
          "html_files_checked": html_count, "svg_files_checked": svg_count, "errors": errors}
    commands = {
        "pytest": [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        "ruff": [sys.executable, "-B", "-m", "ruff", "check",
                 "video2op/skill_clips.py", "video2op/cross_video_alignment.py", "video2op/general_graph.py",
                 "video2op/cross_video_delivery.py", "video2op/generalized_holdout.py",
                 "tools/finish_cross_video_generalization.py", "tools/review_cross_video_samples.py",
                 "tools/attach_cross_video_reviews.py", "tools/verify_cross_video_delivery.py",
                 "tests/test_cross_video_generalization.py", "run.py", "learn.py"],
        "diff_whitespace": ["git", "diff", "--check"],
        "single_cli_help": [sys.executable, "-B", "run.py", "--help"],
        "learning_cli_help": [sys.executable, "-B", "learn.py", "--help"]}
    qa["checks"] = {}
    for name, command in commands.items():
        r = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=90)
        qa["checks"][name] = {"passed": r.returncode == 0, "output": r.stdout+r.stderr}
        if r.returncode:
            errors.append(name+"_failed")
    if shutil.which("node"):
        script = re.search(r"<script>(.*?)</script>", (out/"knowledge_development/cross_video_review.html").read_text(), re.S).group(1)
        script_path = out/"review_script_qa.js"
        script_path.write_text(script)
        r = subprocess.run(["node", "--check", str(script_path)], capture_output=True, text=True)
        qa["checks"]["review_javascript"] = {"passed": r.returncode == 0, "output": r.stdout+r.stderr}
        if r.returncode:
            errors.append("javascript_syntax")
    qa["passed"] = not errors
    save(out/"final_verification.json", qa)
    print(json.dumps({k: v for k, v in qa.items() if k != "checks"}, ensure_ascii=False))
    print(qa["checks"]["pytest"]["output"].strip())
    print("RUFF", qa["checks"]["ruff"]["output"].strip())
    return 0 if qa["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
