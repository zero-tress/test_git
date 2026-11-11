"""Validate scoped human review records before applying them to knowledge."""
from copy import deepcopy
from .task_observations import OUTCOMES

def validate_reviewed(rows, instances):
    from .stages.s08_scope import _evidence
    by_id = {i["instance_id"]: i for i in instances}
    result = []
    seen = {}
    for original in rows:
        r = deepcopy(original)
        item = by_id.get(r.get("instance_id"))
        if item is None or r.get("video_uid") != item["video_uid"] or not r.get("reviewer"):
            raise ValueError("reviewed observation must name a loaded instance, video and reviewer")
        if r.get("goal_key") != item["goal_key"]:
            raise ValueError("reviewed observation goal does not match its instance")
        if r.get("outcome", "unknown") not in OUTCOMES or r.get("truth", "U") not in {"T", "F", "U"}:
            raise ValueError("invalid reviewed truth or outcome")
        actions = {a["id"]: a for a in item["observed_process"]}
        for e in [*r.get("evidence", []), *r.get("outcome_evidence", [])]:
            _evidence(e, actions)
        if r.get("truth") in {"T", "F"} and not r.get("evidence"):
            raise ValueError("condition truth requires evidence")
        if r.get("outcome_review") and r.get("outcome") in {"success", "failure"}:
            if not r.get("outcome_evidence"):
                raise ValueError("reviewed outcome requires evidence")
            end = max(a["end"] for a in actions.values())
            for ev in r["outcome_evidence"]:
                a = actions[ev["atomic_ref"]]
                t = a["start"] if "before" in ev["field"] else a["end"]
                if t < end:
                    raise ValueError("reviewed outcome is not at its final boundary")
        if r.get("truth") in {"T", "F"}:
            start = min(a["start"] for a in actions.values())
            end = max(a["end"] for a in actions.values())
            for e in r["evidence"]:
                a = actions[e["atomic_ref"]]
                t = a["start"] if "before" in e["field"] else a["end"]
                if (r.get("at", "pre") == "pre" and t > start) or (r.get("at") == "post" and t < end):
                    raise ValueError("reviewed condition is not at its annotated boundary")
        key = (r["instance_id"], r.get("condition_key"), r.get("at", "pre"))
        label = (r.get("truth"), r.get("outcome"))
        if key in seen and seen[key] != label:
            raise ValueError("conflicting reviewed observations")
        seen[key] = label
        r["provenance"] = "reviewed_observation"
        result.append(r)
    return result
