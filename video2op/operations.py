#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""操作图（确定性）：把任务级节点组织成"以操作为节点"的有向图。

与 graph.py 的分工（同一批数据的两个视角，互相补充而不是替代）：

  graph.py      节点 = 执行器级原子动作 —— 回答"哪个部位在第几秒做了什么"（追溯用）
  operations.py 节点 = 操作（任务级语义单元）—— 回答"为完成意图做了哪些操作、
                它们之间是先后还是并行、每个操作是为了什么"（交付/调度用）

**执行器在这张图里是节点属性（executors），不是节点本身。** 这是为了泛化：换成
非人形执行体（底盘 / 爪 / 四足）时，它的能力表可以直接挂到"操作"上，不需要先做
一遍"左臂 → 某执行机构"的映射。

三类信息在这里被显式化（都是此前只隐含表达的）：

  1. 时序：sequence（先后）/ parallel（并行）/ alternation（交替）全部作为**边**保留，
     并行与交替不再退化成"同一列"这种需要读者自己推断的布局约定；
  2. 因果：enables —— 前一个操作的 C_post 满足后一个操作的 C_pre（条件衔接）；
  3. 意图链：每个操作的 purpose（为了什么）= 它为后继操作提供了哪一条前置条件。

分层（layer）复用与 graph.py 相同的两条规则：依赖边保证层号递增，并行/交替对
拉到同层；不收敛时回退纯依赖分层，保证每条边的方向都从左指向右。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

DEP_RELATIONS = ("sequence", "enables", "maintain_until")
SOFT_RELATIONS = ("parallel", "alternation")
TIME_TOL = 0.05        # 两个操作的时间区间视为重叠的容差（秒）
SIM_FLOOR = 0.34       # C_post ↔ C_pre 的文本相似度阈值（低于此不算"条件衔接"）


# ---------------------------------------------------------------
# 文本相似度（只用于"条件衔接"判定，不参与任何语义结论）
# ---------------------------------------------------------------

_PUNCT_RE = re.compile(r"[\s，。、；：（）()\[\]【】「」,.;:!?·\-—_/]+")


def _norm(text: object) -> str:
    return _PUNCT_RE.sub("", str(text or ""))


def _bigrams(s: str) -> set[str]:
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _sim(a: object, b: object) -> float:
    """字符二元组 Jaccard 相似度：中文短语的近似匹配够用，且完全确定。"""
    A, B = _bigrams(_norm(a)), _bigrams(_norm(b))
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


# ---------------------------------------------------------------
# 节点：任务级节点 → 操作节点
# ---------------------------------------------------------------

def _to_operations(task_nodes: list[dict], amap: dict) -> list[dict]:
    from .evidence import observed_states
    ops: list[dict] = []
    for i, n in enumerate(task_nodes):
        if not isinstance(n, dict):
            continue
        t = n.get("tuple") or {}
        x = t.get("X") if isinstance(t.get("X"), dict) else {}
        refs = [int(r) for r in (n.get("atomic_refs") or []) if r in amap]
        parts = [str(p) for p in (x.get("parts") or []) if p]
        if not parts:                      # 回退：从绑定动作的执行器取
            parts = sorted({str(amap[r].get("executor")) for r in refs
                            if amap[r].get("executor")})
        tr = n.get("time_range")
        if isinstance(tr, list) and len(tr) == 2 and all(_is_num(v) for v in tr):
            start, end = round(float(tr[0]), 2), round(float(tr[1]), 2)
        elif refs:
            start = round(min(float(amap[r].get("start", 0)) for r in refs), 2)
            end = round(max(float(amap[r].get("end", 0)) for r in refs), 2)
        else:
            start = end = 0.0
        if end < start:
            start, end = end, start
        ops.append({
            "id": str(n.get("id") or f"node_{i + 1}"),
            "name": str(n.get("name") or "").strip(),
            "intent": str(n.get("intent_role") or "").strip(),   # 操作意图
            "start": start,
            "end": end,
            "executors": parts,                                   # 执行器 = 节点属性
            "object": [str(o) for o in (_as_list(t.get("O"))) if o],
            "pre": [str(c) for c in _as_list(t.get("C_pre")) if c],
            "post": [str(c) for c in _as_list(t.get("C_post")) if c],
            "invariants": [str(c) for c in _as_list(t.get("C_const")) if c],
            "completion": [str(c) for c in _as_list((t.get("E") or {}).get("completion")) if c]
                          if isinstance(t.get("E"), dict) else [],
            "required_capabilities": [str(c) for c in _as_list(n.get("required_capabilities")) if c],
            "observed_effects": [{"atomic_ref": r, "state": state}
                                 for r in refs for state in observed_states(amap[r])],
            "atomic_refs": refs,
            "inferred_steps": sum(1 for r in refs if amap[r].get("inferred")),
            "purpose": "",                                        # 由意图链回填
            "layer": 0,
        })
    ops.sort(key=lambda o: (o["start"], o["end"], o["id"]))
    return ops


# ---------------------------------------------------------------
# 保持动作 → 操作层的 MAINTAIN 节点
#
# 一个 maintain 动作只覆盖单个操作时，它是那个操作的内部步骤；一旦它跨越两个以上
# 操作（例如“保持抓握”从抓取建立后一直持续到放置释放），它就是一个**独立的调度
# 单元**：自己占用执行器、自己等一个停止事件，并且自己有条件要检查。这时把它提到
# 操作层，对齐“MAINTAIN 节点 + maintain_until”的表达（同事的 A3_HOLD / A7 同形）。
#
# 提升只重组已有证据：新节点的前后条件来自被提升动作的观测状态，不新增任何事实。
# ---------------------------------------------------------------

HOLD_FORCE_TEXT = {
    "grasp": "持续保持抓持",
    "support": "持续保持托举",
    "contact": "持续保持接触",
    "pose": "持续保持位姿",
}
MAX_LIFTED_HOLDS = 4          # 一张图上最多提升多少条保持（避免背景状态淹掉主图）
HOLD_BUSY_RATIO = 0.5         # 同执行器的其他动作占该保持时长的比例超过它，就不算独立保持


def _overlap_len(op: dict, s: float, e: float) -> float:
    return max(0.0, min(float(op["end"]), e) - max(float(op["start"]), s))


def _liftable(action: dict) -> bool:
    """该保持动作是否值得提升为独立操作。

    腿的站立支撑不进操作层：它是全程的背景支撑状态，不是“为某个操作提供条件”的
    操作；手 / 臂 / 腰的保持（抓握、托举、位姿、接触）才是。
    """
    if str(action.get("mode")) != "maintain":
        return False
    actor = str(action.get("executor") or "")
    text = str(action.get("action") or "")
    if actor in ("左腿", "右腿") and "站立" in text:
        return False
    return bool(actor)


def _independent_hold(action: dict, covered: list[dict]) -> bool:
    """这条保持是不是一个独立的调度单元（值得提升为 MAINTAIN 节点）。

    两种情况：
      · **跨操作覆盖**（覆盖 ≥2 个操作）：它跨过了操作边界，本身就是调度单元；
      · **只覆盖一个操作**：只有位姿保持（pose）算——“把这个执行器固定在某个位姿上”
        与那个操作的动作天然是两件事：③ 手臂保持抓取位姿 ∥ ④ 手指闭合建立抓握，
        发生在两个执行器上，可以各自调度（同事图里的 A3_HOLD 同形）。
        托举/接触类保持常与动作并发（搬运时手臂保持托举），是那个动作自己的一部分。

    只覆盖一个操作的位姿保持里，还要再分一层宾语：
      · “右臂保持位置”“右臂保持伸出”：维持执行器自己的位姿 → 提升；
      · “右臂保持燕麦杯在桌面近处位置”：维持的是物体在世界中的位置，手臂只是停在
        原地等释放，不是以操作为目的的一步 → 不提升。不提升它，这一步才能留在
        “放置”内部，让“放置”和“释放”拆得开（见 _split_release_steps）。
    """
    from .vocab import hold_category, is_self_hold
    if len(covered) >= 2:
        return True
    if len(covered) == 1:
        text = str(action.get("action") or "")
        if hold_category(text + str(action.get("force_role") or "")) != "pose":
            return False
        return is_self_hold(text)
    return False


def _handoff_owner(action: dict, ops: list[dict], amap: dict) -> str:
    """保持结束后接管执行器的操作（“保持到移动接管”的落点）。

    停止事件（until.ref）指向的动作属于哪个操作，就交接给谁——前提是那个动作在
    保持结束之后才开始（保持的终点正是它的起点）。只用于叙述与审查，**不进
    maintain_until**：执行侧把 maintain_until 解释为“等目标完成才放掉执行器”，
    与同执行器的目标写成 maintain_until 会互等死锁。
    """
    ev = action.get("until")
    ref = ev.get("ref") if isinstance(ev, dict) else None
    if ref is None:
        return ""
    nxt = amap.get(ref)
    if not nxt:
        return ""
    if float(nxt.get("start", 0)) < float(action.get("end", 0)) - TIME_TOL:
        return ""
    for o in ops:
        if ref in (o.get("atomic_refs") or []):
            return o["id"]
    return ""


def _op_executors(op: dict, amap: dict) -> set[str]:
    """操作实际占用的执行器：以它绑定的原子动作为准。

    节点属性（task_node 的 parts）可能标得过宽（“搬运”同时写了右臂和右手），
    但真正占用哪个执行器要看动作表——否则会把不冲突的终点误判成冲突。
    """
    ex = {str((amap.get(r) or {}).get("executor") or "")
          for r in (op.get("atomic_refs") or [])}
    ex.discard("")
    return ex or {str(x) for x in (op.get("executors") or [])}


def _maintain_target(action: dict, covered: list[dict], amap: dict) -> dict:
    """执行侧的安全锚点：不能选与保持同执行器的操作。

    执行侧把 MAINTAIN 解释为“占着执行器直到目标完成”。如果目标也要用同一个
    执行器，两边互等（真实死锁，验证器会报出来）。所以优先选“不同执行器的
    最后一个被覆盖操作”；确实全都同执行器时才退回最后一个，由校验器报出。
    """
    actor = str(action.get("executor") or "")
    safe = [o for o in covered if actor not in _op_executors(o, amap)]
    return (safe or covered)[-1]


def _hold_name(actor: str, text: str, ensure_hold: bool = True) -> str:
    """节点名称：节点名不能以执行器开头（节点是操作，执行器写在属性里）。

    “右手保持抓握药瓶” → “保持抓握药瓶”；执行器已经写在 executors 属性里了。
    ensure_hold=False 用于拆分出来的释放步骤——它本来就不是一条保持动作。
    """
    name = text
    if actor and name.startswith(actor):
        name = name[len(actor):].strip()
    if not name:
        name = f"保持{actor}" if ensure_hold else actor
    if ensure_hold and not any(w in name for w in ("保持", "维持", "持续")):
        name = "保持" + name
    return name


def _busy_ratio(action: dict, amap: dict) -> float:
    """该保持动作的区间里，同一个执行器还在做多少“别的活儿”（非保持动作）。

    “保持”不等于“这个执行器被它独占”：拧瓶盖时手臂既在维持接触又在转动，
    这种保持是动作的一部分，不是一个能独立调度的调度单元。把这类提升为 MAINTAIN
    节点，反而会和它本来就在配合的动作抢资源。
    """
    actor = str(action.get("executor") or "")
    s, e = float(action.get("start", 0)), float(action.get("end", 0))
    span = max(e - s, 1e-6)
    busy = 0.0
    for a in amap.values():
        if a.get("id") == action.get("id") or str(a.get("executor")) != actor:
            continue
        if str(a.get("mode")) == "maintain":
            continue
        busy += max(0.0, min(e, float(a.get("end", 0))) - max(s, float(a.get("start", 0))))
    return busy / span


def _make_hold_node(action: dict, covered: list[dict], source_ops: list[dict],
                    index: int, handoff: str = "", target: dict | None = None) -> dict:
    from .vocab import hold_category
    actor = str(action.get("executor") or "")
    text = str(action.get("action") or "")
    name = _hold_name(actor, text)
    category = hold_category(text + str(action.get("force_role") or ""))
    covered_names = "、".join(f"「{o['name']}」" for o in covered)
    target = target or covered[-1]
    obj: list[str] = []
    for o in covered:
        for x in (o.get("object") or []):
            if x not in obj:
                obj.append(x)
    if not obj and action.get("object"):
        obj = [str(action["object"])]
    return {
        "id": f"hold_{index}",
        "name": name,
        "intent": f"持续维持对「{obj[0]}」的控制，覆盖{covered_names}的全过程"
                  if obj else f"持续维持该状态，覆盖{covered_names}的全过程",
        "start": round(float(action.get("start", 0)), 2),
        "end": round(float(action.get("end", 0)), 2),
        "executors": [actor],
        "object": obj,
        "pre": [str(action.get("state_before") or "")] if action.get("state_before") else [],
        "post": [str(action.get("state_after") or "")] if action.get("state_after") else [],
        "invariants": [],
        "completion": [],
        "required_capabilities": [HOLD_FORCE_TEXT.get(category, "持续保持")],
        "observed_effects": [{"atomic_ref": action.get("id"),
                              "state": str(action.get("state_after") or "")}]
                            if action.get("state_after") else [],
        "atomic_refs": [action.get("id")],
        "inferred_steps": 1 if action.get("inferred") else 0,
        "purpose": "",
        "layer": 0,
        "mode": "maintain",                # 对齐 MAINTAIN 语义
        "maintain_until": [target["id"]],        # 执行侧安全锚点（不同执行器优先）
        "maintain_until_mode": "handoff" if handoff else "complete",
        "handoff_to": [handoff] if handoff else [],   # 结束时接管执行器的操作（交接）
        "stop_event": action.get("until"),   # 更精确的停止事件（来自示范证据）
        "covers": [o["id"] for o in covered],
        "lifted_from": [o["id"] for o in source_ops],
        "hold_action": text,
        "hold_category": category,
    }


def _lift_maintains(ops: list[dict], amap: dict) -> list[dict]:
    """把跨操作的保持动作提升为操作层 MAINTAIN 节点，并从原操作上摘掉它。

    返回新节点；同时给原操作写上 held_by（谁在覆盖它的过程）。幂等：每次都从
    task_nodes 重建，不累积。
    """
    found: dict[int, tuple[dict, list[dict]]] = {}
    for op in ops:
        for r in op["atomic_refs"]:
            a = amap.get(r)
            if not a or not _liftable(a):
                continue
            if r in found:
                continue
            s, e = float(a.get("start", 0)), float(a.get("end", 0))
            covered = [o for o in ops if _overlap_len(o, s, e) > TIME_TOL]
            if not _independent_hold(a, covered):
                continue
            if _busy_ratio(a, amap) > HOLD_BUSY_RATIO:      # 执行器同时在干别的活
                continue
            found[r] = (a, covered)
    if not found:
        return []
    picked = sorted(found.items(), key=lambda kv: (-len(kv[1][1]), float(kv[1][0].get("start", 0))))
    picked = picked[:MAX_LIFTED_HOLDS]
    holds: list[dict] = []
    for i, (rid, (a, covered)) in enumerate(picked, start=1):
        sources = [o for o in ops if rid in o["atomic_refs"]]
        handoff = _handoff_owner(a, ops, amap)
        target = _maintain_target(a, covered, amap)
        node = _make_hold_node(a, covered, sources, i, handoff, target)
        holds.append(node)
        for o in ops:                                  # 调度单元只能有一个宿主
            if rid in o["atomic_refs"]:
                o["atomic_refs"] = [x for x in o["atomic_refs"] if x != rid]
        for o in covered:
            o.setdefault("held_by", []).append(node["id"])
        for o in sources:
            o.setdefault("lifted_holds", []).append(node["id"])
    return holds


def _adopt_orphan_maintains(ops: list[dict], amap: dict) -> int:
    """把没被任何操作认领的保持动作归入它实际覆盖的那个操作。

    先验补全（站立支撑 / 接触期手臂保持 / 姿态保持）产出的保持动作，有时不落在
    任何 task_node 的 atomic_refs 里——于是它们在操作图层面上像是不存在一样，
    覆盖检查自然也就看不到它们。按“重叠时长最长”认领，只动 maintain，不碰其他动作。
    """
    claimed = {r for o in ops for r in o["atomic_refs"]}
    n = 0
    for a in sorted(amap.values(), key=lambda x: (float(x.get("start", 0)), int(x.get("id", 0)))):
        if a.get("id") in claimed or str(a.get("mode")) != "maintain":
            continue
        s, e = float(a.get("start", 0)), float(a.get("end", 0))
        best = max(ops, key=lambda o: _overlap_len(o, s, e), default=None)
        if best is None or _overlap_len(best, s, e) <= TIME_TOL:
            continue
        best["atomic_refs"] = sorted(best["atomic_refs"] + [a["id"]])
        claimed.add(a["id"])
        n += 1
    return n


RELEASE_SPLIT_MARKERS = ("松开", "释放", "放开", "脱离", "脱开")


def _lift_orphan_steps(ops: list[dict], amap: dict) -> list[dict]:
    """把未被任何操作认领的**先验步骤**（inferred 的 transition）提升为独立操作。

    先验补全会补出“逻辑上必然存在”的瞬时步骤（如抓握前把手张开到可抓取开度）。
    它们不属于任何模型判定的操作，但也不应隐形：操作图上要有一个节点回答
    “这一步谁做、为什么、给后续提供了什么”。只收 inferred=true 的 transition
    ——视频里直接提取到的动作不在这里动，它们归模型判定的操作。
    """
    claimed = {r for o in ops for r in o["atomic_refs"]}
    out: list[dict] = []
    for a in sorted(amap.values(), key=lambda x: (float(x.get("start", 0)), int(x.get("id", 0)))):
        rid = a.get("id")
        if rid in claimed or str(a.get("mode")) != "transition" or not a.get("inferred"):
            continue
        actor = str(a.get("executor") or "")
        text = str(a.get("action") or "")
        after = str(a.get("state_after") or "")
        nxt = next((o for o in ops
                    if float(o.get("start", 0)) >= float(a.get("end", 0)) - TIME_TOL), None)
        out.append({
            "id": f"step_{rid}",
            "name": _hold_name(actor, text, ensure_hold=False),
            "intent": f"为后续操作准备条件：{after}" if after else "为后续操作准备条件",
            "start": round(float(a.get("start", 0)), 2),
            "end": round(float(a.get("end", 0)), 2),
            "executors": [actor],
            "object": [],
            "pre": [str(a.get("state_before"))] if a.get("state_before") else [],
            "post": [after] if after else [],
            "invariants": [],
            "completion": [after] if after else [],
            "required_capabilities": ["手部预张开"] if "手" in actor else [],
            "observed_effects": [],
            "atomic_refs": [rid],
            "inferred_steps": 1,
            "purpose": "",
            "layer": 0,
            "inferred": True,
            "inference_reason": a.get("inference_reason"),
            "provides": after,
            "prepares": [nxt["id"]] if nxt else [],   # 它给哪个后继操作准备条件
        })
    return out


def _resync_holds_after_split(ops: list[dict], holds: list[dict],
                              split: list[dict]) -> None:
    """释放步骤拆出后，把保持节点里指向被拆操作的引用改指到拆出的释放节点。

    拆分改变了操作边界：原来“就位+释放”的那一步现在只剩“就位”，释放成了新节点。
    保持节点（尤其覆盖释放期的位姿保持）必须跟着改指，否则又会出现
    “保持占着某个执行器、终点却是同执行器的旧操作”这种互等引用。
    """
    smap = {s["id"]: s for s in split}
    for h in holds:
        hs, he = float(h.get("start", 0)), float(h.get("end", 0))
        for i, cov in enumerate(list(h.get("covers") or [])):
            rel = smap.get(f"{cov}_release")
            if rel and _overlap_len(rel, hs, he) > TIME_TOL:
                h["covers"][i] = rel["id"]
        mu = (h.get("maintain_until") or [None])[0]
        rel = smap.get(f"{mu}_release")
        if rel and _overlap_len(rel, hs, he) > TIME_TOL:
            h["maintain_until"] = [rel["id"]]
        for rel in smap.values():
            src = next((o for o in ops if o["id"] == rel.get("split_from")), None)
            if not src or h["id"] not in (src.get("held_by") or []):
                continue
            if _overlap_len(rel, hs, he) > TIME_TOL and h["id"] not in (rel.get("held_by") or []):
                src["held_by"] = [x for x in src["held_by"] if x != h["id"]]
                rel.setdefault("held_by", []).append(h["id"])
        # 交接对象也重算：停止事件指向的动作拆到哪个操作，就交接给谁
        ev = h.get("stop_event") or {}
        ref = ev.get("ref") if isinstance(ev, dict) else None
        if ref is not None:
            owner = next((o["id"] for o in ops if ref in (o.get("atomic_refs") or [])), None)
            if owner and owner != (h.get("maintain_until") or [None])[0]:
                h["handoff_to"] = [owner]


def _is_release_action(a: dict) -> bool:
    return (str(a.get("mode")) == "transition"
            and any(w in str(a.get("action") or "") for w in RELEASE_SPLIT_MARKERS))


def _split_release_steps(ops: list[dict], amap: dict, holds: list[dict]) -> list[dict]:
    """把被保持覆盖的操作里的“释放”步骤拆成独立节点。

    为什么非拆不可：保持节点（例如“保持抓握”）在持续期间占着那个执行器，直到它的
    maintain_until 达成才释放。如果“释放”这个步骤本身要和它抢同一个执行器，两条规则
    会互相等对方——调度上就是死锁。同事那张图把“建立支撑”（不占夹爪）放在保持的
    终点、“释放”（占夹爪）放在其后，正是这个道理。

    拆分只依据已有证据：那个释放动作本来就是独立的一条原子动作，且发生在该操作的后段。
    """
    new_nodes: list[dict] = []
    for op in list(ops):
        if str(op.get("mode") or "") == "maintain":
            continue
        if not any(op["id"] in (h.get("covers") or []) for h in holds):
            continue
        releases = [r for r in op["atomic_refs"] if _is_release_action(amap.get(r) or {})]
        others = [r for r in op["atomic_refs"] if r not in releases]
        if len(releases) != 1 or not others:
            continue
        rid = releases[0]
        a = amap[rid]
        rel_start = float(a.get("start", 0))
        # 只看“非保持”步骤的顺序：保持类动作跨过释放时刻是正常的
        # （手臂保持抬起、夹爪保持夹持在释放那一刻仍在成立），不能因为它就认为释放不是最后一步。
        if any(float((amap.get(x) or {}).get("end", 0)) > rel_start + TIME_TOL
               for x in others
               if str((amap.get(x) or {}).get("mode")) != "maintain"):
            continue
        actor = str(a.get("executor") or "")
        text = str(a.get("action") or "")
        node = {
            "id": f"{op['id']}_release",
            "name": _hold_name(actor, text, ensure_hold=False),
            "intent": f"在保持结束后解除对「{('、'.join(op.get('object') or ['目标']))}」的作用，"
                      f"让执行器回到可用状态",
            "start": round(rel_start, 2),
            "end": round(float(a.get("end", 0)), 2),
            "executors": [actor],
            "object": list(op.get("object") or []),
            "pre": [str(a.get("state_before"))] if a.get("state_before") else [],
            "post": [str(a.get("state_after"))] if a.get("state_after") else [],
            "invariants": [],
            "completion": [],
            "required_capabilities": ["释放"],
            "observed_effects": [{"atomic_ref": a.get("id"),
                                  "state": str(a.get("state_after") or "")}]
                                if a.get("state_after") else [],
            "atomic_refs": [rid],
            "inferred_steps": 1 if a.get("inferred") else 0,
            "purpose": "",
            "layer": 0,
            "split_from": op["id"],              # 从哪一步拆出来的
            "split_reason": ("该步骤占用执行器，而它所属的操作正被保持节点覆盖："
                             "不拆开则保持与释放互等资源"),
        }
        op["atomic_refs"] = others
        op["end"] = round(rel_start, 2)
        # 拆出去的那条动作仍然是这一步产生的证据：拆分只是换了个调度边界，
        # 不改变“这一步本来做了什么”。丢掉它会让原操作的预期效果突然变得“无证据”。
        op.setdefault("split_action_refs", []).append(rid)
        # 执行器必须按拆分**剩下的**动作重算：放置就位那一段由臂完成（占臂），
        # 释放那一段才由手/夹爪完成（占终端执行器）——两者分开后才不会与保持互相等资源。
        rest = sorted({str((amap.get(x) or {}).get("executor")) for x in others
                       if (amap.get(x) or {}).get("executor")})
        if rest:
            op["executors"] = rest
        op.setdefault("split_steps", []).append(node["id"])
        new_nodes.append(node)
    return new_nodes


def _is_num(v: object) -> bool:
    try:
        float(v)  # type: ignore[arg-type]
        return True
    except (TypeError, ValueError):
        return False


def _as_list(v: object) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


# ---------------------------------------------------------------
# 边：操作之间的先后 / 并行 / 交替 / 使能
# ---------------------------------------------------------------

def _rel_index(relations: list[dict]) -> dict[tuple, set]:
    idx: dict[tuple, set] = defaultdict(set)
    for r in relations:
        if not isinstance(r, dict):
            continue
        f, t = r.get("from"), r.get("to")
        rel = str(r.get("relation") or "").strip().lower()
        if f is None or t is None or not rel:
            continue
        idx[(f, t)].add(rel)
    return idx


def _vote(A: dict, B: dict, idx: dict) -> tuple[Counter, Counter]:
    """统计 A 的动作 → B 的动作 与反向的原始关系票数。"""
    fwd: Counter = Counter()
    rev: Counter = Counter()
    for a in A["atomic_refs"]:
        for b in B["atomic_refs"]:
            for rel in idx.get((a, b), ()):
                fwd[rel] += 1
            for rel in idx.get((b, a), ()):
                rev[rel] += 1
    return fwd, rev


def _pick(counter: Counter, allowed: tuple[str, ...]) -> tuple[str, int]:
    items = [(k, v) for k, v in counter.items() if k in allowed]
    if not items:
        return "", 0
    rel, n = max(items, key=lambda kv: (kv[1], -allowed.index(kv[0])))
    return rel, n


def _edges(ops: list[dict], relations: list[dict]) -> list[dict]:
    idx = _rel_index(relations)
    edges: list[dict] = []
    for i, A in enumerate(ops):
        for B in ops[i + 1:]:
            fwd, rev = _vote(A, B, idx)
            rel_f, n_f = _pick(fwd, DEP_RELATIONS)
            rel_r, n_r = _pick(rev, DEP_RELATIONS)
            soft_f, n_sf = _pick(fwd, SOFT_RELATIONS)
            soft_r, n_sr = _pick(rev, SOFT_RELATIONS)

            if n_f or n_r:
                # 依赖边优先：它比"同时进行"承载更强的信息
                if n_f >= n_r and n_f > 0:
                    edges.append({"from": A["id"], "to": B["id"], "relation": rel_f,
                                  "note": _edge_note(rel_f, A, B),
                                  "inferred_by": "action_relations"})
                else:
                    edges.append({"from": B["id"], "to": A["id"], "relation": rel_r,
                                  "note": _edge_note(rel_r, B, A),
                                  "inferred_by": "action_relations"})
                continue

            overlap = A["start"] < B["end"] - TIME_TOL and B["start"] < A["end"] - TIME_TOL
            if (n_sf or n_sr) and overlap:
                # 并行/交替是无向关系：保留为一个"互见"的对，渲染层画成并列标记
                rel = soft_f if n_sf >= n_sr else soft_r
                edges.append({"from": A["id"], "to": B["id"], "relation": rel,
                              "mutual": True,
                              "note": "两者在时间上重叠、互为"
                                      + ("并行" if rel == "parallel" else "交替"),
                              "inferred_by": "action_relations"})
                continue

            # 时间兜底：完全不重叠的两个操作，按时间先后补一条顺序边
            if B["start"] >= A["end"] - TIME_TOL:
                edges.append({"from": A["id"], "to": B["id"], "relation": "sequence",
                              "note": f"「{A['name']}」结束后开始「{B['name']}」",
                              "inferred_by": "time_order"})
            elif A["start"] >= B["end"] - TIME_TOL:
                edges.append({"from": B["id"], "to": A["id"], "relation": "sequence",
                              "note": f"「{B['name']}」结束后开始「{A['name']}」",
                              "inferred_by": "time_order"})
    return edges


def _reduce_sequences(edges: list[dict]) -> list[dict]:
    """传递约简：A→C 若能沿 A→…→C 走到，就删掉这条冗余的先后边。

    时间兜底会给"不重叠的任意两个操作"连边，六个操作就能连出十五条——图会糊成
    一团。只保留最小依赖集（相邻步之间的先后）才读得出来。只约简 sequence：
    enables（因果）与 maintain_until（保持）承载额外语义，即使有传递路径也保留。
    """
    hard = [(i, e) for i, e in enumerate(edges) if not e.get("mutual")]
    adj: dict[str, list[int]] = defaultdict(list)
    for i, e in hard:
        adj[e["from"]].append(i)
    drop: set[int] = set()
    for i, e in hard:
        if e["relation"] != "sequence":
            continue
        seen, stack, found = {e["from"]}, [e["from"]], False
        while stack and not found:
            for j in adj.get(stack.pop(), []):
                if j == i:
                    continue
                v = edges[j]["to"]
                if v == e["to"]:
                    found = True
                    break
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        if found:
            drop.add(i)
    return [e for i, e in enumerate(edges) if i not in drop]


def _hold_entry_source(h: dict, ops: list[dict], amap: dict) -> dict | None:
    """谁建立了这个保持：时间上紧邻的前序操作（它的后置效果是这个保持的前提）。

    保持动作落在哪个操作的 atomic_refs 里，取决于模型当时怎么认领的，不一定就是
    建立它的那一步。按“结束时间最接近保持起点”找前驱，再用“后置效果与保持的前置
    条件同类”验证，才是数据本身说话。
    """
    from .vocab import hold_category
    cat = str(h.get("hold_category") or "pose")
    start = float(h.get("start", 0))
    cands = [o for o in ops
             if not o.get("mode") and float(o.get("end", 0)) <= start + TIME_TOL]
    if not cands:
        return None

    def score(o: dict) -> tuple:
        match = 1 if any(hold_category(p) == cat for p in (o.get("post") or [])) else 0
        return (match, float(o.get("end", 0)))

    best = max(cands, key=score)
    # 只有还真有“前序”才能说有谁建立了它；否则保持从任务开始就存在，不编造来路。
    return best if float(best.get("end", 0)) > 0.0 else None


def _hold_edges(holds: list[dict], ops: list[dict], amap: dict) -> list[dict]:
    """保持节点的两条边：谁建立了它、它维持到谁（MAINTAIN until）。

    覆盖到中间某个操作不画边（那是“同层并行推进”，写在节点的 covers 上）；
    只画一条 maintain_until 指向它守着直到发生的那一步——边多了反而读不出
    “这个保持在哪里结束”。
    """
    omap = {o["id"]: o for o in ops}
    out: list[dict] = []
    for h in holds:
        target = (h.get("maintain_until") or [None])[0]
        src = _hold_entry_source(h, ops, amap)
        if src is not None and src["id"] != target:
            out.append({"from": src["id"], "to": h["id"], "relation": "enables",
                        "note": f"「{src['name']}」建立了「{h['name']}」所需的状态",
                        "inferred_by": "maintain_lift"})
        elif src is not None:
            h["entry_within"] = src["id"]      # 保持就是在这一步内部建立的，不另画边
        for cov in h.get("covers") or []:
            if cov == target or cov not in omap:
                continue
            # 保持与它覆盖的中间步骤是同时推进的，不是前后依赖：写成并行对。
            out.append({"from": h["id"], "to": cov, "relation": "parallel", "mutual": True,
                        "note": f"「{h['name']}」在「{omap[cov]['name']}」期间同时推进",
                        "inferred_by": "maintain_lift"})
        cov = omap.get(target)
        if cov is not None:
            stop = h.get("stop_event") or {}
            detail = (f"；停止事件：{stop.get('text')}" if isinstance(stop, dict)
                      and stop.get("text") else "")
            note = f"「{h['name']}」持续到「{cov['name']}」完成{detail}"
            ho = (h.get("handoff_to") or [None])[0]
            if ho and omap.get(ho):
                note = (f"「{h['name']}」保持到「{cov['name']}」完成；结束后由"
                        f"「{omap[ho]['name']}」接管执行器（控制交接）{detail}")
            out.append({"from": h["id"], "to": cov["id"], "relation": "maintain_until",
                        "note": note, "carries": h["name"], "inferred_by": "maintain_lift"})
    return out


def _edge_note(rel: str, A: dict, B: dict) -> str:
    if rel == "enables":
        return f"「{A['name']}」是「{B['name']}」的前置条件"
    if rel == "maintain_until":
        return f"「{A['name']}」保持到「{B['name']}」发生"
    return f"「{A['name']}」完成后才开始「{B['name']}」"


# ---------------------------------------------------------------
# 因果衔接：C_post 满足 C_pre → enables 边 + 意图链
# ---------------------------------------------------------------

def _carry_marks(ops: list[dict], amap: dict, edges: list[dict]) -> None:
    """跨操作的保持延续：前一个操作里的执行器动作一直保持到后一个操作期间。

    这是"持续关系"在执行层的样子：起身托举时建立的`双手保持抓握`会一直延续到放置
    才解除。图上不画成新边，而是标在相邻两步的边上（carries），因为它表达的是
    "前一步的执行器动作与后一步并行推进"，而不是额外的先后依赖。
    """
    for i in range(len(ops) - 1):
        A, B = ops[i], ops[i + 1]
        # 保持节点自己就是那个持续状态的载体，不再给它挂“上一步延续过来”的标记
        if str(A.get("mode") or "") == "maintain" or str(B.get("mode") or "") == "maintain":
            continue
        carried = []
        for r in A["atomic_refs"]:
            a = amap.get(r)
            if not a or str(a.get("mode")) != "maintain":
                continue
            s, e = float(a.get("start", 0)), float(a.get("end", 0))
            # “延续”要求它是在本步开始之前就已经建立的状态，而不是与本步同时开始：
            # 同时开始的保持属于本步自己的执行内容，不是前一步递过来的。
            if s < B["start"] - TIME_TOL and e > B["start"] + TIME_TOL:
                act = str(a.get("action") or "")
                exec_ = str(a.get("executor") or "")
                text = act if act.startswith(exec_) else f"{exec_}{act}"   # 避免"右手右手…"
                if text not in carried:
                    carried.append(text)
        if not carried:
            continue
        txt = "、".join(carried[:2])
        hit = next((e for e in edges if not e.get("mutual")
                    and (e["from"], e["to"]) == (A["id"], B["id"])), None)
        if hit is not None:
            hit["carries"] = txt
        else:
            edges.append({
                "from": A["id"], "to": B["id"], "relation": "maintain_until",
                "note": f"「{A['name']}」期间的 {txt} 一直保持到「{B['name']}」期间",
                "carries": txt, "inferred_by": "cross_op_maintain"})


def _phrase(action: dict, obj_tokens: list[str], limit: int = 8) -> str:
    """图上用的短短语：去掉执行器前缀、操作对象与连接词，只留动作本身。"""
    ex = str(action.get("executor") or "")
    out = str(action.get("action") or "").strip()
    if ex and out.startswith(ex):
        out = out[len(ex):].strip()
    for tok in obj_tokens:
        out = out.replace(tok, "")
    for sep in ("将", "把", "使"):
        idx = out.find(sep, 1)
        if 2 <= idx <= limit:
            out = out[:idx]
    out = out.strip(" 　，,。；;、的")
    return (out or ex)[:limit]


def _merge_pair_items(items: list[dict]) -> list[dict]:
    """同一保持内容的重复项去重、左右配对合并（右腿+左腿 → 双腿），图上不写两遍。"""
    pair_map = {"右腿": "双腿", "左腿": "双腿", "右手": "双手",
                "左手": "双手", "右臂": "双臂", "左臂": "双臂"}
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    for it in items:
        ph = str(it.get("phrase") or "")
        if ph not in buckets:
            buckets[ph] = []
            order.append(ph)
        buckets[ph].append(it)
    out: list[dict] = []
    for ph in order:
        group = buckets[ph]
        names = [str(g.get("executor") or "") for g in group]
        if len(set(names)) < len(names):
            names = list(dict.fromkeys(names))
        merged: list[str] = []
        used: set[int] = set()
        for i, nm in enumerate(names):
            if i in used:
                continue
            used.add(i)
            pair = pair_map.get(nm)
            partner = None
            if pair:
                for j in range(len(names)):
                    if j not in used and pair_map.get(names[j]) == pair:
                        partner = j
                        break
            if partner is not None:
                used.add(partner)
                merged.append(pair)
            else:
                merged.append(nm)
        item = dict(group[0])
        item["executor"] = "、".join(merged)
        out.append(item)
    return out


def _attach_coordination(ops: list[dict], amap: dict) -> None:
    """给每个操作节点补「主动执行器 / 协同保持执行器」（这一步谁在动、谁在保持）。

    事实来源是原子动作表本身：节点绑定的动作里 mode=motion/transition 的执行器在“动”；
    同一时段内 mode=maintain、执行器又不同的动作，就是这一步的“协同保持”（比如
    “提起”时右臂在抬、右手在保持抓握）。确定性推导，不依赖模型再推理一遍——
    “谁在保持”本来就写在动作表里。保持节点自身不挂协同（它本身就是那个保持）。
    """
    act_modes = {"motion", "transition"}
    maintains = [a for a in amap.values() if isinstance(a, dict)
                 and str(a.get("mode") or "").lower() == "maintain"]
    for op in ops:
        if str(op.get("mode") or "").lower() == "maintain":
            continue
        refs = [amap.get(r) for r in (op.get("atomic_refs") or [])]
        own = [a for a in refs if isinstance(a, dict)]
        primary = [a for a in own if str(a.get("mode") or "").lower() in act_modes]
        prim_ex = {str(a.get("executor") or "") for a in primary}
        try:
            s, e = float(op.get("start", 0)), float(op.get("end", 0))
        except (TypeError, ValueError):
            continue
        holding = []
        for a in maintains:
            ex = str(a.get("executor") or "")
            if not ex or ex in prim_ex:
                continue
            try:
                a_s, a_e = float(a.get("start", 0)), float(a.get("end", 0))
            except (TypeError, ValueError):
                continue
            if a_s <= e + TIME_TOL and a_e >= s - TIME_TOL:
                holding.append(a)
        if not primary and not holding:
            continue
        objs = [str(x) for x in (op.get("object") or []) if x]

        def item(a: dict, mode: str) -> dict:
            return {"executor": str(a.get("executor") or ""),
                    "phrase": _phrase(a, objs),
                    "action": str(a.get("action") or ""),
                    "mode": mode}

        prim_items, hold_items, seen = [], [], set()
        for a in primary:
            it = item(a, str(a.get("mode") or ""))
            key = (it["executor"], it["phrase"])
            if key not in seen:
                seen.add(key)
                prim_items.append(it)
        seen = set()
        for a in sorted(holding, key=lambda x: float(x.get("start") or 0)):
            it = item(a, "maintain")
            key = (it["executor"], it["phrase"])
            if key not in seen:
                seen.add(key)
                hold_items.append(it)
        op["coordination"] = {"primary": _merge_pair_items(prim_items),
                              "holding": _merge_pair_items(hold_items)}


def _chains(ops: list[dict], edges: list[dict]) -> list[dict]:
    omap = {o["id"]: o for o in ops}
    out: list[dict] = []
    for e in edges:
        if e.get("mutual") or e["relation"] not in ("sequence", "enables", "maintain_until"):
            continue
        A, B = omap.get(e["from"]), omap.get(e["to"])
        if not A or not B:
            continue
        best: tuple[float, str, str] | None = None
        for post in A["post"]:
            for pre in B["pre"]:
                s = _sim(post, pre)
                if s >= SIM_FLOOR and (best is None or s > best[0]):
                    best = (s, post, pre)
        if best:
            out.append({"from": A["id"], "to": B["id"],
                        "provides": best[2], "because": best[1],
                        "score": round(best[0], 2)})
    return out


# ---------------------------------------------------------------
# 分层：依赖边递增，并行/交替同层
# ---------------------------------------------------------------

def _layer(order: list[str], edges: list[dict], soft: list[tuple[str, str]]) -> dict[str, int]:
    hard = [(e["from"], e["to"]) for e in edges if not e.get("mutual")]
    layer: dict[str, int] = dict.fromkeys(order, 0)
    for _ in range(len(order) + 4):
        changed = False
        for u, v in hard:
            if layer[v] < layer[u] + 1:
                layer[v] = layer[u] + 1
                changed = True
        for u, v in soft:
            if u not in layer or v not in layer:
                continue
            top = max(layer[u], layer[v])
            if layer[u] != top or layer[v] != top:
                layer[u] = layer[v] = top
                changed = True
        if not changed:
            used = sorted(set(layer.values()))
            remap = {v: i for i, v in enumerate(used)}
            return {k: remap[v] for k, v in layer.items()}
    fallback: dict[str, int] = dict.fromkeys(order, 0)      # 不收敛：只用依赖边分层
    for _ in range(len(order) + 1):
        changed = False
        for u, v in hard:
            if fallback[v] < fallback[u] + 1:
                fallback[v] = fallback[u] + 1
                changed = True
        if not changed:
            break
    used = sorted(set(fallback.values()))
    remap = {v: i for i, v in enumerate(used)}
    return {k: remap[v] for k, v in fallback.items()}


# ---------------------------------------------------------------
# 入口
# ---------------------------------------------------------------

def _inner_relations(op: dict, relations: list[dict], amap: dict) -> None:
    """节点内部的并行/交替：操作内部各执行器怎么协同（如“双腿交替迈步”）。

    节点间没有并行不代表没有并行——“搬运纸箱”内部就是“双腿交替”同时“双臂保持托举”。
    这层信息留在节点上，换执行体时正好对应该执行体的多轴协同能力。
    """
    refs = set(op["atomic_refs"])
    alt_pairs: list[list[str]] = []
    par_count = 0
    for r in relations:
        if not isinstance(r, dict):
            continue
        f, t = r.get("from"), r.get("to")
        if f not in refs or t not in refs:
            continue
        rel = str(r.get("relation") or "")
        if rel == "parallel":
            par_count += 1
        elif rel == "alternation":
            pf = str((amap.get(f) or {}).get("executor") or "")
            pt = str((amap.get(t) or {}).get("executor") or "")
            if pf and pt and [pf, pt] not in alt_pairs and [pt, pf] not in alt_pairs:
                alt_pairs.append([pf, pt])
    op["inner_parallel_count"] = par_count
    op["inner_alternations"] = alt_pairs


def build(task_nodes: dict | list | None, actions: list[dict],
          relations: list[dict], *, semantic_only: bool = False) -> dict:
    """构建操作图：节点（操作，含执行器属性与意图）+ 边（先后/并行/交替/使能）+ 意图链。"""
    raw = task_nodes.get("task_nodes") if isinstance(task_nodes, dict) else task_nodes
    raw = [n for n in (raw or []) if isinstance(n, dict)]
    amap = {a.get("id"): a for a in actions or [] if isinstance(a, dict)}

    empty = {"nodes": [], "edges": [], "layers": [], "intent_chain": [],
             "parallel_groups": [], "alternation_pairs": [], "orchestration": "",
             "stats": {"nodes": 0, "edges": 0, "sequence": 0, "parallel": 0,
                       "alternation": 0, "enables": 0, "maintain_until": 0,
                       "holds": 0, "executors": 0}}
    if not raw:
        return empty

    ops = _to_operations(raw, amap)
    if not ops:
        return empty
    holds = []
    if semantic_only:
        edges = _reduce_sequences(_edges(ops, relations))
    else:
        _adopt_orphan_maintains(ops, amap)
        steps = _lift_orphan_steps(ops, amap)
        if steps:
            ops = ops + steps
        for o in ops:
            _inner_relations(o, relations or [], amap)
        holds = _lift_maintains(ops, amap)
        hold_ids = {h["id"] for h in holds}
        if holds:
            ops = sorted(ops + holds, key=lambda o: (o["start"], o["end"], o["id"]))
        split = _split_release_steps(ops, amap, holds)
        if split:
            ops = sorted(ops + split, key=lambda o: (o["start"], o["end"], o["id"]))
            _resync_holds_after_split(ops, holds, split)
        if holds or split:
            for o in ops:
                _inner_relations(o, relations or [], amap)
        # 保持节点与其他操作的边由 _hold_edges 统一定义：自动推出来的边只会在这里打架
        # （同一个动作既被推成 parallel 又被推成 sequence），所以涉及保持节点的自动边全部让位。
        auto = [e for e in _edges(ops, relations)
                if e["from"] not in hold_ids and e["to"] not in hold_ids]
        edges = _reduce_sequences(auto)
        edges += _hold_edges(holds, ops, amap)
        # 拆分出来的释放步骤：它与源操作之间是执行依赖（先就位、再释放），
        # 不是“示范里碰巧先后”。标出来，后面 program / 契约才不会再把它当弱边丢掉。
        omap0 = {o["id"]: o for o in ops}
        for o in ops:
            for sid in (o.get("split_steps") or []):
                e = next((x for x in edges if x["from"] == o["id"] and x["to"] == sid), None)
                if e is None:
                    continue
                e["inferred_by"] = "release_split"
                e["note"] = (f"「{o['name']}」就位后执行「{omap0[sid]['name']}」："
                             f"解除作用，让执行器回到可用状态")
        _carry_marks(ops, amap, edges)
        # 节点内的协同结构：主动执行器（在动）与协同保持执行器（保持），写进节点属性
        _attach_coordination(ops, amap)
        # 先验步骤（如抓握前的预张开）：把“必要前提”写到边上、写进后继操作的前提里。
        # 这是必要性推理，不是效果证据：合着的手物理上包裹不了物体，无论模型有没有看到。
        omap1 = {o["id"]: o for o in ops}
        for o in ops:
            if not o.get("inferred") or not o.get("prepares"):
                continue
            tgt = omap1.get((o["prepares"] or [None])[0])
            if tgt is None:
                continue
            cond = (o.get("post") or [""])[0]
            note = (f"「{o['name']}」完成后才开始「{tgt['name']}」；这是它的必要前提——"
                    f"不先做到这一步，后续动作物理上无法成立（功能先验推理，待画面核实）")
            hit = False
            for e in edges:
                if e["from"] == o["id"] and e["to"] == tgt["id"]:
                    e["note"] = note
                    e["inferred_by"] = "prior_step_lift"
                    hit = True
            if not hit:
                edges.append({"from": o["id"], "to": tgt["id"], "relation": "sequence",
                              "note": note, "inferred_by": "prior_step_lift"})
            if cond:
                tgt.setdefault("pre_inferred", []).append(
                    f"{cond}（必要前提，由「{o['name']}」提供；功能先验推理，待画面核实）")
    chains = _chains(ops, edges)
    omap = {o["id"]: o for o in ops}

    # 有条件衔接的先后边升级为"使能"：前一个操作的后置效果正是后一个的前置条件，
    # 这就是领导要的"操作意图 = 前置/后置条件"——因果关系落到边上，不是只写在表格里。
    linked = {(c["from"], c["to"]) for c in chains}
    for e in edges:
        if e["relation"] == "sequence" and (e["from"], e["to"]) in linked:
            e["relation"] = "enables"
            a, b = omap.get(e["from"]), omap.get(e["to"])
            e["note"] = f"「{(a or {}).get('name')}」为「{(b or {}).get('name')}」提供前置条件"

    # 意图链回填：这个操作为了哪个操作、提供了什么
    for c in chains:
        src, dst = omap.get(c["from"]), omap.get(c["to"])
        if src and dst:
            src["purpose"] = f"为「{dst['name']}」提供：{c['provides']}"
            c["from_name"], c["to_name"] = src["name"], dst["name"]

    soft_pairs = [(e["from"], e["to"]) for e in edges if e.get("mutual")]
    layer = _layer([o["id"] for o in ops], edges, soft_pairs)
    for o in ops:
        o["layer"] = int(layer.get(o["id"], 0))

    grouped: dict[int, list[str]] = {}
    for o in ops:
        grouped.setdefault(o["layer"], []).append(o["id"])
    layers = [grouped[c] for c in sorted(grouped)]

    # 并行组 / 交替对（渲染成并列标记用）
    par_edges = [e for e in edges if e["relation"] == "parallel"]
    alt_edges = [e for e in edges if e["relation"] == "alternation"]
    groups = _group_pairs([(e["from"], e["to"]) for e in par_edges])
    counters = Counter(e["relation"] for e in edges)

    return {
        "nodes": ops,
        "edges": edges,
        "layers": layers,
        "intent_chain": chains,
        "parallel_groups": groups,
        "alternation_pairs": [[e["from"], e["to"]] for e in alt_edges],
        "orchestration": _orchestration(ops, edges, groups),
        "stats": {
            "nodes": len(ops),
            "edges": len(edges),
            "sequence": counters.get("sequence", 0),
            "parallel": counters.get("parallel", 0),
            "alternation": counters.get("alternation", 0),
            "enables": counters.get("enables", 0),
            "maintain_until": counters.get("maintain_until", 0),
            "holds": len(holds),
            "executors": len({p for o in ops for p in o["executors"]}),
        },
    }


def _group_pairs(pairs: list[tuple[str, str]]) -> list[list[str]]:
    """把两两并行对聚成并行组（并查集）。"""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
    comps: dict[str, list[str]] = defaultdict(list)
    for node in list(parent):
        comps[find(node)].append(node)
    return [sorted(v) for v in comps.values() if len(v) > 1]


def _orchestration(ops: list[dict], edges: list[dict], groups: list[list[str]]) -> str:
    """一句话调度口径：谁先、谁与谁并行（同时开始 / 同时结束）。"""
    omap = {o["id"]: o for o in ops}
    seq = [e for e in edges
           if e["relation"] in ("sequence", "enables", "maintain_until") and not e.get("mutual")]
    seq.sort(key=lambda e: (omap[e["from"]]["start"] if e["from"] in omap else 0,
                            omap[e["to"]]["start"] if e["to"] in omap else 0))
    parts = [f"{omap[e['from']]['name']} → {omap[e['to']]['name']}" for e in seq
             if e["from"] in omap and e["to"] in omap]
    flows = ("；".join(parts[:6]))
    if groups:
        gtext = "；".join("∥ ".join(omap[i]["name"] for i in g if i in omap) for g in groups)
        flows = f"{flows}（并行：{gtext}）" if flows else f"并行：{gtext}"
    return flows
