"""Build reviewable goal/effect knowledge from independent saved cases (study environment)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from video2op import semantic
from video2op.knowledge import aggregate, extract, render, video_identity
from video2op.llm import VLMClient
from video2op.pipeline import build_learning_graph
from video2op.stages import s08_scope


def load_reviewed(path: Path | None, cases: list[dict]) -> list[dict]:
    if path is None:
        return []
    from video2op.review import validate_reviewed
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("reviewed observations must be a list")
    return validate_reviewed(rows, [i for c in cases for i in c["instances"]])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按局部目的/目标效果跨视频归纳，保留对象与实现方式")
    ap.add_argument("--inputs", nargs="+", required=True, help="result.json或其所在案例目录")
    ap.add_argument("--out", type=Path, required=True, help="新的输出目录，不覆盖原案例")
    ap.add_argument("--clip-manifest", type=Path, help="关联已导出的技能切片manifest.json")
    ap.add_argument("--refresh-scope", action="store_true", help="访问已配置模型重新识别子任务范围")
    ap.add_argument("--reviewed-observations", type=Path, help="带审阅者和真实证据的条件对照样本JSON")
    ap.add_argument("--task-predictions", type=Path, help="独立任务审计观察，按视频SHA256关联")
    ap.add_argument("--observed-truth", type=Path, help="已有任务标注，仅用于显式审阅归纳")
    ap.add_argument("--allow-holdout-references", action="store_true", help="仅供all-16事后展示，不用于独立留出验收")
    args = ap.parse_args(argv)
    predictions = {}
    references = {}
    if args.task_predictions:
        predictions = {r["video_uid"]: r for r in json.loads(args.task_predictions.read_text())}
    if args.observed_truth:
        from video2op.task_observations import load_references
        references = load_references(args.observed_truth)
        if not predictions:
            raise ValueError("--observed-truth requires --task-predictions so task outcomes cannot silently replace local goals")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("输出目录已有文件，请指定新目录")
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for index, name in enumerate(args.inputs):
        source = Path(name).resolve()
        source = source / "result.json" if source.is_dir() else source
        b = json.loads(source.read_text(encoding="utf-8"))
        destination = out / "cases" / f"{index + 1:02d}_{source.parent.name}"
        destination.mkdir(parents=True)
        from video2op.media_quality import annotate, audit
        media_path = Path(b.get("meta", {}).get("path") or "")
        if media_path.is_file() and not b.get("meta", {}).get("media_quality"):
            b["meta"]["media_quality"] = audit(media_path)
        annotate(b)
        if args.refresh_scope:
            ctx = {**b, "task_nodes": b.get("task_nodes_source") or b.get("task_nodes")}
            b["semantic_scope"] = s08_scope.run(VLMClient(destination / "cache"), ctx)
        if not b.get("semantic_scope"):
            b["semantic_scope"] = {"subtasks": [], "unresolved": [
                "Saved case has no goal-scoped annotations; only explicit leaf skills can be grouped."]}
        if b.get("semantic_scope", {}).get("subtasks"):
            s08_scope.expand_evidence(b["semantic_scope"], b)
        b["source_video_sha256"], _ = video_identity(b)
        if predictions:
            from video2op.task_observations import attach
            uid = b["source_video_sha256"]
            if uid not in predictions:
                raise ValueError("task prediction missing for loaded video " + uid)
            ref = references.get(uid)
            if ref and ref.get("split") == "holdout" and not args.allow_holdout_references:
                raise ValueError("Holdout references cannot enter development induction")
            attach(b, predictions[uid], ref)
        build_learning_graph(b)
        if b.get("provided_task_contract"):
            b["semantic_graph"]["task_intent"] = b["provided_task_contract"]["statement"]
            b["semantic_graph"]["x-meta"]["provided_task_contract"] = b["provided_task_contract"]
            b["semantic_graph"]["x-meta"]["task_observation"] = b["task_observation"]
        from video2op.evidence import audit_effects
        effect_audit = audit_effects(b)
        (destination / "effect_evidence_audit.json").write_text(json.dumps(effect_audit, ensure_ascii=False, indent=2))
        b["validation"] = semantic.validate(b)
        (destination / "result.json").write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
        semantic.export(b, destination)
        semantic.render(b, destination)
        cases.append(extract(b, str(source)))
        for instance in cases[-1]["instances"]:
            instance["analysis_source"] = str(destination / "result.json")
        exported = b["semantic_graph"]["x-meta"]["final_to_export"]
        local = cases[-1]["instances"]
        task_graph = {"schema_version": "task_skill_graph.v1", "video_uid": b["source_video_sha256"],
                      "provided_task": b.get("provided_task_contract"),
                      "task_observation": b.get("task_observation"),
                      "nodes": [{"instance_id": i["instance_id"], "skill_ref": i["skill_ref"],
                                 "scope": i["instance_scope"], "atomic_refs": i["atomic_refs"],
                                 "operation_node_refs": [exported[n] for n in i["source_node_refs"] if n in exported]}
                                for i in local],
                      "contains": [{"parent": p["instance_id"], "child": c["instance_id"]}
                                   for p in local if p["instance_scope"] == "provided_task"
                                   for c in local if c["instance_scope"] != "provided_task"
                                   and set(c["atomic_refs"]) <= set(p["atomic_refs"])]}
        (destination / "task_skill_graph.json").write_text(json.dumps(task_graph, ensure_ascii=False, indent=2))
        print(f"{source.parent.name}: {len(cases[-1]['instances'])}个技能/子任务实例；{b['validation']['summary']}", flush=True)
    reviewed = load_reviewed(args.reviewed_observations, cases)
    knowledge = aggregate(cases, reviewed)
    (out / "knowledge.json").write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    from video2op.cross_video_delivery import export as export_cross_video
    export_cross_video(knowledge, out, args.clip_manifest)
    artifacts = {"skill_tuples": json.loads((out / "skill_tuples.json").read_text())}
    page = render(knowledge)
    import html
    page = page.replace("</html>", "<section><h2>跨视频 Skill Tuple 七元组</h2><pre>" +
                        html.escape(json.dumps(artifacts["skill_tuples"], ensure_ascii=False, indent=2)) +
                        "</pre></section></html>")
    (out / "review.html").write_text(page, encoding="utf-8")
    print(f"视频{len(knowledge['sources'])}；语义技能{len(knowledge['skills'])}；"
          f"对象任务族{len(knowledge['task_families'])}；实例{len(knowledge['instances'])}", flush=True)
    return 0 if knowledge["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
