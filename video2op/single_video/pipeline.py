#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频学习：观察证据 → 受控任务动作 → 语义七元组图。
新结果写 output/<视频名>_semantic_v3/，主交付为 result.json、operations.svg、workbench.html 和 clip/sequence.json。
不生成执行程序、保持节点或执行策略。build_legacy_execution_graph 只供旧执行契约回归使用。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import (
    __version__,
    config,
    contract,
    expand,
    gates,
    graph,
    ignored_parts,
    local_review,
    logic,
    media,
    operations,
    predicates,
    program,
    reasoning,
    sampling,
    semantic,
)
from ..contracts.learning_contracts import task_contract
from ..llm import VLMClient
from .stages import (
    s01_viewpoint,
    s02a_intent,
    s02b_atomic,
    s02b_merge,
    s02c_task,
    s02d_link,
    s03_sync,
    s04_conditions,
    s05_rules,
    s07_purify,
    s08_scope,
)

_TOKEN_RE = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _path_tokens(path: str) -> list:
    out: list = []
    for m in _TOKEN_RE.finditer(path):
        out.append(m.group(1) if m.group(1) is not None else int(m.group(2)))
    return out


def set_by_path(root: object, path: str, value: object) -> bool:
    """按 "a.b[0].c" 形式的路径写回（失败返回 False，不抛异常）。"""
    try:
        tokens = _path_tokens(path)
        cur = root
        for tok in tokens[:-1]:
            cur = cur[tok]  # type: ignore[index]
        if isinstance(cur, dict) and isinstance(tokens[-1], str):
            if tokens[-1] not in cur:
                return False
            cur[tokens[-1]] = value
            return True
        if isinstance(cur, list) and isinstance(tokens[-1], int):
            cur[tokens[-1]] = value
            return True
    except Exception:
        return False
    return False


def _dump(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def absorb_actions(ctx: dict, new_actions: list[dict]) -> int:
    """把推理/先验补全的动作并入总表（排序 → 状态补全 → 保持缝合 → 重建关系）。

    pipeline（在线）与 tools/render_case.py（离线重算）共用这一条路径，
    保证"并入新动作"的行为只有一处实现。
    """
    new_actions = [dict(m) for m in (new_actions or []) if not semantic.is_hold(m)]
    if not new_actions:
        return 0
    actions = list(ctx["atomic"]["atomic_actions"]) + new_actions
    actions.sort(key=lambda a: (float(a.get("start", 0)), float(a.get("end", 0)),
                                int(a.get("id", 0))))
    actions = s02b_merge.fill_states(actions)
    ctx["atomic"]["atomic_actions"] = actions
    rels = s02b_merge.add_boundary_relations(actions, ctx["relations"])
    rels = s02b_merge.apply_alternations(actions, rels)
    ctx["atomic"]["temporal_relations"] = rels
    ctx["relations"] = rels
    return len(new_actions)


def build_legacy_execution_graph(bundle: dict) -> None:
    """（重）建操作图与执行器语义程序（幂等）。

    pipeline（在线）与 tools/render_case.py（离线重算）共用：操作图是从 task_nodes
    与已定稿的动作表推出来的确定性产物，不调用模型；文本被净化改写后重跑一次即可。
    """
    # 不参与操作的部位（头 / 颈 / 口）内容净化：条件 / 约束 / 评价 / 世界状态里的
    # “保持视线”“张开嘴”这类表述对操作没有作用，建图前先确定性去掉
    # （在线与离线重建共用这条路径）
    from ..abstraction import validate_bundle
    validate_bundle(bundle)
    bundle["ignored_parts"] = ignored_parts.purge(bundle)
    bundle["operations"] = operations.build(
        bundle.get("task_nodes") or {},
        (bundle.get("atomic") or {}).get("atomic_actions") or [],
        bundle.get("relations") or [])
    # 推理修正：逐条追问"这个条件真的成立吗"，并把结论写回图（边降级 / 候选缺口）
    bundle["reasoning"] = reasoning.audit(bundle)
    # 子操作展开：每个操作展开成可调度的执行单元 + 关系 + 检查点
    bundle["expansion"] = expand.build(bundle)
    # 谓词化：给图上每条条件一个稳定名字（不改写原文，不放松任何一格证据纪律）
    bundle["predicates"] = predicates.build(bundle)
    # 门控：把"前序效果 ∧ 下一前置 ∧ 持续约束"写成可判定 T/F/U 的换挡点
    # （只读上面已经写好的证据：effect_evidence / pre_coverage / hold / 谓词表）
    bundle["gates"] = gates.build(bundle)
    bundle["program"] = program.build(bundle)
    # 可执行契约：对齐执行侧语义图 schema 的导出（带证据，不猜参数）
    bundle["contract"] = contract.build_contract(bundle)
    bundle["execution_policy"] = contract.build_policy(bundle["contract"])


def build_learning_graph(bundle: dict) -> None:
    """Single-actor semantic nodes, logical parallel branches, event-scoped grip."""
    from copy import deepcopy

    from .. import arm_hand, grasp_preparation, single_actor
    from ..abstraction import validate_bundle
    bundle["learning_layer"] = "semantic"
    if bundle.get("single_actor_version") and bundle.get("task_nodes_source"):
        bundle["task_nodes"] = deepcopy(bundle["task_nodes_source"])
    from .. import learning_alignment, temporal_learning
    learning_alignment.apply_intent_updates(bundle)
    from ..media_quality import annotate as annotate_media
    annotate_media(bundle)
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
    bundle["learning_alignment"] = learning_alignment.align(bundle, spec["task_nodes"])
    bundle["temporal_knowledge"] = temporal_learning.build(bundle, spec)
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
    bundle["operation_abstraction_version"] = "4.1"
    for key in ("program", "contract", "execution_policy", "expansion"):
        bundle.pop(key, None)


def build_operation_graph(bundle: dict) -> None:
    """Public builder: learning output is always a semantic graph."""
    build_learning_graph(bundle)


def run_observation_branches(stage, client, ctx):
    """Independent clients permit actual parallel inference without shared sessions/stat counters."""
    from concurrent.futures import ThreadPoolExecutor
    branches = [(s02a_intent, "s02a_intent", "intents", {"intents": []}),
                (s02b_atomic, "s02b_atomic", "windows", {"windows": []})]
    clients = [VLMClient(client.cache_dir, base_url=client.base_url,
                         model=client.model, use_cache=client.use_cache) for _ in branches]
    errors = []
    try:
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-observation") as pool:
            futures = [pool.submit(stage, name,
                       lambda module=module, child=child: module.run(child, ctx), key, default)
                       for (module, name, key, default), child in zip(branches, clients, strict=True)]
            for future in futures:
                try:
                    future.result()
                except Exception as exc:
                    errors.append(exc)
    finally:
        for child in clients:
            for key in ("calls", "cache_hits", "failures", "seconds"):
                client.stats[key] += child.stats[key]
            client.stats["attempts"].extend(child.stats["attempts"])
            child.session.close()
    if errors:
        raise errors[0]


def run_case(video: Path, force: bool = False, verbose: bool = True, description: str | None = None, export_clips: bool = True, clip_padding: float = .25, graph_requirements: dict | None = None) -> dict:
    """从源视频生成一个案例并返回写入 result.json 的字典。

    description 与 graph_requirements 随本批次的任务声明传递。
    force 控制模型缓存，export_clips 和 clip_padding 控制导出片段。
    返回值包含 atomic、operations、case_graph 和 validation，供批次入口使用。
    """
    t_start = time.time()
    video = Path(video).resolve()
    if not video.exists():
        raise FileNotFoundError(f"视频不存在：{video}")

    meta = media.probe(video)
    from ..media_quality import audit as audit_media
    meta["media_quality"] = audit_media(video)
    out_dir = config.OUTPUT_DIR / (meta["name"] + "_semantic_v3")
    stages_dir = out_dir / "stages"
    stages_dir.mkdir(parents=True, exist_ok=True)
    if force:
        print("  [force] 绕过模型缓存读取（保留已有缓存文件）")

    if verbose:
        print(f"\n=== 案例 {meta['name']} ===")
        print(f"  时长 {meta['duration']}s · {meta['width']}x{meta['height']} @{meta['fps']}fps")
    profile = media.motion_profile(video)
    if verbose:
        print(f"  客观运动证据：变化点 {len(profile['change_points'])} 个，"
              f"高活动段 {len(profile['hot_segments'])} 段")

    preprocessing_seconds = round(time.time() - t_start, 3)
    client = VLMClient(out_dir / "cache", use_cache=not force)
    ctx: dict = {
        "video": video,
        "meta": meta,
        "profile": profile,
        "out_dir": out_dir,
        "video_id": media.file_sha1(video)[:16],
    }
    declared = description or ""
    if graph_requirements and graph_requirements.get("task_policy"):
        declared += "\n显式任务政策（不是观察事实）：" + json.dumps(graph_requirements["task_policy"], ensure_ascii=False)
    if declared:
        ctx["text_description"] = {"text": declared, "provenance": "text_description",
                                   "role": "provided_context_not_observed_success"}
    _dump(stages_dir / "s00_probe.json", {"meta": meta, "profile": profile})

    errors: list[str] = []
    timings: dict[str, float] = {"preprocess": preprocessing_seconds}

    def stage(name: str, fn, key: str, default):
        t0 = time.time()
        if verbose:
            print(f"  → {name}")
        try:
            result = fn()
            if result is None:
                result = default
            ctx[key] = result
            _dump(stages_dir / f"{name}.json", result)
        except Exception as e:
            msg = f"{name}: {type(e).__name__}: {e}"
            errors.append(msg)
            print(f"  [错误] {msg}")
            ctx[key] = default
            timings[name] = round(time.time() - t0, 3)
            _dump(out_dir / "failure.json", {
                "failed_stage": name, "error": msg,
                "stage_seconds": timings, "llm_stats": client.stats,
                "wall_seconds": round(time.time() - t_start, 3)})
            raise
        timings[name] = round(time.time() - t0, 3)

    stage("s00_state_frames", lambda: sampling.prepare(ctx), "sampling", {})
    stage("s01_viewpoint", lambda: s01_viewpoint.run(client, ctx), "viewpoint", {})
    t_branches = time.time()
    run_observation_branches(stage, client, ctx)
    timings["independent_branches_wall"] = round(time.time() - t_branches, 3)

    # 跨窗口合并（确定性）
    t0 = time.time()
    if ctx.get("windows", {}).get("windows"):
        merged = s02b_merge.run(ctx["windows"]["windows"], meta["duration"])
    else:
        merged = {"atomic_actions": [], "temporal_relations": [], "conflicts": [],
                  "inactive_parts": [], "unclear": "", "stats": {}}
    ctx["atomic"] = {
        "atomic_actions": merged["atomic_actions"],
        "temporal_relations": merged["temporal_relations"],
        "conflicts": merged["conflicts"],
        "inactive_parts": merged["inactive_parts"],
        "unclear": merged["unclear"],
        "stats": merged["stats"],
    }
    ctx["relations"] = merged["temporal_relations"]
    semantic.normalize_observations(ctx)
    _dump(stages_dir / "s02b_before_review.json", {"atomic": ctx["atomic"], "relations": ctx["relations"]})
    stage("s02r_local_review", lambda: local_review.run(client, ctx), "local_review", {})
    _dump(stages_dir / "s02b_after_review.json", {"atomic": ctx["atomic"], "relations": ctx["relations"]})
    from .. import arm_hand, grasp_preparation
    grasp_preparation.annotate(ctx)
    arm_hand.annotate(ctx)
    _dump(stages_dir / "s02b_merge.json", ctx["atomic"])
    timings["s02b_merge"] = round(time.time() - t0, 1)
    if verbose:
        print(f"  → 合并：原始 {merged['stats'].get('raw_actions')} 条 → 去重后 "
              f"{merged['stats'].get('merged_actions')} 条动作，{len(ctx['relations'])} 条时序关系")

    from ..media_quality import annotate as annotate_media
    annotate_media(ctx)
    # Freeze only the independent observation branch before intent alignment or
    # s02c logical projections. Inferred/missing actions are never observation facts.
    from copy import deepcopy
    actual = [deepcopy(a) for a in ctx["atomic"]["atomic_actions"] if not a.get("inferred")]
    actual_ids = {a["id"] for a in actual}
    ctx["observed_operation_graph"] = {
        "schema_version": "observed_operation_graph.v1",
        "origin": "s02b_atomic_and_local_review_before_intent_alignment",
        "nodes": actual,
        "relations": [deepcopy(r) for r in ctx.get("relations", [])
                      if r["from"] in actual_ids and r["to"] in actual_ids],
        "policy": "Observed model records; excludes inferred actions and later logical projections.",
    }
    _dump(stages_dir / "s02_observed_operation_graph.json", ctx["observed_operation_graph"])
    stage("s02c_task", lambda: s02c_task.run(client, ctx), "task_nodes", {"task_nodes": []})
    stage("s02d_link", lambda: s02d_link.run(client, ctx), "link", {"links": [], "missing_actions": []})

    # 把推理补全的动作并入总表，并补上它们与既有动作的关系
    missing = ctx.get("link", {}).get("missing_actions") or []
    if absorb_actions(ctx, missing):
        _dump(stages_dir / "s02d_link_merged.json",
              {"atomic_actions": ctx["atomic"]["atomic_actions"],
               "temporal_relations": ctx["relations"]})
        if verbose:
            print(f"  → 补全 {len(missing)} 条推理动作，"
                  f"动作总数 {len(ctx['atomic']['atomic_actions'])}")

    # 持续状态作为约束，禁止先验补保持动作或用保持填补时间轴。
    semantic.normalize_observations(ctx)
    from .. import arm_hand, grasp_preparation
    grasp_preparation.annotate(ctx)
    arm_hand.annotate(ctx)

    stage("s03_sync", lambda: s03_sync.run(client, ctx), "sync", {})
    from ..learning_alignment import apply_intent_updates
    apply_intent_updates(ctx)
    stage("s04_conditions", lambda: s04_conditions.run(client, ctx), "conditions", {})
    stage("s05_rules", lambda: s05_rules.run(client, ctx), "rules", {})
    if (ctx.get("intents") or {}).get("intents"):
        stage("s08_scope", lambda: s08_scope.run(client, ctx), "semantic_scope", {})

    bundle = {
        "schema_version": "1.0",
        "task_contract": task_contract(graph_requirements, description),
        "operation_abstraction_version": "2.0",
        "code_version": __version__,
        "meta": meta,
        "viewpoint": ctx.get("viewpoint") or {},
        "intents": ctx.get("intents") or {"intents": []},
        "sampling": ctx.get("sampling") or {},
        "local_review": ctx.get("local_review") or {},
        "atomic": ctx.get("atomic") or {},
        "observed_operation_graph": ctx.get("observed_operation_graph") or {},
        "relations": ctx.get("relations") or [],
        "task_nodes": ctx.get("task_nodes") or {"task_nodes": []},
        "link": ctx.get("link") or {},
        "sync": ctx.get("sync") or {},
        "semantic_scope": ctx.get("semantic_scope") or {},
        "intent_alignment": ctx.get("intent_alignment") or {},
        "conditions": ctx.get("conditions") or {},
        "rules": ctx.get("rules") or {},
        "errors": errors,
        "pipeline": {
            "code_version": __version__,
            "model": config.MODEL,
            "base_url": config.BASE_URL,
            "wall_seconds": round(time.time() - t_start, 1),
            "stage_seconds": timings,
            "llm_stats": client.stats,
        },
    }
    # 操作图 + 执行器语义程序：在参数净化之前先建一次，校验器才能检查它们；
    # 净化改写文本后重建一次（见下），保证图与定稿文本一致。
    # 建图入口会先做头部内容净化（headfree.purge），所以时序逻辑表达要在其后派生，
    # 才能保证“动作文本 → 视图”这条链上不带头部内容。
    t_build = time.time()
    build_learning_graph(bundle)
    bundle["temporal_logic"] = logic.build(bundle["atomic"].get("atomic_actions", []),
                                           bundle.get("relations") or [])
    bundle["validation"] = semantic.validate(bundle)

    # 参数净化：若发现"具体数值参数"，交给模型改写成定性表述后重新校验
    param_check = next((c for c in bundle["validation"].get("checks", [])
                        if c.get("id") == "param_discipline"), None)
    if param_check and param_check.get("status") != "pass":
        stage("s07_purify", lambda: s07_purify.run(client, ctx, param_check.get("detail") or []),
              "purify", {"rewrites": []})
        applied = 0
        for r in (ctx.get("purify") or {}).get("rewrites", []):
            if set_by_path(bundle, r["path"], r["new_text"]):
                applied += 1
        bundle["purify"] = {"applied": applied,
                            "rewrites": (ctx.get("purify") or {}).get("rewrites", [])}
        if applied:
            build_learning_graph(bundle)
            bundle["validation"] = semantic.validate(bundle)
            _dump(out_dir / "result.json", bundle)
            if verbose:
                print(f"  → 参数净化：改写 {applied} 条，重新校验：{bundle['validation']['summary']}")

    # 执行器级动作依赖图（DAG，追溯视图）：在文本净化完成后建图，保证节点文本与产物一致
    if declared:
        bundle["text_description"] = ctx["text_description"]
    bundle["graph"] = graph.build(bundle["atomic"].get("atomic_actions", []),
                                  bundle.get("relations") or [])
    _dump(out_dir / "result.json", bundle)

    timings["build_validate"] = round(time.time() - t_build, 3)
    t_render = time.time()
    from ..knowledge import video_identity
    bundle["source_video_sha256"], _ = video_identity(bundle)
    from . import case_graph
    stage("s09_case_graph", lambda: case_graph.learn(client, bundle, graph_requirements), "case_graph", {})
    bundle["case_graph"] = ctx["case_graph"]
    semantic.export(bundle, out_dir, export_clips=export_clips, clip_padding=clip_padding)
    semantic.render(bundle, out_dir)

    timings["render_export"] = round(time.time() - t_render, 3)
    bundle["pipeline"]["wall_seconds"] = round(time.time() - t_start, 3)
    _dump(out_dir / "result.json", bundle)
    _dump(out_dir / "performance.json", bundle["pipeline"])
    if verbose:
        print(f"  完成：{bundle['validation']['summary']}")
        ops_stats = (bundle.get("operations") or {}).get("stats") or {}
        print(f"  操作图：{ops_stats.get('nodes', 0)} 个操作 · "
              f"顺序 {ops_stats.get('sequence', 0)} · 并行 {ops_stats.get('parallel', 0)} · "
              f"交替 {ops_stats.get('alternation', 0)} · 执行器 {ops_stats.get('executors', 0)} 个")
        stats = (bundle.get("gates") or {}).get("stats") or {}
        if stats:
            print(f"  门控：{stats.get('gates', 0)} 个（T {stats.get('T', 0)} · "
                  f"U {stats.get('U', 0)} · F {stats.get('F', 0)}）· "
                  f"待确认条件 {stats.get('unresolved', 0)} 条")
        print(f"  产物：{out_dir}/result.json · operations.svg（语义七元组）· workbench.html（可交互工作台）· "
              f"skill_instances.json · clip/sequence.json · G_case.json · G_case.svg"
              f"（用时 {bundle['pipeline']['wall_seconds']}s）")
    return bundle


def run_all(force: bool = False, description: str | None = None, export_clips: bool = True, clip_padding: float = .25, graph_requirements: dict | None = None) -> list[dict]:
    videos = sorted(p for p in config.DATA_DIR.glob("*.mp4"))
    if not videos:
        print(f"data/ 下没有 mp4：{config.DATA_DIR}")
        return []
    out = []
    for v in videos:
        out.append(run_case(v, force=force, export_clips=export_clips, clip_padding=clip_padding, graph_requirements=graph_requirements, **({"description": description} if description is not None else {})))
    if out:
        from ..knowledge import aggregate, extract, render
        knowledge = aggregate([extract(b, str(config.OUTPUT_DIR / (b["meta"]["name"] + "_semantic_v3") / "result.json")) for b in out])
        destination = config.OUTPUT_DIR / "goal_effect_knowledge"
        destination.mkdir(parents=True, exist_ok=True)
        _dump(destination / "knowledge.json", knowledge)
        (destination / "review.html").write_text(render(knowledge), encoding="utf-8")
        from ..cross_video_delivery import export as export_cross_video
        export_cross_video(knowledge, destination)
        from ..learning_tracks import split
        from ..two_track_delivery import export as export_tracks
        tracks=[split(b,str(config.OUTPUT_DIR/(b["meta"]["name"]+"_semantic_v3")/"result.json")) for b in out]
        export_tracks(tracks,destination/"learning_tracks",export_clips=export_clips)
    return out
