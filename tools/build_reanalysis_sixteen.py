"""Build separate development, blind holdout and all-16 views from this run's fresh outputs."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import semantic
from video2op.case_outputs import attach_classified_clips
from video2op.contrastive_learning import enrich
from video2op.cross_video_delivery import export as export_legacy
from video2op.generalized_holdout import explain
from video2op.knowledge import aggregate, render
from video2op.learning_tracks import split
from video2op.pipeline import build_learning_graph
from video2op.skill_clips import save, sha256
from video2op.task_observations import reference_from_annotation
from video2op.two_track_delivery import export

ROOT = Path(__file__).resolve().parents[1]


def dense_process_evidence(b, row, run, folder):
    """Use temporally denser process evidence, preserving the initial prediction."""
    source = run / "process_review" / (row["id"] + "_dense") / "result.json"
    if not source.exists():
        return None
    data = json.loads(source.read_text())
    if data.get("status") != "completed":
        return None
    response = data["response"]
    prior = b["task_observation"]["drop"]
    b["task_observation"]["initial_task_audit_drop"] = prior
    b["task_observation"]["drop"] = response["drop"]
    b["task_observation"]["drop_review"] = {
        "source": str(source),
        "initial_prediction": prior,
        "selected_prediction": response["drop"],
        "selection_basis": "higher_temporal_resolution_process_window",
        "provenance": "additional_model_review_candidate",
        "human_verified": False,
    }
    for ev in b["task_observation"]["evidence"]:
        ev["superseded_fields"] = ["drop"]
    b["task_observation"]["evidence"].append(
        {
            "source": str(source),
            "video_uid": row["sha256"],
            "field": "drop",
            "quote": deepcopy(response),
            "provenance": "dense_model_process_review",
            "verification_status": "unverified",
        }
    )
    b["process_review"] = {"source": str(source), "response": deepcopy(response), "human_verified": False}
    frames = {f["frame_id"]: f for f in data["frames"]}
    relevant = [e for e in response["events"] if any(w in e["kind"] for w in ["分离", "落", "支撑"])]
    times = [frames[f]["timestamp"] for e in relevant for f in e["evidence_frames"]]
    if times:
        from video2op.case_outputs import analysis_stamp, safe_name
        from video2op.skill_clips import cut

        start = max(0, min(times) - 0.2)
        end = min(b["meta"]["duration"], max(times) + 0.2)
        directory = folder / "clip/process_review"
        directory.mkdir(parents=True, exist_ok=True)
        name = f"{safe_name(Path(row['source']).stem)}_手物分离与下落_001_{analysis_stamp(b)}.mp4"
        target = directory / name
        meta = directory / "sequence.json"
        if meta.exists():
            previous = json.loads(meta.read_text())
            if sha256(target) != previous["clip"]["probe"]["sha256"]:
                raise ValueError("Existing process evidence bytes changed")
            clip = previous["clip"]
        else:
            probe = cut(row["source"], target, start, end)
            clip = {
                "path": "clip/process_review/" + name,
                "source_start_sec": start,
                "source_end_sec": end,
                "probe": probe,
            }
            save(
                meta,
                {
                    "clip": clip,
                    "source_video_sha256": row["sha256"],
                    "policy": "Process evidence view, not an additional trial or fabricated action.",
                },
            )
        b["process_review"]["clip"] = clip
    save(folder / "process_review.json", b["process_review"])
    return b["process_review"]


def dense_execution_evidence(b, row, run, folder):
    source = run / "process_review" / (row["id"] + "_execution_dense") / "result.json"
    if not source.exists():
        return None
    data = json.loads(source.read_text())
    if data.get("status") != "completed":
        return None
    from video2op.task_observations import execution_outcome

    response = data["response"]
    obs = b["task_observation"]
    obs["initial_task_audit_attempted"] = obs["attempted"]
    visible = response["target_displaced"]
    caused = response["hand_caused_target_motion"]
    selected = "T" if visible == "T" and caused == "T" else "F" if visible == "F" else "U"
    obs["attempted"] = selected
    obs["outcome"] = execution_outcome(selected, obs["goal_satisfied_final"])
    if selected == "T":
        obs["method"] = response["movement_method"]
    elif selected == "F":
        obs["method"] = "None"
    obs["execution_review"] = {
        "source": str(source),
        "response": deepcopy(response),
        "selection_basis": "dense_continuous_target_motion_relative_to_background",
        "provenance": "additional_model_review_candidate",
        "human_verified": False,
    }
    for ev in obs["evidence"]:
        ev.setdefault("superseded_fields", []).extend(["attempted", "method"])
    obs["evidence"].append(
        {
            "source": str(source),
            "video_uid": row["sha256"],
            "field": "execution",
            "quote": deepcopy(response),
            "provenance": "dense_model_execution_review",
            "verification_status": "unverified",
        }
    )
    b["execution_review"] = deepcopy(obs["execution_review"])
    save(folder / "execution_review.json", b["execution_review"])
    return b["execution_review"]


def prepare_case(row, status, out):
    source = Path(status["result"])
    b = json.loads(source.read_text())
    if b["task_observation"]["provenance"] != "model_task_audit":
        raise ValueError("Only this run's model observations may enter learning")
    if b["source_video_sha256"] != row["sha256"] or sha256(row["source"]) != row["sha256"]:
        raise ValueError("Source identity mismatch")
    folder = out / "cases" / source.parent.name
    b["raw_model_analysis_source"] = str(source)
    b["meta"]["neutral_analysis_name"] = b["meta"]["name"]
    b["meta"]["name"] = Path(row["source"]).stem
    b["meta"]["path"] = row["source"]
    b["dataset_split"] = row["split"]
    process = dense_process_evidence(b, row, source.parents[2], folder)
    dense_execution_evidence(b, row, source.parents[2], folder)
    build_learning_graph(b)
    b["semantic_graph"]["task_intent"] = b["provided_task_contract"]["statement"]
    b["semantic_graph"]["x-meta"]["provided_task_contract"] = b["provided_task_contract"]
    b["semantic_graph"]["x-meta"]["task_observation"] = b["task_observation"]
    b["validation"] = semantic.validate(b)
    semantic.export(b, folder, export_clips=True, cache_dir=out / "_case_clip_cache")
    semantic.render(b, folder)
    record = json.loads((source.parents[2] / "local_reviews_v2" / row["id"] / "results.json").read_text())["records"][
        0
    ]
    case, _ = enrich(record)
    case["source"] = str(folder / "result.json")
    case["case_validation"] = b["validation"]
    case["task_observation"] = deepcopy(b["task_observation"])
    from video2op.knowledge import extract

    audited_task = [
        u for u in extract(b, str(folder / "result.json"))["instances"] if u["instance_scope"] == "provided_task"
    ]
    indexed = {u["instance_id"]: u for u in case["instances"]}
    for task in audited_task:
        current = indexed.get(task["instance_id"])
        if current:
            current["task_audit_alignment"] = {
                "local_review_outcome": current["outcome"],
                "selected_task_outcome": task["outcome"],
                "policy": "Independent fixed-goal task audit supplies the whole-task result; local skill outcomes remain independent.",
            }
            current.update(
                outcome=task["outcome"],
                outcome_status="model_grounded_candidate",
                outcome_evidence=deepcopy(task["outcome_evidence"]),
            )
            for observation in current.get("condition_observations", []):
                observation.update(outcome=task["outcome"], outcome_evidence=deepcopy(task["outcome_evidence"]))
        else:
            task["task_audit_alignment"] = {
                "selected_task_outcome": task["outcome"],
                "policy": "Whole-task trial supported by fresh task audit; no human reference label used.",
            }
            case["instances"].append(task)

    if process:
        for unit in case["instances"]:
            unit["process_review"] = deepcopy(process)
    for unit in case["instances"]:
        unit["analysis_source"] = str(folder / "result.json")
    tracks = split(b, str(folder / "result.json"), case)
    if process:
        tracks["task_causal_audit"]["additional_process_review"] = deepcopy(process)
    save(
        folder / "task_learning_units.json",
        {"schema_version": "purpose_tasks.v1", "instances": tracks["purpose_case"]["instances"]},
    )
    save(
        folder / "clip_classification.json",
        {"schema_version": "clip_classification.v1", "instances": tracks["classification"]},
    )
    save(folder / "task_causal_audit.json", tracks["task_causal_audit"])
    episodes = json.loads((folder / "skill_episodes.json").read_text())
    episodes["episodes"] = [u for u in tracks["clip_case"]["instances"] if u["instance_scope"] == "skill_episode"]
    save(folder / "skill_episodes.json", episodes)
    attach_classified_clips(folder)
    save(
        folder / "learning_review.json",
        {
            "unit_quarantine": case["review_quarantine"],
            "causal_model_review": case["causal_model_review"],
            "human_verified": False,
        },
    )
    export_map = b["semantic_graph"]["x-meta"]["final_to_export"]
    units = tracks["purpose_case"]["instances"] + tracks["clip_case"]["instances"]
    save(
        folder / "task_skill_graph.json",
        {
            "schema_version": "task_skill_graph.v2",
            "video_uid": row["sha256"],
            "provided_task": b["provided_task_contract"],
            "nodes": [
                {
                    "instance_id": u["instance_id"],
                    "skill_ref": u["skill_ref"],
                    "scope": u["instance_scope"],
                    "learning_track": u["learning_track"],
                    "atomic_refs": u["atomic_refs"],
                    "operation_node_refs": [export_map[n] for n in u["source_node_refs"] if n in export_map],
                }
                for u in units
            ],
            "contains": [
                {"parent": p["instance_id"], "child": c["instance_id"]}
                for p in tracks["purpose_case"]["instances"]
                for c in tracks["clip_case"]["instances"]
                if p["instance_id"] in c.get("parent_task_refs", [])
            ],
        },
    )
    if process:
        import html
        from urllib.parse import quote

        panel = "<section><h2>过程加密复核（模型候选）</h2><p>最终目标判定与过程异常分别保存。</p><p><a href='process_review.json'>查看连续画面复核依据</a></p>"
        if process.get("clip"):
            panel += (
                "<video controls preload='none' style='max-width:100%;width:640px' src='"
                + quote(process["clip"]["path"], safe="/")
                + "'></video>"
            )
        panel += (
            "<pre>" + html.escape(json.dumps(process["response"], ensure_ascii=False, indent=2)) + "</pre></section>"
        )
        page = folder / "workbench.html"
        page.write_text(page.read_text().replace("</html>", panel + "</html>"))
    return b, case, tracks, folder, record


def group_export(rows, folder, shared_cache):
    folder.mkdir(parents=True, exist_ok=True)
    cases = [r["case"] for r in rows]
    knowledge = aggregate(cases)
    save(folder / "knowledge.json", knowledge)
    export_legacy(knowledge, folder)
    (folder / "review.html").write_text(render(knowledge))
    links = folder / "cases"
    links.mkdir(exist_ok=True)
    for row in rows:
        dst = links / row["folder"].name
        if not dst.exists():
            dst.symlink_to(row["folder"], target_is_directory=True)
    clip_cache = folder / "learning_tracks/classified_skill_clips/_clip_cache"
    clip_cache.parent.mkdir(parents=True, exist_ok=True)
    if not clip_cache.exists():
        clip_cache.symlink_to(shared_cache, target_is_directory=True)
    summary = export([r["tracks"] for r in rows], folder / "learning_tracks", export_clips=True)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--resume-delivery", action="store_true")
    ap.add_argument(
        "--prepare-ids", nargs="+", help="Prepare finished single-video outputs before all model jobs finish"
    )
    args = ap.parse_args(argv)
    run = args.run.resolve()
    snapshot = json.loads((run / "input_snapshot.json").read_text())
    rows = snapshot["media"]
    statuses = {
        r["id"]: json.loads((run / "status" / (r["id"] + ".json")).read_text())
        if (run / "status" / (r["id"] + ".json")).exists()
        else {"phase": "pending"}
        for r in rows
    }
    if args.prepare_ids:
        out = run / "delivery"
        out.mkdir(parents=True, exist_ok=True)
        for row in rows:
            if row["id"] not in args.prepare_ids:
                continue
            status = statuses[row["id"]]
            if status["phase"] != "complete" or status.get("task_protocol_revision") != 2:
                raise ValueError("Selected video has not completed the final task protocol")
            prepare_case(row, status, out)
            print(row["id"] + " single-video output prepared", flush=True)
        return 0
    if len(rows) != 16 or any(
        s["phase"] != "complete" or s.get("task_protocol_revision") != 2 for s in statuses.values()
    ):
        raise ValueError("All 16 videos must complete the same task protocol before learning")
    out = run / "delivery"
    if out.exists() and any(out.iterdir()) and not args.resume_delivery:
        raise FileExistsError("Use a new delivery or explicit resume")
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "_shared_pool_cache"
    cache.mkdir(exist_ok=True)
    prepared = []
    for r in rows:
        b, case, tracks, folder, record = prepare_case(r, statuses[r["id"]], out)
        prepared.append({"row": r, "bundle": b, "case": case, "tracks": tracks, "folder": folder, "record": record})
        print(r["id"] + " single-video outputs exported", flush=True)
    dev = [r for r in prepared if r["row"]["split"] == "development"]
    held = [r for r in prepared if r["row"]["split"] == "holdout"]
    assert len(dev) == 13 and len(held) == 3
    summaries = {}
    summaries["knowledge_development"] = group_export(dev, out / "knowledge_development", cache)
    frozen = {
        kind: sha256(out / "knowledge_development/learning_tracks" / kind / "knowledge.json")
        for kind in ["same_goal_graphs", "classified_skill_clips"]
    }
    summaries["holdout_observations"] = group_export(held, out / "holdout_observations", cache)
    evaluations = {}
    for kind in frozen:
        development = json.loads(
            (out / "knowledge_development/learning_tracks" / kind / "knowledge.json").read_text()
        )
        holdout = json.loads((out / "holdout_observations/learning_tracks" / kind / "knowledge.json").read_text())
        evaluations[kind] = explain(development, holdout)
    save(
        out / "holdout_evaluation.json",
        {
            "frozen_sha256": frozen,
            "decisions": evaluations,
            "policy": "Historical split regression; no reference outcomes enter development or holdout model outputs.",
        },
    )
    summaries["knowledge_all_16"] = group_export(prepared, out / "knowledge_all_16", cache)
    assert all(
        sha256(out / "knowledge_development/learning_tracks" / k / "knowledge.json") == v for k, v in frozen.items()
    )
    # Open outcome reference annotations only for the post-learning comparison.
    annotations = json.loads((ROOT / "data/16段视频_命名标注/标注数据.json").read_text())["视频标注"]
    references = {
        r["编号"]: reference_from_annotation(r, str(ROOT / "data/16段视频_命名标注/标注数据.json"))
        for r in annotations
    }
    comparisons = []
    cases = []
    for p in prepared:
        row = p["row"]
        b = p["bundle"]
        prediction = b["task_observation"]
        ref = references[row["id"]]
        fields = ["attempted", "outcome", "goal_satisfied_final", "method", "drop"]
        comparisons.append(
            {
                "case_id": row["id"],
                "differences": [k for k in fields if prediction[k] != ref[k]],
                "contradictions": [
                    k
                    for k in fields
                    if prediction[k] != ref[k]
                    and prediction[k] not in {"U", "Unknown", "unknown"}
                    and ref[k] not in {"U", "Unknown", "unknown"}
                ],
                "model_abstentions": [
                    k
                    for k in fields
                    if prediction[k] in {"U", "Unknown", "unknown"} and ref[k] not in {"U", "Unknown", "unknown"}
                ],
                "reference_unspecified": [k for k in fields if ref[k] in {"U", "Unknown", "unknown"}],
                "fresh_model": {k: prediction[k] for k in fields},
                "reference": {k: ref[k] for k in fields},
                "reference_usage": "evaluation_only_not_applied_to_learning",
            }
        )
        cases.append(
            {
                "case_id": row["id"],
                "split": row["split"],
                "source": row["source"],
                "sha256": row["sha256"],
                "result": str(p["folder"] / "result.json"),
                "validation": b["validation"]["summary"],
                "structural_passed": b["validation"]["passed"],
                "fresh_model_task_outcome": prediction["outcome"],
                "process_drop": prediction["drop"],
                "additional_process_review": bool(b.get("process_review")),
                "initial_analysis_model_calls": b["pipeline"]["llm_stats"]["calls"],
                "analysis_cache_hits": b["pipeline"]["llm_stats"]["cache_hits"],
                "local_review_response_status": p["record"]["status"],
            }
        )
    save(out / "reference_comparison.json", comparisons)
    summary = {
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "model": snapshot["model"],
        "endpoint": snapshot["endpoint"],
        "cases": cases,
        "source_videos": 16,
        "splits": {"development": 13, "holdout": 3},
        "structural_passes": sum(r["structural_passed"] for r in cases),
        "model_task_outcomes": dict(Counter(r["fresh_model_task_outcome"] for r in cases)),
        "initial_analysis_calls": sum(r["initial_analysis_model_calls"] for r in cases),
        "initial_analysis_cache_hits": sum(r["analysis_cache_hits"] for r in cases),
        "cache_scope": "Only newly generated stages inside this run were resumed; no historical model analysis cache was reused.",
        "learning_views": summaries,
        "reference_conflict_cases": [r["case_id"] for r in comparisons if r["contradictions"]],
        "development_frozen_unchanged": True,
        "original_sources_unchanged": all(sha256(r["source"]) == r["sha256"] for r in rows),
        "robot_execution_enabled": False,
    }
    save(out / "summary.json", summary)
    import html

    body = [
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>16段视频8032全量重分析</title>",
        "<style>body{font:17px system-ui;max-width:1200px;margin:36px auto;color:#172033}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:10px}pre{white-space:pre-wrap}</style>",
        "<h1>16段视频 · 8032全量重分析</h1>",
        "<p>每段重新分析画面与意图，保留七元组、完整任务图和局部技能片段。模型结果为候选；成败参考标注只用于学习之后的对照。</p><ul>",
    ]
    for name, label in [
        ("knowledge_all_16", "全部16段：任务图与技能切片"),
        ("knowledge_development", "13段开发集：归纳结果"),
        ("holdout_observations", "3段留出：独立保存的模型观察"),
    ]:
        body.append(f"<li><a href='{name}/learning_tracks/index.html'>{label}</a></li>")
    body.append(
        "</ul><p><a href='summary.json'>运行汇总</a> · <a href='reference_comparison.json'>与既有标注的差异</a> · <a href='holdout_evaluation.json'>冻结留出解释</a></p><table><tr><th>编号</th><th>来源</th><th>模型任务结果</th><th>过程掉落</th><th>结构校验</th><th>案例</th></tr>"
    )
    for c in cases:
        url = Path(c["result"]).parent.relative_to(out).as_posix() + "/workbench.html"
        body.append(
            "<tr><td>"
            + c["case_id"]
            + "</td><td>"
            + html.escape(Path(c["source"]).name)
            + "</td><td>"
            + c["fresh_model_task_outcome"]
            + "</td><td>"
            + c["process_drop"]
            + "</td><td>"
            + html.escape(c["validation"])
            + "</td><td><a href='"
            + url
            + "'>查看</a></td></tr>"
        )
    body.append("</table></html>")
    (out / "index.html").write_text("\n".join(body))
    print(
        json.dumps({k: v for k, v in summary.items() if k not in {"cases", "learning_views"}}, ensure_ascii=False),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
