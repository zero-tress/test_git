#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门控（确定性）：把"操作之间的转移条件"显式化成可判定真值的门控点。

一句话口径（领导给的定义，落在数据上就是这三项的合取）：

    关键门控 G = 前序操作所需效果已成立
                 ∧ 下一操作前置条件已成立
                 ∧ 必要的场景与持续约束已成立

三值状态，互相不可顶替：

    T  证据确认满足        —— 连线画实线（放行）
    F  证据确认不满足      —— 连线画虚线（阻断；修条件或补操作）
    U  未观察到 / 尚未确认 —— 连线画虚线（等待证据）

图面上只有实线与虚线两种线型、全图线色统一为黑，且不写 T/U/F 字母（菱形只留序号）；
状态与依据在悬停详情、报告「门控明细」与工作台详情里。

**U 既不是 F 也不是 T**：没有证据时既不能放行、也不能判死。这条纪律决定门控是
"给人看的解释"还是"能接执行的开关"——把 U 当 T 会放开一个没确认的转移，把 U 当
F 会把一个可能真发生过的操作判死。

门控点的条件从四个来源收集（全部是已经写好的结论，本模块不重新解释证据）：

    ① 换挡条件（effect）  跨列依赖边上承载的条件：trigger.predicates / 意图链 provides；
                          没有承载条件的边，退回源操作自己的后置效果（它产生了什么）
    ② 功能先验前提（prior）下一操作 pre_inferred 里"由某操作提供的必要前提"
                          （例如抓取前手必须先张开；推理补全，尚无画面证据就是 U）
    ③ 持续约束（constraint）下一操作的保持类 C_const，以及有没有保持动作承担它
    ④ 场景前提（context）  反复出现在多个操作前置里的世界状态（"物体仍在桌上"）——
                          保留在明细里，但**不参与放行判定**：它不是这一跳要交出的东西

判定只读已有证据：effect_evidence（前序效果）、pre_coverage（下一前置）、hold（约束）。
结构进 result.json（机器可读），人看的是 render.gate_svg 画的门控状态机图。
"""

from __future__ import annotations

import re
from collections import Counter

from .operations import TIME_TOL, _norm, _sim
from .vocab import hold_category, is_hold_constraint

MATCH_FLOOR = 0.55        # 条件文本匹配阈值（与 operations.SIM_FLOOR 同量级）
DEDUP_FLOOR = 0.75        # 同一门控内两条条件视为重复的相似度
CONTEXT_PRE_REPEAT = 3    # 在这么多个操作的前置条件里出现 → 场景前提，不是换挡条件
MAX_LINES = 3             # 门控菱形上直接写几行条件（其余进报告明细）

# 判定用的证据词表：只看结论，不重新解释证据
T_VERDICTS = {"supported", "supported_partial", "provided", "ambient",
              "covered", "delegated", "evidenced"}
# F 需要"明确的否定证据"。当前检查器都不产生它——出现时（例如人工复核标注"条件
# 被画面否定"）才会走到这里，所以它是通道而不是常态。
F_VERDICTS = {"violated", "contradicted", "refuted", "denied", "falsified"}
DEP_RELATIONS = ("sequence", "enables", "maintain_until")

_PRE_INFERRED_RE = re.compile(r"^(?P<cond>.+?)（必要前提，由「(?P<src>.+?)」提供")
_PRED_TAIL_RE = re.compile(r"_\d+$")


# ---------------------------------------------------------------
# 列序：layers + 保持列合并
# ---------------------------------------------------------------

def _overlap(a: dict, b: dict) -> float:
    return max(0.0, min(float(a.get("end", 0)), float(b.get("end", 0)))
               - max(float(a.get("start", 0)), float(b.get("start", 0))))


def columns(op_graph: dict) -> list[list[str]]:
    """门控与渲染共用的列序：**时间上重叠的操作算一组**（同一列 = 并行推进）。

    不用 operations.layers：它是为依赖图分层的，保证边方向从左到右，但同一层未必
    同时发生（举升与放置会被最长路径松弛压到同一层，图上就成了“同时做”）。门控要
    回答的是“哪几步在同时做、在哪一跳换挡”，所以列序按时间重叠切：

      · 非保持操作按开始时间流式分组：与当前组时间重叠就并入，否则起新组；
      · 保持操作并入与它时间重叠最多的那一组——“手臂保持伸出”就与“手掌抓握”
        同列，门控正好落在真正需要放行的换挡点上。
    """
    if op_graph.get("single_actor"):
        return [list(c) for c in op_graph.get("semantic_columns") or []]
    ops = [n for n in op_graph.get("nodes") or [] if isinstance(n, dict)]
    if not ops:
        return []
    omap = {str(n["id"]): n for n in ops}
    doing = [n for n in ops if str(n.get("mode") or "") != "maintain"]
    holds = [n for n in ops if str(n.get("mode") or "") == "maintain"]
    doing.sort(key=lambda n: (float(n.get("start", 0)), float(n.get("end", 0)), str(n["id"])))

    cols: list[list[str]] = []
    cur: list[str] = []
    cur_end = 0.0
    for n in doing:
        start, end = float(n.get("start", 0)), float(n.get("end", 0))
        if cur and start < cur_end - TIME_TOL:
            cur.append(str(n["id"]))
            cur_end = max(cur_end, end)
        else:
            if cur:
                cols.append(cur)
            cur, cur_end = [str(n["id"])], end
    if cur:
        cols.append(cur)

    for h in sorted(holds, key=lambda n: (float(n.get("start", 0)), str(n["id"]))):
        best_i, best_ov = None, 0.0
        for i, col in enumerate(cols):
            ov = sum(_overlap(h, omap[c]) for c in col)
            if ov > best_ov + 1e-6:
                best_i, best_ov = i, ov
        if best_i is None:
            # 与任何列都不重叠的孤立保持：按开始时间插到对应的位置
            at = len(cols)
            for i, col in enumerate(cols):
                if float(omap[col[0]].get("start", 0)) > float(h.get("start", 0)):
                    at = i
                    break
            cols.insert(at, [str(h["id"])])
        else:
            cols[best_i].append(str(h["id"]))

    ordered: list[list[str]] = []
    for col in cols:
        col = list(dict.fromkeys(col))
        col.sort(key=lambda x: (str((omap.get(x) or {}).get("mode") or "") == "maintain",
                                float((omap.get(x) or {}).get("start", 0)), x))
        ordered.append(col)
    return ordered


# ---------------------------------------------------------------
# 证据索引
# ---------------------------------------------------------------

def _pre_index(checks: list[dict]) -> dict[tuple[str, str], dict]:
    idx: dict[tuple[str, str], dict] = {}
    for c in checks:
        if c.get("kind") == "pre_coverage" and c.get("node"):
            idx[(str(c["node"]), _norm(c.get("condition")))] = c
    return idx


def _hold_index(checks: list[dict]) -> dict[str, dict]:
    return {str(c["node"]): c for c in checks if c.get("kind") in {"hold", "constraint", "grip_scope"} and c.get("node")}


def _rejected_texts(bundle: dict) -> list[str]:
    """被 s04 反证剔除的条件：不再是"必要条件"，标出来（但不改门控状态）。"""
    out = []
    for r in (bundle.get("conditions") or {}).get("rejected_conditions") or []:
        text = str((r or {}).get("condition") or "")
        if text:
            out.append(text)
    return out


def _pred_base(name: str) -> str:
    return _PRED_TAIL_RE.sub("", str(name or ""))


# ---------------------------------------------------------------
# 条件匹配
# ---------------------------------------------------------------

def _text_hit(a: object, b: object) -> bool:
    """两条条件的文本匹配：相同、互相包含，或相似度达标。

    只用来判断"谁提供了它""这两条是不是重复"，不做语义判定——条件成不成立
    仍然由证据侧说了算。
    """
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na or _sim(a, b) >= MATCH_FLOOR


def _same_condition(a: str, b: str, pa: str, pb: str) -> bool:
    if _norm(a) == _norm(b):
        return True
    if pa and pb and _pred_base(pa) == _pred_base(pb) and _text_hit(a, b):
        return True
    return _sim(a, b) >= DEDUP_FLOOR


def _self_condition(text: str, node: dict) -> bool:
    """保持节点自身状态名（"保持伸出"的前置也是"保持伸出"）：不是转移条件。"""
    if str(node.get("mode") or "") != "maintain":
        return False
    posts = node.get("post") or []
    return (_text_hit(text, node.get("name"))
            or _text_hit(text, node.get("hold_action"))
            or (bool(posts) and _text_hit(text, posts[0])))


# ---------------------------------------------------------------
# 条件的四个来源
# ---------------------------------------------------------------

def _edge_cond_texts(e: dict, chain_idx: dict, omap: dict) -> list[str]:
    """一条跨列依赖边承载的条件：先看 trigger，再看意图链，最后退回源操作自己的效果。"""
    t = e.get("trigger") or {}
    preds = [str(p) for p in (t.get("predicates") or []) if p]
    if preds:
        return preds
    given = chain_idx.get((str(e.get("from")), str(e.get("to"))))
    if given:
        return [given]
    if str(e.get("relation") or "") in ("sequence", "enables"):
        src = omap.get(str(e.get("from"))) or {}
        posts = [str(p) for p in (src.get("post") or []) if p]
        if posts:                      # 它产生了什么，就是这一跳要交出的东西
            return posts[:1]
    return []


def _provider_for(text: str, src_ids: list[str], dst_id: str, omap: dict,
                  chain_idx: dict, by_text: dict) -> tuple[str, str] | None:
    """这条条件由前一列的哪个操作提供（返回：提供者 id、它承诺的效果文本）。"""
    for sid in src_ids:
        given = chain_idx.get((sid, dst_id))
        if given and _text_hit(given, text):
            return sid, given
    want = _pred_base(by_text.get(text) or "")
    for sid in src_ids:
        for post in (omap.get(sid) or {}).get("post") or []:
            if _text_hit(post, text):
                return sid, str(post)
            # 谓词同根即视为同一个条件（GraspEstablished_RH 与 _RH_4 是同义写法）：
            # 只用于判断谁提供了它，条件成不成立仍由证据侧决定。
            if want and _pred_base(by_text.get(post) or "") == want:
                return sid, str(post)
    return None


def _effect_status(node: dict, post_text: str) -> str:
    for e in node.get("effect_evidence") or []:
        if _text_hit(e.get("expected"), post_text):
            return str(e.get("status") or "")
    return ""


def _state_from(status: str, verdict: str) -> str:
    if status == "observed" or verdict in T_VERDICTS:
        return "T"
    if verdict in F_VERDICTS:
        return "F"
    return "U"


def _check(kind: str, text: str, state: str, verdict: str, evidence: str, **extra) -> dict:
    out = {"kind": kind, "text": str(text), "state": state,
           "verdict": str(verdict or "unknown"), "evidence": str(evidence or ""),
           "gate": kind != "context"}
    out.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return out


def _constraint_check(inv: str, src_ids: list[str], dst_ids: list[str], omap: dict,
                      hold_chk: dict) -> dict:
    """约束由谁承担：本段里有没有对应的保持节点（本列或前一列的 MAINTAIN 节点）。

    有承担者 → T（"这条约束在过程中由谁守住"能答上来）；没有 → 看 hold 检查的结论，
    uncovered 就是 U（待复核），不能当 F：没有保持动作不等于约束被违反。
    """
    cat = hold_category(inv)
    for oid in list(dst_ids) + list(src_ids):
        node = omap.get(oid) or {}
        if str(node.get("mode") or "") != "maintain":
            continue
        name = str(node.get("name") or "")
        if hold_category(name) != cat:
            continue
        parts = [str(p) for p in node.get("executors") or []]
        if parts and any(p and p in inv for p in parts):
            return _check("constraint", inv, "T", "covered",
                          f"由「{name}」在过程中保持（{node.get('start')}~{node.get('end')}s）",
                          source="保持节点", holder=oid)
    verdict = str(hold_chk.get("verdict") or "")
    state = "T" if verdict in T_VERDICTS else ("F" if verdict in F_VERDICTS else "U")
    return _check("constraint", inv, state, verdict,
                  str(hold_chk.get("evidence") or "该持续约束尚需状态证据确认；不要求补保持动作"),
                  source="C_const")


def _gate_checks(src: list[str], dst: list[str], ctx: dict) -> list[dict]:
    """一个门控点的全部条件（含不参与判定的场景前提）。"""
    omap, edges, chain_idx = ctx["omap"], ctx["edges"], ctx["chain_idx"]
    by_text, pre_idx, hold_idx = ctx["by_text"], ctx["pre_idx"], ctx["hold_idx"]
    pre_counts, rejected = ctx["pre_counts"], ctx["rejected"]
    out: list[dict] = []

    def add(chk: dict) -> None:
        for old in out:
            if _same_condition(old["text"], chk["text"], old.get("predicate", ""),
                               chk.get("predicate", "")):
                # 已有更强的判定就保留它：T > U > F 之外的顺序不适用，按信息来源优先级
                if old["state"] != "T" and chk["state"] == "T":
                    out[out.index(old)] = chk
                return
        out.append(chk)

    # ① 跨列依赖边承载的条件（换挡条件）
    for e in edges:
        if e.get("mutual") or str(e.get("relation") or "") not in DEP_RELATIONS:
            continue
        f, t = str(e.get("from")), str(e.get("to"))
        if f not in src or t not in dst:
            continue
        for text in _edge_cond_texts(e, chain_idx, omap):
            prov = _provider_for(text, [f], t, omap, chain_idx, by_text)
            pid, post = prov if prov else (f, text)
            status = _effect_status(omap.get(pid) or {}, post)
            chk = ctx["edge_check"].get((f, t)) or {}
            verdict = str(chk.get("verdict") or "")
            state = _state_from(status, verdict)
            evidence = (f"由「{(omap.get(pid) or {}).get('name')}」的后置效果提供；"
                        + ("观测后状态已确认" if state == "T" else "尚无观测证据（预期 ≠ 实际）"))
            if str(e.get("basis") or "") == "observed_order":
                evidence += "；该依赖只观测到先后，未固化为执行依赖"
            add(_check("effect", text, state, verdict or status, evidence,
                       provider=pid, provider_name=(omap.get(pid) or {}).get("name"),
                       source=f"{pid}.C_post", predicate=ctx["pred_of"](post)))

    # ② 下一操作的功能先验前提（推理补全的必需环节）
    for tid in dst:
        for raw in (omap.get(tid) or {}).get("pre_inferred") or []:
            m = _PRE_INFERRED_RE.match(str(raw))
            if not m:
                continue
            cond, who = m.group("cond"), m.group("src")
            src_id = ctx["name2id"].get(who)
            status = _effect_status(omap.get(src_id) or {}, cond) if src_id else ""
            state = "T" if status == "observed" else ("F" if status in F_VERDICTS else "U")
            add(_check("prior", cond, state, status or "functional_prior",
                       f"功能先验推理：由「{who}」提供（必要前提，尚无画面证据）",
                       provider=src_id, provider_name=who, source="功能先验",
                       predicate=ctx["pred_of"](cond)))

    # ③ 下一操作的前置条件（有提供者 → 换挡条件；反复出现 → 场景前提）
    for tid in dst:
        node = omap.get(tid) or {}
        for pre in node.get("pre") or []:
            if _self_condition(pre, node):
                continue
            norm = _norm(pre)
            chk = pre_idx.get((tid, norm)) or {}
            verdict = str(chk.get("verdict") or "")
            quality = "rejected" if any(_text_hit(pre, r) for r in rejected) else ""
            if pre_counts[norm] >= CONTEXT_PRE_REPEAT:
                # 反复出现在多个操作前置里的世界状态：不是这一跳要交出的东西
                add(_check("context", pre, "T" if verdict in T_VERDICTS else "U", verdict,
                           str(chk.get("evidence") or "多个操作共有的世界状态，本跳默认延续"),
                           source="场景前提", quality=quality))
                continue
            prov = _provider_for(pre, src, tid, omap, chain_idx, by_text)
            if prov:
                pid, post = prov
                pred = ctx["pred_of"](post)
                # 同一个提供者已经就同一件事写过条件（保持节点的前置与边上那条往往
                # 是同一件事）：不重复列，避免菱形上出现两条近义条件
                if any(c.get("kind") in ("effect", "prior") and c.get("provider") == pid
                       and _pred_base(c.get("predicate") or "") == _pred_base(pred)
                       for c in out):
                    continue
                status = _effect_status(omap.get(pid) or {}, post)
                state = _state_from(status, verdict)
                evidence = (f"由「{(omap.get(pid) or {}).get('name')}」的后置效果提供；"
                            + ("观测后状态已确认" if state == "T" else "尚无观测证据"))
                add(_check("effect", pre, state, verdict or status, evidence,
                           provider=pid, provider_name=(omap.get(pid) or {}).get("name"),
                           source=f"{pid}.C_post", predicate=pred))
                continue
            state = "T" if verdict in T_VERDICTS else ("F" if verdict in F_VERDICTS else "U")
            evidence = str(chk.get("evidence") or "")
            if verdict == "unprovided":
                evidence = "候选缺口：" + (evidence or "没有找到提供该条件的操作")
            elif not evidence:
                evidence = "没有找到提供该条件的操作（候选缺口，不写成事实）"
            add(_check("pre", pre, state, verdict, evidence,
                       source=f"{tid}.C_pre", predicate=ctx["pred_of"](pre), quality=quality))

    # ④ 下一操作的持续约束
    for tid in dst:
        node = omap.get(tid) or {}
        hold_chk = hold_idx.get(tid) or {}
        for inv in node.get("invariants") or []:
            if is_hold_constraint(inv):
                add(_constraint_check(str(inv), src, dst, omap, hold_chk))
    return out


# ---------------------------------------------------------------
# 聚合与装配
# ---------------------------------------------------------------

def _aggregate(checks: list[dict]) -> str:
    """合取：只看参与放行判定的条件（场景前提不算）。全 T 才放行。"""
    states = [c["state"] for c in checks if c.get("gate")]
    if not states:
        return "U"
    if "F" in states:
        return "F"
    return "T" if all(s == "T" for s in states) else "U"


def _lines(checks: list[dict]) -> list[str]:
    """菱形上写的条件行：未确认的优先（它们决定这个门控为什么还没放行）。"""
    order = {"U": 0, "F": 1, "T": 2, "context": 3}
    picked = sorted([c for c in checks if c.get("gate")],
                    key=lambda c: (order.get(c["state"], 9),))
    return [str(c["text"]) for c in picked[:MAX_LINES]]


def _reason(state: str, checks: list[dict]) -> str:
    live = [c for c in checks if c.get("gate")]
    n_u = sum(1 for c in live if c["state"] == "U")
    n_f = sum(1 for c in live if c["state"] == "F")
    if state == "T":
        return f"{len(live)} 条条件都有证据支持 → 放行（连线画实线）"
    if state == "F":
        return f"{n_f} 条条件有证据表明不满足 → 阻断（需要修条件或补操作）"
    return (f"{n_u}/{len(live)} 条条件尚未确认 → 等待证据（连线画虚线）；"
            f"U 既不能当 T 放行，也不能当 F 判死")


def build(bundle: dict) -> dict:
    """构建门控表：列出每个换挡点的条件、状态与证据（确定性，不调用模型）。"""
    op_graph = bundle.get("operations") or {}
    ops = [n for n in op_graph.get("nodes") or [] if isinstance(n, dict)]
    empty = {"schema_version": "1.0", "kind": "gates", "columns": [], "gates": [],
             "stats": {"gates": 0, "T": 0, "F": 0, "U": 0, "checks": 0,
                       "unresolved": 0, "columns": 0}}
    if not ops:
        return empty

    omap = {str(n["id"]): n for n in ops}
    checks_all = (bundle.get("reasoning") or {}).get("checks") or []
    by_text = (bundle.get("predicates") or {}).get("by_text") or {}
    if not isinstance(by_text, dict):
        by_text = {}
    chain_idx: dict[tuple[str, str], str] = {}
    for key in ("intent_chain", "candidate_intent_chain"):
        for c in op_graph.get(key) or []:
            chain_idx[(str(c.get("from")), str(c.get("to")))] = str(c.get("provides") or "")

    ctx = {
        "omap": omap,
        "edges": op_graph.get("edges") or [],
        "chain_idx": chain_idx,
        "by_text": by_text,
        "pre_idx": _pre_index(checks_all),
        "hold_idx": _hold_index(checks_all),
        "rejected": _rejected_texts(bundle),
        "pre_counts": Counter(_norm(p) for o in ops for p in (o.get("pre") or [])),
        "edge_check": {(str(c.get("edge", [None, None])[0]), str(c.get("edge", [None, None])[1])): c
                       for c in checks_all if c.get("kind") == "edge_support" and c.get("edge")},
        "name2id": {str(n.get("name")): str(n["id"]) for n in ops},
        "pred_of": lambda text: str(by_text.get(text) or ""),
    }

    cols = columns(op_graph)
    gates: list[dict] = []
    for k in range(len(cols) - 1):
        src, dst = cols[k], cols[k + 1]
        checks = _gate_checks(src, dst, ctx)
        state = _aggregate(checks)
        gates.append({
            "id": f"gate_{k + 1}",
            "seq": k + 1,
            "from": list(src),
            "to": list(dst),
            "from_names": [(omap.get(i) or {}).get("name") or i for i in src],
            "to_names": [(omap.get(i) or {}).get("name") or i for i in dst],
            "state": state,
            "checks": checks,
            "lines": _lines(checks),
            "unresolved": [c["text"] for c in checks
                           if c.get("gate") and c["state"] == "U"],
            "reason": _reason(state, checks),
        })

    counts = {"T": 0, "F": 0, "U": 0}
    for g in gates:
        counts[g["state"]] = counts.get(g["state"], 0) + 1
    return {
        "schema_version": "1.0",
        "kind": "gates",
        "columns": cols,
        "gates": gates,
        "stats": {
            "gates": len(gates),
            "T": counts["T"], "F": counts["F"], "U": counts["U"],
            "checks": sum(len(g["checks"]) for g in gates),
            "unresolved": sum(len(g["unresolved"]) for g in gates),
            "columns": len(cols),
        },
    }
