#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段公共工具：提示词加载、结构渲染、JSON 约束校验。"""

from __future__ import annotations

from typing import Any

from .. import config
from ..vocab import (
    BODY_PARTS,
    IGNORED_PARTS,
    MODE_MAINTAIN,
    MODE_MOTION,
    MODE_TRANSITION,
    RELATION_TEXT,
    REST_STATE,
    part_functions_text,
)


def load_prompt(name: str, kind: str = "system") -> str:
    """读取外置提示词：prompts/<name>.<kind>.txt"""
    path = config.PROMPTS_DIR / f"{name}.{kind}.txt"
    if not path.exists():
        raise FileNotFoundError(f"提示词缺失：{path}")
    text = path.read_text(encoding="utf-8")
    if kind == "system" and name != "s01_viewpoint":
        from ..abstraction import PROMPT_POLICY
        from ..semantic import POLICY
        text += "\n" + PROMPT_POLICY + "\n" + POLICY
    return text


def fill(template: str, **kw: Any) -> str:
    """用 {{KEY}} 占位符填充模板（避免与 JSON 花括号冲突）。"""
    out = template
    for k, v in kw.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


# ---------------------------------------------------------------
# 结构化文本渲染（给文本阶段当输入用）
# ---------------------------------------------------------------

def atomic_table(actions: list[dict], with_states: bool = True) -> str:
    """把原子动作渲染成紧凑表格文本。"""
    if not actions:
        return "（空）"
    lines = ["id | 部位 | 动作 | 模式 | 起止(秒) | 给力 | 作用对象" +
             (" | 开始状态 → 结束状态" if with_states else "") + " | 维持到 | 来源 | 状态来源 | 操作目的 | 世界前状态 | 世界后状态 | 抓握准备校验 | 臂手功能"]
    for a in actions:
        row = [
            str(a.get("id", "?")),
            str(a.get("executor", "")),
            str(a.get("action", "")),
            str(a.get("mode", "")),
            f"{_fmt_t(a.get('start'))}-{_fmt_t(a.get('end'))}",
            _force_text(a),
            str(a.get("object") or "-"),
        ]
        if with_states:
            row.append(f"{a.get('state_before') or '-'} → {a.get('state_after') or '-'}")
        until = a.get("until")
        if isinstance(until, dict):
            row.append(str(until.get("text") or "-"))
        else:
            row.append(str(until or "-"))
        row.append("inferred（待核实）" if a.get("inferred") else "observed（模型观察）")
        row.append(f"before={a.get('state_before_from') or 'observed'}; after={a.get('state_after_from') or 'observed'}")
        row.extend([str(a.get("operation_intent") or ""),
                    str(a.get("world_before") or []), str(a.get("world_after") or [])])
        preparation = a.get("grasp_preparation") or {}
        row.append((str(preparation.get("status")) + "：" +
                    str(preparation.get("required_state")) + "；" + str(preparation.get("note")))
                   if preparation else "-")
        role = a.get("functional_role") or {}
        row.append(str(role.get("function") or "-") + "；" + str(role.get("atomic_capability") or ""))
        lines.append(" | ".join(row))
    return "\n".join(lines)


def _fmt_t(v: Any) -> str:
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return str(v)


def _force_text(a: dict) -> str:
    if not a.get("exerts_force"):
        return "否"
    role = a.get("force_role")
    return f"是({role})" if role else "是"


def relation_table(rels: list[dict], actions: list[dict] | None = None,
                   nodes: list[dict] | None = None) -> str:
    """把时序关系渲染成人可读文本（带动作名）。"""
    if not rels:
        return "（空）"
    amap = {a.get("id"): a.get("action", f"动作{a.get('id')}") for a in (actions or [])}
    nmap = {n.get("id"): n.get("name", n.get("id")) for n in (nodes or [])}
    lines = []
    for r in rels:
        f, t = r.get("from"), r.get("to")
        fa = amap.get(f, nmap.get(f, str(f)))
        fb = amap.get(t, nmap.get(t, str(t)))
        tmpl = RELATION_TEXT.get(r.get("relation", ""), "{a} → {b}")
        text = tmpl.format(a=fa, b=fb)
        note = r.get("note")
        lines.append(f"- [{r.get('relation')}] {text}" + (f"（{note}）" if note else ""))
    return "\n".join(lines)


def nodes_table(nodes: list[dict]) -> str:
    """任务节点（七元组）渲染。"""
    if not nodes:
        return "（空）"
    import json
    return "\n".join(json.dumps(n, ensure_ascii=False) for n in nodes)


def intents_table(intents: list[dict]) -> str:
    if not intents:
        return "（空）"
    import json
    return "\n".join(json.dumps(i, ensure_ascii=False) for i in intents)


def part_hint_text(intents: list[dict]) -> str:
    """把 2a 的部位先验转成 2b 的"重点关注"提示（只提示部位与角色，不给动作剧本）。"""
    rows: list[str] = []
    seen: set[str] = set()
    for it in intents or []:
        for bp in it.get("required_body_parts", []) or []:
            part = str(bp.get("part", "")).strip()
            if not part or part in seen:
                continue
            seen.add(part)
            rows.append(f"- {part}：可能在意图中承担「{bp.get('role', '参与')}」的作用（{bp.get('reason', '')}）")
    if not rows:
        return "- （意图未给出明确部位，请按画面自行判断所有部位）"
    rows.append("- 以上只是「需要关注哪些部位」的提示，**不代表这些部位一定有动作**；画面里没有发生的，不要写。")
    return "\n".join(rows)


# ---------------------------------------------------------------
# 校验器（给 llm.ask 用，抛异常即触发重试）
# ---------------------------------------------------------------

class ValidationFailure(ValueError):
    pass


def require_keys(obj: Any, keys: list[str], where: str = "") -> None:
    if not isinstance(obj, dict):
        raise ValidationFailure(f"{where} 期望对象，实际 {type(obj).__name__}")
    missing = [k for k in keys if k not in obj]
    if missing:
        raise ValidationFailure(f"{where} 缺字段：{missing}")


def validate_atomic(payload: Any) -> None:
    require_keys(payload, ["atomic_actions"], "atomic")
    acts = payload["atomic_actions"]
    if not isinstance(acts, list):
        raise ValidationFailure("atomic_actions 必须是数组")
    for i, a in enumerate(acts):
        require_keys(a, ["executor", "action", "mode", "start", "end"], f"atomic[{i}]")
        if a["mode"] not in (MODE_TRANSITION, MODE_MOTION, MODE_MAINTAIN):
            raise ValidationFailure(f"atomic[{i}] mode 非法：{a['mode']}")
        try:
            s, e = float(a["start"]), float(a["end"])
        except (TypeError, ValueError) as exc:
            raise ValidationFailure(f"atomic[{i}] 时间非数值") from exc
        if e < s:
            raise ValidationFailure(f"atomic[{i}] end < start")


def clamp_time(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return round(max(lo, min(hi, v)), 2)


def normalize_part(name: str) -> str:
    """把模型可能的别名收敛到标准部位词（单值；腿脚一体，脚归入腿）。"""
    n = str(name or "").strip()
    alias = {
        "手臂": "左臂", "手": "左手", "腿": "左腿", "脚": "左腿",
        "左脚": "左腿", "右脚": "右腿", "双脚": "左腿",
        "身体": "整体", "全身": "整体", "操作者": "整体", "左手臂": "左臂", "右手臂": "右臂", "上身": "躯干", "头颈": "头", "头部": "头",
        "脖子": "颈", "嘴巴": "口", "嘴": "口", "口部": "口",
    }
    if n in BODY_PARTS:
        return n
    return alias.get(n, n)


def is_ignored_part(name: object) -> bool:
    """该部位是否不参与操作（头 / 颈 / 口：只承担朝向 / 观察 / 言语，不产生操作）。"""
    return normalize_part(str(name or "")) in IGNORED_PARTS


# 这几个部位不产生"持续给力"（视觉 / 言语等功能不算施加作用）；
# 它们已不参与操作（IGNORED_PARTS），这里只是旧数据与兜底的开关。
FORCE_FREE_PARTS = {"头", "颈", "口"}

_FORCE_ALIAS = {
    "稳定支撑": "支撑", "保持": "保持抓握", "保持位置": "支撑", "握紧": "握持",
    "提举": "托举", "举起": "托举", "承重": "支撑", "夹持": "握持", "给力": "给力",
}
_NOT_FORCE_WORDS = ("视觉", "观察", "定位", "感知", "注视")


def normalize_force(a: dict) -> None:
    """力角色纪律（就地修改）：取值受控、不给力时清空、非体力部位不记力。"""
    from ..vocab import FORCE_ROLES

    part = str(a.get("executor") or "")
    role = a.get("force_role")
    if role is not None:
        role = str(role).strip()
        if role.lower() in ("null", "none", ""):
            role = None
    if role is not None:
        role = _FORCE_ALIAS.get(role, role)
        if role not in FORCE_ROLES:
            if part in FORCE_FREE_PARTS or any(w in role for w in _NOT_FORCE_WORDS):
                role = None
                a["exerts_force"] = False
            else:
                role = "给力"
    if not a.get("exerts_force"):
        role = None
    a["force_role"] = role


# 复数/群体部位展开（用于意图部位覆盖检查）；腿脚一体，不单列脚。
MULTI_PART_MAP: dict[str, list[str]] = {
    "双臂": ["左臂", "右臂"],
    "双手": ["左手", "右手"],
    "双腿": ["左腿", "右腿"],
    "双脚": ["左腿", "右腿"],
    "手臂": ["左臂", "右臂"],
    "上肢": ["左臂", "右臂", "左手", "右手"],
    "下肢": ["左腿", "右腿"],
    "腿": ["左腿", "右腿"],
    "脚": ["左腿", "右腿"],
    "手": ["左手", "右手"],
    "全身": ["整体"],
}


# 静息/被动状态词：出现这些说明该部位不在主动发力
PASSIVE_WORDS = ("自然下垂", "垂下", "下垂", "张开", "被动", "随动", "放松", "释放", "松开", "放开")


def enforce_active_force(a: dict) -> None:
    """主动运动/保持就是用力的（就地修正）。

    手臂/手/腿只要在做动作（不处于静息或被动状态），就应记 exerts_force=true：
    抬起、伸出、收回这些移动本身就要对抗重力，不能因为“还没碰到物体”就当作不给力。
    """
    part = str(a.get("executor") or "")
    text = str(a.get("action") or "")
    if not any(k in part for k in ("臂", "手", "腿")):
        return  # 头 / 颈 / 口 / 躯干不记“持续给力”
    if any(w in text for w in PASSIVE_WORDS):
        return
    if not a.get("exerts_force"):
        a["exerts_force"] = True
    if not a.get("force_role"):
        if "臂" in part:
            a["force_role"] = "托举"
        elif "手" in part:
            a["force_role"] = "抓握"
        else:
            a["force_role"] = "支撑"


def expand_parts(names: list[str]) -> list[str]:
    """把可能含复数写法的部位列表展开为标准部位列表（保持顺序、去重）。"""
    out: list[str] = []
    for n in names:
        n = str(n or "").strip()
        for p in MULTI_PART_MAP.get(n, [n]):
            if p and p not in out:
                out.append(p)
    return out


def rest_state(part: str) -> str:
    return REST_STATE.get(part, "未知")


def parts_functions() -> str:
    return part_functions_text()
