"""DURING VISIT: read and write photo metadata.

Owner: ________
Suggested library: Pillow + piexif (pip install pillow piexif)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import GeoPoint, Observation


def read_photo_metadata(photo_path: Path) -> tuple[datetime | None, GeoPoint | None]:
    """Return (time taken, GPS location) from the photo's EXIF, or None for
    whichever is missing."""
    raise NotImplementedError


def embed_observation(obs: Observation, out_path: Path) -> Path:
    """Write a copy of obs.photo_path to out_path with the observation number,
    severity, tags and description stored in the photo's EXIF/metadata, so the
    info travels with the photo file. Return out_path."""
    raise NotImplementedError
