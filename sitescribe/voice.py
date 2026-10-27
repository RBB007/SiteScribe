"""DURING VISIT: voice memos to text.

Owner: ________
Suggested: OpenAI Whisper API, or the local openai-whisper package.
"""

from __future__ import annotations

from pathlib import Path

from .models import PlanPin, PlanSheet


def transcribe(audio_path: Path) -> str:
    """Return the text of a voice memo (wav, m4a, or webm)."""
    raise NotImplementedError


def location_from_speech(text: str, sheets: list[PlanSheet]) -> PlanPin | None:
    """Optional stretch goal: turn phrases like "second floor, grid C-4" into
    a pin on the right sheet. Return None if the text gives no location."""
    raise NotImplementedError
