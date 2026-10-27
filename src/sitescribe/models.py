"""Shared data model for SiteScribe.

Every module reads or produces Observation objects. Keep this file stable:
changes go through a PR reviewed by the integration lead.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class MediaType(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"


class Severity(str, Enum):
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


@dataclass
class PlanLocation:
    """A point on a plan sheet.

    x and y are normalized to the sheet (0.0 to 1.0, origin at top-left),
    so locations survive resizing or re-rendering the plan image.
    """

    plan_id: str
    x: float
    y: float
    label: str | None = None  # e.g. "Grid C-4" or "Level 2, NE corner"


@dataclass
class Observation:
    media_type: MediaType
    source_path: Path | None = None  # original file; None for typed text notes
    text: str = ""  # typed note, or transcript of audio/video
    location: PlanLocation | None = None
    severity: Severity = Severity.INFO
    tags: list[str] = field(default_factory=list)
    author: str = ""
    captured_at: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
