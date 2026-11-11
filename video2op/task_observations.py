"""Task observations keep provided goals, model predictions and reference labels separate."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

OUTCOMES = {"success", "failure", "not_executed", "unknown"}
TRUTH = {"T", "F", "U"}

def identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]

def conjunction(values):
    if any(v not in TRUTH for v in values):
        raise ValueError("invalid three-valued component")
    return "F" if "F" in values else "T" if all(v == "T" for v in values) else "U"

def evaluate_goal(components):
    return conjunction([components.get(k, "U") for k in ("at_destination", "stationary", "hand_separated")])

def execution_outcome(attempted, goal):
    if attempted not in TRUTH or goal not in TRUTH:
        raise ValueError("invalid task truth")
    return "not_executed" if attempted == "F" else ("success" if goal == "T" else "failure" if goal == "F" else "unknown") if attempted == "T" else "unknown"

def reference_from_annotation(row, source):
    """Import an existing reference. No new human reviewer or frame observation is invented."""
    text = row["实际结果"]
    attempted = "T" if row["是否尝试"] == "是" else "F" if "未见" in row["是否尝试"] else "U"
    goal = "T" if text.startswith(("成功", "目标达成")) or "初始目标状态已成立" in text else "F" if text.startswith("失败") or "未到" in text else "U"
    # These are reference task labels, not condition labels or local-subtask outcomes.
    method = row["方法"]
    method = "None" if attempted == "F" else "GraspMove" if method.startswith("抓起") else "GraspSlide" if method.startswith("抓持") else "Push" if method.startswith("推") else "Pull" if method.startswith("拉") else "Unknown"
    evidence = {"evidence_id": "annotation_" + row["编号"], "source": str(source),
                "video_uid": row["SHA256"], "field": "可见证据", "quote": row["可见证据"],
                "time_precision": "approximate_observation_points_not_action_boundaries",
                "provenance": "existing_annotation", "verification_status": "verified",
                "verification_basis": "imported_existing_reference_not_new_frame_review"}
    negative_drop = any(w in text for w in ("未见掉落", "未掉落", "无掉落"))
    drop = "F" if negative_drop else "T" if "掉落" in text else "U"
    return {"case_id": row["编号"], "video_uid": row["SHA256"],
            "observation_id": identity([row["SHA256"], "provided_task"]),
            "task_contract": {"goal_key": "relocate_and_release", "statement": row["指派任务"],
                              "source_region": "黑色桌垫 A", "destination": "白色桌面 B",
                              "origin": "provided_dataset_task"},
            "attempted": attempted, "outcome": execution_outcome(attempted, goal),
            "goal_satisfied_final": goal, "method": method, "drop": drop,
            "target_description": row["物体"], "initial_state": row["初始状态"],
            "obstacle": row["障碍物"], "evidence": [evidence],
            "reviewer": {"kind": "existing_reference_import", "identity": None,
                         "note": "原标注未记录审阅者身份，本轮不补造姓名"},
            "provenance": "existing_annotation", "verification_status": "verified"}

def prediction_from_audit(audit, uid, task_contract, source):
    components = {"at_destination": "T" if audit.get("final_region") == "B" else "U" if audit.get("final_region") in {None, "Unknown"} else "F",
                  "stationary": audit.get("final_stationary", "U"),
                  "hand_separated": audit.get("hand_separated_final", "U")}
    goal = evaluate_goal(components)
    return {"video_uid": uid, "observation_id": identity([uid, "provided_task"]),
            "task_contract": deepcopy(task_contract), "attempted": audit.get("attempted", "U"),
            "outcome": execution_outcome(audit.get("attempted", "U"), goal),
            "goal_satisfied_final": goal, "components": components,
            "original_model_goal": audit.get("goal_satisfied_final"),
            "original_model_outcome": audit.get("operation_outcome"),
            "method": audit.get("method", "Unknown"), "drop": audit.get("drop", "U"),
            "evidence": [{"evidence_id": identity([uid, str(source)]), "source": str(source),
                          "video_uid": uid, "quote": deepcopy(audit.get("evidence", [])),
                          "provenance": "model_task_audit", "verification_status": "unverified"}],
            "provenance": "model_task_audit", "verification_status": "unverified"}

def validate_reference(record):
    if record.get("outcome") not in OUTCOMES or record.get("attempted") not in TRUTH:
        raise ValueError("invalid task observation")
    if record.get("outcome") != execution_outcome(record["attempted"], record.get("goal_satisfied_final", "U")):
        raise ValueError("outcome does not follow attempted and final goal")
    if not record.get("reviewer") or not record.get("evidence") or not record.get("video_uid"):
        raise ValueError("task reference requires identity, reviewer provenance and evidence")
    for ev in record["evidence"]:
        if ev.get("video_uid") != record["video_uid"] or not ev.get("quote") or not ev.get("source"):
            raise ValueError("task evidence has wrong identity or no source")
    return record

def attach(bundle, prediction, reference=None):
    """Only an explicitly supplied reviewed reference may override this task observation."""
    result = deepcopy(prediction)
    if reference is not None:
        validate_reference(reference)
        if reference["video_uid"] != prediction["video_uid"]:
            raise ValueError("reference video identity mismatch")
        result = deepcopy(reference)
        result["model_prediction"] = deepcopy(prediction)
    bundle["task_observation"] = result
    bundle["provided_task_contract"] = deepcopy(result["task_contract"])
    return result

def condition_observations(observations):
    """Task-level facts stay separate from model-scoped skill preconditions."""
    rows = []
    for obs in observations:
        if obs.get("provenance") != "existing_annotation":
            continue
        source_ev = obs["evidence"][0]
        obstacle = obs.get("obstacle", "")
        truth = "F" if obstacle == "无" else "T" if obstacle and "不确定" not in obstacle else "U"
        # Presence of an obstacle is observed. Whether it blocks a particular R is not inferred.
        ev = {**source_ev, "field": "障碍物", "quote": obstacle,
              "evidence_id": source_ev["evidence_id"] + "_obstacle"}
        rows.append({"video_uid": obs["video_uid"], "instance_id": obs["observation_id"],
                     "goal_key": "relocate_and_release", "condition_key": "path_obstacle_present",
                     "truth": truth, "at": "pre", "outcome": obs["outcome"],
                     "evidence": [ev], "outcome_evidence": obs["evidence"],
                     "provenance": "reviewed_observation", "reviewer": obs["reviewer"],
                     "comparison_context": "method:" + obs.get("method", "Unknown"),
                     "scope": "provided_task", "causal_status": "not_established"})
    return rows

def load_references(path):
    value = json.loads(Path(path).read_text())
    records = value["observations"] if isinstance(value, dict) else value
    result = {}
    for record in records:
        validate_reference(record)
        uid = record["video_uid"]
        if uid in result:
            raise ValueError("duplicate task reference video")
        result[uid] = record
    return result
