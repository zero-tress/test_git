#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可执行契约导出：把学出来的操作图写成执行层能直接加载的语义图。

**这份导出的定位**：前面几步产出的是"这套图说了什么"（人看的报告、操作图 SVG、
证据与推理修正）。这一份是"执行层拿它做什么"——它对齐执行侧的语义图 schema：

    graph_id / start_node / end_node / nodes{ id → 节点 }
    节点 = name / phase / subject / object / pre / constraints / evaluator /
           post / implementation / dependencies / mode / maintain_until

七元组在这里各自归位：
    执行主体 subject · 操作对象 object · 前置条件 pre · 约束元 constraints ·
    评价指标 evaluator · 后置效果 post · 候选方式集合 implementation

两条纪律，导出时一条都不放松：

1. **条件不翻译成更好的说法，只给它们名字**。pre/post 里的谓词名指向谓词表里
   的原文（`predicates.json` / result.json 的 `predicates`），执行层检查的是同一
   条条件，不是我们替它改写过的近义词。
2. **不猜参数**。implementation 只写"这一步需要哪一类能力"（名字取自执行侧的
   实现词表），参数绑定、超时、阈值一律留空并标注 `unbound`——那些必须由接入时
   的真实执行器给，导出层编不出来。

另外，`semantic_graph.yaml` 里带 `x-video2op` 前缀的字段是我们的扩展（证据、时间
范围、示范执行者、推理结论）。执行侧加载器忽略多余字段，人复核时正好用得上。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import predicates as pred_mod

# ---------------------------------------------------------------
# 命名映射：示范里的部位 → 能力层执行器名
# ---------------------------------------------------------------
# 用执行侧已有的名字（RightArm / RightGripper / …），这样 GraphInstantiator 能把
# 执行器绑到任务上下文里的真实设备上；人的“右手”在能力层就是该侧的终端执行器
# （夹爪 / 灵巧手由接入时决定）。示范里到底是哪个部位，保留在 x-video2op 里。
EXECUTOR_CAPABILITY = {
    "整体": "LocomotionSystem",
    "右臂": "RightArm", "左臂": "LeftArm",
    "右手": "RightGripper", "左手": "LeftGripper",
    "双手": "ArmGripperSystem", "双臂": "DualArmSystem",
    "腰": "Torso", "躯干": "Torso", "身体": "Torso", "腰背": "Torso",
    "右腿": "Legs", "左腿": "Legs", "腿": "Legs",
}

# 能力需求 → 候选实现方式。名字取自执行侧实现词表，接入时可直接绑定。
CAPABILITY_IMPLEMENTATIONS = {
    "接近目标": ["PlannedMove", "CartesianMove", "JointMove"],
    "建立抓持": ["PositionClose", "ForceClose", "HybridClose"],
    "承载移动": ["PlannedTransport", "CartesianTransport", "JointTransport"],
    "稳定放置": ["LinearPlace", "IncrementalPlace", "CompliantPlace"],
    "收回肢体": ["LinearRetreat", "SafePoseRetreat"],
    "持续保持抓持": ["PositionHold", "ForceHold", "AdaptiveHold"],
    "持续保持托举": ["PositionHold", "CartesianHold"],
    "持续保持位姿": ["PositionHold", "CartesianHold"],
    "持续保持接触": ["PositionHold", "ContactHold"],
    "清障": ["Push", "Pull", "GraspMove"],
    "举起": ["PlannedLift", "CartesianLift"],
    "稳定支撑": ["PositionHold"],
    "建立接触": ["LinearApproach", "CompliantApproach"],
    "解除抓持": ["OpenRelease", "ProgressiveRelease"],
    "释放": ["OpenRelease", "ProgressiveRelease"],
    "手部预张开": ["AdaptiveOpen", "FullOpen"],
    "移动执行器": ["PlannedMove", "CartesianMove"],
    "状态切换": ["PlannedMove"],
}
DEFAULT_IMPLEMENTATIONS = ["PlannedMove"]

# 词表未收录时的关键词兑底：模型给的能力词是自由文本，语义能对上就给出候选，
# 同时仍把原词记进 unmapped（提醒补词表）——不给对的候选，就会落到默认值
# （曾把“释放”映射成 PlannedMove）。顺序敏感：释放优先于抓持（“释放抓持”）。
CAPABILITY_KEYWORD_FALLBACK = [
    (("释放", "解除", "松开", "张开", "脱落"), ["OpenRelease", "ProgressiveRelease"]),
    (("抓持", "抓握", "夹持", "夹紧"), ["PositionClose", "ForceClose", "HybridClose"]),
    (("接触", "贴合"), ["LinearApproach", "CompliantApproach"]),
    (("保持", "维持"), ["PositionHold", "CartesianHold"]),
    (("承载", "搬运", "运送", "转移"), ["PlannedTransport", "CartesianTransport", "JointTransport"]),
    (("放置", "放下", "安放"), ["LinearPlace", "IncrementalPlace", "CompliantPlace"]),
    (("收回", "撤回", "退回"), ["LinearRetreat", "SafePoseRetreat"]),
    (("接近", "伸展", "靠近", "伸出", "前伸"), ["PlannedMove", "CartesianMove", "JointMove"]),
    (("举起", "提起", "抬起"), ["PlannedLift", "CartesianLift"]),
]


def _keyword_implementations(capability: str) -> list[str]:
    for words, impls in CAPABILITY_KEYWORD_FALLBACK:
        if any(w in capability for w in words):
            return list(impls)
    return []

# 操作名 → 英文操作名（对齐执行侧的谓词式命名风格）
OPERATION_NAMES = [
    (("向目标移动",), "MoveToTarget"),
    (("上升",), "RaiseOperatingHeight"),
    (("下降",), "LowerOperatingHeight"),
    (("调整操作位置",), "AdjustOperatingPose"),
    (("保持抓握", "持续抓握"), "MaintainGrasp"),
    (("保持托举", "保持抬起托举"), "MaintainLift"),
    (("保持伸出", "保持位姿", "保持位置"), "MaintainPose"),
    (("保持", "维持"), "MaintainState"),
    (("张开手指", "预张开", "张开至"), "GripperPreOpen"),
    (("接近", "靠近", "前伸", "走到", "走向"), "ApproachTarget"),
    (("抓取", "抓握", "夹住", "拿起"), "GraspTarget"),
    (("搬运", "移动", "转移", "送到", "送至"), "TransportTarget"),
    (("放置", "放下", "安放"), "PlaceTarget"),
    (("收回", "撤回", "退回", "复位", "归位", "恢复", "手臂收回"), "ArmRetreat"),
    (("打开", "拉开", "拧开"), "OpenTarget"),
    (("关闭", "关上", "旋紧"), "CloseTarget"),
    (("清障", "清除", "挪开"), "ClearObstacle"),
    (("提起", "举起", "抬起"), "LiftTarget"),
    (("释放", "松开"), "ReleaseTarget"),
    (("饮用", "喝", "送入嘴", "送到嘴"), "ConsumeTarget"),
    (("下蹲", "弯腰", "俯身"), "CrouchDown"),
    (("起身", "直立", "站起"), "StandUp"),
    (("转身", "调转"), "TurnBody"),
]

# 操作名 → 阶段
PHASE_WORDS = [
    (("接近", "靠近", "前伸", "走到", "走向", "转身", "张开手指"), "approach"),
    (("抓取", "抓握", "夹住", "握住", "清障", "打开", "拧开", "下蹲", "弯腰"), "grasp"),
    (("搬运", "转移", "提起", "举起", "移动", "送至", "送到", "起身", "直立"), "transport"),
    (("放置", "放下", "释放", "松开", "安放", "关闭", "旋紧"), "place"),
    (("收回", "撤回", "退回", "复位", "归位"), "retreat"),
    (("饮用", "喝", "送入嘴"), "consume"),
]

START_NODE = {
    "name": "BeginOperation", "phase": "start", "subject": "OperationSystem",
    "object": "TaskTarget", "pre": ["OperationStartTriggered"], "constraints": [],
    "evaluator": [], "post": ["OperationStarted"], "implementation": ["BeginOperation"],
    "dependencies": [], "mode": "NORMAL",
}
END_NODE = {
    "name": "EndOperation", "phase": "end", "subject": "OperationSystem",
    "object": "TaskTarget",
    # END 的前置条件只能等**本图里某个节点真的会产生**的状态：
    # 照抄别人图里的状态名（那是他那张图的终点效果），会永远等不到。
    # 具体的“最后一步”后置谓词由 build_contract 补上。
    "pre": ["OperationEndTriggered"],
    "constraints": [], "evaluator": [], "post": ["OperationStopped"],
    "implementation": ["EndOperation"], "dependencies": [], "mode": "NORMAL",
}


def _en_name(name: str, used: set[str]) -> str:
    for words, en in OPERATION_NAMES:
        if any(w in name for w in words):
            base = en
            break
    else:
        base = "Operation"
    out, i = base, 2
    while out in used:
        out = f"{base}{i}"
        i += 1
    used.add(out)
    return out


def _phase(name: str, op: dict, covers_phase: str = "") -> str:
    for words, ph in PHASE_WORDS:
        if any(w in name for w in words):
            return ph
    return covers_phase or "task"


# 保持节点的建议检查项：由保持类别派生。它是**建议**，不是从视频里看出来的，
# 所以导出时单独标源（x-video2op.evaluator_source），接入时按真实传感器替换。
HOLD_EVALUATORS = {
    "grasp": ["GripperWidthStability", "ContactState"],
    "support": ["HoldStability", "ContactState"],
    "contact": ["ContactState"],
    "pose": ["PoseHoldError"],
}


def _subject(executors: list[str]) -> str:
    """执行主体（能力层）。

    多个部位参与时取**主导执行器**：搬运、接近、收回这类动作由臂主导，臂占 arm 资源；
    只有手参与时才写终端执行器。这样才能和执行侧的资源仲裁对上——同事的 A6（带载
    移动，RightArm）与 A7（保持夹持，RightGripper）之所以能并行，就是因为两者资源
    不同；把“右臂+右手”写成同一个执行器反而会把它们错开。
    """
    parts = [EXECUTOR_CAPABILITY.get(str(e), str(e)) for e in executors if e]
    if not parts:
        return "OperationSystem"
    for arm in ("RightArm", "LeftArm"):
        if arm in parts:
            return arm
    if len(set(parts)) == 1:
        return parts[0]
    return "ArmGripperSystem"       # 多部件协同（双手合抱这类）


def _executor_note(executors: list[str]) -> str:
    """能力层名与示范部位的对应说明——写进扩展段，避免“把手当成夹爪”的误解。"""
    pairs = [f"{EXECUTOR_CAPABILITY.get(str(e), str(e))}←{e}" for e in executors if e]
    return "；".join(pairs)


def _subject_of(op: dict, amap: dict) -> str:
    """本操作的执行主体。

    按**主动作**算：保持动作不算（那件事已经由保持节点承担），取时长最长的那个主动作
    的执行器——它最能代表这一步在执行器层面占用了谁。

    不用“臂优先”之类的固定顺序：拧瓶盖、放瓶盖这类动作的主体是手，臂只是跟随；
    一律写 RightArm 会把“手在做的事”记到臂上，也会让保持节点与它抢同一个资源。
    """
    active = [(a) for r in (op.get("atomic_refs") or [])
              for a in [amap.get(r)]
              if a and str(a.get("mode")) != "maintain" and a.get("executor")]
    if active:
        best = max(active, key=lambda a: (float(a.get("end", 0)) - float(a.get("start", 0)),
                                          -float(a.get("start", 0))))
        return _subject([str(best.get("executor"))])
    return _subject([str(e) for e in (op.get("executors") or []) if e])

def _implementations(op: dict, unmapped: list[str]) -> list[str]:
    out: list[str] = []
    for cap in op.get("required_capabilities") or []:
        key = str(cap)
        cands = CAPABILITY_IMPLEMENTATIONS.get(key)
        if not cands:
            cands = _keyword_implementations(key)   # 词表未收录：关键词兑底
            unmapped.append(key)                    # 仍记下原词，提醒补词表
        if not cands:
            continue
        for c in cands:
            if c not in out:
                out.append(c)
    if not out:
        out = list(DEFAULT_IMPLEMENTATIONS)
        unmapped.append(str(op.get("name") or ""))
    return out


def _pred_ids(table: dict, texts: list | None) -> list[str]:
    out: list[str] = []
    for t in texts or []:
        pid = pred_mod.lookup(table, t)
        if pid and pid not in out:
            out.append(pid)
    return out


def build_contract(bundle: dict) -> dict:
    """把操作图编译成执行侧的语义图结构（纯数据，可直接序列化成 YAML）。"""
    ops = ((bundle.get("operations") or {}).get("nodes")) or []
    edges = ((bundle.get("operations") or {}).get("edges")) or []
    amap = {a.get("id"): a for a in ((bundle.get("atomic") or {}).get("atomic_actions") or [])
            if isinstance(a, dict)}
    table = bundle.get("predicates") or pred_mod.build(bundle)
    intents = (bundle.get("intents") or {}).get("intents") or []
    task_intent = str(intents[0].get("statement") or "") if intents else ""

    hold_nodes = [o for o in ops if str(o.get("mode") or "") == "maintain"]
    plain = [o for o in ops if str(o.get("mode") or "") != "maintain"]
    id_map: dict[str, str] = {}
    for i, o in enumerate(plain, start=1):
        id_map[str(o["id"])] = f"A{i}"
    for i, o in enumerate(hold_nodes, start=1):
        id_map[str(o["id"])] = f"H{i}"

    omap = {str(o["id"]): o for o in ops}
    # 依赖：sequence / enables 边表达“先做完前者”；maintain_until 由 MAINTAIN 节点自己带
    deps: dict[str, list[str]] = {str(o["id"]): [] for o in ops}
    parallel_with: dict[str, list[str]] = {str(o["id"]): [] for o in ops}
    holds_of: dict[str, list[str]] = {str(o["id"]): [] for o in ops}
    for e in edges:
        f, t = str(e.get("from")), str(e.get("to"))
        if f not in omap or t not in omap:
            continue
        rel = str(e.get("relation"))
        if rel in ("sequence", "enables") and f not in deps[t]:
            deps[t].append(f)
        elif rel == "parallel":
            if t not in parallel_with[f]:
                parallel_with[f].append(t)
            if f not in parallel_with[t]:
                parallel_with[t].append(f)
    for h in hold_nodes:
        for c in h.get("covers") or []:
            if str(c) in holds_of:
                holds_of[str(c)].append(str(h["id"]))

    used_names: set[str] = set()
    unmapped: list[str] = []
    nodes: dict[str, dict] = {"START": dict(START_NODE)}
    for o in ops:
        oid = str(o["id"])
        nid = id_map[oid]
        is_hold = str(o.get("mode") or "") == "maintain"
        covers_phase = ""
        if is_hold:
            covered = [omap[c] for c in (o.get("covers") or []) if c in omap]
            phases: list[str] = []
            for c in covered:
                ph = _phase(str(c.get("name") or ""), c)
                if ph not in phases:
                    phases.append(ph)
            covers_phase = "_".join(phases)          # 如 transport_place
        evaluator = [f"Verify_{p}" for p in _pred_ids(table, o.get("completion"))]
        evaluator_source = "observed_completion"
        if is_hold and not evaluator:
            evaluator = list(HOLD_EVALUATORS.get(str(o.get("hold_category") or "pose"), []))
            evaluator_source = "derived_from_hold_category"
        entry = [id_map[d] for d in deps.get(oid, []) if d in id_map and not is_hold]
        if is_hold:
            # 保持节点的依赖 = 建立它的那一步；其余被覆盖的步骤靠 maintain_until 表达
            entry = [id_map[d] for d in deps.get(oid, []) if d in id_map]
        if not entry and not is_hold:
            entry = ["START"]
        name = str(o.get("name") or "")
        subject = _subject_of(o, amap)
        if subject == "LocomotionSystem" and name in ("移动", "向目标移动"):
            name = "向目标移动"
        node = {
            "name": _en_name(name, used_names),
            # 保持节点的阶段由它覆盖的步骤决定（跨越搬运与放置时写 transport_place）
            "phase": (covers_phase or "task") if is_hold
                     else _phase(str(o.get("name") or ""), o, covers_phase),
            "subject": subject,
            "object": "TargetObject",
            "pre": _pred_ids(table, o.get("pre")) or ["OperationStarted"],
            "constraints": _pred_ids(table, o.get("invariants")),
            "evaluator": evaluator,
            "post": _pred_ids(table, o.get("post")),
            "implementation": _implementations(o, unmapped),
            "dependencies": entry,
        }
        if is_hold:
            node["mode"] = "MAINTAIN"
            node["maintain_until"] = [id_map[c] for c in (o.get("maintain_until") or [])
                                      if c in id_map]
        else:
            node["mode"] = "NORMAL"
        # ---- video2op 扩展：证据与推理结论（执行侧加载器会忽略，人复核要用） ----
        ext: dict = {
            "operation_id": oid,
            "operation_name": str(o.get("name") or ""),
            "intent": str(o.get("intent") or ""),
            "demonstration": {
                "time_range": [o.get("start"), o.get("end")],
                "executors": list(o.get("executors") or []),
                "executor_binding": _executor_note(list(o.get("executors") or [])),
                "atomic_refs": list(o.get("atomic_refs") or []),
                "inferred_steps": int(o.get("inferred_steps") or 0),
            },
            "pre_text": list(o.get("pre") or []),
            "post_text": list(o.get("post") or []),
            "constraint_text": list(o.get("invariants") or []),
        }
        if o.get("purpose"):
            ext["purpose"] = o["purpose"]
        if parallel_with.get(oid):
            ext["parallel_with"] = [id_map[x] for x in parallel_with[oid] if x in id_map]
        if holds_of.get(oid):
            ext["held_by"] = [id_map[x] for x in holds_of[oid] if x in id_map]
        if is_hold:
            ext["covers"] = [id_map[c] for c in (o.get("covers") or []) if c in id_map]
            ext["stop_event"] = o.get("stop_event")
            ext["hold_category"] = o.get("hold_category")
            if evaluator_source != "observed_completion":
                ext["evaluator_source"] = evaluator_source
        node["x-video2op"] = ext
        nodes[nid] = node

    end = dict(END_NODE)
    if plain:
        last = plain[-1]
        end["dependencies"] = [id_map[str(last["id"])]]
        # 结束条件 = 触发信号 + 最后一步真的产生了的效果（这些谓词本图会产生，
        # 执行侧能注册检测器；照抄别人图的终点状态则永远等不到）。
        end["pre"] = ["OperationEndTriggered", *_pred_ids(table, last.get("post"))]
        end["x-video2op"] = {"waits_for": str(last.get("name") or ""),
                             "last_operation": str(last.get("id") or "")}
    nodes["END"] = end

    return {
        "schema_version": "1.0",
        "kind": "operation_contract",
        "graph_id": str((bundle.get("meta") or {}).get("name") or "operation_graph"),
        "start_node": "START",
        "end_node": "END",
        "task_intent": task_intent,
        "nodes": nodes,
        "x-video2op": {
            "source": "video2op",
            "note": "pre/post 里的标识对应谓词表原文；本文件只给条件命名，不改写条件。",
            "predicate_count": int((table.get("stats") or {}).get("predicates") or 0),
            "unmapped_capabilities": sorted(set(unmapped)),
            "id_map": id_map,
        },
    }


def build_policy(contract: dict) -> dict:
    """导出待绑定的实现选择策略（对齐执行侧 policy：implementations / parameter_bindings）。"""
    impls: dict[str, str] = {}
    for nid, node in (contract.get("nodes") or {}).items():
        cands = node.get("implementation") or []
        if cands:
            impls[nid] = cands[0]          # 首选候选；其余候选留在语义图的 implementation 列表里
    return {
        "implementations": impls,
        "parameter_bindings": {},          # 参数必须由接入时的真实执行器给，导出层不猜
        "timeouts": {},                    # 同上：不在语义层编造时间
        "x-video2op": {
            "status": "unbound",
            "note": "本文件只给出实现选择的起点。parameter_bindings / timeouts 需要执行侧"
                    "按真实能力表填写；填不出来说明该操作还需要能力补齐，不是可以略过。",
        },
    }


def _dump_yaml(path: Path, data: dict, header: str) -> None:
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110)
    path.write_text(header + body, encoding="utf-8")


GRAPH_HEADER = (
    "# 由 video2op 从操作视频学习导出的操作语义图（UTF-8）。\n"
    "#\n"
    "# 读法：pre / post / constraints / evaluator 里是谓词名，原文在 result.json 的\n"
    "#       predicates.predicates（同一份数据；导出不翻译、不改写条件）。\n"
    "#       x-video2op 段是我们的扩展字段：示范执行者、时间范围、证据引用与推理结论，\n"
    "#       执行侧加载器忽略它，人复核时用它。\n"
    "#\n"
    "# 注意：这是**未绑定执行器**的契约。视频秒数只作示范证据，不是调度指令；\n"
    "#       implementation 里写的是“需要哪一类能力”，具体参数由接入时绑定。\n"
)

POLICY_HEADER = (
    "# 由 video2op 导出的待绑定实现策略（UTF-8）。\n"
    "# implementations 是每一步的首选实现方式（名字取自执行侧实现词表）；\n"
    "# parameter_bindings / timeouts 留空：参数与超时必须由接入时的真实执行器给出。\n"
)


def export(bundle: dict, out_dir: Path | None = None) -> dict:
    """构建契约并（可选）落盘：semantic_graph.yaml + execution_policy.yaml。"""
    if bundle.get("learning_layer") == "semantic":
        from . import semantic
        if out_dir is not None:
            semantic.export(bundle, Path(out_dir))
        return {"semantic_graph": bundle["semantic_graph"]}
    contract = build_contract(bundle)
    policy = build_policy(contract)
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        _dump_yaml(out_dir / "semantic_graph.yaml", contract, GRAPH_HEADER)
        _dump_yaml(out_dir / "execution_policy.yaml", policy, POLICY_HEADER)
    return {"contract": contract, "policy": policy}
