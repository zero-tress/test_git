"""Video learning delivers task skills; execution binding belongs to the next layer."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import yaml

SCHEMA = Path(__file__).parent / "schemas/semantic_learning_graph.schema.yaml"

PEER = Path("/home/wj/codex-workspace/semantic_exec_opgraph202610141638")
# Explicit equivalences only. Observation wording is retained as evidence.
ALIASES = {
    "抓取": ("抓取目标", "捡起", "拾起", "拿起", "抓握", "抓住", "握住", "夹住", "提起", "抬起", "举起", "托起"),
    "移动": ("搬运", "放置", "放下", "安放", "搁下", "转移", "运送", "搬动", "移动物体", "承载移动"),
    "靠近": ("接近", "接近目标", "向前伸出", "伸出", "前伸", "伸向"),
    "撤回": ("收回", "退回", "复位"),
    "释放": ("松开", "放开", "解除抓持"),
    "推": ("推动", "推开"),
    "拉": ("拉动", "拉开"),
    "旋转": ("拧", "转动"),
    "按压": ("按下", "按"),
    "接触": ("触碰", "轻触"),
    "打开": ("张开", "预张开", "张开手", "张开手指", "开启", "拧开", "打开瓶盖", "打开门"),
    "关闭": ("关上", "合上", "旋紧"),
    "清障": ("清除障碍", "挪开"),
    "向目标移动": ("走向", "走到", "行走"),
    "上升": ("起身", "站起"),
    "下降": ("下蹲", "蹲下"),
}

HOLD_WORDS = ("保持", "维持", "持续抓", "持续托", "悬停")
POLICY = """
【单执行主体语义图 v4，优先于旧示例】
每个任务节点只有一个执行主体，X.subject 直接写整体/左臂/右臂/左手/右手，X.parts 只含同一主体。
受控名称：靠近=臂带手到可抓位置；打开=手打开；抓取=手建立稳定握持；移动=臂移动（含抬升、带载与下降）；释放=手解除握持；撤回=臂回到原位或安全位。
整体只用于垂直上升/下降和水平方向移动。左右臂手分别保留，不用机器人系统名。
禁止把靠近、打开、抓取合成一个多主体节点。靠近和打开可并行；二者后置条件同时满足才允许抓取。
语义图的并行是逻辑许可，不要求视频实际同时发生，也不受底层夹爪/臂运动互斥反向限制；底层资源映射另行解决。
握持是抓取成功到释放开始前持续成立的状态，可用 maintain_until 关系；禁止保持动作节点或 maintain 动作类型。
移动时手继续握持；移动结束后直到释放开始仍不能松手。释放完成后臂才撤回。
手已打开但未看到打开动作时，可列出“打开”语义目标并标记已满足的状态来源；不虚构打开过程或视频秒数。
需要推断靠近/打开时明确 inferred=true、条件式适用范围与来源。手持有其他物体时保留占用疑点。
语义节点的 R 表示可选方式，允许尚未绑定设备模板；缺少执行模板不等于语义图不成立，不编控制参数。
通用单主体动作还允许臂执行推、拉、旋转、按压，手执行接触、按压。接触只说明接触关系，不能等同于稳定抓握。手指是否接触被遮挡时保留不确定性。必须有实际证据，目标效果由子任务界定。\n观察动作只用 transition/motion；移动属于臂，打开/抓握/释放属于手。失败或未知不改写成成功。
"""


def is_hold(item: dict) -> bool:
    return str(item.get("mode", "")).lower() == "maintain" or any(
        w in str(item.get("action") or item.get("name") or "") for w in HOLD_WORDS)


def canonical(name: str) -> str:
    name = str(name).strip()
    if any(w in name for w in HOLD_WORDS):
        raise ValueError("保持只能写为 C_const，不能作为动作类型")
    if name in ALIASES:
        return name
    for target, aliases in ALIASES.items():
        if name in aliases:
            return target
    raise ValueError(f"未登记的语义动作：{name}；请使用受控动作词表")


def normalize_tasks(payload: dict) -> dict:
    for n in payload.get("task_nodes") or []:
        original = n["name"]
        n["name"] = canonical(original)
        actor = (n.get("tuple") or {}).get("X") or {}
        if isinstance(actor, dict) and "整体" in (actor.get("parts") or []):
            if n["name"] not in {"上升", "下降", "向目标移动", "移动"}:
                raise ValueError("整体只用于垂直上升/下降与水平移动，不用于臂手操作")
        if original != n["name"]:
            n.setdefault("name_evidence", original)
        n["required_capabilities"] = [n["name"]]
    return payload


def normalize_observations(ctx: dict) -> None:
    """Migrate legacy hold observations to evidence/constraints without inventing events."""
    atomic = ctx.setdefault("atomic", {})
    actions = atomic.get("atomic_actions") or []
    holds = list(atomic.get("state_evidence") or [])
    existing = {a["id"] for a in holds}
    holds += [a for a in actions if is_hold(a) and a["id"] not in existing]
    if holds:
        archive = atomic.setdefault("state_evidence", [])
        known = {a["id"] for a in archive}
        archive.extend(deepcopy(a) for a in holds if a["id"] not in known)
    kept = [a for a in actions if not is_hold(a)]
    ids = {a["id"] for a in kept}
    atomic["atomic_actions"] = kept
    rels = [r for r in (ctx.get("relations") or atomic.get("temporal_relations") or [])
            if r.get("from") in ids and r.get("to") in ids
            and r.get("relation") != "maintain_until"]
    ctx["relations"] = atomic["temporal_relations"] = rels
    for a in kept:
        a["until"] = None
    nodes = (ctx.get("task_nodes") or {}).get("task_nodes") or []
    for n in nodes:
        refs = set(n.get("atomic_refs") or [])
        constraints = n.setdefault("tuple", {}).setdefault("C_const", [])
        for a in holds:
            tr = n.get("time_range") or [0, 0]
            same_object = a.get("object") and a["object"] in (n["tuple"].get("O") or [])
            overlap = float(a.get("start", 0)) < tr[1] and float(a.get("end", 0)) > tr[0]
            if a["id"] in refs or (same_object and overlap):
                text = a.get("action") or "操作期间维持状态"
                if text not in constraints:
                    constraints.append(text)
        n["atomic_refs"] = [r for r in n.get("atomic_refs") or [] if r in ids]
    link = ctx.get("link") or {}
    for item in link.get("links") or []:
        item["atomic_ids"] = [r for r in item.get("atomic_ids") or [] if r in ids]
    link["missing_actions"] = [a for a in link.get("missing_actions") or [] if not is_hold(a)]


def build(bundle: dict) -> dict:
    """Emit a semantic graph with the original project actors, never an execution contract."""
    tasks = (bundle.get("task_nodes") or {}).get("task_nodes") or []
    normalize_tasks({"task_nodes": tasks})
    objects, predicates, evidence, gaps = {}, {}, {}, []
    def obj(text):
        key = "Obj" + hashlib.sha1(text.encode()).hexdigest()[:10]
        objects[key] = {"entity_type": "object", "label": text}
        return key
    def pred(text, kind="semantic"):
        key = "P" + hashlib.sha1(text.encode()).hexdigest()[:12]
        predicates.setdefault(key, {"text": text, "kind": kind, "subject": "待绑定检测器"})
        if kind == "hold":
            predicates[key].update(kind="hold", hold_category="grasp", hold_scope="cross_node")
        return key
    nodes = {}
    idmap = {n["id"]: f"N{i}" for i, n in enumerate(tasks, 1)}
    def boundary(name):
        return {"name": name, "template_ref": "semantic/state_transition", "skill": {
            "X": {"subject": "操作者", "parts": []}, "O": [], "C_pre": [], "C_const": [],
            "E": [], "C_post": [], "R": [{"id": "R1", "name": "本地状态转换",
                "template_ref": "execution/state_transition", "origin": "system"}]}}
    nodes["START"] = boundary("任务开始")
    for n in tasks:
        nid, t = idmap[n["id"]], n.get("tuple") or {}
        candidates = [{"id": f"R{i}", "name": str(r.get("name") or n["name"]),
                       "origin": r.get("origin") if r.get("origin") in {"observed", "alternative", "inferred", "system"} else "inferred",
                       "note": "语义实现方式；设备能力与资源由后续映射绑定"}
                      for i, r in enumerate(t.get("R") or [{"name": n["name"], "origin": "inferred"}], 1)]
        e = t.get("E") or {}
        metrics = ([{"name": str(x), "target": "过程判据"} for x in e.get("process", [])] +
                   [{"name": str(x), "target": "完成判据"} for x in e.get("completion", [])] +
                   [{"name": str(x), "target": "失败信号"} for x in e.get("failure_signals", [])]) if isinstance(e, dict) else [{"name": str(x)} for x in e]
        metrics = [dict(items) for items in dict.fromkeys(tuple(sorted(m.items())) for m in metrics)]
        skill = {"X": deepcopy(t.get("X") or {"subject": "操作者", "parts": []}), "O": [obj(str(x)) for x in t.get("O") or []],
                 "C_pre": list(dict.fromkeys(pred(x, "start_gate") for x in t.get("C_pre") or [])),
                 "C_const": list(dict.fromkeys(pred(x) for x in t.get("C_const") or [])), "E": metrics,
                 "C_post": list(dict.fromkeys(pred(x, "post") for x in t.get("C_post") or [])), "R": candidates}
        nodes[nid] = {"name": n["name"], "intent": n.get("intent_role") or "完成任务效果",
                      "skill": skill, "evidence_refs": [nid]}
        evidence[nid] = {"source_node": n["id"], "atomic_refs": n.get("atomic_refs") or [],
                         "demonstration_executor": (t.get("X") or {}).get("parts") or [],
                         "time_range": n.get("time_range"), "original_name": n.get("name_evidence", n["name"]),
                         "observed_candidates": t.get("R") or [],
                         "preparation_requirements": deepcopy(n.get("preparation_requirements") or []),
                         "functional_roles": deepcopy(n.get("functional_roles") or []),
                         "reach_requirements": deepcopy(n.get("reach_requirements") or []),
                         "scoped_grip_constraints": deepcopy(n.get("scoped_grip_constraints") or []),
                         "constraint_revisions": deepcopy(n.get("constraint_revisions") or []),
                         "learning_annotations": deepcopy(n.get("learning_annotations") or []),
                         "source_node_ids": n.get("source_node_ids") or [],
                         "source_skill_tuples": [{"node_id": s["id"], "tuple": deepcopy(s.get("tuple") or {})}
                            for s in (bundle.get("task_nodes_source") or {}).get("task_nodes") or []
                            if s["id"] in (n.get("source_node_ids") or [])],
                         "origin": n.get("origin"), "inferred": n.get("inferred", False),
                         "already_satisfied": n.get("already_satisfied", False),
                         "inference_reason": n.get("inference_reason") or "",
                         "condition_evidence": deepcopy(n.get("condition_evidence") or [])}
    nodes["END"] = boundary("任务结束")
    # Reuse audited semantic edges; never promote mere chronology to execution dependency.
    relations = []
    for edge in (bundle.get("operations") or {}).get("edges") or []:
        if edge["from"] not in idmap or edge["to"] not in idmap:
            continue
        rel = edge.get("relation")
        if rel not in ("sequence", "enables", "parallel", "alternation", "maintain_until"):
            continue
        relations.append({"from": idmap[edge["from"]], "to": idmap[edge["to"]],
            "relation": "sequence" if rel == "enables" else rel,
            "basis": edge["basis"] if edge.get("basis") in ("required_dependency", "inferred", "semantic_independence") else "observed_order", "note": edge.get("note") or ""})
        if rel == "maintain_until":
            relations[-1].update(when=pred(edge.get("condition") or "握持持续成立", "hold"),
                                 until_event="target_starts")
    incoming = {r["to"] for r in relations if r["relation"] == "sequence"}
    outgoing = {r["from"] for r in relations if r["relation"] == "sequence"}
    for nid in idmap.values():
        if nid not in incoming:
            relations.append({"from": "START", "to": nid, "relation": "sequence", "basis": "required_dependency"})
        if nid not in outgoing:
            relations.append({"from": nid, "to": "END", "relation": "sequence", "basis": "required_dependency"})
    if not tasks:
        relations.append({"from": "START", "to": "END", "relation": "sequence", "basis": "observed_order"})
        gaps.append({"reason": "没有学到任务节点"})
    if not objects:
        obj("待确认操作对象")
        gaps.append({"reason": "操作对象未确认"})
    if not predicates:
        pred("任务条件待确认")
        gaps.append({"reason": "任务条件未确认"})
    intents = (bundle.get("intents") or {}).get("intents") or []
    return {"schema_version": "1.0", "graph_id": str((bundle.get("meta") or {}).get("name") or "video_learning"),
            "task_intent": (intents[0].get("statement") if intents else None) or "视频示范任务（意图待确认）",
            "layer": "semantic", "source": "teach", "start_node": "START", "end_node": "END",
            "objects": objects, "predicates": predicates, "nodes": nodes, "relations": relations,
            "evidence": evidence, "x-meta": {"action_vocabulary_version": "4.0",
                "action_catalog": catalog(), "capability_gaps": gaps,
                "final_to_export": dict(idmap),
                "learning_alignment": deepcopy(bundle.get("learning_alignment") or {}),
                "intent_hypotheses": deepcopy((bundle.get("intents") or {}).get("intents") or []),
                "intent_alignment": deepcopy(bundle.get("intent_alignment") or {}),
                "temporal_knowledge": deepcopy(bundle.get("temporal_knowledge") or {}),
                "semantic_scope": deepcopy(bundle.get("semantic_scope") or {}),
                "grasp_preparation": deepcopy(bundle.get("grasp_preparation") or {}),
                "arm_hand_coordination": deepcopy(bundle.get("arm_hand_coordination") or {}),
                "reasoner_policy": "单主体、受控功能名称；允许靠近和打开并行，合取后抓取；握持持续至释放开始；执行资源另行映射",
                "evidence_note": "C_post 是预期效果；是否观测成功参见 result.json 的 reasoning 和 atomic，不能由谓词名推断成功"}}


def catalog():
    roles = {
        "靠近": (["左臂", "右臂"], ["move_chain_client"], "臂带手到目标可抓取位置"),
        "打开": (["左手", "右手"], ["OperateGripper"], "手打开到可抓取状态"),
        "抓取": (["左手", "右手"], ["OperateGripper"], "手建立稳定握持"),
        "移动": (["左臂", "右臂", "整体"], ["move_chain_client"], "臂移动或带载移动；整体只表示平移"),
        "释放": (["左手", "右手"], ["OperateGripper"], "手解除握持"),
        "撤回": (["左臂", "右臂"], ["move_chain_client"], "臂返回原位或安全位置"),
        "推": (["左臂", "右臂"], [], "通过推接触使目标移动；实现待绑定"),
        "拉": (["左臂", "右臂"], [], "通过牵引使目标移动；实现待绑定"),
        "旋转": (["左臂", "右臂"], [], "使目标发生旋转；实现待绑定"),
        "按压": (["左臂", "右臂", "左手", "右手"], [], "通过接触使目标达到按下状态；实现待绑定"),
        "接触": (["左手", "右手"], [], "手与目标建立接触；稳定握持需独立证据"),
        "向目标移动": (["整体"], [], "整体水平移动"),
        "上升": (["整体"], [], "整体垂直上升"),
        "下降": (["整体"], [], "整体垂直下降"),
    }
    out = {name: {"aliases": list(ALIASES.get(name, ())), "allowed_subjects": subjects,
                  "meaning": meaning, "atomic_capabilities": capabilities,
                  "semantic_status": "registered", "binding_status": "pending",
                  "note": "语义图独立成立；能力列表供后续映射参考，不决定本层并行关系"}
           for name, (subjects, capabilities, meaning) in roles.items()}
    arm_motion_aliases = ("提起", "抬起", "举起", "托起")
    out["抓取"]["aliases"] = [a for a in out["抓取"]["aliases"] if a not in arm_motion_aliases]
    out["移动"]["aliases"] = list(dict.fromkeys(out["移动"]["aliases"] + list(arm_motion_aliases)))
    for name, mode in (("打开", "MODE_SET_WIDTH"), ("抓取", "MODE_GRASP"), ("释放", "MODE_RELEASE")):
        out[name]["control_mode"] = mode
    return out


def export(bundle: dict, out: Path) -> None:
    graph = bundle["semantic_graph"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "semantic_graph.yaml").write_text(yaml.safe_dump(graph, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out / "action_catalog.json").write_text(json.dumps(catalog(), ensure_ascii=False, indent=2), encoding="utf-8")
    from .semantic_interface import export as export_interface
    export_interface(bundle, out)


def render(bundle: dict, out: Path) -> None:
    """Original operation circles/gate diamonds; tuple details open on click."""
    from . import render as original_render
    from . import workbench
    out.mkdir(parents=True, exist_ok=True)
    original_render.render_operations(bundle, out)
    data = workbench.build(out, bundle=bundle)
    page = workbench.render(data)
    for name in ("workbench.html", "report.html"):
        (out / name).write_text(page, encoding="utf-8")


def validate(bundle: dict) -> dict:
    from .stages import s06_validate as v
    graph = bundle["semantic_graph"]
    checks = [v._check_param_discipline(bundle), v._check_time_sanity(
        (bundle.get("atomic") or {}).get("atomic_actions") or [], float((bundle.get("meta") or {}).get("duration") or 0)),
        v._check_references(bundle), v._check_ignored_parts(bundle)]
    from .temporal_learning import validate_graph
    errors = validate_graph(graph)
    try:
        import jsonschema
        schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
        errors.extend(e.message for e in jsonschema.Draft7Validator(schema).iter_errors(graph))
    except (ImportError, OSError) as exc:
        errors.append(f"无法验证下游语义契约：{exc}")
    errors.extend(str(g) for g in graph["x-meta"]["capability_gaps"])
    for nid, node in graph["nodes"].items():
        if nid not in ("START", "END"):
            x = node["skill"]["X"]
            allowed = ({"打开", "抓取", "释放", "接触", "按压"} if x["subject"].endswith("手") else
                       {"靠近", "移动", "撤回", "推", "拉", "旋转", "按压"} if x["subject"].endswith("臂") else
                       {"上升", "下降", "向目标移动", "移动"})
            if node["name"] not in allowed:
                errors.append(f"{nid}: 主体 {x['subject']} 不支持 {node['name']}")
            if len(x.get("parts") or []) != 1 or x["subject"] != x["parts"][0]:
                errors.append(f"{nid}: 必须只有一个明确执行主体")
    if any(is_hold(a) for a in (bundle.get("atomic") or {}).get("atomic_actions") or []):
        errors.append("动作表仍有保持类型")
    checks.append({"id": "semantic_schema", "name": "单主体语义契约与结构完整性", "status": "fail" if errors else "pass", "detail": errors})
    preparation = (bundle.get("grasp_preparation") or {}).get("requirements") or []
    pending = [r for r in preparation if r["status"] != "satisfied"]
    checks.append({"id": "grasp_preparation", "name": "抓握前手张开与证据来源",
                   "status": "warn" if pending else "pass", "detail": pending})
    roles = bundle.get("arm_hand_coordination") or {}
    role_issues = list(roles.get("function_issues") or [])
    pending_reach = [r for r in roles.get("reach_requirements") or [] if r["status"] != "satisfied"]
    grip_issues = [g for g in roles.get("grip_intervals") or [] if g["violation_refs"] or g["release_ref"] is None]
    checks.append({"id": "arm_hand_coordination", "name": "臂手功能与抓持生效边界",
                   "status": "warn" if role_issues or pending_reach or grip_issues else "pass",
                   "detail": role_issues + pending_reach + grip_issues})
    pending += role_issues + pending_reach + grip_issues
    temporal_issues = (bundle.get("temporal_knowledge") or {}).get("issues") or []
    unmapped = [r for r in (bundle.get("learning_alignment") or {}).get("records") or [] if r["scope"] in {"unmapped", "uninstantiated_hypothesis"}]
    checks.append({"id": "learning_scope", "name": "学习结果映射与时序语义复核",
                   "status": "warn" if temporal_issues or unmapped else "pass",
                   "detail": temporal_issues + unmapped})
    pending += temporal_issues + unmapped
    quality = (bundle.get("meta") or {}).get("media_quality") or {}
    media_pending = [quality] if quality and not quality.get("coverage_verified") else []
    checks.append({"id": "media_coverage", "name": "源视频解码与证据覆盖",
                   "status": "warn" if media_pending else "pass", "detail": media_pending})
    pending += media_pending
    from .semantic_checks import causal_consistency, pre_post_consistency, temporal_consistency
    checks.extend([causal_consistency(bundle), pre_post_consistency(bundle), temporal_consistency(bundle)])
    pending += [d for c in checks[-3:] if c["status"] == "warn" for d in c["detail"]]
    failed = sum(c["status"] == "fail" for c in checks)
    warned = sum(c["status"] == "warn" for c in checks)
    effect_items = [e for n in (bundle.get("operations") or {}).get("nodes", []) for e in n.get("effect_evidence", [])]
    operation_by_id = {n["id"]: n for n in (bundle.get("operations") or {}).get("nodes", [])}
    missing_effects = []
    for nid, node in graph["nodes"].items():
        if nid in {"START", "END"}:
            continue
        source = graph.get("evidence", {}).get(nid, {}).get("source_node")
        op = operation_by_id.get(source, {})
        for pid in node["skill"]["C_post"]:
            condition = graph["predicates"][pid]["text"]
            if not any(e.get("condition") == condition and e.get("verification_status") == "verified"
                       for e in op.get("effect_evidence", [])):
                missing_effects.append({"node": nid, "condition": condition})
    success_verified = (failed == 0 and bool(effect_items) and not missing_effects
                        and all(e.get("verification_status") == "verified" for e in effect_items)
                        and bool(bundle.get("effect_review_records")))
    return {"passed": failed == 0, "summary": f"{len(checks)} 项检查，提醒 {warned}，失败 {failed}", "checks": checks,
            "needs_review": graph["x-meta"]["capability_gaps"] + pending,
            "semantic_success_verified": success_verified,
            "verification_basis": {"unverified_effects": len([e for e in effect_items if e.get("verification_status") != "verified"]),
                                   "missing_reviewed_postconditions": missing_effects,
                                   "policy": "All node effects require scoped review; structure alone does not prove success."}}
