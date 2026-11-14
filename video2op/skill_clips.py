"""Export source-resolution skill evidence clips without changing saved observations."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import subprocess
from copy import deepcopy
from pathlib import Path

from . import media


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def intervals(actions, duration, padding=0.25):
    """Keep gaps and overlapping/nested instances; reject invalid source timestamps."""
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(padding) or padding < 0:
        raise ValueError("Invalid media duration or padding")
    core, issues = [], []
    for a in actions:
        if a.get("inferred"):
            issues.append({"atomic_ref": a["id"], "reason": "inferred_action_not_clip_evidence"})
            continue
        try:
            start, end = float(a["start"]), float(a["end"])
        except (KeyError, TypeError, ValueError):
            issues.append({"atomic_ref": a.get("id"), "reason": "invalid_time"})
            continue
        if not (math.isfinite(start) and math.isfinite(end)) or end <= start or end <= 0 or start >= duration:
            issues.append({"atomic_ref": a.get("id"), "reason": "outside_or_invalid_time"})
            continue
        clipped = [max(0.0, start), min(duration, end)]
        if clipped != [start, end]:
            issues.append({"atomic_ref": a["id"], "reason": "clamped_to_available_media"})
        core.append({"start": clipped[0], "end": clipped[1], "atomic_ref": a["id"]})
    spans = []
    for a in sorted(core, key=lambda r: (r["start"], r["end"])):
        start, end = max(0.0, a["start"] - padding), min(duration, a["end"] + padding)
        if spans and start <= spans[-1]["end"] + 1e-6:
            spans[-1]["end"] = max(spans[-1]["end"], end)
            spans[-1]["atomic_refs"].append(a["atomic_ref"])
        else:
            spans.append({"start": start, "end": end, "atomic_refs": [a["atomic_ref"]]})
    return core, spans, issues


def cut(source, target, start, end):
    """Accurate re-encode, original resolution/frame rate, audio when present."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-n", "-hide_banner", "-loglevel", "error", "-threads", "1",
               "-i", str(source), "-ss", f"{start:.6f}", "-t", f"{end-start:.6f}",
               "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast",
               "-crf", "18", "-threads", "1", "-c:a", "aac", "-movflags", "+faststart", str(target)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr[-800:])
    info = media.probe(target)
    decode = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-threads", "1",
                             "-i", str(target), "-f", "null", "-"], capture_output=True, text=True, timeout=90)
    if decode.returncode or decode.stderr.strip() or info["duration"] <= 0:
        raise RuntimeError("Exported clip failed decoding: " + decode.stderr[-500:])
    return {**info, "sha256": sha256(target), "decode_verified": True}


def export(knowledge, out, manifest, padding=0.25, include_actions=True, resume=False):
    out = Path(out).resolve()
    run_signature = hashlib.sha256(json.dumps({"knowledge": knowledge, "manifest": manifest,
                                              "padding": padding, "include_actions": include_actions},
                                             ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    prior = {}
    if out.exists() and any(out.iterdir()):
        if not resume or not (out / "manifest.json").is_file():
            raise FileExistsError("Use a new empty clip directory or explicit --resume")
        previous = json.loads((out / "manifest.json").read_text())
        if previous.get("run_signature", run_signature) != run_signature:
            raise ValueError("Resume inputs or export settings differ")
        prior = {(r["video_uid"], r["kind"], r["instance_id"]): r for r in previous["instances"]}
    out.mkdir(parents=True, exist_ok=True)
    splits = {r["sha256"]: r for r in manifest["media"]}
    bundles, video_info = {}, {}
    instances = knowledge["instances"]
    rows, files, diagnostics = [], [], []
    # Export each video even when it has no recognized skill instances.
    source_paths = {i.get("analysis_source", i["source"]) for i in instances}
    for source in knowledge.get("sources", []):
        source_paths.update(source.get("source_files", []))
    for path in sorted(source_paths):
        b = json.loads(Path(path).read_text())
        uid = b.get("source_video_sha256")
        if uid in splits:
            bundles.setdefault(uid, b)
    for uid, bundle in sorted(bundles.items()):
        entry = splits[uid]
        source = Path(bundle["meta"]["path"])
        if not source.is_file() or sha256(source) != uid:
            raise ValueError("Missing or changed original video: " + str(source))
        info = media.probe(source)
        quality = bundle["meta"].get("media_quality", {})
        available = min(info["duration"], quality.get("decoded_until_seconds") or info["duration"])
        video_info[uid] = {"case_id": entry["id"], "split": entry["split"], "source": str(source),
                           "source_sha256": uid, "duration": info["duration"], "available_until": available,
                           "width": info["width"], "height": info["height"], "fps": info["fps"]}
    def add(item, kind, name, uid):
        b, vi = bundles[uid], video_info[uid]
        actions = item["observed_process"]
        core, spans, issues = intervals(actions, vi["available_until"], padding)
        iid = item["instance_id"]
        safe_name = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "_", name)[:60]
        row = {"instance_id": iid, "kind": kind, "name": name, "video_uid": uid,
               "case_id": vi["case_id"], "split": vi["split"], "source_video": vi["source"],
               "source_sha256": uid, "goal_key": item.get("goal_key"), "target": deepcopy(item.get("target")),
               "bindings": deepcopy(item.get("bindings", {})), "instance_scope": item.get("instance_scope"),
               "atomic_refs": item["atomic_refs"], "core_intervals": core, "segments": [],
               "outcome": item.get("outcome", "unknown"), "outcome_status": item.get("outcome_status", "unverified"),
               "goal_effect_audit": deepcopy(item.get("goal_effect_audit", {})),
               "operation_subgraph": deepcopy(item.get("operation_subgraph", {})),
               "source_node_refs": item.get("source_node_refs", []),
               "analysis_source": item.get("analysis_source", item.get("source")),
               "task_observation": deepcopy(b.get("task_observation")),
               "parent_instances": [j["instance_id"] for j in instances if j["video_uid"] == uid
                                    and j["instance_id"] != iid and set(item["atomic_refs"]) < set(j["atomic_refs"])],
               "neighbor_actions": [{k: a.get(k) for k in ["id", "start", "end", "action", "object"]}
                                    for a in b["atomic"]["atomic_actions"] if a["id"] not in item["atomic_refs"]],
               "state_evidence": [{k: a.get(k) for k in ["id", "start", "end", "object", "state_before",
                                     "state_after", "world_before", "world_after", "visual_state_evidence",
                                     "confidence", "inferred", "media_coverage_status"]} for a in actions],
               "issues": issues, "boundary_status": "model_candidate_requires_review",
               "label_provenance": "saved_analysis_not_human_verified"}
        previous = prior.get((uid, kind, iid))
        if previous and previous["status"] == "exported":
            for key in row:
                if key not in {"segments", "issues", "boundary_status", "label_provenance"} and previous.get(key) != row[key]:
                    raise ValueError("Resume metadata differs: " + iid + " / " + key)
            if len(previous["segments"]) != len(spans):
                raise ValueError("Resume padding differs")
            for old, expected in zip(previous["segments"], spans, strict=True):
                if any(old[k] != expected[k] for k in ["start", "end", "atomic_refs"]):
                    raise ValueError("Resume intervals differ")
                if sha256(out / old["path"]) != old["probe"]["sha256"]:
                    raise ValueError("Resume clip bytes differ")
            rows.append(previous)
            files.extend(previous["segments"])
            return
        for n, span in enumerate(spans, 1):
            rel = Path(vi["split"]) / kind / safe_name / f'{vi["case_id"]}_{iid}_{n:02d}.mp4'
            try:
                if (out / rel).exists():
                    quarantine = out / "incomplete" / (rel.stem + "_" + __import__("uuid").uuid4().hex + ".mp4")
                    quarantine.parent.mkdir(parents=True, exist_ok=True)
                    (out / rel).rename(quarantine)
                probe = cut(vi["source"], out / rel, span["start"], span["end"])
                if abs(probe["fps"] - vi["fps"]) > .05:
                    raise ValueError("Clip frame rate differs from source")
                if (probe["width"], probe["height"]) != (vi["width"], vi["height"]):
                    raise ValueError("Clip resolution differs from source")
                if abs(probe["duration"] - (span["end"]-span["start"])) > max(.15, 2/max(vi["fps"], 1)):
                    raise ValueError("Clip duration differs from source interval")
                record = {**span, "path": rel.as_posix(), "source_time_offset": span["start"],
                          "probe": probe, "quality": "source_resolution_frame_rate_crf18"}
                row["segments"].append(record)
                files.append(record)
            except Exception as exc:
                row["issues"].append({"reason": "clip_export_failed", "detail": str(exc)})
        row["status"] = "exported" if row["segments"] and len(row["segments"]) == len(spans) else "needs_review"
        rows.append(row)
        save(out / "manifest.json", {"schema_version": "skill_clips.v1", "run_signature": run_signature, "instances": rows,
                                     "videos": list(video_info.values()), "complete": False})
    for item in instances:
        add(item, "skills", item["expected"]["name"], item["video_uid"])
    if include_actions:
        for uid, b in sorted(bundles.items()):
            for a in b["atomic"]["atomic_actions"]:
                function = a.get("functional_role", {}).get("function") or a.get("semantic_action") or "未分类动作"
                item = {"instance_id": f'action_{a["id"]}', "atomic_refs": [a["id"]],
                        "observed_process": [a], "target": {"local_entity": a.get("object")},
                        "source": b["meta"]["path"], "instance_scope": "atomic_evidence"}
                add(item, "actions", function, uid)
    index = {"schema_version": "skill_clips.v1", "run_signature": run_signature, "complete": True, "videos": list(video_info.values()),
             "instances": rows, "summary": {"videos": len(video_info), "skill_instances": len(instances),
             "action_instances": sum(r["kind"] == "actions" for r in rows), "clip_files": len(files),
             "exported_instances": sum(r["status"] == "exported" for r in rows),
             "export_issues": sum(r["status"] != "exported" or bool(r["issues"]) for r in rows),
             "boundary_review_candidates": len(rows)},
             "policy": "Boundaries/labels remain saved model candidates. Holdout stays separate. No relabeling from whole-task outcome.",
             "diagnostics": diagnostics}
    save(out / "manifest.json", index)
    body = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>技能与动作视频切片</title>",
            "<style>body{font:16px system-ui;max-width:1100px;margin:32px auto}video{width:420px;max-width:100%}article{border-top:1px solid #ccc;padding:16px}small{display:block}</style>",
            "<h1>技能与动作视频切片</h1><p>技能、动作分别索引；开发集与留出集分别保存。边界和标签来自已有模型分析，待语义审阅。</p>",
            "<pre>"+html.escape(json.dumps(index["summary"], ensure_ascii=False, indent=2))+"</pre>"]
    for row in rows:
        body.append("<article><h2>"+html.escape(f'{row["case_id"]} · {row["split"]} · {row["kind"]} · {row["name"]}')+"</h2>")
        body.append("<small>"+html.escape(f'{row["instance_id"]} / outcome={row["outcome"]} / {row["status"]} / {row["issues"]}')+"</small>")
        for segment in row["segments"]:
            body.append(f'<p>源视频 {segment["start"]:.3f}—{segment["end"]:.3f} 秒</p><video controls preload="none" src="{html.escape(segment["path"], quote=True)}"></video>')
        body.append("</article>")
    (out / "index.html").write_text("\n".join(body) + "</html>")
    return index


def main(argv=None):
    ap = argparse.ArgumentParser(description="按保存的技能范围和动作时间导出原分辨率视频，不调用模型")
    ap.add_argument("--knowledge", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=Path(__file__).resolve().parents[1]/"eval/manifest.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--padding", type=float, default=.25)
    ap.add_argument("--skills-only", action="store_true")
    ap.add_argument("--resume", action="store_true", help="校验已有索引和片段后继续中断的导出")
    args = ap.parse_args(argv)
    result = export(json.loads(args.knowledge.read_text()), args.out,
                    json.loads(args.manifest.read_text()), args.padding, not args.skills_only, args.resume)
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 1 if any(any(i["reason"] == "clip_export_failed" for i in r["issues"]) for r in result["instances"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
