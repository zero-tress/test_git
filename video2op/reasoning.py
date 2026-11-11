#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推理修正（确定性）：让意图参与推理，让视频约束推理，并产生**可检查的图修改**。

这一步回答"图里的每条关系、每个操作，是否真的成立"：

  · 候选依赖      A → B 声称"A 为 B 提供条件 X"，先追问 X 是什么；
  · 效果校验      A 是否实际观察到了 X，不把能力或动作名称当成成功证据；
  · 前置覆盖      B 的每条前置条件：由有效前驱或当时的观测状态支持，还是待核实；
  · 缺口取证      前置条件无人提供时，回头扫描全部原子动作（含未被任何操作认领的），
                  看有没有动作能提供它——有证据就指出证据，没有才算候选缺口；
  · 持续约束      依赖"握持/托举/支撑"这类条件的操作，其过程内必须有保持动作覆盖；
  · 证据校验      每个操作声明的"预期效果"要能在画面证据里找到落点（预期 ≠ 实际）。

处理结果只作用于**依赖关系与必要子图**，绝不改写视频事实：

  keep      条件成立，保留依赖
  downgrade 因果未获证据支持 → 保留观测顺序和候选解释（不删节点、不删动作）
  flag      证据不足或存在持续约束缺口 → 标为待复核
  gap       确无来源 → 提出**候选缺口**（需要找证据，不写成事实）

两条纪律（谈话记录明确要求）：
  1. 不能因为"A 没支持 B"就把 A 删掉——A 可能确实发生了，只是与 B 无因果；
  2. 推理认为"应当存在一个操作"时，只能登记为候选缺口，不能直接写进图。
另外，"视频里 A 先于 B"是观测，"执行 B 必须先完成 A"是更强的判断——两者在边上分
`basis` 区分，不把示范者偶然的顺序固化成执行约束。
"""

from __future__ import annotations

from .evidence import matches, observed_states, support
from .operations import TIME_TOL
from .vocab import hold_category, is_hold_constraint

# Legacy preconditions that also imply a sustained state; explicit C_const is preferred.
PERSISTENT_WORDS = ("保持抓握", "稳定握持", "保持托举", "被双臂托举", "保持抬起",
                    "站立支撑", "保持接触")

# 接触类约束（手要稳住物体）可以由同侧手臂的位姿保持来承担：
# 手稳定接触靠的是臂别动，而不是另一条“手”的保持动作。
HAND_ARM_PAIR = {"左手": "左臂", "右手": "右臂"}


def _covering_actions(op: dict, amap: dict, omap: dict) -> list[dict]:
    """能覆盖该操作全过程的保持动作：它自己的 + 被提升的 MAINTAIN 节点的。"""
    ids = list(op.get("atomic_refs") or [])
    for hid in op.get("held_by") or []:
        h = omap.get(hid)
        if h:
            ids += list(h.get("atomic_refs") or [])
    return [amap[i] for i in ids if i in amap]


def _covers_span(a: dict, op: dict) -> bool:
    return (float(a.get("start", 0)) <= float(op.get("start", 0)) + TIME_TOL
            and float(a.get("end", 0)) >= float(op.get("end", 0)) - TIME_TOL)


def _action_category(a: dict) -> str:
    text = (str(a.get("action") or "") + str(a.get("force_role") or "")
            + str(a.get("state_before") or "") + str(a.get("state_after") or ""))
    return hold_category(text)


# 保持动作能承担哪类约束：托举保持隐含维持姿态，接触保持同理；反过来不成立
# （臂的位姿保持不能证明抓握）。同侧手臂的位姿保持还可以承担本侧手的接触约束——
# 手指合拢时要稳定接触，靠的就是手臂别动。
COVER_RELATION = {
    "grasp": {"grasp"},
    "support": {"support", "pose"},
    "contact": {"contact", "pose"},
    "pose": {"pose"},
}


def _actor_related(actor: str, op: dict) -> bool:
    """保持动作的执行器是否与本操作相关。

    “腿上站立支撑”不能替“药瓶保持竖直”撑腰——部位不对，类别再像也不算。
    同侧的手臂与手视为同一条执行链（手稳定靠臂不动）。
    """
    if not actor:
        return False
    executors = list(op.get("executors") or [])
    if actor in executors:
        return True
    if any(HAND_ARM_PAIR.get(p) == actor for p in executors):
        return True
    if HAND_ARM_PAIR.get(actor) in executors:
        return True
    return False


def _constraint_matches_action(cond: str, a: dict, op: dict) -> bool:
    """约束是否被这条保持动作承担。

    先看观测状态文本；再看执行器是否相关（部位链），最后看类别是否相容
    （含托举→姿态、接触→姿态的包含关系，以及同侧手臂承担本侧手接触约束）。
    """
    actor = str(a.get("executor") or "")
    if any(matches(cond, s) for s in observed_states(a)) and _actor_related(actor, op):
        return True
    if not _actor_related(actor, op):
        return False
    cat_c, cat_a = hold_category(cond), _action_category(a)
    if cat_c in COVER_RELATION.get(cat_a, {cat_a}):
        return True
    # 同侧手臂的位姿保持可以承担本侧手的接触/抓握约束：手稳住靠的是臂不动。
    if cat_a == "pose" and cat_c in ("grasp", "contact"):
        return any(HAND_ARM_PAIR.get(p) == actor for p in (op.get("executors") or []))
    return False

def _unlockable(B: dict, src_end: float, atomic: list[dict]) -> dict | None:
    """B 内部有没有“在源条件产生之后才开始”的子步骤——有就是中间触发点。

    这是「a 执行一半要发 b」的可计算形式：a 的效果在 src_end 产生，b 里从那一刻
    起才开始的那一步，就是被触发的那一步（例：下蹲在 3.5s 完成，纸箱的“接触”
    从 3.5s 才开始）。这样就不用把“重叠”降级成并列，也能说清怎么发。
    """
    amap = {a.get("id"): a for a in atomic if isinstance(a, dict)}
    later = []
    for r in B.get("atomic_refs") or []:
        a = amap.get(r)
        if a and float(a.get("start", 0)) >= src_end - TIME_TOL:
            later.append(a)
    if not later:
        return None
    later.sort(key=lambda a: (float(a.get("start", 0)), int(a.get("id", 0))))
    return {
        "ids": [a.get("id") for a in later],
        "labels": "、".join(f"#{a.get('id')} {a.get('executor')}{a.get('action')}"
                            for a in later[:3]),
    }


def _edge_checks(ops: list[dict], edges: list[dict], chains: list[dict],
                 atomic: list[dict]) -> list[dict]:
    omap = {o["id"]: o for o in ops}
    by_pair = {(c["from"], c["to"]): c for c in chains}
    out: list[dict] = []
    for e in edges:
        if e.get("mutual") or e["relation"] not in ("enables", "sequence", "maintain_until"):
            continue
        A, B = omap.get(e["from"]), omap.get(e["to"])
        if not A or not B:
            continue
        base = {"id": f"edge:{A['id']}->{B['id']}", "kind": "edge_support",
                "edge": [A["id"], B["id"]]}
        c = by_pair.get((A["id"], B["id"]))
        if not c:
            out.append(dict(base, verdict="order_only",
                            question=f"「{A['name']}」与「{B['name']}」之间是什么关系？",
                            evidence="两者之间没有可判定的条件衔接，只有时间上的先后",
                            action="downgrade" if e["relation"] == "enables" else "keep",
                            note="按「仅观测顺序」保留：不固化为执行依赖"))
            continue
        # A condition match and a capable hand do not prove this action produced it.
        evidence = support(c["provides"], A, atomic)
        q = f"「{A['name']}」能否提供「{c['provides']}」？"
        if not evidence:
            out.append(dict(base, verdict="unknown", question=q,
                            evidence="缺少该操作实际产生此条件的观测后状态；能力与文字相似不能证明效果",
                            action="downgrade", note="保留候选解释，撤销已成立的因果依赖"))
            continue
        if float(A["end"]) <= float(B["start"]) + TIME_TOL:
            out.append(dict(base, verdict="supported", question=q,
                            evidence=f"观测后状态对应条件；来源动作 {[a['id'] for a in evidence]}",
                            action="keep", note="条件有观测支持；运行时仍需检查谓词"))
            continue
        # 源操作尚未结束：先看 B 内部有没有“在源条件产生之后才开始”的子步骤。
        # 有 → 这就是中间触发点（保保留因果，只把触发点说清楚）；没有 → 才能降级。
        src = max(evidence, key=lambda a: float(a.get("end", 0)))
        src_end = float(src.get("end", 0))
        unlock = _unlockable(B, src_end, atomic)
        if unlock:
            out.append(dict(
                base, verdict="supported_partial", question=q,
                evidence=f"观测后状态在 {src_end}s 产生（动作 #{src.get('id')}）；"
                         f"「{B['name']}」的 {unlock['labels']} 在该时点之后才开始，"
                         f"构成中间触发条件",
                action="keep",
                note="保留因果，但触发点不是操作起点：运行时等源动作完成事件再发后续步骤",
                trigger={"type": "partial", "predicate": c["provides"],
                         "event": {"type": "action_completed", "ref": src.get("id"),
                                   "at": src_end},
                         "unlocks": unlock["ids"],
                         "unlock_actions": unlock["labels"]}))
        else:
            out.append(dict(base, verdict="unknown", question=q,
                            evidence="源操作尚未结束，且后继操作没有在该时点之后才开始的子步骤；"
                                     "需要明确中间状态触发条件，不能使用最终效果启动后继",
                            action="downgrade", note="重叠时段保留为候选触发，不伪造完成依赖"))
    return out


# ---------------------------------------------------------------
# ② 前置覆盖 + 缺口取证
# ---------------------------------------------------------------

def _pre_check(op: dict, pre: str, verdict: str, evidence: str,
               action: str, note: str) -> dict:
    return {"id": f"pre:{op['id']}:{pre[:12]}", "kind": "pre_coverage",
            "node": op["id"], "condition": pre,
            "question": f"「{op['name']}」的前置条件「{pre}」由谁提供？",
            "verdict": verdict, "evidence": evidence, "action": action, "note": note}


def _pre_coverage_checks(ops: list[dict], edges: list[dict],
                         atomic: list[dict]) -> list[dict]:
    omap = {o["id"]: o for o in ops}
    preds: dict[str, list[str]] = {o["id"]: [] for o in ops}
    for e in edges:
        if e.get("basis") == "required_dependency" and e["to"] in preds and e["from"] in omap:
            preds[e["to"]].append(e["from"])
    bound = {r for o in ops for r in o["atomic_refs"]}

    out: list[dict] = []
    for op in ops:
        for pre in op["pre"]:
            sources = []
            for pid in preds.get(op["id"], []):
                p = omap[pid]
                # 提供方只要不晚于接收方开始即可：部分重叠的依赖由边上的 trigger 说明
                # 触发点（不能把“操作级时间先后”当成唯一准入条件）。
                if float(p["start"]) > float(op["start"]) + TIME_TOL:
                    continue
                hit = next((post for post in p["post"] if matches(post, pre)
                            and support(pre, p, atomic)), None)
                if hit:
                    sources.append(f"「{p['name']}」的后置效果「{hit}」")
            if not sources:
                for other in ops:
                    if (other["id"] == op["id"]
                            or float(other["start"]) > float(op["start"]) + TIME_TOL):
                        continue
                    hit = next((post for post in other["post"]
                                if matches(pre, post) and support(pre, other, atomic)), None)
                    if hit:
                        # A source outside the dependency graph needs review, not silent activation.
                        out.append(_pre_check(op, pre, "candidate_source",
                                              f"「{other['name']}」有对应后状态，但尚未建立有效依赖",
                                              "flag", "先核实并补充依赖，再用于调度"))
                        break
                else:
                    hit = None
                if hit:
                    continue

            if sources:
                out.append(_pre_check(op, pre, "provided", "；".join(sources),
                                      "keep", "条件有明确来源"))
                continue
            if any(abs(float(a.get("start", 0)) - float(op["start"])) <= TIME_TOL
                   and any(matches(pre, s) for s in observed_states(a, "state_before")) for a in atomic):
                out.append(_pre_check(
                    op, pre, "ambient",
                    "有对应的观测前状态；运行时仍需重新检测",
                    "keep", "有证据的环境前提"))
                continue

            # 缺口取证：回头扫全部原子动作（含没被任何操作认领的），看谁提供了这个条件。
            # 必须在本操作开始之前，并且实际后状态与条件对应。
            found = []
            for a in atomic:
                if not isinstance(a, dict) or a.get("id") in bound:
                    continue
                if float(a.get("end", 0)) > float(op["start"]) + TIME_TOL:
                    continue
                if any(matches(pre, s) for s in observed_states(a)):
                    found.append(f"未被认领的动作 #{a.get('id')}「{a.get('executor')}"
                                 f"{a.get('action')}」的状态为「{a.get('state_after') or '—'}」")
            if found:
                out.append(_pre_check(op, pre, "evidenced_by_unclaimed",
                                      found[0], "flag",
                                      "找到了证据：把该动作认领进本条前置条件的来源，"
                                      "并在图中补一条依赖（不新增任何事实）"))
            else:
                out.append(_pre_check(op, pre, "unprovided",
                                      "前驱操作的后置效果与全部原子动作里都没有能提供"
                                      "该条件的内容", "gap",
                                      "候选缺口：可能存在被漏识别的操作；"
                                      "本步只登记候选，不写成视频事实"))
    return out


# ---------------------------------------------------------------
# ③ 持续约束
# ---------------------------------------------------------------

def _hold_checks(ops: list[dict], atomic: list[dict]) -> list[dict]:
    amap = {a.get("id"): a for a in atomic if isinstance(a, dict)}
    omap = {o["id"]: o for o in ops}
    out: list[dict] = []
    for op in ops:
        invariants = list(dict.fromkeys(op.get("invariants") or []))
        needed = list(dict.fromkeys(
            [c for c in invariants if is_hold_constraint(c)]
            + [pre for pre in op["pre"] if any(w in pre for w in PERSISTENT_WORDS)]))
        delegated = [c for c in invariants if not is_hold_constraint(c)]
        if float(op.get("end", 0)) - float(op.get("start", 0)) <= 0.4:
            continue
        if not needed:
            # 安全类约束不需要“一条保持动作”来承担：它由规划与力控守住。
            # 这条记录不是“检验通过”，而是把“为什么不要求保持动作”写清楚。
            if delegated:
                out.append({"id": f"hold:{op['id']}", "kind": "hold", "node": op["id"],
                            "question": f"「{op['name']}」期间的约束由谁保证？",
                            "verdict": "delegated",
                            "evidence": "由规划与控制器保证的边界条件：" + "；".join(delegated),
                            "action": "keep",
                            "note": "安全类约束不要求覆盖全程的保持动作；运行期由规划与力控守住，"
                                    "校验不把它当成“缺保持”"})
            continue
        covering = [a for a in _covering_actions(op, amap, omap)
                    if not a.get("inferred") and str(a.get("mode")) == "maintain"
                    and _covers_span(a, op)]
        inferred_covering = [a for a in _covering_actions(op, amap, omap)
                             if a.get("inferred") and str(a.get("mode")) == "maintain"
                             and _covers_span(a, op)]
        covers = list(dict.fromkeys(
            cond for cond in needed for a in covering
            if _constraint_matches_action(cond, a, op)))
        q = f"「{op['name']}」期间「{needed[0]}」是否持续成立？"
        missing = [c for c in needed if c not in covers]
        if not missing:
            out.append({"id": f"hold:{op['id']}", "kind": "hold", "node": op["id"],
                        "question": q, "verdict": "covered",
                        "evidence": f"对应状态且覆盖整个过程：{'、'.join(covers)}",
                        "action": "keep", "note": "持续约束满足",
                        "delegated": list(delegated)})
        else:
            # 观测到的保持动作不能证明它（推断不是事实）；但若图上已经有一条推理
            # 补全的保持动作在承担它，就不能再说“没有任何落点”——那是两件事。
            by_inferred = list(dict.fromkeys(
                cond for cond in missing for a in inferred_covering
                if _constraint_matches_action(cond, a, op)))
            check = {"id": f"hold:{op['id']}", "kind": "hold", "node": op["id"],
                     "question": q, "verdict": "uncovered",
                     "evidence": f"该操作依赖「{missing[0]}」在过程中持续成立，但 "
                                 f"{op['start']}~{op['end']}s 内没有观测到的、覆盖全程的保持动作",
                     "action": "flag",
                     "note": "需复核：要么补一条保持动作，要么该条件无需全程保持",
                     "delegated": list(delegated)}
            if by_inferred:
                check["covered_by_inferred"] = by_inferred
                check["evidence"] += "；图上由推理补全的保持动作承担（待画面核实），不算结构性缺口"
                check["note"] = "持续约束有承担者（推理补全），复核重点是去画面里找它"
            out.append(check)
    return out


# ---------------------------------------------------------------
# ④ 预期效果 vs 画面证据
# ---------------------------------------------------------------

def _evidence_checks(ops: list[dict], atomic: list[dict]) -> list[dict]:
    amap = {a.get("id"): a for a in atomic if isinstance(a, dict)}
    out: list[dict] = []
    for op in ops:
        if not op["post"]:
            continue
        observed, acts = [], []
        view = dict(op)
        # 被拆出去的步骤（如释放）仍然是本步的证据来源：拆分只改调度边界，
        # 不改写“这一步实际做了哪些动作”。预期效果往往正是在那一步完成后才成立的，
        # 所以视图的结束时刻也要跟着靠后，否则证据会被时间条件挡在门外。
        split_refs = list(op.get("split_action_refs") or [])
        view["atomic_refs"] = list(op.get("atomic_refs") or []) + split_refs
        if split_refs:
            view["end"] = max([float(op.get("end") or 0)]
                              + [float((amap.get(r) or {}).get("end", 0)) for r in split_refs])
        for r in view["atomic_refs"]:
            a = amap.get(r) or {}
            for v in observed_states(a):
                if v not in observed:
                    observed.append(v)
        hit = [post for post in op["post"] if support(post, view, atomic)]
        op["effect_evidence"] = [{"expected": post,
                                  "status": "observed" if post in hit else "unverified",
                                  "atomic_refs": [a["id"] for a in support(post, view, atomic)]}
                                 for post in op["post"]]
        q = f"「{op['name']}」声明的效果在画面证据里有无落点？"
        if len(hit) == len(op["post"]):
            out.append({"id": f"evidence:{op['id']}", "kind": "evidence", "node": op["id"],
                        "question": q, "verdict": "evidenced",
                        "evidence": f"有观测后状态支持的效果：{'、'.join(hit)}"
                                    + (f"（证据：{'；'.join((observed + acts)[:2])}）"
                                       if (observed + acts) else ""),
                        "action": "keep", "note": "预期效果与观测证据对应上了",
                        "expected": list(op["post"]), "observed": observed[:4]})
        else:
            out.append({"id": f"evidence:{op['id']}", "kind": "evidence", "node": op["id"],
                        "question": q, "verdict": "weak",
                        "evidence": "尚未全部找到对应的观测后状态；动作名称、前状态和推断不算成功证据（预期："
                                    + "；".join(op["post"][:2]) + "）",
                        "action": "flag",
                        "note": "预期效果尚无证据：可能识别遗漏，也可能由后续操作达成",
                        "expected": list(op["post"]), "observed": observed[:4]})
    return out


# ---------------------------------------------------------------
# 入口
# ---------------------------------------------------------------

def audit(bundle: dict) -> dict:
    """对操作图做一轮推理修正，并把结论写回图（边降级 / 依赖基准 / 缺口登记）。"""
    graph = bundle.get("operations") or {}
    ops = graph.get("nodes") or []
    edges = graph.get("edges") or []
    chains = graph.get("intent_chain") or []
    atomic = (bundle.get("atomic") or {}).get("atomic_actions") or []
    if not ops:
        return {"checks": [], "revisions": [], "gaps": [],
                "stats": {"checks": 0, "supported": 0, "downgraded": 0,
                          "gaps": 0, "flagged": 0}}

    checks = _edge_checks(ops, edges, chains, atomic)

    n = 0

    def rid() -> str:
        nonlocal n
        n += 1
        return f"rev{n}"

    revisions: list[dict] = []
    gaps: list[dict] = []

    # 每条依赖标注基准：执行依赖（有条件支持）还是仅观测顺序
    for e in edges:
        if e.get("mutual"):
            continue
        if e.get("inferred_by") == "release_split":
            # 拆分边界：释放必须发生在就位之后——这是调度顺序，不是“示范里碰巧先后”。
            target = next((o for o in ops if o["id"] == e["to"]), {})
            e["basis"] = "required_dependency"
            e["support"] = "split_schedule"
            e["trigger"] = {"type": "all",
                             "predicates": list(target.get("pre") or []),
                             "event": {"type": "operation_completed", "ref": e["from"]}}
            continue
        c = next((x for x in chains if x["from"] == e["from"] and x["to"] == e["to"]), None)
        check = next((x for x in checks if x.get("edge") == [e["from"], e["to"]]), {})
        supported = check.get("verdict") in ("supported", "supported_partial")
        e["basis"] = "required_dependency" if supported else "observed_order"
        e["support"] = "observed_state" if supported else "unverified" if c else "order"
        if supported:
            e["trigger"] = check.get("trigger") or {
                "type": "all", "predicates": [c["provides"]],
                "event": {"type": "operation_completed", "ref": e["from"]}}

    # Check preconditions only AFTER rejected dependencies have lost authority.
    if bundle.get("learning_layer") == "semantic":
        constraint_checks = [
            {"id": f"constraint:{o['id']}", "kind": "constraint", "node": o["id"],
             "question": "持续约束是否在操作期间成立？", "verdict": "unverified",
             "evidence": "；".join(o.get("invariants") or []), "action": "flag",
             "note": "语义约束保留；需连续状态观测或执行层检测器确认，不补保持动作"}
            for o in ops if o.get("invariants")]
    else:
        constraint_checks = _hold_checks(ops, atomic)
    checks += (_pre_coverage_checks(ops, edges, atomic)
               + constraint_checks + _evidence_checks(ops, atomic))

    for c in checks:
        if c["kind"] == "edge_support" and c["action"] == "downgrade":
            fid, tid = c.get("edge") or (None, None)
            e = next((x for x in edges if x["from"] == fid and x["to"] == tid), None)
            if not e:
                continue
            before = e["relation"]
            src = next(o for o in ops if o["id"] == fid)
            dst = next(o for o in ops if o["id"] == tid)
            overlap = src["start"] < dst["end"] - TIME_TOL and dst["start"] < src["end"] - TIME_TOL
            e["relation"] = "parallel" if overlap else "sequence"
            e["basis"] = "observed_overlap" if overlap else "observed_order"
            if overlap:
                e["mutual"] = True
            e["downgraded"] = True
            e["downgrade_reason"] = c["evidence"]
            e["note"] = "候选因果未获证据支持；仅保留示范中的时间关系"
            e.pop("trigger", None)
            revisions.append({"id": rid(), "kind": "downgrade_edge",
                              "target": f"{fid} → {tid}", "before": before,
                              "after": e["relation"] + "（仅观测时间关系）", "why": c["evidence"],
                              "note": "只改依赖语义，保留观测到的先后；节点与动作不动"})
        elif c["kind"] == "pre_coverage" and c["action"] == "gap":
            op = next((o for o in ops if o["id"] == c.get("node")), None)
            gaps.append({"node": c.get("node"), "node_name": (op or {}).get("name"),
                         "condition": c.get("condition"), "missing": c["question"],
                         "evidence": c["evidence"],
                         "candidate": "检查是否存在提供该条件但未被识别的操作",
                         "status": "candidate"})
            revisions.append({"id": rid(), "kind": "propose_gap",
                              "target": c.get("node") or "", "before": "—",
                              "after": "候选缺口（待证据）", "why": c["evidence"],
                              "note": "推理结果不直接写成视频事实"})
        elif c["action"] in ("flag",):
            revisions.append({"id": rid(), "kind": "flag_for_review",
                              "target": c["id"], "before": "—", "after": "待复核",
                              "why": c["evidence"], "note": c["note"]})

    # Refresh derived explanations and counters so the report cannot retain a rejected cause.
    from collections import Counter

    from .operations import _group_pairs, _layer, _orchestration
    rejected = {(e["from"], e["to"]) for e in edges if e.get("downgraded")}
    graph["candidate_intent_chain"] = [c for c in chains if (c["from"], c["to"]) in rejected]
    graph["intent_chain"] = [c for c in chains if (c["from"], c["to"]) not in rejected]
    for op in ops:
        op["purpose"] = "；".join(f"为「{c.get('to_name', c['to'])}」提供：{c['provides']}"
                                  for c in graph["intent_chain"] if c["from"] == op["id"])
    counts = Counter(e["relation"] for e in edges)
    graph["parallel_groups"] = _group_pairs([(e["from"], e["to"]) for e in edges
                                             if e["relation"] == "parallel"])
    levels = _layer([o["id"] for o in ops], edges,
                    [(e["from"], e["to"]) for e in edges if e.get("mutual")])
    for op in ops:
        op["layer"] = levels[op["id"]]
    graph["layers"] = [[o["id"] for o in ops if o["layer"] == layer]
                       for layer in sorted(set(levels.values()))]
    graph.setdefault("stats", {}).update({k: counts[k] for k in
                                         ("sequence", "enables", "parallel", "alternation")})
    graph["orchestration"] = _orchestration(ops, edges, graph.get("parallel_groups") or [])
    good = ("supported", "supported_partial", "provided", "covered", "evidenced", "ambient")
    stats = {
        "checks": len(checks),
        "supported": sum(1 for c in checks if c["verdict"] in good),
        "partial_triggers": sum(1 for c in checks if c["verdict"] == "supported_partial"),
        "downgraded": sum(1 for c in checks if c["action"] == "downgrade"),
        "gaps": len(gaps),
        "flagged": sum(1 for c in checks if c["action"] == "flag"),
        "order_only": sum(1 for c in checks if c["verdict"] == "order_only"),
    }
    return {"checks": checks, "revisions": revisions, "gaps": gaps, "stats": stats}
