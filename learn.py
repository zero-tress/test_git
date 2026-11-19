"""Build reviewable goal/effect knowledge from independent saved cases (study environment)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video2op import semantic
from video2op.knowledge import aggregate, extract, render, video_identity
from video2op.llm import VLMClient
from video2op.single_video.pipeline import build_learning_graph
from video2op.single_video.stages import s08_scope


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
    ap.add_argument(
        "--goal",
        choices=__import__("video2op.goal_semantics", fromlist=["GOALS"]).GOALS,
        help="User-provided common task goal; does not prove success",
    )
    ap.add_argument("--target-category", help="Common goal target category, e.g. pen")
    ap.add_argument("--local-reviews", type=Path, help="8032 review records; invalid opinions remain quarantined")
    ap.add_argument("--no-clips", action="store_true", help="保存时间索引但不导出各案例MP4")
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
            raise ValueError(
                "--observed-truth requires --task-predictions so task outcomes cannot silently replace local goals"
            )
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("输出目录已有文件，请指定新目录")
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    track_inputs = []
    case_destinations = []
    review_records = {}
    if args.local_reviews:
        review_records = {r["video_uid"]: r for r in json.loads(args.local_reviews.read_text())["records"]}
    for index, name in enumerate(args.inputs):
        source = Path(name).resolve()
        source = source / "result.json" if source.is_dir() else source
        b = json.loads(source.read_text(encoding="utf-8"))
        destination = out / "cases" / f"{index + 1:02d}_{source.parent.name}"
        destination.mkdir(parents=True)
        case_destinations.append(destination)
        from video2op.media_quality import annotate, audit

        media_path = Path(b.get("meta", {}).get("path") or "")
        if media_path.is_file() and not b.get("meta", {}).get("media_quality"):
            b["meta"]["media_quality"] = audit(media_path)
        annotate(b)
        if args.refresh_scope:
            ctx = {**b, "task_nodes": b.get("task_nodes_source") or b.get("task_nodes")}
            b["semantic_scope"] = s08_scope.run(VLMClient(destination / "cache"), ctx)
        if not b.get("semantic_scope"):
            b["semantic_scope"] = {
                "subtasks": [],
                "unresolved": [
                    "Saved case has no goal-scoped annotations; only explicit leaf skills can be grouped."
                ],
            }
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
        if args.goal:
            b["learning_goal"] = {
                "goal_key": args.goal,
                "target_category": args.target_category,
                "origin": "user_provided_goal",
                "observed_success": False,
            }
        build_learning_graph(b)
        if b.get("provided_task_contract"):
            b["semantic_graph"]["task_intent"] = b["provided_task_contract"]["statement"]
            b["semantic_graph"]["x-meta"]["provided_task_contract"] = b["provided_task_contract"]
            b["semantic_graph"]["x-meta"]["task_observation"] = b["task_observation"]
        from video2op.evidence import audit_effects

        effect_audit = audit_effects(b)
        (destination / "effect_evidence_audit.json").write_text(
            json.dumps(effect_audit, ensure_ascii=False, indent=2)
        )
        b["validation"] = semantic.validate(b)
        (destination / "result.json").write_text(json.dumps(b, ensure_ascii=False, indent=2), encoding="utf-8")
        semantic.export(b, destination, export_clips=not args.no_clips, cache_dir=out / "_clip_cache")
        semantic.render(b, destination)
        cases.append(extract(b, str(source)))
        for instance in cases[-1]["instances"]:
            instance["analysis_source"] = str(destination / "result.json")
        from video2op.learning_tracks import split

        learning_case = cases[-1]
        if b["source_video_sha256"] in review_records:
            from video2op.contrastive_learning import enrich

            learning_case, _ = enrich(review_records[b["source_video_sha256"]])
            learning_case["source"] = str(destination / "result.json")
            for u in learning_case["instances"]:
                u["original_analysis_source"] = u.get("analysis_source", u["source"])
                u["analysis_source"] = str(destination / "result.json")
        track_inputs.append(split(b, str(destination / "result.json"), learning_case, b.get("learning_goal")))
        from video2op.single_video.case_outputs import attach_classified_clips
        from video2op.skill_clips import save

        final_tracks = track_inputs[-1]
        save(
            destination / "task_learning_units.json",
            {"schema_version": "purpose_tasks.v1", "instances": final_tracks["purpose_case"]["instances"]},
        )
        save(
            destination / "clip_classification.json",
            {"schema_version": "clip_classification.v1", "instances": final_tracks["classification"]},
        )
        save(destination / "task_causal_audit.json", final_tracks["task_causal_audit"])
        attach_classified_clips(destination)
        save(
            destination / "learning_review.json",
            {
                "unit_quarantine": learning_case.get("review_quarantine", []),
                "causal_model_review": learning_case.get("causal_model_review", {}),
                "human_verified": False,
            },
        )
        exported = b["semantic_graph"]["x-meta"]["final_to_export"]
        local = final_tracks["purpose_case"]["instances"] + final_tracks["clip_case"]["instances"]
        task_graph = {
            "schema_version": "task_skill_graph.v1",
            "video_uid": b["source_video_sha256"],
            "provided_task": b.get("learning_goal") or b.get("provided_task_contract"),
            "task_observation": b.get("task_observation"),
            "nodes": [
                {
                    "instance_id": i["instance_id"],
                    "skill_ref": i["skill_ref"],
                    "scope": i["instance_scope"],
                    "atomic_refs": i["atomic_refs"],
                    "operation_node_refs": [exported[n] for n in i["source_node_refs"] if n in exported],
                }
                for i in local
            ],
            "contains": [
                {"parent": p["instance_id"], "child": c["instance_id"]}
                for p in local
                if p["instance_scope"] == "purpose_task"
                for c in local
                if c["instance_scope"] != "purpose_task" and set(c["atomic_refs"]) <= set(p["atomic_refs"])
            ],
        }
        (destination / "task_skill_graph.json").write_text(json.dumps(task_graph, ensure_ascii=False, indent=2))
        print(
            f"{source.parent.name}: {len(cases[-1]['instances'])}个技能/子任务实例；{b['validation']['summary']}",
            flush=True,
        )
    reviewed = load_reviewed(args.reviewed_observations, cases)
    from video2op.learning_tracks import apply_reviewed

    apply_reviewed(track_inputs, reviewed)
    if reviewed:
        for t, destination in zip(track_inputs, case_destinations, strict=True):
            save(
                destination / "task_learning_units.json",
                {"schema_version": "purpose_tasks.v1", "instances": t["purpose_case"]["instances"]},
            )
            save(
                destination / "clip_classification.json",
                {"schema_version": "clip_classification.v1", "instances": t["classification"]},
            )
            episodes = json.loads((destination / "skill_episodes.json").read_text())
            episodes["episodes"] = [u for u in t["clip_case"]["instances"] if u["instance_scope"] == "skill_episode"]
            save(destination / "skill_episodes.json", episodes)
            attach_classified_clips(destination)

    knowledge = aggregate(cases, reviewed)
    (out / "knowledge.json").write_text(json.dumps(knowledge, ensure_ascii=False, indent=2), encoding="utf-8")
    from video2op.cross_video_delivery import export as export_cross_video

    export_cross_video(knowledge, out, args.clip_manifest)
    artifacts = {"skill_tuples": json.loads((out / "skill_tuples.json").read_text())}
    page = render(knowledge)
    import html

    page = page.replace(
        "</html>",
        "<section><h2>跨视频 Skill Tuple 七元组</h2><pre>"
        + html.escape(json.dumps(artifacts["skill_tuples"], ensure_ascii=False, indent=2))
        + "</pre></section></html>",
    )
    (out / "review.html").write_text(page, encoding="utf-8")
    print(
        f"视频{len(knowledge['sources'])}；语义技能{len(knowledge['skills'])}；"
        f"对象任务族{len(knowledge['task_families'])}；实例{len(knowledge['instances'])}",
        flush=True,
    )
    from video2op.two_track_delivery import export as export_tracks

    result = export_tracks(track_inputs, out / "learning_tracks", export_clips=not args.no_clips)
    (out / "index.html").write_text(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>视频学习交付</title><body><h1>视频学习交付</h1><p><a href='learning_tracks/index.html'>同目标任务图归纳与同类技能切片正反例学习</a></p></body></html>"
    )
    print("两条学习流程：" + str(out / "learning_tracks/index.html"), flush=True)
    return 0 if knowledge["validation"]["passed"] and not result["unresolved_user_goals"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
