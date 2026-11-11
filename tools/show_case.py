#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看案例产物的关键内容（人工检查用）。"""
import json
import sys
from pathlib import Path

case = sys.argv[1] if len(sys.argv) > 1 else "搬物体"
p = Path("output") / case / "result.json"
d = json.loads(p.read_text(encoding="utf-8"))

print("=" * 30, "视角")
vp = d["viewpoint"]
print(f"{vp.get('label_cn')} conf={vp.get('confidence')} operator={vp.get('operator')}")
print("  场景:", vp.get("scene"))

print("=" * 30, "意图")
for it in d["intents"]["intents"]:
    print(f"[{it.get('confidence')}] {it.get('statement')}  ({it.get('intent_type')})")
    print("   部位:", "、".join(f"{b.get('part')}:{b.get('role')}" for b in it.get("required_body_parts", [])))
    print("   终态:", it.get("expected_final_state"))

print("=" * 30, "原子动作（执行器级）")
for a in d["atomic"]["atomic_actions"]:
    mark = " [推理补全]" if a.get("inferred") else ""
    print(f"  #{a['id']:>2} [{a['start']:>5}-{a['end']:>5}] {a['executor']:<3} {a['action']}{mark}")
    print(f"        mode={a['mode']} 给力={a.get('exerts_force')}({a.get('force_role')}) "
          f"对象={a.get('object')} until={a.get('until')}")
    print(f"        {a.get('state_before')} → {a.get('state_after')}")

print("=" * 30, "时序关系")
actions = {a["id"]: a for a in d["atomic"]["atomic_actions"]}
for r in d["relations"]:
    fa = actions.get(r["from"], {})
    fb = actions.get(r["to"], {})
    print(f"  {r['relation']:<14} #{r['from']}({fa.get('executor')}{str(fa.get('action'))[:8]}) "
          f"→ #{r['to']}({fb.get('executor')}{str(fb.get('action'))[:8]})  {r.get('note','')}")

print("=" * 30, "任务节点")
for n in d["task_nodes"]["task_nodes"]:
    print(f"[{n['id']}] {n.get('name')}  时间={n.get('time_range')} refs={n.get('atomic_refs')}")
    print("    overall:", n.get("intent_role"))

print("=" * 30, "同步因果检验")
s = d.get("sync", {})
for c in s.get("checks", []):
    print(f"  {c.get('verdict'):<8} {c.get('question')}: {str(c.get('reason'))[:120]}")
    for k in ("detail", "missing", "inconsistencies"):
        for x in c.get(k, []) or []:
            print(f"      - {str(x)[:140]}")
print(f"  置信度 {s.get('intent_confidence_before')} → {s.get('intent_confidence_after')}: "
      f"{s.get('confidence_rationale')}")
print("  修订:", json.dumps(s.get("revisions", {}), ensure_ascii=False)[:600])

print("=" * 30, "校验")
v = d["validation"]
print(v["summary"])
for c in v["checks"]:
    st = c["status"]
    print(f"  [{st}] {c['name']}  ({len(c.get('detail') or [])} 条)")
    if st != "pass":
        for x in (c.get("detail") or [])[:8]:
            print("      -", json.dumps(x, ensure_ascii=False)[:300])
print("  待复核:", len(v.get("needs_review", [])))
