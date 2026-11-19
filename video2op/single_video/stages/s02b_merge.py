#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""② 2b-2 跨窗口合并（确定性，不经模型）。

职责：
  1. 把窗口局部时间换成全局时间；
  2. 合并重叠窗口里重复出现的同一个动作；
  3. 缝合被窗口边界截断的动作；
  4. 重编号、重映射时序关系与 until.ref（"直到……才停止"指向的动作）；
  5. 识别成对部位的交替动作（左右腿迈步 → alternation）；
  6. 检查同一部位的时间冲突（同一时刻两个互斥动作）。
"""

from __future__ import annotations

import re

from ...ignored_parts import is_ignored_part

# 合并阈值
IOU_MERGE = 0.35            # 时间重叠（交并比）达到该值即认为可能是同一动作
CONTAIN_RATIO = 0.65        # 或者一个动作被另一个包含到该比例
TEXT_SIM_MERGE = 0.45       # 动作文本相似度门槛
GAP_SEQUENCE = 0.35         # 同部位前后动作间隔小于该值视为紧接（sequence）
PARALLEL_IOU = 0.5          # 不同部位动作重叠达到该值视为并行

# 成对部位（用于识别交替动作）
# 只对下肢做规则识别：左右腿/左右脚的同类动作本质上是交替的。
# 上肢（左右臂/左右手）的“同时”动作多为并行，交替关系交由模型在窗口内自己判定。
PART_PAIRS = [("左腿", "右腿"), ("左脚", "右脚")]
ALTERNATION_IOU = 0.30      # 交替动作的时间重叠门槛
ALTERNATION_SIM = 0.38      # 交替动作的文本相似门槛


def _text_sim(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def _verbs(text: str) -> set[str]:
    """粗提动词性字符（中文不好切词，用双字滑窗近似）。"""
    t = re.sub(r"[^\u4e00-\u9fff]", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _verb_sim(a: str, b: str) -> float:
    va, vb = _verbs(a), _verbs(b)
    if not va or not vb:
        return 0.0
    return len(va & vb) / len(va | vb)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> tuple[float, float]:
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    union = max(a1, b1) - min(a0, b0)
    iou = inter / union if union > 0 else 0.0
    contain = inter / min(a1 - a0, b1 - b0) if min(a1 - a0, b1 - b0) > 1e-6 else 0.0
    return iou, contain


STOP_WORDS = ("停止", "停下", "结束", "完毕", "静止", "站立不动", "保持不动")


def _core(action: str, executor: str) -> str:
    """去掉部位名后的动作核心短语（用于判断包含关系）。"""
    text = str(action or "")
    if executor:
        text = text.replace(str(executor), "")
    return text.strip("，,。.、；; ")


def _similar(a: dict, b: dict) -> bool:
    if a["executor"] != b["executor"]:
        return False
    iou, contain = _overlap(a["start"], a["end"], b["start"], b["end"])
    ts = max(_text_sim(a["action"], b["action"]), _verb_sim(a["action"], b["action"]))
    if iou >= IOU_MERGE or contain >= CONTAIN_RATIO:
        return ts >= TEXT_SIM_MERGE
    # 边界缝合：同一动作被窗口边界切成两半（前段尾部截断 + 后段头部截断），
    # 两段时间相接或轻微重叠，且文本高度相似。
    touching = not (a["end"] < b["start"] - 0.4 or b["end"] < a["start"] - 0.4)
    boundary = bool((a.get("_truncated_end") and b.get("_truncated_start")) or
                    (b.get("_truncated_end") and a.get("_truncated_start")))
    if not (touching and boundary):
        return False
    # 一方说“停止/结束”、另一方不说，多半不是同一件事（如“迈步”vs“停止迈步”）
    a_stop = any(w in a["action"] for w in STOP_WORDS)
    b_stop = any(w in b["action"] for w in STOP_WORDS)
    if a_stop != b_stop:
        return False
    ca, cb = _core(a["action"], a["executor"]), _core(b["action"], b["executor"])
    if ca and cb and (ca in cb or cb in ca):
        return True
    return ts >= 0.45


def _merge_two(a: dict, b: dict) -> dict:
    """把时间上重合的同一动作合成一条：区间取并，状态取首尾，信息取更全的。"""
    first, second = (a, b) if a["start"] <= b["start"] else (b, a)
    span_a = a["end"] - a["start"]
    span_b = b["end"] - b["start"]
    keep_mode_from = a if span_a >= span_b else b
    out = dict(first)
    out["start"] = min(a["start"], b["start"])
    out["end"] = max(a["end"], b["end"])
    out["action"] = a["action"] if len(a["action"] or "") >= len(b["action"] or "") else b["action"]
    out["mode"] = keep_mode_from["mode"]
    out["exerts_force"] = bool(a.get("exerts_force") or b.get("exerts_force"))
    out["force_role"] = a.get("force_role") or b.get("force_role")
    out["object"] = a.get("object") or b.get("object")
    out["state_before"] = first.get("state_before") or second.get("state_before")
    out["state_after"] = second.get("state_after") or first.get("state_after")
    # World state belongs to the actual interval endpoint, not the later START.
    last = max((a, b), key=lambda x: x["end"])
    for key, owner in (("world_before", first), ("world_after", last)):
        out[key] = list(owner.get(key) or [])
        out[key + "_from"] = owner.get(key + "_from", "observed")
    out["until"] = a.get("until") or b.get("until")
    out["confidence"] = max(float(a.get("confidence") or 0.6), float(b.get("confidence") or 0.6))
    out["evidence"] = a.get("evidence") or b.get("evidence")
    out["_truncated_start"] = bool(first.get("_truncated_start"))
    out["_truncated_end"] = bool(second.get("_truncated_end"))
    if a.get("inferred") or b.get("inferred"):
        out["inferred"] = True
    return out


def flatten(windows: list[dict], total_duration: float) -> list[dict]:
    """窗口局部时间 → 全局时间（保留来源窗口与局部 id 供关系重映射）。

    同时标记“被窗口边界截断”的动作，供边界缝合逻辑使用。
    """
    flat: list[dict] = []
    for w in windows:
        w_start = float(w["window"]["start"])
        w_dur = float(w["window"]["duration"])
        for a in w.get("atomic_actions", []):
            item = dict(a)
            item["start"] = round(min(total_duration, w_start + float(a["start"])), 2)
            item["end"] = round(min(total_duration, w_start + float(a["end"])), 2)
            item["_win"] = int(w["window"]["index"])
            item["_local_id"] = int(a["id"])
            item["_truncated_start"] = float(a["start"]) <= 0.3 and w_start > 0.3
            item["_truncated_end"] = float(a["end"]) >= w_dur - 0.3 and (w_start + w_dur) < total_duration - 0.3
            flat.append(item)
    return flat


def merge_actions(flat: list[dict]) -> list[dict]:
    by_part: dict[str, list[dict]] = {}
    for item in flat:
        by_part.setdefault(item["executor"], []).append(item)

    merged: list[dict] = []
    for _part, items in by_part.items():
        items.sort(key=lambda x: (x["start"], x["end"]))
        group: list[dict] = []
        for item in items:
            if group and _similar(group[-1], item):
                group[-1] = _merge_two(group[-1], item)
            else:
                group.append(item)
        merged.extend(group)
    merged.sort(key=lambda x: (x["start"], x["end"], x["executor"]))
    return merged


def renumber(actions: list[dict]) -> tuple[list[dict], dict[tuple[int, int], int]]:
    """全局重编号（按时间排序），返回 (动作表, (窗口号, 局部id) → 全局id)。"""
    mapping: dict[tuple[int, int], int] = {}
    out: list[dict] = []
    for i, a in enumerate(actions, 1):
        a = dict(a)
        a["id"] = i
        win = int(a.get("_win") or 0)
        local = int(a.get("_local_id") or 0)
        if win and local:
            mapping[(win, local)] = i
        out.append(a)
    return out, mapping


def remap_until_refs(actions: list[dict], mapping: dict[tuple[int, int], int]) -> list[dict]:
    """把 until.ref（模型给的窗口内局部 id）换成全局 id。"""
    for a in actions:
        u = a.get("until")
        if not isinstance(u, dict):
            continue
        ref = u.get("ref")
        if ref is None:
            continue
        try:
            local = int(ref)
        except (TypeError, ValueError):
            u["ref"] = None
            continue
        win = int(a.get("_win") or 0)
        gid = mapping.get((win, local))
        if gid is None:
            # 兜底：全局唯一同号动作
            cands = [g for (w, loc), g in mapping.items() if loc == local]
            gid = cands[0] if len(cands) == 1 else None
        if gid is None:
            u["ref_unresolved"] = local
        u["ref"] = gid
    return actions


def cleanup_internal(actions: list[dict]) -> list[dict]:
    for a in actions:
        for key in ("_win", "_local_id", "_win_start", "_truncated_start", "_truncated_end"):
            a.pop(key, None)
    return actions


def remap_relations(windows: list[dict], mapping: dict[tuple[int, int], int]) -> list[dict]:
    seen: set[tuple[str, int, int]] = set()
    out: list[dict] = []
    for w in windows:
        wi = int(w["window"]["index"])
        for r in w.get("temporal_relations", []):
            f = mapping.get((wi, int(r["from"])))
            t = mapping.get((wi, int(r["to"])))
            if not f or not t or f == t:
                continue
            key = (str(r.get("relation")), f, t)
            if key in seen:
                continue
            seen.add(key)
            out.append({"relation": r.get("relation") or "sequence", "from": f, "to": t,
                        "note": r.get("note") or "", "inferred_by": "vlm_window"})
    return out


def add_boundary_relations(actions: list[dict], relations: list[dict]) -> list[dict]:
    """补上跨窗口/跨部位的显式关系（保守：只补明确成立的，且不覆盖已有关系）。"""
    have_pairs = {frozenset((r["from"], r["to"])) for r in relations}
    out = list(relations)
    n = len(actions)
    for i in range(n):
        a = actions[i]
        for j in range(i + 1, n):
            b = actions[j]
            if b["start"] > a["end"] + GAP_SEQUENCE:
                break
            pair = frozenset((a["id"], b["id"]))
            if pair in have_pairs:
                continue
            if a["executor"] == b["executor"]:
                if abs(b["start"] - a["end"]) <= GAP_SEQUENCE and a["end"] <= b["start"] + 1e-6:
                    have_pairs.add(pair)
                    out.append({"relation": "sequence", "from": a["id"], "to": b["id"],
                                "note": "同部位先后衔接", "inferred_by": "rule"})
            else:
                iou, _ = _overlap(a["start"], a["end"], b["start"], b["end"])
                if iou >= PARALLEL_IOU:
                    have_pairs.add(pair)
                    out.append({"relation": "parallel", "from": a["id"], "to": b["id"],
                                "note": "不同部位同时进行", "inferred_by": "rule"})
    return out


def apply_alternations(actions: list[dict], relations: list[dict]) -> list[dict]:
    """成对下肢部位在同一时段做同类动作 → alternation（走路、交替踏步）。"""
    alt: dict[frozenset, tuple[int, int]] = {}
    for left, right in PART_PAIRS:
        a_acts = [a for a in actions if a["executor"] == left]
        b_acts = [a for a in actions if a["executor"] == right]
        for a in a_acts:
            for b in b_acts:
                iou, _ = _overlap(a["start"], a["end"], b["start"], b["end"])
                if iou < ALTERNATION_IOU:
                    continue
                sim = max(_text_sim(a["action"], b["action"]), _verb_sim(a["action"], b["action"]))
                if sim < ALTERNATION_SIM:
                    continue
                alt[frozenset((a["id"], b["id"]))] = (a["id"], b["id"])

    if not alt:
        return relations

    out: list[dict] = []
    promoted: set[frozenset] = set()
    for r in relations:
        key = frozenset((r["from"], r["to"]))
        if key in alt and r.get("relation") in ("parallel", "sequence"):
            f, t = alt[key]
            note = r.get("note") if "交替" in str(r.get("note") or "") else "左右交替进行"
            out.append({"relation": "alternation", "from": f, "to": t,
                        "note": note, "inferred_by": "rule_alternation"})
            promoted.add(key)
        else:
            out.append(r)
    for key, (f, t) in alt.items():
        if key not in promoted and not any(
                frozenset((x["from"], x["to"])) == key and x["relation"] == "alternation" for x in out):
            out.append({"relation": "alternation", "from": f, "to": t,
                        "note": "左右交替进行", "inferred_by": "rule_alternation"})
    return out


def fill_states(actions: list[dict]) -> list[dict]:
    """补全缺失的状态字段：同部位首动作用静息态，后续动作继承前一动作的结束状态。"""
    from ...vocab import REST_STATE

    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(a.get("executor", "?"), []).append(a)
    for part, items in by_part.items():
        items.sort(key=lambda x: (x.get("start", 0), x.get("end", 0)))
        for i, a in enumerate(items):
            if not a.get("state_before"):
                prev = items[i - 1] if i > 0 else None
                if prev is not None and prev.get("state_after"):
                    a["state_before"] = prev["state_after"]
                    a["state_before_from"] = "inherit"
                elif prev is not None:
                    a["state_before"] = prev.get("action") or REST_STATE.get(part, "")
                    a["state_before_from"] = "inherit_action"
                else:
                    a["state_before"] = REST_STATE.get(part, "")
                    a["state_before_from"] = "rest_state"
            if not a.get("state_after"):
                nxt = items[i + 1] if i + 1 < len(items) else None
                if nxt is not None and nxt.get("state_before"):
                    a["state_after"] = nxt["state_before"]
                    a["state_after_from"] = "inherit"
                elif a.get("mode") == "maintain":
                    a["state_after"] = a.get("state_before") or ""
                    a["state_after_from"] = "maintain_same"
                else:
                    a["state_after"] = a.get("action") or ""
                    a["state_after_from"] = "from_action"
    return actions


# 持有型状态词（这些状态在保持动作结束后往往仍在持续）
HOLD_STATE_WORDS = ("抓握", "握持", "托举", "支撑", "夹持", "接触", "保持")
RELEASE_ACTION_WORDS = ("松开", "释放", "放开", "放下", "脱离", "离开", "撤回")


def stitch_maintains(actions: list[dict], max_gap: float = 6.0) -> list[dict]:
    """保持缝合：若“保持”动作与下一个动作之间有空档，且状态事实上仍在维持，
    就把保持区间延长到下一个动作开始前——状态不能突然断掉。

    只在证据支撑时延长：该部位在空档里没有其它动作，且下一个动作是“解除型”
    或它的开始状态与保持状态同源。
    """
    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(a.get("executor", "?"), []).append(a)
    stitched: list[dict] = []
    for part, items in by_part.items():
        items.sort(key=lambda x: (float(x.get("start", 0)), float(x.get("end", 0))))
        for a in items:
            if a.get("mode") != "maintain":
                continue
            end = float(a.get("end", 0))
            nxt = None
            for b in items:
                if b is a:
                    continue
                if float(b.get("start", 0)) >= end - 0.05:
                    nxt = b
                    break
            if nxt is None:
                continue
            gap = float(nxt["start"]) - end
            if gap < 0.4 or gap > max_gap:
                continue
            a_state = str(a.get("state_after") or a.get("state_before") or "")
            if not any(w in a_state for w in HOLD_STATE_WORDS):
                continue
            b_text = str(nxt.get("action") or "")
            b_state = str(nxt.get("state_before") or "")
            if any(w in b_text for w in RELEASE_ACTION_WORDS) or \
                    any(w in b_state for w in HOLD_STATE_WORDS):
                old = end
                a["end"] = round(float(nxt["start"]), 2)
                a["stitched_to"] = nxt.get("id")
                a["stitch_reason"] = (f"该部位在 {old}s 之后没有其它动作，状态仍在维持，"
                                      f"保持区间已缝合至下一个动作「{b_text}」开始前")
                stitched.append({"part": part, "action": a.get("action"),
                                 "from": old, "to": a["end"]})
    return stitched


def trim_maintain_overlaps(actions: list[dict]) -> list[dict]:
    """保持动作与同部位后续的移动动作重叠时，把保持截断到移动开始前。

    语义：该部位一旦开始改变姿态/位置（前伸、放下、收回），就不再是“保持”；
    但这不影响它仍在托举/持物——那由移动动作的 force_role 表达。
    """
    trimmed: list[dict] = []
    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(a.get("executor", "?"), []).append(a)
    for part, items in by_part.items():
        items.sort(key=lambda x: (float(x.get("start", 0)), float(x.get("end", 0))))
        for m in items:
            if m.get("mode") != "maintain":
                continue
            m_start, m_end = float(m.get("start", 0)), float(m.get("end", 0))
            for b in items:
                if b is m or b.get("mode") != "motion":
                    continue
                b_start = float(b.get("start", 0))
                if m_start + 0.3 < b_start < m_end - 0.2:
                    old = m_end
                    m["end"] = round(b_start, 2)
                    m["trimmed_by"] = b.get("id")
                    m["trim_reason"] = (f"该部位在 {b_start}s 开始「{b.get('action')}」，"
                                        f"保持状态在此之前结束")
                    trimmed.append({"part": part, "action": m.get("action"),
                                    "from": old, "to": m["end"]})
                    break
    return trimmed


def detect_conflicts(actions: list[dict]) -> list[dict]:
    conflicts: list[dict] = []
    by_part: dict[str, list[dict]] = {}
    for a in actions:
        by_part.setdefault(a["executor"], []).append(a)
    for part, items in by_part.items():
        items.sort(key=lambda x: x["start"])
        for i in range(len(items) - 1):
            a, b = items[i], items[i + 1]
            if a.get("mode") == "maintain" or b.get("mode") == "maintain":
                continue  # 保持动作与其它动作并存是正常的
            iou, contain = _overlap(a["start"], a["end"], b["start"], b["end"])
            if iou > 0.55 or contain > 0.8:
                sim = max(_text_sim(a["action"], b["action"]), _verb_sim(a["action"], b["action"]))
                if sim < 0.3:
                    conflicts.append({
                        "part": part, "a": a["action"], "a_span": [a["start"], a["end"]],
                        "b": b["action"], "b_span": [b["start"], b["end"]],
                        "note": "同一部位同一时段出现两条不相容的动作描述",
                    })
    return conflicts


def run(windows: list[dict], total_duration: float) -> dict:
    flat = flatten(windows, total_duration)
    merged = merge_actions(flat)
    actions, mapping = renumber(merged)
    actions = remap_until_refs(actions, mapping)
    relations = remap_relations(windows, mapping)
    actions = cleanup_internal(actions)
    actions = fill_states(actions)
    stitched = stitch_maintains(actions)
    trimmed = trim_maintain_overlaps(actions)
    relations = add_boundary_relations(actions, relations)
    relations = apply_alternations(actions, relations)
    conflicts = detect_conflicts(actions)

    inactive: dict[str, str] = {}
    unclear: list[str] = []
    for w in windows:
        for ip in w.get("inactive_parts", []) or []:
            if not isinstance(ip, dict) or not ip.get("part"):
                continue
            if is_ignored_part(ip):
                continue  # 不参与操作的部位（头 / 颈 / 口）：可见世界状态里不列它们
            inactive.setdefault(str(ip["part"]), str(ip.get("state") or ""))
        if w.get("missing_or_unclear"):
            unclear.append(f"[窗口{w['window']['index']}] {w['missing_or_unclear']}")

    return {
        "atomic_actions": actions,
        "temporal_relations": relations,
        "inactive_parts": [{"part": k, "state": v} for k, v in inactive.items()],
        "conflicts": conflicts,
        "stitched_maintains": stitched,
        "trimmed_maintains": trimmed,
        "unclear": " / ".join(unclear),
        "stats": {
            "windows": len(windows),
            "raw_actions": len(flat),
            "merged_actions": len(actions),
            "relations": len(relations),
            "stitched": len(stitched),
        },
    }
