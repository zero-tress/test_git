"""Separate arm motion from hand actuation and scope gripping to event boundaries."""
from __future__ import annotations

from copy import deepcopy

from .evidence import observed_state
from .grasp_preparation import is_grasp, state_kind

HAND_TO_ARM = {"左手": "左臂", "右手": "右臂"}
MOVE_WORDS = ("移动", "靠近", "接近", "伸出", "伸向", "前伸", "收回", "撤回",
              "抬起", "提起", "举起", "放下", "下降", "搬运", "运送", "移出", "移入",
              "拉回", "向左", "向右", "向前", "向后")
GRASP_WORDS = ("抓握", "抓取", "抓住", "抓紧", "握住", "夹住", "夹紧", "收拢")
RELEASE_WORDS = ("释放", "松开", "放开", "解除抓持")
OPEN_WORDS = ("张开", "打开手", "手指打开", "伸展手指")


def same_object(a: object, b: object) -> bool:
    a, b = str(a or ""), str(b or "")
    return bool(a and b and (a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))))


def function(action: dict) -> str:
    text, executor = str(action.get("action") or ""), action.get("executor")
    if executor in HAND_TO_ARM:
        if any(w in text for w in MOVE_WORDS):
            return "misbound_motion"
        if any(w in text for w in RELEASE_WORDS):
            return "释放"
        if text == "打开" or any(w in text for w in OPEN_WORDS):
            return "张开"
        if any(w in text for w in GRASP_WORDS):
            return "抓握"
        if any(w in text for w in ("按压", "按下")):
            return "按压"
        if any(w in text for w in ("触碰", "接触", "轻触")):
            return "接触"
        return "unclassified_hand"
    if executor in HAND_TO_ARM.values():
        if any(w in text for w in ("接近", "靠近", "前伸", "伸向", "伸出")):
            return "靠近"
        if any(w in text for w in ("收回", "撤回", "拉回")):
            return "撤回"
        for label, words in (("推", ("推动", "推开", "推移")), ("拉", ("拉动", "拉开", "拖动")),
                             ("旋转", ("旋转", "拧动", "转动")), ("按压", ("按压", "按下"))):
            if action.get("semantic_action") == label or any(w in text for w in words):
                return label
        if any(w in text for w in (*GRASP_WORDS, *OPEN_WORDS, *RELEASE_WORDS)) and not any(w in text for w in MOVE_WORDS):
            return "misbound_gripper"
        if any(w in text for w in MOVE_WORDS) or action.get("mode") == "motion":
            return "移动"
        if any(w in text for w in (*GRASP_WORDS, *OPEN_WORDS, *RELEASE_WORDS)):
            return "misbound_gripper"
        return "unclassified_arm"
    return "整体移动" if executor == "整体" else "unknown"


def function_issues(actions: list[dict]) -> list[dict]:
    issues = []
    for a in actions:
        f = function(a)
        if f in {"misbound_motion", "unclassified_hand", "misbound_gripper"}:
            issues.append({"atomic_ref": a.get("id"), "executor": a.get("executor"),
                           "action": a.get("action"), "kind": f,
                           "message": "手只负责张开、抓握、释放、接触、按压；空间移动由同侧臂承担。"
                                      "不能静默改执行主体；请复核画面，遮挡时明确记录不确定性。"})
    return issues


def release(action: dict) -> bool:
    return action.get("executor") in HAND_TO_ARM and any(
        w in str(action.get("action") or "") for w in RELEASE_WORDS)


def grip_constraint(text: str, hand: str, obj: str) -> bool:
    other = "左手" if hand == "右手" else "右手"
    if other in text:
        return False
    markers = ("保持", "维持", "持续", "全程", "直至", "直到")
    grip = ("抓握", "握持", "抓持", "夹持", "握住")
    return (any(w in text for w in markers) and any(w in text for w in grip)
            and (hand in text or (obj and obj in text)))


def inspect(actions: list[dict]) -> dict:
    ordered = sorted(actions, key=lambda a: (float(a.get("start", 0)), float(a.get("end", 0)), a["id"]))
    intervals, reach = [], []
    for grasp in ordered:
        if not is_grasp(grasp):
            continue
        hand, obj = grasp["executor"], str(grasp.get("object") or "")
        arm = HAND_TO_ARM[hand]
        end = next((a for a in ordered if release(a) and a.get("executor") == hand
                    and float(a.get("start", 0)) >= float(grasp.get("end", 0))
                    and (not a.get("object") or same_object(a.get("object"), obj))), None)
        start_supported = state_kind(observed_state(grasp)) == "occupied"
        violations = [a["id"] for a in ordered
                      if float(a.get("start", 0)) >= float(grasp.get("end", 0))
                      and (end is None or float(a.get("start", 0)) < float(end["start"]))
                      and a.get("executor") in {hand, arm} and not a.get("inferred")
                      and any(w in observed_state(a) for w in ("滑落", "掉落", "脱手"))
                      and not any(w in observed_state(a) for w in ("不滑落", "未滑落", "没有滑落", "不掉落", "未掉落", "没有掉落", "不脱手", "未脱手"))]
        intervals.append({
            "id": f"grip:{hand}:{grasp['id']}", "executor": hand, "object": obj,
            "grasp_ref": grasp["id"], "release_ref": end["id"] if end else None,
            "begin": {"event": "grasp_succeeded", "atomic_ref": grasp["id"],
                      "demonstration_time": None if grasp.get("inferred") else grasp.get("end")},
            "end": {"event": "release_starts", "atomic_ref": end["id"] if end else None,
                    "demonstration_time": end.get("start") if end and not end.get("inferred") else None},
            "interval_semantics": "[grasp_succeeded, release_starts)",
            "start_evidence": "observed" if start_supported else "unverified",
            "continuous_state_status": "violated" if violations else "unverified",
            "violation_refs": violations,
            "constraint_text": f"{hand}对{obj or '目标'}的稳定抓握在抓握成功后生效，持续至释放动作开始前",
            "note": "握持是持续约束，无保持动作节点。释放开始即允许张开；释放完成才确认抓持关系解除。"
                    + ("未观察到释放边界，保留开放终点待确认。" if end is None else "")
                    + "起点状态证据不等于全过程连续成立的证据。",
        })
        # A reach requirement is distinct from an invented approach action.
        candidates = [a for a in ordered if a.get("executor") == arm
                      and float(a.get("end", 0)) <= float(grasp.get("start", 0))
                      and same_object(a.get("object"), obj)]
        approach = candidates[-1] if candidates else None
        pose = observed_state(approach) if approach else ""
        before = observed_state(grasp, "state_before")
        ready_words = ("可抓取位置", "抓取位姿", "可触范围", "可抓范围", "已到达抓取位置")
        negatives = ("不在可", "未到达", "尚未到达", "不可达", "够不着", "超出", "无法触及", "未处于")
        before_blocked = any(w in before for w in negatives)
        ready = not before_blocked and any(
            any(w in text for w in ready_words) and not any(w in text for w in negatives)
            for text in (before, pose))
        requirement = {
            "id": f"reach:{hand}:{grasp['id']}", "executor": arm, "hand": hand, "object": obj,
            "grasp_ref": grasp["id"], "approach_ref": approach["id"] if approach else None,
            "required_state": f"{hand}在抓握前处于{obj or '目标'}的可抓取位置",
            "purpose": f"{arm}带着{hand}靠近目标，为手建立抓握提供空间条件",
            "status": "satisfied" if ready else "approach_observed" if approach and not approach.get("inferred") else "unknown",
            "note": "观察到靠近不等于已证实抓取位姿；目标是否超出整个机械臂工作空间需要另行判断。",
        }
        if requirement["status"] == "unknown":
            requirement["candidate_action"] = {
                "executor": arm, "action": "靠近", "inferred": True,
                "applicability": f"{hand}尚未处于目标的可抓取位置且目标位于臂可达范围内",
                "atomic_capability": "move_chain_client",
                "must_complete_before_atomic_ref": grasp["id"], "observed_time": None}
        reach.append(requirement)
    return {"grip_intervals": intervals, "reach_requirements": reach,
            "function_issues": function_issues(ordered)}


def annotate(bundle: dict) -> dict:
    actions = (bundle.get("atomic") or {}).get("atomic_actions") or []
    analysis = inspect(actions)
    amap = {a["id"]: a for a in actions}
    approach_refs = {r["approach_ref"]: r for r in analysis["reach_requirements"]
                     if r["approach_ref"] is not None}
    for a in actions:
        f = function(a)
        carrying = next((g for g in analysis["grip_intervals"]
                         if HAND_TO_ARM[g["executor"]] == a.get("executor")
                         and same_object(a.get("object"), g["object"])
                         and float(a.get("start", 0)) >= float(amap[g["grasp_ref"]].get("end", 0))
                         and (g["release_ref"] is None
                              or float(a.get("start", 0)) < float(amap[g["release_ref"]]["start"]))), None)
        if not carrying and f == "移动" and a["id"] in approach_refs:
            f = "靠近"
        a["functional_role"] = {
            "executor": a.get("executor"), "function": "带载移动" if carrying and f == "移动" else f,
            "atomic_capability": "OperateGripper" if f in {"张开", "抓握", "释放"}
                                 else "move_chain_client" if f in {"靠近", "移动", "撤回"} else None,
            "grip_constraint_ref": carrying["id"] if carrying else None,
            "load_state": "violated" if carrying and carrying["violation_refs"]
                          else "requires_grip" if carrying else None}
        if f in {"张开", "抓握", "释放"}:
            a["functional_role"]["control_mode"] = {"张开": "MODE_SET_WIDTH", "抓握": "MODE_GRASP", "释放": "MODE_RELEASE"}[f]
    for n in (bundle.get("task_nodes") or {}).get("task_nodes") or []:
        refs = set(n.get("atomic_refs") or [])
        selected = [amap[r] for r in refs if r in amap]
        n["functional_roles"] = [{"atomic_ref": a["id"], "action": a.get("action"), "mode": a.get("mode"),
                                  **deepcopy(a["functional_role"])} for a in sorted(selected, key=lambda a: (a.get("start", 0), a["id"]))]
        n["reach_requirements"] = [deepcopy(r) for r in analysis["reach_requirements"] if r["grasp_ref"] in refs]
        scoped = []
        const = n.setdefault("tuple", {}).setdefault("C_const", [])
        for grip in analysis["grip_intervals"]:
            start = float(amap[grip["grasp_ref"]].get("end", 0))
            stop = float(amap[grip["release_ref"]]["start"]) if grip["release_ref"] else float("inf")
            relevant = grip["grasp_ref"] in refs or any(
                a["id"] != grip["release_ref"] and same_object(a.get("object"), grip["object"])
                and float(a.get("start", 0)) < stop and float(a.get("end", 0)) > start
                for a in selected)
            if relevant:
                scoped.append(deepcopy(grip))
        desired = {g["constraint_text"] for g in scoped}
        for old in list(const):
            matching = [g for g in analysis["grip_intervals"]
                        if grip_constraint(old, g["executor"], g["object"])]
            if matching and old not in desired:
                const.remove(old)
                replacements = [g["constraint_text"] for g in scoped
                                if any(g["executor"] == m["executor"] and g["object"] == m["object"]
                                       for m in matching)]
                revision = {"original": old, "replacement": list(dict.fromkeys(replacements)),
                            "reason": "握持只在抓握成功后至释放开始前生效；不覆盖准备与释放过程"}
                history = n.setdefault("constraint_revisions", [])
                if revision not in history:
                    history.append(revision)
        for text in sorted(desired):
            if text not in const:
                const.append(text)
        n["scoped_grip_constraints"] = scoped
    bundle["arm_hand_coordination"] = analysis
    return analysis


def checks(bundle: dict) -> list[dict]:
    out = []
    for n in (bundle.get("task_nodes") or {}).get("task_nodes") or []:
        for g in n.get("scoped_grip_constraints") or []:
            out.append({"id": f"{g['id']}:{n['id']}", "kind": "grip_scope", "node": n["id"],
                        "question": g["constraint_text"], "verdict": g["continuous_state_status"],
                        "action": "flag", "evidence": g["note"],
                        "note": "持续状态由检测器确认，不补保持动作；开始/终止边界使用事件引用"})
        for r in n.get("reach_requirements") or []:
            out.append({"id": r["id"], "kind": "reach_precondition", "node": n["id"],
                        "question": r["required_state"], "verdict": r["status"],
                        "action": "keep" if r["status"] == "satisfied" else "flag",
                        "evidence": r["purpose"], "note": r["note"]})
    return out
