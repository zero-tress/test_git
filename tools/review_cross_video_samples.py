"""Three bounded local-model reviews. Requires explicit network authorization."""
import argparse
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video2op import config, sampling
from video2op.cross_video_delivery import save
from video2op.llm import LLMError, VLMClient
from video2op.skill_clips import sha256

SYSTEM = """你是视频证据复核员。仅根据提供的视频/真实帧报告可见事实。技能名称和给定目标是待验证的任务定义，不是观察结果。
不同case_id的帧来自不同视频，不得混为连续过程。所有时间为源视频全局时间；只有所附视频片段使用局部时间。
只对有直接画面依据的命题给T或F；遮挡、帧间遗漏、时间范围不足时给U。静态手形不证明发生了抓握转换，物体在桌面不证明可达。
同一任务目的、观察到相同效果、采用相同方法必须分开判断。不从结果倒推必要条件，不输出已证实的因果规律。
输出JSON，包含：
{"observations":[{"case_id":"01","claims":[{"claim":"命题","truth":"T/F/U","evidence_frames":["提供的frame_id"],"reason":"画面依据或不确定性"}]}],
"comparison":{"same_semantic_goal":"T/F/U","same_observed_effect":"T/F/U","same_method":"T/F/U","boundary_sufficient":"T/F/U","evidence_frames":[],"reason":"分别说明"},
"suggested_boundaries":[{"case_id":"01","start":0.0,"end":1.0,"evidence_frames":[]}],
"missing_evidence":["还缺什么"]}
只使用提供的case_id和frame_id。没有足够依据时边界建议列表可为空；禁止为了满足预期而给出合并结论。"""


def validate(result, cases, frames, durations):
    allowed = {f["frame_id"] for f in frames}
    def refs(row, case=None):
        values = row.get("evidence_frames", [])
        if not isinstance(values, list) or not set(values) <= allowed:
            raise ValueError("Unknown frame reference")
        if case and any(not f.startswith("case_"+case+"_") for f in values):
            raise ValueError("Cross-video evidence attached to a local claim")
        return values
    if not isinstance(result, dict) or not isinstance(result.get("observations"), list):
        raise ValueError("Missing observations")
    for row in result["observations"]:
        if row.get("case_id") not in cases:
            raise ValueError("Unknown case")
        for claim in row.get("claims", []):
            if claim.get("truth") not in {"T", "F", "U"}:
                raise ValueError("Invalid truth")
            if claim["truth"] != "U" and not refs(claim, row["case_id"]):
                raise ValueError("Asserted truth requires actual frames")
            refs(claim, row["case_id"])
    comparison = result["comparison"]
    for key in ["same_semantic_goal", "same_observed_effect", "same_method", "boundary_sufficient"]:
        if comparison.get(key) not in {"T", "F", "U"}:
            raise ValueError("Invalid comparison status")
    if any(comparison[k] != "U" for k in ["same_observed_effect", "same_method", "boundary_sufficient"]) and not refs(comparison):
        raise ValueError("Comparison requires frames")
    refs(comparison)
    for row in result.get("suggested_boundaries", []):
        case = row["case_id"]
        if case not in cases:
            raise ValueError("Unknown boundary case")
        start, end = float(row["start"]), float(row["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= durations[case]):
            raise ValueError("Boundary outside source")
        refs(row, case)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--allow-local-model", action="store_true")
    ap.add_argument("--retry-failed-from", type=Path, help="只重试指定记录中的失败样例，保留原始失败记录")
    args = ap.parse_args(argv)
    parsed = urlparse(config.BASE_URL)
    if not args.allow_local_model or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.scheme not in {"http", "https"}:
        ap.error("Requires explicit permission; only configured loopback model endpoint is accepted")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        ap.error("Use a new output directory; the three-call budget cannot be silently retried")
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.clips.read_text())
    selected = {(r["case_id"], r["goal_key"]): r for r in manifest["instances"] if r["kind"] == "skills"}
    durations = {r["case_id"]: r["duration"] for r in manifest["videos"]}
    jobs = [("boundary_grasp_01", [("01", "grasp_object")], "核对抓取片段的起止范围是否足够观察抓取前后状态，给出有依据的修正建议。"),
            ("grasp_comparison_01_07", [("01", "grasp_object"), ("07", "grasp_object")], "比较两个抓取实例的动作和可见后状态，判断是否支持同一抓取语义效果；不要仅凭相同技能标签给结论。"),
            ("function_comparison_05_08", [("05", "relocate_and_release"), ("08", "relocate_and_release")], "比较两例搬移任务：给定目标是目标物体到达指定区域、静止且与手分离。分别核对过程做法与可见结果，判断是否支持同一功能的不同实现；缺少目标区域定义时保留U。")]
    previous_failures = None
    if args.retry_failed_from:
        previous = json.loads(args.retry_failed_from.read_text())
        previous_failures = {j["name"] for j in previous["results"] if j["status"] == "failed"}
        jobs = [job for job in jobs if job[0] in previous_failures]
    client = VLMClient(out/"cache", use_cache=False)
    client.session.trust_env = False
    actual_post = client.session.post
    client.session.post = lambda *a, **kw: actual_post(*a, **{**kw, "allow_redirects": False})
    results = []
    for name, specs, question in jobs:
        images, descriptions = [], []
        for case, goal in specs:
            row = selected[(case, goal)]
            if row["split"] != "development":
                raise ValueError("Only development samples may be reviewed here")
            if sha256(row["source_video"]) != row["source_sha256"]:
                raise ValueError("Source changed")
            start = max(0., min(i["start"] for i in row["core_intervals"]) - .5)
            end = min(durations[case], max(i["end"] for i in row["core_intervals"]) + .5)
            frames = sampling.export_frames(Path(row["source_video"]), start, end, out/name/("case_"+case), fps=4, maximum=3 if len(specs) > 1 else 6)
            for f in frames:
                f["frame_id"] = "case_"+case+"_"+f["frame_id"]
                f["case_id"] = case
            images.extend(frames)
            descriptions.append({"case_id": case, "declared_goal": row["goal_key"], "candidate_intervals": row["core_intervals"],
                                 "provided_context_interval": [start, end],
                                 "frame_ids": [f["frame_id"] for f in frames]})
        prompt = question+"\n任务/候选边界（不是观测真值）：\n"+json.dumps(descriptions, ensure_ascii=False)
        job = {"name": name, "cases": [c for c, _ in specs], "frames": images, "prompt": prompt,
               "system": SYSTEM, "status": "pending", "provenance": "additional_model_review_candidate",
               "human_verified": False, "causally_verified": False}
        save(out/name/"inputs.json", job)
        try:
            response = client.ask(stage=name, system=SYSTEM, user_text=prompt, images=images,
                                  video_id=name, max_tokens=4096, attempts=1, timeout=240,
                                  validator=lambda obj, cases=job["cases"], frames=images: validate(obj, cases, frames, durations))
            job.update(status="completed", response=response)
            print(name+" completed", flush=True)
        except LLMError as exc:
            job.update(status="failed", errors=exc.errors, raw_outputs=exc.raw)
            print(name+" failed", flush=True)
        results.append(job)
        save(out/"results.json", {"results": results, "model_stats": client.stats,
                                  "endpoint_scope": "configured_loopback_only_no_redirects",
                                  "maximum_calls": len(jobs), "retry_failed_from": str(args.retry_failed_from) if args.retry_failed_from else None,
                                  "updates_applied_to_learning": False})
    return 0 if all(r["status"] == "completed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
