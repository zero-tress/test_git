#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""先验补全（腿部站立支撑、姿态保持）的确定性测试。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video2op.single_video.stages import s02e_prior as p


def _walk_actions():
    return [
        {"id": 1, "executor": "左腿", "action": "左腿向前迈步", "mode": "motion",
         "start": 0.0, "end": 2.0, "exerts_force": True, "force_role": "支撑"},
        {"id": 2, "executor": "右腿", "action": "右腿向前迈步", "mode": "motion",
         "start": 0.0, "end": 2.0, "exerts_force": True, "force_role": "支撑"},
        {"id": 3, "executor": "左腿", "action": "左腿向前迈步", "mode": "motion",
         "start": 6.0, "end": 8.0, "exerts_force": True, "force_role": "支撑"},
        {"id": 4, "executor": "右腿", "action": "右腿向前迈步", "mode": "motion",
         "start": 6.0, "end": 8.0, "exerts_force": True, "force_role": "支撑"},
    ]


def test_leg_support_is_no_longer_inferred():
    """操作层不再为旧下肢记录生成支撑节点。"""
    out = p.run(_walk_actions(), 8.0)
    assert out["inferred_actions"] == []


def test_no_foot_actions_inferred():
    """腿脚一体：不再单列脚。"""
    out = p.run(_walk_actions(), 8.0)
    assert all("脚" not in a["executor"] for a in out["inferred_actions"])


def test_arm_hold_filled_between_lift_and_next_action():
    """手臂抬起托举后到下一个动作之间应补出保持抬起托举。"""
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向上抬起托举", "mode": "motion",
         "start": 4.0, "end": 6.0, "exerts_force": True, "force_role": "托举"},
        {"id": 2, "executor": "右臂", "action": "右臂向前伸出放置", "mode": "motion",
         "start": 10.0, "end": 12.0, "exerts_force": True, "force_role": "托举"},
    ]
    out = p.run(actions, 12.0)
    holds = [a for a in out["inferred_actions"] if a["executor"] == "右臂"]
    assert holds and holds[0]["action"] == "右臂保持抬起托举", holds
    assert (holds[0]["start"], holds[0]["end"]) == (6.0, 10.0)
    assert holds[0]["object"] is None  # 状态不带物体


def test_preopen_filled_before_grasp_when_missing():
    """要抓握，手必须先张开；视频没有开度变化记录 → 按必要性补出预张开。"""
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向前伸出靠近杯子", "mode": "motion",
         "start": 0.0, "end": 2.0, "exerts_force": True, "force_role": "稳定"},
        {"id": 2, "executor": "右手", "action": "右手手指收拢抓紧杯子", "mode": "transition",
         "start": 2.0, "end": 3.0, "exerts_force": True, "force_role": "抓握"},
    ]
    out = p.run(actions, 3.0)
    pre = [a for a in out["inferred_actions"] if "张开" in a["action"]]
    assert pre, out["inferred_actions"]
    a = pre[0]
    assert a["mode"] == "transition" and a["inferred"] is True
    assert a["executor"] == "右手" and (a["start"], a["end"]) == (1.0, 2.0)
    assert "先张开" in a["inference_reason"]


def test_preopen_not_added_when_video_already_shows_open():
    """视频里已经有张开动作 → 不再重复补。"""
    actions = [
        {"id": 1, "executor": "右手", "action": "右手张开手指", "mode": "transition",
         "start": 0.5, "end": 1.0, "exerts_force": True, "force_role": "抓握"},
        {"id": 2, "executor": "右手", "action": "右手手指收拢抓紧杯子", "mode": "transition",
         "start": 2.0, "end": 3.0, "exerts_force": True, "force_role": "抓握"},
    ]
    out = p.run(actions, 3.0)
    assert not [a for a in out["inferred_actions"] if "张开" in a["action"]]


def test_preopen_idempotent_when_inferred_already_present():
    """重跑（表里已有推理补出的预张开）→ 不重复补——幂等回归。"""
    actions = [
        {"id": 1, "executor": "右手", "action": "右手手指收拢抓紧杯子", "mode": "transition",
         "start": 2.0, "end": 3.0, "exerts_force": True, "force_role": "抓握"},
        {"id": 2, "executor": "右手", "action": "右手张开手指至可抓取开度", "mode": "transition",
         "start": 1.0, "end": 2.0, "exerts_force": True, "force_role": "抓握",
         "inferred": True, "inference_reason": "先验补全"},
    ]
    out = p.run(actions, 3.0)
    assert not [a for a in out["inferred_actions"] if "张开" in a["action"]]


def test_release_hold_filled_during_release_when_arm_idle():
    """释放期间手臂必然停在释放位姿不动（模板⑦）→ 补出保持位置。"""
    actions = [
        {"id": 1, "executor": "右手", "action": "右手手指张开释放杯子", "mode": "transition",
         "start": 3.0, "end": 4.0, "exerts_force": True, "force_role": "抓握"},
        {"id": 2, "executor": "右臂", "action": "右臂向后收回", "mode": "motion",
         "start": 4.5, "end": 6.0, "exerts_force": True, "force_role": "稳定"},
    ]
    out = p.run(actions, 6.0)
    holds = [a for a in out["inferred_actions"]
             if a["executor"] == "右臂" and "保持位置" in a["action"]]
    assert holds, out["inferred_actions"]
    a = holds[0]
    assert (a["start"], a["end"]) == (3.0, 4.0)
    assert a["mode"] == "maintain" and a["inferred"] is True


def test_release_hold_not_added_when_arm_already_covered():
    """释放期间手臂已有保持记录 → 不重复补。"""
    actions = [
        {"id": 1, "executor": "右手", "action": "右手手指张开释放杯子", "mode": "transition",
         "start": 3.0, "end": 4.0, "exerts_force": True, "force_role": "抓握"},
        {"id": 2, "executor": "右臂", "action": "右臂保持抬起", "mode": "maintain",
         "start": 2.0, "end": 4.5, "exerts_force": True, "force_role": "托举"},
        {"id": 3, "executor": "右臂", "action": "右臂向后收回", "mode": "motion",
         "start": 4.5, "end": 6.0, "exerts_force": True, "force_role": "稳定"},
    ]
    out = p.run(actions, 6.0)
    assert not [a for a in out["inferred_actions"]
                if a["executor"] == "右臂" and "保持位置" in a["action"]]


def test_release_hold_not_duplicated_when_release_is_short():
    """释放期只有 0.2s 时也要幂等：补出的保持和释放期一样长，重算不该再多补一条。

    幂等判定不能写成“重叠超过固定秒数”：短释放期（如 0.2s）里补出的保持自身也只有 0.2s，
    固定门槛永远不成立，离线重算一次就多一条重复保持（从冰箱取出蔬菜案例踩过的坑）。
    """
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向后拉动冰箱门", "mode": "motion",
         "start": 0.3, "end": 1.0, "exerts_force": True, "force_role": "拉"},
        {"id": 2, "executor": "右手", "action": "右手松开冰箱门", "mode": "transition",
         "start": 1.0, "end": 1.2, "exerts_force": True, "force_role": "抓握"},
        {"id": 3, "executor": "右臂", "action": "右臂向前下方伸出", "mode": "motion",
         "start": 1.2, "end": 1.8, "exerts_force": True, "force_role": "稳定"},
    ]
    first = p.run(actions, 2.0)
    holds = [a for a in first["inferred_actions"]
             if a["executor"] == "右臂" and "保持位置" in a["action"]]
    assert len(holds) == 1, first["inferred_actions"]
    # 把补出的动作并回总表再算一次——render_case 的离线重算就是这么做的
    again = p.run(actions + holds, 2.0)
    assert not [a for a in again["inferred_actions"]
                if a["executor"] == "右臂" and "保持位置" in a["action"]]


def test_hold_not_duplicated_when_already_present():
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向上抬起托举", "mode": "motion",
         "start": 4.0, "end": 6.0},
        {"id": 2, "executor": "右臂", "action": "右臂保持抬起托举", "mode": "maintain",
         "start": 6.0, "end": 10.0},
        {"id": 3, "executor": "右臂", "action": "右臂向前伸出放置", "mode": "motion",
         "start": 10.0, "end": 12.0},
    ]
    out = p.run(actions, 12.0)
    assert not [a for a in out["inferred_actions"] if a["executor"] == "右臂"]


def test_no_inference_for_unrelated_motion():
    actions = [{"id": 1, "executor": "头", "action": "头向后仰", "mode": "motion",
                "start": 12.0, "end": 13.0},
               {"id": 2, "executor": "头", "action": "头部转回", "mode": "motion",
                "start": 16.0, "end": 17.0}]
    out = p.run(actions, 18.0)
    assert not [a for a in out["inferred_actions"] if a["executor"] == "头"]


def test_arm_hold_during_hand_contact():
    """手接触箱子时，同侧手臂应停在前一动作的末端位置保持给力（稳定）。"""
    actions = [
        {"id": 1, "executor": "左臂", "action": "左臂向下伸出", "mode": "motion",
         "start": 2.0, "end": 3.5, "exerts_force": True, "force_role": "稳定"},
        {"id": 2, "executor": "左手", "action": "左手接触纸箱", "mode": "transition",
         "start": 3.5, "end": 3.8, "exerts_force": True, "force_role": "抓握"},
        {"id": 3, "executor": "左手", "action": "左手抓握纸箱", "mode": "transition",
         "start": 3.8, "end": 4.0, "exerts_force": True, "force_role": "抓握"},
        {"id": 4, "executor": "左臂", "action": "左臂向上抬起", "mode": "motion",
         "start": 4.0, "end": 5.5, "exerts_force": True, "force_role": "托举"},
    ]
    out = p.run(actions, 6.0)
    holds = [a for a in out["inferred_actions"] if a["executor"] == "左臂"]
    assert len(holds) == 1, holds
    h = holds[0]
    assert (h["start"], h["end"]) == (3.5, 4.0)
    assert h["action"] == "左臂保持伸出"
    assert h["mode"] == "maintain" and h["exerts_force"] is True
    assert h["force_role"] == "稳定"
    assert h["object"] is None
    assert h["until"] and h["until"]["ref"] == 4
    assert "接触" in h["inference_reason"]


def test_no_arm_hold_without_hand_contact():
    """手没有接触/操作物体时，手臂空档不补（避免过度推断）。"""
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向下伸出", "mode": "motion",
         "start": 0.0, "end": 2.0},
        {"id": 2, "executor": "右手", "action": "右手四指并拢", "mode": "motion",
         "start": 2.0, "end": 2.6},
        {"id": 3, "executor": "右臂", "action": "右臂向前伸出", "mode": "motion",
         "start": 3.2, "end": 4.0},
    ]
    out = p.run(actions, 5.0)
    assert not [a for a in out["inferred_actions"] if a["executor"] == "右臂"]


def test_arm_hold_not_duplicated_when_covered():
    """接触期间手臂已有保持覆盖（含手保持抓握）时，不再重复补。"""
    actions = [
        {"id": 1, "executor": "左臂", "action": "左臂向前伸出", "mode": "motion",
         "start": 0.0, "end": 2.0},
        {"id": 2, "executor": "左手", "action": "左手保持抓握纸箱", "mode": "maintain",
         "start": 2.0, "end": 3.0},
        {"id": 3, "executor": "左臂", "action": "左臂保持伸出", "mode": "maintain",
         "start": 2.0, "end": 3.0},
        {"id": 4, "executor": "左臂", "action": "左臂向上抬起", "mode": "motion",
         "start": 3.0, "end": 4.0},
    ]
    out = p.run(actions, 5.0)
    assert not [a for a in out["inferred_actions"] if a["executor"] == "左臂"]


def test_release_not_treated_as_contact():
    """松开/放下不算接触期（规则 4 不触发）；释放期的手臂静置由规则 6 承担。"""
    actions = [
        {"id": 1, "executor": "左臂", "action": "左臂向前伸出", "mode": "motion",
         "start": 0.0, "end": 2.0},
        {"id": 2, "executor": "左手", "action": "左手松开纸箱", "mode": "transition",
         "start": 2.0, "end": 2.4},
        {"id": 3, "executor": "左臂", "action": "左臂收回", "mode": "motion",
         "start": 3.2, "end": 4.0},
    ]
    out = p.run(actions, 5.0)
    holds = [a for a in out["inferred_actions"] if a["executor"] == "左臂"]
    # 不能是“接触期保持”的理由（释放不是接触）
    assert all("接触/操作物体" not in a["inference_reason"] for a in holds), holds
    # 若补了，只能是释放期手臂保持（规则 6）
    assert all("正在释放物体" in a["inference_reason"] for a in holds), holds


def test_contact_hold_not_duplicated_with_pose_hold():
    """同一个空档不能被“姿态保持”与“接触期保持”各补一条（重叠去重）。"""
    actions = [
        {"id": 1, "executor": "左臂", "action": "左臂向上抬起托举", "mode": "motion",
         "start": 0.0, "end": 2.0},
        {"id": 2, "executor": "左手", "action": "左手接触纸箱", "mode": "transition",
         "start": 4.0, "end": 4.5},
        {"id": 3, "executor": "左臂", "action": "左臂向前伸出放置", "mode": "motion",
         "start": 5.0, "end": 6.0},
    ]
    out = p.run(actions, 8.0)
    holds = [a for a in out["inferred_actions"]
             if a["executor"] == "左臂" and a["start"] >= 2.0 and a["end"] <= 5.1]
    assert len(holds) == 1, holds


def test_contact_hold_reaches_video_end():
    """手一直握着物体到视频结束，手臂在后段也必须保持。"""
    actions = [
        {"id": 1, "executor": "右臂", "action": "右臂向上抬起托举", "mode": "motion",
         "start": 0.0, "end": 2.0},
        {"id": 2, "executor": "右手", "action": "右手抓握瓶身", "mode": "transition",
         "start": 2.0, "end": 2.4},
        {"id": 3, "executor": "右手", "action": "右手保持抓握瓶身", "mode": "maintain",
         "start": 2.4, "end": 8.0},
    ]
    out = p.run(actions, 8.0)
    holds = [a for a in out["inferred_actions"] if a["executor"] == "右臂"]
    assert holds and holds[0]["action"] == "右臂保持抬起托举", holds
    assert (holds[0]["start"], holds[0]["end"]) == (2.0, 8.0)
    assert holds[0]["until"] is None


def test_ids_do_not_collide():
    actions = _walk_actions()
    out = p.run(actions, 8.0)
    ids = {a["id"] for a in actions} | {a["id"] for a in out["inferred_actions"]}
    assert len(ids) == len(actions) + len(out["inferred_actions"])
