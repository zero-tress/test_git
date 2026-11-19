"""Render model-authored graphs. No video interpretation, action taxonomy, tuple or gate inference."""

from __future__ import annotations

import hashlib
import json
import os
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

from .single_video.case_outputs import safe_name
from .model_contrastive_review import analyze as analyze_contrastive
from .model_contrastive_review import load_review
from .model_merged_graph import analyze, load_model_graph
from .skill_clips import cut, save, sha256

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


def _media(root, source_row, start, end, label, key):
    if start is None or end is None or end - start < 0.04:
        return []
    source = Path(source_row["source"])
    identity = hashlib.sha256(json.dumps([source_row["sha256"], start, end], sort_keys=True).encode()).hexdigest()[
        :16
    ]
    folder = root / "model_graph_media"
    target = folder / (safe_name(source.stem) + "_" + safe_name(label) + "_" + identity + ".mp4")
    receipt = target.with_suffix(".json")
    if receipt.exists():
        probe = json.loads(receipt.read_text())
        if not target.exists() or sha256(target) != probe["sha256"]:
            raise ValueError("Previously exported media changed")
    else:
        if target.exists():
            raise FileExistsError("Media exists without its export receipt: " + str(target))
        probe = cut(source, target, start, end)
        save(receipt, probe)
    return [
        {
            "action": label,
            "start": start,
            "end": end,
            "path": os.path.relpath(target, root),
            "probe": probe,
            "source_timing_origin": "deployed_model",
            "example_or_node_id": key,
        }
    ]


def _sources(root, rows, cases, label, key):
    result = []
    for row in rows:
        item = deepcopy(row)
        case = cases[row["case_id"]]
        item.update(
            name=case["name"],
            source_video=os.path.relpath(case["source"], root),
            model_result="success_process_model/result.json",
        )
        item["clips"] = _media(root, case, row.get("start_sec"), row.get("end_sec"), label, key)
        result.append(item)
    return result


def _svg(graph, root):
    from .cross_video_render import svg

    return svg(graph)


def export(root):
    root = Path(root).resolve()
    record, cases, _evidence = load_model_graph(root)
    review = load_review(root)
    business = deepcopy(record["response"])
    view = deepcopy(business)
    for node in view["nodes"]:
        node["sources"] = _sources(root, node.get("sources", []), cases, node["label"], node["id"])
    examples = []
    for example in review["response"]["examples"]:
        item = deepcopy(example)
        cid = example["case_id"]
        item["source_video"] = os.path.relpath(cases[cid]["source"], root)
        item["clips"] = _media(
            root,
            cases[cid],
            example.get("context_start_sec"),
            example.get("context_end_sec"),
            example["skill_id"],
            example["id"],
        )
        examples.append(item)
    view["contrastive_examples"] = examples
    view["contrastive_skill_definitions"] = deepcopy(review["response"]["skill_definitions"])
    view["contrastive_condition_comparisons"] = deepcopy(review["response"].get("condition_comparisons", []))
    view["model_provenance"] = {
        "analysis_origin": record["analysis_origin"],
        "model": record["model"],
        "record": "success_process_model/result.json",
        "input_fingerprint": record["input_fingerprint"],
        "business_fields": "Graph nodes/edges/tuples/gates are unchanged model output. Contrastive examples come from a separate deployed-model review. Host adds URLs/layout only.",
        "contrastive_record": "contrastive_process_model/result.json",
        "contrastive_model": review["model"],
    }
    save(root / "merged_operation_graph.json", business)
    save(root / "merged_operation_view.json", view)
    save(
        root / "success_source_selection.json",
        {
            "source_decisions": business["source_decisions"],
            "simplifications": business["simplifications"],
            "analysis_origin": "deployed_model",
            "model_record": "success_process_model/result.json",
        },
    )
    save(
        root / "model_contrastive_examples.json",
        {
            "examples": examples,
            "skill_definitions": review["response"]["skill_definitions"],
            "condition_comparisons": review["response"].get("condition_comparisons", []),
            "analysis_origin": "deployed_model",
            "model_record": "contrastive_process_model/result.json",
        },
    )
    drawing = _svg(business, root)
    (root / "operations.svg").write_text(drawing)
    from .cross_video_workbench import render

    (root / "workbench.html").write_text(render(view, drawing))
    for folder, relative in [(root / "learning_tracks/same_goal_graphs", "../.."), (root / "跨视频模型分析", "..")]:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "operations.svg").write_text(drawing)
        (folder / "workbench.html").write_text(
            '<!doctype html><meta charset="utf-8"><title>成功流程操作图</title><a href="'
            + relative
            + '/workbench.html">打开模型生成的成功流程图</a><script>location.replace("'
            + relative
            + '/workbench.html"+location.hash)</script>'
        )
    for page, url in [
        (root / "index.html", "workbench.html"),
        (root / "跨视频分析.html", "workbench.html"),
        (root / "learning_tracks/index.html", "../workbench.html"),
    ]:
        if not page.exists():
            continue
        text = page.read_text()
        panel = (
            '<section id="model-success-graph-entry"><p><strong><a href="'
            + url
            + '">模型生成：成功流程合并图与正反例</a></strong> · <a href="'
            + url.replace("workbench.html", "operations.svg")
            + '">SVG</a></p><p>只归纳成功行为，失败片段单独保留为正反例。结束前无门控。</p></section>'
        )
        if 'id="model-success-graph-entry"' not in text:
            text = (
                text.replace("</body>", panel + "</body>")
                if "</body>" in text
                else text.replace("</html>", panel + "</html>")
            )
        page.write_text(text)
    summary = json.loads((root / "summary.json").read_text())
    summary["merged_operation_visualization"] = {
        "svg": "operations.svg",
        "workbench": "workbench.html",
        "graph": "merged_operation_graph.json",
        "view": "merged_operation_view.json",
        "analysis_origin": "deployed_model",
        "model": record["model"],
        "model_record": "success_process_model/result.json",
        "source_paths": len(business["paths"]),
        "gate_before_end": False,
        "completion_validation": False,
        "success_only": True,
        "failures_in_separate_pool": True,
    }
    save(root / "summary.json", summary)
    return {
        "svg": str(root / "operations.svg"),
        "workbench": str(root / "workbench.html"),
        "analysis_origin": "deployed_model",
        "model": record["model"],
        "source_paths": len(business["paths"]),
        "nodes": len(business["nodes"]),
        "gates": sum(n["kind"] == "gate" for n in business["nodes"]),
        "contrastive_examples": len(examples),
        "end_gate": False,
    }


def analyze_then_export(root, *, allow_model_service=False, force=False):
    analyze(root, allow_model_service=allow_model_service, force=force)
    analyze_contrastive(root, allow_model_service=allow_model_service, force=force)
    return export(root)
