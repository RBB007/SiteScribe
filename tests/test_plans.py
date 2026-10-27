import pymupdf
import pytest
from PIL import Image

from sitescribe import plans


def _plan_pdf(path, pages=2, size=(2592, 1728)):   # 36" x 24" in points
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_text((100, 100), f"S-20{i + 1}", fontsize=72)
    doc.save(path)
    return path


def test_every_page_becomes_a_sheet(tmp_path):
    pdf = _plan_pdf(tmp_path / "plans.pdf")

    sheets = plans.load_plan_set(pdf, tmp_path / "sheets")

    assert [s.name for s in sheets] == ["Sheet 1", "Sheet 2"]
    assert [s.page_index for s in sheets] == [0, 1]
    for sheet in sheets:
        assert sheet.source_pdf == pdf
        assert sheet.image_path.parent == tmp_path / "sheets"
        with Image.open(sheet.image_path) as image:
            assert image.size == (sheet.width_px, sheet.height_px)
        assert max(sheet.width_px, sheet.height_px) <= 4000   # big sheets are capped
        assert sheet.width_px / sheet.height_px == pytest.approx(1.5, rel=0.01)


def test_image_plan_is_one_sheet(tmp_path):
    png = tmp_path / "site.png"
    Image.new("RGB", (800, 600), "white").save(png)

    sheets = plans.load_plan_set(png, tmp_path / "sheets")

    assert len(sheets) == 1
    assert sheets[0].image_path.exists()
