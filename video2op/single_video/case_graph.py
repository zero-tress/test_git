"""Qwen-produced, evidence-linked semantic skill instances for one saved video.

This module validates, traces and renders model conclusions; it never assigns
skill meaning, effects, conditions or outcomes through host-side heuristics.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

SCHEMA_VERSION = "case_graph.v1"
FIELDS = ("X", "O", "C_pre", "C_const", "E", "C_post", "R")
OUTCOMES = {"success", "failure", "not_executed", "unknown"}
RELATIONS = {"sequence", "parallel", "alternation", "branch", "synchronization", "maintain_until"}
OPERATION_RELATIONS = {"parallel", "maintain_until", "alternation", "branch", "synchronization"}
BASES = {"observed_order", "observed_overlap", "declared_rule", "inferred_dependency",
         "candidate_parallelism", "supported_semantic_dependency"}

from ..contracts.learning_contracts import CASE_SYSTEM as SYSTEM
from ..contracts.learning_contracts import CONTRACT_VERSION, graph_records, policy_prompt, validate_observed_relation
from ..presentation.case_graph_render import (
    _draw_flow as _draw_flow,
)
from ..presentation.case_graph_render import (
    _operation_flow as _operation_flow,
)
from ..presentation.case_graph_render import (
    _svg_text_lines as _svg_text_lines,
)
from ..presentation.case_graph_render import (
    _svg_text_width as _svg_text_width,
)
from ..presentation.case_graph_render import (
    svg as svg,
)
from .case_scope_review import learn_scope, validate_retained_operations


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _intent_ids(payload):
    found = set()
    for item in payload.get("intents", []):
        found.add(item.get("id"))
        found.update(_intent_ids({"intents": item.get("subtasks", [])}))
    return found - {None}


def _precedence_roots(nodes, relations):
    ids = {n["id"] for n in nodes}
    targets = {r.get("to") for r in relations
               if r.get("relation") in {"sequence", "branch"} and r.get("to") in ids}
    return [n["id"] for n in nodes if n["id"] not in targets]


def _require_policy_shape(payload, requirements):
    """Enforce the explicit single-video task policy; never invent semantics."""
    if not requirements:
        return
    nodes = payload.get("nodes") or []
    relations = payload.get("relations") or []
    single = requirements.get("single_video") or {}
    task = requirements.get("task_policy") or {}

    forbidden = set(task.get("forbidden_roles") or [])
    if forbidden:
        offenders = [n["id"] for n in nodes if n.get("role") in forbidden]
        if offenders:
            raise ValueError(
                f"任务范围 policy 禁止这些角色 {sorted(forbidden)}（{task.get('forbidden_reason') or ''}）；"
                f"违规节点={offenders}；请改为写在 unresolved 说明它超出任务范围")

    role = single.get("start_role") or (requirements.get("entry_policy") or {}).get("start_successor_role")
    if role:
        roles = {"approach", "approach_target"} if role == "approach" else {role}
        roots = set(_precedence_roots(nodes, relations))
        approaches = [n for n in nodes if n.get("role") in roles]
        if not approaches:
            raise ValueError(f"任务链起点应为 role={role} 的靠近技能；请为相应节点补 role 字段")
        root_approaches = [n for n in approaches if n["id"] in roots]
        if not root_approaches:
            raise ValueError(
                f"任务链的第一个技能应为 role={role} 的靠近；当前起点是 {sorted(roots)}")
        observed_root = [n for n in root_approaches if n.get("occurrence") != "rule_only"]
        if (single.get("add_approach_when_unobserved")
                and not observed_root
                and not any(n.get("occurrence") == "rule_only" for n in root_approaches)):
            # 允许模型自己决定要不要补；但若它把清障之类放在起点又不补靠近，就是漏了起点。
            raise ValueError(
                "观察里没有作为起点的靠近段时，请补一个 occurrence=rule_only、role=approach、"
                "name=靠近 的节点，并写明模型未识别到独立原子动作段")

    if single.get("chain") == "linear":
        kinds = {"sequence", "maintain_until"}
        branching = [rel for rel in relations if rel.get("relation") not in kinds]
        if branching:
            raise ValueError(
                "单个视频只画一条链：技能之间用 sequence（保持可用 maintain_until）；"
                "条件分支属于跨视频归纳，不在这里画。违规关系="
                f"{[(r.get('from'), r.get('to'), r.get('relation')) for r in branching]}")
        successors, predecessors = {}, {}
        for rel in relations:
            if rel.get("relation") != "sequence":
                continue
            successors.setdefault(rel["from"], []).append(rel["to"])
            predecessors.setdefault(rel["to"], []).append(rel["from"])
        roots = _precedence_roots(nodes, relations)
        leaves = [n["id"] for n in nodes
                  if n["id"] not in {rel["from"] for rel in relations if rel.get("relation") == "sequence"}]
        if len(roots) > 1 or len(leaves) > 1:
            raise ValueError(
                f"单个视频应是一条首尾相连的链；当前起点={roots}，终点={leaves}；"
                "断开的节点请用 sequence 接上，或写进 unresolved 说明它为什么不属本任务")
        forks = {k: v for k, v in successors.items() if len(v) > 1}
        merges = {k: v for k, v in predecessors.items() if len(v) > 1}
        if forks or merges:
            raise ValueError(
                f"单个视频应是一条链（每个技能至多一个后继/前驱）；分支={forks}；汇合={merges}；"
                "重复出现请用不同节点串成链，不要并行分支")


def validate(payload, bundle, requirements=None):
    """用 bundle 中的原子动作与操作图核对 G_case 的来源和结构。

    payload 是待校验的特例图，requirements 是可选任务政策。
    校验失败会抛出带字段或节点信息的 ValueError。
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("G_case schema_version must be case_graph.v1")
    actions = {a["id"]: a for a in bundle.get("atomic", {}).get("atomic_actions", [])}
    observed = {key for key, value in actions.items() if not value.get("inferred")
                and value.get("media_coverage_status") != "outside_decoded_coverage"}
    ops = {n["id"]: n for n in graph_records(bundle.get("operations", {}).get("nodes", []))}
    intents = _intent_ids(bundle.get("intents", {}))
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not isinstance(payload.get("unresolved"), list):
        raise ValueError("G_case requires nodes and unresolved arrays")
    if not nodes and not payload["unresolved"]:
        raise ValueError("An empty skill graph needs an explicit evidence gap")
    ids = set()
    skill_actions = {}
    for node in nodes:
        nid = node.get("id")
        if not isinstance(nid, str) or not nid or nid in ids:
            raise ValueError("Unique nonempty semantic skill ids required")
        ids.add(nid)
        if any(k not in node for k in ("name", "purpose", "expected_effects", "status", "outcome", "evidence_refs", *FIELDS)):
            raise ValueError(f"{nid}: incomplete semantic skill contract")
        for key in ("name", "purpose"):
            if not isinstance(node[key], str) or not node[key].strip():
                raise ValueError(f"{nid}: {key} must describe model semantics")
        for key in ("expected_effects", "C_pre", "C_const", "C_post"):
            if not isinstance(node[key], list) or any(not isinstance(v, str) or not v.strip() for v in node[key]):
                raise ValueError(f"{nid}: {key} must be an array of statements")
        if not node["expected_effects"]:
            raise ValueError(f"{nid}: expected_effects must list the semantic effect this skill expects")
        if not node["C_post"]:
            raise ValueError(f"{nid}: C_post must list the expected postcondition; rule-only skills need it too")
        if node["status"] not in {"observed", "candidate", "not_executed"} or node["outcome"] not in OUTCOMES:
            raise ValueError(f"{nid}: invalid skill status/outcome")
        occurrence = node.get("occurrence", "observed")
        if occurrence not in {"observed", "rule_only"}:
            raise ValueError(f"{nid}: occurrence must be observed or rule_only")
        refs = node["evidence_refs"]
        if not isinstance(refs, list) or any(ref not in observed for ref in refs):
            raise ValueError(f"{nid}: effect evidence must reference observed atomic actions")
        if occurrence == "rule_only":
            if node["status"] != "candidate" or node["outcome"] != "unknown" or refs:
                raise ValueError(f"{nid}: rule-only skill must stay an unobserved candidate with no evidence")
            if not str(node.get("reason") or "").strip():
                raise ValueError(f"{nid}: rule-only skill must state why it has no independent observation")
            for r in node["R"]:
                if r.get("status") != "candidate" or r.get("atomic_refs") or r.get("operation_refs"):
                    raise ValueError(f"{nid}: rule-only skill cannot carry observed realizations")
        if node["outcome"] in {"success", "failure"} and (not refs or node["status"] != "observed"):
            raise ValueError(f"{nid}: success/failure needs an observed local attempt")
        if node["status"] == "not_executed" and node["outcome"] != "not_executed":
            raise ValueError(f"{nid}: not-executed outcome must remain censored")
        if any(ref not in intents for ref in node.get("intent_refs", [])):
            raise ValueError(f"{nid}: unknown intent reference")
        evaluator = node["E"]
        if not isinstance(evaluator, dict) or any(not isinstance(evaluator.get(k), list) for k in
                ("completion", "process_constraint", "implementation_applicability")):
            raise ValueError(f"{nid}: evaluator must cover completion, process and applicability")
        if evaluator.get("binding_status") != "unbound" or evaluator.get("detector_ref") is not None or evaluator.get("controller_ref") is not None:
            raise ValueError(f"{nid}: video learning cannot invent execution bindings")
        realizations = node["R"]
        if not isinstance(realizations, list) or (node["status"] == "observed" and not realizations):
            raise ValueError(f"{nid}: observed skill needs a realization")
        rids = set()
        local_actions = set()
        for r in realizations:
            if not isinstance(r.get("id"), str) or not r["id"] or r["id"] in rids or not r.get("name"):
                raise ValueError(f"{nid}: unique named realization ids required")
            rids.add(r["id"])
            if r.get("status") not in {"observed", "candidate"}:
                raise ValueError(f"{nid}: invalid realization status")
            ore = r.get("operation_refs")
            are = r.get("atomic_refs")
            if not isinstance(ore, list) or not isinstance(are, list) or any(ref not in ops for ref in ore) or any(ref not in actions for ref in are):
                raise ValueError(f"{nid}: realization references must resolve to source operations/actions; "
                                 f"operation_refs must use {list(ops)}, atomic_refs must use {list(actions)}; "
                                 f"received operation_refs={ore}, atomic_refs={are}")
            covered = {ref for op in ore for ref in ops[op].get("atomic_refs", [])}
            if not set(are) <= covered:
                raise ValueError(f"{nid}: atomic refs must be covered by realization operation refs")
            if r["status"] == "observed" and (not are or any(ref not in observed for ref in are) or
                    any(ops[ref].get("inferred") or ops[ref].get("already_satisfied") for ref in ore)):
                raise ValueError(f"{nid}: inferred/state-only operations cannot be claimed as observed")
            if node["status"] == "not_executed" and (r["status"] == "observed" or are or ore):
                raise ValueError(f"{nid}: a nonexecuted skill cannot contain executed action references")
            local_actions.update(are)
        skill_actions[nid] = local_actions
        if not set(refs) <= local_actions:
            raise ValueError(f"{nid}: local skill evidence must belong to its realization actions")
        if node["status"] == "observed" and not refs:
            raise ValueError(f"{nid}: observed skill requires local action evidence")
        if node["status"] == "not_executed" and refs:
            raise ValueError(f"{nid}: nonexecution cannot have executed action evidence")
        if payload.get("contract_version") == CONTRACT_VERSION:
            if node.get("occurrence") == "rule_only" and not requirements:
                raise ValueError("Rule-only skills require an explicit task policy")
            if not node.get("attempt_id") or not isinstance(node.get("actual_postconditions"), list):
                raise ValueError(f"{nid}: attempt_id and actual_postconditions are required")
            for realization in node["R"]:
                if realization.get("completeness") not in {"complete", "partial", "unknown"}:
                    raise ValueError(f"{nid}: realization completeness must be explicit")
                effect_refs = realization.get("effect_evidence_refs")
                if not isinstance(effect_refs, list) or not set(effect_refs) <= set(realization["atomic_refs"]) & observed:
                    raise ValueError(f"{nid}: realization effect evidence must be local and observed")
            if node["outcome"] == "success" and not any(
                    r.get("completeness") == "complete" and r.get("status") == "observed"
                    and r.get("effect_evidence_refs") for r in node["R"]):
                raise ValueError(f"{nid}: success needs a complete observed realization with effect evidence")
            if node["outcome"] == "success" and any(r.get("completeness") != "complete" for r in node["R"]):
                raise ValueError(f"{nid}: serial partial fragments are not alternative complete realizations")
    relations = payload.get("relations")
    if not isinstance(relations, list):
        raise ValueError("G_case relations must be an array")
    rule_only_ids = {node["id"] for node in nodes if node.get("occurrence") == "rule_only"}
    precedences = []
    parallel_pairs = set()
    by_skill = {node["id"]: node for node in nodes}
    for rel in relations:
        if rel.get("from") not in ids or rel.get("to") not in ids or rel["from"] == rel["to"]:
            raise ValueError("Semantic relationship endpoints must reference distinct skills")
        if rel.get("relation") not in RELATIONS or rel.get("basis") not in BASES or rel.get("status") not in {"observed", "candidate"}:
            raise ValueError("Unknown semantic relationship type/basis/status")
        refs = rel.get("source_refs")
        if not isinstance(refs, list) or any(ref not in observed for ref in refs):
            raise ValueError("Relationship evidence must reference observed source actions")
        if rel.get("from") in rule_only_ids or rel.get("to") in rule_only_ids:
            if rel["basis"] not in {"declared_rule", "inferred_dependency"} or rel["status"] != "candidate" or refs:
                raise ValueError("A rule-only skill can only join candidate declared/inferred relations without evidence")
        if rel["basis"] in {"observed_order", "observed_overlap"} and not refs:
            raise ValueError("Observed temporal relationship requires evidence")
        if rel["basis"] not in {"observed_order", "observed_overlap"} and rel["status"] != "candidate":
            raise ValueError("Rule-derived or inferred relationships are not observed temporal facts")
        validate_observed_relation(rel, by_skill, actions)
        if rel["relation"] in {"sequence", "branch"}:
            precedences.append((rel["from"], rel["to"]))
        if rel["relation"] == "parallel":
            parallel_pairs.add(frozenset((rel["from"], rel["to"])))
        if rel["relation"] == "maintain_until":
            # 持续约束描述前段效果保持到后段开始，不是先后关系，不参与拓扑与并行冲突判定。
            if not rel.get("reason"):
                raise ValueError("maintain_until must explain which effect is held until which skill starts")
        if rel["relation"] == "branch" and (not rel.get("guard") or rel.get("guard_truth") not in {"T", "F", "U"}):
            raise ValueError("Branch requires an explicit three-valued guard")
        if rel["relation"] == "synchronization":
            members = rel.get("members")
            if rel.get("join") not in {"all", "any"} or not isinstance(members, list) or len(set(members)) < 2 or not set(members) <= ids or rel["to"] in members:
                raise ValueError("Synchronization requires distinct participants and all/any join")
            precedences.extend((member, rel["to"]) for member in members)
    if any(frozenset(pair) in parallel_pairs for pair in precedences):
        raise ValueError("A skill pair cannot be both precedence-constrained and parallel")
    remaining = set(ids)
    while remaining:
        roots = {n for n in remaining if not any(b == n and a in remaining for a, b in precedences)}
        if not roots:
            raise ValueError("Precedence graph contains a cycle; distinguish repeated skill occurrences")
        remaining -= roots
    task = payload.get("task_outcome")
    if not isinstance(task, dict) or task.get("value") not in OUTCOMES or not isinstance(task.get("evidence_refs"), list):
        raise ValueError("Separate task outcome with evidence refs required")
    if any(ref not in observed for ref in task["evidence_refs"]) or (task["value"] in {"success", "failure"} and not task["evidence_refs"]):
        raise ValueError("Task success/failure requires observed evidence")
    if not nodes and task["value"] != "unknown":
        raise ValueError("Empty semantic graph cannot establish task success/failure")
    observations = payload.get("condition_observations")
    if not isinstance(observations, list):
        raise ValueError("condition_observations must be an array")
    by_id = {n["id"]: n for n in nodes}
    for obs in observations:
        if obs.get("skill_id") not in ids or obs.get("kind") not in {"C_pre", "C_const", "C_post"} or obs.get("truth") not in {"T", "F", "U"} or obs.get("phase") not in {"pre", "during", "post"}:
            raise ValueError("Invalid condition observation scope/type/truth")
        if not isinstance(obs.get("text"), str) or not obs["text"].strip() or obs.get("outcome") != by_id[obs["skill_id"]]["outcome"]:
            raise ValueError("Condition evidence must use its local skill outcome")
        refs = obs.get("evidence_refs")
        if not isinstance(refs, list) or any(ref not in observed for ref in refs) or (obs["truth"] != "U" and not refs):
            raise ValueError("Known condition truth requires observed evidence")
        if not set(refs) <= skill_actions[obs["skill_id"]]:
            raise ValueError(f"Condition evidence cannot leak from another local skill: {obs['skill_id']} "
                             f"may cite only {sorted(skill_actions[obs['skill_id']], key=str)}, received {refs}; "
                             "use local state evidence or truth=U, never cite a previous skill's actions")
    _require_policy_shape(payload, requirements)
    if payload.get("task_scope_review") is not None:
        observed_ops = {oid for oid, op in ops.items()
                        if not op.get("inferred") and not op.get("already_satisfied")
                        and set(op.get("atomic_refs") or []) & observed}
        approach_ops = {oid for oid in observed_ops if ops[oid].get("name") == "靠近"}
        validate_retained_operations(payload["task_scope_review"], nodes, observed_ops, approach_ops)
    unmapped, excluded = _operation_traceability(payload, bundle, nodes, relations)
    return {"structure_valid": True, "semantic_status": "model_grounded_candidate",
            "temporal_evidence_status": "model_assessed_requires_review",
            "causal_status": "not_established", "execution_binding_status": "unbound",
            "rule_only_skills": sorted(rule_only_ids),
            "mapped_operation_relations": unmapped, "excluded_operations": excluded}


def _operation_traceability(payload, bundle, nodes, relations):
    """Require every model-observed operation relation and unused step to be accounted for.

    The host only compares identifiers and relation types; it never decides which
    operation belongs to which skill or whether a relation is semantically right.
    """
    operations = graph_records(bundle.get("operations", {}).get("nodes", []))
    by_op = {n.get("id"): n for n in operations}
    edges = graph_records(bundle.get("operations", {}).get("edges", []))
    owner = {}
    for node in nodes:
        for realization in node["R"]:
            for ref in realization["operation_refs"]:
                owner.setdefault(ref, set()).add(node["id"])
    declared = {(rel["from"], rel["to"], rel["relation"]) for rel in relations}
    unmapped_rows = payload.get("unmapped_relations") or []
    if not isinstance(unmapped_rows, list):
        raise ValueError("unmapped_relations must be an array")
    unmapped = set()
    for row in unmapped_rows:
        if not isinstance(row, dict) or not str(row.get("reason") or "").strip():
            raise ValueError("An unmapped operation relation must state why it cannot be lifted")
        if row.get("operation_from") not in by_op or row.get("operation_to") not in by_op:
            raise ValueError("Unmapped relation references an unknown operation")
        if row.get("relation") not in OPERATION_RELATIONS:
            raise ValueError("Unmapped relation must be a model-observed operation relation")
        unmapped.add((row["operation_from"], row["operation_to"], row["relation"]))
    lifted, internal = [], []
    for edge in edges:
        kind = edge.get("relation")
        if kind not in OPERATION_RELATIONS:
            continue
        left, right = edge.get("from"), edge.get("to")
        owners_left, owners_right = owner.get(left) or set(), owner.get(right) or set()
        if not owners_left or not owners_right:
            continue  # unclaimed steps are covered by excluded_operations below
        if owners_left & owners_right:
            internal.append({"operation_from": left, "operation_to": right, "relation": kind,
                             "skill": sorted(owners_left & owners_right)[0]})
            continue
        pairs = {(a, b, kind) for a in owners_left for b in owners_right}
        if pairs & declared:
            lifted.append({"operation_from": left, "operation_to": right, "relation": kind,
                           "skills": sorted({(a, b) for a, b, _ in pairs & declared})})
            continue
        if (left, right, kind) in unmapped:
            continue
        raise ValueError(
            "Operation relation was dropped from the semantic graph: "
            f"{kind} {left}({by_op[left].get('name')}) -> {right}({by_op[right].get('name')}); "
            f"skills={sorted(owners_left)} -> {sorted(owners_right)}; "
            "add the matching skill relation, keep it as an internal realization detail, "
            "or record it in unmapped_relations with a reason")
    excluded_rows = payload.get("excluded_operations") or []
    if not isinstance(excluded_rows, list):
        raise ValueError("excluded_operations must be an array")
    excluded = set()
    for row in excluded_rows:
        if not isinstance(row, dict) or row.get("operation_ref") not in by_op:
            raise ValueError("excluded_operations must reference an existing operation")
        if not str(row.get("reason") or "").strip():
            raise ValueError("An excluded operation must state why it is not part of any skill")
        if row["operation_ref"] in owner:
            raise ValueError(f"Excluded operation {row['operation_ref']} is claimed by a skill realization")
        excluded.add(row["operation_ref"])
    for op_id, op in by_op.items():
        if op.get("inferred") or op.get("already_satisfied") or op_id in owner or op_id in excluded:
            continue
        if not any(node["status"] == "observed" for node in nodes):
            continue  # 没有已观察技能时无实现可承载，空图/未执行场景保持未知
        # 手必须抵达才能抓取：任何被观察的操作都不允许从技能实现里消失而不解释。
        raise ValueError(
            "An observed operation is missing from every skill realization: "
            f"{op_id}({op.get('name')}); add it to a realization or list it in excluded_operations with a reason"
        )
    return lifted, sorted(excluded)


def learn(client, bundle, requirements=None):
    """Ask the deployed model to interpret saved model observations, fail closed."""
    from ..knowledge import video_identity

    pipeline = bundle.get("pipeline", {})
    source_model = pipeline.get("model")
    source_url = pipeline.get("base_url", "").rstrip("/")
    if source_model != "qwen3.8-27b" or source_url not in {"http://127.0.0.1:8032", "http://localhost:8032", "http://192.168.137.102:8032"}:
        raise ValueError("G_case requires source observations from the authorized 8032 qwen3.8-27b service")
    if client.model != "qwen3.8-27b" or client.base_url.rstrip("/") not in {"http://127.0.0.1:8032", "http://localhost:8032", "http://192.168.137.102:8032"}:
        raise ValueError("G_case semantic learning must use 8032 qwen3.8-27b")
    if requirements is not None and not isinstance(requirements, dict):
        raise ValueError("graph_requirements must be a JSON object")
    uid, identity_kind = video_identity(bundle)
    fields = ("meta", "intents", "atomic", "relations", "observed_operation_graph", "sync", "task_contract", "text_description",
              "semantic_scope", "task_nodes_source", "operations", "conditions", "source_analysis")
    inputs = {key: deepcopy(bundle[key]) for key in fields if key in bundle}
    if bundle.get("task_contract"):
        # A refreshed declaration supersedes legacy text that embedded the old policy.
        # Historical observations remain frozen in the saved source bundle.
        inputs.pop("text_description", None)
    inputs["reference_index"] = [
        {"operation_id": op["id"], "name": op.get("name"), "atomic_refs": op.get("atomic_refs", []),
         "observed_realization_allowed": not bool(op.get("inferred") or op.get("already_satisfied"))}
        for op in graph_records(bundle.get("operations", {}).get("nodes", []))]
    if requirements is not None:
        inputs["graph_requirements"] = deepcopy(requirements)
    checklist = "输出前检查引用、局部结果、完整R、时间与未知状态。只输出完整JSON。" + policy_prompt(requirements)
    video_kwargs = {}
    source = Path((bundle.get("meta") or {}).get("path") or "")
    if source.is_file() and (bundle.get("meta") or {}).get("duration"):
        from ..media import make_clip
        video_kwargs["video"] = make_clip(source, 0, bundle["meta"]["duration"], tag="s09_case_graph_v2")
        video_kwargs["video_id"] = uid
    actions = {a["id"]: a for a in bundle.get("atomic", {}).get("atomic_actions", [])
               if not a.get("inferred") and a.get("media_coverage_status") != "outside_decoded_coverage"}
    observed_ops = [entry for entry in inputs["reference_index"]
                    if entry["observed_realization_allowed"] and set(entry["atomic_refs"]) & actions.keys()]
    scope_ops = [{**entry, "id": entry["operation_id"]} for entry in observed_ops]
    scope_review = learn_scope(client, bundle, scope_ops, video_kwargs)
    inputs["task_scope_review"] = scope_review
    user = checklist + "\n以下为已有观察、模型复核及引文。\n" + json.dumps(inputs, ensure_ascii=False)
    def generated(value):
        if value.get("contract_version") != CONTRACT_VERSION:
            raise ValueError("New G_case must declare contract_version=" + CONTRACT_VERSION)
        return validate({**value, "task_scope_review": scope_review}, bundle, requirements)
    result = client.ask(stage="s09_case_graph", system=SYSTEM, user_text=user,
                        validator=generated, **video_kwargs)
    result = deepcopy(result)
    result["task_scope_review"] = scope_review
    result["provenance"] = {"origin": "deployed_model", "model": client.model, "base_url": client.base_url,
                            "source_observation_model": source_model, "source_observation_base_url": source_url,
                            "source_video_sha256": uid, "identity_kind": identity_kind,
                            "input_sha256": _digest(inputs), "code_version": bundle.get("code_version"),
                            "graph_requirements_sha256": _digest(requirements) if requirements is not None else None,
                            "observation_independence": "frozen_pre_sync" if bundle.get("observed_operation_graph") else "legacy_not_established"}
    result["intent_hypotheses"] = deepcopy(bundle.get("intents", {}).get("intents", []))
    result["intent_alignment"] = deepcopy(bundle.get("intent_alignment", {}))
    result["operation_graph_ref"] = {"file": "result.json", "field": "operations", "sha256": _digest(bundle.get("operations", {}))}
    result["mappings"] = [{"skill_id": n["id"], "realization_id": r["id"],
                           "operation_refs": deepcopy(r["operation_refs"]), "atomic_refs": deepcopy(r["atomic_refs"])}
                          for n in result["nodes"] for r in n["R"]]
    if requirements is not None:
        result["graph_requirements"] = deepcopy(requirements)
    result["validation"] = validate(result, bundle, requirements)
    return result


def export(bundle, out):
    """校验案例字典，将其中的 G_case 写到 out 下的 JSON 与 SVG。"""
    graph = bundle.get("case_graph")
    if graph is None:
        return
    validate(graph, bundle, graph.get("graph_requirements"))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "G_case.json").write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    video_name = Path((bundle.get("meta") or {}).get("path", "")).stem
    (out / "G_case.svg").write_text(svg(graph, name=video_name, operations=bundle.get("operations")),
                                     encoding="utf-8")
    bundle.setdefault("output_layout", {}).update(case_graph="G_case.json", case_graph_view="G_case.svg")
