"""Single-video instances and chronological clip manifest using shared skill templates."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .skill_clips import cut, intervals, sha256
from .skill_library import FIELDS, LIBRARY, load, save


def analysis_stamp(bundle):
    meta = bundle.setdefault("meta", {})
    if not meta.get("analysis_time"):
        meta["analysis_time"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="microseconds")
    parsed = datetime.fromisoformat(meta["analysis_time"])
    return parsed.strftime("%Y%m%d_%H%M%S_%f")


def safe_name(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")[:80] or "video"


def export_metadata(bundle, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    library = load()
    stamp = analysis_stamp(bundle)
    catalog_ref = Path(os.path.relpath(LIBRARY/"action_catalog.json", out)).as_posix()
    templates_ref = Path(os.path.relpath(LIBRARY/"skill_templates.json", out)).as_posix()
    graph = bundle["semantic_graph"]
    graph.setdefault("x-meta", {}).pop("action_catalog", None)
    graph["x-meta"].update(action_catalog_ref=catalog_ref, skill_templates_ref=templates_ref,
                            skill_template_revision=library["revision"])
    rows = []
    for nid, node in graph["nodes"].items():
        if nid in {"START", "END"}:
            continue
        template_ref = "action/"+node["name"]
        if template_ref not in library["templates"]:
            template_ref = None
        slots = library["templates"].get(template_ref, {}).get("seven_tuple", {}).get("O", {}).get("role_slots", [])
        role_bindings = []
        for slot in slots:
            refs = node["skill"]["O"] if slot["slot_ref"] == "GraspTargetSkillSlot" else []
            role_bindings.append({"slot_ref": slot["slot_ref"], "role_ref": slot["role_ref"],
                                  "object_ref": refs[0] if len(refs) == 1 else None,
                                  "candidate_object_refs": refs,
                                  "binding_status": "video_local_candidate" if len(refs) == 1 else "unbound",
                                  "basis": "local_node_object_reference_not_robot_world_fact"})
        rows.append({"instance_id": f'{graph["graph_id"]}:{nid}', "node_ref": nid,
                     "action": node["name"], "template_ref": template_ref, "role_bindings": role_bindings,
                     "seven_tuple": {k: node["skill"][k] for k in FIELDS},
                     "object_bindings": {ref: graph["objects"].get(ref) for ref in node["skill"]["O"]},
                     "evidence": graph.get("evidence", {}).get(nid, {}),
                     "provenance": "single_video_instance_not_global_definition"})
    graph["x-meta"]["skill_template_refs"] = {r["node_ref"]: r["template_ref"] for r in rows}
    view = {"schema_version": "single_video_skill_instances.v1", "analysis_time": bundle["meta"]["analysis_time"],
            "analysis_stamp": stamp, "tuple_fields": list(FIELDS),
            "catalog_ref": catalog_ref, "skill_templates_ref": templates_ref,
            "template_revision": library["revision"], "instances": rows}
    save(out/"skill_instances.json", view)
    from .skill_episodes import build as build_episodes
    episode_data = build_episodes(bundle, str((out/"result.json").resolve()))
    save(out/"skill_episodes.json", {"schema_version": episode_data["schema_version"], "episodes": episode_data["episodes"], "policy": episode_data["policy"]})
    save(out/"task_causal_audit.json", episode_data["task_causal_audit"])
    from .learning_tracks import split
    tracks=split(bundle,str((out/"result.json").resolve()))
    save(out/"task_learning_units.json",{"schema_version":"purpose_tasks.v1","instances":tracks["purpose_case"]["instances"]})
    save(out/"clip_classification.json",{"schema_version":"clip_classification.v1","instances":tracks["classification"]})
    bundle["output_layout"] = {"version": "single_video.v2", "skill_instances": "skill_instances.json",
                               "clip_manifest": "clip/sequence.json", "skill_episodes": "skill_episodes.json",
                               "task_causal_audit": "task_causal_audit.json", "task_learning_units": "task_learning_units.json",
                               "clip_classification": "clip_classification.json", "catalog_ref": catalog_ref,
                               "skill_templates_ref": templates_ref}
    save(out/"result.json", bundle)
    return view


def plan_clips(bundle, duration, padding=.25):
    graph = bundle["semantic_graph"]
    actions = {a["id"]: a for a in bundle.get("atomic", {}).get("atomic_actions", [])}
    plans, skipped = [], []
    for nid, node in graph["nodes"].items():
        if nid in {"START", "END"}:
            continue
        evidence = graph.get("evidence", {}).get(nid, {})
        selected = [actions[r] for r in evidence.get("atomic_refs", []) if r in actions]
        if evidence.get("inferred") or evidence.get("already_satisfied"):
            skipped.append({"node_ref": nid, "action": node["name"], "reason": "inferred_or_state_only_no_observed_event"})
            continue
        core, spans, issues = intervals(selected, duration, padding)
        if not spans:
            skipped.append({"node_ref": nid, "action": node["name"], "reason": "no_observed_valid_interval", "issues": issues})
            continue
        for n, span in enumerate(spans, 1):
            plans.append({"node_ref": nid, "action": node["name"], "segment_index": n,
                          "template_ref": graph.get("x-meta", {}).get("skill_template_refs", {}).get(nid), "atomic_refs": span["atomic_refs"],
                          "source_start_sec": span["start"], "source_end_sec": span["end"],
                          "core_intervals": [r for r in core if r["atomic_ref"] in span["atomic_refs"]],
                          "action_start_sec": min(r["start"] for r in core if r["atomic_ref"] in span["atomic_refs"]),
                          "action_end_sec": max(r["end"] for r in core if r["atomic_ref"] in span["atomic_refs"]),
                          "boundary_status": "model_candidate_with_context", "issues": issues})
    plans.sort(key=lambda r: (r["action_start_sec"], r["action_end_sec"], r["node_ref"], r["segment_index"]))
    return plans, skipped


def chronology(clips):
    # Start order is an index; it never changes overlap into a sequential dependency.
    relations = []
    for n, a in enumerate(clips):
        for b in clips[n+1:]:
            if a["action_end_sec"] <= b["action_start_sec"]:
                kind = "before"
            else:
                kind = "overlap"
            relations.append({"from": a["clip_id"], "to": b["clip_id"], "relation": kind,
                              "basis": "source_time_only_not_causal_dependency"})
    return relations


def export_case_clips(bundle, out, *, padding=.25, enabled=True, cache_dir=None):
    if not math.isfinite(padding) or padding < 0:
        raise ValueError("Clip padding must be a nonnegative finite number")
    out = Path(out)
    directory = out/"clip"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = analysis_stamp(bundle)
    source = Path(bundle.get("meta", {}).get("path") or "")
    quality = bundle.get("meta", {}).get("media_quality", {})
    duration = float(bundle["meta"].get("duration") or 0)
    coverage = quality.get("decoded_until_seconds")
    if coverage is not None:
        duration = min(duration, float(coverage))
    uid = sha256(source) if source.is_file() else None
    plans, skipped = plan_clips(bundle, duration, padding) if duration > 0 else ([], [])
    input_fingerprint = hashlib.sha256(json.dumps({
        "video_uid": uid, "analysis_stamp": stamp, "plans": plans, "padding": padding,
        "enabled": enabled}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    manifest_path = directory/"sequence.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing["input_fingerprint"] != input_fingerprint:
            # v1 hashed the whole graph, including unrelated shared-library metadata.
            # Upgrade only after comparing every actual crop input and source identity.
            same_plans = len(existing["clips"]) == len(plans) and all(
                all(row.get(k) == v for k, v in plan.items())
                for row, plan in zip(existing["clips"], plans, strict=True))
            if (existing.get("fingerprint_version", 1) != 1 or
                    existing["source_video"]["sha256"] != uid or
                    existing["analysis_stamp"] != stamp or not same_plans or
                    (existing["status"] == "disabled") != (not enabled)):
                raise ValueError("Existing clip manifest belongs to another analysis; use a new case directory")
            existing["input_fingerprint"] = input_fingerprint
            existing["fingerprint_version"] = 2
            save(manifest_path, existing)
        if all(r.get("status") != "exported" or sha256(directory/r["filename"]) == r["sha256"]
               for r in existing["clips"]):
            bundle["clip_export"] = {k: existing[k] for k in ["status", "exported", "analysis_time"]}
            return existing
        raise ValueError("Existing clip bytes differ from their manifest")
    errors = []

    if not source.is_file() or duration <= 0 or quality.get("decoded_frames") == 0:
        errors.append({"reason": "source_media_unavailable_or_undecodable"})
    original_name = safe_name(source.stem if source.name else bundle["meta"].get("name", "video"))
    rows = []
    for n, plan in enumerate(plans, 1):
        row = {**plan, "clip_id": f"clip_{n:03d}", "sequence_index": n,
               "filename": f'{original_name}_{safe_name(plan["action"])}_{n:03d}_{stamp}.mp4',
               "source_time_offset": plan["source_start_sec"], "status": "planned"}
        if not enabled:
            row["status"] = "disabled"
        elif errors:
            row["status"] = "source_unavailable"
        else:
            try:
                target = directory/row["filename"]
                if cache_dir is not None:
                    import shutil
                    cache = Path(cache_dir)
                    cache.mkdir(parents=True, exist_ok=True)
                    key = hashlib.sha256(json.dumps([uid, row["source_start_sec"], row["source_end_sec"], "source_crf18_v1"]).encode()).hexdigest()
                    cached = cache/(key+".mp4")
                    info = cache/(key+".json")
                    if info.exists():
                        probe = json.loads(info.read_text())
                        if sha256(cached) != probe["sha256"]:
                            raise ValueError("Shared clip cache bytes changed")
                    else:
                        probe = cut(source, cached, row["source_start_sec"], row["source_end_sec"])
                        save(info, probe)
                    try:
                        os.link(cached, target)
                    except OSError:
                        if target.exists():
                            raise
                        shutil.copy2(cached, target)
                    probe = {**probe, "path": str(target)}
                else:
                    probe = cut(source, target, row["source_start_sec"], row["source_end_sec"])
                row.update(status="exported", sha256=probe["sha256"], probe=probe)
            except Exception as exc:
                row.update(status="failed", error=str(exc))
        rows.append(row)
    exported = sum(r["status"] == "exported" for r in rows)
    failed = [r["clip_id"] for r in rows if r["status"] not in {"exported", "disabled"}]
    result = {"schema_version": "single_video_clip_sequence.v1", "analysis_time": bundle["meta"]["analysis_time"],
              "analysis_stamp": stamp, "timezone": "Asia/Shanghai", "input_fingerprint": input_fingerprint, "fingerprint_version": 2,
              "source_video": {"path": str(source), "name": original_name, "sha256": uid,
                               "fps": bundle["meta"].get("fps"), "duration": bundle["meta"].get("duration")},
              "status": "disabled" if not enabled else "complete" if not errors and not failed else "needs_review",
              "exported": exported, "clips": rows, "chronological_order": [r["clip_id"] for r in rows],
              "temporal_relations": chronology(rows), "semantic_relations": bundle["semantic_graph"]["relations"],
              "skipped_nodes": skipped, "errors": errors,
              "policy": "Video intervals are candidate boundaries; time order is separate from semantic dependencies."}
    save(manifest_path, result)
    bundle["clip_export"] = {k: result[k] for k in ["status", "exported", "analysis_time"]}
    save(out/"result.json", bundle)
    return result


def clip_panel(out):
    import html
    path = Path(out)/"clip/sequence.json"
    if not path.exists():
        return ""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    rows = ['<section style="margin:24px;padding:20px;border:1px solid #64748b;border-radius:12px"><h2>动作视频切片</h2>',
            '<p>按动作开始时间排列；重叠关系与语义依赖分别保留。边界仍需结合证据审阅。</p>',
            '<p><a href="clip/sequence.json">查看时间顺序与来源索引</a> · <a href="skill_instances.json">查看本视频七元组实例</a></p>']
    for row in manifest["clips"]:
        rows.append("<h3>"+html.escape(f'{row["sequence_index"]:03d} · {row["action"]}')+"</h3>")
        rows.append("<p>"+html.escape(f'动作 {row["action_start_sec"]:.3f}—{row["action_end_sec"]:.3f}s；片段含上下文 {row["source_start_sec"]:.3f}—{row["source_end_sec"]:.3f}s；{row["status"]}')+"</p>")
        if row["status"] == "exported":
            rows.append('<video controls preload="none" style="width:480px;max-width:100%" src="clip/'+html.escape(row["filename"],quote=True)+'"></video>')
    return "\\n".join(rows)+"</section>"


def attach_classified_clips(out):
    """Link each semantic classification to real single-video clips and contexts."""
    out=Path(out)
    file=out/"clip_classification.json"
    data=json.loads(file.read_text())
    sequence=json.loads((out/"clip/sequence.json").read_text())
    episodes=json.loads((out/"clip/episodes/episode_sequence.json").read_text())
    for row in data["instances"]:
        core=set(row["atomic_refs"])
        row["core_clips"]=[{"clip_id":c["clip_id"],"path":"clip/"+c["filename"],"status":c["status"],
                            "source_start_sec":c["source_start_sec"],"source_end_sec":c["source_end_sec"]}
                           for c in sequence["clips"] if set(c["atomic_refs"]) & core]
        row["context_videos"]=[{"kind":v["kind"],"path":"clip/episodes/"+v["path"],"status":v["status"]}
                               for e in episodes["episodes"] if e["instance_id"]==row["instance_id"] for v in e["videos"]]
    save(file,data)
    return data
