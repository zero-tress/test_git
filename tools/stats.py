#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计案例产物的规模（用于交付说明与自检）。"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _dag_text(d: dict) -> str:
    g = d.get("graph") or {}
    s = g.get("stats") or {}
    if not s:
        return "（无）"
    txt = f"{s.get('nodes', 0)} 节点 / {s.get('edges', 0)} 条依赖 / {s.get('layers', 0)} 列"
    if s.get("dropped"):
        txt += f" / 剔除回边 {s['dropped']}"
    return txt


def stat(case: str) -> dict:
    d = json.loads((ROOT / "output" / case / "result.json").read_text(encoding="utf-8"))
    acts = d["atomic"]["atomic_actions"]
    rels = d.get("relations") or []
    nodes = d.get("task_nodes", {}).get("task_nodes", [])
    rules = d.get("rules", {})
    cond = d.get("conditions", {})
    cl = cond.get("condition_learning", [])
    return {
        "case": case,
        "duration": d["meta"]["duration"],
        "视角": f"{d['viewpoint'].get('label_cn')} {d['viewpoint'].get('confidence')}",
        "意图": (d["intents"]["intents"][0]["statement"] if d["intents"]["intents"] else ""),
        "意图置信度": (f"{d['intents']['intents'][0]['confidence']} → "
                   f"{d.get('sync', {}).get('intent_confidence_after')}"
                   if d["intents"]["intents"] else ""),
        "动作总数": len(acts),
        "观测动作": sum(1 for a in acts if not a.get("inferred")),
        "补全动作": sum(1 for a in acts if a.get("inferred")),
        "部位分布": dict(Counter(a["executor"] for a in acts).most_common()),
        "mode分布": dict(Counter(a["mode"] for a in acts)),
        "持续给力动作": sum(1 for a in acts if a.get("exerts_force")),
        "关系总数": len(rels),
        "关系类型": dict(Counter(r["relation"] for r in rels)),
        "任务节点": len(nodes),
        "节点七元组完整": sum(
            1 for n in nodes
            if all(k in (n.get("tuple") or {}) for k in
                   ("X", "O", "C_pre", "C_const", "E", "C_post", "R"))),
        "条件学习条目": sum(len(x.get("C_pre_learning", [])) + len(x.get("C_post_learning", []))
                      for x in cl),
        "有效条件": len(cond.get("effective_conditions_summary", [])),
        "时序结构": len(rules.get("temporal_structures", [])),
        "语义约束": len(rules.get("constraints", [])),
        "评价器": len(rules.get("evaluators", [])),
        "校验": d["validation"]["summary"],
        "待复核": len(d["validation"].get("needs_review", [])),
        "时序逻辑行": len((d.get("temporal_logic") or {}).get("plc", [])),
        "依赖图(DAG)": _dag_text(d),
    }


def main() -> int:
    cases = sys.argv[1:] or [p.name for p in (ROOT / "output").glob("*")
                             if (p / "result.json").exists() and not p.name.startswith("_")]
    for c in cases:
        s = stat(c)
        print("=" * 46, c)
        for k, v in s.items():
            if k != "case":
                print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
