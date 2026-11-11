"""Review uncertain hand/arm observations against original video and real frames."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

from . import config, grasp_preparation, media, sampling, semantic
from .evidence import observed_state
from .stages import s02b_atomic, s02b_merge

SYSTEM = """你是局部视频证据复查员。只报告实际可见的信息，不按任务常识补造动作。
视频片段时间从0开始；图片标签给出源视频全局时间，不可混用。
运动候选不是接触或抓握事实。手打开、抓握、释放属于手；靠近、搬运属于臂。
看不清、遮挡、视频边界之外的信息写unclear。不生成保持动作。
输出JSON：
{"state_checks":[{"atomic_ref":整数,"field":"state_before或state_after",
"status":"observed或unclear","state":"可见状态或空串","evidence_frames":["提供的帧ID"]}],
"missing_actions":[原子动作],"notes":"遮挡或不确定性"}
仅填写待检查动作的状态。missing_actions仅填此前漏掉且在视频中明确发生的动作，
遵循原子动作完整字段：id,executor,action,mode(transition/motion),start,end,
exerts_force,force_role,object,state_before,state_after,world_before,world_after,
operation_intent,confidence,evidence,evidence_frames。
start/end为本片段局部秒数；每个新增动作必须有提供的证据帧ID。单张静态手姿势不能证明发生过打开动作。
"""


def plan(ctx: dict) -> list[dict]:
    duration = ctx["meta"]["duration"]
    actions = ctx["atomic"]["atomic_actions"]
    candidates = []
    by_id = {a["id"]: a for a in actions}
    for req in grasp_preparation.inspect(actions):
        if req["status"] != "satisfied":
            a = by_id[req["grasp_ref"]]
            candidates.append((0, a["start"] - 0.75, a["end"] + 0.35,
                               [a["id"]], "grasp_preopen_" + req["status"]))
    for a in actions:
        release = a.get("executor") in grasp_preparation.HANDS and any(
            w in a.get("action", "") for w in grasp_preparation.RELEASE_WORDS)
        if release and (not observed_state(a, "state_before")
                        or not observed_state(a, "state_after")
                        or not any(w in str(a.get("world_before") or []) + observed_state(a, "state_before")
                                   for w in ("支撑", "桌面", "接触", "台面"))):
            candidates.append((1, a["start"] - 0.75, a["end"] + 0.5, [a["id"]],
                               "release_support_or_end_state_unclear"))
        if float(a.get("confidence", 0.0)) < config.LOCAL_REVIEW_CONFIDENCE:
            candidates.append((2, a["start"] - 0.5, a["end"] + 0.5, [a["id"]], "low_confidence"))
    for p in (ctx.get("sampling") or {}).get("refinement", {}).get("proposals") or []:
        refs = [a["id"] for a in actions if a["end"] >= p["start_time"] and a["start"] <= p["end_time"]]
        candidates.append((3, p["start_time"], p["end_time"], refs, p["reason"]))
    for w in (ctx.get("windows") or {}).get("windows") or []:
        if str(w.get("missing_or_unclear") or "").strip():
            start, dur = w["window"]["start"], w["window"]["duration"]
            refs = [a["id"] for a in actions if a["end"] >= start and a["start"] <= start + dur]
            candidates.append((2, start, start + dur, refs, "model_reported_unclear"))
    proposals = []
    for priority, start, end, refs, reason in sorted(candidates):
        start, end = max(0, start), min(duration, end)
        end = min(end, start + config.LOCAL_REVIEW_MAX_SECONDS)
        if end <= start:
            continue
        existing = next((p for p in proposals if
                         min(end, p["end"]) - max(start, p["start"]) >=
                         0.6 * min(end - start, p["end"] - p["start"])), None)
        if existing:
            existing["reasons"] = sorted(set(existing["reasons"] + [reason]))
            existing["atomic_refs"] = sorted(set(existing["atomic_refs"] + refs))
        else:
            proposals.append({"id": f"review_{len(proposals)+1}", "start": round(start, 6),
                              "end": round(end, 6), "atomic_refs": refs,
                              "reasons": [reason], "priority": priority})
    for p in proposals[config.LOCAL_REVIEW_MAX_WINDOWS:]:
        p["status"] = "skipped_budget"
    return proposals


def validate(payload, proposal, frames):
    if not isinstance(payload, dict):
        raise ValueError("复查必须返回JSON对象")
    frame_map = {f["frame_id"]: f for f in frames}
    duration = proposal["end"] - proposal["start"]
    checks = payload.get("state_checks")
    missing = payload.get("missing_actions")
    if not isinstance(checks, list) or not isinstance(missing, list):
        raise ValueError("必须有state_checks和missing_actions数组")
    seen = set()
    for check in checks:
        if check.get("atomic_ref") not in proposal["atomic_refs"]:
            raise ValueError("复查状态引用了未提供的原子动作")
        if check.get("field") not in {"state_before", "state_after"} or check.get("status") not in {"observed", "unclear"}:
            raise ValueError("非法状态检查字段")
        key = (check["atomic_ref"], check["field"])
        if key in seen:
            raise ValueError("同一状态不能重复给出结论")
        seen.add(key)
        refs = check.get("evidence_frames") or []
        if not set(refs) <= frame_map.keys():
            raise ValueError("复查引用了不存在的帧")
        if check["status"] == "observed" and (not refs or not isinstance(check.get("state"), str) or not check["state"].strip()):
            raise ValueError("可见状态必须有真实帧引用和状态文字")
    if missing:
        s02b_atomic._validate({"atomic_actions": missing, "temporal_relations": []})
    for a in missing:
        refs = a.get("evidence_frames") or []
        if not refs or not set(refs) <= frame_map.keys() or a.get("inferred") or semantic.is_hold(a):
            raise ValueError("补回动作必须来自实际视频与提供的帧，不能是推断或保持")
        if a.get("executor") not in {"左臂", "右臂", "左手", "右手", "整体"}:
            raise ValueError("新增动作的主体不在允许范围")
        start, end = float(a["start"]), float(a["end"])
        if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start <= end <= duration:
            raise ValueError("新增动作时间必须位于复查片段内")
        actual = [frame_map[r]["timestamp"] for r in refs]
        if len(set(actual)) < 2:
            raise ValueError("新增动作至少需要两个不同时间的证据帧，单帧只能证明状态")
        if not any(proposal["start"] + start - 0.15 <= t <= proposal["start"] + end + 0.15 for t in actual):
            raise ValueError("新增动作引用的帧不在动作时间附近")


def apply(ctx, payload, proposal, frames):
    """Unknown states can gain visual evidence; contradictory observations are retained."""
    actions = ctx["atomic"]["atomic_actions"]
    amap = {a["id"]: a for a in actions}
    fmap = {f["frame_id"]: f for f in frames}
    result = {"state_updates": [], "added_refs": [], "conflicts": []}
    for check in payload["state_checks"]:
        if check["status"] != "observed":
            continue
        a = amap[check["atomic_ref"]]
        field, new = check["field"], check["state"].strip()
        old = observed_state(a, field)
        refs = [deepcopy(fmap[r]) for r in check["evidence_frames"]]
        # A before/after claim must cite frames at that action boundary.
        boundary = float(a["start"] if field == "state_before" else a["end"])
        in_scope = [f for f in refs if
                    (boundary - 0.75 <= f["timestamp"] <= boundary + 0.15 if field == "state_before"
                     else boundary - 0.15 <= f["timestamp"] <= boundary + 0.75)]
        if not in_scope:
            result["conflicts"].append({**check, "reason": "证据帧不在该状态边界附近"})
            continue
        if old and old != new:
            result["conflicts"].append({**check, "original_state": old, "reason": "与已有观测冲突，保留原证据"})
            continue
        if a.get("inferred"):
            result["conflicts"].append({**check, "reason": "不能仅凭状态帧把推断动作提升为已观测动作"})
            continue
        a[field] = new
        a[field + "_from"] = "observed"
        a.setdefault("visual_state_evidence", []).append(
            {"field": field, "state": new, "review_id": proposal["id"], "frames": in_scope})
        result["state_updates"].append({"atomic_ref": a["id"], "field": field})
    new_actions = s02b_atomic._normalize_window(
        {"atomic_actions": deepcopy(payload["missing_actions"]), "temporal_relations": []},
        proposal["end"] - proposal["start"])["atomic_actions"]
    for a in new_actions:
        a["start"] += proposal["start"]
        a["end"] += proposal["start"]
        if any(s02b_merge._similar(a, old) for old in actions):
            continue
        a["id"] = max((old["id"] for old in actions), default=0) + 1
        a["inferred"] = False
        a["origin"] = "video_local_review"
        a["review_id"] = proposal["id"]
        a["visual_evidence"] = [deepcopy(fmap[r]) for r in a["evidence_frames"]]
        actions.append(a)
        result["added_refs"].append(a["id"])
    actions.sort(key=lambda a: (a["start"], a["end"], a["id"]))
    if result["added_refs"]:
        ctx["relations"] = s02b_merge.add_boundary_relations(actions, ctx["relations"])
        ctx["atomic"]["temporal_relations"] = ctx["relations"]
    return result


def run(client, ctx):
    report = {"status": "disabled" if not config.LOCAL_REVIEW_ENABLED else "ok",
              "policy": "复查真实视频与帧；未知可补证，冲突保留；运动候选不当作动作",
              "proposals": [], "results": []}
    if not config.LOCAL_REVIEW_ENABLED:
        return report
    proposals = plan(ctx)
    report["proposals"] = proposals
    root = Path(ctx["out_dir"]) / "local_review"
    root.mkdir(parents=True, exist_ok=True)
    amap = {a["id"]: a for a in ctx["atomic"]["atomic_actions"]}
    for p in proposals[:config.LOCAL_REVIEW_MAX_WINDOWS]:
        directory = root / p["id"]
        directory.mkdir(exist_ok=True)
        try:
            frames = sampling.export_frames(Path(ctx["video"]), p["start"], p["end"], directory / "frames",
                                            fps=config.LOCAL_REVIEW_FPS, maximum=config.LOCAL_REVIEW_MAX_FRAMES)
            if len(frames) < 2:
                raise ValueError("复查可用帧不足，不能确认状态转换")
            targets = [amap[r] for r in p["atomic_refs"] if r in amap]
            clip = media.make_clip(Path(ctx["video"]), p["start"], p["end"] - p["start"],
                                   tag="local_review", fps=config.LOCAL_REVIEW_FPS)
            prompt = ("复查原因：" + "；".join(p["reasons"]) +
                      f"。源视频全局区间[{p['start']},{p['end']}]。待检查动作为全局时间：\n" +
                      json.dumps(targets, ensure_ascii=False) +
                      "\n对新增动作报告片段局部时间；不要重述已有动作，不按前置条件推断事实。")
            raw = client.ask(stage="s02r_" + p["id"], system=SYSTEM, user_text=prompt,
                             video=clip, images=frames, video_id=ctx["video_id"],
                             validator=lambda data, proposal=p, evidence=frames: validate(data, proposal, evidence),
                             attempts=2, max_tokens=6000)
            outcome = apply(ctx, raw, p, frames)
            saved = {"proposal": p, "frames": frames, "response": raw, "applied": outcome}
            sampling._save(directory / "review.json", saved)
            report["results"].append(saved)
            p["status"] = "reviewed"
        except Exception as exc:
            p["status"] = "failed"
            p["error"] = f"{type(exc).__name__}: {exc}"
            report["status"] = "partial"
    sampling._save(root / "review_report.json", report)
    return report
