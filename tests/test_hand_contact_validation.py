"""Regressions exposed by contact gestures and canonical opening labels."""
import pytest

from video2op.arm_hand import function
from video2op.semantic import catalog
from video2op.single_video.stages.s02b_atomic import _validate
from video2op.single_video.stages.s02c_task import _validate as validate_task


@pytest.mark.parametrize(
    "action, role, name",
    [
        ("打开", "张开", "打开"),
        ("右手食指触碰小盒", "接触", "接触"),
        ("右手食指按压小盒", "按压", "按压"),
    ],
)
def test_hand_contact_and_opening_reach_task_validation(action, role, name):
    observation = {
        "id": 1, "executor": "右手", "action": action, "mode": "transition",
        "start": 0, "end": 1, "world_before": [], "world_after": [],
    }
    _validate({"atomic_actions": [observation]})
    assert function(observation) == role
    assert "右手" in catalog()[name]["allowed_subjects"]
    validate_task({"task_nodes": [{
        "id": "node_1", "name": name, "intent_role": "建立相应接触或手形状态",
        "required_capabilities": [name],
        "tuple": {
            "X": {"subject": "右手", "parts": ["右手"]}, "O": ["小盒"],
            "C_pre": [], "C_const": [], "E": {}, "C_post": [],
            "R": [{"name": name, "origin": "observed"}],
        },
    }]})


def test_contact_support_does_not_allow_hand_bound_transport():
    with pytest.raises(ValueError, match="空间移动由同侧臂承担"):
        _validate({"atomic_actions": [{
            "id": 1, "executor": "右手", "action": "右手向右移动盒子",
            "mode": "motion", "start": 0, "end": 1,
            "world_before": [], "world_after": [],
        }]})
