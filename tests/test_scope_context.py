"""Target effects and neighboring-object context have separate source roles."""
from copy import deepcopy

import pytest

from video2op.stages.s08_scope import validate


def fixture():
    ctx = {"atomic": {"atomic_actions": [
        {"id": 5, "object": "container", "start": 0, "end": 1},
        {"id": 6, "object": "target", "start": 1, "end": 2},
    ]}}
    payload = {"objects": [], "subtasks": [
        {"id": "s", "goal_key": "acquire_object", "target": "target",
         "atomic_refs": [6], "context_atomic_refs": [5], "outcome": "unknown"}
    ]}
    return ctx, payload


def test_context_preserved_without_proving_target_outcome():
    ctx, payload = fixture()
    before = deepcopy(payload)
    validate(payload, ctx)
    assert payload == before


def test_wrong_object_feedback_identifies_subtask_action_and_object():
    ctx, payload = fixture()
    payload["subtasks"][0].update(atomic_refs=[5, 6], context_atomic_refs=[])
    with pytest.raises(ValueError, match=r"atomic_ref.*5.*container"):
        validate(payload, ctx)


@pytest.mark.parametrize("refs", [[99], [6], "5"])
def test_context_reference_must_resolve_and_remain_separate(refs):
    ctx, payload = fixture()
    payload["subtasks"][0]["context_atomic_refs"] = refs
    with pytest.raises(ValueError, match="context_atomic_refs"):
        validate(payload, ctx)
