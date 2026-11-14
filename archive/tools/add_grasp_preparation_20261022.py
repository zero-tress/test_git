"""Integrate state-aware preparation without re-enabling hold priors."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
backup = root / "backups/grasp_preparation_20261022"
def edit(name, old, new):
    p = root / name
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing anchor in {name}: {old[:60]}")
    b = backup / name
    b.parent.mkdir(parents=True, exist_ok=True)
    if not b.exists():
        shutil.copy2(p, b)
    p.write_text(text.replace(old, new), encoding="utf-8")

edit("video2op/pipeline.py", "    from .abstraction import validate_bundle\n    bundle[\"learning_layer\"]", "    from .abstraction import validate_bundle\n    from . import grasp_preparation\n    bundle[\"learning_layer\"]")
edit("video2op/pipeline.py", '    semantic.normalize_tasks(bundle.get("task_nodes") or {})\n', '    semantic.normalize_tasks(bundle.get("task_nodes") or {})\n    grasp_preparation.annotate(bundle)\n')
edit("video2op/pipeline.py", '    bundle["reasoning"] = reasoning.audit(bundle)\n    bundle["predicates"]', '''    bundle["reasoning"] = reasoning.audit(bundle)
    preparation_checks = grasp_preparation.checks(bundle)
    bundle["reasoning"]["checks"].extend(preparation_checks)
    bundle["reasoning"]["stats"]["checks"] += len(preparation_checks)
    bundle["predicates"]''')
edit("video2op/pipeline.py", '    semantic.normalize_observations(ctx)\n', '    semantic.normalize_observations(ctx)\n    from . import grasp_preparation\n    grasp_preparation.annotate(ctx)\n')
edit("video2op/semantic.py", '    "释放": ("松开", "放开", "解除抓持"),', '    "释放": ("松开", "放开", "解除抓持"),\n    "张开": ("预张开", "张开手", "张开手指"),')
edit("video2op/semantic.py", '下游推理也必须使用同一词表、模板和能力缺口，不扩造动作。',
'''臂负责靠近、抬升、带载移动、下降放置与撤回；手负责张开、抓握、释放。
手空着且紧握时，抓握前需张开到可包络目标。张开通常作为抓取节点内部准备，不强制单列任务节点。
若已观察到张开状态，不必补张开动作；若确认闭合且缺少张开环节，只提出 inferred=true 的必要准备。
状态未知时保留条件式准备与待确认，不把默认静息态或继承状态当观测，不假定先前紧握，不编动作时间。
手已持有物体时先报告占用/重抓疑点，不能擅自推断张开丢弃物体。
抓取短链内的空间移动属于臂，不因短链名叫抓取就全算到手上。
下游推理也必须使用同一词表、模板和能力缺口，不扩造动作。''')
edit("video2op/semantic.py", '                         "observed_candidates": t.get("R") or []}', '                         "observed_candidates": t.get("R") or [],\n                         "preparation_requirements": deepcopy(n.get("preparation_requirements") or [])}')
edit("video2op/semantic.py", '"action_catalog": catalog(), "capability_gaps": gaps,', '"action_catalog": catalog(), "capability_gaps": gaps,\n                "grasp_preparation": deepcopy(bundle.get("grasp_preparation") or {}),')
edit("video2op/semantic.py", 'def catalog():\n    return {name:', 'def catalog():\n    out = {name:')
edit("video2op/semantic.py", '            for name, aliases in ALIASES.items()}\n', '''            for name, aliases in ALIASES.items()}
    out["张开"].update(atomic_capabilities=["OperateGripper"], control_mode="MODE_SET_WIDTH",
                       status="atomic_registered", scope="grasp_preparation")
    return out
''')
edit("video2op/semantic.py", '    failed = sum(c["status"] == "fail" for c in checks)', '''    preparation = (bundle.get("grasp_preparation") or {}).get("requirements") or []
    pending = [r for r in preparation if r["status"] != "satisfied"]
    checks.append({"id": "grasp_preparation", "name": "抓握前手张开与证据来源",
                   "status": "warn" if pending else "pass", "detail": pending})
    failed = sum(c["status"] == "fail" for c in checks)
    warned = sum(c["status"] == "warn" for c in checks)''')
edit("video2op/semantic.py", 'f"{len(checks)} 项检查，失败 {failed}"', 'f"{len(checks)} 项检查，提醒 {warned}，失败 {failed}"')
edit("video2op/semantic.py", '"needs_review": graph["x-meta"]["capability_gaps"]}', '"needs_review": graph["x-meta"]["capability_gaps"] + pending}')
# Every text stage sees the annotated prerequisite with its evidence source.
edit("video2op/stages/common.py", '+ " | 维持到 | 来源 | 状态来源 | 操作目的 | 世界前状态 | 世界后状态"]', '+ " | 维持到 | 来源 | 状态来源 | 操作目的 | 世界前状态 | 世界后状态 | 抓握准备校验"]')
edit("video2op/stages/common.py", '        lines.append(" | ".join(row))', '''        preparation = a.get("grasp_preparation") or {}
        row.append((str(preparation.get("status")) + "：" +
                    str(preparation.get("required_state")) + "；" + str(preparation.get("note")))
                   if preparation else "-")
        lines.append(" | ".join(row))''')
edit("video2op/workbench.py", '            "tuple": tup,', '            "tuple": tup,\n            "preparation_requirements": tn.get("preparation_requirements") or [],')
edit("video2op/workbench.py", '{tuple_rows(node, data["predicate_by_text"])}</div>', '{tuple_rows(node, data["predicate_by_text"])}</div>\n{preparation_html(node)}')
edit("video2op/workbench.py", 'def render_semantic(data: dict) -> str:', '''def preparation_html(node: dict) -> str:
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


def render_semantic(data: dict) -> str:''')
edit("video2op/vocab.py", '"左手": ["抓握", "释放", "接触", "支撑"]', '"左手": ["张开（抓握准备）", "抓握", "释放"]')
edit("video2op/vocab.py", '"右手": ["抓握", "释放", "接触", "支撑"]', '"右手": ["张开（抓握准备）", "抓握", "释放"]')
edit("video2op/prompts/s02b_atomic.system.txt", '手的接触、抓握、松开用该侧手记录；持续状态写入约束。', '手的张开准备、抓握、松开用该侧手记录；臂带着手靠近或搬运归臂，持续抓持写入约束。')
print("State-aware grasp preparation integrated; no hold priors enabled.")
