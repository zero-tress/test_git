"""Video-local alias resolution and typed state predicates; absence never means false."""

from __future__ import annotations

import re


def alias_map(instance):
    labels = set()
    categories = {}
    for row in instance.get("entity_context", []):
        if row.get("label"):
            labels.add(row["label"])
            categories[row["label"]] = row.get("category")
    labels.update(str(x) for x in instance.get("bindings", {}).values() if x)
    labels.update(str(a["object"]) for a in instance.get("observed_process", []) if a.get("object"))
    target = instance.get("target", {}).get("local_entity")
    if target:
        labels.add(target)
        categories[target] = instance.get("target", {}).get("category")
    candidates = {}
    nouns = {
        "塑料盒": "box",
        "盒子": "box",
        "盒": "box",
        "杯子": "cup",
        "杯": "cup",
        "瓶子": "bottle",
        "瓶": "bottle",
        "笔": "pen",
    }
    for term, category in nouns.items():
        matched = {label for label in labels if term in label or categories.get(label) == category}
        if len(matched) == 1:
            label = next(iter(matched))
            if term != label:
                candidates[term] = label
    for alias, label in instance.get("entity_aliases", {}).items():
        if label in labels and alias not in labels:
            competing = [other for other in labels if alias in other]
            if not competing or competing == [label]:
                candidates[alias] = label
    return candidates


def atoms(text, instance, actor=None, *, requirement=False, object_hint=None):
    """Parse explicit claims. Output atoms are candidate semantics, not truth certification."""
    from .cross_video_alignment import normalized, roles

    value = normalized(text, instance)
    if not value or (
        not requirement
        and any(w in value for w in ["可能", "隐含", "推测", "不确定", "看不清", "遮挡", "如果", "若", "也许"])
    ):
        return []
    actors = re.findall(r"\$(?:gripper|arm|body)_\d+", value)
    current = actors[0].lstrip("$") if actors else roles(instance).get(actor, actor or "acting_agent")
    if any(w in value for w in ["手指", "手掌", "手已", "手处"]) and str(current).startswith("arm_"):
        current = str(current).replace("arm_", "gripper_")
    objects = re.findall(r"\$(?:target|destination|other_\d+|context_\d+)", value)
    hinted = normalized(object_hint, instance) if object_hint else ""
    hinted = re.findall(r"\$(?:target|destination|other_\d+|context_\d+)", hinted)
    obj = objects[0].lstrip("$") if objects else hinted[0].lstrip("$") if hinted else "target"
    labels = [r.get("label", "") for r in instance.get("entity_context", [])]
    if not objects and any(
        term in value and sum(term in label for label in labels) > 1 for term in ["盒", "杯", "瓶", "笔"]
    ):
        obj = "unresolved_object"
    out = []

    def add(predicate, args, truth=True):
        row = {"predicate": predicate, "args": list(args), "truth": truth}
        if row not in out:
            out.append(row)

    holding_words = ["握住", "抓住", "抓握", "握持", "抓牢", "抓稳", "握紧"]
    grip_negative = any(
        w in value
        for w in [
            "未握住",
            "没握住",
            "没有握住",
            "未抓住",
            "没抓住",
            "未能抓住",
            "没有抓住",
            "不再握持",
            "未建立握持",
            "未握持",
            "未抓握",
            "没有抓握",
            "没有握持",
        ]
    )
    unstable = any(
        w in value
        for w in [
            "未抓稳",
            "没抓稳",
            "未抓牢",
            "握持不稳",
            "抓握不稳",
            "滑落",
            "失去握持",
            "未稳定握持",
            "没有稳定握持",
            "没有抓稳",
            "没有握紧",
        ]
    )
    if any(w in value for w in ["没有滑落", "未滑落", "没有失去握持", "未失去握持"]):
        unstable = any(
            w in value
            for w in [
                "握持不稳",
                "抓握不稳",
                "未抓稳",
                "未抓牢",
                "未稳定握持",
                "没有稳定握持",
                "没有抓稳",
                "没有握紧",
            ]
        )
    released = any(w in value for w in ["与手分离", "手物分离", "解除握持", "手已松开", "已释放"])
    if any(w in value for w in ["允许解除", "可解除", "准备解除", "将解除", "待解除", "允许释放", "准备释放"]):
        released = False
    if str(current).startswith("arm_") and (
        any(w in value for w in holding_words)
        or grip_negative
        or unstable
        or released
        or any(w in value for w in ["手指", "空手", "夹爪空闲"])
    ):
        current = str(current).replace("arm_", "gripper_")
    if grip_negative or released:
        add("holding", [current, obj], False)
    elif any(w in value for w in holding_words):
        if not any(w in value for w in ["准备抓", "将要抓", "待抓", "抓取前"]):
            if not unstable or (
                any(w in value for w in ["握住", "握持", "抓握"])
                and not any(w in value for w in ["未稳定握持", "没有稳定握持"])
            ):
                add("holding", [current, obj])
            if any(w in value for w in ["稳定", "抓牢", "抓稳", "牢固"]) and not unstable:
                add("stable_holding", [current, obj])
    if unstable:
        add("stable_holding", [current, obj], False)
    if any(w in value for w in ["未张开", "没有张开", "手指闭合", "手未打开"]):
        add("hand_open", [current], False)
    elif any(w in value for w in ["手指张开", "手已张开", "手处于张开", "手张开", "手指打开", "手已打开"]):
        add("hand_open", [current])
    if any(w in value for w in ["手空闲", "未持有任何", "没有持有", "空手", "夹爪空闲"]):
        add("gripper_empty", [current])
    if any(w in value for w in ["可抓取位置", "可抓位置", "抓取位姿", "抓握位置"]):
        add("at_grasp_position", [current, obj], not any(w in value for w in ["未到", "不在", "未处于", "无法到达"]))
    elif any(w in value for w in ["上方", "悬停"]):
        add("above_target", [current, obj])
    if any(w in value for w in ["通路受阻", "不可接近", "被挡住", "通路被阻挡", "通道不通"]):
        add("accessible", [obj], False)
    elif any(w in value for w in ["目标可接近", "通路可用", "通路畅通", "通道畅通", "无障碍可接近"]):
        add("accessible", [obj])
    if any(w in value for w in ["可达", "可及", "可抓取范围"]):
        add("reachable", [obj], not any(w in value for w in ["不可达", "不可及", "超出"]))
    if any(w in value for w in ["静止", "不再移动", "保持不动"]):
        add("stationary", [obj], not any(w in value for w in ["未静止", "没有静止", "不保持不动"]))
    if any(w in value for w in ["得到支撑", "受到支撑", "稳定支撑", "可靠支撑", "支撑在"]):
        add(
            "supported",
            [obj],
            not any(w in value for w in ["未受到", "未得到", "没有支撑", "未稳定支撑", "未有可靠支撑"]),
        )
    if any(w in value for w in ["脱离原支撑", "离开原支撑", "离开桌面", "抬离"]):
        add(
            "off_source_support",
            [obj, "source"],
            not any(w in value for w in ["未脱离", "没有脱离", "未离开", "没有离开", "未抬离"]),
        )
    if "$destination" in value and any(w in value for w in ["到达", "位于", "放在", "静止在", "已在"]):
        add("at_destination", ["target", "destination"])
    return sorted(out, key=lambda r: (r["predicate"], r["args"], r["truth"]))


def signature(text, instance, actor=None):
    from .cross_video_alignment import normalized

    parsed = atoms(text, instance, actor)
    value = normalized(text or "", instance)
    qualifiers = []
    if any(w in value for w in ["位于", "静止在", "放在"]) and "$destination" not in value:
        qualifiers.append(value)
    return {"atoms": parsed, "unmapped": value if not parsed else "", "qualifiers": qualifiers}


def entails(observed, required):
    if observed["args"] != required["args"]:
        return False
    if observed["truth"] != required["truth"]:
        return False
    return observed["predicate"] == required["predicate"] or (
        observed["predicate"] == "stable_holding" and required["predicate"] == "holding" and observed["truth"]
    )


def opposite(a, b):
    if a["args"] != b["args"]:
        return False
    if a["predicate"] == b["predicate"]:
        return a["truth"] != b["truth"]
    return (a["predicate"], a["truth"], b["predicate"], b["truth"]) in {
        ("holding", False, "stable_holding", True),
        ("stable_holding", True, "holding", False),
    }
