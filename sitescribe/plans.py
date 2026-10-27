"""PRE-VISIT: turn an uploaded plan set into sheets you can pin photos on.

Owner: allenmarden
Suggested library: PyMuPDF (pip install pymupdf)

Pages render at 150 dpi, capped so the long side is at most 4000 px; a
36" x 24" sheet comes out 4000 x 2667. PyMuPDF also opens JPEG/PNG plans,
which come back as a single sheet.
"""

from __future__ import annotations

from pathlib import Path

from .models import PlanSheet

_DPI = 150
_MAX_SIDE_PX = 4000


def load_plan_set(pdf_path: Path, out_dir: Path) -> list[PlanSheet]:
    """Render every page of the plan PDF to a PNG in out_dir.

    Return one PlanSheet per page, with image_path, width_px and height_px
    filled in. Use the sheet number/title from the title block as the name if
    you can find it, otherwise "Sheet 1", "Sheet 2", ...
    """
    pymupdf = _pymupdf()
    pdf_path, out_dir = Path(pdf_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sheets = []
    with pymupdf.open(pdf_path) as doc:
        for index, page in enumerate(doc):
            zoom = min(_DPI / 72, _MAX_SIDE_PX / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            image_path = out_dir / f"{pdf_path.stem}_p{index + 1:03d}.png"
            pix.save(image_path)
            sheets.append(PlanSheet(
                name=f"Sheet {index + 1}",
                source_pdf=pdf_path,
                page_index=index,
                image_path=image_path,
                width_px=pix.width,
                height_px=pix.height,
            ))
    return sheets


def _pymupdf():
    try:
        import pymupdf
    except ImportError as exc:
        raise ImportError("plans.py needs PyMuPDF: pip install pymupdf") from exc
    return pymupdf
