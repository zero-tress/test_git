#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""子操作展开（确定性）：把每个操作展开成执行层可以直接调度的子操作。

交付标准是"给执行层一个末端节点时，它能找到对应的已有动作能力，不用再自己推理
这个任务该拆成哪些操作"。所以每个操作下面要能回答三件事：

  1. **这一步内部有哪些子操作**——每个子操作对应一个执行器的一个动作（建立 / 移动 /
     保持），带自己的前后状态与时间区间。
  2. **它们之间是什么关系**——先后、并行，还是"一个保持覆盖另一个动作的全过程"。
     第三条是重点：手指合拢建立抓握时，手臂必须保持位姿，这不是"两件事同时发生"，
     而是"保持在前、闭合在其覆盖下完成"。
  3. **执行层要在哪里设检查点**——建立型动作要一个"建立成功了吗"，解除型要一个
     "确实松开了吗"，保持型要一个"期间它还在保持吗"。

子操作**全部来自已经定稿的原子动作表**，不新增任何动作、不发明任何状态：展开是
换个粒度重排证据，不是二次创作。所以 `inferred=true` 的子操作依旧带着它的推理
理由，识别不到的地方就空着——空着比编一个更接近事实。
"""

from __future__ import annotations

from .vocab import hold_category

# 执行器 → 能力层的中文说法（用于能力需求描述）
PART_CAPABILITY = {
    "右臂": "臂", "左臂": "臂", "右手": "手", "左手": "手",
    "腰": "躯干", "躯干": "躯干",
    "右腿": "腿", "左腿": "腿",
}

RELEASE_MARKERS = ("松开", "释放", "放开", "脱离", "撤回", "收回")
BUILD_MARKERS = ("抓握", "抓紧", "握住", "夹住", "接触", "贴上", "搭上", "按住")

OPEN_MARKERS = ("张开", "打开", "开")


def _strip_executor(actor: str, text: str) -> str:
    out = text
    if actor and out.startswith(actor):
        out = out[len(actor):].strip()
    return out or text


def _sub_capability(action: dict) -> str:
    """子操作需要什么能力。名字与执行侧实现词表对齐，接过去就能挂技能。"""
    mode = str(action.get("mode") or "")
    text = str(action.get("action") or "")
    if mode == "maintain":
        cat = hold_category(text + str(action.get("force_role") or ""))
        return {"grasp": "持续保持抓持", "support": "持续保持托举",
                "contact": "持续保持接触", "pose": "持续保持位姿"}.get(cat, "持续保持位姿")
    if mode == "transition":
        if any(w in text for w in RELEASE_MARKERS):
            return "解除抓持" if any(w in text for w in ("抓握", "握住", "夹")) else "释放"
        if any(w in text for w in ("抓握", "抓紧", "握住", "夹住", "握持")):
            return "建立抓持"
        if any(w in text for w in ("接触", "贴上", "搭上", "按住")):
            return "建立接触"
        if any(w in text for w in ("放置", "放下", "安放")):
            return "稳定放置"
        return "状态切换"
    if any(w in text for w in ("搬运", "转移", "挪动", "携带", "托举着")) \
            or str(action.get("force_role") or "") == "托举":
        return "承载移动"
    if any(w in text for w in ("收回", "撤回", "退回")):
        return "收回肢体"
    if any(w in text for w in ("接近", "靠近", "伸出", "前伸", "伸向")):
        return "接近目标"
    if any(w in text for w in ("抬起", "举起", "提起")):
        return "举起"
    return "移动执行器"


def _sub_kind(action: dict) -> str:
    mode = str(action.get("mode") or "")
    if mode == "maintain":
        return "hold"
    text = str(action.get("action") or "")
    if mode == "transition":
        return "release" if any(w in text for w in RELEASE_MARKERS) else "establish"
    return "motion"


def _sub_name(action: dict) -> str:
    """子操作名：不带执行器前缀（执行器是属性），保持动作原意。"""
    actor = str(action.get("executor") or "")
    core = _strip_executor(actor, str(action.get("action") or ""))
    return core or str(action.get("action") or "")


def _checkpoints(subs: list[dict], op: dict) -> list[dict]:
    """执行层要设的检查点：建立型要验证、解除型要确认、保持型要在期间持续检查。"""
    out: list[dict] = []
    for s in subs:
        state = (s.get("post") or [None])[0]
        if s["kind"] == "establish" and state:
            out.append({"id": f"{s['id']}.established", "kind": "state_check",
                        "sub_operation": s["id"], "executor": s["executor"],
                        "question": f"{state}是否成立？",
                        "at": s["end"], "action": "verify_after_sub_operation",
                        "note": "建立型动作必须验证它真的建立了，不能按动作名当作成功"})
        elif s["kind"] == "release" and state:
            out.append({"id": f"{s['id']}.released", "kind": "state_check",
                        "sub_operation": s["id"], "executor": s["executor"],
                        "question": f"{state}是否成立？",
                        "at": s["end"], "action": "verify_after_sub_operation",
                        "note": "解除型动作要确认作用确实解除，避免带着未释放的接触进入后续步骤"})
        elif s["kind"] == "hold":
            cat = hold_category(str(s.get("action") or ""))
            state = (s.get("pre") or s.get("post") or ["保持状态"])[0]
            out.append({"id": f"{s['id']}.holding", "kind": "hold_check",
                        "sub_operation": s["id"], "executor": s["executor"],
                        "question": f"{state}在 {s['start']}~{s['end']}s 期间是否持续成立？",
                        "during": [s["start"], s["end"]], "action": "monitor_during",
                        "note": f"保持类（{cat}）要在过程中持续监测，退出条件见 until 字段"})
    return out


def _sub_relations(subs: list[dict], relations: list[dict]) -> list[dict]:
    """子操作之间的关系：先后 / 并行 / 保持覆盖。

    “保持覆盖”比“并行”强：一个保持动作盖住另一个动作的全过程时，它不只是“同时也
    在发生”，而是那个动作成立的前提（手指合拢建立抓握时，手臂必须保持不动）。
    所以先算覆盖，再从已有关系里取剩下的，最后才用时间兜底。
    """
    out: list[dict] = []
    covered_pairs: set[tuple[str, str]] = set()
    for i, a in enumerate(subs):
        for b in subs[i + 1:]:
            hold, act = (a, b) if a["kind"] == "hold" else (b, a) if b["kind"] == "hold" else (None, None)
            if not hold or not act:
                continue
            if float(hold["start"]) <= float(act["start"]) + 0.05 \
                    and float(hold["end"]) >= float(act["end"]) - 0.05:
                out.append({"from": hold["id"], "to": act["id"], "relation": "hold_covers",
                            "note": f"「{hold['name']}」在「{act['name']}」全过程持续成立"
                                    f"（后者期间该状态不中断）",
                            "inferred": bool(hold.get("inferred"))})
                covered_pairs.add((hold["id"], act["id"]))
                covered_pairs.add((act["id"], hold["id"]))
    amap = {s["atomic_ref"]: s for s in subs}
    seen: set[tuple[str, str]] = {(e["from"], e["to"]) for e in out}
    for r in relations or []:
        if not isinstance(r, dict):
            continue
        f, t = amap.get(r.get("from")), amap.get(r.get("to"))
        if not f or not t or (f["id"], t["id"]) in covered_pairs:
            continue
        rel = str(r.get("relation") or "")
        if rel not in ("sequence", "parallel", "maintain_until", "enables"):
            continue
        if (f["id"], t["id"]) in seen or (t["id"], f["id"]) in seen:
            continue
        seen.add((f["id"], t["id"]))
        out.append({"from": f["id"], "to": t["id"], "relation": rel,
                    "note": str(r.get("note") or "")})
    # 时间兜底：上面两类都没覆盖到的子操作对
    for i, a in enumerate(subs):
        for b in subs[i + 1:]:
            if (a["id"], b["id"]) in seen or (b["id"], a["id"]) in seen:
                continue
            if (a["id"], b["id"]) in covered_pairs:
                continue
            if float(a["end"]) <= float(b["start"]) + 0.05:
                out.append({"from": a["id"], "to": b["id"], "relation": "sequence",
                            "note": f"「{a['name']}」结束后才开始「{b['name']}」"})
            elif float(b["end"]) <= float(a["start"]) + 0.05:
                out.append({"from": b["id"], "to": a["id"], "relation": "sequence",
                            "note": f"「{b['name']}」结束后才开始「{a['name']}」"})
            else:
                out.append({"from": a["id"], "to": b["id"], "relation": "parallel",
                            "mutual": True,
                            "note": f"「{a['name']}」与「{b['name']}」时间重叠"})
    return out


def _expand_one(op: dict, amap: dict, relations: list[dict]) -> dict:
    subs: list[dict] = []
    for i, r in enumerate(sorted(op.get("atomic_refs") or [],
                                 key=lambda x: (float((amap.get(x) or {}).get("start", 0)), x)), start=1):
        a = amap.get(r)
        if not a:
            continue
        subs.append({
            "id": f"{op['id']}.s{i}",
            "name": _sub_name(a),
            "executor": str(a.get("executor") or ""),
            "mode": str(a.get("mode") or ""),
            "kind": _sub_kind(a),
            "capability": _sub_capability(a),
            "start": round(float(a.get("start", 0)), 2),
            "end": round(float(a.get("end", 0)), 2),
            "pre": [str(a.get("state_before"))] if a.get("state_before") else [],
            "post": [str(a.get("state_after"))] if a.get("state_after") else [],
            "exerts_force": bool(a.get("exerts_force")),
            "force_role": a.get("force_role"),
            "object": a.get("object"),
            "atomic_ref": a.get("id"),
            "inferred": bool(a.get("inferred")),
            "inference_reason": a.get("inference_reason"),
            "until": a.get("until"),
            "evidence": a.get("evidence"),
        })
    rels = _sub_relations(subs, relations) if len(subs) > 1 else []
    checks = _checkpoints(subs, op)
    return {
        "id": op["id"],
        "name": op["name"],
        "intent": op.get("intent") or "",
        "executors": list(op.get("executors") or []),
        "time_range": [op.get("start"), op.get("end")],
        # 子操作是执行单元的粒度；概览图上这一步仍是一个节点，展开时看这里
        "expandable": len(subs) > 1,
        "sub_operations": subs,
        "relations": rels,
        "checkpoints": checks,
        "unexpanded_note": ("该操作只有一条原子动作，内部无可再分的调度单元"
                            if len(subs) == 1 else ""),
    }


def build(bundle: dict) -> dict:
    """对操作图里每个操作做子操作展开（纯确定性，不改动任何原有字段）。"""
    ops = ((bundle.get("operations") or {}).get("nodes")) or []
    actions = ((bundle.get("atomic") or {}).get("atomic_actions")) or []
    relations = bundle.get("relations") or []
    amap = {a.get("id"): a for a in actions if isinstance(a, dict)}
    items = [_expand_one(o, amap, relations) for o in ops if o.get("atomic_refs")]
    total_subs = sum(len(x["sub_operations"]) for x in items)
    return {
        "schema_version": "1.0",
        "kind": "operation_expansion",
        "note": "子操作来自已定稿的原子动作表；展开只换粒度，不新增动作或状态。",
        "operations": items,
        "by_operation": {x["id"]: x for x in items},
        "stats": {
            "operations": len(items),
            "sub_operations": total_subs,
            "expandable": sum(1 for x in items if x["expandable"]),
            "checkpoints": sum(len(x["checkpoints"]) for x in items),
            "inferred_sub_operations": sum(1 for x in items
                                           for s in x["sub_operations"] if s["inferred"]),
        },
    }
