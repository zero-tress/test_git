#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 2b-5 先验补全（确定性，不经模型）。

用部位功能先验补出"逻辑上必然存在、但画面/模型没给到"的状态，让时序图不留空白。
每条都带 `inferred=true` 与推理理由。当前五条规则：

  1. 腿的站立支撑：人在站立时腿必然在支撑身体——腿不迈步的区间必须有 maintain 覆盖。
     （腿包含脚，不再单列脚）
  2. 姿态保持：手臂抬起托举之后、开始放下或前伸之前，必须有一段 maintain 保持抬起。
  3. 抓握保持：手建立抓握之后、松开之前必须有 maintain（与 2 同机制，见 HOLD_POSE_WORDS）。
  4. 接触期手臂保持：手正在接触/操作物体（接触、抓握、拧、按……）的时段里，同侧手臂
     必然停在上一动作的末端位置保持不动并持续给力——手臂不会一边被手带着接触物体、
     一边自己移位。这类保持的力角色是"稳定"（维持位置），不是"托举"。
  5. 抓握前的预张开：要建立抓握，手必须先张开到能包裹物体的开度——合着的手不能
     直接包裹杯子。视频若没有开度变化的记录，按必要性补一个候选步骤（待画面核实）。
  6. 释放期间的手臂保持：手在张开释放时手臂无需动作，必然停在释放位姿不动，
     直到撤回接管（模板⑦：先保持生效，再允许释放）。

保持类动作只描述部位自身的姿态与功能，不带物体名（物体与手直接接触，由手的动作表达）。
"""

from __future__ import annotations

from ..vocab import (
    HAND_TO_ARM,
    IGNORED_PARTS,
    REST_STATE,
    is_contact_action,
)

# 需要"保持"的姿态词（按动作文本中的出现顺序组合成姿态名）
HOLD_POSE_WORDS = ("托举", "抬起", "举起", "抬升", "提起", "抓握", "握持", "抓紧", "支撑")
# 只有"伸出/靠近/下垂"这类动作词时，用来给接触期的手臂保持起名（取最靠前的一个）
EXTEND_WORDS = ("伸出", "前伸", "靠近", "下垂", "弯曲", "探向")

LEGS = ("左腿", "右腿")

MIN_STAND_GAP = 1.2      # 腿部状态空档超过该秒数即补站立支撑
MIN_HOLD_GAP = 1.0       # 姿态动作与其后续动作之间的空档门槛
MIN_CONTACT_GAP = 0.4    # 接触期手臂空档超过该秒数即补保持（见规则 4）
PREOPEN_SPAN = 1.0       # 抓握前预张开动作的时长（紧贴抓握之前，见规则 5）
# 释放型动词（规则 6）：手在做这些动作时，臂只需停在释放位姿不动
RELEASE_HOLD_WORDS = ("松开", "释放", "放开", "脱离", "张开释放")

# 建立抓握的动词（transition 且命中这些词 → 它需要“手已经张开”这个前提）
GRASP_WORDS = ("抓紧", "抓握", "握住", "握紧", "抓取", "夹住", "收拢")
# 手部张开的动词：命中即认为这段视频里已经有一次张开/放开记录，无需补全
OPEN_WORDS = ("张开", "打开", "松开", "释放", "放开", "伸展手指")


def _intervals(items: list[dict]) -> list[tuple[float, float]]:
    spans = sorted((float(a.get("start", 0)), float(a.get("end", 0))) for a in items)
    merged: list[list[float]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + 0.3:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _gaps(intervals: list[tuple[float, float]], duration: float,
          extend_tail: bool = True,
          min_gap: float = MIN_STAND_GAP) -> list[tuple[float, float]]:
    """区间之间的空档（含尾部延伸）。"""
    out: list[tuple[float, float]] = []
    for (_, e0), (s1, _) in zip(intervals, intervals[1:], strict=False):
        if s1 - e0 > min_gap:
            out.append((round(e0, 2), round(s1, 2)))
    if extend_tail and intervals:
        last_end = intervals[-1][1]
        if duration - last_end > min_gap:
            out.append((round(last_end, 2), round(duration, 2)))
    return out


def _pose_name(action: str, allow_extend: bool = False) -> str:
    """从动作文本里按出现顺序取出姿态词，组成"抬起托举"这样的短语。

    allow_extend=True 时，若没有姿态词，退而用"伸出/靠近"这类动作词给保持起名
    （用于接触期的手臂保持：手臂停在"伸出"的末端位置）。
    """
    hits = [w for w in HOLD_POSE_WORDS if w in action]
    if not hits and allow_extend:
        hits = [w for w in EXTEND_WORDS if w in action][:1]
    hits.sort(key=lambda w: action.index(w))
    return "".join(hits[:2])


def _contact_spans(hand_items: list[dict]) -> list[tuple[float, float]]:
    """同一只手"正在接触/操作物体"的连续时段（接触→抓握→保持抓握 合并成一段）。"""
    spans = sorted((float(a.get("start", 0)), float(a.get("end", 0)))
                   for a in hand_items if is_contact_action(a))
    merged: list[list[float]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1] + 0.3:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(round(s, 2), round(e, 2)) for s, e in merged]


def _neighbor(items: list[dict], gap_s: float,
              gap_e: float) -> tuple[dict | None, dict | None]:
    """空档前后紧邻的两个动作（用于给保持命名、并写"直到"指向）。"""
    prev = nxt = None
    for a in sorted(items, key=lambda x: (float(x.get("start", 0)), float(x.get("end", 0)))):
        if float(a.get("end", 0)) <= gap_s + 0.05:
            prev = a
        if nxt is None and float(a.get("start", 0)) >= gap_e - 0.05:
            nxt = a
    return prev, nxt


def _force_role(part: str, pose: str) -> str:
    if "手" in part:
        return "抓握"
    if "臂" in part:
        return "托举"
    if "腿" in part:
        return "支撑"
    return "稳定"


def _mk(aid: int, part: str, action: str, start: float, end: float,
        role: str, reason: str, state: str | None = None,
        confidence: float = 0.75, until: dict | None = None) -> dict:
    return {
        "id": aid,
        "executor": part,
        "action": action,
        "mode": "maintain",
        "start": round(start, 2),
        "end": round(end, 2),
        "exerts_force": True,
        "force_role": role,
        "object": None,
        "state_before": state or REST_STATE.get(part, ""),
        "state_after": state or REST_STATE.get(part, ""),
        "until": until,
        "inferred": True,
        "inference_reason": reason,
        "confidence": confidence,
    }


def _mk_transition(aid: int, part: str, action: str, start: float, end: float,
                   role: str, reason: str, state_before: str,
                   state_after: str, confidence: float = 0.7) -> dict:
    """推理补出的瞬时步骤（建立/解除一个状态，如抓握前的预张开）。"""
    return {
        "id": aid,
        "executor": part,
        "action": action,
        "mode": "transition",
        "start": round(start, 2),
        "end": round(end, 2),
        "exerts_force": True,
        "force_role": role,
        "object": None,
        "state_before": state_before,
        "state_after": state_after,
        "until": None,
        "inferred": True,
        "inference_reason": reason,
        "confidence": confidence,
    }


def _covers_span(a: dict, s: float, e: float) -> bool:
    """动作 a 是否已经覆盖 [s, e] 整段（释放期保持的幂等判定用）。

    不能用固定秒数门槛：释放期本身可能只有 0.2s，补出的保持和它一样长，
    “重叠 >0.3s” 永远不成立，离线重算一次就多一条重复保持。
    """
    span = max(e - s, 1e-6)
    return (min(e, float(a.get("end", 0))) - max(s, float(a.get("start", 0)))
            >= span - 0.05)


def run(actions: list[dict], duration: float) -> dict:
    next_id = max((int(a.get("id", 0)) for a in actions), default=0)
    inferred: list[dict] = []
    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(str(a.get("executor") or ""), []).append(a)

    # 整体只记录有目标的位置变化；不再补全下肢支撑或整体静止。

    # ---- 规则 2/3：姿态保持（抬起托举、抓握等建立之后到改变之前）----
    for part, items in by_part.items():
        if part not in ("左臂", "右臂", "左手", "右手"):
            continue  # 腿由规则 1 负责；头不参与操作，不补保持
        items = sorted(items, key=lambda x: (float(x.get("start", 0)), float(x.get("end", 0))))
        for a in items:
            if a.get("mode") != "motion":
                continue
            pose = _pose_name(str(a.get("action") or ""))
            if not pose:
                continue
            end = float(a.get("end", 0))
            nxt = next((b for b in items
                        if b is not a and float(b.get("start", 0)) >= end - 0.05), None)
            if nxt is None:
                continue
            gap = float(nxt["start"]) - end
            if gap < MIN_HOLD_GAP:
                continue
            covered = any(
                x.get("mode") == "maintain"
                and float(x.get("start", 0)) <= end + 0.4
                and float(x.get("end", 0)) >= float(nxt["start"]) - 0.4
                for x in items if x is not a)
            if covered:
                continue
            next_id += 1
            inferred.append(_mk(
                next_id, part, f"{part}保持{pose}", end, float(nxt["start"]),
                _force_role(part, pose),
                f"「{a.get('action')}」建立之后到「{nxt.get('action')}」之前没有该部位的动作记录，"
                f"但这段时间姿态必然在维持（肢体不会瞬间松掉），补为保持{pose}",
                state=f"保持{pose}",
            ))

    # ---- 规则 4：接触期手臂保持（手在接触/操作物体时，手臂停在上一位置给力）----
    for hand, arm in HAND_TO_ARM.items():
        hand_items = by_part.get(hand) or []
        arm_items = by_part.get(arm) or []
        spans = _contact_spans(hand_items)
        if not spans or not arm_items:
            continue
        for gap_s, gap_e in _gaps(_intervals(arm_items), duration, min_gap=MIN_CONTACT_GAP):
            inter = sum(max(0.0, min(gap_e, ce) - max(gap_s, cs)) for cs, ce in spans)
            if inter < MIN_CONTACT_GAP:
                continue
            # 规则 2/3 已经给这个部位补过保持的话，不再重复补
            if any(min(gap_e, float(x["end"])) - max(gap_s, float(x["start"])) > 0.3
                   for x in inferred if x["executor"] == arm):
                continue
            touching = [str(x.get("action")) for x in hand_items
                        if is_contact_action(x) and float(x.get("end", 0)) > gap_s + 0.05
                        and float(x.get("start", 0)) < gap_e - 0.05]
            prev, nxt = _neighbor(arm_items, gap_s, gap_e)
            pose = _pose_name(str((prev or {}).get("action") or ""), allow_extend=True)
            label = f"保持{pose}" if pose else "保持位置"
            next_id += 1
            inferred.append(_mk(
                next_id, arm, f"{arm}{label}", gap_s, gap_e, "稳定",
                f"{hand}在 {gap_s}~{gap_e}s 正在接触/操作物体"
                f"（{'、'.join(touching[:2])}），但这段时间 {arm} 没有任何动作记录——"
                f"手臂不会一边被手带着接触物体一边自己移位，必然停在上一动作的末端位置"
                f"保持不动并持续给稳定力",
                state=label,
                confidence=0.8,
                until={"type": "action_completed", "ref": nxt.get("id"),
                       "text": f"直到{nxt.get('action')}"} if nxt else None,
            ))

    # ---- 规则 5：抓握前的预张开（要抓握，手必须先张开）----
    # 手的功能先验：抓握 / 释放；不给力时静息态是张开。但一旦手已经合上（握着东西
    # 或空握），要再去抓取就必须先把它打开——“合着的手不能直接包裹杯子”是抓握的
    # 必要条件。视频若没记录这次开度变化，按必要性补一个带理由的候选步骤（待核实）。
    for hand in ("左手", "右手"):
        items = sorted(by_part.get(hand) or [],
                       key=lambda x: (float(x.get("start", 0)), float(x.get("end", 0))))
        # 幂等：这条手已经有推理补出的预张开，就不再重复补
        if any(x.get("inferred") and "张开手指" in str(x.get("action") or "") for x in items):
            continue
        for a in items:
            if str(a.get("mode")) != "transition":
                continue
            text = str(a.get("action") or "")
            if not any(w in text for w in GRASP_WORDS):
                continue
            # 张开型动作本身不是“建立抓握”（“张开手指至可抓取开度”里也含“抓取”）
            if any(w in text for w in OPEN_WORDS):
                continue
            start = float(a.get("start", 0))
            opened = any(
                b is not a
                and float(b.get("start", 0)) < start
                and float(b.get("end", 0)) <= start + 0.05
                and any(w in str(b.get("action") or "") for w in OPEN_WORDS)
                for b in items)
            if opened:
                continue
            next_id += 1
            inferred.append(_mk_transition(
                next_id, hand, f"{hand}张开手指至可抓取开度",
                max(0.0, start - PREOPEN_SPAN), start, "抓握",
                f"要建立抓握（「{text}」），手必须先张开到能包裹物体的开度——"
                f"合着的手无法直接包裹杯子（手的功能先验：抓握 / 释放）；"
                f"视频没有记录这次开度变化，按动作必要性补全"
                f"（待画面核实：若此前手本就处于张开状态，本条是冗余候选）",
                state_before="手未处于张开状态",
                state_after="手指张开至可抓取开度"))

    # ---- 规则 6：释放期间的手臂保持（模板⑦：先保持生效，再允许释放）----
    # 手在张开释放时，同侧手臂无需动作——它会停在释放位姿不动，直到撤回接管。
    for hand, arm in HAND_TO_ARM.items():
        hand_items = by_part.get(hand) or []
        arm_items = by_part.get(arm) or []
        if not arm_items:
            continue
        for rel in hand_items:
            if str(rel.get("mode")) != "transition":
                continue
            text = str(rel.get("action") or "")
            if not any(w in text for w in RELEASE_HOLD_WORDS):
                continue
            s, e = float(rel.get("start", 0)), float(rel.get("end", 0))
            if e - s <= 0.05:
                continue
            # 该时段手臂已有动作记录（含保持）→ 不补；已补过也不重复补（幂等）。
            # 判定按“覆盖整个释放期”算，不能用固定秒数门槛：释放期本身可能只有 0.2s，
            # 补出的保持和它一样长——固定门槛（如 >0.3s）永远不成立，重跑一次就多一条
            # 重复保持（从冰箱取出蔬菜案例踩过的坑：同一段补出了 3 条“右臂保持位置”）。
            if any(_covers_span(x, s, e) for x in arm_items):
                continue
            if any(_covers_span(x, s, e) for x in inferred if x["executor"] == arm):
                continue
            nxt = next((x for x in sorted(arm_items, key=lambda y: float(y.get("start", 0)))
                        if float(x.get("start", 0)) >= e - 0.05), None)
            next_id += 1
            inferred.append(_mk(
                next_id, arm, f"{arm}保持位置", s, e, "稳定",
                f"{hand}在 {s}~{e}s 正在释放物体（「{text}」），这段时间 {arm} "
                f"没有任何动作记录——释放期间手臂停在释放位姿不动、持续给稳定力"
                f"（模板⑦：先保持生效，再允许释放）",
                state="保持位置",
                confidence=0.78,
                until={"type": "action_completed", "ref": nxt.get("id"),
                       "text": f"直到{nxt.get('action')}"} if nxt else None,
            ))

    # 兜底：不参与操作的部位（头）不产生任何先验补全
    inferred = [a for a in inferred if a.get("executor") not in IGNORED_PARTS]
    return {"inferred_actions": inferred}