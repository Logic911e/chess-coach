import io
import json

from chess_coach.llm import OllamaClient


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch, reply="hi"):
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data)
        return _Response(json.dumps({"message": {"content": reply}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return sent


def test_plain_chat_sends_no_format(monkeypatch):
    sent = _capture(monkeypatch)
    assert OllamaClient(host="http://x").chat([{"role": "user", "content": "q"}]) == "hi"
    assert "format" not in sent["body"]


def test_a_schema_is_passed_to_ollama_as_the_format(monkeypatch):
    sent = _capture(monkeypatch, reply='{"sentences": []}')
    schema = {"type": "object"}
    OllamaClient(host="http://x").chat([{"role": "user", "content": "q"}], format=schema)
    assert sent["body"]["format"] == schema and sent["body"]["stream"] is False
