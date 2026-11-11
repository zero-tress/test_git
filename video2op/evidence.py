"""Conservative state evidence. Similar wording proposes a link, never proves it.

Free-text paraphrases remain unknown until a reviewer or predicate grounding layer
confirms them. Generated/inherited states and intended actions are not observations.
"""
from __future__ import annotations

from .operations import _norm


def matches(expected: str, observed: str) -> bool:
    return bool(_norm(expected)) and _norm(expected) == _norm(observed)


def observed_state(action: dict, key: str = "state_after") -> str:
    if action.get("media_coverage_status") == "outside_decoded_coverage" or action.get("inferred") or action.get(f"{key}_from", "observed") != "observed":
        return ""
    return str(action.get(key) or "")


def observed_states(action: dict, key: str = "state_after") -> list[str]:
    if action.get("media_coverage_status") == "outside_decoded_coverage":
        return []
    world_key = "world_before" if key == "state_before" else "world_after"
    world = action.get(world_key) or []
    if (action.get("inferred") or action.get(world_key + "_from", "observed") != "observed"
            or not isinstance(world, list)):
        world = []
    return [s for s in [observed_state(action, key), *world] if isinstance(s, str) and s]


def support(condition: str, op: dict, atomic: list[dict]) -> list[dict]:
    refs = set(op.get("atomic_refs") or [])
    candidates = [a for a in atomic if a.get("id") in refs
            and float(a.get("end", 0)) <= float(op.get("end", 0)) + 0.05
            and any(matches(condition, s) for s in observed_states(a))]
    # An earlier success cannot prove completion if a later state for that same
    # executor differs. Without state fluents we conservatively request review.
    return [a for a in candidates if not any(
        b.get("id") in refs and b.get("executor") == a.get("executor")
        and float(a.get("end", 0)) < float(b.get("end", 0)) <= float(op.get("end", 0)) + 0.05
        and observed_states(b) and not any(matches(condition, s) for s in observed_states(b))
        for b in atomic)]
