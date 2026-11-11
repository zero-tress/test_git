"""Corroboration counts and explicit human-review gates for temporal pattern verification."""
import hashlib
import json
from collections import Counter

def summarize(cases, reviews=None):
    groups = {}
    for case in cases:
        b = case["bundle"]
        uid = case["video_uid"]
        names = {n["id"]: n["name"] for n in b["task_nodes"]["task_nodes"]}
        for p in b.get("temporal_knowledge", {}).get("patterns", []):
            signature = [p["pattern"], [names.get(n, n) for n in p.get("members", [])]]
            if p["pattern"] in {"Branch", "Synchronization"}:
                signature.append(p.get("alternatives", p.get("join")))
            key = hashlib.sha256(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
            group = groups.setdefault(key, {"pattern_key": key, "pattern": p["pattern"], "signature": signature,
                                            "support_video_sha256": [], "occurrences": [], "verification_status": "unverified"})
            if uid not in group["support_video_sha256"]:
                group["support_video_sha256"].append(uid)
            group["occurrences"].append({"video_uid": uid, "pattern_id": p["id"], "issues": p.get("issues", [])})
    for r in reviews or []:
        group = groups.get(r.get("pattern_key"))
        if not group or not r.get("reviewer") or not r.get("evidence") or r.get("confirmed") is not True:
            raise ValueError("pattern verification requires explicit reviewer, evidence and confirmation")
        support = set(group["support_video_sha256"])
        if len(support) < 2 or not support <= set(r.get("reviewed_video_sha256", [])):
            raise ValueError("pattern verification requires two independent reviewed videos")
        if any(o["issues"] for o in group["occurrences"]):
            raise ValueError("unresolved pattern conflicts prevent verification")
        group.update(verification_status="verified", review=r)
    return {"patterns": list(groups.values()), "counts": dict(Counter(g["pattern"] for g in groups.values())),
            "verified": sum(g["verification_status"] == "verified" for g in groups.values()),
            "verification_scope": "observed_pattern_support_not_universal_causal_necessity",
            "unresolved": "No human confirmation is inferred from model output or annotations about unrelated propositions."}
