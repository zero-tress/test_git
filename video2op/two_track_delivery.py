"""Deliver the two learning tracks, their clips, and auditable conditions offline."""

from __future__ import annotations

import html
import json
import os
from collections import Counter
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

from .branch_guards import induce as branch_guards
from .condition_induction import induce as condition_contrasts
from .contrastive_learning import pool_summary
from .cross_video_alignment import digest
from .cross_video_delivery import export as export_graphs
from .knowledge import aggregate
from .semantic_state import alias_map, atoms
from .skill_clips import cut, save, sha256

OUTCOMES = ("success", "failure", "not_executed", "unknown")


def samples_for(case):
    result = []
    by_id = {u["instance_id"]: u for u in case["instances"]}
    for iid, u in by_id.items():
        acts = u["observed_process"]
        boundary = u.get("boundary") or {
            "start_sec": min(a["start"] for a in acts),
            "end_sec": max(a["end"] for a in acts),
        }
        observations = deepcopy(u.get("condition_observations", [])) or [
            deepcopy(o) for o in case["observations"] if o["instance_id"] == iid
        ]
        for row in observations:
            row.setdefault("phase", "entry" if row.get("at", "pre") == "pre" else "post")
            row.setdefault("predicate", row.get("condition_key"))
            times = [
                v.get("timestamp", v.get("at_sec"))
                for v in row.get("evidence", [])
                if isinstance(v, dict) and v.get("timestamp", v.get("at_sec")) is not None
            ]
            row.setdefault("at_sec", max(times) if times else None)
        review = u.get("contrastive_outcome_review", {}).get("raw_review", {})
        result.append(
            {
                "instance_id": iid,
                "video_uid": u["video_uid"],
                "goal_key": u["goal_key"],
                "instance_scope": u["instance_scope"],
                "outcome": u["outcome"],
                "outcome_status": u["outcome_status"],
                "boundary": deepcopy(boundary),
                "condition_observations": observations,
                "eligible_for_rule_learning": review.get("scope_verdict") == "supported"
                and not u.get("goal_effect_audit", {}).get("issues"),
                "source_analysis": u.get("analysis_source", u["source"]),
            }
        )
    return result


def attach_guards(knowledge, guards):
    for skill in knowledge["skills"]:
        graph = skill["general_operation_graph"]
        matching = [b for b in guards["branches"] if b["skill_id"] == skill["skill_id"]]
        for path in graph["alternatives"]:
            conditions = []
            for b in matching:
                edges = [
                    e["to"]
                    for e in path["relations"]
                    if e["from"] == b["branch_node"] and e["relation"] == "sequence"
                ]
                for rule in b["rules"]:
                    if rule["target"] in edges:
                        conditions.append(
                            {
                                "branch_node": b["branch_node"],
                                "target": rule["target"],
                                "predicate": rule["predicate"],
                                "expected_truth": rule["expected_truth"],
                                "status": rule["status"],
                                "execution_enabled": False,
                            }
                        )
            path["selection_guard"].update(
                status="observational_candidates" if conditions else "unresolved",
                truth="U",
                observed_candidates=conditions,
                evidence_ref="../../branch_guards.json",
            )


def export_pool_clips(knowledge, out, enabled=True):
    """One source instance is one trial, even when several contexts are exported."""
    from .case_outputs import analysis_stamp, safe_name

    out = Path(out)
    manifest_path = out / "clip_index.json"
    cache = out / "_clip_cache"
    prior = {}
    if manifest_path.exists():
        prior = {r["instance_id"]: r for r in json.loads(manifest_path.read_text())["instances"]}
    rows = []
    bundles = {}
    for sequence, u in enumerate(knowledge["instances"], 1):
        source_path = u.get("analysis_source", u["source"])
        if source_path not in bundles:
            bundles[source_path] = json.loads(Path(source_path).read_text())
        b = bundles[source_path]
        source = Path(b["meta"]["path"])
        if sha256(source) != u["video_uid"]:
            raise ValueError("Source video bytes changed: " + str(source))
        actions = [a for a in u["observed_process"] if not a.get("inferred")]
        core = set(u.get("core_atomic_refs", u["atomic_refs"]))
        core_actions = [a for a in actions if a["id"] in core]
        if not core_actions:
            continue
        start = min(a["start"] for a in core_actions)
        end = max(a["end"] for a in core_actions)
        boundary = u.get("boundary", {})
        context_end = boundary.get("context_end_sec", min(b["meta"]["duration"], end + 0.5))
        later = [f.get("timestamp", 0) for f in u.get("outcome_evidence", []) if isinstance(f, dict)]
        if u["goal_key"] == "grasp_object":
            release = min(
                (
                    a["start"]
                    for a in b["atomic"]["atomic_actions"]
                    if a.get("functional_role", {}).get("function") == "释放"
                    and a["start"] >= end
                    and a.get("object") == u["target"]["local_entity"]
                ),
                default=b["meta"]["duration"],
            )
            context_end = min(release, max([context_end] + [t + 0.1 for t in later]))
        available = b["meta"].get("media_quality", {}).get("decoded_until_seconds", b["meta"]["duration"])
        spans = [("core", max(0, start - 0.15), min(b["meta"]["duration"], end + 0.15))]
        if u.get("instance_scope") == "skill_episode":
            spans.extend(
                [
                    ("process_context", max(0, boundary["start_sec"] - 0.25), end),
                    ("effect_context", max(0, start - 0.25), min(b["meta"]["duration"], context_end)),
                ]
            )
        row = {
            "instance_id": u["instance_id"],
            "video_uid": u["video_uid"],
            "goal_key": u["goal_key"],
            "outcome": u["outcome"],
            "outcome_status": u["outcome_status"],
            "target": u["target"],
            "parent_task_refs": u.get("parent_task_refs", []),
            "atomic_refs": u["atomic_refs"],
            "core_atomic_refs": sorted(core),
            "source_analysis": source_path,
            "source_video": str(source),
            "segments": [],
        }
        for kind, lo, hi in spans:
            if hi <= lo:
                continue
            if hi > available + 0.05:
                row["segments"].append(
                    {
                        "kind": kind,
                        "status": "outside_verified_decode_coverage",
                        "source_start_sec": lo,
                        "source_end_sec": hi,
                    }
                )
                continue
            key = digest([u["video_uid"], lo, hi, "crf18_source"])
            name = f"{safe_name(source.stem)}_{safe_name(u['expected']['name'])}_{sequence:03d}_{analysis_stamp(b)}_{kind}.mp4"
            rel = Path("skill_sets") / u["goal_key"] / u["outcome"] / name
            target = out / rel
            segment = {
                "kind": kind,
                "path": rel.as_posix(),
                "source_start_sec": lo,
                "source_end_sec": hi,
                "input_fingerprint": key,
                "status": "disabled",
            }
            if enabled:
                cache.mkdir(parents=True, exist_ok=True)
                cached = cache / (key + ".mp4")
                meta = cache / (key + ".json")
                old = next(
                    (
                        s
                        for s in prior.get(u["instance_id"], {}).get("segments", [])
                        if s.get("input_fingerprint") == key and s.get("status") == "exported"
                    ),
                    None,
                )
                if old:
                    if sha256(out / old["path"]) != old["probe"]["sha256"]:
                        raise ValueError("Existing pool clip changed")
                    segment = deepcopy(old)
                else:
                    if meta.is_file():
                        probe = json.loads(meta.read_text())
                        if sha256(cached) != probe["sha256"]:
                            raise ValueError("Cached pool clip changed")
                    else:
                        probe = cut(source, cached, lo, hi)
                        save(meta, probe)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        if sha256(target) != probe["sha256"]:
                            raise ValueError("Existing pool target differs")
                    else:
                        os.link(cached, target)
                    segment.update(status="exported", probe=probe)
            row["segments"].append(segment)
        rows.append(row)
        save(manifest_path, {"schema_version": "classified_skill_clips.v1", "instances": rows, "complete": False})
    result = {
        "schema_version": "classified_skill_clips.v1",
        "instances": rows,
        "complete": True,
        "trial_count": len(rows),
        "mp4_count": sum(s["status"] == "exported" for r in rows for s in r["segments"]),
        "policy": "Core/process/effect context videos are views of one trial, not independent demonstrations.",
    }
    save(manifest_path, result)
    return result


def _review_page(knowledge, pools, clips, out):
    rows = [
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>同类技能切片正反例学习</title>",
        "<style>body{font:16px system-ui;max-width:1250px;margin:32px auto;color:#172033}section{border-top:1px solid #bbb;padding:20px 0}article{border:1px solid #ddd;padding:16px;margin:12px 0}video{width:420px;max-width:100%}pre{white-space:pre-wrap;word-break:break-word}select{padding:8px}</style>",
        "<h1>同类技能切片正反例学习</h1><p>按局部意图与目标效果归类。成功、失败、未执行、未知分别记录；任务成败与局部技能成败各有作用域。</p>",
        "<p><a href='condition_contrasts.json'>条件对照</a> · <a href='clip_index.json'>片段与源时间</a> · <a href='../same_goal_graphs/cross_video_review.html'>同目标任务图归纳</a></p>",
        "<label>样本状态 <select onchange=\"document.querySelectorAll('article').forEach(a=>a.hidden=this.value&&a.dataset.outcome!==this.value)\"><option value=''>全部</option>"
        + "".join(f"<option value='{o}'>{o}</option>" for o in OUTCOMES)
        + "</select></label>",
    ]
    by_id = {r["instance_id"]: r for r in clips["instances"]}
    for skill in knowledge["skills"]:
        goal = skill["goal_key"]
        rows.append("<section><h2>" + html.escape(skill["name"]) + "</h2>")
        rows.append("<pre>" + html.escape(json.dumps(pools["skills"][goal]["counts"], ensure_ascii=False)) + "</pre>")
        if pools["skills"][goal]["missing_negative_trials"]:
            rows.append("<p>当前缺少该技能的真实失败案例，尚不能形成充分的成败对照。</p>")
        for u in knowledge["instances"]:
            if u["goal_key"] != goal:
                continue
            rows.append(
                f"<article data-outcome='{u['outcome']}'><h3>"
                + html.escape(Path(by_id[u["instance_id"]]["source_video"]).name + " · " + u["outcome"])
                + "</h3>"
            )
            rows.append("<p>" + html.escape(u["instance_id"] + " · " + u["outcome_status"]) + "</p>")
            for seg in by_id[u["instance_id"]]["segments"]:
                rows.append(
                    "<p>"
                    + html.escape(
                        f"{seg['kind']}：源视频 {seg['source_start_sec']:.3f}—{seg['source_end_sec']:.3f} 秒"
                    )
                    + "</p>"
                )
                if seg["status"] == "exported":
                    rows.append("<video controls preload='none' src='" + quote(seg["path"], safe="/") + "'></video>")
            rows.append(
                "<details><summary>局部结果依据与范围</summary><pre>"
                + html.escape(
                    json.dumps(
                        {
                            "review": u.get("contrastive_outcome_review"),
                            "classification": u.get("classification"),
                            "outcome_evidence": u["outcome_evidence"],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                + "</pre></details></article>"
            )
        rows.append("</section>")
    (Path(out) / "index.html").write_text("\n".join(rows) + "</html>")


def export(tracks, out, export_clips=True):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    purpose_cases = [t["purpose_case"] for t in tracks]
    clip_cases = [t["clip_case"] for t in tracks]
    tasks = aggregate(purpose_cases)
    local = aggregate(clip_cases)
    task_samples = [s for c in purpose_cases for s in samples_for(c)]
    local_samples = [s for c in clip_cases for s in samples_for(c)]
    guards = branch_guards(tasks, task_samples)
    attach_guards(tasks, guards)
    save(out / "branch_guards.json", guards)
    summaries = {}
    for name, k in [("same_goal_graphs", tasks), ("classified_skill_clips", local)]:
        save(out / name / "knowledge.json", k)
        summaries[name] = export_graphs(k, out / name)
    pools = pool_summary(local_samples)
    clips = export_pool_clips(local, out / "classified_skill_clips", enabled=export_clips)
    save(out / "classified_skill_clips/contrastive_samples.json", local_samples)
    save(out / "classified_skill_clips/pools.json", pools)
    save(out / "classified_skill_clips/condition_contrasts.json", pools["condition_contrasts"])
    save(
        out / "same_goal_graphs/condition_contrasts.json",
        condition_contrasts([o for s in task_samples for o in s["condition_observations"]]),
    )
    save(out / "same_goal_graphs/task_samples.json", task_samples)
    _review_page(local, pools, clips, out / "classified_skill_clips")
    alignments = []
    for t in tracks:
        uid = t["purpose_case"]["video_uid"]
        save(out / "task_causal_audits" / (uid + ".json"), t["task_causal_audit"])
        for u in t["clip_case"]["instances"] + t["purpose_case"]["instances"]:
            alignments.append(
                {
                    "instance_id": u["instance_id"],
                    "video_uid": uid,
                    "aliases": alias_map(u),
                    "states": [
                        {
                            "atomic_ref": a["id"],
                            "original": a.get("state_after"),
                            "atoms": atoms(a.get("state_after", ""), u, a.get("executor")),
                        }
                        for a in u["observed_process"]
                    ],
                }
            )
    save(out / "semantic_alignment.json", alignments)
    censored = [
        deepcopy(c["task_observation"])
        for c in purpose_cases
        if c.get("task_observation", {}) and c["task_observation"].get("outcome") == "not_executed"
    ]
    save(
        out / "censored_tasks.json",
        {"observations": censored, "policy": "No unexecuted skill action or negative clip is invented."},
    )
    manifest = {
        "schema_version": "two_track_learning.v1",
        "summaries": summaries,
        "source_video_count": len({c["video_uid"] for c in purpose_cases}),
        "classified_trial_count": clips["trial_count"],
        "classified_mp4_count": clips["mp4_count"],
        "local_outcome_counts": dict(Counter(s["outcome"] for s in local_samples)),
        "censored_task_count": len(censored),
        "causally_verified": False,
        "execution_enabled": False,
        "unresolved_user_goals": [t["purpose_case"]["source"] for t in tracks if t["unresolved_goal"]],
    }
    save(out / "learning_tracks.json", manifest)
    audit_links = (
        "<h2>源任务图因果校验</h2><ul>"
        + "".join(
            "<li><a href='task_causal_audits/"
            + t["purpose_case"]["video_uid"]
            + ".json'>"
            + html.escape(Path(t["purpose_case"]["source"]).parent.name)
            + "</a></li>"
            for t in tracks
        )
        + "</ul>"
    )

    (out / "index.html").write_text(
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>任务图归纳与技能对照</title><body style='font:18px system-ui;max-width:1100px;margin:40px auto'><h1>任务图归纳与技能对照</h1><p><a href='same_goal_graphs/cross_video_review.html'>同目标任务图：支路合并、功能合并与七元组 R</a></p><p><a href='classified_skill_clips/index.html'>同类技能切片：正反例与条件对照</a></p><p><a href='branch_guards.json'>任务路径选择条件及证据缺口</a> · <a href='semantic_alignment.json'>同义状态与对象对齐</a></p><pre style='white-space:pre-wrap'>"
        + html.escape(json.dumps(manifest, ensure_ascii=False, indent=2))
        + "</pre>"
        + audit_links
        + "</body></html>"
    )
    return manifest
