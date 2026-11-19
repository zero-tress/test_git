#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线验证先验补全（拿已落盘的动作表跑，不调用模型）。

用法：python tools/check_prior.py 搬物体
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from video2op.single_video.stages import s02e_prior


def main() -> int:
    case = sys.argv[1] if len(sys.argv) > 1 else "搬物体"
    merged = ROOT / "output" / case / "stages" / "s02d_link_merged.json"
    if not merged.exists():
        merged = ROOT / "output" / case / "stages" / "s02b_merge.json"
    data = json.loads(merged.read_text(encoding="utf-8"))
    actions = data["atomic_actions"]
    duration = json.loads((ROOT / "output" / case / "result.json").read_text(encoding="utf-8"))["meta"]["duration"]
    print(f"输入：{merged.name}｜动作 {len(actions)} 条")
    for a in sorted(actions, key=lambda x: (x["start"], x["end"])):
        print(f"  #{a['id']:>2} [{a['start']:>5}-{a['end']:>5}] {a['executor']:<3} {a['action'][:32]}")
    out = s02e_prior.run(actions, duration)
    print(f"\n补全 {len(out['inferred_actions'])} 条：")
    for a in out["inferred_actions"]:
        print(f"  #{a['id']:>2} [{a['start']:>5}-{a['end']:>5}] {a['executor']:<3} {a['action']}"
              f"  给力={a['exerts_force']}({a['force_role']}) object={a['object']}")
        print(f"        理由：{a['inference_reason'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
