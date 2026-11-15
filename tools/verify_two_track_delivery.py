"""Validate two-track source preservation, tuples, actual clips, and offline links."""

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.knowledge import validate
from video2op.skill_clips import save, sha256
from video2op.skill_tuple import FIELDS


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.scripts = []
        self.inline = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        for key in ["src", "href"]:
            if d.get(key):
                self.links.append(d[key])
        if tag == "script" and not d.get("src"):
            self.inline = True
        for key, value in attrs:
            if key.startswith("on") and value:
                self.scripts.append("function handler(){" + value + "}")

    def handle_endtag(self, tag):
        if tag == "script":
            self.inline = False

    def handle_data(self, data):
        if self.inline:
            self.scripts.append(data)


def verify(root):
    root = Path(root).resolve()
    track = root / "learning_tracks" if (root / "learning_tracks").is_dir() else root
    manifest = json.loads((track / "learning_tracks.json").read_text())
    errors = []
    checks = {}
    ks = {}
    for name in ["same_goal_graphs", "classified_skill_clips"]:
        folder = track / name
        k = json.loads((folder / "knowledge.json").read_text())
        ks[name] = k
        if not validate(k)["passed"]:
            errors.append(name + ": knowledge validation failed")
        view = json.loads((folder / "skill_tuples.json").read_text())
        for s in view["skills"]:
            if any(f not in s for f in FIELDS):
                errors.append("Tuple fields missing")
        for s in k["skills"]:
            if not s["general_operation_graph"]["reconstruction_validation"]["passed"]:
                errors.append(name + ": source graph path loss")
        checks[name] = {"videos": len(k["sources"]), "instances": len(k["instances"]), "skills": len(k["skills"])}
    tasks = {u["instance_id"]: u for u in ks["same_goal_graphs"]["instances"]}
    local = {u["instance_id"]: u for u in ks["classified_skill_clips"]["instances"]}
    for u in tasks.values():
        if u["instance_scope"] != "purpose_task":
            errors.append("Wrong whole-task scope")
    for u in local.values():
        if u["instance_scope"] == "purpose_task":
            errors.append("Whole task mixed into local clip trial pool")
        for parent in u.get("parent_task_refs", []):
            if parent not in tasks or not set(u["atomic_refs"]) <= set(tasks[parent]["atomic_refs"]):
                errors.append("Invalid parent task reference")
    sources = {}
    for u in list(tasks.values()) + list(local.values()):
        p = Path(u.get("analysis_source", u["source"]))
        b = json.loads(p.read_text())
        video = Path(b["meta"]["path"])
        sources[str(video)] = u["video_uid"]
    for p, uid in sources.items():
        if sha256(p) != uid:
            errors.append("Original source changed: " + p)
    cm = json.loads((track / "classified_skill_clips/clip_index.json").read_text())
    if {r["instance_id"] for r in cm["instances"]} != set(local):
        errors.append("Classified clip index mismatch")
    decoded = 0
    for row in cm["instances"]:
        for seg in row["segments"]:
            if seg["status"] != "exported":
                if seg["status"] == "outside_verified_decode_coverage" and row["outcome"] != "unknown":
                    errors.append("Unobserved clip promoted to a positive or negative")
                continue
            p = track / "classified_skill_clips" / seg["path"]
            if sha256(p) != seg["probe"]["sha256"]:
                errors.append("Clip bytes changed: " + str(p))
            expected = seg["source_end_sec"] - seg["source_start_sec"]
            if abs(seg["probe"]["duration"] - expected) > max(0.2, 2 / max(seg["probe"]["fps"], 1)):
                errors.append("Clip/source duration mismatch: " + str(p))
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-threads", "1", "-i", str(p), "-f", "null", "-"],
                text=True,
                capture_output=True,
                timeout=60,
            )
            if r.returncode or r.stderr.strip():
                errors.append("Clip decode failed: " + str(p))
            decoded += 1
    checks["original_videos_unchanged"] = len(sources)
    checks["decoded_classified_mp4"] = decoded
    links = 0
    scripts = []
    html_count = 0
    for p in root.rglob("*.html"):
        parser = Links()
        parser.feed(p.read_text())
        for ref in parser.links:
            parsed = urlsplit(ref)
            if parsed.scheme or not parsed.path:
                continue
            target = p.parent / unquote(parsed.path)
            if not target.exists():
                errors.append("Broken link: " + str(p) + " -> " + ref)
            links += 1
        scripts += parser.scripts
        html_count += 1
    for p in root.rglob("*.svg"):
        ET.parse(p)
    if scripts:
        script_file = root / "_verification" / "inline_scripts.js"
        script_file.parent.mkdir(parents=True, exist_ok=True)
        script_file.write_text(
            "\n".join("function block" + str(i) + "(){\n" + s + "\n}" for i, s in enumerate(scripts))
        )
        check = subprocess.run(["node", "--check", str(script_file)], text=True, capture_output=True, timeout=60)
        if check.returncode:
            errors.append("JavaScript syntax: " + check.stderr[-1200:])
    checks.update(html_documents=html_count, local_links_checked=links, script_fragments=len(scripts))
    cases = root / "cases"
    if cases.is_dir():
        for folder in cases.iterdir():
            if not folder.is_dir():
                continue
            for unwanted in ["report.html", "semantic_graph.yaml", "action_catalog.json"]:
                if (folder / unwanted).exists():
                    errors.append("Removed single-video output reappeared: " + unwanted)
            required = [
                "task_learning_units.json",
                "clip_classification.json",
                "task_causal_audit.json",
                "clip/sequence.json",
            ]
            for name in required:
                if not (folder / name).is_file():
                    errors.append("Missing case output: " + str(folder / name))
    guards = json.loads((track / "branch_guards.json").read_text())
    if guards["automatic_execution_rules"] != 0:
        errors.append("Unreviewed guards enabled execution")
    return {
        "passed": not errors,
        "checks": checks,
        "errors": errors,
        "delivery": str(root),
        "local_outcome_counts": manifest["local_outcome_counts"],
        "branch_count": len(guards["branches"]),
        "routing_rule_count": sum(len(b["rules"]) for b in guards["branches"]),
        "causally_verified": False,
        "browser_visual_qa": False,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    result = verify(args.out)
    save(args.out / "verification.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
