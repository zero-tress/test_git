"""Re-export saved analyses into a new layout; retain all historical artifacts."""
import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import semantic
from video2op.case_outputs import export_case_clips
from video2op.cross_video_delivery import export as export_cross
from video2op.cross_video_delivery import refine
from video2op.generalized_holdout import explain
from video2op.skill_clips import save, sha256
from video2op.skill_library import LIBRARY

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=ROOT/"output/current")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    old = args.source.resolve()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        ap.error("请选择新的空输出目录")
    out.mkdir(parents=True)
    hashes = {str(p): sha256(p) for p in old.rglob("*") if p.is_file()}
    fixture = (ROOT/"output/抓取2_semantic_v3").resolve()
    hashes.update({str(p): sha256(p) for p in fixture.rglob("*") if p.is_file()})
    save(out/"source_hashes.json", hashes)
    save(out/"previous_aliases.json", {str(p): str(p.readlink()) for p in [ROOT/"output/current", ROOT/"output/抓取2_semantic_v3"] if p.is_symlink()})
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="microseconds")
    groups = ["knowledge_development", "knowledge_all_16", "holdout_observations"]
    results, summaries, learnt = [], {}, {}
    for group in groups:
        source = old/group
        knowledge = json.loads((source/"knowledge.json").read_text())
        by_uid = {}
        for p in sorted((source/"cases").glob("*/result.json")):
            b = json.loads(p.read_text())
            b["meta"]["analysis_time"] = stamp
            b["layout_migration"] = {"source_analysis": str(p), "mode": "reexport_saved_observations_no_new_model_call"}
            destination = out/group/"cases"/p.parent.name
            semantic.export(b, destination, cache_dir=out/"_clip_cache")
            clip = export_case_clips(b, destination, cache_dir=out/"_clip_cache")
            semantic.render(b, destination)
            if clip["status"] != "complete":
                raise ValueError("Clip export incomplete: "+str(destination))
            by_uid[b["source_video_sha256"]] = str(destination/"result.json")
            results.append({"group": group, "case": str(destination), "clips": clip["exported"]})
            print(group+"/"+p.parent.name, clip["exported"], flush=True)
        for i in knowledge["instances"]:
            i["analysis_source"] = by_uid[i["video_uid"]]
        for source_row in knowledge["sources"]:
            source_row["source_files"] = [by_uid[source_row["video_uid"]]]
        knowledge = refine(knowledge)
        save(out/group/"knowledge.json", knowledge)
        summaries[group] = export_cross(knowledge, out/group)
        # Use local case evidence, not the former cross-video clip directory.
        evidence = json.loads((out/group/"evidence_index.json").read_text())
        for row in evidence:
            row["case_clip_manifest"] = str(Path(row["analysis_source"]).parent/"clip/sequence.json")
        save(out/group/"evidence_index.json", evidence)
        learnt[group] = knowledge
    b = json.loads((fixture/"result.json").read_text())
    b["meta"]["analysis_time"] = stamp
    b["layout_migration"] = {"source_analysis": str(fixture/"result.json"), "mode": "reexport_saved_observations_no_new_model_call"}
    destination = out/"抓取2_semantic_v3"
    semantic.export(b, destination, cache_dir=out/"_clip_cache")
    clip = export_case_clips(b, destination, cache_dir=out/"_clip_cache")
    semantic.render(b, destination)
    if clip["status"] != "complete":
        raise ValueError("Grasp2 clip export incomplete")
    results.append({"group": "fixture", "case": str(destination), "clips": clip["exported"]})
    frozen = sha256(out/"knowledge_development/knowledge.json")
    held = explain(learnt["knowledge_development"], learnt["holdout_observations"])
    save(out/"holdout_evaluation.json", held)
    if sha256(out/"knowledge_development/knowledge.json") != frozen:
        raise ValueError("Holdout evaluation modified development")
    changed = [p for p,v in hashes.items() if sha256(p) != v]
    if changed:
        raise ValueError("Historical source changed: "+repr(changed))
    # Publish the developer split alone as the unified learned outline.
    catalog = json.loads((out/"knowledge_development/skill_catalog.json").read_text())
    eval_manifest = json.loads((ROOT/"eval/manifest.json").read_text())
    allowed = {r["sha256"] for r in eval_manifest["media"] if r.get("split") == "development"}
    if not set(catalog["source_video_uids"]) <= allowed:
        raise ValueError("Holdout may not enter the published skill outline")
    version = sha256(out/"knowledge_development/skill_catalog.json")[:20]
    save(LIBRARY/"learned_versions"/(version+".json"), catalog)
    save(LIBRARY/"learned_skill_catalog.json", catalog)
    save(LIBRARY/"index.json", {"schema_version": "skill_library_index.v1",
         "action_catalog": "action_catalog.json", "declared_templates": "skill_templates.json",
         "learned_catalog": "learned_skill_catalog.json", "learned_version": version,
         "source_split": "development", "learning_source": str(out/"knowledge_development")})
    save(out/"layout_summary.json", {"analysis_time": stamp, "cases": results, "learning": summaries,
                                     "historical_files_unchanged": len(hashes),
                                     "published_catalog_version": version,
                                     "frozen_development_sha256": frozen})
    links = [f'<li><a href="{g}/cross_video_review.html">{html.escape(g)}</a></li>' for g in groups]
    links.extend(f'<li><a href="{Path(r["case"]).relative_to(out).as_posix()}/workbench.html">{html.escape(Path(r["case"]).name)} · {html.escape(r["group"])}</a></li>' for r in results)
    (out/"index.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>单视频切片与统一技能库</title><body style="font:18px system-ui;max-width:1100px;margin:32px auto"><h1>单视频切片与统一技能库</h1><p>单视频保存实例和片段；项目技能大纲统一定义，开发集归纳结果统一发布；留出与事后展示分别保存。</p><ul>'+"\n".join(links)+'</ul></body></html>')
    print(json.dumps({"out": str(out), "cases": len(results), "clip_entries": sum(r["clips"] for r in results),
                      "unique_clip_files": len(list((out/"_clip_cache").glob("*.mp4")))},ensure_ascii=False),flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
