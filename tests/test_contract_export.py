"""导出层回归：约束分类、保持节点提升、释放拆分、谓词化、契约 schema、子操作展开。

这些用例都是确定性的（不调用模型），覆盖的是"图学出来了，但执行层能不能接住"这一段。
"""
from video2op import contract, expand, predicates
from video2op.pipeline import build_legacy_execution_graph as build_operation_graph
from video2op.stages import s06_validate
from video2op.vocab import constraint_kind, hold_category, is_self_hold


def action(i, executor="右手", text="靠近目标", mode="motion", start=0.0, end=1.0,
           before=None, after=None, inferred=False, force=None, role=None):
    return dict(id=i, executor=executor, action=text, mode=mode, start=start, end=end,
                state_before=before, state_after=after, inferred=inferred,
                exerts_force=True, force_role=role)


def node(i, name, refs, pre=(), post=(), start=0.0, end=1.0, invariants=(),
         parts=("右手",), caps=("建立抓持",), completion=()):
    return dict(id=i, name=name, intent_role=f"{name}的意图", required_capabilities=list(caps),
                atomic_refs=list(refs), time_range=[start, end], tuple={
                    "X": {"parts": list(parts)}, "O": ["目标物"],
                    "C_pre": list(pre), "C_post": list(post), "C_const": list(invariants),
                    "E": {"process": [], "completion": list(completion)}})


def build(nodes, actions, relations=()):
    b = {"task_nodes": {"task_nodes": nodes},
         "atomic": {"atomic_actions": actions}, "relations": list(relations)}
    build_operation_graph(b)
    return b


def _grasp_then_place():
    """一个最小但完整的例子：抓取 → 搬运 → 放置（含释放），保持跨越搬运与放置。"""
    actions = [
        action(1, "右手", "右手手指收拢抓紧杯子", "transition", 1.0, 2.0,
               before="手指张开", after="右手抓握杯子", role="抓握"),
        action(2, "右手", "右手保持抓握杯子", "maintain", 2.0, 6.0,
               before="右手已建立抓握", after="右手松开杯子", role="抓握"),
        action(3, "右臂", "右臂抬起并移动", "motion", 2.0, 5.0,
               before="手臂静止", after="杯子到达目标位置", role="托举"),
        action(4, "右臂", "右臂保持抬起", "maintain", 5.0, 7.0,
               before="保持抬起", after="保持抬起", role="托举"),
        action(5, "右手", "右手手指张开释放杯子", "transition", 6.0, 7.0,
               before="右手抓握杯子", after="手指张开不再接触杯子", role="抓握"),
    ]
    nodes = [
        node("n1", "抓取杯子", [1], pre=["杯子位于桌面上"], post=["右手抓握杯子"],
             start=1.0, end=2.0),
        node("n2", "搬运杯子", [3], pre=["右手抓握杯子"], post=["杯子到达目标位置"],
             start=2.0, end=5.0, invariants=["移动过程中保持对杯子的抓握"]),
        node("n3", "放置杯子", [4, 5], pre=["杯子到达目标位置"], post=["杯子落在支撑面上"],
             start=5.0, end=7.0, invariants=["释放前保持杯子竖直"]),
    ]
    return build(nodes, actions)


# ---------------------------------------------------------------
# 约束分类
# ---------------------------------------------------------------

def test_constraint_kind_separates_safety_from_hold():
    assert constraint_kind("右臂移动过程中不碰撞其他物体") == "safety"
    assert constraint_kind("药瓶不滑落") == "safety"
    assert constraint_kind("移动过程中保持对药瓶的抓握") == "hold"
    assert constraint_kind("释放前保持药瓶竖直") == "hold"
    assert hold_category("保持抓握杯子") == "grasp"
    assert hold_category("保持托举纸箱") == "support"


def test_safety_constraint_is_not_reported_as_missing_hold():
    """安全类约束不该被当成“缺一条保持动作”——它由规划与力控保证。"""
    b = build([node("n1", "接近目标", [1], post=["手到达目标附近"],
                    invariants=["移动过程中不碰撞其他物体"], start=0.0, end=1.0)],
              [action(1, "右臂", "右臂向前伸出", "motion", 0.0, 1.0,
                      after="手到达目标附近")])
    hold = next(c for c in b["reasoning"]["checks"] if c["kind"] == "hold")
    assert hold["verdict"] == "delegated"
    assert b["program"]["operations"][0]["startable"] is None


def test_hold_constraint_without_cover_still_blocks():
    """真正的持续约束没人覆盖时，仍然要标出来（不能因为分类就放过）。"""
    b = build([node("n1", "搬运杯子", [1], invariants=["移动过程中保持对杯子的抓握"],
                    start=0.0, end=1.0)],
              [action(1, "右臂", "右臂抬起移动", "motion", 0.0, 1.0)])
    hold = next(c for c in b["reasoning"]["checks"] if c["kind"] == "hold")
    assert hold["verdict"] == "uncovered"
    assert b["program"]["operations"][0]["startable"] is False


# ---------------------------------------------------------------
# 保持节点提升 + 释放拆分
# ---------------------------------------------------------------

def test_cross_operation_hold_becomes_maintain_node():
    b = _grasp_then_place()
    ops = b["operations"]["nodes"]
    holds = [o for o in ops if o.get("mode") == "maintain"]
    assert len(holds) == 1
    h = holds[0]
    assert h["maintain_until"] == ["n3"]
    assert set(h["covers"]) == {"n2", "n3"}
    assert "保持" in h["name"] and not h["name"].startswith("右手")
    edge = next(e for e in b["operations"]["edges"]
                if e["from"] == h["id"] and e["relation"] == "maintain_until")
    assert edge["to"] == "n3"


def test_release_step_is_split_out_of_the_held_operation():
    """放置里的释放动作必须拆出去，否则保持与释放抢同一个执行器。"""
    b = _grasp_then_place()
    ops = {o["id"]: o for o in b["operations"]["nodes"]}
    release = next(o for o in ops.values() if o.get("split_from") == "n3")
    assert release["atomic_refs"] == [5]
    assert release["executors"] == ["右手"]
    # 剩下的那一段由臂完成：不再占终端执行器
    assert ops["n3"]["executors"] == ["右臂"]
    assert ops["n3"]["end"] == 6.0
    assert ops["n3"]["split_steps"] == [release["id"]]


def test_pose_hold_over_single_operation_is_lifted_with_handoff():
    """位姿保持只覆盖一个操作（而且是别个执行器的）时也要提升。

    这是同事图 A3_HOLD 的形态：手臂保持抓取位姿 ∥ 手指闭合建立抓握。保持的终点
    仍锚定被覆盖的操作（否则执行侧会与后继同执行器的操作互等），接管者单独记在
    handoff_to 上。
    """
    actions = [
        action(1, "右臂", "右臂向前伸出", "motion", 0.0, 1.0, after="手到达抓取位姿"),
        action(2, "右手", "右手手指收拢抓紧杯子", "transition", 1.0, 2.0,
               before="手指张开", after="右手抓握杯子", role="抓握"),
        action(3, "右臂", "右臂保持伸出", "maintain", 1.0, 2.0,
               before="保持伸出", after="保持伸出", role="稳定", inferred=True),
        action(4, "右臂", "右臂抬起移动", "motion", 2.0, 3.0, after="杯子到达目标位置"),
    ]
    actions[2]["until"] = {"type": "action_completed", "ref": 4,
                           "text": "直到右臂抬起移动"}
    nodes = [
        node("n1", "接近杯子", [1], start=0.0, end=1.0, post=["手到达抓取位姿"]),
        node("n2", "抓取杯子", [2], start=1.0, end=2.0, parts=["右手"]),
        node("n3", "搬运杯子", [4], start=2.0, end=3.0, parts=["右臂"]),
    ]
    b = build(nodes, actions)
    holds = [o for o in b["operations"]["nodes"] if o.get("mode") == "maintain"]
    assert len(holds) == 1, holds
    h = holds[0]
    assert h["executors"] == ["右臂"]
    assert h["covers"] == ["n2"]
    assert h["maintain_until"] == ["n2"]      # 终点锚定被覆盖操作：执行侧不互等
    assert h["handoff_to"] == ["n3"]          # 接管者单独记，供审查与展示
    assert h["maintain_until_mode"] == "handoff"
    edge = next(e for e in b["operations"]["edges"] if e["from"] == h["id"]
                and e["relation"] == "maintain_until")
    assert "接管" in edge["note"]


def test_support_hold_over_single_operation_stays_inside_its_operation():
    """托举/接触类保持与动作并发（抓取期间臂保持托举），是那一步的一部分，不提升。"""
    actions = [
        action(1, "右手", "右手手指收拢抓紧杯子", "transition", 1.0, 2.0,
               before="手指张开", after="右手抓握杯子", role="抓握"),
        action(2, "右臂", "右臂保持抬起托举", "maintain", 1.0, 2.0, role="托举"),
    ]
    nodes = [node("n1", "抓取杯子", [1, 2], start=1.0, end=2.0, parts=["右手"])]
    b = build(nodes, actions)
    holds = [o for o in b["operations"]["nodes"] if o.get("mode") == "maintain"]
    assert holds == []


def test_object_state_hold_is_not_self_hold():
    """保持的宾语是执行器自己，还是物体在世界中的位置——判据本身。"""
    assert is_self_hold("右臂保持位置")
    assert is_self_hold("右臂保持伸出")
    assert is_self_hold("右臂保持抬起托举")
    assert is_self_hold("右手保持抓握燕麦杯")
    assert not is_self_hold("右臂保持燕麦杯在桌面近处位置")
    assert not is_self_hold("右臂保持杯子的位置")


def test_object_state_hold_stays_inside_its_operation_and_release_still_splits():
    """“右臂保持燕麦杯在桌面近处位置”不提升，放置里才留得下“手臂那一段”。

    它维持的是物体在世界中的位置，手臂只是停在原地等释放——不以操作为目的（用户口径）。
    若把它提升成 MAINTAIN 节点，放置操作里就只剩“手指张开释放”一条动作，拆分的
    “释放之外还有别的东西”条件不成立，于是既拆不出释放节点，又让保持与释放抢同
    一个执行器（燕麦杯案例踩过的坑）。
    """
    actions = [
        action(1, "右手", "右手手指收拢抓紧杯子", "transition", 1.0, 2.0,
               before="手指张开", after="右手抓握杯子", role="抓握"),
        action(2, "右手", "右手保持抓握杯子", "maintain", 2.0, 6.0,
               before="右手已建立抓握", after="右手松开杯子", role="抓握"),
        action(3, "右臂", "右臂抬起并移动", "motion", 2.0, 5.0,
               before="手臂静止", after="杯子到达目标位置", role="托举"),
        action(4, "右臂", "右臂保持杯子在桌面近处位置", "maintain", 5.0, 6.0,
               before="右臂处于近处位置", after="右臂处于近处位置", role="稳定"),
        action(5, "右手", "右手手指张开释放杯子", "transition", 6.0, 7.0,
               before="右手抓握杯子", after="手指张开不再接触杯子", role="抓握"),
    ]
    nodes = [
        node("n1", "抓取杯子", [1], pre=["杯子位于桌面上"], post=["右手抓握杯子"],
             start=1.0, end=2.0),
        node("n2", "搬运杯子", [3], pre=["右手抓握杯子"], post=["杯子到达目标位置"],
             start=2.0, end=5.0, invariants=["搬运过程中保持对杯子的抓握"]),
        node("n3", "放置杯子", [4, 5], pre=["杯子到达目标位置"], post=["杯子落在支撑面上"],
             start=5.0, end=7.0, invariants=["释放前保持杯子在目标位置"]),
    ]
    b = build(nodes, actions)
    ops = {o["id"]: o for o in b["operations"]["nodes"]}
    assert [o["name"] for o in ops.values() if o.get("mode") == "maintain"] == ["保持抓握杯子"]
    rel = next(o for o in ops.values() if o.get("split_from") == "n3")
    assert rel["executors"] == ["右手"]
    assert ops["n3"]["executors"] == ["右臂"]       # 剩下的那一段由臂完成
    assert ops["n3"]["end"] == 6.0
    assert ops["n3"]["atomic_refs"] == [4]


def test_inferred_transition_step_is_lifted_as_operation():
    """先验补的瞬时步骤（预张开）提升为独立操作，并写清它是后继的必要前提。"""
    actions = [
        action(1, "右手", "右手张开手指至可抓取开度", "transition", 1.0, 2.0,
               before="手未处于张开状态", after="手指张开至可抓取开度", inferred=True),
        action(2, "右手", "右手手指收拢抓紧杯子", "transition", 2.0, 3.0,
               before="手指张开", after="右手抓握杯子", role="抓握"),
    ]
    nodes = [node("n1", "抓取杯子", [2], start=2.0, end=3.0, parts=["右手"])]
    b = build(nodes, actions)
    ops = b["operations"]["nodes"]
    step = [o for o in ops if str(o["id"]).startswith("step_")]
    assert len(step) == 1, ops
    s = step[0]
    assert s["name"] == "张开手指至可抓取开度"      # 节点名不带执行器前缀
    assert s["required_capabilities"] == ["手部预张开"]
    assert s["prepares"] == ["n1"]
    edge = next(e for e in b["operations"]["edges"]
                if e["from"] == s["id"] and e["to"] == "n1")
    assert "必要前提" in edge["note"]
    grip = next(o for o in ops if o["id"] == "n1")
    assert grip["pre_inferred"] and "必要前提" in grip["pre_inferred"][0]


def test_contract_reports_maintain_target_resource_conflict():
    """保持终点和目标抢同一执行器时，校验器要说出来。"""
    bundle = {
        "operations": {"nodes": [{"id": "h1", "name": "保持抓握", "mode": "maintain",
                                  "maintain_until": ["a1"], "covers": ["a1"]}],
                       "edges": []},
        "contract": {"nodes": {
            "H1": {"name": "MaintainGrasp", "subject": "RightGripper", "mode": "MAINTAIN",
                   "maintain_until": ["A1"], "pre": [], "constraints": [], "evaluator": [],
                   "post": [], "implementation": ["PositionHold"], "dependencies": ["A1"],
                   "object": "TargetObject"},
            "A1": {"name": "PlaceTarget", "subject": "RightGripper", "mode": "NORMAL",
                   "pre": [], "constraints": [], "evaluator": [], "post": [],
                   "implementation": ["LinearPlace"], "dependencies": [],
                   "object": "TargetObject"},
        }},
    }
    check = s06_validate._check_contract_schema(bundle)
    assert check["status"] == "warn"
    assert any("同一个执行器" in i["message"] for i in check["detail"])


# ---------------------------------------------------------------
# 谓词化
# ---------------------------------------------------------------

def test_predicate_ids_are_stable_and_reuse_same_text():
    t = predicates.PredicateTable()
    a = t.add("右手抓握白色药瓶", "n1", "post")
    b = t.add("右手抓握白色药瓶", "n2", "pre")
    c = t.add("左手抓握白色药瓶", "n3", "post")
    assert a == b                                     # 同一文本同一个谓词
    assert a != c                                     # 不同文本不合并
    assert t.export()["by_text"]["右手抓握白色药瓶"] == a


def test_predicate_names_follow_execution_vocabulary():
    t = predicates.PredicateTable()
    assert t.add("移动过程中不碰撞其他物体") == "CollisionFree"
    assert t.add("药瓶不滑落") == "NoSlip"
    assert t.add("移动过程中保持对药瓶的抓握").startswith("GraspMaintained")
    assert t.add("释放前保持药瓶竖直") == "PoseHeld"


def test_hold_event_prefix_does_not_change_predicate():
    t = predicates.PredicateTable()
    plain = t.add("右手松开杯子")
    with_prefix = t.add("直到右手松开杯子")
    assert plain != with_prefix
    item = next(p for p in t.items if p["text"] == "直到右手松开杯子")
    assert item["prefix"] == "直到" and item["verb"] == "GraspReleased"


# ---------------------------------------------------------------
# 契约导出
# ---------------------------------------------------------------

def test_contract_alignment_with_execution_schema():
    b = _grasp_then_place()
    c = contract.build_contract(b)
    assert c["start_node"] == "START" and c["end_node"] == "END"
    required = {"name", "subject", "object", "pre", "constraints", "evaluator",
                "post", "implementation", "dependencies"}
    for nid, n in c["nodes"].items():
        assert required <= set(n), f"{nid} 缺字段"
        assert n["implementation"], f"{nid} 没有候选方式集合"
    # 执行器名对齐执行侧：臂 → RightArm，手 → 终端执行器
    assert c["nodes"]["A1"]["subject"] == "RightGripper"
    assert c["nodes"]["A3"]["subject"] == "RightArm"
    # 依赖不含保持节点（保持靠 maintain_until 表达）
    assert c["nodes"]["A2"]["dependencies"] == ["A1"]
    policy = contract.build_policy(c)
    for nid, impl in policy["implementations"].items():
        if nid in c["nodes"]:
            assert impl in c["nodes"][nid]["implementation"]


def test_contract_keeps_original_condition_text():
    b = _grasp_then_place()
    c = contract.build_contract(b)
    n2 = c["nodes"]["A2"]
    assert n2["x-video2op"]["pre_text"] == ["右手抓握杯子"]
    table = b["predicates"]["by_text"]
    for pid in n2["pre"]:
        assert any(p["id"] == pid and p["text"] for p in b["predicates"]["predicates"])
    assert "右手抓握杯子" in table


def test_exported_contract_passes_its_own_schema_check():
    b = _grasp_then_place()
    check = s06_validate._check_contract_schema(b)
    assert check["status"] == "pass", check["detail"]


def test_end_node_waits_for_a_condition_this_graph_produces():
    """END 的前置条件必须由图内某个节点产生，不能照搬别人图里的终点状态。

    照搬的后果不是“报错”，而是跑到 max_ticks 也结束不了（我们真实踩过）。
    """
    b = _grasp_then_place()
    c = b["contract"]
    produced = {p for nid, n in c["nodes"].items()
                if nid not in (c["start_node"], c["end_node"])
                for p in (n.get("post") or [])}
    for cond in c["nodes"][c["end_node"]]["pre"]:
        assert cond == "OperationEndTriggered" or cond in produced


def test_end_with_foreign_condition_is_reported():
    bundle = {"contract": {
        "start_node": "START", "end_node": "END",
        "nodes": {
            "START": {"name": "BeginOperation", "subject": "OperationSystem",
                      "object": "TaskTarget", "pre": [], "constraints": [], "evaluator": [],
                      "post": ["OperationStarted"], "implementation": ["BeginOperation"],
                      "dependencies": []},
            "A1": {"name": "PlaceTarget", "subject": "RightArm", "object": "TaskTarget",
                   "pre": [], "constraints": [], "evaluator": [],
                   "post": ["PlacedOn_Target"], "implementation": ["LinearPlace"],
                   "dependencies": ["START"]},
            "END": {"name": "EndOperation", "subject": "OperationSystem",
                    "object": "TaskTarget",
                    "pre": ["OperationEndTriggered", "PlacementCompleted"],  # ← 图里没人产生它
                    "constraints": [], "evaluator": [], "post": ["OperationStopped"],
                    "implementation": ["EndOperation"], "dependencies": ["A1"]}}}}
    check = s06_validate._check_contract_schema(bundle)
    assert check["status"] == "warn"
    assert any("永远等不到" in i["message"] for i in check["detail"])


def test_contract_handoff_field_types():
    """导出物要能被执行侧加载器接受：首尾节点成对、字段类型都是字符串列表。"""
    b = _grasp_then_place()
    check = s06_validate._check_installed_peer(b)
    assert check["status"] == "pass", check["detail"]


# ---------------------------------------------------------------
# 子操作展开
# ---------------------------------------------------------------

def test_expansion_marks_hold_covers_instead_of_parallel():
    """“保持”盖住另一个动作时写成 hold_covers，而不是普通的并行。"""
    b = _grasp_then_place()
    ex = expand.build(b)
    item = ex["by_operation"]["n1"]
    rels = {(r["from"], r["to"]): r["relation"] for r in item["relations"]}
    assert any(v == "hold_covers" for v in rels.values()) or len(item["sub_operations"]) < 2
    # 搬运那一步：保持抬起托举盖住移动
    move = ex["by_operation"]["n2"]
    kinds = {s["kind"] for s in move["sub_operations"]}
    if "hold" in kinds and "motion" in kinds:
        assert any(r["relation"] == "hold_covers" for r in move["relations"])
    # 检查点：建立型要有验证、保持型要有持续监测
    check_kinds = {c["kind"] for c in item["checkpoints"]}
    assert "state_check" in check_kinds


def test_expansion_references_existing_atomic_actions():
    b = _grasp_then_place()
    ex = expand.build(b)
    known = {a["id"] for a in b["atomic"]["atomic_actions"]}
    for item in ex["operations"]:
        for s in item["sub_operations"]:
            assert s["atomic_ref"] in known
            assert s["id"].startswith(item["id"] + ".")


def test_expansion_check_passes_on_generated_bundle():
    b = _grasp_then_place()
    check = s06_validate._check_expansion(b)
    assert check["status"] == "pass", check["detail"]


# ---------------------------------------------------------------
# 图自身仍然自洽
# ---------------------------------------------------------------

def test_operation_graph_stays_acyclic_after_lifting_and_splitting():
    b = _grasp_then_place()
    edges = b["operations"]["edges"]
    deps = {}
    for e in edges:
        if e.get("mutual"):
            continue
        deps.setdefault(e["to"], set()).add(e["from"])
    seen, stack = set(), set()

    def walk(nid):
        if nid in stack:
            raise AssertionError(f"成环：{nid}")
        if nid in seen:
            return
        stack.add(nid)
        for p in deps.get(nid, ()):
            walk(p)
        stack.discard(nid)
        seen.add(nid)

    for nid in list(deps):
        walk(nid)


def test_rebuild_is_idempotent():
    b = _grasp_then_place()
    first = {o["id"]: dict(o) for o in b["operations"]["nodes"]}
    build_operation_graph(b)
    second = {o["id"]: dict(o) for o in b["operations"]["nodes"]}
    assert first.keys() == second.keys()
    for k in first:
        assert first[k]["atomic_refs"] == second[k]["atomic_refs"]
        assert first[k]["name"] == second[k]["name"]


def test_orphan_maintain_is_adopted_by_the_step_it_covers():
    """先验补出的保持动作没被任何操作认领时，按重叠时长归属，避免“图上看不见”。"""
    actions = [action(2, "右臂", "右臂抬起移动", "motion", 0.0, 3.0),
               action(9, "右臂", "右臂保持伸出", "maintain", 0.0, 3.0, inferred=True)]
    b = build([node("n1", "搬运杯子", [2], start=0.0, end=3.0)], actions)
    op = b["operations"]["nodes"][0]
    assert 9 in op["atomic_refs"]
