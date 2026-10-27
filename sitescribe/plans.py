"""PRE-VISIT: turn an uploaded plan set into sheets you can pin photos on.

Owner: ________
Suggested library: PyMuPDF (pip install pymupdf)
"""

from __future__ import annotations

from pathlib import Path

from .models import PlanSheet


def load_plan_set(pdf_path: Path, out_dir: Path) -> list[PlanSheet]:
    """Render every page of the plan PDF to a PNG in out_dir.

    Return one PlanSheet per page, with image_path, width_px and height_px
    filled in. Use the sheet number/title from the title block as the name if
    you can find it, otherwise "Sheet 1", "Sheet 2", ...
    """
    raise NotImplementedError
