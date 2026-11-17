"""Run the complete video-to-case-to-semantic-knowledge workflow through 8032."""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op import config
from video2op.llm import require_deployed_model
from video2op.pipeline import run_case


def save(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description="8032单视频特例学习及跨视频语义操作图")
    parser.add_argument("--videos", nargs="+", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--description", type=Path, help="任务背景；不会作为已发生事实")
    parser.add_argument("--allow-8032", action="store_true")
    parser.add_argument("--resume", action="store_true", help="仅续跑输入及来源hash一致的本批次")
    parser.add_argument("--refresh-prompts", action="store_true",
                        help="提示词更新后允许续跑；已完成实例只重新导出本地视图，不重复调用模型")
    args = parser.parse_args(argv)
    if not args.allow_8032:
        parser.error("模型访问需要 --allow-8032")
    require_deployed_model(config.BASE_URL, config.MODEL)
    videos = [v.resolve(strict=True) for v in args.videos]
    if len({v.stem for v in videos}) != len(videos):
        parser.error("同批视频名称必须唯一，避免实例目录冲突")
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()) and not args.resume:
        parser.error("输出目录必须为空；续跑本批次须显式 --resume")
    if any(output == v.parent or output in v.parents for v in videos):
        parser.error("输出目录不能包含源视频")
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "video_learning_run.v1",
        "created": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "model": config.MODEL, "endpoint": config.BASE_URL,
        "analysis_origin": "deployed_model", "status": "running", "cases": [],
        "execution_enabled": False,
    }
    for video in videos:
        manifest["cases"].append({
            "video": str(video), "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
            "status": "pending",
        })
    description = args.description.read_text(encoding="utf-8") if args.description else None
    manifest["description_sha256"] = hashlib.sha256((description or "").encode()).hexdigest()
    if args.resume:
        saved = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
        expected = [(r["video"], r["video_sha256"]) for r in manifest["cases"]]
        actual = [(r["video"], r["video_sha256"]) for r in saved["cases"]]
        if (expected != actual or saved["model"] != config.MODEL
                or saved["endpoint"] != config.BASE_URL
                or saved.get("description_sha256") != manifest["description_sha256"]):
            parser.error("输入、模型或任务背景已改变，不能续跑；请另建输出目录")
        manifest = saved
        manifest["status"] = "running"
        manifest.pop("error", None)
    save(output / "run_manifest.json", manifest)
    config.OUTPUT_DIR = output / "cases"
    config.WORK_DIR = output / "_work"
    try:
        inputs = []
        for row, video in zip(manifest["cases"], videos, strict=True):
            source = config.OUTPUT_DIR / (video.stem + "_semantic_v3") / "result.json"
            if args.resume and row["status"] == "complete":
                if (not source.is_file()
                        or hashlib.sha256(source.read_bytes()).hexdigest() != row.get("result_sha256")):
                    raise RuntimeError("已完成实例被修改，不能静默续跑")
                # Re-export local views only; the saved model output is untouched.
                from video2op import case_graph
                bundle = json.loads(source.read_text(encoding="utf-8"))
                if bundle.get("case_graph"):
                    case_graph.export(bundle, source.parent)
                inputs.append(str(source))
                continue
            row["status"] = "running"
            save(output / "run_manifest.json", manifest)
            bundle = run_case(video, description=description)
            if bundle.get("errors") or not bundle.get("case_graph"):
                raise RuntimeError(f"{video.name}: 完整模型特例学习未完成")
            if not bundle.get("validation", {}).get("passed"):
                raise RuntimeError(f"{video.name}: 实例结构校验未通过")
            if hashlib.sha256(video.read_bytes()).hexdigest() != row["video_sha256"]:
                raise RuntimeError("源视频在分析期间变化")
            row.update(status="complete", result=str(source),
                       result_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            inputs.append(str(source))
            save(output / "run_manifest.json", manifest)
        module_path = Path(__file__).with_name("learn_semantic_graph.py")
        spec = importlib.util.spec_from_file_location("semantic_graph_cli", module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cross_args = ["--inputs", *inputs, "--out", str(output / "knowledge"), "--allow-8032"]
        if args.resume and (output / "knowledge").exists() and any((output / "knowledge").iterdir()):
            cross_args.append("--resume")
        if args.refresh_prompts:
            cross_args.append("--refresh-prompts")
        code = module.main(cross_args)
        if code:
            raise RuntimeError(f"跨视频学习失败，退出码 {code}")
        manifest.update(status="complete", knowledge="knowledge/workbench.html")
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
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        save(output / "run_manifest.json", manifest)
        raise
    save(output / "run_manifest.json", manifest)
    print(output / "knowledge" / "workbench.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
