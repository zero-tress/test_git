#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印探针输出摘要（动作序列 + 时序关系）。"""
import json
import pathlib
import re

for f in sorted(pathlib.Path("/data/wj_data/deepseek_videostudy/output/_probe").glob("*.txt")):
    print("=" * 24, f.name)
    t = f.read_text(encoding="utf-8")
    t = re.sub(r"^```(?:json)?|```$", "", t.strip(), flags=re.M)
    try:
        d = json.loads(t)
    except Exception as e:
        print("parse fail", e)
        print(t[:2000])
        continue
    acts = d.get("atomic_actions", [])
    print(f"动作数={len(acts)}")
    for a in acts:
        print(f"  [{a.get('start'):>5}-{a.get('end'):>5}] {a.get('executor')!s:<4} "
              f"{a.get('action')!s:<18} mode={a.get('mode')!s:<9} "
              f"force={a.get('exerts_force')} until={a.get('until')}")
    rels = d.get("temporal_relations", [])
    print(f"关系数={len(rels)}")
    for r in rels:
        print(f"  {r.get('relation'):<14} {r.get('from')}->{r.get('to')}  {r.get('note','')}")
