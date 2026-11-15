"""Verify active single-video output layout and the unified seven-tuple skill outline."""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.semantic_interface import validate_files
from video2op.skill_clips import save, sha256
from video2op.skill_library import FIELDS, LIBRARY, load


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls.extend(v for k, v in attrs if k in {"href", "src"} and v)


def verify(out, live=None):
    out = Path(out).resolve()
    summary = json.loads((out/"layout_summary.json").read_text())
    cases = [Path(r["case"]) for r in summary["cases"]]
    if live:
        cases.append(Path(live).resolve())
    errors, clips, html_files, svg_files = [], 0, 0, 0
    library = load()
    source_uids = set()
    for case in cases:
        for old in ["report.html", "semantic_graph.yaml", "action_catalog.json"]:
            if (case/old).exists():
                errors.append({"case": str(case), "reason": "obsolete_output", "name": old})
        b = json.loads((case/"result.json").read_text())
        index = json.loads((case/"clip/sequence.json").read_text())
        view = json.loads((case/"skill_instances.json").read_text())
        if index["analysis_time"] != b["meta"]["analysis_time"]:
            errors.append({"case": str(case), "reason": "analysis_clock_mismatch"})
        if index["status"] != "complete":
            errors.append({"case": str(case), "reason": "clip_export_incomplete"})
        if view["template_revision"] != library["revision"]:
            errors.append({"case": str(case), "reason": "stale_template_revision"})
        for key in ["catalog_ref", "skill_templates_ref"]:
            if not (case/view[key]).resolve().is_file():
                errors.append({"case": str(case), "reason": "missing_global_outline", "key": key})
        for row in view["instances"]:
            if set(row["seven_tuple"]) != set(FIELDS) or row["template_ref"] not in library["templates"]:
                errors.append({"case": str(case), "reason": "invalid_instance_seven_tuple"})
        if [r["clip_id"] for r in index["clips"]] != index["chronological_order"]:
            errors.append({"case": str(case), "reason": "invalid_order_index"})
        starts = [r["action_start_sec"] for r in index["clips"]]
        if starts != sorted(starts):
            errors.append({"case": str(case), "reason": "action_time_order_changed"})
        for n, row in enumerate(index["clips"], 1):
            if row["sequence_index"] != n or not re.fullmatch(r".+_.+_\d{3}_\d{8}_\d{6}_\d{6}\.mp4", row["filename"]):
                errors.append({"case": str(case), "reason": "filename_or_number"})
            if row["status"] != "exported" or sha256(case/"clip"/row["filename"]) != row["sha256"]:
                errors.append({"case": str(case), "reason": "clip_bytes"})
            if not row["probe"]["decode_verified"]:
                errors.append({"case": str(case), "reason": "clip_decode"})
            if row["source_start_sec"] > row["action_start_sec"] or row["source_end_sec"] < row["action_end_sec"]:
                errors.append({"case": str(case), "reason": "core_outside_clip"})
            clips += 1
        if sha256(index["source_video"]["path"]) != index["source_video"]["sha256"]:
            errors.append({"case": str(case), "reason": "source_changed"})
        source_uids.add(index["source_video"]["sha256"])
        if not validate_files(case)["passed"]:
            errors.append({"case": str(case), "reason": "unbound_interface_invalid"})
    for p in out.rglob("*.html"):
        parser = Links()
        parser.feed(p.read_text(encoding="utf-8"))
        for url in parser.urls:
            parsed = urlparse(url)
            if parsed.scheme or not parsed.path:
                continue
            if not (p.parent/unquote(parsed.path)).exists():
                errors.append({"case": str(p), "reason": "broken_link", "url": url})
        html_files += 1
    for p in out.rglob("*.svg"):
        ET.parse(p)
        svg_files += 1
    baseline = json.loads((out/"source_hashes.json").read_text())
    for p, digest in baseline.items():
        if sha256(p) != digest:
            errors.append({"case": p, "reason": "historical_file_changed"})
    catalog = json.loads((LIBRARY/"learned_skill_catalog.json").read_text())
    evaluators = {e["evaluator_id"] for e in catalog["evaluators"]["evaluators"]}
    for row in catalog["skills"]:
        s = row["learned_seven_tuple"]
        if set(s) != set(FIELDS) or not set(s["C_post"]) <= set(catalog["predicates"]) or not set(s["E"]) <= evaluators:
            errors.append({"case": row["skill_id"], "reason": "global_seven_tuple_or_predicate"})
        for r in s["R"]:
            if not (Path(catalog["artifact_base"])/r["implementation_graph_ref"]).is_file():
                errors.append({"case": row["skill_id"], "reason": "unresolved_implementation_graph"})
    eval_manifest = json.loads((Path(__file__).resolve().parents[1]/"eval/manifest.json").read_text())
    held = {r["sha256"] for r in eval_manifest["media"] if r.get("split") == "holdout"}
    if set(catalog["source_video_uids"]) & held:
        errors.append({"case": "global_catalog", "reason": "holdout_leak"})
    return {"passed": not errors, "cases": len(cases), "source_videos": len(source_uids), "clip_entries": clips,
            "html_files": html_files, "svg_files": svg_files, "historical_files_unchanged": len(baseline),
            "declared_templates": len(library["templates"]), "learned_skills": len(catalog["skills"]), "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--live-case", type=Path)
    args = ap.parse_args(argv)
    result = verify(args.out, args.live_case)
    save(args.out/"layout_verification.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
