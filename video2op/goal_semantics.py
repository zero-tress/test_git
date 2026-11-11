"""Role-based goal contracts. Object identity/type and realization are separate axes."""
from __future__ import annotations

GOALS = {
    "grasp_object": {"name": "抓取对象", "purpose": "建立对目标的稳定握持",
                     "effects": [("holding", ("actor", "target"), True)]},
    "acquire_object": {"name": "获取对象", "purpose": "取得目标并持有，脱离原支撑",
                       "effects": [("holding", ("actor", "target"), True),
                                   ("off_source_support", ("target", "source"), True)]},
    "relocate_object": {"name": "搬移对象", "purpose": "使目标到达目的位置，不限定推拉或抓持方式",
                        "effects": [("at_destination", ("target", "destination"), True)]},
    "place_object": {"name": "放置对象", "purpose": "使目标得到支撑并解除握持",
                     "effects": [("at_destination", ("target", "destination"), True),
                                 ("supported", ("target",), True),
                                 ("holding", ("actor", "target"), False)]},
    "clear_access": {"name": "清除接近障碍", "purpose": "使目标的接近通路可用",
                     "effects": [("accessible", ("target",), True)]},
    "open_object": {"name": "打开对象", "purpose": "使目标处于打开状态",
                    "effects": [("open", ("target",), True)]},
    "close_object": {"name": "关闭对象", "purpose": "使目标处于关闭状态",
                     "effects": [("open", ("target",), False)]},
}
LEAF_GOALS = {
    "抓取": "grasp_object",
    # Other leaf names need local goals: arm movement alone need not relocate its object.
}


def contract(key: str) -> dict:
    g = GOALS[key]
    return {"goal_key": key, "name": g["name"], "purpose": g["purpose"],
            "expected_effects": [{"predicate": p, "roles": list(a), "value": v}
                                 for p, a, v in g["effects"]],
            "origin": "seed_semantic_vocabulary", "observation_status": "expected_not_observed"}
