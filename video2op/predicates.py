#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""谓词化（确定性）：把自由文本条件变成稳定、可引用、可检查的谓词。

在此之前，图上的条件是自然语言（“右手位于白色药瓶上方”）。人读得懂，机器判不了：
两条边没办法说“我等的就是这个谓词”，执行层也没办法说“这个谓词我检测不了”。
这一步不改变语义，只把每条条件登记成一个**稳定标识**：

  text       原文（人读的那一份，永远保留，不改写、不美化）
  id         谓词名（`GraspEstablished_RH`），同一份输入永远得到同一个名字
  verb       谓语（抓握 / 位于 / 保持 / 释放 ……），来自词表，不是模型即兴发挥
  agent      执行主体（右手 / 左臂 / 白色药瓶 / 环境）——从原文里认出来的那个
  spatial    空间限定（上方 / 上 / 内 / 旁），没有就是空
  polarity   positive / negative（“门未打开”是负例，不能和“门已打开”混成一个谓词）
  roles      谁在引用它：某个操作的前置 / 后置 / 约束，或某个保持节点的停止事件

**谓词名不是事实**：它只是“这条条件”的代号。条件成不成立仍然由证据侧决定
（reasoning 的 support / matches 照旧按原文核对），谓词化不放松任何一条纪律。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------
# 谓语词表：顺序即优先级（长词在前，"保持抓握"不能被"抓握"抢先认走）
# ---------------------------------------------------------------
VERB_PREDICATES: list[tuple[tuple[str, ...], str]] = [
    (("保持抓握", "持续抓握", "维持抓握", "保持夹持"), "GraspMaintained"),
    (("保持托举", "持续托举", "保持抬起托举"), "LiftMaintained"),
    (("保持站立", "站立支撑", "保持支撑"), "SupportMaintained"),
    (("保持伸出", "保持位置", "保持位姿", "保持不动", "保持抬起", "保持姿态"), "PoseHeld"),
    (("保持接触", "持续接触", "稳定接触"), "ContactMaintained"),
    (("保持", "维持", "持续"), "StateHeld"),
    (("抓握", "握住", "抓紧", "抓持", "握持", "夹持", "夹住"), "GraspEstablished"),
    (("释放", "松开", "放开", "脱离", "脱开"), "GraspReleased"),
    (("接触", "触碰", "搭上", "贴合"), "ContactEstablished"),
    (("放置", "放下", "安放", "搁"), "Placed"),
    (("举起", "提起", "抬起", "托起"), "Lifted"),
    (("搬运", "转移", "挪动"), "Moved"),
    (("接近", "靠近", "前伸", "伸向", "伸出"), "Approaching"),
    (("收回", "撤回", "退回", "收回手臂"), "Retreated"),
    (("打开", "拉开", "开启", "掰开"), "Opened"),
    (("关闭", "关上", "合上"), "Closed"),
    (("前倾", "弯腰", "俯身"), "BentForward"),
    (("直立", "回正", "起身"), "Upright"),
    (("位于", "处于", "在", "达到", "抵达"), "Located"),
    (("空", "未握持", "没有握", "未持"), "HandFree"),
    (("可触", "可抓取", "可操作", "可被"), "InReach"),
    (("自由",), "Free"),
    (("未", "不", "没有"), "Negated"),
]

SPATIAL_WORDS = [
    ("上方", "Above"), ("下面", "Below"), ("下方", "Below"),
    ("内部", "Inside"), ("内侧", "Inside"), ("里", "Inside"), ("内", "Inside"),
    ("旁边", "Beside"), ("旁", "Beside"), ("侧", "Beside"),
    ("顶部", "Top"), ("上", "On"),
]                                    # 注意：“中”不算空间词——“过程中”会被误读成 Inside

# 执行主体的识别顺序：先说具体的手 / 臂，再说腿 / 躯干，最后才轮到物体与环境
AGENT_WORDS: list[tuple[str, str]] = [
    ("右手", "RH"), ("左手", "LH"), ("双手", "BothHands"),
    ("右臂", "RA"), ("左臂", "LA"), ("双臂", "BothArms"),
    ("右腿", "RL"), ("左腿", "LL"), ("双腿", "BothLegs"), ("腿", "Leg"),
    ("手指", "Fingers"), ("手掌", "Palm"),
    ("腰", "Waist"), ("躯干", "Torso"), ("身体", "Body"),
    ("环境", "Env"), ("路径", "Path"), ("支撑面", "Support"),
]

NEGATIVE_WORDS = ("未", "没有", "不再", "不", "无")

# 安全类约束专用谓词：名字直接对齐执行侧约束名，接过去就能挂检测项
SAFETY_PREDICATES = [
    (("不碰撞", "无碰撞", "避免碰撞", "不刷碰"), "CollisionFree"),
    (("不滑落", "不打滑", "不脱落", "不跌落", "不脱手"), "NoSlip"),
    (("不倾倒", "不翻倒", "不斜倒", "不倒"), "NoTipping"),
    (("不损伤", "不破坏", "不压坏"), "NoDamage"),
    (("不干扰", "不拖动", "不移动其他"), "NoDisturbance"),
]

# 保持类：中文里“保持……的抓握”会把动词和宾语隔开，所以先做组合判定
HOLD_QUALIFIERS = [
    (("抓握", "握持", "握住", "抓持", "夹持"), "GraspMaintained"),
    (("托举", "抬起托举", "承载"), "LiftMaintained"),
    (("接触", "贴合", "稳定接触"), "ContactMaintained"),
    (("站立", "支撑"), "SupportMaintained"),
    (("位姿", "位置", "伸出", "姿态", "竖直", "水平"), "PoseHeld"),
]
HOLD_MARKERS = ("保持", "持续", "维持", "全程", "自始至终")
# "不"在“稳定接触 / 不碰撞”这类约束里不是否定谓词，而是约束语气；这些词出现时不判负例
NEGATION_EXEMPT = ("不碰撞", "不滑落", "不倾倒", "不损伤", "不破坏", "不脱落", "不干扰",
                   "不拖动", "不越界", "不超出", "不晃动", "不倾斜", "不溢出", "不动")

_PUNCT_RE = re.compile(r"[\s，。、；：（）()\[\]【】「」,.;:!?·\-—_/]+")
_PREFIX_RE = re.compile(r"^(直到|等到|直至|直至到|一直|一直保持)")


def _norm(text: object) -> str:
    return _PUNCT_RE.sub("", str(text or ""))


def _strip_prefix(text: str) -> tuple[str, str]:
    """剥掉“直到……”这类事件前缀：它是叙述口吻，不是谓词本身的一部分。

    返回 (用于命名的主体文本, 前缀)；原文仍按原样保存。
    """
    m = _PREFIX_RE.match(text)
    if not m:
        return text, ""
    return text[m.end():], m.group(1)


def _is_negated(norm: str) -> bool:
    """是不是否定谓词。安全类短语里的“不”是约束语气（不碰撞、不滑落），不算否定。"""
    if any(exempt in norm for exempt in NEGATION_EXEMPT):
        return False
    return any(w in norm for w in NEGATIVE_WORDS)


def _pick_verb(text: str) -> str:
    # 安全类约束最先认：它们决定“这条约束用什么方法守”
    for words, name in SAFETY_PREDICATES:
        if any(w in text for w in words):
            return name
    # 保持类：“保持……的抓握”这类隔开的写法在这里归一
    if any(w in text for w in HOLD_MARKERS):
        for words, name in HOLD_QUALIFIERS:
            if any(w in text for w in words):
                return name
    for words, name in VERB_PREDICATES:
        if name == "Negated":
            continue
        if any(w in text for w in words):
            return name
    if _is_negated(text):
        return "Negated"
    return "State"


def _pick_spatial(text: str) -> str:
    for word, name in SPATIAL_WORDS:
        if word in text:
            return name
    return ""


def _pick_agent(text: str) -> str:
    for word, name in AGENT_WORDS:
        if word in text:
            return name
    return "Target"


def _pick_polarity(norm: str) -> str:
    return "negative" if _is_negated(norm) else "positive"


class PredicateTable:
    """条件文本 → 谓词名。同一份输入永远得到同一份表（顺序由首次出现决定）。"""

    def __init__(self) -> None:
        self.by_text: dict[str, str] = {}
        self.items: list[dict] = []
        self._used: set[str] = set()

    def _mint(self, text: str, base: str) -> str:
        name = base
        i = 2
        while name in self._used:
            # 同一个谓词名下出现了不同的条件文本：加序号，不合并、不假装同义
            other = next((p for p in self.items if p["id"] == name), None)
            if other is not None and other["text"] == text:
                return name
            name = f"{base}_{i}"
            i += 1
        self._used.add(name)
        return name

    def add(self, text: object, node: str = "", role: str = "") -> str:
        raw = str(text if text is not None else "").strip()
        if not raw:
            return ""
        if raw in self.by_text:
            pid = self.by_text[raw]
            item = next(p for p in self.items if p["id"] == pid)
            ref = {"node": node, "role": role}
            if role and ref not in item["roles"]:
                item["roles"].append(ref)
            return pid
        norm = _norm(raw)
        stem, prefix = _strip_prefix(norm)
        verb = _pick_verb(stem)
        spatial = _pick_spatial(stem)
        agent = _pick_agent(stem)
        base = verb + (spatial or "")
        if verb not in ("Located", "State", "StateHeld", "Negated", "PoseHeld",
                        "CollisionFree", "NoSlip", "NoTipping", "NoDamage",
                        "NoDisturbance"):
            base = f"{base}_{agent}"
        pid = self._mint(raw, base)
        self.by_text[raw] = pid
        self.items.append({
            "id": pid,
            "text": raw,                       # 原文永远保留
            "verb": verb,
            "agent": agent,
            "spatial": spatial,
            "polarity": _pick_polarity(stem),
            "prefix": prefix,                  # “直到……”这类叙述前缀，单独记着
            "roles": [{"node": node, "role": role}] if role else [],
            "source": "observed_text",         # 由视频观察得到的条件文本
        })
        return pid

    def ids(self, texts: list | None) -> list[str]:
        return [self.add(t) for t in (texts or []) if str(t or "").strip()]

    def export(self) -> dict:
        roles = {}
        for p in self.items:
            for r in p["roles"]:
                roles.setdefault(str(r.get("role") or "other"), 0)
                roles[str(r.get("role") or "other")] += 1
        return {
            "schema_version": "1.0",
            "kind": "predicate_table",
            "predicates": self.items,
            "by_text": dict(self.by_text),
            "stats": {"predicates": len(self.items), "roles": roles},
        }


def build(bundle: dict) -> dict:
    """从操作图里抽出全部条件文本，建成谓词表（不改变任何原有字段）。"""
    ops = ((bundle.get("operations") or {}).get("nodes")) or []
    table = PredicateTable()
    for op in ops:
        oid = str(op.get("id") or "")
        for c in op.get("pre") or []:
            table.add(c, oid, "pre")
        for c in op.get("post") or []:
            table.add(c, oid, "post")
        for c in op.get("invariants") or []:
            table.add(c, oid, "constraint")
        for c in op.get("completion") or []:
            table.add(c, oid, "evaluator")
        # 保持节点的停止事件也要有名字：执行层要能检查“它什么时候该停”
        stop = op.get("stop_event")
        if isinstance(stop, dict) and stop.get("text"):
            table.add(stop["text"], oid, "stop_event")
    # 子操作的状态也是执行层要检查的：一并给它们名字（同一张表，不另起一套）
    for item in ((bundle.get("expansion") or {}).get("operations")) or []:
        for s in item.get("sub_operations") or []:
            for c in s.get("pre") or []:
                table.add(c, str(s.get("id") or ""), "sub_pre")
            for c in s.get("post") or []:
                table.add(c, str(s.get("id") or ""), "sub_post")
    return table.export()


def lookup(table: dict, text: object) -> str:
    """按原文取谓词名；表里没有就返回空（调用方自己决定怎么办，不在这里猜）。"""
    return str((table.get("by_text") or {}).get(str(text if text is not None else "").strip(), ""))
