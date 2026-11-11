from threading import Barrier
from types import SimpleNamespace

from test_goal_effect_learning import scoped_case

from video2op import evidence, knowledge, media_quality, pipeline
from video2op.llm import VLMClient


def test_two_independent_model_clients_run_in_parallel_and_merge_stats(tmp_path, monkeypatch):
    barrier, seen = Barrier(2), []
    def branch(client, ctx):
        seen.append(id(client))
        barrier.wait(timeout=3)
        client.stats["calls"] += 1
        return {"ok": True}
    monkeypatch.setattr(pipeline.s02a_intent, "run", branch)
    monkeypatch.setattr(pipeline.s02b_atomic, "run", branch)
    client = VLMClient(tmp_path/"cache")
    ctx = {}
    def stage(name, fn, key, default):
        ctx[key] = fn()
    pipeline.run_observation_branches(stage, client, ctx)
    assert len(set(seen)) == 2
    assert client.stats["calls"] == 2
    assert ctx["intents"] == ctx["windows"] == {"ok": True}


def test_parallel_branch_failure_is_reported_after_other_branch_finishes(tmp_path, monkeypatch):
    barrier, completed = Barrier(2), []
    def fail(*args):
        barrier.wait(timeout=3)
        raise ValueError("intent unavailable")
    def succeed(*args):
        barrier.wait(timeout=3)
        completed.append(True)
        return {}
    monkeypatch.setattr(pipeline.s02a_intent, "run", fail)
    monkeypatch.setattr(pipeline.s02b_atomic, "run", succeed)
    import pytest
    with pytest.raises(ValueError, match="intent unavailable"):
        pipeline.run_observation_branches(lambda n, fn, k, d: fn(), VLMClient(tmp_path/"cache"), {})
    assert completed


def test_zero_exit_decoder_with_errors_does_not_claim_complete_coverage(monkeypatch):
    monkeypatch.setattr(media_quality.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout="frame=487\nout_time_us=16415730\nprogress=end\n",
        stderr="partial file"))
    result = media_quality.audit("source.mp4")
    assert not result["coverage_verified"]
    assert result["status"] == "decode_warning"
    assert result["decoded_until_seconds"] == 16.41573


def test_unavailable_tail_never_becomes_observed_state_or_success():
    b = scoped_case()
    b["meta"]["media_quality"] = {"status": "decode_warning", "coverage_verified": False,
                                  "decoded_until_seconds": 1.0}
    media_quality.annotate(b)
    a = b["atomic"]["atomic_actions"][1]
    assert evidence.observed_state(a) == ""
    assert evidence.observed_states(a) == []
    item = next(i for i in knowledge.extract(b, "case/result.json")["instances"]
                if i["goal_key"] == "acquire_object")
    assert item["outcome"] == "unknown"
    assert item["outcome_status"] == "unverified"
