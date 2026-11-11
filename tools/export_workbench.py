#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 薄壳 · 渲染案例的操作图工作台（离线可交互页）。

实现本体在 `video2op/workbench.py`；`run.py`（pipeline）与 `tools/render_case.py`
在渲染阶段结束后会自动调用 `workbench.export()`，所以跑完分析就有 workbench.html，
本脚本只用于单独重导出（例如改了页面样式想立刻看效果）。

用法：
  python tools/export_workbench.py 移动物体            # → output/移动物体/workbench.html
  python tools/export_workbench.py 移动物体 --out /tmp/x.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from video2op import workbench


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染操作图工作台（离线交互页）")
    ap.add_argument("case", help="案例名（output/<case>/result.json）")
    ap.add_argument("--out", default="", help="输出 HTML 路径（默认 output/<case>/workbench.html）")
    args = ap.parse_args()
    case_dir = ROOT / "output" / args.case
    src = case_dir / "result.json"
    if not src.exists():
        print(f"[ERR] 找不到 {src}", file=sys.stderr)
        return 2
    out, data = workbench.export(case_dir, Path(args.out) if args.out else None)
    print(f"[OK] {out}  ({out.stat().st_size} bytes)")
    print("节点:", [f'{n["cid"]}/{n["id"]}' for n in data["nodes"]])
    print("边:", [(f'{e["from"]}→{e["to"]}', e["relation"]) for e in data["edges"]])
    print("统计:", json.dumps(data["stats"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
