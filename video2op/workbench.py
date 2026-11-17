#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workbench · 把案例的操作图渲染成一个离线可交互页（确定性，不调用模型）。

实现本体：`tools/export_workbench.py` 是本模块的 CLI 薄壳；`pipeline.run_case`
与 `tools/render_case.py` 在渲染阶段结束后调用 `export()`，所以跑完 `run.py`
（或 `tools/render_case.py`）就会自动产出 `output/<案例>/workbench.html`。

交付对齐点（`new_task/新的任务.md`）：
  - 主图就是**操作图本身**（与 `operations.svg` 同一张图，同一个 render.operation_svg）：
    节点 = 操作（执行器是节点属性），不套“准备 / 抓取 / 搬运 / 放置 · 释放 / 撤回”这类上层阶段标签；
    图上保留关键关系——使能条件（提供什么条件）、先后、并行 / 交替、**保持直到**；
  - 点击节点在右侧展开**七元组** Si=⟨A,O,Pre,Con,Eval,Post,R⟩；
  - 七元组与全部详情在**生成时**就写进页面（不是点击后才生成），点击只切换显示；
  - 末端展开到**子操作 + 关系（含保持覆盖）+ 执行层检查点**，并给出台阶：
    子操作 → 能力 → 执行侧候选实现 / policy 首选实现（参数与超时留空待绑定）。

用法：
  python tools/export_workbench.py 移动物体            # → output/移动物体/workbench.html
  python tools/export_workbench.py 移动物体 --out /tmp/x.html
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

from . import render as v2o_render

REL_TEXT = {"enables": "条件依赖", "sequence": "顺序", "parallel": "并行",
            "maintain_until": "保持直到"}
KIND_TEXT = {"establish": "建立", "release": "解除", "motion": "移动", "hold": "保持"}
KIND_CLS = {"establish": "k-est", "release": "k-rel", "motion": "k-mov", "hold": "k-hold"}

# 九节点模板（new_task/新的任务.md 的人工对照，供验收时逐条核对；页面会标注这是人工对照）
TEMPLATE_ROWS = [
    ("①", "靠近", "手臂到达抓取位姿，可与②重叠"),
    ("②", "打开", "手达到准备开度；完成后张开保持到④开始"),
    ("③", "保持抓取位姿", "手臂位姿保持；持续到⑤生效且⑥接管（不等⑤完成）"),
    ("④", "抓握", "稳定抓握建立；③先进入有效保持，④再开始"),
    ("⑤", "保持抓握", "覆盖⑥并延续到⑦生效、释放条件满足、⑧接管"),
    ("⑥", "移动杯子", "到位、停止、可靠受支撑；⑥不会“变成”⑦"),
    ("⑦", "保持释放位姿", "手臂位姿保持；⑦先生效，再允许⑧释放；持续到⑨接管"),
    ("⑧", "释放", "解除抓握且物体稳定；与⑤是同一只手的控制切换"),
    ("⑨", "移动撤回", "到达撤回位姿"),
]
TEMPLATE_NOTES = {
    "②": "未观测到独立的“打开”动作时的说明：张开状态由抓握的必要前提承担（本项目会用先验规则补出候选步骤）。",
    "⑦": "未观测到独立的“释放期位姿保持”时的说明：释放期间手臂的静置没有记录（本项目会用先验规则补出候选）。",
}


def _template_role(node: dict) -> str:
    """按节点语义给一个模板序号标签（人工对照规则，不是数据字段）。"""
    name = str(node.get("name") or "")
    if node.get("mode") == "MAINTAIN":
        cat = str(node.get("hold_category") or "")
        if cat == "pose":
            ho = "、".join(node.get("handoff_to") or [])
            if any(w in ho for w in ("收回", "撤回", "退回", "撤退", "复位", "归位")):
                return "⑦ 保持释放位姿"
            return "③ 保持抓取位姿"
        if cat == "grasp":
            return "⑤ 保持抓握"
        return "保持（模板③/⑤/⑦）"
    if any(w in name for w in ("接近", "靠近", "走到")):
        return "① 靠近"
    if any(w in name for w in ("释放", "松开", "放开")):
        return "⑧ 释放"
    if any(w in name for w in ("张开", "打开", "拉开", "拧开")):
        return "② 打开"
    if any(w in name for w in ("收回", "撤回", "退回", "复位", "归位")):
        return "⑨ 移动撤回"
    if any(w in name for w in ("搬运", "移动", "转移", "挪动")):
        return "⑥ 移动"
    if any(w in name for w in ("放置", "放下", "安放")):
        return "⑥ 落放段"
    if any(w in name for w in ("抓握", "抓紧", "握住", "抓取")):
        return "④ 抓握"
    return ""


def _edge_rationale(ed: dict) -> str:
    """这条关系凭什么这么画（把证据强度译成人话）。"""
    parts = []
    basis = ed.get("basis")
    support = ed.get("support")
    if basis == "required_dependency":
        parts.append("执行依赖：前一步产生/提供的条件正是后一步的前提")
    elif basis == "observed_order":
        parts.append("仅观测到的先后——不固化为执行约束（示范者可能只是刚好这个顺序）")
    if support == "observed_state":
        parts.append("有观测后状态支持")
    elif support == "order":
        parts.append("只有时间先后，没有观测状态支持")
    elif support == "split_schedule":
        parts.append("由释放拆分确定：就位后才能解除作用（否则保持与释放互等执行器）")
    elif support == "unverified":
        parts.append("条件衔接未获证据支持")
    ib = ed.get("inferred_by")
    if ib == "maintain_lift":
        parts.append("由保持节点提升推导（建立→覆盖→交接）")
    elif ib == "release_split":
        parts.append("由释放步骤拆分推导")
    elif ib == "prior_step_lift":
        parts.append("由先验步骤提升推导：这一步是后继动作的必要前提（功能先验推理，不是观测证据）")
    return "；".join(parts)


def e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def truncate(text: str, n: int) -> str:
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


def side_verify(case_dir: Path) -> dict:
    """读取（若存在）执行侧结构验证输出，只引用结论，不重新解释。"""
    path = case_dir / "verify_contract.txt"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"谓词清单：(.+)", text)
    return {"file": path.name, "summary": m.group(1).strip() if m else ""}


def build(case_dir: Path, *, bundle: dict | None = None) -> dict:
    from .render import intent_hierarchy_html
    if bundle is None:
        bundle = json.loads((case_dir / "result.json").read_text(encoding="utf-8"))
    contract = bundle.get("contract") or {}
    sg = contract.get("nodes") or {}
    ops = ((bundle.get("operations") or {}).get("nodes")) or []
    edges = ((bundle.get("operations") or {}).get("edges")) or []
    expansion = (bundle.get("expansion") or {}).get("by_operation") or {}
    program = {o["id"]: o for o in ((bundle.get("program") or {}).get("operations") or [])}
    task_nodes = {n["id"]: n for n in
                  ((bundle.get("task_nodes") or {}).get("task_nodes") or [])}
    preds = (bundle.get("predicates") or {}).get("predicates") or []
    text2id = {}
    roles_by_node: dict[str, list[dict]] = {}
    for p in preds:
        text2id.setdefault(str(p.get("text") or ""), p.get("id"))
        for r in p.get("roles") or []:
            roles_by_node.setdefault(str(r.get("node")), []).append(
                {"id": p.get("id"), "text": p.get("text"), "role": r.get("role")})
    policy = (bundle.get("execution_policy") or {}).get("implementations") or {}
    schedule = ((bundle.get("program") or {}).get("executor_schedule")) or {}
    atomic = {a.get("id"): a for a in
              ((bundle.get("atomic") or {}).get("atomic_actions")) or []}
    # Expose only case-local evidence images as portable relative links.
    from copy import deepcopy
    atomic = deepcopy(atomic)
    for a in atomic.values():
        frames = list(a.get("visual_evidence") or [])
        frames += [f for item in a.get("visual_state_evidence") or [] for f in item["frames"]]
        for frame in frames:
            try:
                frame["display_path"] = Path(frame["path"]).resolve().relative_to(case_dir.resolve()).as_posix()
            except ValueError:
                frame["display_path"] = ""
    sampling_doc = bundle.get("sampling") or {}
    gallery = ""
    if sampling_doc.get("directory"):
        try:
            gallery = (Path(sampling_doc["directory"]).resolve() / "index.html").relative_to(case_dir.resolve()).as_posix()
        except ValueError:
            pass
    review = bundle.get("local_review") or {}
    media_review = {"gallery": gallery, "sampling_status": sampling_doc.get("status"),
                    "reviewed": sum(p.get("status") == "reviewed" for p in review.get("proposals") or []),
                    "unresolved": sum(p.get("status") in {"failed", "skipped_budget"}
                                      for p in review.get("proposals") or []),
                    "conflicts": sum(len(r["applied"]["conflicts"]) for r in review.get("results") or [])}
    # 操作 id → 契约 id（A1/H1/...）
    cid_by_op = {}
    for cid, node in sg.items():
        opid = ((node.get("x-video2op") or {}).get("operation_id"))
        if opid:
            cid_by_op[opid] = cid

    nodes = []
    name_by_id = {o.get("id"): (o.get("name") or "") for o in ops}
    for op in ops:
        opid = op.get("id")
        cid = cid_by_op.get(opid, "")
        node_contract = sg.get(cid) or {}
        exp = expansion.get(opid) or {}
        prog = program.get(opid) or {}
        tn = task_nodes.get(opid) or {}
        tup = tn.get("tuple") or {}
        derived = not bool(tup)
        if derived:  # 派生只从既有字段取材，不改写：来源在页面上标出
            tup = {
                "X": {"subject": "操作者", "parts": list(op.get("executors") or [])},
                "O": list(op.get("object") or []),
                "C_pre": list(op.get("pre") or []),
                "C_const": list(op.get("invariants") or []),
                "E": {"process": [], "completion": list(op.get("completion") or [])},
                "C_post": list(op.get("post") or []),
                "R": [],
            }
        refs = [rid for rid in (op.get("atomic_refs") or []) if rid in atomic]
        nodes.append({
            "id": opid,
            "cid": cid,
            "name": op.get("name") or "",
            "mode": node_contract.get("mode") or "NORMAL",
            "executors": list(op.get("executors") or []),
            "object": list(op.get("object") or []),
            "time": ((tn.get("time_range") or [None, None]) if bundle.get("single_actor_version") else [op.get("start"), op.get("end")]),
            "intent": op.get("intent") or "",
            "purpose": op.get("purpose") or "",
            "layer": op.get("layer"),
            "tuple": tup,
            "preparation_requirements": tn.get("preparation_requirements") or [],
            "functional_roles": tn.get("functional_roles") or [],
            "reach_requirements": tn.get("reach_requirements") or [],
            "scoped_grip_constraints": tn.get("scoped_grip_constraints") or [],
            "constraint_revisions": tn.get("constraint_revisions") or [],
            "tuple_derived": derived,
            "tuple_source": ("task_nodes.tuple" if not derived
                             else "契约/展开字段派生（该操作由修订新增，无任务级七元组）"),
            "contract": {
                "pre": node_contract.get("pre") or [],
                "constraints": node_contract.get("constraints") or [],
                "evaluator": node_contract.get("evaluator") or [],
                "post": node_contract.get("post") or [],
                "implementation": node_contract.get("implementation") or [],
                "dependencies": node_contract.get("dependencies") or [],
                "maintain_until": node_contract.get("maintain_until") or [],
            },
            "policy_impl": policy.get(cid, ""),
            "program": {
                "when": prog.get("when") or [],
                "until": prog.get("until") or [],
                "startable": prog.get("startable"),
                "blocked_by": prog.get("blocked_by") or [],
                "held_by": [name_by_id.get(x, x) for x in (prog.get("held_by") or [])],
                "covers": [name_by_id.get(x, x) for x in (prog.get("covers") or [])],
                "start_guard": prog.get("start_guard") or {},
            },
            "subs": exp.get("sub_operations") or [],
            "sub_relations": exp.get("relations") or [],
            "checkpoints": exp.get("checkpoints") or [],
            "atomic_refs": refs,
            "observed_effects": op.get("observed_effects") or [],
            "effect_evidence": op.get("effect_evidence") or [],
            "predicate_roles": roles_by_node.get(opid, []),
            "sub_predicate_roles": [r for k, rs in roles_by_node.items()
                                    if k.startswith(opid + ".")
                                    for r in [{**x, "sub": k} for x in rs]],
            "hold_category": op.get("hold_category") or "",
            "covers": [name_by_id.get(c, c) for c in (op.get("covers") or [])],
            "inferred": bool(op.get("inferred")),
            "already_satisfied": bool(op.get("already_satisfied")),
            "origin": op.get("origin"),
            "inference_reason": op.get("inference_reason") or "",
            "pre_inferred": list(op.get("pre_inferred") or []),
            "provides": op.get("provides") or "",
            "handoff_to": [name_by_id.get(h, h) for h in (op.get("handoff_to") or [])],
            "maintain_until_mode": op.get("maintain_until_mode") or "",
            "template_role": _template_role({
                "name": op.get("name") or "",
                "mode": "MAINTAIN" if str(op.get("mode")) == "maintain" else "",
                "hold_category": op.get("hold_category") or "",
                "handoff_to": [name_by_id.get(h, h) for h in (op.get("handoff_to") or [])]}),
        })

    edge_rows = []
    for idx, ed in enumerate(edges):
        rel = ed.get("relation") or ""
        trig = (ed.get("trigger") or {}).get("predicates") or []
        fname = name_by_id.get(ed.get("from"), ed.get("from"))
        tname = name_by_id.get(ed.get("to"), ed.get("to"))
        if rel == "enables":
            label = ("条件：" + "、".join(trig)) if trig else "提供前置条件"
        elif rel == "sequence":
            label = ("拆分：就位后释放" if ed.get("support") == "split_schedule"
                     else ("先后（仅观测）" if ed.get("basis") == "observed_order" else "顺序"))
        elif rel == "parallel":
            label = "∥ 并行"
        elif rel == "maintain_until":
            label = f"握持至「{tname}」开始前" if ed.get("until_event") == "target_starts" else f"保持直到「{tname}」"
        else:
            label = rel
        edge_rows.append({
            "idx": idx,
            "from": ed.get("from"), "to": ed.get("to"), "relation": rel,
            "from_name": fname, "to_name": tname,
            "label": truncate(label, 20), "full": label,
            "note": ed.get("note") or "", "basis": ed.get("basis"),
            "support": ed.get("support"), "trigger": trig,
            "rationale": _edge_rationale(ed),
        })

    schedule_rows = []
    for executor, items in schedule.items():
        schedule_rows.append({
            "executor": executor,
            "blocks": [{
                "op": it.get("op_name"), "op_id": it.get("op_id"),
                "action": it.get("action"), "mode": it.get("mode"),
                "start": it.get("start"), "end": it.get("end"),
                "force": it.get("force_role"),
            } for it in items],
        })

    reasons = bundle.get("reasoning") or {}
    validation = bundle.get("validation") or {}
    # 主图 = 门控状态机图（与 operations.svg 同一张图，多带机器可读锚点供页面联动）
    main_svg = v2o_render.gate_svg(bundle)
    gdoc = bundle.get("gates") or {}
    gate_rows = [{
        "id": g.get("id"), "seq": g.get("seq"), "state": g.get("state"),
        "from_names": g.get("from_names") or [], "to_names": g.get("to_names") or [],
        "lines": g.get("lines") or [], "reason": g.get("reason") or "",
        "unresolved": g.get("unresolved") or [],
        "checks": [{
            "kind": c.get("kind"), "text": c.get("text"), "state": c.get("state"),
            "verdict": c.get("verdict"), "evidence": c.get("evidence"),
            "gate": bool(c.get("gate")), "quality": c.get("quality") or "",
            "provider_name": c.get("provider_name") or "",
        } for c in g.get("checks") or []],
    } for g in gdoc.get("gates") or []]
    stats = {
        "operations": len(nodes),
        "subs": sum(len(n["subs"]) for n in nodes),
        "checkpoints": sum(len(n["checkpoints"]) for n in nodes),
        "holds": sum(1 for n in nodes if n["mode"] == "MAINTAIN"),
        "inferred_subs": sum(1 for n in nodes for s in n["subs"] if s.get("inferred")),
        "edges": len(edge_rows),
        "gates": len(gate_rows),
        "gates_T": sum(1 for g in gate_rows if g["state"] == "T"),
        "gates_U": sum(1 for g in gate_rows if g["state"] == "U"),
        "gates_F": sum(1 for g in gate_rows if g["state"] == "F"),
    }
    intent_items = bundle.get("intents") or []
    if isinstance(intent_items, dict):
        intent_items = intent_items.get("intents") or []
    task_intent = next((it if isinstance(it, str) else (it or {}).get("statement", "")
                        for it in intent_items), "") or ""
    return {
        "case": case_dir.name,
        "intent_hierarchy_html": intent_hierarchy_html(bundle),
        "media_review": media_review,
        "learning_layer": bundle.get("learning_layer"),
        "task_intent": (sg.get("task_intent") or "") or task_intent,
        "stats": stats,
        "validation": {"summary": validation.get("summary"),
                       "passed": validation.get("passed"),
                       "needs_review": validation.get("needs_review") or []},
        "main_svg": main_svg,
        "gates": gate_rows,
        "gate_stats": gdoc.get("stats") or {},
        "nodes": nodes,
        "edges": edge_rows,
        "template_check": [
            {"no": no, "name": name, "desc": desc,
             "node": next((n["name"] for n in nodes
                            if str(n.get("template_role") or "").startswith(no)), ""),
             "node_cid": next((n["cid"] for n in nodes
                               if str(n.get("template_role") or "").startswith(no)), ""),
             "note": TEMPLATE_NOTES.get(no, "")}
            for no, name, desc in TEMPLATE_ROWS],
        "schedule": schedule_rows,
        "predicates": [{"id": p.get("id"), "text": p.get("text"), "verb": p.get("verb"),
                        "agent": p.get("agent"), "spatial": p.get("spatial"),
                        "n_roles": len(p.get("roles") or [])} for p in preds],
        "predicate_by_text": text2id,
        "side_verify": side_verify(case_dir),
        "revisions": reasons.get("revisions") or [],
        "gaps": reasons.get("gaps") or [],
        "atomic": dict(atomic),
        "policy_status": ((bundle.get("execution_policy") or {}).get("x-video2op") or {}).get("status", ""),
    }


# ---------------------------------------------------------------- 片段渲染

def pred_line(text: str, t2i: dict) -> str:
    pid = t2i.get(str(text))
    if pid:
        return (f'<div class="pv"><span class="pred">{e(pid)}</span>'
                f'<span class="ptxt">{e(text)}</span></div>')
    return f'<div class="pv"><span class="plain">{e(text)}</span></div>'


def pred_lines(items, t2i) -> str:
    if not items:
        return '<div class="pv empty">（未记录）</div>'
    return "".join(pred_line(x, t2i) for x in items)


def pred_chips(ids) -> str:
    if not ids:
        return '<span class="muted">（无）</span>'
    return " ".join(f'<span class="pred">{e(i)}</span>' for i in ids)


def tuple_rows(node: dict, t2i: dict) -> str:
    t = node["tuple"]
    x = t.get("X") or {}
    parts = x.get("parts") or []
    subj = x.get("subject") or ""
    a_text = " · ".join([subj] + [str(p) for p in parts]) if (subj or parts) else "（未记录）"
    ev = t.get("E") or {}
    pre_html = pred_lines(t.get("C_pre"), t2i)
    for x in node.get("pre_inferred") or []:
        pre_html += f'<div class="pv inf-note">＋推理补充前提：{e(x)}</div>'
    eval_html = []
    if isinstance(ev, dict):
        for label, key in (("过程", "process"), ("完成", "completion")):
            for item in ev.get(key) or []:
                eval_html.append(f'<div class="pv"><span class="tlab">{label}</span>{e(item)}</div>')
    elif isinstance(ev, list):
        eval_html = [f'<div class="pv">{e(x)}</div>' for x in ev]
    if node["contract"]["evaluator"]:
        eval_html.append('<div class="pv"><span class="tlab">执行侧检查器</span>'
                         + pred_chips(node["contract"]["evaluator"]) + "</div>")
    r_html = []
    for r in t.get("R") or []:
        if isinstance(r, dict):
            steps = " → ".join(str(s) for s in (r.get("steps") or []))
            r_html.append(f'<div class="pv"><b>{e(r.get("name"))}</b>'
                          f'<span class="tag">{e(r.get("origin"))}</span>'
                          f'<div class="steps">{e(steps)}</div></div>')
    if node["contract"]["implementation"]:
        r_html.append('<div class="pv"><span class="tlab">执行侧候选实现</span>'
                      + " · ".join(e(i) for i in node["contract"]["implementation"]) + "</div>")
    if not r_html:
        r_html = ['<div class="pv empty">（未记录）</div>']
    rows = [
        ("A 执行主体", f'<div class="pv">{e(a_text)}</div>'),
        ("O 操作对象", pred_lines(t.get("O") or node["object"], t2i)),
        ("Pre 前置条件", pre_html),
        ("Con 约束元", pred_lines(t.get("C_const"), t2i)),
        ("Eval 评价指标", "".join(eval_html) or '<div class="pv empty">（未记录）</div>'),
        ("Post 后置效果", pred_lines(t.get("C_post"), t2i)),
        ("R 候选方式集合", "".join(r_html)),
    ]
    out = []
    for key, val in rows:
        out.append(f'<div class="trow"><div class="tkey">{e(key)}</div>'
                   f'<div class="tval">{val}</div></div>')
    return "".join(out)


def subs_html(node: dict) -> str:
    subs = node["subs"]
    if not subs:
        return '<div class="empty">该操作没有可展开的原子动作。</div>'
    out = []
    for s in subs:
        kind = s.get("kind") or ""
        pre = (s.get("pre") or ["—"])[0]
        post = (s.get("post") or ["—"])[0]
        inf = ""
        if s.get("inferred"):
            inf = (f'<div class="sub-inf">⚠ 推理补全：{e(truncate(s.get("inference_reason"), 200))}</div>')
        until = ""
        if s.get("until"):
            until = f'<div class="sub-meta">持续到：{e((s.get("until") or {}).get("text"))}</div>'
        out.append(
            f'<div class="sub">'
            f'<div class="sub-h"><span class="kind {KIND_CLS.get(kind, "")}">{e(KIND_TEXT.get(kind, kind))}</span>'
            f'<span class="sub-n">{e(s.get("name"))}</span>'
            f'<span class="sub-e">{e(s.get("executor"))}</span>'
            f'<span class="sub-t">{e(s.get("start"))}–{e(s.get("end"))}s</span></div>'
            f'<div class="sub-meta">能力需求：<b>{e(s.get("capability"))}</b>'
            f'　给力：{e(s.get("force_role") or "—")}{"（持续给力）" if s.get("exerts_force") else ""}</div>'
            f'<div class="sub-meta">{e(pre)} → {e(post)}</div>{until}{inf}</div>')
    rels = []
    for r in node["sub_relations"]:
        rel = r.get("relation")
        txt = r.get("note") or f'{r.get("from")} → {r.get("to")}'
        rels.append(f'<div class="relc {e(rel)}"><span class="tag">{e(REL_TEXT.get(rel, rel))}</span>{e(txt)}</div>')
    chks = []
    for c in node["checkpoints"]:
        at = f'@ {e(c.get("at"))}s' if c.get("at") is not None else ""
        during = " · ".join(str(x) for x in c.get("during") or [])
        chks.append(f'<div class="chk"><b>{e(c.get("kind"))}</b>：{e(c.get("question"))} '
                    f'<span class="at">{at or (during and during + "s") or ""}</span>'
                    f'<div class="sub-meta">{e(c.get("note"))}</div></div>')
    return ("".join(out)
            + ('<div class="rel-title">子操作关系</div>' + "".join(rels) if rels else "")
            + ('<div class="rel-title">执行层检查点</div>' + "".join(chks) if chks else ""))


def evidence_html(node: dict, atomic: dict) -> str:
    if node["time"][0] is None or node["time"][1] is None:
        out = ['<div class="kv"><span>示范时间</span><b>未观察到独立动作时间</b></div>']
    else:
        out = [f'<div class="kv"><span>示范时间</span><b>{e(node["time"][0])} – {e(node["time"][1])} s</b></div>']
    for ref in node["atomic_refs"]:
        a = atomic.get(ref) or {}
        out.append(
            f'<div class="evatom">#{e(ref)} <b>{e(a.get("executor"))}</b> {e(a.get("action"))} '
            f'[{e(a.get("start"))}–{e(a.get("end"))}s · {e(a.get("mode"))}]'
            f'{" · 推理补全" if a.get("inferred") else ""}'
            f'<div class="sub-meta">{e(a.get("state_before"))} → {e(a.get("state_after"))}'
            f'{"　证据：" + e(truncate(a.get("evidence"), 80)) if a.get("evidence") else ""}</div></div>')
        visual = list(a.get("visual_evidence") or [])
        for item in a.get("visual_state_evidence") or []:
            out.append(f'<div class="pv">局部复查：{e(item["state"])}（{e(item["field"])}）</div>')
            visual.extend(item["frames"])
        seen = set()
        for frame in visual:
            src = frame.get("display_path")
            if not src or frame["frame_id"] in seen:
                continue
            seen.add(frame["frame_id"])
            out.append(f'<figure><a target="_blank" href="{e(src)}"><img loading="lazy" '
                       f'src="{e(src)}" style="max-width:100%" alt="复查证据帧"></a>'
                       f'<figcaption>{e(frame["frame_id"])} · 源视频 {e(frame["timestamp"])} s</figcaption></figure>')
    if node["observed_effects"]:
        out.append('<div class="ev-title">观测效果</div>')
        for oe in node["observed_effects"]:
            out.append(f'<div class="pv">#{e(oe.get("atomic_ref"))} {e(oe.get("state"))}</div>')
    if node["effect_evidence"]:
        out.append('<div class="ev-title">效果证据（预期 vs 观测）</div>')
        for ee in node["effect_evidence"]:
            out.append(f'<div class="pv">{e(ee.get("expected"))} '
                       f'<span class="tag">{e(ee.get("status"))}</span> '
                       f'<span class="muted">原子动作 {e(ee.get("atomic_refs"))}</span></div>')
    return "".join(out)


def contract_html(node: dict) -> str:
    c = node["contract"]
    p = node["program"]
    detectors = list(dict.fromkeys(
        list(c["pre"]) + list(c["constraints"]) + list(c["evaluator"]) + list(c["post"])))
    startable = p.get("startable")
    if startable is True:
        st = '<b class="ok">true</b>'
    elif startable is False:
        st = f'<b class="warn">false</b>（阻塞：{e("、".join(p.get("blocked_by") or []))}）'
    else:
        st = '<b class="muted">null（待绑定执行器与运行时检测）</b>'
    rows = [
        ("契约节点", f'<b>{e(node["cid"])}</b>　模式 <b>{e(node["mode"])}</b>'),
        ("依赖", e("、".join(c["dependencies"])) or "—"),
        ("保持直到", e("、".join(c["maintain_until"])) or "—"),
        ("候选实现（执行侧词表）", " · ".join(e(i) for i in c["implementation"]) or "—"),
        ("首选实现（policy）", e(node["policy_impl"]) or "—"),
        ("参数绑定 / 超时", '<span class="muted">未绑定——接入时由真实执行器给（execution_policy 中为空）</span>'),
        ("可启动性", st),
        ("谓词检测器（执行侧需注册）", pred_chips(detectors)),
    ]
    if p.get("held_by"):
        rows.append(("被保持覆盖", e("、".join(p["held_by"]))))
    if p.get("covers"):
        rows.append(("覆盖操作", e("、".join(p["covers"]))))
    if node.get("handoff_to"):
        names = ",".join(node["handoff_to"])
        rows.append(("结束交接", f'保持结束后由「{e(names)}」接管执行器控制'
                                f'（同一时刻交接，双方不互相等待）'))
    if node.get("maintain_until_mode") == "handoff":
        rows.append(("终点语义", "交接型：结束于被覆盖操作完成，控制随即交给下一操作"
                                "——不是“等下一操作完成”（那会互相等执行器）"))
    return "".join(f'<div class="kv"><span>{e(k)}</span><span>{v}</span></div>' for k, v in rows)


GATE_KIND_CN = {"effect": "换挡条件", "prior": "必要前提", "constraint": "持续约束",
                "context": "场景前提", "pre": "前置条件"}


def gate_detail_html(g: dict) -> str:
    """门控详情：这一跳的条件、状态与依据（点击主图里的菱形打开）。"""
    state = str(g.get("state") or "U")
    rows = []
    for c in g.get("checks") or []:
        kind = GATE_KIND_CN.get(str(c.get("kind")), str(c.get("kind")))
        st = str(c.get("state"))
        mark = {"T": "✔", "F": "✘"}.get(st, "○")
        extra = "" if c.get("gate") else ' <span class="muted">（不参与放行判定）</span>'
        qual = (' <span class="muted">（已被反证剔除，不再当必要条件）</span>'
                if c.get("quality") == "rejected" else "")
        rows.append(
            f'<div class="trow"><div class="tkey">{mark} {e(kind)} · {e(st)}</div>'
            f'<div class="tval">{e(c.get("text"))}{extra}{qual}'
            f'<div class="purpose">{e(c.get("evidence") or c.get("verdict") or "")}</div>'
            f'</div></div>')
    body = "".join(rows) or '<div class="purpose">（该门控暂无登记条件）</div>'
    head = f'门控 {e(g.get("seq"))} · {e(g.get("id"))}'
    way = (f'{e("、".join(g.get("from_names") or []))}'
           f' → {e("、".join(g.get("to_names") or []))}')
    return ('<section class="detail" data-gate="' + e(g.get("id")) + '" hidden>'
            '<div class="dhead"><div class="dtitle">'
            f'<span class="dname">{head}</span>'
            f'<span class="cid">放行状态 {e(state)}</span></div>'
            f'<div class="dbadges"><span class="badge mode">{e(state)}</span></div></div>'
            f'<div class="dintent"><span class="tlab">放行方向</span>{way}'
            f'<div class="purpose">{e(g.get("reason"))}</div></div>'
            '<div class="dsec"><div class="dsec-t">条件与依据（来自七元组的 PRE / POST / CONST）</div>'
            f'{body}</div></section>')


def detail_html(node: dict, t2i: dict, atomic: dict) -> str:
    purpose_line = (f'<div class="purpose">服务后续：{e(node["purpose"])}</div>'
                    if node["purpose"] else "")
    mode_line = ('<span class="badge mode">MAINTAIN 保持</span>'
                 if node["mode"] == "MAINTAIN" else "")
    tpl_line = (f'<span class="badge tpl-full">模板：{e(node["template_role"])}</span>'
                if node.get("template_role") else "")
    infer_line = (f'<div class="purpose">推理补全：{e(node.get("inference_reason") or "")}</div>'
                  if node.get("inferred") else "")
    return f'''<section class="detail" data-id="{e(node["id"])}" hidden>
  <div class="dhead">
    <div class="dtitle"><span class="dname">{e(node["name"])}</span>
      <span class="cid">{e(node["cid"])} · {e(node["id"])}</span></div>
    <div class="dbadges">{mode_line}{tpl_line}</div>
  </div>
  <div class="dintent"><span class="tlab">局部目的</span>{e(node["intent"])}
    {purpose_line}
    <div class="purpose">执行器（属性）：{e("、".join(node["executors"]))}</div>
    {infer_line}
  </div>
  <div class="dsec">
    <div class="dsec-t">七元组 Si = ⟨A, O, Pre, Con, Eval, Post, R⟩
      <span class="src">{e(node["tuple_source"])}{" · 派生视图" if node["tuple_derived"] else ""}</span></div>
    {tuple_rows(node, t2i)}
  </div>
  <div class="dsec"><div class="dsec-t">证据（示范定位）</div>{evidence_html(node, atomic)}</div>
  <div class="dsec"><div class="dsec-t">子操作展开（执行单元）</div>{subs_html(node)}</div>
  <div class="dsec"><div class="dsec-t">执行层对接</div>{contract_html(node)}</div>
</section>'''


def edge_detail_html(edge: dict) -> str:
    rows = [
        ("关系类型", f'<b>{e(REL_TEXT.get(edge["relation"], edge["relation"]))}</b>'),
        ("方向", f'{e(edge["from_name"])} → {e(edge["to_name"])}'),
        ("说明", e(edge["note"])),
    ]
    if edge.get("trigger"):
        rows.append(("触发条件", pred_chips(edge["trigger"])))
    if edge.get("rationale"):
        rows.append(("依据（证据强度）", e(edge["rationale"])))
    body = "".join(f'<div class="kv"><span>{e(k)}</span><span>{v}</span></div>'
                   for k, v in rows)
    return f'''<section class="detail" data-edge="{edge["idx"]}" hidden>
  <div class="dhead"><div class="dtitle">
    <span class="dname">{e(REL_TEXT.get(edge["relation"], edge["relation"]))}</span>
    <span class="cid">关系 {edge["idx"] + 1}</span></div></div>
  <div class="dsec">{body}</div>
</section>'''


def timeline_html(data: dict) -> str:
    total = 0.0
    for row in data["schedule"]:
        for b in row["blocks"]:
            total = max(total, float(b.get("end") or 0))
    if total <= 0:
        return ""
    ticks = "".join(
        f'<div class="tl-tick" style="left:{100 * t / total:.2f}%">{int(t)}s</div>'
        for t in range(0, int(total) + 1, 2))
    rows = []
    for row in data["schedule"]:
        blocks = []
        for b in row["blocks"]:
            left = 100 * float(b.get("start") or 0) / total
            width = max(1.2, 100 * (float(b.get("end") or 0) - float(b.get("start") or 0)) / total)
            cls = b.get("mode") or "motion"
            title = (f'{b.get("op")} / {b.get("action")} [{b.get("start")}–{b.get("end")}s]'
                     f' 模式 {cls} 力角色 {b.get("force")}')
            blocks.append(f'<div class="tl-block {e(cls)}" style="left:{left:.2f}%;width:{width:.2f}%" '
                          f'title="{e(title)}">{e(truncate(b.get("op"), 6))}</div>')
        rows.append(f'<div class="tl-row"><span class="tl-exec">{e(row["executor"])}</span>'
                    f'<div class="tl-track">{"".join(blocks)}</div></div>')
    return f'''<div class="timeline">
  <div class="tl-title">示范时间轴（证据定位用；执行图由条件决定启动与结束，秒数不用于调度）
    <span class="legend"><i class="lg motion"></i>移动 <i class="lg transition"></i>建立/解除
    <i class="lg maintain"></i>保持</span></div>
  <div class="tl-scale">{ticks}</div>
  {"".join(rows)}
</div>'''


def extras_html(data: dict) -> str:
    preds = "".join(
        f'<tr><td><span class="pred">{e(p["id"])}</span></td><td>{e(p["text"])}</td>'
        f'<td>{e(p["verb"])}</td><td>{e(p["agent"])}</td><td>{e(p["n_roles"])}</td></tr>'
        for p in data["predicates"])
    revs = "".join(
        f'<div class="rev"><span class="tag">{e(r.get("kind"))}</span>'
        f'<b>{e(r.get("target"))}</b>：{e(r.get("before"))} → {e(r.get("after"))}'
        f'<div class="sub-meta">原因：{e(r.get("why"))}。{e(r.get("note"))}</div></div>'
        for r in data["revisions"])
    gaps = "".join(
        f'<div class="rev"><span class="tag warn">候选缺口</span><b>{e(g.get("node_name"))}</b>：'
        f'{e(g.get("missing"))}<div class="sub-meta">证据：{e(g.get("evidence"))}；'
        f'处理建议：{e(g.get("candidate"))}（状态：{e(g.get("status"))}，不写成事实）</div></div>'
        for g in data["gaps"])
    rev = "".join(
        f'<div class="rev"><span class="tag">{e(r.get("kind"))}</span>{e(r.get("text"))}</div>'
        for r in data["validation"]["needs_review"])
    tpl_rows = []
    for t in data.get("template_check") or []:
        cid = f'（{e(t["node_cid"])}）' if t.get("node_cid") else ""
        note = "" if t.get("node") else (t.get("note") or "")
        tpl_rows.append(
            f'<tr><td><b>{e(t["no"])}</b></td><td>{e(t["name"])}</td>'
            f'<td class="muted">{e(t["desc"])}</td>'
            f'<td>{e(t["node"]) or "—"}{cid}</td>'
            f'<td class="muted">{e(note) if note else ""}</td></tr>')
    return f'''<details class="fold-sec" open>
  <summary>九节点模板核对（人工对照，不是数据字段）</summary>
  <div class="sub-meta">“对应”一列本案例实际输出的节点；空白或带说明的就是视频里没有直接证据的项。
  模板要求来自 new_task/新的任务.md 的九个节点，逐条可核。</div>
  <table class="ptable"><thead><tr><th>#</th><th>模板节点</th><th>模板要求（摘要）</th>
  <th>本案例对应</th><th>说明</th></tr></thead><tbody>{"".join(tpl_rows)}</tbody></table>
</details>
<details class="fold-sec" open>
  <summary>推理修正（落回图的修改）</summary>
  {revs or '<div class="empty">无</div>'}{gaps}
</details>
<details class="fold-sec">
  <summary>谓词表（{len(data["predicates"])} 条）——执行侧需要注册的检测器清单</summary>
  <table class="ptable"><thead><tr><th>谓词</th><th>原文</th><th>动词</th><th>主体</th><th>引用</th></tr></thead>
  <tbody>{preds}</tbody></table>
</details>
<details class="fold-sec">
  <summary>校验与待复核</summary>
  <div class="rev"><b>{e(data["validation"]["summary"])}</b>（确定性校验，passed={e(data["validation"]["passed"])}）</div>
  {rev or '<div class="empty">无待复核项</div>'}
</details>'''


# ---------------------------------------------------------------- 页面模板

CSS = """
:root{--bg:#f4f5f7;--panel:#fff;--line:#d9dee6;--ink:#1f2937;--muted:#6b7280;
--blue:#2563eb;--orange:#d97706;--teal:#0d9488;--green:#15803d;--slate:#64748b;}
*{box-sizing:border-box}
body{margin:0;font:14px/1.55 system-ui,-apple-system,"Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif;
color:var(--ink);background:var(--bg)}
header.top{padding:16px 22px 12px;background:var(--panel);border-bottom:1px solid var(--line)}
h1{font-size:19px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.chip{border:1px solid var(--line);border-radius:999px;padding:2px 10px;font-size:12px;background:#fff}
.chip.ok{border-color:#86efac;background:#f0fdf4;color:#166534}
.chip.warn{border-color:#fcd34d;background:#fffbeb;color:#92400e}
#app{display:flex;align-items:stretch}
#graphPane{flex:1;min-width:0;overflow:auto;padding:16px 18px 30px}
#detailPane{width:440px;flex:0 0 440px;background:var(--panel);border-left:1px solid var(--line);
overflow:auto;position:sticky;top:0;max-height:100vh;padding:0 0 40px}
#figure{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:auto;
max-height:70vh}
#figure svg{display:block}
.figcap{color:var(--muted);font-size:11.5px;margin-top:8px;line-height:1.7}
g.op-node{cursor:pointer}
g.op-node:focus{outline:none}
g.op-node>rect:first-of-type{transition:stroke .12s,stroke-width .12s}
g.op-node:hover>rect:first-of-type{stroke:#94a3b8}
g.op-node.sel>rect:first-of-type{stroke:var(--blue);stroke-width:2.6}
g.op-edge{cursor:pointer}
g.op-edge.dim{opacity:.16}
/* 门控状态机图（主图）的交互：圆 = 操作、菱形 = 门控、线 = 放行 */
g.gs-node{cursor:pointer}
g.gs-node:focus{outline:none}
g.gs-node:hover>circle{stroke:#94a3b8}
g.gs-node.sel>circle{stroke:var(--blue);stroke-width:4.6}
g.gs-gate{cursor:pointer}
g.gs-gate:focus{outline:none}
g.gs-gate:hover>path{stroke:#0f766e;stroke-width:4.4}
g.gs-gate.sel>path{stroke:var(--blue);stroke-width:4.6}
g.gs-line{cursor:pointer}
g.gs-line.dim{opacity:.14}
.cid{font-size:11px;color:var(--muted);margin-left:auto}
.badge{font-size:11px;border:1px solid var(--line);border-radius:6px;padding:0 6px;background:#f8fafc;color:#475569}
.badge.mode{border-color:#fcd34d;background:#fffbeb;color:#92400e;font-weight:600}
.badge.tpl-full{color:#6d28d9;border-color:#ddd6fe;background:#f5f3ff}
.inf-note{color:#92400e;background:#fffbeb;border:1px dashed #fcd34d;border-radius:6px;
padding:3px 7px;margin-top:4px;font-size:11.5px}
.timeline{margin-top:26px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px 18px}
.tl-title{font-size:13px;font-weight:600;margin-bottom:10px;color:#334155}
.legend{margin-left:10px;font-weight:400;font-size:11.5px;color:var(--muted)}
.lg{display:inline-block;width:9px;height:9px;border-radius:2px;margin:0 3px 0 8px}
.lg.motion{background:var(--blue)}.lg.transition{background:var(--green)}.lg.maintain{background:var(--orange)}
.tl-scale{position:relative;height:16px;margin:0 0 4px 74px}
.tl-tick{position:absolute;transform:translateX(-50%);font-size:10px;color:var(--muted)}
.tl-row{display:flex;align-items:center;gap:8px;margin-top:6px}
.tl-exec{width:66px;flex:0 0 66px;font-size:12px;color:#334155;font-weight:500;text-align:right}
.tl-track{position:relative;height:22px;flex:1;background:#f1f5f9;border-radius:6px}
.tl-block{position:absolute;top:2px;bottom:2px;border-radius:5px;color:#fff;font-size:10.5px;
line-height:18px;padding:0 5px;overflow:hidden;white-space:nowrap}
.tl-block.motion{background:#60a5fa}
.tl-block.transition{background:#34d399}
.tl-block.maintain{background:#fbbf24}
.detail{padding:16px 18px 0}
.detail[hidden]{display:none}
.dhead{display:flex;align-items:flex-start;gap:8px}
.dtitle{flex:1}
.dname{font-size:16px;font-weight:700}
.dintent{margin-top:10px;font-size:13px;color:#334155;background:#f8fafc;border:1px solid var(--line);
border-radius:8px;padding:9px 10px}
.tlab{color:var(--muted);font-size:11.5px;margin-right:6px}
.purpose{margin-top:4px;color:var(--muted);font-size:12px}
.dsec{border-top:1px solid var(--line);margin-top:14px;padding-top:10px}
.dsec-t{font-size:13px;font-weight:600;color:#334155;margin-bottom:8px}
.dsec-t .src{font-weight:400;font-size:11px;color:var(--muted);margin-left:6px}
.trow{display:flex;gap:8px;padding:5px 0;border-top:1px dashed #eef2f7}
.trow:first-of-type{border-top:none}
.tkey{width:118px;flex:0 0 118px;color:#475569;font-size:12px;font-weight:600}
.tval{flex:1;min-width:0;font-size:12.5px}
.pv{padding:1px 0}
.pred{display:inline-block;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;border-radius:5px;padding:0 5px}
.ptxt{color:#64748b;font-size:11.5px;margin-left:6px}
.plain{color:#334155}
.tag{display:inline-block;font-size:10.5px;background:#f1f5f9;border:1px solid var(--line);
border-radius:5px;padding:0 5px;color:#475569;margin-left:4px}
.tag.warn{background:#fffbeb;border-color:#fcd34d;color:#92400e}
.steps{color:var(--muted);font-size:11.5px;margin-left:2px}
.empty{color:var(--muted);font-size:12px}
.muted{color:var(--muted)}
.ok{color:#166534}.warn{color:#92400e}
.sub{border:1px solid var(--line);border-radius:8px;padding:8px 9px;margin-bottom:8px;background:#fcfdff}
.sub-h{display:flex;align-items:center;gap:6px;font-size:12.5px}
.sub-n{font-weight:600}
.sub-e{color:var(--muted)}
.sub-t{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums}
.kind{font-size:10.5px;border-radius:5px;padding:0 5px;border:1px solid}
.k-est{background:#ecfdf5;border-color:#a7f3d0;color:#065f46}
.k-rel{background:#fef2f2;border-color:#fecaca;color:#991b1b}
.k-mov{background:#eff6ff;border-color:#bfdbfe;color:#1e40af}
.k-hold{background:#fffbeb;border-color:#fcd34d;color:#92400e}
.sub-meta{color:#475569;font-size:11.5px;margin-top:3px}
.sub-inf{color:#92400e;font-size:11.5px;margin-top:4px;background:#fffbeb;border:1px dashed #fcd34d;
border-radius:6px;padding:4px 6px}
.rel-title{font-size:12px;font-weight:600;color:#334155;margin:10px 0 6px}
.relc{font-size:11.5px;color:#334155;border-left:3px solid var(--line);padding:3px 0 3px 8px;margin-bottom:5px}
.relc.hold_covers{border-left-color:var(--orange)}
.relc.sequence{border-left-color:#94a3b8}
.relc.parallel{border-left-color:var(--teal)}
.chk{font-size:11.5px;background:#f8fafc;border:1px solid var(--line);border-radius:6px;
padding:5px 7px;margin-bottom:5px}
.chk .at{color:var(--muted);font-size:11px}
.kv{display:flex;gap:8px;font-size:12.5px;padding:3px 0}
.kv>span:first-child{width:168px;flex:0 0 168px;color:#475569}
.evatom{font-size:12px;border-left:3px solid #cbd5e1;padding:2px 0 2px 8px;margin:4px 0}
.ev-title{font-size:11.5px;font-weight:600;color:#475569;margin:8px 0 3px}
.fold-sec{margin-top:18px;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.fold-sec summary{cursor:pointer;font-weight:600;font-size:13px;color:#334155}
.rev{font-size:12px;padding:6px 0;border-top:1px dashed #eef2f7}
.rev:first-of-type{border-top:none}
.ptable{width:100%;border-collapse:collapse;margin-top:10px;font-size:12px}
.ptable th,.ptable td{border-bottom:1px solid #eef2f7;padding:4px 6px;text-align:left;vertical-align:top}
.ptable th{color:var(--muted);font-weight:600;font-size:11.5px}
#detailEmpty{padding:22px 18px;color:var(--muted);font-size:13px}
footer.pagefoot{margin:26px 18px 0;color:var(--muted);font-size:11.5px;line-height:1.7}
"""

JS = """(function(){
  var NODE_SEL = 'g.op-node, g.gs-node';

  function hideDetails(){
    var ds = document.querySelectorAll('.detail');
    for (var j=0;j<ds.length;j++) ds[j].hidden = true;
  }

  function showDetail(attr, value){
    hideDetails();
    var ds = document.querySelectorAll('.detail');
    for (var j=0;j<ds.length;j++) ds[j].hidden = ds[j].dataset[attr] !== value;
    document.getElementById('detailEmpty').hidden = true;
    document.getElementById('detailPane').scrollTop = 0;
  }

  function isGateId(id){
    var gs = WB.gates || [];
    for (var i=0;i<gs.length;i++) if (gs[i].id === id) return true;
    return false;
  }

  function clearSel(){
    var ns = document.querySelectorAll(NODE_SEL + ', g.gs-gate');
    for (var i=0;i<ns.length;i++) ns[i].classList.remove('sel');
  }

  function dimLines(keepId){
    var ls = document.querySelectorAll('g.op-edge, .gs-line');
    for (var i=0;i<ls.length;i++){
      var keep = !keepId
        || ls[i].getAttribute('data-from') === keepId
        || ls[i].getAttribute('data-to') === keepId;
      ls[i].classList.toggle('dim', !keep);
    }
  }

  function selectNode(id){
    clearSel();
    var ns = document.querySelectorAll(NODE_SEL);
    for (var i=0;i<ns.length;i++) ns[i].classList.toggle('sel', ns[i].getAttribute('data-op') === id);
    dimLines(id);
    if (id) { showDetail('id', id); }
    else { hideDetails(); document.getElementById('detailEmpty').hidden = false; }
  }

  function selectGate(gid){
    clearSel();
    var gs = document.querySelectorAll('g.gs-gate');
    for (var i=0;i<gs.length;i++) gs[i].classList.toggle('sel', gs[i].getAttribute('data-gate') === gid);
    var ls = document.querySelectorAll('.gs-line');
    for (var j=0;j<ls.length;j++){
      var f = ls[j].getAttribute('data-from'), t = ls[j].getAttribute('data-to');
      ls[j].classList.toggle('dim', !(f === gid || t === gid));
    }
    showDetail('gate', gid);
  }

  function edgeIdx(from, to, relation){
    for (var i=0;i<WB.edges.length;i++){
      if (WB.edges[i].from === from && WB.edges[i].to === to && (!relation || WB.edges[i].relation === relation)) return WB.edges[i].idx;
    }
    return -1;
  }

  function selectEdge(from, to, relation){
    var idx = edgeIdx(from, to, relation);
    if (idx < 0) return false;
    clearSel();
    showDetail('edge', String(idx));
    var ls = document.querySelectorAll('g.op-edge, .gs-line');
    for (var k=0;k<ls.length;k++){
      var same = ls[k].getAttribute('data-from') === from && ls[k].getAttribute('data-to') === to;
      ls[k].classList.toggle('dim', !same);
    }
    return true;
  }

  document.querySelectorAll(NODE_SEL).forEach(function(g){
    var id = g.getAttribute('data-op');
    g.setAttribute('tabindex', '0');
    g.addEventListener('click', function(){ selectNode(id); });
    g.addEventListener('keydown', function(ev){
      if (ev.key === 'Enter' || ev.key === ' '){ ev.preventDefault(); selectNode(id); }
    });
  });
  document.querySelectorAll('g.gs-gate').forEach(function(g){
    var gid = g.getAttribute('data-gate');
    g.setAttribute('tabindex', '0');
    g.addEventListener('click', function(){ selectGate(gid); });
    g.addEventListener('keydown', function(ev){
      if (ev.key === 'Enter' || ev.key === ' '){ ev.preventDefault(); selectGate(gid); }
    });
  });
  document.querySelectorAll('g.op-edge, .gs-line').forEach(function(g){
    var from = g.getAttribute('data-from'), to = g.getAttribute('data-to');
    if (!from || !to) return;
    g.addEventListener('click', function(){
      if (isGateId(from)) return selectGate(from);
      if (isGateId(to)) return selectGate(to);
      selectEdge(from, to, g.classList.contains("hold") ? "maintain_until" : null);
    });
  });
  document.addEventListener('keydown', function(ev){ if (ev.key === 'Escape') selectNode(null); });
})();"""


def render(data: dict) -> str:
    if data.get("learning_layer") == "semantic":
        return render_semantic(data)
    # main_svg 已直接内联进页面主体，不再重复塞进 JSON（否则 <svg> 标签计数会被当成结构标签）
    payload = json.dumps({k: v for k, v in data.items() if k != "main_svg"},
                         ensure_ascii=False).replace("</", "<\\/")
    chips = [
        ("", f'{data["stats"]["operations"]} 个操作节点'),
        ("", f'门控 {data["stats"].get("gates", 0)} 个'
             f'（T {data["stats"].get("gates_T", 0)} · '
             f'U {data["stats"].get("gates_U", 0)} · '
             f'F {data["stats"].get("gates_F", 0)}）'),
        ("", f'{data["stats"]["subs"]} 个子操作'),
        ("", f'{data["stats"]["checkpoints"]} 个执行层检查点'),
        ("", f'{data["stats"]["holds"]} 个保持节点（MAINTAIN）'),
        ("", f'{data["stats"]["inferred_subs"]} 个推理补全子操作'),
        ("", f'{data["stats"]["edges"]} 条操作关系'),
    ]
    val = data["validation"]
    state_cls = "ok" if val.get("passed") else "warn"
    chips.append((state_cls, f'校验：{val.get("summary") or "—"}'))
    sv = data.get("side_verify") or {}
    if sv.get("summary"):
        chips.append(("warn", f'执行侧结构验证：{sv["summary"]}'))
    chip_html = "".join(f'<span class="chip {c}">{e(t)}</span>' for c, t in chips)
    verify_line = (
        f'执行侧结构验证输出：output/{data["case"]}/{sv["file"]}'
        f'（用 tools/verify_contract.py {data["case"]} 可复跑；语义图与策略已按该工具装到执行侧目录）。'
        if sv else
        f'执行侧结构验证：用 tools/verify_contract.py {data["case"]} 运行（本目录暂无输出文件）。')
    main_block = f'''<div id="figure">{data["main_svg"]}</div>
    <div class="figcap">主图 = 操作图本身（门控状态机图，与 <code>output/{e(data["case"])}/operations.svg</code> 同一张图）：
      圆 = 操作（只写动作；保持类操作为暖色框）、菱形 = 门控，同一列 = 时间上重叠的一组操作（并行泳道上下排），列间就是一次换挡。<br>
      门控放行（T）时连线画<b>实线</b>，未放行（U）画<b>虚线</b>；虚线也用于持续约束（保持动作覆盖后续操作，不是放行）。
      连线只用黑色，线型只有实线与虚线两种。
      点击节点看七元组、子操作展开与执行层对接；点击菱形看这一跳的条件、状态与依据；点击连线看关系类型（Esc 取消选中）。</div>'''
    details = "".join(detail_html(n, data["predicate_by_text"], data["atomic"])
                      for n in data["nodes"])
    gate_details = "".join(gate_detail_html(g) for g in data.get("gates") or [])
    edge_details = "".join(edge_detail_html(x) for x in data["edges"])
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(data["case"])} · 操作图工作台</title>
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <h1>{e(data["case"])} · 操作图工作台（门控状态机 → 七元组 → 执行层能力）</h1>
  <div class="sub">任务意图：{e(data["task_intent"])}　|　数据源：output/{e(data["case"])}/result.json（生成时写入，点击只展开显示）</div>
  <div class="chips">{chip_html}</div>
</header>
<div id="app">
  <div id="graphPane">
    {main_block}
    {timeline_html(data)}
    {extras_html(data)}
    <footer class="pagefoot">
      读法：主图是<b>门控状态机</b>（圆 = 操作、菱形 = 门控、同一列 = 时间上重叠的一组操作）——
      门控放行（T）时连线画实线，未放行（U）与持续约束都画虚线（全图黑色，只有实线／虚线两种线型），
      菱形的放行条件取自七元组里的 PRE / POST / CONST，悬停或点击可看依据。<br>
      点击节点看七元组、子操作展开与执行层对接；点击菱形看条件与证据；点击连线看关系类型。
      七元组来源：task_nodes.tuple；hold_1 / node_4_release 为修订新增节点，其七元组由契约与展开字段派生并标注。
      所有内容在生成时写入页面（不是点击后才生成）。<br>
      {verify_line}
    </footer>
  </div>
  <div id="detailPane">
    <div id="detailEmpty">点击主图里的操作节点看它的七元组、子操作展开与执行层对接；
      点击菱形门控看这一跳的条件、状态（T/F/U）与依据；点击连线看关系类型（Esc 取消选中）。</div>
    {details}
    {gate_details}
    {edge_details}
  </div>
</div>
<script>
const WB = {payload};
{JS}
</script>
</body>
</html>
'''



def preparation_html(node: dict) -> str:
    rows = []
    names = {"satisfied": "前提有状态证据", "inferred_preparation": "必要准备：推理补全，待核实",
             "unknown": "状态未知，条件式准备", "conflict": "占用或重抓疑点，待复核"}
    for r in node.get("preparation_requirements") or []:
        rows.append(f'<div class="rev"><b>{e(r["required_state"])}</b>'
                    f'<div>{e(names[r["status"]])}</div><div>{e(r["note"])}</div>')
        for evidence in r.get("state_evidence") or []:
            rows.append(f'<div class="sub-meta">依据：#{e(evidence["atomic_ref"])} '
                        f'{e(evidence["field"])}：{e(evidence["text"])}</div>')
        if r.get("candidate_action"):
            rows.append(f'<div class="sub-inf">候选：{e(r["executor"])}张开 → 抓握。'
                        '本动作未被观察；不指定视频时间；具体开度由执行侧绑定。</div>')
        rows.append('</div>')
    if not rows:
        return ""
    return '<div class="dsec"><div class="dsec-t">抓握准备 · 因果校验</div>' + "".join(rows) + '</div>'


def coordination_html(node: dict) -> str:
    rows = []
    for role in node.get("functional_roles") or []:
        rows.append(f'<div class="pv">#{e(role["atomic_ref"])} {e(role["executor"])}：'
                    f'<b>{e(role["function"])}</b> · {e(role.get("atomic_capability"))}</div>')
    for reach in node.get("reach_requirements") or []:
        rows.append(f'<div class="rev"><b>靠近的目的：</b>{e(reach["purpose"])}'
                    f'<div>前提：{e(reach["required_state"])}；{e(reach["status"])}</div>'
                    f'<div class="sub-meta">{e(reach["note"])}</div></div>')
    for grip in node.get("scoped_grip_constraints") or []:
        rows.append(f'<div class="rev"><b>握持生效范围：</b>{e(grip["constraint_text"])}'
                    f'<div>开始：抓握成功（动作 #{e(grip["grasp_ref"])}）</div>'
                    f'<div>终止：释放动作开始前（动作 #{e(grip.get("release_ref") or "待确认")}）</div>'
                    '<div>释放开始即允许手张开，释放完成后确认抓持关系解除。</div>'
                    f'<div class="sub-meta">{e(grip["note"])}</div></div>')
    if not rows:
        return ""
    return '<div class="dsec"><div class="dsec-t">臂手分工与握持约束</div>' + "".join(rows) + '</div>'


def origin_html(node: dict) -> str:
    if node.get("inferred"):
        return '<div class="sub-inf">语义补全目标（未观察到独立动作）：' + e(node.get("inference_reason")) + '</div>'
    if node.get("already_satisfied"):
        return '<div class="purpose">该语义目标已有状态证据满足；不表示观察到了独立的打开动作。</div>'
    return ""


def render_semantic(data: dict) -> str:
    """Keep the original workbench frame and node-click tuple interaction."""
    payload = json.dumps({k: v for k, v in data.items() if k != "main_svg"},
                         ensure_ascii=False).replace("</", r"<\/")
    media_review = data.get("media_review") or {}
    media_html = ""
    if media_review.get("gallery"):
        media_html = (f'<div class="figcap"><a href="{e(media_review["gallery"])}" target="_blank">'
                      '查看关键状态帧</a> · '
                      f'局部复查 {e(media_review["reviewed"])} 次，'
                      f'未完成 {e(media_review["unresolved"])} 项，'
                      f'证据冲突 {e(media_review["conflicts"])} 项。'
                      '关键帧选择不等于动作已被证实。</div>')
    details = []
    for node in data["nodes"]:
        details.append(f'''<section class="detail" data-id="{e(node["id"])}" hidden>
<div class="dhead"><div class="dtitle"><span class="dname">{e(node["name"])}</span>
<span class="cid">{e(node["id"])}</span></div></div>
<div class="dintent"><span class="tlab">操作目的</span>{e(node["intent"])}{origin_html(node)}</div>
<div class="dsec"><div class="dsec-t">七元组 Si = ⟨X, O, C_pre, C_const, E, C_post, R⟩</div>
{tuple_rows(node, data["predicate_by_text"])}</div>
{preparation_html(node)}
{coordination_html(node)}
<div class="dsec"><div class="dsec-t">示范证据</div>{evidence_html(node, data["atomic"])}</div>
</section>''')
    details.extend(gate_detail_html(g) for g in data.get("gates") or [])
    details.extend(edge_detail_html(x) for x in data["edges"])
    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(data["case"])} · 语义操作图工作台</title><style>{CSS}</style></head>
<body><header class="top"><h1>{e(data["case"])} · 语义操作图工作台</h1>
<div class="sub">任务意图：{e(data["task_intent"])} ｜ 点击操作节点展开七元组</div>
<div class="chips"><span class="chip">{len(data["nodes"])} 个语义操作</span>
<span class="chip">校验：{e(data["validation"].get("summary"))}</span></div></header>
{data.get("intent_hierarchy_html", "")}
<div id="app"><div id="graphPane"><div id="figure">{data["main_svg"]}</div>
<div class="figcap">圆为操作、菱形为条件门控，沿用原操作图形式。
图上只显示动作；点击节点在右侧查看七元组，点击菱形查看条件与证据，Esc 取消选择。
条件未知不代表失败，图形不表示机器人已执行。</div>
{media_html}
{timeline_html(data)}
<details class="fold-sec"><summary>校验与待复核</summary>
<div>{e(data["validation"].get("summary"))}</div></details></div>
<div id="detailPane"><div id="detailEmpty">点击主图中的操作节点查看七元组。</div>
{"".join(details)}</div></div><script>const WB = {payload};{JS}</script></body></html>'''


def export(case_dir: Path, out: Path | None = None) -> tuple[Path, dict]:
    """确定性导出工作台页面，返回 (输出路径, payload)。

    pipeline 与 tools/render_case.py 共用这一个入口，保证跑完分析就有 workbench.html。
    """
    data = build(case_dir)
    target = Path(out) if out else case_dir / "workbench.html"
    target.write_text(render(data), encoding="utf-8")
    return target, data
