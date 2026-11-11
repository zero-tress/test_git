#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时：统计 result.json 关键规模，供项目总结使用。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

base = Path("/data/wj_data/deepseek_videostudy/output")


def dig(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, dict):
        for k in ["nodes", "task_nodes", "items", "list", "relations", "atomic_actions"]:
            if isinstance(x.get(k), list):
                return x[k]
        # dict of id->item
        vals = list(x.values())
        if vals and all(isinstance(v, dict) for v in vals):
            return vals
    return []


for name in ["搬物体", "喝牛奶2", "long_test"]:
    p = base / name / "result.json"
    if not p.exists():
        print(name, "missing")
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    print("=" * 40, name)
    vp = dig(d, "viewpoint", default={}) or {}
    print("viewpoint:", vp.get("viewpoint"), vp.get("confidence"))

    intents_raw = dig(d, "intents", default={}) or {}
    intents = as_list(intents_raw if not isinstance(intents_raw, dict) else intents_raw.get("intents"))
    if intents:
        i0 = intents[0]
        parts = i0.get("required_body_parts") or []
        print("intent:", i0.get("statement"), "| conf", i0.get("confidence"))
        print("  parts:", [x.get("part") for x in parts])
        print("  expected_final:", str(i0.get("expected_final_state"))[:140])

    acts = as_list(dig(d, "atomic", "atomic_actions", default=[]))
    print("atomic_actions:", len(acts))
    if acts:
        print("  executors:", dict(Counter(a.get("executor") for a in acts)))
        print("  modes:", dict(Counter(a.get("mode") for a in acts)))
        print("  inferred:", sum(1 for a in acts if a.get("inferred")))
        print("  force true:", sum(1 for a in acts if a.get("exerts_force")))
        for a in acts[:5]:
            print(
                "  act:",
                a.get("executor"),
                "|",
                (a.get("action") or "")[:40],
                "|",
                a.get("mode"),
                "|",
                a.get("start"),
                "-",
                a.get("end"),
                "| until=",
                str(a.get("until"))[:60],
            )

    rels = as_list(d.get("relations"))
    print("relations:", len(rels))
    if rels:
        print("  types:", dict(Counter(r.get("type") or r.get("relation") for r in rels)))
        r0 = rels[0]
        print("  rel keys:", list(r0))
        print("  sample:", json.dumps(r0, ensure_ascii=False)[:220])

    nodes = as_list(d.get("task_nodes"))
    print("task_nodes:", len(nodes))
    for n in nodes[:8]:
        if not isinstance(n, dict):
            continue
        t = n.get("tuple") or {}
        label = n.get("name") or n.get("label") or n.get("id") or n.get("title")
        print(
            "  node:",
            label,
            "| O=",
            str(t.get("O") or "")[:40],
            "| C_pre=",
            str(t.get("C_pre"))[:80],
            "| R=",
            str(t.get("R"))[:60],
        )

    sync = dig(d, "sync", default={}) or {}
    print("sync top:", json.dumps({k: sync[k] for k in list(sync)[:8] if not isinstance(sync[k], (list, dict))}, ensure_ascii=False)[:300])
    for k, v in sync.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            if any(s in k.lower() for s in ["yes", "conf", "pass", "state", "q", "answer", "verdict"]):
                print(" ", k, ":", v)
    rev = sync.get("revisions") or {}
    print("  revisions:", list(rev) if isinstance(rev, dict) else type(rev))

    val = dig(d, "validation", default={}) or {}
    print("validation passed:", val.get("passed"), "|", val.get("summary"))
    checks = as_list(val.get("checks"))
    for c in checks:
        if isinstance(c, dict):
            print("  check:", c.get("id") or c.get("name"), c.get("status") or c.get("passed"))

    cond = dig(d, "conditions", default={}) or {}
    cl = as_list(cond.get("condition_learning"))
    print("condition_learning entries:", len(cl))
    if cl:
        print("  sample:", json.dumps(cl[0], ensure_ascii=False)[:350])
    for k in cond:
        if isinstance(cond[k], list):
            print("  conditions.", k, len(cond[k]))
        elif isinstance(cond[k], (str, int, float, bool)):
            print("  conditions.", k, cond[k])

    rules = dig(d, "rules", default={}) or {}
    for k, v in rules.items():
        items = as_list(v)
        print(f"rules.{k}: {len(items) if isinstance(v, (list, dict)) else v}")
        if items and isinstance(items[0], dict):
            print("  sample:", json.dumps(items[0], ensure_ascii=False)[:220])

    pipe = dig(d, "pipeline", default={}) or {}
    print("pipeline wall_seconds:", pipe.get("wall_seconds"), "| model:", pipe.get("model"))
    print("errors:", d.get("errors"))
    meta = dig(d, "meta", default={}) or {}
    print("meta:", meta.get("duration"), "s", meta.get("width"), "x", meta.get("height"), "@", meta.get("fps"))
    tl = dig(d, "temporal_logic", default={}) or {}
    print("temporal_logic keys:", list(tl) if isinstance(tl, dict) else type(tl))
    if isinstance(tl, dict):
        for k, v in tl.items():
            items = as_list(v)
            if items:
                print("  tl.", k, len(items), "e.g.", json.dumps(items[0], ensure_ascii=False)[:160])
            elif isinstance(v, (str, int, float)):
                print("  tl.", k, v)
    print()
