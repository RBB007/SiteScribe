"""DURING VISIT: voice memos to text.

Owner: hmmigdal
Uses the OpenAI Whisper API over HTTP (pip install requests).
Needs OPENAI_API_KEY in the environment.

transcribe raises on any failure (no key, missing file, network error, API
error) with a one-line message, so the app can tell the user what went wrong
and fall back. It never returns "" to mean "it failed".
"""

from __future__ import annotations

import os
from pathlib import Path

from .models import PlanPin, PlanSheet

_WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"
_WHISPER_MODEL = "whisper-1"
_TIMEOUT_SECONDS = 60
_CONTENT_TYPES = {
    ".webm": "audio/webm",   # browser MediaRecorder
    ".m4a": "audio/mp4",     # iPhone voice memos
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
}


def transcribe(audio_path: Path) -> str:
    """Return the text of a voice memo (wav, m4a, or webm)."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("voice.py needs an OpenAI API key: set OPENAI_API_KEY")
    audio_path = Path(audio_path)
    if not audio_path.is_file():
        raise FileNotFoundError(f"No audio file at {audio_path}")

    requests = _requests()
    content_type = _CONTENT_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")
    try:
        with audio_path.open("rb") as fh:
            response = requests.post(
                _WHISPER_URL,
                headers={"Authorization": f"Bearer {key}"},
                data={"model": _WHISPER_MODEL},
                files={"file": (audio_path.name, fh, content_type)},
                timeout=_TIMEOUT_SECONDS,
            )
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach OpenAI to transcribe audio: {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Transcription failed (OpenAI HTTP {response.status_code}): {_error_message(response)}")
    return (response.json().get("text") or "").strip()


def location_from_speech(text: str, sheets: list[PlanSheet]) -> PlanPin | None:
    """Optional stretch goal: turn phrases like "second floor, grid C-4" into
    a pin on the right sheet. Return None if the text gives no location."""
    raise NotImplementedError


# ---------------------------------------------------------------- helpers

def _error_message(response) -> str:
    """OpenAI's own error message if it sent one, else the start of the body."""
    try:
        return response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text[:300] or "no details"


def _requests():
    try:
        import requests
    except ImportError as exc:
        raise ImportError("voice.py needs requests: pip install requests") from exc
    return requests
