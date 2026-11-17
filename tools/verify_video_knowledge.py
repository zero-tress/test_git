"""Read-only knowledge checks; no semantic classification or video interpretation."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op.case_graph import validate as validate_case
from video2op.llm import require_deployed_model
from video2op.semantic_aggregation import load_cases, validate_graph


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"href", "src", "poster"} and value:
                self.links.append(value)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(out, preserved=None):
    out = Path(out).resolve()
    manifest = json.loads((out / "run_manifest.json").read_text())
    if manifest.get("status") != "complete":
        raise ValueError("This batch has not completed")
    inputs = []
    results = []
    calls = cache_hits = 0
    for row in manifest["cases"]:
        source = Path(row["result"])
        if sha(row["video"]) != row["video_sha256"] or sha(source) != row["result_sha256"]:
            raise ValueError("Source video/result changed")
        bundle = json.loads(source.read_text())
        validate_case(bundle["case_graph"], bundle)
        case = source.parent
        for name in ["operations.svg", "workbench.html", "G_case.json", "G_case.svg"]:
            if not (case / name).is_file():
                raise ValueError("Missing single-video artifact: " + name)
        if json.loads((case / "G_case.json").read_text()) != bundle["case_graph"]:
            raise ValueError("G_case export differs from result.json")
        if bundle["case_graph"]["provenance"]["observation_independence"] != "frozen_pre_sync":
            raise ValueError("Observation branch was not frozen independently")
        inputs.append(source)
        metrics = bundle["pipeline"]["llm_stats"]
        calls += metrics["calls"]
        cache_hits += metrics["cache_hits"]
        results.append({"video": row["video"], "task_outcome": bundle["case_graph"]["task_outcome"],
                        "semantic_instances": len(bundle["case_graph"]["nodes"]),
                        "local_outcomes": {key: sum(n["outcome"] == key for n in bundle["case_graph"]["nodes"])
                                           for key in ["success", "failure", "not_executed", "unknown"]},
                        "model_calls": metrics["calls"], "cache_hits": metrics["cache_hits"]})
    cases = load_cases(inputs)
    knowledge = out / "knowledge"
    graph = json.loads((knowledge / "G_semantic.json").read_text())
    cross = validate_graph(graph, cases, graph["condition_learning"], graph["semantic_rules"])
    if len(graph["source_paths"]) != len(cases):
        raise ValueError("Source paths lost")
    for path, case in zip(graph["source_paths"], cases, strict=True):
        if path["task_outcome"] != case["graph"]["task_outcome"]:
            raise ValueError("Source task outcome changed")
    cross_metrics = json.loads((knowledge / "model_metrics.json").read_text())
    calls += cross_metrics["calls"]
    cache_hits += cross_metrics["cache_hits"]
    xml_count = 0
    for svg in out.rglob("*.svg"):
        ET.parse(svg)
        xml_count += 1
    pages = links = 0
    broken = []
    for page in out.rglob("*.html"):
        parser = Links()
        parser.feed(page.read_text(encoding="utf-8"))
        pages += 1
        for value in parser.links:
            url = urlsplit(value)
            if url.scheme or url.netloc or not url.path:
                continue
            path = Path(unquote(url.path))
            target = path if path.is_absolute() else page.parent / path
            links += 1
            if not target.exists():
                broken.append({"page": str(page), "link": value})
    if broken:
        raise ValueError("Broken local links: " + json.dumps(broken, ensure_ascii=False))
    preserved_count = 0
    if preserved:
        for row in json.loads(Path(preserved).read_text()):
            p = Path(row["path"])
            if sha(p) != row["sha256"] or str(p.resolve()) != row["resolved"]:
                raise ValueError("Existing output changed: " + row["path"])
            preserved_count += 1
    caches = 0
    for cache_dir in out.rglob("cache"):
        for record in cache_dir.glob("*.json"):
            value = json.loads(record.read_text())
            require_deployed_model(value.get("endpoint", ""), value.get("model", ""))
            if not value.get("complete") or not value.get("raw_response") or not value.get("request_fingerprint"):
                raise ValueError("Missing complete model provenance: " + str(record))
            caches += 1
    return {"passed": True, "single_videos": results, "cross_validation": cross,
            "model": manifest["model"], "endpoint": manifest["endpoint"],
            "model_calls": calls, "cache_hits": cache_hits, "complete_model_records": caches,
            "svg_xml_checked": xml_count, "html_checked": pages, "local_links_checked": links,
            "existing_artifacts_unchanged": preserved_count,
            "semantic_review_status": "model_grounded_candidate",
            "causal_status": "not_established", "robot_execution_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preserved", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = verify(args.out, args.preserved)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
