import os
from pathlib import Path

import pytest
import requests

from sitescribe import voice


class _FakeResponse:
    def __init__(self, status_code, body=None, text=""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if self._body is None:
            raise ValueError("no JSON")
        return self._body


def _memo(tmp_path, name="memo.webm"):
    path = tmp_path / name
    path.write_bytes(b"\x1aE\xdf\xa3 not really audio")
    return path


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


@pytest.fixture
def fake_post(monkeypatch):
    """Replace requests.post; record each call and return the queued response."""
    calls = []
    reply = {"response": _FakeResponse(200, {"text": ""})}

    def post(url, **kw):
        calls.append({"url": url, **kw, "filename": kw["files"]["file"][0],
                      "content_type": kw["files"]["file"][2]})
        if isinstance(reply["response"], Exception):
            raise reply["response"]
        return reply["response"]

    monkeypatch.setattr(requests, "post", post)
    return calls, reply


def test_transcribe_returns_trimmed_text(tmp_path, api_key, fake_post):
    calls, reply = fake_post
    reply["response"] = _FakeResponse(200, {"text": "  Cracked beam at grid C-4, about 3 mm wide.\n"})

    text = voice.transcribe(_memo(tmp_path))

    assert text == "Cracked beam at grid C-4, about 3 mm wide."
    [call] = calls
    assert call["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert call["headers"] == {"Authorization": "Bearer sk-test"}
    assert call["data"] == {"model": "whisper-1"}
    assert call["filename"] == "memo.webm"
    assert call["content_type"] == "audio/webm"


@pytest.mark.parametrize("name, content_type", [
    ("memo.webm", "audio/webm"), ("memo.m4a", "audio/mp4"), ("memo.wav", "audio/wav"),
    ("MEMO.WAV", "audio/wav"), ("memo.xyz", "application/octet-stream"),
])
def test_transcribe_sends_the_right_audio_type(tmp_path, api_key, fake_post, name, content_type):
    calls, reply = fake_post
    reply["response"] = _FakeResponse(200, {"text": "ok"})

    voice.transcribe(_memo(tmp_path, name))

    assert calls[0]["filename"] == name
    assert calls[0]["content_type"] == content_type


def test_transcribe_accepts_a_string_path(tmp_path, api_key, fake_post):
    _, reply = fake_post
    reply["response"] = _FakeResponse(200, {"text": "ok"})

    assert voice.transcribe(str(_memo(tmp_path))) == "ok"


def test_silent_memo_returns_empty_text(tmp_path, api_key, fake_post):
    _, reply = fake_post
    reply["response"] = _FakeResponse(200, {"text": "   "})

    assert voice.transcribe(_memo(tmp_path)) == ""


def test_missing_key_raises_clear_error(tmp_path, monkeypatch, fake_post):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    calls, _ = fake_post

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        voice.transcribe(_memo(tmp_path))
    assert calls == []


def test_missing_file_raises(tmp_path, api_key, fake_post):
    calls, _ = fake_post

    with pytest.raises(FileNotFoundError, match="nope.webm"):
        voice.transcribe(tmp_path / "nope.webm")
    assert calls == []


def test_api_error_raises_with_openai_message(tmp_path, api_key, fake_post):
    _, reply = fake_post
    reply["response"] = _FakeResponse(401, {"error": {"message": "Incorrect API key provided"}})

    with pytest.raises(RuntimeError, match=r"HTTP 401.*Incorrect API key provided"):
        voice.transcribe(_memo(tmp_path))


def test_api_error_without_json_raises_with_body(tmp_path, api_key, fake_post):
    _, reply = fake_post
    reply["response"] = _FakeResponse(502, text="Bad Gateway")

    with pytest.raises(RuntimeError, match=r"HTTP 502.*Bad Gateway"):
        voice.transcribe(_memo(tmp_path))


def test_network_error_raises(tmp_path, api_key, fake_post):
    _, reply = fake_post
    reply["response"] = requests.ConnectionError("no route to host")

    with pytest.raises(RuntimeError, match="Could not reach OpenAI.*no route to host"):
        voice.transcribe(_memo(tmp_path))


def test_transcribe_real_recording():
    """Sends a real recording to OpenAI. Set OPENAI_API_KEY and
    SITESCRIBE_TEST_AUDIO (path to a short webm/m4a/wav you recorded) to run it."""
    sample = os.environ.get("SITESCRIBE_TEST_AUDIO")
    if not os.environ.get("OPENAI_API_KEY") or not sample:
        pytest.skip("set OPENAI_API_KEY and SITESCRIBE_TEST_AUDIO to run against the real API")

    text = voice.transcribe(Path(sample))

    assert text.strip()
