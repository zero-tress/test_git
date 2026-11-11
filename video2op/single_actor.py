"""Single-actor semantic steps and logical (not video-time) parallelism."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from . import arm_hand, evidence


def build(bundle: dict) -> dict:
    actions = (bundle.get("atomic") or {}).get("atomic_actions") or []
    amap = {a["id"]: a for a in actions}
    source = (bundle.get("task_nodes") or {}).get("task_nodes") or []
    owner = {r: n for n in source for r in n.get("atomic_refs") or []}
    prep = {r["grasp_ref"]: r for r in (bundle.get("grasp_preparation") or {}).get("requirements") or []}
    reach = {r["grasp_ref"]: r for r in (bundle.get("arm_hand_coordination") or {}).get("reach_requirements") or []}
    grips = (bundle.get("arm_hand_coordination") or {}).get("grip_intervals") or []
    nodes, action_node = [], {}
    ranks = {a["id"]: i * 3 for i, a in enumerate(sorted(actions, key=lambda a: (a.get("start", 0), a.get("end", 0), a["id"])))}

    def make(name, actor, refs, obj, *, inferred=False, origin="observed_action", post=None):
        index = len(nodes) + 1
        selected = [amap[r] for r in refs if r in amap]
        parents = list(dict.fromkeys(owner[r]["id"] for r in refs if r in owner))
        before = [s for a in selected[:1] for s in evidence.observed_states(a, "state_before")]
        after = list(post) if post is not None else [s for a in selected[-1:] for s in evidence.observed_states(a)]
        failed = any(w in str(s) for s in after for w in ("未抓住", "未握住", "未抓牢", "抓取失败", "无法释放", "未松开", "滑落", "掉落", "脱手"))
        if post is None and (not after or failed):
            after = [{"靠近": f"{actor}带手到达目标的可抓取位置",
                      "打开": f"{actor}已打开到可抓取状态", "抓取": f"{actor}已建立对目标的稳定握持",
                      "移动": "目标到达指定位置", "释放": f"{actor}已解除对目标的握持",
                      "撤回": f"{actor}已返回原位或安全位置"}.get(name, f"{name}的目标状态已达成")]
        tr = ([min(a.get("start", 0) for a in selected), max(a.get("end", 0) for a in selected)]
              if selected else None)
        n = {"id": f"step_{index}", "name": name,
             "intent_role": f"{actor}{name}，建立后续操作需要的状态",
             "required_capabilities": [name], "atomic_refs": list(refs), "time_range": tr,
             "inferred": inferred, "origin": origin, "source_node_ids": parents,
             "_semantic_order": min((ranks[r] for r in refs), default=0),
             "tuple": {"X": {"subject": actor, "parts": [actor]}, "O": [obj] if obj else [],
                       "C_pre": list(dict.fromkeys(before)), "C_const": [],
                       "E": {"process": [], "completion": list(after)},
                       "C_post": list(dict.fromkeys(after)), "R": [
                           {"name": f"{actor}{name}", "origin": "observed" if refs and not inferred else "inferred",
                            "steps": [name]}]}}
        n["tuple"]["C_const"] = list(dict.fromkeys(
            str(c) for s in source if s["id"] in parents
            for c in (s.get("tuple") or {}).get("C_const") or []
            if any(w in str(c) for w in ("不碰撞", "不能滑落", "不滑落", "不损伤", "不倾倒"))))
        nodes.append(n)
        for ref in refs:
            action_node[ref] = n
        return n

    ordered = sorted(actions, key=lambda a: (a.get("start", 0), a.get("end", 0), a["id"]))
    for a in ordered:
        actor = a.get("executor")
        if actor not in {"左臂", "右臂", "左手", "右手", "整体"}:
            continue
        role = (a.get("functional_role") or {}).get("function") or arm_hand.function(a)
        names = {"靠近": "靠近", "张开": "打开", "抓握": "抓取", "带载移动": "移动",
                 "移动": "移动", "释放": "释放", "撤回": "撤回",
                 "推": "推", "拉": "拉", "旋转": "旋转", "按压": "按压", "接触": "接触"}
        if actor == "整体":
            name = a.get("action") or "移动"
        else:
            name = names.get(role)
            if name is None:
                # Keep an unresolved meaning explicit; do not silently rebind its actor.
                original = owner.get(a["id"], {}).get("name") or a.get("action") or "未分类"
                name = {"搬运": "移动", "放置": "移动", "接近": "靠近", "张开": "打开"}.get(original, original)
        obj = a.get("object")
        # Adjacent same-arm motion stages (lift, carry, lower) become one semantic move.
        if nodes and name == "移动" and actor.endswith("臂") and nodes[-1]["name"] == name:
            last = nodes[-1]
            if last["tuple"]["X"]["subject"] == actor and arm_hand.same_object((last["tuple"]["O"] or [None])[0], obj):
                last["atomic_refs"].append(a["id"])
                last["source_node_ids"] = list(dict.fromkeys(last["source_node_ids"] + ([owner[a["id"]]["id"]] if a["id"] in owner else [])))
                last["time_range"][1] = max(last["time_range"][1], a.get("end", 0))
                after = evidence.observed_states(a)
                if not after or any(w in str(s) for s in after for w in ("滑落", "掉落", "脱手", "移动失败")):
                    after = ["目标到达指定位置且抓持未丢失"]
                last["tuple"]["C_post"] = list(after)
                last["tuple"]["E"]["completion"] = list(after)
                action_node[a["id"]] = last
                continue
        make(name, actor, [a["id"]], obj, inferred=bool(a.get("inferred")))

    dependencies: set[tuple[str, str]] = set()
    parallels: set[tuple[str, str]] = set()
    persistent = []
    def dep(a, b):
        if a and b and a["id"] != b["id"]:
            dependencies.add((a["id"], b["id"]))

    for grasp in ordered:
        gnode = action_node.get(grasp["id"])
        if not gnode or gnode["name"] != "抓取" or not grasp.get("executor", "").endswith("手"):
            continue
        hand, obj = grasp["executor"], grasp.get("object")
        arm = arm_hand.HAND_TO_ARM[hand]
        r = reach.get(grasp["id"]) or {}
        approach = action_node.get(r.get("approach_ref"))
        if not approach or approach["tuple"]["X"]["subject"] != arm:
            approach = make("靠近", arm, [], obj, inferred=True, origin="semantic_precondition",
                            post=[f"{hand}已处于目标的可抓取位置"])
            approach["_semantic_order"] = ranks[grasp["id"]] - 2
            approach["inference_reason"] = "抓取需要空间可达；未观察到独立靠近动作时，作为可已满足的语义准备目标"
        else:
            approach["name"] = "靠近"
            approach["intent_role"] = f"{arm}带着{hand}靠近目标，使手处于可抓取位置"
        p = prep.get(grasp["id"]) or {}
        opening = next((n for n in reversed(nodes) if n["name"] == "打开"
                        and n["tuple"]["X"]["subject"] == hand
                        and n["time_range"] and n["time_range"][1] <= grasp.get("start", 0)
                        and not any(a.get("executor") == hand and a["id"] != grasp["id"]
                                    and n["time_range"][1] < a.get("end", 0) <= grasp.get("start", 0)
                                    and arm_hand.function(a) == "抓握" for a in ordered)), None)
        if opening is None:
            state_evidence = p.get("state_evidence") or []
            known_open = p.get("status") == "satisfied"
            opening = make("打开", hand, [], obj, inferred=not known_open,
                           origin="observed_state_goal" if known_open else "semantic_precondition",
                           post=[e["text"] for e in state_evidence] if known_open else [f"{hand}已张开到可抓取状态"])
            opening["_semantic_order"] = ranks[grasp["id"]] - 1
            opening["already_satisfied"] = known_open
            opening["inference_reason"] = p.get("note") or "抓握前需打开手；动作是否在视频内发生尚未确认"
            opening["state_evidence"] = deepcopy(state_evidence)
        approach_goal = f"{hand}已处于目标的可抓取位置"
        open_goal = f"{hand}已打开到可抓取状态"
        approach["tuple"]["C_post"] = [approach_goal]
        opening["tuple"]["C_post"] = [open_goal]
        approach["condition_evidence"] = ([{"condition": approach_goal, "source": "可达状态证据",
                                            "atomic_refs": [x for x in (r.get("approach_ref"), grasp["id"]) if x is not None]}]
                                         if r.get("status") == "satisfied" else [])
        opening["condition_evidence"] = ([{"condition": open_goal, "source": "张开状态证据",
                                          "state_evidence": deepcopy(p.get("state_evidence") or [])}]
                                        if p.get("status") == "satisfied" else [])
        gnode["tuple"]["C_pre"] = [approach_goal, open_goal]
        gnode["intent_role"] = f"{hand}闭合并建立对目标的稳定握持"
        dep(approach, gnode)
        dep(opening, gnode)
        parallels.add(tuple(sorted((approach["id"], opening["id"]))))
        grip = next((g for g in grips if g["grasp_ref"] == grasp["id"]), None)
        release = action_node.get(grip.get("release_ref")) if grip else None
        moving = [n for n in nodes if n["name"] == "移动" and n["tuple"]["X"]["subject"] == arm
                  and n["time_range"] and n["time_range"][0] >= grasp.get("end", 0)
                  and (release is None or n["time_range"][0] < (release["time_range"] or [float("inf")])[0])
                  and any(arm_hand.same_object(o, obj) for o in n["tuple"]["O"])]
        previous = gnode
        for move in moving:
            dep(previous, move)
            previous = move
            if grip:
                move["tuple"]["C_const"] = [grip["constraint_text"]]
        if release:
            dep(previous, release)
            # Support is a condition for releasing, not evidence invented from mere ordering.
            support = [s for s in previous["tuple"]["C_post"] if any(w in s for w in ("桌面", "支撑", "杯底", "接触"))]
            release["tuple"]["C_pre"] = list(dict.fromkeys([*support, "目标已经受到可靠支撑，允许解除握持"]))
            if grip:
                persistent.append({"from": gnode["id"], "to": release["id"], "relation": "maintain_until",
                                   "until_event": "target_starts", "condition": grip["constraint_text"],
                                   "basis": "required_dependency",
                                   "note": "抓取成功后握持持续至释放开始前；维持关系不是保持动作节点"})
            retreats = [n for n in nodes if n["name"] == "撤回" and n["tuple"]["X"]["subject"] == arm
                        and n["time_range"] and n["time_range"][0] >= (release["time_range"] or [0, 0])[1]]
            if retreats:
                dep(release, retreats[0])

    # A single actor's own active actions remain ordered. Distinct preparation
    # actors are independent even if the demonstration happened to use a sequence.
    for actor in {n["tuple"]["X"]["subject"] for n in nodes}:
        chain = sorted([n for n in nodes if n["tuple"]["X"]["subject"] == actor],
                       key=lambda n: (n["_semantic_order"], n["id"]))
        # Inferred/state-goal preparation nodes must precede their corresponding grasp.
        for left, right in zip(chain, chain[1:], strict=False):
            if (right["id"], left["id"]) not in dependencies:
                dep(left, right)
    # Release and approach are exclusive semantic stages across actor boundaries.
    # Preserve their cycle order even when the video intervals overlap. Opening
    # may still run alongside the next approach after the previous release.
    boundaries = sorted(
        [n for n in nodes if n["name"] in {"释放", "靠近"}],
        key=lambda n: (n["_semantic_order"], n["id"]))
    for i, left in enumerate(boundaries):
        for right in boundaries[i + 1:]:
            if left["name"] != right["name"]:
                dep(left, right)
    # Remove redundant actor-order edges so the only bypass line is the
    # explicit persistent grip relation, not a second sequence shortcut.
    for edge in sorted(dependencies):
        a, b = edge
        todo, seen = [a], set()
        reached = False
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            for left, right in dependencies:
                if (left, right) == edge or left != current:
                    continue
                if right == b:
                    reached = True
                    break
                todo.append(right)
            if reached:
                break
        if reached:
            dependencies.remove(edge)
    # Omit incidental cross-actor demonstration ordering.
    edges = [{"from": a, "to": b, "relation": "sequence", "basis": "required_dependency",
              "note": "语义前置条件与单主体动作顺序"} for a, b in sorted(dependencies)]
    edges += [{"from": a, "to": b, "relation": "parallel", "basis": "semantic_independence",
               "mutual": True, "note": "臂靠近与手打开可在语义层并行；设备互斥由执行映射处理"}
              for a, b in sorted(parallels)]
    edges += persistent
    ids = {n["id"] for n in nodes}
    remaining = set(ids)
    columns = []
    while remaining:
        ready = sorted(n for n in remaining if not any(
            b == n and a in remaining for a, b in dependencies))
        if not ready:
            raise ValueError("单主体语义依赖出现环，请复核动作周期与推断准备节点")
        columns.append(ready)
        remaining.difference_update(ready)
    ordinal = {nid: (i, j) for i, col in enumerate(columns) for j, nid in enumerate(col)}
    nodes.sort(key=lambda n: ordinal[n["id"]])
    renumber = {n["id"]: f"step_{i}" for i, n in enumerate(nodes, 1)}
    for n in nodes:
        n["id"] = renumber[n["id"]]
    for e in edges:
        e["from"], e["to"] = renumber[e["from"]], renumber[e["to"]]
    columns = [[renumber[nid] for nid in col] for col in columns]
    return {"task_nodes": nodes, "edges": edges, "columns": columns, "action_node": {
        ref: n["id"] for ref, n in action_node.items()}}


def operations(bundle: dict, spec: dict) -> dict:
    from .operations import _to_operations
    actions = (bundle.get("atomic") or {}).get("atomic_actions") or []
    nodes = _to_operations(spec["task_nodes"], {a["id"]: a for a in actions})
    by_id = {n["id"]: n for n in nodes}
    sources = {n["id"]: n for n in spec["task_nodes"]}
    for n in nodes:
        source = sources[n["id"]]
        n.update(inferred=source.get("inferred", False), origin=source.get("origin"),
                 already_satisfied=source.get("already_satisfied", False),
                 inference_reason=source.get("inference_reason") or "")
    for layer, ids in enumerate(spec["columns"]):
        for nid in ids:
            by_id[nid]["layer"] = layer
    order = {nid: i for i, nid in enumerate(n for col in spec["columns"] for n in col)}
    nodes.sort(key=lambda n: order[n["id"]])
    counts = Counter(e["relation"] for e in spec["edges"])
    return {"nodes": nodes, "edges": deepcopy(spec["edges"]), "layers": spec["columns"],
            "semantic_columns": spec["columns"], "single_actor": True,
            "intent_chain": [], "parallel_groups": [[e["from"], e["to"]] for e in spec["edges"] if e["relation"] == "parallel"],
            "alternation_pairs": [[e["from"], e["to"]] for e in spec["edges"] if e["relation"] == "alternation"], "orchestration": "单执行主体；靠近与打开并行，合取门控后抓取",
            "stats": {"nodes": len(nodes), "edges": len(spec["edges"]), "holds": 0,
                      "executors": len({n["tuple"]["X"]["subject"] for n in spec["task_nodes"]}),
                      **{k: counts.get(k, 0) for k in ("sequence", "enables", "parallel", "alternation", "maintain_until")}}}


def audit(bundle: dict) -> dict:
    actions = (bundle.get("atomic") or {}).get("atomic_actions") or []
    tasks = {n["id"]: n for n in bundle["task_nodes"]["task_nodes"]}
    checks = []
    for op in bundle["operations"]["nodes"]:
        source = tasks[op["id"]]
        op["effect_evidence"] = []
        for post in op["post"]:
            refs = evidence.support(post, op, actions)
            state_goal = any(evidence.matches(post, e["text"]) for e in source.get("state_evidence") or [])
            state_goal = state_goal or any(evidence.matches(post, e["condition"]) for e in source.get("condition_evidence") or [])
            observed = bool(refs or state_goal)
            op["effect_evidence"].append({"condition": post, "status": "observed" if observed else "unverified",
                                          "atomic_refs": [a["id"] for a in refs], "origin": source.get("origin")})
            checks.append({"id": f"effect:{op['id']}:{len(checks)}", "kind": "evidence", "node": op["id"],
                           "question": post, "verdict": "evidenced" if observed else "unverified",
                           "action": "keep" if observed else "flag", "evidence": "状态证据支持" if observed else "语义目标，尚无观测支持",
                           "note": "语义依赖保留；未知状态不当作实际成功"})
    return {"checks": checks, "revisions": [], "gaps": [],
            "stats": {"checks": len(checks), "supported": sum(c["action"] == "keep" for c in checks),
                      "downgraded": 0, "gaps": 0, "flagged": sum(c["action"] == "flag" for c in checks)}}
