"""Reprocess frozen saved cases and clips; no model, network, shared KB or DB writes."""
import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op.cross_video_delivery import export, refine, save
from video2op.generalized_holdout import explain
from video2op.skill_clips import sha256

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=ROOT/"output/current")
    ap.add_argument("--clips", type=Path, required=True, help="已完成导出的技能切片manifest.json")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        ap.error("请选择新的空输出目录")
    source = args.source.resolve()
    clips = json.loads(args.clips.read_text())
    if not clips.get("complete"):
        ap.error("切片尚未完整导出")
    initial = {name: json.loads((source/name/"knowledge.json").read_text())
               for name in ["knowledge_development", "knowledge_all_16", "holdout_observations"]}
    dev_uids = {s["video_uid"] for s in initial["knowledge_development"]["sources"]}
    held_uids = {s["video_uid"] for s in initial["holdout_observations"]["sources"]}
    if dev_uids & held_uids:
        raise ValueError("Development and holdout overlap")
    clip_splits = {v["source_sha256"]: v["split"] for v in clips["videos"]}
    if any(clip_splits.get(uid) != "development" for uid in dev_uids):
        raise ValueError("Clip split does not match development")
    if any(clip_splits.get(uid) != "holdout" for uid in held_uids):
        raise ValueError("Clip split does not match holdout")
    out.mkdir(parents=True)
    baseline = {}
    for p in source.rglob("*"):
        if p.is_file():
            baseline[str(p)] = sha256(p)
    save(out/"source_hashes.json", baseline)
    summaries, learned = {}, {}
    for name, saved in initial.items():
        knowledge = refine(saved)
        destination = out/name
        save(destination/"knowledge.json", knowledge)
        summaries[name] = export(knowledge, destination, args.clips)
        learned[name] = knowledge
        print(name, json.dumps(summaries[name], ensure_ascii=False), flush=True)
    frozen = sha256(out/"knowledge_development/knowledge.json")
    held = explain(learned["knowledge_development"], learned["holdout_observations"])
    if frozen != sha256(out/"knowledge_development/knowledge.json"):
        raise ValueError("Evaluation modified frozen development knowledge")
    save(out/"holdout_evaluation.json", held)
    missing = {
        "unverified_claims": ["Branch choice guards and R applicability require proposition-level review.",
                              "Literal state matching is conservative and can split semantic synonyms.",
                              "Current reference annotations do not certify all local action effects.",
                              "Historical holdout is not a newly independent generalization experiment."],
        "missing_video_contrasts": ["Direct grasp versus grasp after explicit obstacle clearance is not established by existing labels.",
                                   "Bypass and waiting are definitions/examples only until actual videos support membership."],
        "external_interfaces": {"execution_causal_store": "ownership_and_schema_pending",
                                "robot_policy_and_behavior_tree_binding": "unbound"},
        "causality": "not_established"}
    save(out/"evidence_gaps.json", missing)
    ledger = [
        {"id": "T0", "task": "技能与目标定义", "mechanism": "implemented", "empirical": "declared_contracts_not_discovered_skills"},
        {"id": "T1", "task": "技能与动作切片", "mechanism": "implemented_decode_checked", "empirical": "boundaries_and_labels_need_review"},
        {"id": "T2", "task": "全实例支路合并与重建", "mechanism": "implemented", "empirical": "source_preservation_verified_semantic_alignment_candidate"},
        {"id": "T3", "task": "功能合并与R引用", "mechanism": "implemented", "empirical": "shared_goal_contracts_effect_entailment_pending"},
        {"id": "T4", "task": "条件与效果证据", "mechanism": "implemented_evidence_separation", "empirical": "partial_needs_controlled_contrasts_and_review"},
        {"id": "T5", "task": "冻结留出与回归", "mechanism": "implemented", "empirical": "historical_regression_only"},
        {"id": "T6", "task": "可追溯交付与账本", "mechanism": "implemented", "empirical": "unknowns_preserved"},
    ]
    save(out/"acceptance_ledger.json", ledger)
    changed = [path for path, before in baseline.items() if sha256(path) != before]
    if changed:
        raise ValueError("Existing delivery changed: " + repr(changed))
    current = subprocess.run(["git", "rev-parse", "HEAD"], text=True, capture_output=True, check=True).stdout.strip()
    result = {"summaries": summaries, "clips": clips["summary"],
              "clip_manifest": str(args.clips.resolve()), "frozen_development_sha256": frozen,
              "historical_holdout_decisions": dict(Counter(r["decision"] for r in held)),
              "source_files_unchanged": len(baseline), "source_commit_before_changes": current,
              "network_used": False, "gpu_used": False, "robot_execution_verified": False}
    save(out/"verification_summary.json", result)
    links = "\n".join(f'<li><a href="{name}/cross_video_review.html">{label}</a></li>' for name,label in [
        ("knowledge_development", "13段开发集：支路与功能合并"),
        ("knowledge_all_16", "全16段：事后展示，含参考标注"),
        ("holdout_observations", "3段留出：独立保存的模型观察")])
    import html
    import os
    clip_link = os.path.relpath(args.clips.resolve().parent/"index.html", out)
    (out/"index.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>跨视频归纳交付</title><body style="font:18px system-ui;max-width:1000px;margin:40px auto"><h1>跨视频归纳交付</h1><p>切片、路径保留、语义与因果证据分别验收。当前仍有待审阅命题。</p><ul>'+links+f'<li><a href="{html.escape(clip_link, quote=True)}">技能与动作视频切片</a></li></ul><pre style="white-space:pre-wrap">'+html.escape(json.dumps(result, ensure_ascii=False, indent=2))+'</pre></body></html>')
    (out/"实施结果.md").write_text("# 跨视频归纳实施结果\n\n"
        +f"已导出{clips['summary']['clip_files']}个视频片段，来源{clips['summary']['videos']}段视频。\n\n"
        +"开发、留出、全16段展示分别处理；当前稳定交付和共享版本库未改写。\n\n"
        +"~~~json\n"+json.dumps(result, ensure_ascii=False, indent=2)+"\n~~~\n\n"
        +"语义边界、分支适用条件、局部效果与因果条件仍需逐命题审阅和真实对照材料；详见evidence_gaps.json及acceptance_ledger.json。\n")
    print("DELIVERY", str(out), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
