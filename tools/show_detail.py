#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印指定案例的七元组 / 条件学习 / 语义规则详情。"""
import json
import sys
from pathlib import Path

case = sys.argv[1] if len(sys.argv) > 1 else "搬物体"
what = sys.argv[2] if len(sys.argv) > 2 else "node"
d = json.loads((Path("output") / case / "result.json").read_text(encoding="utf-8"))

if what == "node":
    idx = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    n = d["task_nodes"]["task_nodes"][idx]
    print(json.dumps(n, ensure_ascii=False, indent=2))
elif what == "rules":
    print(json.dumps(d.get("rules", {}), ensure_ascii=False, indent=2)[:6000])
elif what == "cond":
    idx = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    print(json.dumps(d["conditions"]["condition_learning"][idx], ensure_ascii=False, indent=2))
elif what == "link":
    print(json.dumps(d.get("link", {}), ensure_ascii=False, indent=2)[:4000])
