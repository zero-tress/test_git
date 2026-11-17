"""The project must never silently send analysis to another model or endpoint."""
import pytest

from video2op.llm import VLMClient, require_deployed_model


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:8033", "https://127.0.0.1:8032",
    "http://example.com:8032", "http://127.0.0.1:8032/proxy",
    "http://user:secret@127.0.0.1:8032", "http://127.0.0.1:8032?target=other",
])
def test_other_services_rejected_before_cache_creation(tmp_path, endpoint):
    cache = tmp_path / "cache"
    with pytest.raises(ValueError, match=r"qwen3\.8-27b"):
        VLMClient(cache, base_url=endpoint)
    assert not cache.exists()


def test_other_model_and_mutated_client_cannot_reuse_cache(tmp_path):
    with pytest.raises(ValueError):
        VLMClient(tmp_path, model="another-model")
    client = VLMClient(tmp_path)
    client.model = "another-model"
    with pytest.raises(ValueError):
        client.ask(stage="test", system="", user_text="")
    assert not client.stats["calls"]


@pytest.mark.parametrize("endpoint", [
    "http://127.0.0.1:8032", "http://localhost:8032/", "http://[::1]:8032",
])
def test_authorized_loopback_allowed(endpoint):
    require_deployed_model(endpoint, "qwen3.8-27b")


def test_cache_missing_model_provenance_requires_real_model_call(tmp_path, monkeypatch):
    import json

    client = VLMClient(tmp_path)
    key = client._fingerprint("test", "s", "u", "", 0.1, 16840)
    (tmp_path / (key + ".json")).write_text(json.dumps(
        {"complete": True, "result": {"origin": "unproven"}}))
    class Response:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": '{"origin":"deployed_model"}'},
                                  "finish_reason": "stop"}]}
    sent = []
    def post(*args, **kwargs):
        sent.append(kwargs)
        return Response()
    monkeypatch.setattr(client.session, "post", post)
    assert client.ask(stage="test", system="s", user_text="u")["origin"] == "deployed_model"
    assert sent[0]["allow_redirects"] is False
    cache = json.loads((tmp_path / (key + ".json")).read_text())
    assert cache["model"] == "qwen3.8-27b"
    assert cache["raw_response"] == '{"origin":"deployed_model"}'


def test_retry_keeps_all_previous_validation_errors(tmp_path, monkeypatch):
    import json

    client = VLMClient(tmp_path)
    replies = iter([{"a": True}, {"b": True}, {"a": True, "b": True}])
    sent = []
    class Response:
        status_code = 200
        def __init__(self, value):
            self.value = value
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(self.value)},
                                  "finish_reason": "stop"}]}
    def post(*args, **kwargs):
        sent.append(kwargs["json"])
        return Response(next(replies))
    def validate(value):
        for key in ["a", "b"]:
            if key not in value:
                raise ValueError("missing_" + key)
    monkeypatch.setattr(client.session, "post", post)
    client.ask(stage="test", system="s", user_text="u", validator=validate)
    feedback = sent[2]["messages"][-1]["content"]
    assert "missing_a" in feedback and "missing_b" in feedback
    assert client.stats["calls"] == 3


def test_resume_sends_rejected_draft_back_to_model_without_accepting_it(tmp_path, monkeypatch):
    import json
    from video2op.llm import LLMError

    client = VLMClient(tmp_path)
    class Response:
        status_code = 200
        def __init__(self, value):
            self.value = value
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(self.value)},
                                  "finish_reason": "stop"}]}
    def validate(value):
        if "b" not in value:
            raise ValueError("missing_b")
    monkeypatch.setattr(client.session, "post", lambda *a, **k: Response({"a": True}))
    with pytest.raises(LLMError):
        client.ask(stage="test", system="s", user_text="u", validator=validate, attempts=1)
    resumed = VLMClient(tmp_path)
    sent = []
    def post(*args, **kwargs):
        sent.append(kwargs["json"])
        return Response({"a": True, "b": True})
    monkeypatch.setattr(resumed.session, "post", post)
    result = resumed.ask(stage="test", system="s", user_text="u", validator=validate)
    assert result == {"a": True, "b": True}
    assert resumed.stats["calls"] == 1
    assert "missing_b" in sent[0]["messages"][-1]["content"]
    assert '"a": true' in sent[0]["messages"][-1]["content"]
    complete = next(tmp_path.glob("test_*.json"))
    assert json.loads(complete.read_text())["prior_repair_records"]
