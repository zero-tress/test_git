#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""执行器语义程序（确定性）：把操作图翻译成"执行层能直接照着做"的形式。

领导要的是两套产物：一套给人看的演示（操作图 SVG / 报告），一套给执行器执行的
带语义有向图。这个模块产出的就是后者，三块内容：

  · operations       每个操作 = 一条 WHEN / DO / UNTIL 规则
                     WHEN  = C_pre（启动谓词：满足即开始）
                     DO    = 该操作下每个执行器的动作（谁、做什么、给什么力）
                     UNTIL = C_post（停止谓词：达到即结束）
  · executor_schedule 每个执行器的时刻表（什么时候开始、什么时候停、这段时间给什么力）
                     —— "让每一个执行器知道它什么时候开始，什么时候停止"
  · code             可以直接贴给执行层的伪代码文本

谓词一律定性（不出现角度/距离/力值），保证这套程序是语义层的调度依据而不是控制器参数。
"""

from __future__ import annotations

from .vocab import RELEASE_WORDS

MODE_CN = {"transition": "建立/解除", "motion": "移动", "maintain": "保持"}
BEYOND_TOL = 0.5       # 动作结束时刻超出操作结束多少秒算"延续到后续操作"


def _esc(text: object) -> str:
    return (str(text if text is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _fmt(v: object) -> str:
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "?"


def _show_force(s: dict) -> bool:
    """transition 型的"放开类"动作不展示力角色：释放瞬间不再需要保持给力。"""
    if s.get("mode") != "transition":
        return True
    return not any(w in str(s.get("action") or "") for w in RELEASE_WORDS)


def _rule(op: dict, steps: list[dict], parallel: list[str], alternation: list[str]) -> dict:
    hold = [{"executor": s["executor"], "action": s["action"], "mode": s["mode"],
             "start": s["start"], "end": s["end"],
             "force_role": s.get("force_role"), "object": s.get("object")}
            for s in steps if s.get("exerts_force") and _show_force(s)]
    return {
        "id": op["id"],
        "name": op["name"],
        "intent": op.get("intent") or "",
        "when": list(op.get("pre") or []),      # 启动谓词（C_pre）
        "do": steps,
        "until": list(op.get("post") or []),    # 停止谓词（C_post）
        "invariants": list(op.get("invariants") or []),
        "command": {"operation": op["name"], "objects": list(op.get("object") or []),
                    "required_capabilities": list(op.get("required_capabilities") or []),
                    "binding": {"status": "unbound", "executor": None, "skill": None}},
        "hold": hold,
        "executors": list(op.get("executors") or []),
        "parallel_with": parallel,
        "alternation_with": alternation,
        "start": op.get("start"),
        "end": op.get("end"),
        # MAINTAIN 节点：它不是一个“做完就结束”的操作，而是一个持续维持的状态，
        # 靠一个停止事件（而不是自己的 C_post）退出。
        "node_mode": str(op.get("mode") or "normal"),
        "maintain_until": list(op.get("maintain_until") or []),
        "covers": list(op.get("covers") or []),
        "held_by": list(op.get("held_by") or []),
        "lifted_from": list(op.get("lifted_from") or []),
    }


def build(bundle: dict) -> dict:
    """输入总产物 bundle（需含 operations / atomic），输出执行器语义程序。"""
    op_graph = bundle.get("operations") or {}
    ops = op_graph.get("nodes") or []
    actions = (bundle.get("atomic") or {}).get("atomic_actions") or []
    if not ops:
        return {"operations": [], "executor_schedule": {}, "code": [],
                "stats": {"operations": 0, "executors": 0, "hold": 0}}

    amap = {a.get("id"): a for a in actions if isinstance(a, dict)}
    pmap = {o["id"]: o["name"] for o in ops}
    intents = (bundle.get("intents") or {}).get("intents") or []
    task_intent = str(intents[0].get("statement") or "") if intents else ""
    par = {tuple(sorted(g)): g for g in (op_graph.get("parallel_groups") or [])}
    alt = [tuple(sorted(p)) for p in (op_graph.get("alternation_pairs") or [])]

    def partners(op: dict, kind: str) -> list[str]:
        names = []
        for group in par.values():
            if kind == "parallel" and op["id"] in group:
                names += [pmap.get(i, i) for i in group if i != op["id"]]
        if kind == "alternation":
            for a, b in alt:
                if op["id"] == a:
                    names.append(pmap.get(b, b))
                elif op["id"] == b:
                    names.append(pmap.get(a, a))
        return sorted(set(n for n in names if n))

    rules: list[dict] = []
    schedule: dict[str, list[dict]] = {}
    # 可启动性：前置条件无人提供的操作会被标出来（哪些能跑、哪些被条件阻塞）
    blocked: dict[str, list[str]] = {}
    provided: dict[str, dict[str, str]] = {}
    for c in (bundle.get("reasoning") or {}).get("checks") or []:
        if c.get("kind") in ("hold", "evidence") and c.get("action") == "flag":
            # 持续约束已有承担者、只是证据来自推理补全 → 图上有落点，不算堵死；
            # 但它仍是待核实项，写进 blocked_by 之外的提醒里。
            if c.get("covered_by_inferred"):
                continue
            blocked.setdefault(str(c.get("node") or ""), []).append(c.get("question") or "待核实")
        if c.get("kind") != "pre_coverage":
            continue
        nid = str(c.get("node") or "")
        cond = str(c.get("condition") or "")
        if c.get("verdict") not in ("provided", "ambient"):
            blocked.setdefault(nid, []).append(cond)
        elif c.get("verdict") == "provided":
            provided.setdefault(nid, {})[cond] = str(c.get("evidence") or "")
    for op in ops:
        steps = []
        for r in op.get("atomic_refs") or []:
            a = amap.get(r)
            if not a:
                continue
            steps.append({
                "atomic_ref": a.get("id"),
                "executor": str(a.get("executor") or ""),
                "action": str(a.get("action") or ""),
                "mode": str(a.get("mode") or ""),
                "start": round(float(a.get("start", 0)), 2),
                "end": round(float(a.get("end", 0)), 2),
                "exerts_force": bool(a.get("exerts_force")),
                "force_role": a.get("force_role"),
                "object": a.get("object"),
                "state_before": a.get("state_before"),
                "state_after": a.get("state_after"),
                "inferred": bool(a.get("inferred")),
                "until": a.get("until"),
            })
        steps.sort(key=lambda s: (s["start"], s["end"], s["executor"]))
        for s in steps:
            s["beyond"] = s["end"] > float(op.get("end") or 0) + BEYOND_TOL
        rules.append(_rule(op, steps, partners(op, "parallel"), partners(op, "alternation")))
        issues = list(blocked.get(op["id"], []))
        if not op.get("required_capabilities"):
            issues.append("操作能力需求待标注")
        if not op.get("post"):
            issues.append("缺少可检测的完成条件")
        if not (bundle.get("reasoning") or {}).get("checks"):
            issues.append("尚未完成证据校验")
        # Static evidence is not a live robot state or an executor binding.
        rules[-1]["startable"] = False if issues else None
        rules[-1]["readiness"] = "needs_review" if issues else "requires_binding_and_runtime_check"
        rules[-1]["blocked_by"] = issues
        rules[-1]["provided_by"] = provided.get(op["id"], {})
        rules[-1]["start_guard"] = {
            "type": "all", "predicates": list(op.get("pre") or []),
            "dependencies": [e["trigger"] for e in op_graph.get("edges") or []
                             if e.get("to") == op["id"] and e.get("trigger")
                             and e.get("basis") == "required_dependency"],
            "requires": ["executor_bound", "predicates_grounded", "resources_available"],
        }
        rules[-1]["stop_guard"] = {"type": "all", "predicates": list(op.get("post") or [])}
        rules[-1]["on_invariant_failure"] = "suspend_and_replan"
        for s in steps:
            schedule.setdefault(s["executor"], []).append({
                "op_id": op["id"], "op_name": op["name"],
                "action": s["action"], "mode": s["mode"],
                "start": s["start"], "end": s["end"],
                "force_role": s["force_role"] if s["exerts_force"] else None,
            })
    for rows in schedule.values():
        rows.sort(key=lambda r: (r["start"], r["end"]))

    return {
        "schema_version": "2.0",
        "kind": "unbound_operation_contract",
        "time_basis": "demonstration_only",
        "demonstration_graph": {
            "kind": "single_executor_evidence",
            "nodes": [{"id": a["id"], "operation": a.get("action"),
                       "executor": a.get("executor"), "object": a.get("object"),
                       "start": a.get("start"), "end": a.get("end"),
                       "until": a.get("until"), "inferred": bool(a.get("inferred")),
                       "parent_operations": [o["id"] for o in ops
                                             if a["id"] in (o.get("atomic_refs") or [])]}
                      for a in amap.values()],
            "relations": list(bundle.get("relations") or []),
        },
        "operations": rules,
        "executor_schedule": schedule,
        "code": _code(rules, schedule, op_graph, task_intent),
        "stats": {
            "operations": len(rules),
            "executors": len(schedule),
            "hold": sum(len(r["hold"]) for r in rules),
        },
    }


# ---------------------------------------------------------------
# 伪代码
# ---------------------------------------------------------------

def _code(rules: list[dict], schedule: dict, op_graph: dict, task_intent: str = "") -> list[str]:
    lines: list[str] = ["# 操作语义契约（待绑定执行器与谓词检测器）",
                        "# 视频秒数仅为示范证据；不作为目标机器人启动或停止条件。"]
    if task_intent:
        lines.append(f"# 任务意图：{task_intent}（下面每个操作都为它服务）")
    lines.append("")

    names = {o["id"]: o["name"] for o in op_graph.get("nodes") or []}
    for r in rules:
        is_hold = r.get("node_mode") == "maintain"
        tag = "（MAINTAIN：持续维持状态，不自己“做完”，靠停止事件退出）" if is_hold else ""
        lines.append(f"# 操作 {r['id']} · {r['name']}"
                     + (f"（操作意图：{r['intent']}）" if r["intent"] else "") + tag)
        if is_hold:
            covers = [str(x) for x in (r.get("covers") or [])]
            if covers:
                lines.append("# 覆盖过程：" + "、".join(
                    f"「{names.get(c, c)}」" for c in covers))
        if r.get("blocked_by"):
            lines.append(f"# ⚠ 启动条件尚无来源（需补证据）：{'；'.join(r['blocked_by'][:2])}")
        if r["when"]:
            lines.append(f"{'ON    ' if is_hold else 'WHEN  '}{r['when'][0]}")
            lines += [f"  AND {c}" for c in r["when"][1:]]
        else:
            lines.append(("ON    " if is_hold else "WHEN  ") + "（无显式前置条件）")
        for dependency in r["start_guard"]["dependencies"]:
            ev = dependency.get("event") or {}
            ref = ev.get("ref")
            if ev.get("type") == "action_completed":
                # 部分重叠的依赖：触发点在源动作完成那一刻，不是整个操作结束时
                lines.append(f"  AND AFTER_ACTION(#{ref})"
                             + (f"  # 中间触发：{dependency.get('predicate')}"
                                if dependency.get("predicate") else ""))
            else:
                lines.append(f"  AND COMPLETED({ref})")
        lines.append("  AND BOUND_EXECUTOR AND GROUNDED_PREDICATES AND RESOURCES_AVAILABLE")
        if is_hold:
            force = next((h.get("force_role") for h in r["hold"] if h.get("force_role")), None)
            lines.append(f"DO    MAINTAIN {r['name']}"
                         + (f"（持续给力：{force}）" if force else "")
                         + "　# 目标执行器及技能待绑定")
            until = [str(x) for x in (r.get("maintain_until") or [])]
            stop_text = ""
            for s in r["do"]:
                u = s.get("until")
                if isinstance(u, dict) and u.get("text"):
                    stop_text = str(u["text"])
                    break
            if until:
                lines.append(f"UNTIL STOP_WHEN COMPLETED({until[0]})"
                             + (f"　# {stop_text}" if stop_text else ""))
            elif r["until"]:
                lines.append(f"UNTIL {r['until'][0]}"
                             + (f"　# {stop_text}" if stop_text else ""))
            else:
                lines.append("UNTIL （停止事件未知，需补充；禁止用示范时间代替）")
        else:
            lines.append(f"DO    {r['name']}（目标执行器及技能待绑定）")
            for constraint in r["invariants"]:
                lines.append(f"WHILE {constraint}  ELSE SUSPEND_AND_REPLAN")
            if r["until"]:
                lines.append(f"UNTIL {r['until'][0]}")
                lines += [f"  AND {c}" for c in r["until"][1:]]
            else:
                lines.append("UNTIL （完成条件未知，需补充；禁止用示范时间代替）")
        if r["parallel_with"]:
            lines.append(f"# 示范中与「{'、'.join(r['parallel_with'])}」时段重叠；不代表同时开始或结束")
        if r["alternation_with"]:
            lines.append(f"# 与「{'、'.join(r['alternation_with'])}」交替执行")
        if r.get("held_by"):
            lines.append("# 本步全过程由 MAINTAIN 节点守护：" + "、".join(
                f"「{names.get(h, h)}」" for h in r["held_by"]))
        lines.append("")

    lines.append("# ---- 示范执行器时刻表（视频证据，不直接调度目标机器人） ----")
    for part, rows in schedule.items():
        lines.append(f"{part}:")
        for row in rows:
            force = f"　持续给力（{row['force_role']}）" if row.get("force_role") else ""
            lines.append(f"  {_fmt(row['start'])}~{_fmt(row['end'])}s  "
                         f"{row['op_name']} · {row['action']}{force}")
        lines.append("")

    groups = op_graph.get("parallel_groups") or []
    if groups:
        lines.append("# ---- 示范重叠关系组（组内不保证任意两项都重叠） ----")
        for g in groups:
            lines.append("∥ " + "  ∥  ".join(names.get(i, i) for i in g))
    return lines


def _do_line(s: dict) -> str:
    line = f"{s['executor']}：{s['action']} [{_fmt(s['start'])}~{_fmt(s['end'])}s]"
    if s.get("exerts_force") and s.get("force_role") and _show_force(s):
        line += f" 持续给力（{s['force_role']}）"
    if s.get("beyond"):
        line += "（延续到后续操作）"
    return line


# ---------------------------------------------------------------
# 渲染（报告里的"给执行器看"章节）
# ---------------------------------------------------------------

STYLE = """
.code{background:#0f172a;color:#e2e8f0;border-radius:8px;padding:12px 14px;
 font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12.5px;line-height:1.7;
 white-space:pre-wrap;overflow-x:auto}
.sched{width:100%;border-collapse:collapse;background:#fff;font-size:12.5px}
.sched th,.sched td{border:1px solid #e3e8ef;padding:5px 8px;text-align:left}
.sched th{background:#f7f9fc;font-weight:600}
.pred{display:inline-block;background:#eef2f8;border-radius:6px;padding:1px 7px;margin:2px 4px 2px 0;font-size:11.5px}
.pred.pre{background:#eef7ee;color:#215c3a}
.pred.post{background:#fdf1e6;color:#8a4b12}
.pred.bad{background:#fdecec;color:#9b2c2c}
.oprow{background:#fff;border:1px solid #e3e8ef;border-radius:8px;padding:10px 12px;margin:8px 0}
.oprow h4{margin:0 0 6px}
"""


def render_html(program: dict) -> str:
    rules = program.get("operations") or []
    if not rules:
        return "<p class='muted'>（无操作，无法生成执行器程序）</p>"
    out = []
    for r in rules:
        when = "".join(f"<span class='pred pre'>{_esc(c)}</span>" for c in r["when"]) or \
            "<span class='muted'>无显式前置条件</span>"
        until = "".join(f"<span class='pred post'>{_esc(c)}</span>" for c in r["until"]) or \
            "<span class='muted'>完成条件未知，需补充</span>"
        rows = "".join(
            f"<tr><td>{_esc(s['executor'])}</td><td>{_esc(s['action'])}"
            + ("<span class='sub'>（延续到后续操作）</span>" if s.get("beyond") else "") + "</td>"
            f"<td class='muted'>{_esc(MODE_CN.get(s['mode'], s['mode']))}</td>"
            f"<td>{_fmt(s['start'])}~{_fmt(s['end'])}s</td>"
            f"<td class='muted'>{_esc(s.get('force_role') if _show_force(s) else None) or '—'}</td></tr>"
            for s in r["do"])
        extra = ""
        if r["parallel_with"]:
            extra += f"<div class='sub'>并行：{'、'.join(_esc(x) for x in r['parallel_with'])}</div>"
        if r["alternation_with"]:
            extra += f"<div class='sub'>交替：{'、'.join(_esc(x) for x in r['alternation_with'])}</div>"
        blocked_note = ("<div class='sub'>⚠ 以下启动条件尚无来源："
                        + _esc("；".join(r["blocked_by"]))
                        + "（需补证据，不写成事实）</div>") if r.get("blocked_by") else ""
        out.append(f"""
<div class='oprow'>
  <h4>{_esc(r['id'])} · {_esc(r['name'])}
    <span class='muted'>{_fmt(r['start'])}~{_fmt(r['end'])}s</span>
    <span class='pred {'bad' if r.get('blocked_by') else 'pre'}'>{'待核实' if r.get('blocked_by') else '待绑定与运行时检测'}</span></h4>
  <div class='sub'>操作意图：{_esc(r['intent']) or '—'}</div>
  <div>启动条件（WHEN）：{when}</div>
  <div>停止条件（UNTIL）：{until}</div>
  <div>持续约束：{_esc('；'.join(r.get('invariants') or [])) or '未标注'}</div>
  <div class='sub'>下表是示范动作；目标执行器和技能尚未绑定，时间不是控制指令。</div>
  {blocked_note}
  <table class='sched'><thead><tr><th>执行器</th><th>动作</th><th>模式</th>
    <th>时段</th><th>力角色</th></tr></thead><tbody>{rows}</tbody></table>
  {extra}
</div>""")
    sched = program.get("executor_schedule") or {}
    if sched:
        parts = []
        for part, rows in sched.items():
            body = "".join(
                f"<tr><td>{_esc(part)}</td><td>{_fmt(x['start'])}~{_fmt(x['end'])}s</td>"
                f"<td>{_esc(x['op_name'])} · {_esc(x['action'])}</td>"
                f"<td class='muted'>{_esc(x.get('force_role') or '—')}</td></tr>"
                for x in rows)
            parts.append(body)
        out.append("<h4>执行器时刻表</h4><table class='sched'><thead><tr>"
                   "<th>执行器</th><th>时段</th><th>动作</th><th>力角色</th>"
                   "</tr></thead><tbody>" + "".join(parts) + "</tbody></table>")
    code = program.get("code") or []
    if code:
        out.append("<h4>待绑定的语义伪代码</h4><div class='code'>"
                   + _esc("\n".join(code)) + "</div>")
    return "\n".join(out)
