#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""不参与操作的部位（头 / 颈 / 口）的内容净化（确定性）：操作语义里不留它们的功能。

以操作为节点之后，头部只承担朝向与观察、口部只承担言语与进食，都不给操作提供
条件（“保持视线”“张嘴等待”对操作没有作用）。它们有两个出口：

  · **执行器形态**（“头保持平视”“颈部转动”“口张开”）：各阶段归一化按
    vocab.IGNORED_PARTS 直接丢弃，写进动作表之前就没了（见 stages/s02b_atomic、
    s02d_link、s02e_prior）；旧数据里残留的这类动作由 _drop_ignored_actions 补删
    （连带清理引用它的时序关系、节点 atomic_refs 与 until.ref）；
  · **文本形态**（条件里写“保持视线”、评价里写“头部后仰”“瓶口含入口中”）：
    由本模块统一清理——把命中 vocab.IGNORED_TEXT_WORDS 的**分句**删掉，同一句里
    与操作有关的其余部分保留（“应避免物体撞击身体，且视线应关注物体位置”只去掉
    后半句）；一条内容被清空就整条去掉。

净化的是**操作语义**，不是**观察证据**（边界写在 _field_specs 里）：
  · 净化：原子动作文本与可见世界状态、任务节点七元组与评价、条件学习文本、语义约束、
    评价器、时序结构陈述、链注释、意图所需部位与能力、驻留部位表；
  · 保留：视角判据、动作的 evidence 画面依据、条件理由——它们是“为什么这么判断”的
    溯源信息，不进入操作图，删掉会毁掉证据链。

purge() 在 build_operation_graph() 入口调用一次：在线流水线与离线重建走同一条路径，
可重复执行（幂等）；scan() 供 s06 校验做机制兜底。两者共用同一份字段清单与词表，
不会各说各话。
"""

from __future__ import annotations

from .single_video.stages.common import normalize_part
from .vocab import IGNORED_PARTS, IGNORED_TEXT_WORDS

_SENT_END = "，。；：！？\n"     # 分句边界（顿号不算：它连接的是并列词，不是分句）
_LEAD_TRIM = "，、；：。 \t"
_TAIL_TRIM = "，、；： \t"
# 承接性开头：前一句被删后，以这些词开头的分句也一起去掉
# （“若目标在视线盲区，则不会伸手”——“则不会伸手”脱离前提就没意义）
_DEPENDENT_LEAD = ("则", "就", "且", "并", "也", "还", "而", "但", "却",
                   "因此", "所以", "因而", "然后", "随后", "再", "又", "从而", "以")
# 状语性短语：只剩一个状语分句（“在准备饮用阶段”）时它撑不起一条语义——整条去掉
_ADVERBIAL_LEAD = ("在", "当", "于", "针对", "关于")
_ADVERBIAL_TAIL = ("时", "阶段", "过程中", "期间", "之前", "之后", "中")
# 清空会破坏结构的字段：保留原文，交给 scan / s06 提示人工处理
_KEEP_WHEN_EMPTY = {"name", "intent_role"}


def split_sentences(text: str) -> list[str]:
    """按中文标点分句，标点跟在前一句尾部（保持原文的标点结构）。"""
    out: list[str] = []
    buf = ""
    for ch in str(text or ""):
        buf += ch
        if ch in _SENT_END:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def is_ignored_part(value: object) -> bool:
    """该部位是否不参与操作（头 / 颈 / 口）：字符串部位名或 {part, state} 条目都能判。"""
    if isinstance(value, dict):
        value = value.get("part")
    return normalize_part(str(value or "")) in IGNORED_PARTS


def has_ignored_text(text: object) -> bool:
    """文本里是否出现不参与操作的部位（头部 / 口部）的表述。"""
    t = str(text or "")
    return any(w in t for w in IGNORED_TEXT_WORDS)


def _is_adverbial(text: str) -> bool:
    """是否是孤立的状语性分句（“在准备饮用阶段”）——它自己不成一句操作语义。"""
    t = text.strip()
    return (any(t.startswith(w) for w in _ADVERBIAL_LEAD)
            and any(t.endswith(w) for w in _ADVERBIAL_TAIL))


def clean_text(text: object) -> tuple[str, int]:
    """删掉含不参与操作部位内容的分句。返回 (净化后文本, 删除的分句数)。"""
    t = str(text or "")
    if not t or not has_ignored_text(t):
        return t, 0
    sents = split_sentences(t)
    kept: list[str] = []
    dropped_prev = False
    for s in sents:
        if has_ignored_text(s) or (dropped_prev
                                   and any(s.strip().startswith(w) for w in _DEPENDENT_LEAD)):
            dropped_prev = True
            continue
        kept.append(s)
        dropped_prev = False
    if not kept:
        return "", len(sents)
    out = "".join(kept).strip().lstrip(_LEAD_TRIM).rstrip(_TAIL_TRIM)
    if not out or (len(kept) == 1 and _is_adverbial(out)):
        return "", len(sents)
    return out, len(sents) - len(kept)


# ---------------------------------------------------------------
# 需要净化的字段清单：形态 text（字符串）/ list（字符串数组）/
# parts（部位名数组，元素可为 {part, state} 条目）。
# 不在清单里的字段就是**不净化**的（观察证据与视角判据，见模块 docstring）。
# ---------------------------------------------------------------

def _field_specs(bundle: dict) -> list[tuple[str, dict, str, str]]:
    specs: list[tuple[str, dict, str, str]] = []

    def spec(label: str, container: object, key: str, kind: str) -> None:
        if isinstance(container, dict) and key in container:
            specs.append((label, container, key, kind))

    atomic = bundle.get("atomic") or {}
    for i, a in enumerate(atomic.get("atomic_actions") or []):
        if not isinstance(a, dict):
            continue
        tag = f"atomic.atomic_actions[{i}]"
        for k in ("action", "state_before", "state_after", "operation_intent"):
            spec(f"{tag}.{k}", a, k, "text")
        for k in ("world_before", "world_after"):
            spec(f"{tag}.{k}", a, k, "list")
        if isinstance(a.get("until"), dict):
            spec(f"{tag}.until.text", a["until"], "text", "text")
    spec("atomic.inactive_parts", atomic, "inactive_parts", "parts")

    for i, r in enumerate(bundle.get("relations") or []):
        if isinstance(r, dict):
            spec(f"relations[{i}].note", r, "note", "text")

    for i, n in enumerate((bundle.get("task_nodes") or {}).get("task_nodes") or []):
        if not isinstance(n, dict):
            continue
        tag = f"task_nodes[{i}]"
        t = n.get("tuple") or {}
        for k in ("C_pre", "C_const", "C_post"):
            spec(f"{tag}.tuple.{k}", t, k, "list")
        e = t.get("E")
        if isinstance(e, dict):
            for k in ("process", "completion"):
                spec(f"{tag}.tuple.E.{k}", e, k, "list")
        for j, r in enumerate(t.get("R") or []):
            if isinstance(r, dict):
                spec(f"{tag}.tuple.R[{j}].steps", r, "steps", "list")
        x = t.get("X")
        if isinstance(x, dict):
            spec(f"{tag}.tuple.X.parts", x, "parts", "parts")
        for k in ("name", "intent_role", "required_capabilities"):
            spec(f"{tag}.{k}", n, k,
                 "text" if k in ("name", "intent_role") else "list")

    for i, it in enumerate((bundle.get("intents") or {}).get("intents") or []):
        if isinstance(it, dict):
            spec(f"intents[{i}].required_body_parts", it, "required_body_parts", "parts")
            spec(f"intents[{i}].required_capabilities", it, "required_capabilities", "list")

    cond = bundle.get("conditions") or {}
    for i, item in enumerate(cond.get("condition_learning") or []):
        if not isinstance(item, dict):
            continue
        for key in ("C_pre_learning", "C_post_learning"):
            for j, entry in enumerate(item.get(key) or []):
                if not isinstance(entry, dict):
                    continue
                for side in ("positive", "negative_a", "negative_b"):
                    v = entry.get(side)
                    if isinstance(v, dict):
                        spec(f"conditions[{i}].{key}[{j}].{side}.text", v, "text", "text")
                spec(f"conditions[{i}].{key}[{j}].condition", entry, "condition", "text")
    spec("conditions.effective_conditions_summary", cond, "effective_conditions_summary", "list")
    for i, r in enumerate(cond.get("rejected_conditions") or []):
        if isinstance(r, dict):
            spec(f"conditions.rejected_conditions[{i}].condition", r, "condition", "text")

    rules = bundle.get("rules") or {}
    for i, ts in enumerate(rules.get("temporal_structures") or []):
        if isinstance(ts, dict):
            spec(f"rules.temporal_structures[{i}].statement", ts, "statement", "text")
    for i, ct in enumerate(rules.get("constraints") or []):
        if isinstance(ct, dict):
            spec(f"rules.constraints[{i}].statement", ct, "statement", "text")
    for i, ev in enumerate(rules.get("evaluators") or []):
        if isinstance(ev, dict):
            for k in ("process", "completion", "failure_signals"):
                spec(f"rules.evaluators[{i}].{k}", ev, k, "list")

    for i, l in enumerate((bundle.get("link") or {}).get("links") or []):
        if isinstance(l, dict):
            spec(f"link.links[{i}].chain_comment", l, "chain_comment", "text")

    sync = bundle.get("sync") or {}
    spec("sync.confidence_rationale", sync, "confidence_rationale", "text")
    for i, c in enumerate(sync.get("checks") or []):
        if not isinstance(c, dict):
            continue
        spec(f"sync.checks[{i}].reason", c, "reason", "text")
        for k in ("detail", "missing", "inconsistencies"):
            spec(f"sync.checks[{i}].{k}", c, k, "list")
    return specs


def _sample(stats: dict, path: str, before: str, after: str) -> None:
    if len(stats["samples"]) < 12:
        stats["samples"].append({"path": path, "before": before[:120],
                                 "after": after[:120]})


def _drop_ignored_actions(bundle: dict, stats: dict) -> None:
    """动作表里不留不参与操作的部位的动作（旧数据兜底；在线路径已在 s02b 阶段过滤）。

    删除是级联的：引用被删动作的时序关系、节点 atomic_refs、until.ref 一并清理。
    不重编号——id 只作标识，引用完整性由清理保证（s06 的 references 检查兜底）。
    """
    atomic = bundle.get("atomic") or {}
    actions = atomic.get("atomic_actions")
    if not isinstance(actions, list):
        return
    dropped = {a.get("id") for a in actions
               if isinstance(a, dict) and is_ignored_part(a.get("executor"))}
    if not dropped:
        return
    kept = [a for a in actions if not (isinstance(a, dict) and a.get("id") in dropped)]
    stats["actions_removed"] = len(actions) - len(kept)
    atomic["atomic_actions"] = kept

    def _purge_rels(rels: object) -> object:
        if not isinstance(rels, list):
            return rels
        return [r for r in rels if isinstance(r, dict)
                and r.get("from") not in dropped and r.get("to") not in dropped]

    bundle["relations"] = _purge_rels(bundle.get("relations"))
    if isinstance(atomic.get("temporal_relations"), list):
        atomic["temporal_relations"] = _purge_rels(atomic["temporal_relations"])
    if isinstance(atomic.get("conflicts"), list):
        atomic["conflicts"] = [c for c in atomic["conflicts"]
                               if not (isinstance(c, dict) and is_ignored_part(c.get("part")))]
    for a in kept:
        u = a.get("until")
        if isinstance(u, dict) and u.get("ref") in dropped:
            a["until"] = None
    for n in (bundle.get("task_nodes") or {}).get("task_nodes") or []:
        if isinstance(n, dict) and isinstance(n.get("atomic_refs"), list):
            n["atomic_refs"] = [r for r in n["atomic_refs"] if r not in dropped]


def _prune_emptied_entries(bundle: dict, stats: dict) -> None:
    """整条只讲不参与操作部位的记录被清空后，剩下的空壳没有语义——直接去掉条目。"""
    def _empty(value: object) -> bool:
        return isinstance(value, str) and not value.strip()

    def _prune(items: object, key: str) -> list | None:
        if not isinstance(items, list):
            return None
        kept = [x for x in items if not (isinstance(x, dict) and _empty(x.get(key)))]
        if len(kept) != len(items):
            stats["entries_removed"] += len(items) - len(kept)
            return kept
        return None

    cond = bundle.get("conditions") or {}
    for item in cond.get("condition_learning") or []:
        if not isinstance(item, dict):
            continue
        for key in ("C_pre_learning", "C_post_learning"):
            kept = _prune(item.get(key), "condition")
            if kept is not None:
                item[key] = kept
    kept = _prune(cond.get("rejected_conditions"), "condition")
    if kept is not None:
        cond["rejected_conditions"] = kept
    rules = bundle.get("rules") or {}
    for key in ("temporal_structures", "constraints"):
        kept = _prune(rules.get(key), "statement")
        if kept is not None:
            rules[key] = kept


def purge(bundle: dict) -> dict:
    """就地清理 bundle 的操作语义字段（幂等），返回处理记录。"""
    bundle.pop("headfree", None)   # 旧版本把这个净化记录写在 headfree 键下
    stats: dict = {"fields": 0, "phrases_removed": 0, "entries_removed": 0,
                   "parts_removed": 0, "actions_removed": 0,
                   "unresolved": [], "samples": []}
    _drop_ignored_actions(bundle, stats)
    for label, obj, key, kind in _field_specs(bundle):
        if kind == "parts":
            items = obj.get(key)
            if not isinstance(items, list):
                continue
            kept = [v for v in items if not is_ignored_part(v)]
            if len(kept) != len(items):
                stats["parts_removed"] += len(items) - len(kept)
                obj[key] = kept
            continue
        if kind == "text":
            text = obj.get(key)
            if not isinstance(text, str) or not text:
                continue
            new, n = clean_text(text)
            if not n:
                continue
            stats["fields"] += 1
            stats["phrases_removed"] += n
            if new:
                obj[key] = new
                _sample(stats, label, text, new)
            elif key in _KEEP_WHEN_EMPTY:
                # 结构性字段（节点名 / 操作目的）不能置空：留给 s06 提示人工处理
                stats["unresolved"].append({"path": label, "text": text[:120]})
            else:
                obj[key] = ""
                _sample(stats, label, text, "")
            continue
        items = obj.get(key)
        if not isinstance(items, list):
            continue
        kept_list, removed, changed = [], 0, False
        for it in items:
            if not isinstance(it, str) or not it:
                kept_list.append(it)
                continue
            new, n = clean_text(it)
            if not n:
                kept_list.append(it)
                continue
            stats["fields"] += 1
            stats["phrases_removed"] += n
            if new:
                kept_list.append(new)
                changed = changed or new != it
                _sample(stats, label, it, new)
            else:
                removed += 1
                changed = True
                _sample(stats, label, it, "")
        if removed:
            stats["entries_removed"] += removed
        if changed:
            obj[key] = kept_list
    _prune_emptied_entries(bundle, stats)
    return stats


def scan(bundle: dict) -> list[dict]:
    """只读检查：操作语义字段里还剩哪些不参与操作部位的内容（供 s06 校验兜底）。"""
    hits: list[dict] = []
    for a in ((bundle.get("atomic") or {}).get("atomic_actions") or []):
        if isinstance(a, dict) and is_ignored_part(a.get("executor")):
            hits.append({"path": f"atomic.atomic_actions[{a.get('id')}].executor",
                         "text": f"{a.get('executor')} {a.get('action')}"[:120]})
    for label, obj, key, kind in _field_specs(bundle):
        value = obj.get(key)
        if kind == "parts":
            for v in value if isinstance(value, list) else []:
                if is_ignored_part(v):
                    hits.append({"path": label, "text": str(v)[:120]})
        elif kind == "text":
            if isinstance(value, str) and has_ignored_text(value):
                hits.append({"path": label, "text": value[:120]})
        else:
            for it in value if isinstance(value, list) else []:
                if isinstance(it, str) and has_ignored_text(it):
                    hits.append({"path": label, "text": it[:120]})
    return hits
