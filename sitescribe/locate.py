"""DURING VISIT: put a photo on the plan automatically from GPS.

Owner: ________
"""

from __future__ import annotations

from .models import GeoPoint, PlanPin, PlanSheet


def gps_to_pin(gps: GeoPoint, sheet: PlanSheet) -> PlanPin | None:
    """Convert a GPS point to a pin on the sheet using sheet.calibration
    (pairs of known pixel points and their GPS coordinates).

    Return PlanPin(sheet.id, x, y, source="gps") with x, y as 0-1 fractions of
    the sheet, or None if the sheet isn't calibrated or the point is off-sheet.
    The user can always drag the pin afterward.
    """
    raise NotImplementedError
