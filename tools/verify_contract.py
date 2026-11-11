#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用**执行侧自己的**加载器、实例化器和调度器验证 video2op 导出的契约。

用法：python tools/verify_contract.py 移动物体

做四件事，每一件都打印证据，不打印结论式好评：

  1. 加载：用执行侧的 `load_operation_graph` 读 `output/<案例>/semantic_graph.yaml`。
     缺字段、依赖成环、MAINTAIN 缺 maintain_until 都会在这里直接报错。
  2. 实例化：用 `GraphInstantiator` 把语义图绑到一份 TaskContext 上，得到可执行图。
     这一步能看出执行器绑定、实现候选、资源占用、超时是不是真的接得上。
  3. 调度：用 Dummy 动作跑一遍闭环，观察依赖顺序、并行资源、MAINTAIN 生命周期。
     **这是结构验证，不是“机器人已经能跑”**：Dummy 只是把动作当作成功返回。
  4. 谓词清单：列出契约里用到的语义条件，对照执行侧已注册的谓词名，给出还需要
     注册哪些检测器——这才是“待绑定”的具体内容。

退出码：0 表示加载与实例化通过；非 0 表示契约结构有问题。
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PEER = ROOT / "操作图同事的"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PEER))


from video2op import config


def _demo_context() -> TaskContext:
    """一份演示用的任务上下文：真实接入时由上层任务接口给出，不是这里编的。"""
    return TaskContext(
        object_id="target_01", arm="right_arm", gripper="right_gripper",
        object_pose={"xyz": [0.45, 0.0, 0.1]},
        grasp_pose={"xyz": [0.45, 0.0, 0.15]},
        place_pose={"xyz": [0.3, -0.3, 0.1]},
        parameters={},
    )


def _registry_for(predicates: list[str]) -> SemanticRegistry:
    """把契约用到的谓词注册成“读世界状态”的谓词。

    注意：执行侧默认注册表只认识它自己那套标签；契约里的谓词名前缀不同，必须显式
    注册。这里注册的实现是**最小桩**（读一个布尔量），真实接入时每一项都要换成真
    检测器（视觉 / 力觉 / 关节反馈）。未注册的谓词在执行侧默认返回 True，那样
    “不碰撞”这类约束会恒真——这个坑我们不踩。
    """
    registry = SemanticRegistry()
    for name in predicates:
        registry.register(name, lambda state, key=name: bool(state.get(key, False)))
    return registry


def _legacy_main() -> int:
    global ActionGateway, ActionRegistry, DummyAction, GraphInstantiator, TaskContext
    global GraphScheduler, TaskStatus, load_operation_graph, GraphValidationError, SemanticRegistry, WorldState
    from robot_operation_graph.atomic_actions import ActionGateway, ActionRegistry, DummyAction
    from robot_operation_graph.executable_graph import GraphInstantiator, TaskContext
    from robot_operation_graph.scheduler import GraphScheduler, TaskStatus
    from robot_operation_graph.semantic_graph import load_operation_graph
    from robot_operation_graph.semantic_graph.loader import GraphValidationError
    from robot_operation_graph.world import SemanticRegistry, WorldState


    case = sys.argv[1] if len(sys.argv) > 1 else None
    if not case:
        dirs = [d for d in config.OUTPUT_DIR.glob("*") if (d / "semantic_graph.yaml").exists()]
        print("候选案例：", "、".join(d.name for d in dirs) or "（还没有导出过契约）")
        return 1
    out_dir = config.OUTPUT_DIR / case
    graph_path = out_dir / "semantic_graph.yaml"
    policy_path = out_dir / "execution_policy.yaml"
    if not graph_path.exists():
        print(f"没有找到 {graph_path}；先跑 tools/render_case.py {case}")
        return 1

    print(f"=== 验证 {case} 的可执行契约 ===")
    print(f"图：{graph_path}")
    try:
        graph = load_operation_graph(graph_path)
    except GraphValidationError as e:
        print(f"[失败] 执行侧加载器拒绝了这个契约：{e}")
        return 2
    print(f"[1/4] 加载通过：{len(graph.nodes)} 个节点（START/END 都在），"
          f"start={graph.start_node} end={graph.end_node}")
    holds = [n.node_id for n in graph.nodes.values() if n.mode == "MAINTAIN"]
    print(f"      MAINTAIN 节点：{holds or '无'}")

    try:
        eog = GraphInstantiator(policy_path).instantiate(graph, _demo_context())
    except Exception as e:
        print(f"[失败] 实例化失败：{type(e).__name__}: {e}")
        return 3
    print(f"[2/4] 实例化通过：{len(eog.nodes)} 个可执行节点")
    for nid in ("A1", "A2", *tuple(holds)):
        node = eog.nodes.get(nid)
        if node:
            print(f"      {nid}: executor={node.executor} implementation={node.implementation} "
                  f"resources={node.resources} mode={node.mode}"
                  + (f" maintain_until={node.maintain_until}" if node.maintain_until else ""))

    # ---- 调度：用 Dummy 动作跑闭环，看依赖顺序与 MAINTAIN 生命周期 ----
    contract_preds = sorted({p for n in graph.nodes.values()
                             for p in list(n.preconditions) + list(n.constraints)
                             + list(n.evaluators) + list(n.postconditions)})
    initial = {name: True for name in
               ("OperationStartTriggered", "OperationEndTriggered")}
    state = WorldState(initial)
    dummy = DummyAction(default_ticks=2)
    registry = ActionRegistry()
    for node in eog.nodes.values():
        registry.register(node.implementation, dummy)
    scheduler = GraphScheduler(eog, state, _registry_for(contract_preds),
                               ActionGateway(registry), tick_hz=1000.0, echo=False,
                               event_log=None)

    # 环境前提（示范里第一步之前就成立的状态）与过程约束（不碰撞这类）在真实系统里由
    # 环境适配器与传感检测器实时给出；Dummy 闭环里没有真实物理，所以这里把它们预置为真。
    # 这是**演示假设**，不是执行结果——输出里会写明。
    presumed: list[str] = []
    for nid, node in graph.nodes.items():
        if nid == graph.start_node:
            continue
        for cond in list(node.preconditions) + list(node.constraints):
            if cond in contract_preds and not state.get(cond):
                state.set(cond, True)
                presumed.append(cond)
    print(f"      预置为真的条件 {len(presumed)} 条（环境前提 + 过程约束，演示假设）："
          f"{'、'.join(presumed[:6])}{' …' if len(presumed) > 6 else ''}")
    result = scheduler.run(max_ticks=400)
    print(f"[3/4] 调度结构跑通：task={result.value} ticks={scheduler.tick_count}")
    for nid in graph.nodes:
        node = eog.nodes[nid]
        print(f"      {nid:<5} {node.status.value:<8} "
              f"start={'-' if node.started_at is None else round(node.started_at, 3)} "
              f"finish={'-' if node.finished_at is None else round(node.finished_at, 3)}")
    ok_struct = result is TaskStatus.SUCCESS
    if not ok_struct:
        print(f"      失败报告：{json.dumps(asdict(scheduler.failure_report or {}), ensure_ascii=False, default=str)}")
    # 依赖顺序：每个节点不能早于它的依赖完成
    order_issues = []
    for nid, node in eog.nodes.items():
        for dep in node.dependencies:
            d = eog.nodes.get(dep)
            if not d or node.started_at is None or d.finished_at is None:
                continue
            if node.started_at + 1e-6 < d.finished_at:
                order_issues.append(f"{nid} 在依赖 {dep} 完成之前就启动了")
    if order_issues:
        print("      ⚠ 依赖顺序异常：" + "；".join(order_issues))
        ok_struct = False
    else:
        print("      依赖顺序：每个节点都不早于它的依赖完成 ✓")

    # ---- 谓词清单：哪些还要在执行侧注册 ----
    peer_default = {
        "ObjectLocated", "ObjectReachable", "ObjectSizeKnown", "GraspWidthKnown", "PlaceTargetKnown",
        "ArmAtPreGrasp", "GripperReady", "ReadyToClose", "PreliminaryGraspEstablished",
        "StableGraspEstablished", "GraspMaintained", "ObjectAtPlaceRegion", "ReadyForSupport",
        "EnvironmentSupportsObject", "GraspRelationRemoved", "PlacementCompleted",
        "OperationStartTriggered", "OperationEndTriggered", "OperationStarted", "OperationStopped",
    }
    known = [p for p in contract_preds if p in peer_default]
    unknown = [p for p in contract_preds if p not in peer_default]
    print(f"[4/4] 谓词清单：契约用到 {len(contract_preds)} 个条件，"
          f"执行侧已认识 {len(known)} 个，需注册检测器 {len(unknown)} 个")
    print("      需要注册（每一项对应一个真实检测器）：")
    for p in unknown:
        print(f"        - {p}")
    print()
    print("说明：第 3 步是**结构验证**——Dummy 动作把动作一律当作成功返回，"
          "环境前提是预置的，谓词检测器是最小桩。")
    print("      它证明的是：依赖顺序、资源占用、MAINTAIN 生命周期在执行侧跑得通；"
          "它不证明机器人已经能执行这件事。")
    return 0 if ok_struct else 4


def main() -> int:
    if len(sys.argv) > 1:
        import yaml
        candidate = Path(sys.argv[1])
        out = candidate if candidate.is_dir() else config.OUTPUT_DIR / sys.argv[1]
        graph_path = out / "semantic_graph.yaml"
        if graph_path.exists() and yaml.safe_load(graph_path.read_text()).get("layer") == "semantic":
            from video2op.semantic_interface import validate_files
            result = validate_files(out)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["passed"] else 2
    return _legacy_main()


if __name__ == "__main__":
    raise SystemExit(main())
