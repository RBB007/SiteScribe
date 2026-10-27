"""Shared data model for SiteScribe.

Every module passes these objects around. This is the contract that lets
separately written code fit together, so it is only changed by the repo
manager. If you need a new field, ask - don't edit this file yourself.

A site visit is one Project:

    Project
     ├── plans:        [PlanSheet, ...]     uploaded before the visit
     ├── template_path                      Word template for the report
     └── observations: [Observation, ...]   captured during the visit
                          └── pin: PlanPin  where it is on which sheet
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


class Severity(str, Enum):
    INFO = "Info"
    MINOR = "Minor"
    MAJOR = "Major"
    CRITICAL = "Critical"
    SAFETY = "Safety"


# Pin colors on the marked-up plans and in the report, as RGB hex.
SEVERITY_COLORS = {
    Severity.INFO: "#2F80ED",      # blue
    Severity.MINOR: "#27AE60",     # green
    Severity.MAJOR: "#F2994A",     # orange
    Severity.CRITICAL: "#EB5757",  # red
    Severity.SAFETY: "#9B51E0",    # purple
}


@dataclass
class GeoPoint:
    lat: float
    lon: float


@dataclass
class PlanSheet:
    """One page of the uploaded plan set, rendered to an image."""

    name: str                 # e.g. "S-201 Second Floor Framing Plan"
    source_pdf: Path          # the uploaded plan set
    page_index: int           # 0-based page in source_pdf
    image_path: Path          # rendered PNG of this page
    width_px: int
    height_px: int
    # Optional GPS calibration: two or more (pixel point, GPS point) pairs
    # so photo GPS can be converted to a spot on the sheet.
    calibration: list[tuple[tuple[float, float], GeoPoint]] = field(default_factory=list)
    id: str = field(default_factory=_new_id)


@dataclass
class PlanPin:
    """Where an observation sits on a plan sheet.

    x and y are fractions of the sheet (0.0-1.0, origin top-left), so pins
    stay put no matter what resolution the sheet is drawn at.
    """

    sheet_id: str
    x: float
    y: float
    source: str = "manual"    # "manual", "gps", or "voice"


@dataclass
class Observation:
    """One numbered entry in the report: photo(s) + description + flag + pin."""

    photo_path: Path | None = None   # the main photo (same as photos[0])
    photos: list[Path] = field(default_factory=list)  # all photos, in order
    audio_path: Path | None = None
    description: str = ""     # typed caption, or transcript of the voice memo
    severity: Severity = Severity.INFO
    tags: list[str] = field(default_factory=list)
    action_item: str = ""     # what the engineer/contractor needs to do, if anything
    pin: PlanPin | None = None
    gps: GeoPoint | None = None
    taken_at: datetime = field(default_factory=datetime.now)
    number: int = 0           # photo number in the report (1, 2, 3...)
    include: bool = True      # False = captured but left out of the report
    # Per-photo captions for observations with more than one photo, keyed by
    # the photo path as a string (str(photo)). Photos without an entry fall
    # back to `description`.
    captions: dict[str, str] = field(default_factory=dict)
    id: str = field(default_factory=_new_id)


@dataclass
class Project:
    name: str
    site_address: str = ""
    engineer: str = ""
    visit_date: datetime = field(default_factory=datetime.now)
    plans: list[PlanSheet] = field(default_factory=list)
    template_path: Path | None = None
    observations: list[Observation] = field(default_factory=list)
    summary: str = ""         # AI-drafted, editable before export
    # Export choices from the app's options dialog, e.g.
    # {"include_photo_log": True, "include_marked_plans": True, "embed_photo_info": True}
    report_options: dict = field(default_factory=dict)

    def sheet(self, sheet_id: str) -> PlanSheet:
        return next(s for s in self.plans if s.id == sheet_id)

    def to_dict(self) -> dict:
        return asdict(self)
