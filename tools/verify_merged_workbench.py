"""Verify deployed-model provenance, exact business fields, media and offline assets."""

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_two_track_delivery import Links

from video2op.model_contrastive_review import load_review
from video2op.model_merged_graph import load_model_graph
from video2op.skill_clips import save, sha256


def verify(root):
    root = Path(root).resolve()
    record, cases, _ = load_model_graph(root)
    review = load_review(root)
    graph = json.loads((root / "merged_operation_graph.json").read_text())
    view = json.loads((root / "merged_operation_view.json").read_text())
    errors = []
    if graph != record["response"]:
        errors.append("Canonical graph differs from the deployed-model response")
    if {
        k: v
        for k, v in view.items()
        if k
        not in {
            "nodes",
            "contrastive_examples",
            "contrastive_skill_definitions",
            "contrastive_condition_comparisons",
            "model_provenance",
        }
    } != {k: v for k, v in graph.items() if k not in {"nodes", "contrastive_examples"}}:
        errors.append("View changed a business field")
    media = set()

    def media_check(item):
        for clip in item.get("clips", []):
            path = root / clip["path"]
            media.add(str(path))
            if not path.is_file() or sha256(path) != clip["probe"]["sha256"]:
                errors.append("Missing or changed model-bounded clip: " + str(path))
            receipt = path.with_suffix(".json")
            if not receipt.is_file() or json.loads(receipt.read_text()) != clip["probe"]:
                errors.append("Clip receipt differs: " + str(path))
        if item.get("source_video") and not (root / item["source_video"]).is_file():
            errors.append("Missing source video")

    if len(view["nodes"]) != len(graph["nodes"]):
        errors.append("View node count differs")
    for raw, rendered in zip(graph["nodes"], view["nodes"], strict=True):
        if {k: v for k, v in raw.items() if k != "sources"} != {k: v for k, v in rendered.items() if k != "sources"}:
            errors.append("View changed a model-authored node")
        raw_sources = raw.get("sources", [])
        rendered_sources = rendered.get("sources", [])
        if len(raw_sources) != len(rendered_sources):
            errors.append("Source count differs")
        for source, displayed in zip(raw_sources, rendered_sources, strict=True):
            if any(displayed.get(k) != value for k, value in source.items()):
                errors.append("View changed model source timing/evidence")
            media_check(displayed)
            if not (root / displayed["model_result"]).is_file():
                errors.append("Missing source model record")
    if view["contrastive_skill_definitions"] != review["response"]["skill_definitions"]:
        errors.append("View changed model skill definitions")
    if view["contrastive_condition_comparisons"] != review["response"].get("condition_comparisons", []):
        errors.append("View changed model condition comparisons")
    if len(view["contrastive_examples"]) != len(review["response"]["examples"]):
        errors.append("Contrastive example count differs")
    for raw, displayed in zip(review["response"]["examples"], view["contrastive_examples"], strict=True):
        if any(displayed.get(k) != value for k, value in raw.items()):
            errors.append("View changed a model contrastive judgment")
        media_check(displayed)
    # Check cross-stage bookkeeping, never invent a missing failure sample.
    for d in graph["source_decisions"]:
        for s in d.get("removed_failed_segments", []):
            if not any(
                e["case_id"] == d["case_id"]
                and e["outcome"] == "failure"
                and (
                    s.get("start_sec") is None
                    or e.get("core_start_sec") is None
                    or (e["core_start_sec"] <= s["end_sec"] and e["core_end_sec"] >= s["start_sec"])
                )
                for e in review["response"]["examples"]
            ):
                errors.append("Removed failure is absent from the independent contrastive review")
    scripts = []
    links = 0
    pages = [
        root / p
        for p in [
            "workbench.html",
            "index.html",
            "跨视频分析.html",
            "learning_tracks/index.html",
            "learning_tracks/same_goal_graphs/workbench.html",
            "跨视频模型分析/workbench.html",
        ]
    ]
    for path in pages:
        parser = Links()
        parser.feed(path.read_text())
        for ref in parser.links:
            u = urlsplit(ref)
            if not u.scheme and u.path:
                if not (path.parent / unquote(u.path)).exists():
                    errors.append("Broken link: " + str(path) + " -> " + ref)
                links += 1
        scripts.extend(parser.scripts)
    for path in [
        root / p
        for p in [
            "operations.svg",
            "learning_tracks/same_goal_graphs/operations.svg",
            "跨视频模型分析/operations.svg",
        ]
    ]:
        svg = ET.parse(path).getroot()
        if {n.get("data-node-id") for n in svg.iter() if n.get("data-node-id")} != {n["id"] for n in graph["nodes"]}:
            errors.append("SVG/model node mismatch")
    js = root / "_verification/merged_workbench_scripts.js"
    js.parent.mkdir(exist_ok=True)
    js.write_text("\n".join("function block" + str(i) + "(){\n" + s + "\n}" for i, s in enumerate(scripts)))
    run = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True, timeout=30)
    if run.returncode:
        errors.append(run.stderr)
    result = {
        "passed": not errors,
        "errors": errors,
        "analysis_origin": "deployed_model",
        "model": record["model"],
        "canonical_graph_matches_model": graph == record["response"],
        "source_videos_unchanged": len(cases),
        "source_paths": len(graph["paths"]),
        "nodes": len(graph["nodes"]),
        "start_successors": [
            n["label"]
            for n in graph["nodes"]
            if n["id"] in {e["to"] for e in graph["edges"] if e["from"] == graph["start_node_id"]}
        ],
        "user_entry_policy": graph.get("entry_policy"),
        "rule_only_occurrences": len(graph.get("rule_only_occurrences", [])),
        "approach_nodes": sum(n.get("action_role") == "approach_target" for n in graph["nodes"]),
        "pregrasp_gates": sum(n.get("gate_role") == "grasp_precondition" for n in graph["nodes"]),
        "approach_source_reviews": len(graph["approach_review"]),
        "intermediate_gates": sum(n["kind"] == "gate" for n in graph["nodes"]),
        "gate_before_end": False,
        "completion_validation": False,
        "contrastive_outcomes": dict(Counter(e["outcome"] for e in review["response"]["examples"])),
        "source_clips_checked": len(media),
        "html_pages_checked": len(pages),
        "local_links_checked": links,
        "script_fragments_checked": len(scripts),
        "new_model_calls": 0,
        "browser_interaction_qa": False,
        "svg_raster_preview": str(root / "_verification/merged_model_graph.png"),
    }
    save(root / "merged_graph_verification.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    result = verify(parser.parse_args().out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(int(not result["passed"]))
