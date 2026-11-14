"""Promote single-actor semantic steps to the primary graph."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
backup = root / "backups/single_actor_20261022"
def edit(name, old, new):
    p = root / name
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing anchor {name}: {old[:60]}")
    b = backup / name
    b.parent.mkdir(parents=True, exist_ok=True)
    if not b.exists():
        shutil.copy2(p, b)
    p.write_text(text.replace(old, new), encoding="utf-8")

p = root / "video2op/pipeline.py"
t = p.read_text(encoding="utf-8")
start = t.index("def build_learning_graph(")
end = t.index("\ndef build_operation_graph(", start)
edit("video2op/pipeline.py", t[start:end], '''def build_learning_graph(bundle: dict) -> None:
    """Single-actor semantic nodes, logical parallel branches, event-scoped grip."""
    from copy import deepcopy
    from . import arm_hand, grasp_preparation, single_actor
    from .abstraction import validate_bundle
    bundle["learning_layer"] = "semantic"
    if bundle.get("single_actor_version") and bundle.get("task_nodes_source"):
        bundle["task_nodes"] = deepcopy(bundle["task_nodes_source"])
    semantic.normalize_observations(bundle)
    validate_bundle(bundle)
    bundle["ignored_parts"] = ignored_parts.purge(bundle)
    semantic.normalize_tasks(bundle.get("task_nodes") or {})
    grasp_preparation.annotate(bundle)
    arm_hand.annotate(bundle)
    bundle["task_nodes_source"] = deepcopy(bundle.get("task_nodes") or {})
    if "source_analysis" not in bundle:
        bundle["source_analysis"] = {key: deepcopy(bundle.get(key) or {})
                                     for key in ("link", "conditions", "rules", "sync")}
    spec = single_actor.build(bundle)
    bundle["task_nodes"] = {"task_nodes": spec["task_nodes"]}
    bundle["single_actor_version"] = "1.0"
    grasp_preparation.annotate(bundle)
    arm_hand.annotate(bundle)
    bundle["link"] = {"links": [{"node_id": n["id"], "atomic_ids": n["atomic_refs"]}
                                 for n in spec["task_nodes"]], "missing_actions": []}
    bundle["rules"] = {"semantic_relations": deepcopy(spec["edges"])}
    bundle["operations"] = single_actor.operations(bundle, spec)
    bundle["reasoning"] = single_actor.audit(bundle)
    extra = grasp_preparation.checks(bundle) + arm_hand.checks(bundle)
    bundle["reasoning"]["checks"].extend(extra)
    bundle["reasoning"]["stats"]["checks"] += len(extra)
    bundle["predicates"] = predicates.build(bundle)
    bundle["gates"] = gates.build(bundle)
    bundle["semantic_graph"] = semantic.build(bundle)
    bundle["operation_abstraction_version"] = "4.0"
    for key in ("program", "contract", "execution_policy", "expansion"):
        bundle.pop(key, None)

''')
# Converged graph terminology. Original observation wording is never rewritten.
edit("video2op/semantic.py", '    "搬运": ("转移", "运送", "搬动", "移动物体", "承载移动"),\n    "放置": ("放下", "安放", "搁下"),\n    "接近": ("接近目标", "靠近", "向前伸出", "伸出", "前伸", "伸向"),',
'    "移动": ("搬运", "放置", "放下", "安放", "搁下", "转移", "运送", "搬动", "移动物体", "承载移动"),\n    "靠近": ("接近", "接近目标", "向前伸出", "伸出", "前伸", "伸向"),')
edit("video2op/semantic.py", '    "张开": ("预张开", "张开手", "张开手指"),\n', '')
edit("video2op/semantic.py", '    "打开": ("开启", "拧开", "打开瓶盖", "打开门"),', '    "打开": ("张开", "预张开", "张开手", "张开手指", "开启", "拧开", "打开瓶盖", "打开门"),')
edit("video2op/semantic.py", '    "移动": (),\n', '')
# Replace the prompt as a cohesive policy; no leftover compound-node instructions.
p = root / "video2op/semantic.py";t = p.read_text()
start=t.index('POLICY = """');end=t.index('\n\n\ndef is_hold',start)
policy='''POLICY = """
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
观察动作只用 transition/motion；移动属于臂，打开/抓握/释放属于手。失败或未知不改写成成功。
"""'''
edit("video2op/semantic.py",t[start:end],policy)
# Functional candidates are semantic descriptions, not selections of whole robot short chains.
p=root/"video2op/semantic.py";t=p.read_text()
start=t.index('        mapping = MAPPINGS.get(n["name"])');end=t.index('        e = t.get("E")',start)
edit("video2op/semantic.py",t[start:end],'''        candidates = [{"id": f"R{i}", "name": str(r.get("name") or n["name"]),
                       "origin": r.get("origin") if r.get("origin") in {"observed", "alternative", "inferred", "system"} else "inferred",
                       "note": "语义实现方式；设备能力与资源由后续映射绑定"}
                      for i, r in enumerate(t.get("R") or [{"name": n["name"], "origin": "inferred"}], 1)]
''')
edit("video2op/semantic.py", '        if mapping:\n            nodes[nid]["template_ref"] = mapping[0]\n', '')
edit("video2op/semantic.py", '"constraint_revisions": deepcopy(n.get("constraint_revisions") or [])}',
'''"constraint_revisions": deepcopy(n.get("constraint_revisions") or []),
                         "source_node_ids": n.get("source_node_ids") or [],
                         "origin": n.get("origin"), "inferred": n.get("inferred", False),
                         "already_satisfied": n.get("already_satisfied", False),
                         "inference_reason": n.get("inference_reason") or ""}''')
edit("video2op/semantic.py", '("sequence", "enables", "parallel", "alternation")', '("sequence", "enables", "parallel", "alternation", "maintain_until")')
edit("video2op/semantic.py", '    incoming = {r["to"]', '''        if rel == "maintain_until":
            relations[-1].update(when=pred(edge.get("condition") or "握持持续成立", "hold"),
                                 until_event="target_starts")
    incoming = {r["to"]''')
edit("video2op/semantic.py", '"action_vocabulary_version": "3.0"', '"action_vocabulary_version": "4.0"')
edit("video2op/semantic.py", 'out["张开"].update', 'out["打开"].update')
edit("video2op/semantic.py", '"reasoner_policy": "只使用登记动作和候选模板；缺少能力时报告缺口，不生成新动作或默认移动"',
'"reasoner_policy": "单主体、受控功能名称；允许靠近和打开并行，合取后抓取；握持持续至释放开始；执行资源另行映射"')
# Actor and topology are now learning validation requirements.
edit("video2op/semantic.py", '    errors.extend(str(g) for g in graph["x-meta"]["capability_gaps"])',
'''    errors.extend(str(g) for g in graph["x-meta"]["capability_gaps"])
    for nid, node in graph["nodes"].items():
        if nid not in ("START", "END"):
            x = node["skill"]["X"]
            if len(x.get("parts") or []) != 1 or x["subject"] != x["parts"][0]:
                errors.append(f"{nid}: 必须只有一个明确执行主体")''')
edit("video2op/semantic.py", '语义层契约与真实候选能力', '单主体语义契约与结构完整性')
# This schema no longer requires robot behavior-tree template binding.
import yaml
p=root/"video2op/schemas/semantic_learning_graph.schema.yaml"
schema=yaml.safe_load(p.read_text())
schema["$defs"]["candidate"]["required"]=["id","name"]
schema["$defs"]["relation"]["properties"]["until_event"]={"type":"string","enum":["target_starts"]}
b=backup/"video2op/schemas/semantic_learning_graph.schema.yaml";b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,b)
p.write_text(yaml.safe_dump(schema,allow_unicode=True,sort_keys=False))
# Use graph topology, not recorded seconds, to form parallel columns.
edit("video2op/gates.py", '    ops = [n for n in op_graph.get("nodes") or [] if isinstance(n, dict)]\n    if not ops:\n        return []',
'''    if op_graph.get("single_actor"):
        return [list(c) for c in op_graph.get("semantic_columns") or []]
    ops = [n for n in op_graph.get("nodes") or [] if isinstance(n, dict)]
    if not ops:
        return []''')
# Center text in both exported SVG and the inline workbench graph.
edit("video2op/render.py", '    gdoc = bundle.get("gates") or {}\n    op_graph = bundle.get("operations") or {}',
'''    if bundle.get("single_actor_version"):
        show_node_details = False
    gdoc = bundle.get("gates") or {}
    op_graph = bundle.get("operations") or {}''')
edit("video2op/render.py", 'f\'<text x="{cx:.1f}" y="{cy + 7:.1f}" font-size="19" font-weight="600" \'',
'f\'<text x="{cx:.1f}" y="{cy:.1f}" dominant-baseline="central" font-size="19" font-weight="600" \'')
# Explicit persistent relation, with no extra "hold" operation node.
anchor='    # ---- 节点 ----\n    for band in bands:'
edit("video2op/render.py",anchor,'''    if bundle.get("single_actor_version"):
        for edge in edges:
            if edge.get("relation") != "maintain_until":
                continue
            f, t = str(edge["from"]), str(edge["to"])
            if f not in pos or t not in pos:
                continue
            ax, ay = pos[f]
            bx, by = pos[t]
            lane_y = max(y for _, y in pos.values()) + GS_NODE_R + 34
            path = (f"M {ax:.1f},{ay + GS_NODE_R:.1f} V {lane_y:.1f} "
                    f"H {bx:.1f} V {by + GS_NODE_R:.1f}")
            draw(f, t, "hold", path_d=path)

'''+anchor)
# Model task extraction should already match the graph's granularity.
edit("video2op/stages/s02c_task.py", '        parts = (n.get("tuple", {}).get("X") or {}).get("parts") or []',
'''        actor = n.get("tuple", {}).get("X") or {}
        parts = actor.get("parts") or []
        if len(parts) != 1 or actor.get("subject") != parts[0]:
            raise ValidationFailure("一个节点只允许一个执行主体，X.subject 与唯一的 X.parts 一致；请拆开臂与手")''')
print("Single-actor semantic pipeline activated.")
