"""POST-VISIT: the plan set with a numbered, color-coded pin for each photo.

Owner: ________
Suggested library: PyMuPDF (draw directly on the original PDF pages)
"""

from __future__ import annotations

from pathlib import Path

from .models import SEVERITY_COLORS, Project  # noqa: F401  (use SEVERITY_COLORS for pins)


def export_marked_plans(project: Project, out_pdf: Path) -> Path:
    """Write a PDF of the plan sheets with a pin at each observation.pin,
    labeled with observation.number and colored by severity, plus a severity
    legend. Return out_pdf."""
    raise NotImplementedError


def sheet_image_with_pins(project: Project, sheet_id: str, out_png: Path) -> Path:
    """Same pins, but one sheet as a PNG - used to embed plans in the Word
    report. Return out_png."""
    raise NotImplementedError
