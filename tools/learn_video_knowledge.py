"""通过已配置的 8032 模型服务运行单视频与跨视频学习。"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import learn_semantic_graph
from video2op import config, llm
from video2op.contracts.learning_contracts import (
    CASE_SYSTEM,
    fingerprint,
    policy_prompt,
    source_fingerprint,
    task_contract,
)
from video2op.single_video import case_graph
from video2op.single_video.case_scope_review import SCOPE_SYSTEM
from video2op.single_video.pipeline import run_case


def save(path: Path | str, obj: dict) -> None:
    """保存批次、阶段或结果字典，供后续读取与排查。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_arguments(argv):
    """定义批量学习命令和续跑选项。"""
    parser = argparse.ArgumentParser(description="8032单视频特例学习及跨视频语义操作图")
    parser.add_argument("--videos", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--description", type=Path, help="任务背景；不会作为已发生事实")
    parser.add_argument("--graph-requirements", type=Path,
                        help="显式任务图政策JSON；随 s09 一起传入，仅作用于本批次")
    parser.add_argument("--allow-8032", action="store_true")
    parser.add_argument("--resume", action="store_true", help="仅续跑输入及来源hash一致的本批次")
    parser.add_argument("--refresh-prompts", action="store_true",
                        help="提示词更新后允许续跑；已完成实例只重新导出本地视图，不重复调用模型")
    parser.add_argument("--refresh-case-graph", action="store_true",
                        help="仅用已保存的视频观察重新学习 s09 G_case（不重跑抽样/意图/动作阶段），随后重跑跨视频")
    return parser, parser.parse_args(argv)


def create_run_manifest(videos, description, requirements):
    """记录源视频、模型、声明和源码的指纹，供续跑时核对。"""
    manifest = {
        "schema_version": "video_learning_run.v1",
        "created": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "model": config.MODEL, "endpoint": config.BASE_URL,
        "analysis_origin": "deployed_model", "status": "running", "cases": [],
        "execution_enabled": False,
        "code_sha256": source_fingerprint(),
    }
    for video in videos:
        manifest["cases"].append({
            "video": str(video), "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "status": "pending",
        })
    manifest["description_sha256"] = hashlib.sha256((description or "").encode()).hexdigest()
    manifest["task_contract"] = task_contract(requirements, description)
    manifest["case_prompt_fingerprint"] = fingerprint([SCOPE_SYSTEM, CASE_SYSTEM, policy_prompt(requirements)])
    manifest["graph_requirements_sha256"] = (hashlib.sha256(json.dumps(requirements, ensure_ascii=False, sort_keys=True)
                                                              .encode()).hexdigest() if requirements is not None else None)
    return manifest


def resume_run(args, parser, output, manifest):
    """核对续跑输入，返回可继续写入的原批次清单。"""
    saved = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    expected = [(r["video"], r["video_sha256"]) for r in manifest["cases"]]
    actual = [(r["video"], r["video_sha256"]) for r in saved["cases"]]
    if (expected != actual or saved["model"] != config.MODEL
            or saved["endpoint"] != config.BASE_URL
            or saved.get("description_sha256") != manifest["description_sha256"]):
        parser.error("输入、模型或任务背景已改变，不能续跑；请另建输出目录")
    saved_policy = saved.get("graph_requirements_sha256")
    new_policy = manifest["graph_requirements_sha256"]
    if saved_policy != new_policy:
        if not args.refresh_case_graph:
            parser.error("任务图政策已改变；请加 --refresh-case-graph 重跑 s09 与跨视频阶段，或另建输出目录")
        history = saved.get("previous_graph_requirements_sha256")
        saved["previous_graph_requirements_sha256"] = (history if isinstance(history, list) else []) + [saved_policy]
        saved["graph_requirements_sha256"] = new_policy
        saved["policy_refresh"] = "graph requirements changed; s09 and cross-video stages rerun"
    if saved.get("code_sha256") != manifest["code_sha256"] and not args.refresh_prompts:
        parser.error("源码版本改变；请显式 --refresh-prompts 或使用新目录")
    if saved.get("case_prompt_fingerprint") != manifest["case_prompt_fingerprint"] and not args.refresh_case_graph:
        parser.error("单视频契约/提示改变；请 --refresh-case-graph 或使用新目录")
    saved["code_sha256"] = manifest["code_sha256"]
    saved["case_prompt_fingerprint"] = manifest["case_prompt_fingerprint"]
    saved["task_contract"] = manifest["task_contract"]
    saved["status"] = "running"
    saved.pop("error", None)
    return saved


def refresh_case_graph(source, row, manifest_path, manifest, requirements, description):
    """从冻结的观察结果重新学习 s09，更新该视频的阶段文件和清单记录。"""
    if not source.is_file():
        raise RuntimeError("缺少已保存的 result.json，无法只重跑 G_case")
    if hashlib.sha256(source.read_bytes()).hexdigest() != row.get("result_sha256"):
        raise RuntimeError("已完成来源结果被修改，拒绝覆盖刷新")
    bundle = json.loads(source.read_text(encoding="utf-8"))
    history = source.parent / "history" / row["result_sha256"]
    history.mkdir(parents=True, exist_ok=True)
    # 按原结果哈希保留旧阶段与导出物，便于追溯刷新前的结论。
    for filename in ["result.json", "G_case.json", "G_case.svg", "stages/s09_case_graph.json"]:
        old = source.parent / filename
        if old.is_file():
            target = history / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(old.read_bytes())
    if not bundle.get("observed_operation_graph"):
        raise RuntimeError("缺少冻结观察分支，不能只重跑 G_case")
    client = llm.VLMClient(source.parent / "cache", base_url=config.BASE_URL, model=config.MODEL)
    try:
        row["status"] = "running"
        save(manifest_path, manifest)
        bundle["task_contract"] = task_contract(requirements, description)
        bundle["case_graph"] = case_graph.learn(client, bundle, requirements)
        bundle.setdefault("pipeline", {})["case_graph_refresh_stats"] = client.stats
        stats = bundle["pipeline"].get("llm_stats") or {}
        for key in ["calls", "cache_hits", "failures", "seconds"]:
            stats[key] = stats.get(key, 0) + client.stats[key]
        stats["attempts"] = stats.get("attempts", []) + client.stats["attempts"]
        bundle["pipeline"]["llm_stats"] = stats
        save(source.parent / "stages/s09_case_graph.json", bundle["case_graph"])
        case_graph.export(bundle, source.parent)
        save(source, bundle)
    finally:
        client.session.close()
    row.update(status="complete", result=str(source),
               result_sha256=hashlib.sha256(source.read_bytes()).hexdigest())


def run_single_video_cases(args, manifest_path, manifest, videos, description, requirements):
    """按视频生成或复用 G_case，返回跨视频学习所需的 result.json 路径。"""
    source_results = []
    for row, video in zip(manifest["cases"], videos, strict=True):
        source = config.OUTPUT_DIR / (video.stem + "_semantic_v3") / "result.json"
        if args.resume and row["status"] == "complete" and not args.refresh_case_graph:
            if (not source.is_file()
                    or hashlib.sha256(source.read_bytes()).hexdigest() != row.get("result_sha256")):
                raise RuntimeError("已完成实例被修改，不能静默续跑")
            # 续跑已完成案例时，从保存的模型结果重新导出视图。
            bundle = json.loads(source.read_text(encoding="utf-8"))
            if bundle.get("case_graph"):
                case_graph.export(bundle, source.parent)
            source_results.append(str(source))
            continue
        if args.resume and row["status"] == "complete" and args.refresh_case_graph:
            refresh_case_graph(source, row, manifest_path, manifest, requirements, description)
            source_results.append(str(source))
            save(manifest_path, manifest)
            continue
        row["status"] = "running"
        save(manifest_path, manifest)
        bundle = run_case(video, description=description, graph_requirements=requirements)
        if bundle.get("errors") or not bundle.get("case_graph"):
            raise RuntimeError(f"{video.name}: 完整模型特例学习未完成")
        if not bundle.get("validation", {}).get("passed"):
            raise RuntimeError(f"{video.name}: 实例结构校验未通过")
        if hashlib.sha256(video.read_bytes()).hexdigest() != row["video_sha256"]:
            raise RuntimeError("源视频在分析期间变化")
        row.update(status="complete", result=str(source),
                   result_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        source_results.append(str(source))
        save(manifest_path, manifest)
    return source_results


def run_cross_video_learning(args, output, source_results):
    """将已校验的单视频结果交给 s10 到 s13，沿用跨视频入口的续跑校验。"""
    cross_args = ["--inputs", *source_results, "--out", str(output / "knowledge"), "--allow-8032"]
    if args.graph_requirements:
        cross_args.extend(["--graph-requirements", str(args.graph_requirements)])
    if args.resume and (output / "knowledge").exists() and any((output / "knowledge").iterdir()):
        cross_args.append("--resume")
    if args.refresh_prompts:
        cross_args.append("--refresh-prompts")
    if args.refresh_case_graph:
        cross_args.append("--refresh-sources")
    code = learn_semantic_graph.main(cross_args)
    if code:
        raise RuntimeError(f"跨视频学习失败，退出码 {code}")


def write_index(output, videos):
    """为当前批次生成单视频和跨视频产物的索引页。"""
    cards = []
    for video in videos:
        folder = "cases/" + video.stem + "_semantic_v3/"
        cards.append('<li>' + html.escape(video.stem) + '：'
                     + ' · '.join('<a href="' + html.escape(folder + file, quote=True) + '">'
                                  + label + '</a>' for file, label in [
                                      ("workbench.html", "单视频工作台"), ("operations.svg", "操作图"),
                                      ("G_case.svg", "特例图"), ("G_case.json", "G_case")]) + '</li>')
    (output / "index.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>意图拿笔2 · 视频学习</title>'
        '<style>body{max-width:1000px;margin:48px auto;font:18px/1.8 system-ui;background:#f5f7fa;color:#162b42}'
        'a{color:#1761a0}li{margin:16px 0}</style><h1>意图拿笔2 · 视频学习</h1>'
        '<p>模型：Qwen3.8-27B · 服务器8032。各结论保留来源与待确认状态。</p><ul>'
        + "".join(cards) + '</ul><p><a href="knowledge/workbench.html">跨视频语义操作图工作台</a> · '
        '<a href="knowledge/semantic_operation_graph.svg">两层语义操作图</a> · '
        '<a href="knowledge/G_semantic.json">语义图数据</a> · '
        '<a href="run_manifest.json">本批次记录</a></p></html>', encoding="utf-8")


def main(argv=None):
    """校验运行参数，依次完成单视频、跨视频和批次索引。"""
    parser, args = parse_arguments(argv)
    if not args.allow_8032:
        parser.error("模型访问需要 --allow-8032")
    llm.require_deployed_model(config.BASE_URL, config.MODEL)
    videos = [v.resolve(strict=True) for v in args.videos]
    if len({v.stem for v in videos}) != len(videos):
        parser.error("同批视频名称必须唯一，避免实例目录冲突")
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()) and not args.resume:
        parser.error("输出目录必须为空；续跑本批次须显式 --resume")
    if any(output == v.parent or output in v.parents for v in videos):
        parser.error("输出目录不能包含源视频")
    output.mkdir(parents=True, exist_ok=True)
    description = args.description.read_text(encoding="utf-8") if args.description else None
    requirements = json.loads(args.graph_requirements.read_text(encoding="utf-8")) if args.graph_requirements else None
    if requirements is not None and not isinstance(requirements, dict):
        parser.error("graph requirements must be a JSON object")
    manifest = create_run_manifest(videos, description, requirements)
    if args.resume:
        manifest = resume_run(args, parser, output, manifest)

    manifest_path = output / "run_manifest.json"
    save(manifest_path, manifest)
    config.OUTPUT_DIR = output / "cases"
    config.WORK_DIR = output / "_work"
    try:
        source_results = run_single_video_cases(args, manifest_path, manifest, videos, description, requirements)
        run_cross_video_learning(args, output, source_results)
        manifest.update(status="complete", knowledge="knowledge/workbench.html")
        write_index(output, videos)
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        save(manifest_path, manifest)
        raise
    save(manifest_path, manifest)
    print(output / "knowledge" / "workbench.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
