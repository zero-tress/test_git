"""Refresh declarations and stage artifacts without overwriting source observations."""
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from test_video_learning_logic import v2_case
from test_case_graph import scope_stub
from video2op.single_video.case_scope_review import SCOPE_SYSTEM
from tools import learn_video_knowledge as cli
from video2op import config, llm
from video2op.single_video import case_graph
from video2op.contracts.learning_contracts import CASE_SYSTEM, fingerprint, policy_prompt, task_contract


def prepared(tmp_path, monkeypatch):
    video = tmp_path / "source.mp4"
    video.write_bytes(b"synthetic-test-media-not-decoded")
    output = tmp_path / "run"
    case = output / "cases/source_semantic_v3"
    case.mkdir(parents=True)
    bundle, graph = v2_case()
    old_policy = {"policy_id": "old"}
    bundle.update(case_graph=graph, task_contract=task_contract(old_policy),
                  observed_operation_graph={"nodes": deepcopy(bundle["atomic"]["atomic_actions"])},
                  pipeline={**bundle["pipeline"], "llm_stats": {"calls": 2, "cache_hits": 0, "attempts": []}})
    source = case / "result.json"
    source.write_text(json.dumps(bundle))
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = {"model": config.MODEL, "endpoint": config.BASE_URL, "status": "complete",
                "description_sha256": hashlib.sha256(b"").hexdigest(), "code_sha256": "test-code",
                "case_prompt_fingerprint": fingerprint([SCOPE_SYSTEM, CASE_SYSTEM, policy_prompt(old_policy)]),
                "graph_requirements_sha256": fingerprint(old_policy),
                "cases": [{"video": str(video), "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                           "status": "complete", "result": str(source), "result_sha256": source_hash}]}
    (output / "run_manifest.json").write_text(json.dumps(manifest))
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps(old_policy))
    monkeypatch.setattr(cli, "source_fingerprint", lambda: "test-code")
    monkeypatch.setattr(config, "OUTPUT_DIR", config.OUTPUT_DIR)
    monkeypatch.setattr(config, "WORK_DIR", config.WORK_DIR)
    argv = ["--videos", str(video), "--out", str(output), "--graph-requirements", str(policy),
            "--resume", "--allow-8032"]
    return argv, output, source, source_hash, policy, bundle


def test_policy_refresh_uses_new_declaration_before_model_call_and_synchronizes_exports(tmp_path, monkeypatch):
    argv, output, source, source_hash, policy, original = prepared(tmp_path, monkeypatch)
    new_policy = {"policy_id": "new"}
    policy.write_text(json.dumps(new_policy))
    source_before = source.read_bytes()
    class Client:
        def __init__(self, *args, **kwargs):
            self.stats = {"calls": 1, "cache_hits": 0, "failures": 0, "seconds": 0, "attempts": []}
            self.session = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(llm, "VLMClient", Client)
    def relearn(client, bundle, requirements):
        assert bundle["task_contract"] == task_contract(new_policy)
        assert bundle["observed_operation_graph"] == original["observed_operation_graph"]
        graph = deepcopy(original["case_graph"])
        graph.update(graph_requirements=requirements, unresolved=["refreshed synthetic model result"])
        return graph
    monkeypatch.setattr(case_graph, "learn", relearn)
    cross_calls = []
    monkeypatch.setattr(cli.learn_semantic_graph, "main", lambda args: cross_calls.append(args) or 0)
    assert cli.main(argv + ["--refresh-prompts", "--refresh-case-graph"]) == 0
    saved = json.loads(source.read_text())
    assert saved["pipeline"]["llm_stats"]["calls"] == 3
    case = source.parent
    assert saved["case_graph"] == json.loads((case / "stages/s09_case_graph.json").read_text())
    assert saved["case_graph"] == json.loads((case / "G_case.json").read_text())
    assert (case / "history" / source_hash / "result.json").read_bytes() == source_before
    final = json.loads((output / "run_manifest.json").read_text())
    assert final["status"] == "complete"
    assert final["cases"][0]["result_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert final["graph_requirements_sha256"] == fingerprint(new_policy)
    assert "--refresh-sources" in cross_calls[0]


@pytest.mark.parametrize("change", ["policy", "video", "source_result", "code", "prompt"])
def test_resume_refuses_changed_inputs_without_required_refresh(tmp_path, monkeypatch, change):
    argv, output, source, source_hash, policy, bundle = prepared(tmp_path, monkeypatch)
    if change == "policy":
        policy.write_text('{"policy_id":"changed"}')
    elif change == "video":
        (tmp_path / "source.mp4").write_bytes(b"changed-media")
    elif change == "source_result":
        source.write_text(json.dumps({**bundle, "unapproved_change": True}))
    elif change == "code":
        monkeypatch.setattr(cli, "source_fingerprint", lambda: "changed-code")
    else:
        manifest = json.loads((output / "run_manifest.json").read_text())
        manifest["case_prompt_fingerprint"] = "different-prompt"
        (output / "run_manifest.json").write_text(json.dumps(manifest))
    with pytest.raises((SystemExit, RuntimeError)):
        cli.main(argv)


def test_refreshed_task_contract_supersedes_legacy_policy_text():
    bundle, graph = v2_case()
    bundle["task_contract"] = task_contract({"policy_id": "new"})
    bundle["text_description"] = {"text": "obsolete-declaration-must-not-be-sent"}
    class Client:
        model = "qwen3.8-27b"
        base_url = "http://127.0.0.1:8032"
        def ask(self, **kwargs):
            assert "obsolete-declaration-must-not-be-sent" not in kwargs["user_text"]
            assert '"policy_id": "new"' in kwargs["user_text"]
            if kwargs["stage"] == "s09_scope_roles":
                return scope_stub(kwargs)
            kwargs["validator"](graph)
            return deepcopy(graph)
    case_graph.learn(Client(), bundle)
