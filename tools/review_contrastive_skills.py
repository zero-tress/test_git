"""Review local goals and complete episodes against source videos; loopback 8032 only."""

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config, media, sampling
from video2op.contrastive_learning import units_for_review
from video2op.llm import LLMError, VLMClient
from video2op.skill_clips import save, sha256
from video2op.skill_episodes import build

SYSTEM = """你是操作视频正反例证据审阅员。只判断实际画面与给出的本视频动作，不接受文件名、旧结果标签或预期效果作为成功证明。给定bindings中的destination是固定目标，不得用最终停留地点改写；provided_task作用域尤其必须逐项核验给定目标。
一个视频中不同子技能分别判断。整段搬移失败不表示其中抓取失败；未执行不表示条件为假。
抓取=建立稳定握持，不要求抬离桌面；普通接触、手覆盖物体或静态手形不自动证明稳定握持。可看后续手物共同运动提供证据。
技能过程包括相关准备直到目标效果的里程碑；不要把之后的搬运塞入抓取过程。其他对象的动作只有直接证据说明准备关系时才可加入。
前置条件entry必须在该过程开始前或开始瞬间可见；core_entry只属于抓握动作开始前的中间条件，不能升级为整个抓取过程入口条件。
遮挡、缺帧、范围不够、目标区域定义不清均填U。反事实猜想不是负例。时间全部用源视频全局秒数；视频是从0秒开始的完整分析版。
输出严格JSON：
{"unit_reviews":[{"instance_id":"输入ID","scope_verdict":"supported/ambiguous/requires_extension/rejected",
"preparation_atomic_refs":[],"attempted":"T/F/U","goal_satisfied":"T/F/U",
"outcome_evidence_frames":[],"outcome_reason":"实际观察依据/缺口",
"conditions":[{"predicate":"holding/stable_holding/hand_open/gripper_empty/accessible/at_grasp_position/at_destination/stationary/supported",
"phase":"entry/core_entry/post","truth":"T/F/U","at_sec":0.0,"evidence_frames":[],"reason":"证据依据"}]}],
"causal_reviews":[{"from":"输入节点","to":"输入节点","predicate_ref":"输入条件ID","verdict":"supported/contradicted/unknown","evidence_frames":[],"reason":"前步效果是否支持后步条件，不声称因果必要性"}],
"unresolved":[]}
每个unit最多5条条件；每个视频最多3条因果复核。T/F必须引用提供的帧ID；U可无引用。只引用已有动作ID，不创造动作或未提供的图边。"""


def validate(response, units, frames, edges, actions):
    if not isinstance(response, dict) or not isinstance(response.get("unit_reviews"), list):
        raise ValueError("Missing unit_reviews")
    allowed_frames = {f["frame_id"] for f in frames}
    ids = {i["instance_id"] for i in units}
    seen = set()
    for row in response["unit_reviews"]:
        if row.get("instance_id") not in ids or row["instance_id"] in seen:
            raise ValueError("Unknown or duplicate unit ID")
        seen.add(row["instance_id"])
        if row.get("scope_verdict") not in {"supported", "ambiguous", "requires_extension", "rejected"}:
            raise ValueError("Invalid scope verdict")
        if row.get("attempted") not in {"T", "F", "U"} or row.get("goal_satisfied") not in {"T", "F", "U"}:
            raise ValueError("Invalid local outcome")
        if not set(row.get("outcome_evidence_frames", [])) <= allowed_frames:
            raise ValueError("Unknown outcome frame")
        if (row["attempted"] != "U" or row["goal_satisfied"] != "U") and not row.get("outcome_evidence_frames"):
            raise ValueError("Asserted result has no evidence frame")
        if not set(row.get("preparation_atomic_refs", [])) <= actions:
            raise ValueError("Invented preparation action")
        for fact in row.get("conditions", []):
            if fact.get("truth") not in {"T", "F", "U"} or fact.get("phase") not in {"entry", "core_entry", "post"}:
                raise ValueError("Invalid condition status")
            if not set(fact.get("evidence_frames", [])) <= allowed_frames:
                raise ValueError("Unknown condition frame")
            if fact["truth"] != "U" and not fact.get("evidence_frames"):
                raise ValueError("Condition has no visual evidence")
    for row in response.get("causal_reviews", []):
        key = (row.get("from"), row.get("to"))
        if key not in edges or row.get("predicate_ref") not in edges[key]:
            raise ValueError("Invented causal edge or target condition")
        if row.get("verdict") not in {"supported", "contradicted", "unknown"}:
            raise ValueError("Invalid causal verdict")
        if not set(row.get("evidence_frames", [])) <= allowed_frames:
            raise ValueError("Unknown causal frame")
        if row["verdict"] != "unknown" and not row.get("evidence_frames"):
            raise ValueError("Causal opinion has no frames")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "output/current")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--inputs", nargs="+", type=Path, help="Only these saved cases; no historical holdout references")
    ap.add_argument("--allow-8032", action="store_true")
    ap.add_argument(
        "--goal",
        choices=["acquire_object", "relocate_object", "place_object", "clear_access", "relocate_and_release"],
    )
    ap.add_argument("--target-category")
    args = ap.parse_args(argv)
    endpoint = urlparse(config.BASE_URL)
    if not args.allow_8032 or endpoint.hostname not in {"127.0.0.1", "localhost", "::1"} or endpoint.port != 8032:
        ap.error("Explicit authorization for existing loopback 8032 required")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        ap.error("Use a new directory to preserve previous reviews")
    out.mkdir(parents=True)
    source = args.source.resolve()
    sources = sorted((source / "knowledge_development/cases").glob("*/result.json"))
    sources += sorted((source / "holdout_observations/cases").glob("*/result.json"))
    if args.inputs:
        sources = [(p / "result.json" if p.is_dir() else p).resolve() for p in args.inputs]
    if not sources:
        ap.error("No saved analyses found")
    config.WORK_DIR = out / "_model_clips"
    config.CLIP_WIDTH = 512
    config.CLIP_FPS = 4
    provided_goal = (
        {"goal_key": args.goal, "target_category": args.target_category, "origin": "user_provided_goal"}
        if args.goal
        else None
    )
    client = VLMClient(out / "cache", use_cache=False)
    client.session.trust_env = False
    actual_post = client.session.post
    client.session.post = lambda *a, **kw: actual_post(*a, **{**kw, "allow_redirects": False})
    records = []
    # Persist every input before model calls; no reference outcomes are sent.
    for index, p in enumerate(sources, 1):
        b = json.loads(p.read_text())
        split = "holdout" if "holdout_observations" in p.parts else "development"
        uid = b["source_video_sha256"]
        source_video = Path(b["meta"]["path"])
        if sha256(source_video) != uid:
            raise ValueError("Source bytes changed")
        _case, units = units_for_review(b, str(p), provided_goal)
        episode_data = build(b, str(p))
        if provided_goal:
            units = [
                u
                for u in units
                if u["instance_scope"] == "purpose_task"
                or (u["goal_key"] == "grasp_object" and u["target"]["category"] == args.target_category)
            ]
        for unit in units:
            unit["analysis_source"] = str(p)
            unit["entity_context"] = deepcopy(b.get("semantic_scope", {}).get("objects", []))
            if "boundary" not in unit:
                observed = unit["observed_process"]
                unit["boundary"] = {
                    "start_sec": min(a["start"] for a in observed),
                    "end_sec": max(a["end"] for a in observed),
                    "context_end_sec": min(b["meta"]["duration"], max(a["end"] for a in observed) + 0.5),
                }
        folder = out / split / (f"{index:02d}_" + b["meta"]["name"])
        folder.mkdir(parents=True)
        frames = sampling.export_frames(source_video, 0, b["meta"]["duration"], folder / "frames", fps=4, maximum=6)
        # Add true pre-grasp and immediate post-grasp evidence rather than relying on sparse whole-video frames.
        for unit in units:
            if unit["goal_key"] != "grasp_object":
                continue
            core = [a for a in unit["observed_process"] if a["id"] in unit["core_atomic_refs"]]
            for moment in [
                max(0, min(a["start"] for a in core) - 0.05),
                max(a["end"] for a in core) + 0.05,
                min(b["meta"]["duration"], max(a["end"] for a in core) + 0.45),
            ]:
                frames += sampling.export_frames(
                    source_video,
                    moment,
                    min(b["meta"]["duration"], moment + 0.02),
                    folder / "frames",
                    fps=4,
                    maximum=2,
                )
        frames = list({f["frame_id"]: f for f in frames}.values())
        frames = sorted(frames, key=lambda f: f["timestamp"])
        if len(frames) > 6:
            frames = [frames[round(i * (len(frames) - 1) / 5)] for i in range(6)]
        for f in frames:
            f["frame_id"] = uid[:10] + "_" + f["frame_id"]
        packet_units = [
            {
                k: deepcopy(u[k])
                for k in [
                    "instance_id",
                    "goal_key",
                    "target",
                    "bindings",
                    "instance_scope",
                    "atomic_refs",
                    "boundary",
                ]
            }
            for u in units
        ]
        for row, u in zip(packet_units, units, strict=True):
            row["expected_effects"] = u["expected"]["expected_effects"]
            row["core_atomic_refs"] = u.get("core_atomic_refs", u["atomic_refs"])
        graph = b["semantic_graph"]
        edges = {
            (e["from"], e["to"]): set(graph["nodes"][e["to"]]["skill"]["C_pre"])
            for e in graph["relations"]
            if e["from"] not in {"START", "END"} and e["to"] not in {"START", "END"}
        }
        causal = episode_data["task_causal_audit"]
        packet = {
            "units": packet_units,
            "actions": [
                {
                    k: a.get(k)
                    for k in [
                        "id",
                        "executor",
                        "action",
                        "object",
                        "start",
                        "end",
                        "state_before",
                        "state_after",
                        "world_before",
                        "world_after",
                        "inferred",
                    ]
                }
                for a in b["atomic"]["atomic_actions"]
            ],
            "causal_candidates": causal["edges"][:3],
            "predicates": graph["predicates"],
            "task_definition": provided_goal or b.get("provided_task_contract"),
        }
        prompt = "请核验本视频的局部目标、准备过程、条件与因果桥梁。没有相应技能实例时不创造。\n" + json.dumps(
            packet, ensure_ascii=False
        )
        save(
            folder / "inputs.json",
            {
                "source_analysis": str(p),
                "source_sha256": uid,
                "units": units,
                "frames": frames,
                "packet": packet,
                "system": SYSTEM,
                "prompt": prompt,
                "split": split,
            },
        )
        record = {
            "video_uid": uid,
            "split": split,
            "source_analysis": str(p),
            "provided_goal": provided_goal,
            "input_file": str(folder / "inputs.json"),
            "units": units,
            "frames": frames,
            "task_causal_audit": causal,
            "original_task_observation": deepcopy(b.get("task_observation")),
            "provenance": "additional_model_review_candidate",
            "human_verified": False,
        }
        if not units:
            record.update(status="no_local_units", response={"unit_reviews": [], "causal_reviews": []})
        else:
            clip = media.make_clip(source_video, 0, b["meta"]["duration"], tag="contrastive_review")
            try:
                response = client.ask(
                    stage="contrast_" + uid[:12],
                    system=SYSTEM,
                    user_text=prompt,
                    video=clip,
                    images=frames,
                    video_id=uid,
                    max_tokens=6144,
                    attempts=1,
                    timeout=300,
                    validator=lambda obj, us=units, fs=frames, es=edges, acs={a["id"] for a in b["atomic"]["atomic_actions"]}: (
                        validate(obj, us, fs, es, acs)
                    ),
                )
                record.update(status="completed", response=response)
            except LLMError as exc:
                record.update(status="failed", errors=exc.errors, raw_outputs=exc.raw)
        records.append(record)
        save(folder / "result.json", record)
        save(
            out / "results.json",
            {
                "records": records,
                "model_stats": client.stats,
                "source_root": str(source),
                "maximum_model_calls": len(sources),
                "policy": "Local goal outcomes and graph bridges remain model evidence, not human verification.",
            },
        )
        print(split + "/" + b["meta"]["name"] + " " + record["status"], flush=True)
    return 1 if any(r["status"] == "failed" for r in records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
