"""POST-VISIT: build the site visit report as a Word file.

Owner: ________
Suggested library: python-docx (pip install python-docx)

Report sections, in order:
    1. Header: project, address, engineer, visit date
    2. Summary                       (project.summary)
    3. Plan sheets with color-coded pins   (plan_markup.sheet_image_with_pins)
    4. Observations: photo + caption + severity + tags, one per block
    5. Action items table            (observations with an action_item)
    6. Photo log: number, time, sheet, severity, short description
"""

from __future__ import annotations

from pathlib import Path

from .models import Project


def build_report(project: Project, out_docx: Path) -> Path:
    """Write the report to out_docx and return it. If project.template_path is
    set, start from that .docx so the firm's styles, logo and header carry
    over."""
    raise NotImplementedError
