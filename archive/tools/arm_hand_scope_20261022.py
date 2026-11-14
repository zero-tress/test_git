"""Apply arm/hand boundaries and remove timestamps from the main graph."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
backup = root / "backups/arm_hand_scope_20261022"
def edit(name, old, new):
    p = root / name
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing anchor {name}: {old[:65]}")
    b = backup / name
    b.parent.mkdir(parents=True, exist_ok=True)
    if not b.exists():
        shutil.copy2(p, b)
    p.write_text(text.replace(old, new), encoding="utf-8")

edit("video2op/pipeline.py", '    from . import grasp_preparation\n    from .abstraction import validate_bundle',
'    from . import arm_hand, grasp_preparation\n    from .abstraction import validate_bundle')
edit("video2op/pipeline.py", '    grasp_preparation.annotate(bundle)\n', '    grasp_preparation.annotate(bundle)\n    arm_hand.annotate(bundle)\n')
edit("video2op/pipeline.py", '    preparation_checks = grasp_preparation.checks(bundle)', '    preparation_checks = grasp_preparation.checks(bundle) + arm_hand.checks(bundle)')
edit("video2op/pipeline.py", '    from . import grasp_preparation\n    grasp_preparation.annotate(ctx)', '    from . import arm_hand, grasp_preparation\n    grasp_preparation.annotate(ctx)\n    arm_hand.annotate(ctx)')
edit("video2op/semantic.py", '抓取短链内的空间移动属于臂，不因短链名叫抓取就全算到手上。',
'''抓取短链内的空间移动属于臂，不因短链名叫抓取就全算到手上。
靠近的目的是把手送到目标的可抓取位置；手当前位置不够到不等于目标超出整个臂工作空间。
抓握成功后，手的稳定抓持约束持续至释放动作开始前：[grasp_succeeded, release_starts)。
抓取准备阶段不要求手已经握住物体；释放开始后不再要求继续抓紧；释放完成才确认解除抓持关系。
复合放置节点包含臂下降和手释放时，握持约束只覆盖内部下降阶段，不覆盖释放过程。
臂移动、手维持既有抓持可以共存；不得在臂运动期间新下发同侧夹爪改变开度或attachment的命令。''')
edit("video2op/semantic.py", '"preparation_requirements": deepcopy(n.get("preparation_requirements") or [])}',
'''"preparation_requirements": deepcopy(n.get("preparation_requirements") or []),
                         "functional_roles": deepcopy(n.get("functional_roles") or []),
                         "reach_requirements": deepcopy(n.get("reach_requirements") or []),
                         "scoped_grip_constraints": deepcopy(n.get("scoped_grip_constraints") or []),
                         "constraint_revisions": deepcopy(n.get("constraint_revisions") or [])}''')
edit("video2op/semantic.py", '"grasp_preparation": deepcopy(bundle.get("grasp_preparation") or {}),',
'"grasp_preparation": deepcopy(bundle.get("grasp_preparation") or {}),\n                "arm_hand_coordination": deepcopy(bundle.get("arm_hand_coordination") or {}),')
edit("video2op/semantic.py", '    failed = sum(c["status"] == "fail" for c in checks)', '''    roles = bundle.get("arm_hand_coordination") or {}
    role_issues = list(roles.get("function_issues") or [])
    pending_reach = [r for r in roles.get("reach_requirements") or [] if r["status"] != "satisfied"]
    grip_issues = [g for g in roles.get("grip_intervals") or [] if g["violation_refs"] or g["release_ref"] is None]
    checks.append({"id": "arm_hand_coordination", "name": "臂手功能与抓持生效边界",
                   "status": "warn" if role_issues or pending_reach or grip_issues else "pass",
                   "detail": role_issues + pending_reach + grip_issues})
    pending += role_issues + pending_reach + grip_issues
    failed = sum(c["status"] == "fail" for c in checks)''')
edit("video2op/stages/s02b_atomic.py", '    for i, a in enumerate(acts):',
'''    from ..arm_hand import function_issues
    issues = function_issues(acts)
    if issues:
        raise ValidationFailure(issues[0]["message"] + "：" + str(issues[0]["action"]))
    for i, a in enumerate(acts):''')
edit("video2op/stages/s02d_link.py", '    from ..semantic import is_hold\n    if any(str(m.get("mode")',
'''    from ..arm_hand import function_issues
    issues = function_issues(payload["missing_actions"])
    if issues:
        raise ValidationFailure(issues[0]["message"])
    from ..semantic import is_hold
    if any(str(m.get("mode")''')
edit("video2op/stages/s02c_task.py", '        require_keys(n["tuple"], ["X",',
'''        if set(parts) and set(parts) <= {"左手", "右手"} and canonical(n["name"]) in {"搬运", "接近", "撤回", "移动"}:
            raise ValidationFailure("空间移动由手臂承担，手负责张开、抓握、释放；不能把搬运全归给手")
        require_keys(n["tuple"], ["X",''')
edit("video2op/stages/common.py", '世界后状态 | 抓握准备校验"]', '世界后状态 | 抓握准备校验 | 臂手功能"]')
edit("video2op/stages/common.py", '        lines.append(" | ".join(row))',
'''        role = a.get("functional_role") or {}
        row.append(str(role.get("function") or "-") + "；" + str(role.get("atomic_capability") or ""))
        lines.append(" | ".join(row))''')
edit("video2op/workbench.py", '            "preparation_requirements": tn.get("preparation_requirements") or [],',
'''            "preparation_requirements": tn.get("preparation_requirements") or [],
            "functional_roles": tn.get("functional_roles") or [],
            "reach_requirements": tn.get("reach_requirements") or [],
            "scoped_grip_constraints": tn.get("scoped_grip_constraints") or [],
            "constraint_revisions": tn.get("constraint_revisions") or [],''')
edit("video2op/workbench.py", '{preparation_html(node)}', '{preparation_html(node)}\n{coordination_html(node)}')
edit("video2op/workbench.py", 'def render_semantic(data: dict) -> str:',
'''def coordination_html(node: dict) -> str:
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


def render_semantic(data: dict) -> str:''')
edit("video2op/gates.py", 'if c.get("kind") == "hold" and c.get("node")', 'if c.get("kind") in {"hold", "constraint", "grip_scope"} and c.get("node")')
edit("video2op/gates.py", 'str(hold_chk.get("evidence") or "没有覆盖该约束的保持动作")',
'str(hold_chk.get("evidence") or "该持续约束尚需状态证据确认；不要求补保持动作")')
# Remove visible times only. Source evidence and internal temporal calculations remain intact.
edit("video2op/render.py", '                   f"　｜　示范 {t0:.1f}–{t1:.1f}s")', '                   )')
edit("video2op/render.py", '                if show_node_details:\n                    svg.append(f\'<text x="{cx:.1f}" y="{cy + 54:.1f}"',
'                if show_node_details and bundle.get("learning_layer") != "semantic":\n                    svg.append(f\'<text x="{cx:.1f}" y="{cy + 54:.1f}"')
print("Arm/hand functional boundaries, grip scopes and clean graph labels integrated.")
