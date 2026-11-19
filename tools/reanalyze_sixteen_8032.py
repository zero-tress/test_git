"""Fresh 16-video 8032 analysis with neutral filenames, bounded workers and resumable logs."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config, media, sampling, semantic
from video2op.llm import VLMClient
from video2op.single_video.pipeline import run_case
from video2op.skill_clips import save, sha256
from video2op.task_observations import attach, prediction_from_audit

ROOT = Path(__file__).resolve().parents[1]
TASK_REVISION = 2
TASK_SYSTEM = """你是独立的视频任务结果审阅员。只能依据本次提供的完整视频与真实源帧。
任务定义与目标对象只说明希望达成的效果，不是成功或已经执行的证明。黑色桌垫是A，白色桌面是B。
不要把物体最终停留的位置重新定义成B。初始已经在B不表示发生搬移；任务失败不表示局部抓取失败。
障碍存在、是否阻挡当前路径、抓持稳定性及过程掉落分别判断；遮挡、缺帧、含糊不清填U。
本项目attempted表示是否观察到目标盒子的搬移执行，而不是推测心理意图。仅伸手、接触、抓握而未观察到目标盒子平移、抬离或搬运，不算已执行搬移；明确未发生填F，无法判断填U。移动别的盒子不能代替目标盒子的搬移。\n目标初始已在B且未搬移时，最终目标状态可以为T而attempted为F；未搬移时method填None。\n输出严格JSON:
{"attempted":"T/F/U","final_region":"A/B/Other/Unknown","final_stationary":"T/F/U",
"hand_separated_final":"T/F/U","goal_satisfied_final":"T/F/U",
"method":"Push/Pull/GraspMove/GraspSlide/Mixed/None/Unknown","drop":"T/F/U",
"target_description":"实际目标及消歧依据",
"evidence":[{"field":"attempted/final_region/final_stationary/hand_separated_final/method/drop",
"truth":"T/F/U","evidence_frames":["提供的帧ID"],"reason":"画面依据"}],"uncertainty":[]}
每项确定判断引用所提供的帧。最终状态用末段证据，动作名、文件名和预期条件不能替代观察。"""


def selected_media(manifest):
    rows = [r for r in manifest["media"] if r.get("kind") == "current_case"]
    ids = [r["id"] for r in rows]
    if sorted(ids) != [f"{i:02d}" for i in range(1, 17)] or len({r["sha256"] for r in rows}) != 16:
        raise ValueError("Expected exactly 16 unique numbered dataset videos")
    return sorted(rows, key=lambda r: r["id"])


def endpoint_check():
    u = urlparse(config.BASE_URL)
    if u.hostname not in {"127.0.0.1", "localhost", "::1"} or u.port != 8032:
        raise ValueError("Only the existing authorized loopback 8032 service is accepted")


def configure(out, case_id):
    endpoint_check()
    config.OUTPUT_DIR = out / "raw_cases"
    config.WORK_DIR = out / "_work" / case_id
    config.MAX_ATTEMPTS = 3
    config.VIDEO_TIMEOUT = 300
    config.TEXT_TIMEOUT = 300
    import cv2

    cv2.setNumThreads(1)
    original = VLMClient.__init__

    def bounded(self, *args, **kwargs):
        original(self, *args, **kwargs)
        u = urlparse(self.base_url)
        if u.hostname not in {"127.0.0.1", "localhost", "::1"} or u.port != 8032:
            raise ValueError("Unexpected model endpoint")
        self.session.trust_env = False
        post = self.session.post
        self.session.post = lambda *a, **kw: post(*a, **{**kw, "allow_redirects": False})

    VLMClient.__init__ = bounded


def initialize(out):
    snapshot = out / "input_snapshot.json"
    if snapshot.exists():
        data = json.loads(snapshot.read_text())
        for r in data["media"]:
            if sha256(r["source"]) != r["sha256"] or sha256(r["neutral_video"]) != r["sha256"]:
                raise ValueError("Source identity changed")
        return data
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("New run requires an empty output directory")
    rows = selected_media(json.loads((ROOT / "eval/manifest.json").read_text()))
    annotations = json.loads((ROOT / "data/16段视频_命名标注/标注数据.json").read_text())["视频标注"]
    by_id = {r["编号"]: r for r in annotations}
    out.mkdir(parents=True)
    neutral = out / "input_videos"
    neutral.mkdir()
    for r in rows:
        if sha256(r["source"]) != r["sha256"]:
            raise ValueError("Original video changed: " + r["id"])
        target = neutral / ("video_" + r["id"] + ".mp4")
        shutil.copy2(r["source"], target)
        r["neutral_video"] = str(target)
        # Only task definition and target identity enter prompts; no outcome/method/obstacle reference label.
        ann = by_id[r["id"]]
        r["task_context"] = {
            "statement": ann["指派任务"],
            "target_description": ann["物体"],
            "source_region": "黑色桌垫 A",
            "destination": "白色桌面 B",
        }
    current = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    data = {
        "schema_version": "fresh_dataset_analysis.v1",
        "created": datetime.now().astimezone().isoformat(),
        "source_commit": current,
        "model": config.MODEL,
        "endpoint": config.BASE_URL,
        "media": rows,
        "policy": "Fresh per-stage model analysis. Historical labels remain outside prompts and model outputs.",
    }
    save(snapshot, data)
    (out / "logs").mkdir()
    (out / "status").mkdir()
    return data


def validate_task(obj, frames):
    if not isinstance(obj, dict):
        raise ValueError("Task audit must be an object")
    for key in ["attempted", "final_stationary", "hand_separated_final", "goal_satisfied_final", "drop"]:
        if obj.get(key) not in {"T", "F", "U"}:
            raise ValueError("Invalid task truth: " + key)
    if obj.get("final_region") not in {"A", "B", "Other", "Unknown"}:
        raise ValueError("Invalid final region")
    if obj.get("method") not in {"Push", "Pull", "GraspMove", "GraspSlide", "Mixed", "None", "Unknown"}:
        raise ValueError("Invalid method")
    ids = {f["frame_id"] for f in frames}
    if not isinstance(obj.get("evidence"), list):
        raise ValueError("Missing task evidence")
    for e in obj["evidence"]:
        if not set(e.get("evidence_frames", [])) <= ids:
            raise ValueError("Invented evidence frame")
        if e.get("truth") != "U" and not e.get("evidence_frames"):
            raise ValueError("Asserted task fact lacks frames")


def worker(out, row, resume):
    case_id = row["id"]
    configure(out, case_id)
    video = Path(row["neutral_video"])
    case = out / "raw_cases" / ("video_" + case_id + "_semantic_v3")
    state = out / "status" / (case_id + ".json")
    previous = json.loads(state.read_text()) if state.exists() else {}
    attempt = previous.get("attempt", 0) + 1

    def status(phase, **extra):
        save(
            state,
            {
                "case_id": case_id,
                "video_uid": row["sha256"],
                "split": row["split"],
                "phase": phase,
                "pid": os.getpid(),
                "attempt": attempt,
                "task_protocol_revision": TASK_REVISION,
                "updated": time.time(),
                **extra,
            },
        )

    try:
        status("analysis")
        file = case / "result.json"
        if resume and file.exists() and (case / "performance.json").exists():
            b = json.loads(file.read_text())
            if b["source_video_sha256"] != row["sha256"]:
                raise ValueError("Resume case has wrong video")
        else:
            context = "用户提供任务定义（不代表实际发生）：" + json.dumps(row["task_context"], ensure_ascii=False)
            b = run_case(video, force=not resume, description=context, export_clips=False)
        save(out / "analysis_metrics" / (case_id + ".json"), b["pipeline"])
        if b.get("errors"):
            raise ValueError("Pipeline recorded errors")
        status("task_audit", analysis_validation=b["validation"]["summary"])
        folder = out / "task_audits_v2" / case_id
        folder.mkdir(parents=True, exist_ok=True)
        result = folder / "result.json"
        if resume and result.exists():
            audit = json.loads(result.read_text())["response"]
        else:
            frames = sampling.export_frames(video, 0, b["meta"]["duration"], folder / "frames", fps=4, maximum=6)
            for f in frames:
                f["frame_id"] = row["sha256"][:10] + "_" + f["frame_id"]
            save(
                folder / "inputs.json", {"frames": frames, "task_context": row["task_context"], "system": TASK_SYSTEM}
            )
            old_width, old_fps = config.CLIP_WIDTH, config.CLIP_FPS
            config.CLIP_WIDTH, config.CLIP_FPS = 512, 4
            clip = media.make_clip(video, 0, b["meta"]["duration"], tag="independent_task_audit")
            config.CLIP_WIDTH, config.CLIP_FPS = old_width, old_fps
            client = VLMClient(folder / "cache", use_cache=resume)
            audit = client.ask(
                stage="fresh_task_audit_" + case_id,
                system=TASK_SYSTEM,
                user_text=json.dumps(row["task_context"], ensure_ascii=False),
                video=clip,
                images=frames,
                video_id=row["sha256"],
                max_tokens=4096,
                attempts=2,
                timeout=300,
                validator=lambda x: validate_task(x, frames),
            )
            save(
                result,
                {
                    "response": audit,
                    "frames": frames,
                    "model_stats": client.stats,
                    "source_video_uid": row["sha256"],
                    "human_verified": False,
                },
            )
        contract = {
            "goal_key": "relocate_and_release",
            "statement": row["task_context"]["statement"],
            "source_region": row["task_context"]["source_region"],
            "destination": row["task_context"]["destination"],
            "origin": "provided_dataset_task_definition_only",
        }
        prediction = prediction_from_audit(audit, row["sha256"], contract, str(result))
        prediction.update(case_id=case_id, split=row["split"], target_description=audit.get("target_description"))
        save(folder / "prediction.json", prediction)
        attach(b, prediction)
        b["semantic_graph"]["task_intent"] = contract["statement"]
        b["semantic_graph"]["x-meta"]["provided_task_contract"] = contract
        b["semantic_graph"]["x-meta"]["task_observation"] = prediction
        b["validation"] = semantic.validate(b)
        interpreted = out / "interpreted_cases" / case.name
        semantic.export(b, interpreted, export_clips=False)
        semantic.render(b, interpreted)
        file = interpreted / "result.json"
        status("local_skill_review")
        reviews = out / "local_reviews_v2" / case_id
        if not (resume and (reviews / "results.json").exists()):
            command = [
                sys.executable,
                "-u",
                "-B",
                str(ROOT / "tools/review_contrastive_skills.py"),
                "--inputs",
                str(file),
                "--out",
                str(reviews),
                "--allow-8032",
                "--split",
                row["split"],
            ]
            subprocess.run(command, cwd=ROOT, check=False)
        review = json.loads((reviews / "results.json").read_text())
        status(
            "complete",
            result=str(file),
            task_outcome=prediction["outcome"],
            analysis_model_calls=b["pipeline"]["llm_stats"]["calls"],
            review_status=review["records"][0]["status"],
            validation=b["validation"]["summary"],
        )
        if sha256(row["source"]) != row["sha256"]:
            raise ValueError("Original source changed")
        return 0
    except Exception as exc:
        traceback.print_exc()
        error = {
            "type": type(exc).__name__,
            "message": str(exc),
            "raw_outputs": getattr(exc, "raw", []),
            "model_errors": getattr(exc, "errors", []),
        }
        save(out / "failures" / (case_id + f"_attempt_{attempt}.json"), error)
        status("failed", error=error)
        return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ids", nargs="+")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--worker")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--allow-8032", action="store_true")
    args = ap.parse_args(argv)
    if not args.allow_8032:
        ap.error("Explicit authorization for existing 8032 is required")
    endpoint_check()
    out = args.out.resolve()
    data = initialize(out)
    rows = data["media"]
    if args.worker:
        row = next(r for r in rows if r["id"] == args.worker)
        return worker(out, row, args.resume)
    ids = args.ids or [r["id"] for r in rows]
    if not set(ids) <= {r["id"] for r in rows}:
        ap.error("Unknown video IDs")
    if not 1 <= args.workers <= 4:
        ap.error("Use 1 to 4 bounded workers")

    def one(row):
        case_id = row["id"]
        status_file = out / "status" / (case_id + ".json")
        if (
            args.resume
            and status_file.exists()
            and json.loads(status_file.read_text()).get("phase") == "complete"
            and json.loads(status_file.read_text()).get("task_protocol_revision") == TASK_REVISION
        ):
            return {"case_id": case_id, "exit_code": 0, "resumed_completed": True}
        log = out / "logs" / (case_id + "_" + datetime.now().strftime("%H%M%S_%f") + ".log")
        command = [
            sys.executable,
            "-u",
            "-B",
            str(Path(__file__).resolve()),
            "--out",
            str(out),
            "--worker",
            case_id,
            "--allow-8032",
        ]
        if args.resume:
            command.append("--resume")
        env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        try:
            with log.open("w") as f:
                proc = subprocess.run(
                    command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, text=True, env=env, timeout=1080
                )
            return {"case_id": case_id, "exit_code": proc.returncode, "log": str(log)}
        except subprocess.TimeoutExpired:
            return {
                "case_id": case_id,
                "exit_code": 124,
                "log": str(log),
                "error": "Bounded worker timeout; resume this run's new cache",
            }

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(one, r) for r in rows if r["id"] in ids]
        for future in as_completed(futures):
            row = future.result()
            results.append(row)
            save(out / "batch_results" / ("_".join(ids) + ".json"), results)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    return int(any(r["exit_code"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
