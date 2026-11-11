"""State-aware grasp preparation. Inferred requirements never become observations."""
from __future__ import annotations

from copy import deepcopy

from .evidence import observed_state

HANDS = {"左手", "右手"}
GRASP_WORDS = ("抓握", "抓取", "抓住", "抓紧", "握住", "夹住", "夹紧", "收拢")
OPEN_WORDS = ("张开", "打开手", "手指打开", "伸展手指")
RELEASE_WORDS = ("释放", "松开", "放开", "解除抓持")


def state_kind(text: str) -> str:
    text = str(text or "")
    if not text:
        return "unknown"
    # Negations are checked before positive words.
    if any(w in text for w in ("未张开", "没有张开", "尚未打开", "仍然闭合", "紧握成拳", "握拳", "开度不足", "张开不足", "未充分张开", "半张开")):
        return "closed"
    if any(w in text for w in ("张开", "展开手指", "手指打开", "松开", "释放完成")):
        return "open"
    if any(w in text for w in ("未抓住", "未握住", "未抓紧", "未接触", "没有握")):
        return "unknown"  # empty is not proof of a sufficient aperture
    if any(w in text for w in ("握持", "握住", "抓住", "抓紧", "夹持", "环绕并抓紧")):
        return "occupied"
    if any(w in text for w in ("紧握", "闭合", "合拢", "收拢")):
        return "closed"
    return "unknown"


def is_grasp(action: dict) -> bool:
    text = str(action.get("action") or "")
    return (action.get("executor") in HANDS and action.get("mode") == "transition"
            and any(w in text for w in GRASP_WORDS)
            and not any(w in text for w in (*OPEN_WORDS, *RELEASE_WORDS, "保持", "维持")))


def inspect(actions: list[dict]) -> list[dict]:
    requirements = []
    ordered = sorted(actions, key=lambda a: (float(a.get("start", 0)), float(a.get("end", 0)), a["id"]))
    for grasp in ordered:
        if not is_grasp(grasp):
            continue
        hand, ref = grasp["executor"], grasp["id"]
        evidence = []
        # Prefer the directly observed state immediately before this grasp.
        before = observed_state(grasp, "state_before")
        state = state_kind(before)
        if state != "unknown":
            evidence.append({"atomic_ref": ref, "field": "state_before", "text": before})
        else:
            # Never treat default rest-state or inherited text as video evidence.
            prior = [a for a in ordered if a["id"] != ref and a.get("executor") == hand
                     and float(a.get("end", 0)) <= float(grasp.get("start", 0))]
            for a in reversed(prior):
                after = observed_state(a)
                kind = state_kind(after)
                if kind != "unknown":
                    state = kind
                    evidence.append({"atomic_ref": a["id"], "field": "state_after", "text": after})
                    break
                # A later unknown state-changing event invalidates an earlier open state.
                if a.get("mode") == "transition":
                    break
        status = {"open": "satisfied", "closed": "inferred_preparation",
                  "occupied": "conflict", "unknown": "unknown"}[state]
        requirement = {
            "id": f"preopen:{hand}:{ref}", "executor": hand, "grasp_ref": ref,
            "required_state": f"{hand}在抓握开始前已张开到可包络目标的状态",
            "required_before": {"event": "grasp_starts", "atomic_ref": ref},
            "status": status, "state_evidence": evidence,
            "scope": "internal_grasp_precondition",
            "note": {
                "satisfied": "已有张开状态证据；不能由此断言视频里发生过独立张开动作",
                "inferred_preparation": "已观察到不满足张开前提的手状态；张开是必要准备，动作本身未被观察，需核实",
                "conflict": "手可能已持有物体；先复核占用、重复抓握或重抓，不擅自推断张开释放",
                "unknown": "开度状态未知；补充必要前提和条件式准备候选，不断言手原先紧握",
            }[status],
        }
        if status in {"inferred_preparation", "unknown"}:
            requirement["candidate_action"] = {
                "action": "张开", "executor": hand, "mode": "transition", "inferred": True,
                "origin": "functional_precondition",
                "applicability": "手尚未张开到可包络目标的状态",
                "expected_effect": requirement["required_state"],
                "must_complete_before_atomic_ref": ref, "observed_time": None,
                "atomic_capability": "OperateGripper", "control_mode": "MODE_SET_WIDTH",
                "parameters_status": "unbound",
            }
        requirements.append(requirement)
    return requirements


def annotate(bundle: dict) -> dict:
    """Idempotent metadata annotation; do not add fake actions, states or seconds."""
    actions = (bundle.get("atomic") or {}).get("atomic_actions") or []
    requirements = inspect(actions)
    by_ref = {r["grasp_ref"]: r for r in requirements}
    for a in actions:
        if a["id"] in by_ref:
            a["grasp_preparation"] = deepcopy(by_ref[a["id"]])
        else:
            a.pop("grasp_preparation", None)
    for n in (bundle.get("task_nodes") or {}).get("task_nodes") or []:
        refs = set(n.get("atomic_refs") or [])
        n["preparation_requirements"] = [deepcopy(r) for r in requirements if r["grasp_ref"] in refs]
    bundle["grasp_preparation"] = {
        "requirements": requirements,
        "policy": "臂负责靠近与带载移动；手负责张开、抓握、释放。抓握前张开是内部前置条件；推断不充当观测证据。",
        "stats": {s: sum(r["status"] == s for r in requirements)
                  for s in ("satisfied", "inferred_preparation", "unknown", "conflict")},
    }
    return bundle["grasp_preparation"]


def checks(bundle: dict) -> list[dict]:
    return [{
        "id": r["id"], "kind": "grasp_preparation", "node": n["id"],
        "question": r["required_state"], "verdict": r["status"],
        "action": "keep" if r["status"] == "satisfied" else "flag",
        "evidence": "；".join(e["text"] for e in r["state_evidence"]) or "无可信开度观测",
        "note": r["note"], "inferred_candidate": r.get("candidate_action"),
    } for n in (bundle.get("task_nodes") or {}).get("task_nodes") or []
       for r in n.get("preparation_requirements") or []]
