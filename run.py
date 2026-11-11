#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""video2op 命令行入口。

用法（study 环境）：
    python run.py data/搬物体.mp4          # 跑单个视频
    python run.py all                     # 跑 data/ 下全部视频
    python run.py data/搬物体.mp4 --force  # 忽略缓存重跑
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from video2op.llm import LLMError
from video2op.pipeline import run_all, run_case


def main() -> int:
    ap = argparse.ArgumentParser(description="从人体操作视频提取任务语义操作图")
    ap.add_argument("target", help="视频路径，或 all 表示 data/ 下全部")
    ap.add_argument("--force", action="store_true", help="忽略模型缓存重新分析")
    ap.add_argument("--output-root", type=Path, help="另存本次运行产物的目录")
    ap.add_argument("--description", type=Path, help="UTF-8文字背景文件；与视频观察证据分开")
    args = ap.parse_args()
    description = args.description.read_text(encoding="utf-8") if args.description else None
    if args.output_root:
        from video2op import config
        config.OUTPUT_DIR = args.output_root.resolve()
        config.WORK_DIR = config.OUTPUT_DIR / "_work"

    try:
        if args.target == "all":
            results = run_all(force=args.force, **({"description": description} if description is not None else {}))
            failed = [r for r in results if r.get("errors") or not r.get("validation", {}).get("passed")]
            return 1 if failed else 0
        bundle = run_case(Path(args.target), force=args.force, **({"description": description} if description is not None else {}))
        if not bundle.get("validation", {}).get("passed"):
            print("提示：校验未全部通过，详见产物的 validation 与 needs_review 字段")
        return 1 if bundle.get("errors") or not bundle.get("validation", {}).get("passed") else 0
    except LLMError as e:
        print(f"\n模型调用失败：{e}")
        for err in e.errors[-3:]:
            print(f"  - {err[:300]}")
        return 2
    except FileNotFoundError as e:
        print(f"\n{e}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
