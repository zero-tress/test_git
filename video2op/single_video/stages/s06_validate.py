#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⑥ 一致性与纪律校验（确定性，不经模型）。

这里的检查是"机制"而不是"原则"——它们保证：
  · 不出现具体参数（角度/距离/力值）
  · 状态链不断裂（孩子被抢走后怀里不能还有孩子）
  · "保持"不漏（建立抓握后必须有维持，直到释放）
  · 意图声明的部位在操作图里有落脚点
  · 引用完整（节点 ↔ 动作 ↔ 关系）
"""

from __future__ import annotations

import re

from ... import config, ignored_parts
from ...vocab import BODY_PARTS, HAND_TO_ARM, is_contact_action
from .common import MULTI_PART_MAP

# 状态互相矛盾的词对（前者出现在前动作的结束状态、后者出现在后动作的开始状态）
CONFLICT_PAIRS = [
    ("抓握", "张开"), ("抓握", "空手"), ("握住", "张开"), ("握持", "空手"),
    ("接触", "离开"), ("抬起", "下垂"), ("直立", "弯腰"), ("闭合", "张开"),
    ("抓紧", "松开"), ("支撑", "悬空"),
]

# “持有/空手”语义对（“孩子被抢走后怀里不能还有孩子”）
HOLD_WORDS = ("抓握", "握住", "握持", "抓紧", "持有", "托举", "夹住", "抓牢")
EMPTY_WORDS = ("手是空的", "空手", "手中无", "未持有", "没有握", "已释放", "松开了")


def _state_conflict(sa: str, sb: str) -> str | None:
    for x, y in CONFLICT_PAIRS:
        if (x in sa and y in sb) or (y in sa and x in sb):
            return f"{x} / {y}"
    a_hold = any(w in sa for w in HOLD_WORDS)
    b_hold = any(w in sb for w in HOLD_WORDS)
    a_empty = any(w in sa for w in EMPTY_WORDS)
    b_empty = any(w in sb for w in EMPTY_WORDS)
    if a_hold and b_empty:
        return "持有 / 空手"
    if a_empty and b_hold:
        return "空手 / 持有"
    return None

GRASP_WORDS = ("抓握", "抓紧", "握住", "握持", "夹住")
LIFT_WORDS = ("托举", "抬起", "举起", "抬升", "提起")
RELEASE_WORDS = ("松开", "放开", "释放", "脱离", "放下")
LEG_STAND_GAP = 1.2   # 腿部状态空档超过该秒数即视为缺口
CONTACT_HOLD_GAP = 0.5  # 接触期手臂空档超过该秒数即视为缺口（先验补全阈值为 0.4）


def _iter_text_fields(obj, path=""):
    """递归遍历所有字符串字段，yield (路径, 文本)。"""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_text_fields(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _iter_text_fields(v, f"{path}[{i}]")


def _check_param_discipline(bundle: dict) -> dict:
    hits = []
    patterns = [re.compile(p) for p in config.FORBIDDEN_PARAM_PATTERNS]
    # 只检查语义字段（跳过纯元数据：净化记录里的“原文摘引”不是知识内容）
    skip_prefix = ("meta.", "validation.", "stats.", "pipeline.", "profile.",
                   "window_plan", "purify.", "temporal_logic.")
    for path, text in _iter_text_fields(bundle):
        if path.startswith(skip_prefix):
            continue
        for pat in patterns:
            m = pat.search(text)
            if m:
                hits.append({"path": path, "text": text[:120], "match": m.group(0)})
                break
    return {
        "id": "param_discipline",
        "name": "参数纪律（不出现角度/距离/力值等具体数值）",
        "status": "pass" if not hits else "fail",
        "detail": hits[:20],
    }


def _check_ignored_parts(bundle: dict) -> dict:
    """不参与操作的部位纪律（头 / 颈 / 口）：操作语义里不出现它们的功能。

    以操作为节点之后，这些部位只承担朝向、观察与言语，不产生操作
    （vocab.IGNORED_PARTS）：动作表里没有它们，条件、约束与评价里也不该有
    “保持视线”“头部后仰”“张嘴等待”这类表述——它们对操作没有作用。
    清理由 ignored_parts.purge() 在建图入口做，这里作为机制兜底（防止回归）。
    """
    hits = ignored_parts.scan(bundle)
    return {
        "id": "ignored_parts",
        "name": "不参与操作的部位纪律（操作语义里不含头 / 颈 / 口的内容）",
        "status": "pass" if not hits else "warn",
        "detail": hits[:20],
    }


def _check_state_chain(actions: list[dict]) -> dict:
    issues = []
    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(a.get("executor", "?"), []).append(a)
    for part, acts in by_part.items():
        acts.sort(key=lambda x: (x.get("start", 0), x.get("end", 0)))
        for a, b in zip(acts, acts[1:], strict=False):
            if a.get("end", 0) > b.get("start", 0) + 0.05:
                continue  # 时间上重叠，交给冲突检查
            sa, sb = str(a.get("state_after") or ""), str(b.get("state_before") or "")
            if not sa or not sb:
                continue
            hit = _state_conflict(sa, sb)
            if hit:
                issues.append({
                    "part": part,
                    "conflict": hit,
                    "from": f"{a.get('action')}（{a.get('start')}-{a.get('end')}，结束状态：{sa}）",
                    "to": f"{b.get('action')}（{b.get('start')}-{b.get('end')}，开始状态：{sb}）",
                    "message": f"状态链可能断裂：{sa} → {sb}",
                })
    return {
        "id": "state_chain",
        "name": "状态连续性（状态不能突然翻转）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _check_maintain_coverage(actions: list[dict]) -> dict:
    """建立抓握/抬起托举后必须有维持动作覆盖，直到状态被改变或解除。"""
    issues = []
    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(a.get("executor", "?"), []).append(a)
    for part, acts in by_part.items():
        acts.sort(key=lambda x: (x.get("start", 0), x.get("end", 0)))
        for i, a in enumerate(acts):
            text = str(a.get("action") or "")
            is_grasp = any(w in text for w in GRASP_WORDS) and a.get("mode") == "transition"
            is_lift = any(w in text for w in LIFT_WORDS) and a.get("mode") == "motion"
            if not (is_grasp or is_lift):
                continue
            end = float(a.get("end", 0))
            # 找同部位、从该动作之后开始的 maintain
            cover = None
            stop = None
            for b in acts[i + 1:]:
                btext = str(b.get("action") or "")
                if cover is None and b.get("mode") == "maintain" and float(b.get("start", 0)) <= end + 0.6 \
                        and float(b.get("end", 0)) > end:
                    cover = b
                if any(w in btext for w in RELEASE_WORDS) or \
                        (b.get("mode") == "motion" and not any(w in btext for w in LIFT_WORDS)):
                    stop = b
                    break
            if stop is None:
                continue  # 后面没有改变/解除动作，不作为缺口
            if cover is None:
                kind = "抓握" if is_grasp else "抬起托举"
                issues.append({
                    "part": part,
                    "message": f"「{a.get('action')}」建立了{kind}，但之后没有保持动作，"
                               f"直到「{stop.get('action')}」——保持环节缺失",
                })
            elif float(cover.get("end", 0)) < float(stop.get("start", 0)) - 1.0:
                issues.append({
                    "part": part,
                    "message": f"保持动作「{cover.get('action')}」在 {cover.get('end')}s 结束，"
                               f"但到 {stop.get('start')}s 才改变状态，中间 "
                               f"{round(float(stop.get('start', 0)) - float(cover.get('end', 0)), 1)}s 没有保持记录",
                })
    return {
        "id": "maintain_coverage",
        "name": "保持环节覆盖（抓握/托举建立后必须持续保持到状态改变）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _check_leg_coverage(actions: list[dict]) -> dict:
    """腿脚一体：人在站立时腿必然在支撑，腿的状态不能出现空白区间。"""
    issues = []
    for leg in ("左腿", "右腿"):
        items = [a for a in actions if a.get("executor") == leg]
        if not items:
            continue
        spans = sorted((float(a.get("start", 0)), float(a.get("end", 0))) for a in items)
        merged: list[list[float]] = []
        for s, e in spans:
            if merged and s <= merged[-1][1] + 0.3:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        for (_, e0), (s1, _) in zip(merged, merged[1:], strict=False):
            if s1 - e0 > LEG_STAND_GAP:
                issues.append({
                    "part": leg,
                    "message": f"{leg} 在 {round(e0, 1)}s~{round(s1, 1)}s 之间没有任何状态记录"
                               f"——人在站立时腿必然在支撑身体，应补为保持站立支撑",
                })
    return {
        "id": "leg_coverage",
        "name": "腿部状态覆盖（腿不迈步时必须在站立支撑）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _merge_spans(spans: list[tuple[float, float]], tol: float = 0.3) -> list[list[float]]:
    merged: list[list[float]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1] + tol:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def _contact_issue(hand: str, arm: str, s: float, e: float) -> dict:
    return {
        "part": arm,
        "message": f"{hand}在 {round(s, 1)}~{round(e, 1)}s 正在接触/操作物体，"
                   f"但 {arm} 在这段时间没有任何记录——手臂应停在前一位置保持给力",
    }


def _check_arm_contact_hold(actions: list[dict]) -> dict:
    """接触期手臂覆盖：手正在接触/操作物体时，同侧手臂必须有记录。

    手臂在此时应停在前一动作的末端位置保持给力（力角色"稳定"）——
    手臂不会一边被手带着接触物体一边自己移位。缺口由 s02e_prior 规则 4 补全，
    这里作为机制兜底（防止回归）。
    """
    issues = []
    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(a.get("executor", "?"), []).append(a)
    for hand, arm in HAND_TO_ARM.items():
        spans = _merge_spans([(float(a.get("start", 0)), float(a.get("end", 0)))
                              for a in by_part.get(hand, []) if is_contact_action(a)])
        arm_spans = _merge_spans([(float(a.get("start", 0)), float(a.get("end", 0)))
                                  for a in by_part.get(arm, [])])
        if not spans or not arm_spans:
            continue
        for cs, ce in spans:
            cur = cs
            for s, e in arm_spans:
                if e <= cur + 0.05:
                    continue
                if s - cur > CONTACT_HOLD_GAP:
                    issues.append(_contact_issue(hand, arm, cur, min(s, ce)))
                cur = max(cur, e)
                if cur >= ce - 0.05:
                    break
            if ce - cur > CONTACT_HOLD_GAP:
                issues.append(_contact_issue(hand, arm, cur, ce))
    return {
        "id": "arm_contact_hold",
        "name": "接触期手臂保持（手接触物体时，同侧手臂须停在前一位置保持给力）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _expand_parts(parts: list[str]) -> set[str]:
    out: set[str] = set()
    for p in parts:
        if p in MULTI_PART_MAP:
            out.update(MULTI_PART_MAP[p])
        else:
            out.add(p)
    return out


def _check_intent_coverage(intents: list[dict], actions: list[dict]) -> dict:
    actual = {a.get("executor") for a in actions}
    issues = []
    for it in intents[:1]:  # 用最高置信度意图
        required = _expand_parts([bp.get("part", "") for bp in it.get("required_body_parts", []) or []])
        for part in sorted(required):
            if part and part not in actual:
                issues.append({
                    "intent": it.get("statement"),
                    "part": part,
                    "message": f"意图声明需要「{part}」参与，但操作图中没有该部位的任何动作",
                })
    return {
        "id": "intent_part_coverage",
        "name": "意图部位覆盖（意图要求参与的部位在操作图中有记录）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _check_references(bundle: dict) -> dict:
    nodes = bundle.get("task_nodes", {}).get("task_nodes", [])
    actions = bundle.get("atomic", {}).get("atomic_actions", [])
    relations = bundle.get("relations", [])
    links = bundle.get("link", {}).get("links", [])

    node_ids = {n.get("id") for n in nodes}
    action_ids = {a.get("id") for a in actions}
    issues = []
    for item in links:
        if item.get("node_id") not in node_ids:
            issues.append({"where": "links", "message": f"节点引用不存在：{item.get('node_id')}"})
    for n in nodes:
        for r in n.get("atomic_refs") or []:
            if r not in action_ids:
                issues.append({"where": f"{n.get('id')}.atomic_refs", "message": f"动作引用不存在：{r}"})
    for rel in relations:
        for side in ("from", "to"):
            if rel.get(side) not in action_ids:
                issues.append({"where": "temporal_relations",
                               "message": f"关系端点不存在：{rel.get(side)}"})
    for ev in bundle.get("rules", {}).get("evaluators", []):
        if ev.get("node_id") and ev["node_id"] not in node_ids:
            issues.append({"where": "evaluators", "message": f"评价器节点不存在：{ev['node_id']}"})
    return {
        "id": "references",
        "name": "引用完整性（节点/动作/关系互相指得上）",
        "status": "pass" if not issues else "fail",
        "detail": issues[:20],
    }


def _check_time_sanity(actions: list[dict], duration: float) -> dict:
    issues = []
    for a in actions:
        s, e = float(a.get("start", 0)), float(a.get("end", 0))
        if e < s:
            issues.append({"id": a.get("id"), "message": f"结束时间早于开始时间：{s}-{e}"})
        if s < -0.01 or e > duration + 0.5:
            issues.append({"id": a.get("id"), "message": f"时间超出视频范围（{duration}s）：{s}-{e}"})
    return {
        "id": "time_sanity",
        "name": "时间合法性",
        "status": "pass" if not issues else "fail",
        "detail": issues[:20],
    }


def _check_operation_nodes(bundle: dict) -> dict:
    """操作图节点口径：节点必须是"操作"，不能是执行器（左臂/右臂……）本身。

    这是交付口径的机制保证——节点一旦退回执行器，整张图就失去泛化能力（换执行体
    要先把每个执行器动作重新映射一遍）。同时要求每个节点带执行器属性与操作意图。
    """
    nodes = (bundle.get("operations") or {}).get("nodes") or []
    issues = []
    for o in nodes:
        name = str(o.get("name") or "")
        hit = next((p for p in BODY_PARTS if name.startswith(p)), None)
        if hit:
            issues.append({"node": o.get("id"), "name": name,
                           "message": f"节点名以执行器「{hit}」开头——节点应是操作，"
                                      f"执行器写进节点的 executors 属性"})
        if not o.get("executors"):
            issues.append({"node": o.get("id"), "name": name,
                           "message": "节点没有标注执行器属性"})
        if not str(o.get("intent") or "").strip():
            issues.append({"node": o.get("id"), "name": name,
                           "message": "节点缺少操作意图（intent_role）"})
    return {
        "id": "operation_nodes",
        "name": "操作图节点口径（节点=操作，执行器是节点属性）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _check_operation_graph(bundle: dict) -> dict:
    """操作图自洽：边指得上、依赖边与分层方向一致、意图链有落脚点、程序已生成。"""
    ops = bundle.get("operations") or {}
    nodes = ops.get("nodes") or []
    edges = ops.get("edges") or []
    issues = []
    if not nodes:
        return {"id": "operation_graph", "name": "操作图自洽（边/分层/意图链）",
                "status": "warn", "detail": [{"message": "未生成操作图"}]}
    ids = {n.get("id") for n in nodes}
    layer = {n.get("id"): int(n.get("layer", 0)) for n in nodes}
    for e in edges:
        if e.get("from") not in ids or e.get("to") not in ids:
            issues.append({"message": f"边端点不存在：{e.get('from')} → {e.get('to')}"})
            continue
        if not e.get("mutual") and layer.get(e["to"], 0) <= layer.get(e["from"], 0):
            issues.append({"message": f"依赖边与分层方向矛盾（应左→右递增）："
                                      f"{e.get('from')} → {e.get('to')}"})
    for c in ops.get("intent_chain") or []:
        if c.get("from") not in ids or c.get("to") not in ids:
            issues.append({"message": f"意图链引用了不存在的操作："
                                      f"{c.get('from')} → {c.get('to')}"})
    if not (bundle.get("program") or {}).get("operations"):
        issues.append({"message": "存在操作图但没有生成执行器语义程序"})
    return {
        "id": "operation_graph",
        "name": "操作图自洽（边/分层/意图链/执行器程序）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _check_reasoning(bundle: dict) -> dict:
    """推理修正的可追溯性：每条结论都要能指回图上的元素，处理方式合法，且真的落地。"""
    r = bundle.get("reasoning") or {}
    op_graph = bundle.get("operations") or {}
    nodes = op_graph.get("nodes") or []
    edges = op_graph.get("edges") or []
    if not nodes:
        return {"id": "reasoning_traceable", "name": "推理修正可追溯",
                "status": "pass", "detail": []}
    ids = {n.get("id") for n in nodes}
    pairs = {(e.get("from"), e.get("to")) for e in edges}
    issues = []
    for c in r.get("checks") or []:
        if c.get("action") not in ("keep", "downgrade", "flag", "gap"):
            issues.append({"message": f"未知的处理方式：{c.get('action')}（{c.get('id')}）"})
        if c.get("kind") == "edge_support":
            e = c.get("edge") or []
            if len(e) != 2 or (e[0], e[1]) not in pairs:
                issues.append({"message": f"结论指向不存在的边：{c.get('id')}"})
        elif c.get("kind") in ("pre_coverage", "hold", "evidence"):
            if c.get("node") not in ids:
                issues.append({"message": f"结论指向不存在的操作：{c.get('id')}"})
        # 判了"降级"就必须真的把边降下来（机制而不是承诺）
        if c.get("action") == "downgrade":
            e2 = c.get("edge") or []
            edge = next((x for x in edges if [x.get("from"), x.get("to")] == e2), None)
            if edge and edge.get("relation") == "enables":
                issues.append({"message": f"判定为降级但边上仍是 enables：{e2}"})
    for g in r.get("gaps") or []:
        if g.get("node") not in ids:
            issues.append({"message": f"候选缺口指向不存在的操作：{g.get('node')}"})
    return {
        "id": "reasoning_traceable",
        "name": "推理修正可追溯（结论指得上图上的元素、降级已落地）",
        "status": "pass" if not issues else "warn",
        "detail": issues[:20],
    }


def _check_execution_contract(bundle: dict) -> dict:
    issues = []
    for op in (bundle.get("program") or {}).get("operations") or []:
        for issue in op.get("blocked_by") or []:
            issues.append({"message": f"{op['id']}：{issue}"})
    return {"id": "execution_contract", "name": "操作契约证据与条件完整性（不代表机器人已可执行）",
            "status": "warn" if issues else "pass", "detail": issues}


def _check_predicates(bundle: dict) -> dict:
    """谓词绑定：图上每条条件都得有名字，且名字不重复指到不同条件上。"""
    table = bundle.get("predicates") or {}
    ops = ((bundle.get("operations") or {}).get("nodes")) or []
    if not ops:
        return {"id": "predicate_binding", "name": "谓词绑定完整",
                "status": "pass", "detail": []}
    issues = []
    by_text = table.get("by_text") or {}
    ids = [p.get("id") for p in (table.get("predicates") or [])]
    if len(set(ids)) != len(ids):
        issues.append({"message": "谓词名出现重复，引用会出现歧义"})
    for op in ops:
        texts = (list(op.get("pre") or []) + list(op.get("post") or [])
                 + list(op.get("invariants") or []) + list(op.get("completion") or []))
        for t in texts:
            if str(t or "").strip() and str(t).strip() not in by_text:
                issues.append({"message": f"{op.get('id')} 的条件没有谓词名：{t}"})
    # 保持节点必须能回答“怎么知道它还在保持”（停止事件要有名字）
    for op in ops:
        if str(op.get("mode") or "") != "maintain":
            continue
        if not op.get("maintain_until"):
            issues.append({"message": f"{op.get('id')} 是 MAINTAIN 节点但没有 maintain_until"})
    return {"id": "predicate_binding", "name": "谓词绑定完整（每条条件都有稳定名字）",
            "status": "pass" if not issues else "warn", "detail": issues[:20]}


def _check_expansion(bundle: dict) -> dict:
    """子操作展开：引用指得上、保持覆盖成立、检查点能落回子操作。"""
    ex = bundle.get("expansion") or {}
    items = ex.get("operations") or []
    if not items:
        return {"id": "sub_operation_expansion", "name": "子操作展开自洽",
                "status": "pass", "detail": []}
    ops = ((bundle.get("operations") or {}).get("nodes")) or []
    known_refs = {a.get("id") for a in ((bundle.get("atomic") or {}).get("atomic_actions") or [])}
    op_ids = {str(o.get("id")) for o in ops}
    issues = []
    for item in items:
        if str(item.get("id")) not in op_ids:
            issues.append({"message": f"展开指向不存在的操作：{item.get('id')}"})
        sub_ids = {s["id"] for s in item.get("sub_operations") or []}
        for s in item.get("sub_operations") or []:
            if s.get("atomic_ref") not in known_refs:
                issues.append({"message": f"子操作 {s['id']} 引用了不存在的动作 {s.get('atomic_ref')}"})
        for r in item.get("relations") or []:
            if r.get("from") not in sub_ids or r.get("to") not in sub_ids:
                issues.append({"message": f"子操作关系指向不存在的子操作：{r.get('from')} → {r.get('to')}"})
            if r.get("relation") == "hold_covers":
                hold = next((s for s in item["sub_operations"] if s["id"] == r["from"]), None)
                act = next((s for s in item["sub_operations"] if s["id"] == r["to"]), None)
                if not hold or not act or hold.get("kind") != "hold":
                    issues.append({"message": f"保持覆盖的源不是保持类子操作：{r.get('from')}"})
                elif not (float(hold["start"]) <= float(act["start"]) + 0.05
                          and float(hold["end"]) >= float(act["end"]) - 0.05):
                    issues.append({"message": f"保持覆盖在时间上不成立：{r.get('from')} → {r.get('to')}"})
        for c in item.get("checkpoints") or []:
            if c.get("sub_operation") not in sub_ids:
                issues.append({"message": f"检查点指向不存在的子操作：{c.get('id')}"})
    return {"id": "sub_operation_expansion",
            "name": "子操作展开自洽（引用、保持覆盖、检查点）",
            "status": "pass" if not issues else "warn", "detail": issues[:20]}


def _check_contract_schema(bundle: dict) -> dict:
    """导出的契约能不能被执行侧加载：字段齐全、引用有效、依赖无环、MAINTAIN 有终止条件。"""
    c = bundle.get("contract") or {}
    nodes = c.get("nodes") or {}
    if not nodes:
        return {"id": "contract_schema", "name": "可执行契约结构完整",
                "status": "warn", "detail": [{"message": "尚未导出契约"}]}
    required = ("name", "subject", "object", "pre", "constraints", "evaluator",
                "post", "implementation", "dependencies")
    issues = []
    for nid, node in nodes.items():
        missing = [k for k in required if k not in node]
        if missing:
            issues.append({"message": f"{nid} 缺字段：{missing}"})
        if not node.get("implementation"):
            issues.append({"message": f"{nid} 没有候选方式集合（implementation 为空）"})
        mode = str(node.get("mode") or "NORMAL")     # 缺省 NORMAL，与执行侧加载器一致
        if mode not in ("NORMAL", "MAINTAIN"):
            issues.append({"message": f"{nid} 的模式非法：{node.get('mode')}"})
        if mode == "MAINTAIN" and not node.get("maintain_until"):
            issues.append({"message": f"{nid} 标为 MAINTAIN 但没有 maintain_until"})
    known = set(nodes)
    for nid, node in nodes.items():
        for ref in list(node.get("dependencies") or []) + list(node.get("maintain_until") or []):
            if ref not in known:
                issues.append({"message": f"{nid} 引用了不存在的节点：{ref}"})
            if ref == nid:
                issues.append({"message": f"{nid} 依赖自己"})
    # 依赖环：执行侧会在加载时拒绝
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(nid: str, path: list[str]) -> None:
        if nid in done:
            return
        if nid in visiting:
            issues.append({"message": f"依赖成环：{' → '.join([*path, nid])}"})
            return
        visiting.add(nid)
        for dep in nodes.get(nid, {}).get("dependencies") or []:
            visit(dep, [*path, nid])
        visiting.discard(nid)
        done.add(nid)

    for nid in nodes:
        visit(nid, [])
    # END 等的条件必须是**本图真的会产生的状态**。
    # 照抄别人图里的终点效果（那是他那张图产生的）会永远等不到，
    # 而且执行侧一旦为它注册了检测器，任务就永远结束不了。
    end_id = c.get("end_node")
    if end_id and end_id in nodes:
        produced: set[str] = set()
        for nid, node in nodes.items():
            if nid in (c.get("start_node"), end_id):
                continue
            produced |= set(node.get("post") or [])
        for cond in nodes[end_id].get("pre") or []:
            if cond in ("OperationEndTriggered", "OperationStartTriggered"):
                continue          # 上层任务接口给的触发信号，不由图内产生
            if cond not in produced:
                issues.append({"message": f"{end_id} 等的条件 {cond} 在本图里没有任何节点会产生"
                                          f"——它永远等不到，任务结束不了"})
    # 保持节点与它的终点不能抢同一个执行器：执行侧会一直等对方（我们真踩过这个坑）
    for nid, node in nodes.items():
        if str(node.get("mode") or "NORMAL") != "MAINTAIN":
            continue
        for tgt in node.get("maintain_until") or []:
            t = nodes.get(tgt) or {}
            if t.get("subject") and t.get("subject") == node.get("subject"):
                issues.append({"message": f"{nid} 保持期间占着 {node.get('subject')}，"
                                          f"而它的保持终点 {tgt} 也要用同一个执行器——"
                                          f"执行侧两边互等，应把占执行器的步骤拆到保持之后"})
    return {"id": "contract_schema",
            "name": "可执行契约结构完整（对齐执行侧语义图 schema）",
            "status": "pass" if not issues else "warn", "detail": issues[:20]}


def _check_installed_peer(bundle: dict) -> dict:
    """导出物能不能被执行侧入口加载（能加载才谈得上“给它用”）。

    这里只做静态校验；完整的四步验证（加载 → 实例化 → 调度 → 谓词清单）
    用 tools/verify_contract.py，它需要执行侧项目在场。
    """
    c = bundle.get("contract") or {}
    if not c.get("nodes"):
        return {"id": "contract_handoff", "name": "导出物可供执行侧加载",
                "status": "pass", "detail": []}
    issues = []
    if not c.get("start_node") or not c.get("end_node"):
        issues.append({"message": "没有声明 start_node / end_node，执行侧加载器会拒绝"})
    for nid, node in (c.get("nodes") or {}).items():
        if not isinstance(node.get("object"), (str, list)):
            issues.append({"message": f"{nid} 的 object 必须是字符串或字符串列表"})
        for key in ("pre", "constraints", "evaluator", "post", "implementation", "dependencies"):
            v = node.get(key)
            if v is not None and (not isinstance(v, list)
                                  or any(not isinstance(x, str) for x in v)):
                issues.append({"message": f"{nid} 的 {key} 必须是字符串列表"})
    return {"id": "contract_handoff", "name": "导出物可供执行侧加载（字段类型与首尾节点）",
            "status": "pass" if not issues else "warn", "detail": issues[:20]}


def _check_operation_abstraction(bundle: dict) -> dict:
    from ...abstraction import semantic_issues
    issues = []
    for key in ("atomic", "task_nodes", "intents", "conditions", "rules", "operations"):
        issues.extend(semantic_issues(bundle.get(key) or {}, key))
    return {"id": "operation_abstraction", "name": "整体移动与上肢操作抽象",
            "status": "fail" if issues else "pass", "detail": issues[:20]}


def run(bundle: dict) -> dict:
    if bundle.get("learning_layer") == "semantic":
        from ...semantic import validate
        return validate(bundle)
    actions = bundle.get("atomic", {}).get("atomic_actions", [])
    duration = float(bundle.get("meta", {}).get("duration") or 0.0)
    intents = bundle.get("intents", {}).get("intents", [])

    checks = [
        _check_param_discipline(bundle),
        _check_ignored_parts(bundle),
        _check_time_sanity(actions, duration),
        _check_state_chain(actions),
        _check_maintain_coverage(actions),
        _check_arm_contact_hold(actions),
        _check_operation_abstraction(bundle),
        _check_intent_coverage(intents, actions),
        _check_operation_nodes(bundle),
        _check_operation_graph(bundle),
        _check_reasoning(bundle),
        _check_predicates(bundle),
        _check_expansion(bundle),
        _check_contract_schema(bundle),
        _check_installed_peer(bundle),
        _check_execution_contract(bundle),
        _check_references(bundle),
    ]
    conflicts = bundle.get("atomic", {}).get("conflicts", [])
    if conflicts:
        checks.append({
            "id": "part_conflicts",
            "name": "同部位时间冲突",
            "status": "warn",
            "detail": conflicts[:10],
        })

    failed = [c for c in checks if c["status"] == "fail"]
    warned = [c for c in checks if c["status"] == "warn"]
    needs_review = []
    for a in actions:
        if float(a.get("confidence") or 1.0) < config.CONFIDENCE_FLOOR:
            needs_review.append({"kind": "action_low_confidence", "id": a.get("id"),
                                 "text": a.get("action")})
    for it in intents:
        if float(it.get("confidence") or 1.0) < config.DEFAULT_INTENT_CONFIDENCE:
            needs_review.append({"kind": "intent_low_confidence", "id": it.get("id"),
                                 "text": it.get("statement")})
    for m in bundle.get("link", {}).get("missing_actions", []):
        needs_review.append({"kind": "inferred_action", "id": m.get("id"),
                             "text": f"{m.get('executor')} {m.get('action')}（推理补全）"})

    return {
        "passed": not failed,
        "summary": f"{len(checks)} 项检查：通过 {len(checks) - len(failed) - len(warned)}，"
                   f"提醒 {len(warned)}，失败 {len(failed)}",
        "checks": checks,
        "needs_review": needs_review,
    }
