"""POST-VISIT: the plan set with a numbered, color-coded pin for each photo.

Owner: allenmarden
Suggested library: PyMuPDF (draw directly on the original PDF pages)

sheet_image_with_pins draws on the sheet's rendered PNG with Pillow: a
filled circle per pin in its severity color, the observation number in
white, and a severity legend in the top-left corner. Pins that share a
number and a spot (several photos of one item) are drawn once.
"""

from __future__ import annotations

from pathlib import Path

from .models import SEVERITY_COLORS, Project, Severity


def export_marked_plans(project: Project, out_pdf: Path) -> Path:
    """Write a PDF of the plan sheets with a pin at each observation.pin,
    labeled with observation.number and colored by severity, plus a severity
    legend. Return out_pdf."""
    raise NotImplementedError


def sheet_image_with_pins(project: Project, sheet_id: str, out_png: Path) -> Path:
    """Same pins, but one sheet as a PNG - used to embed plans in the Word
    report. Return out_png."""
    from PIL import Image, ImageDraw

    sheet = project.sheet(sheet_id)
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(sheet.image_path) as base:
        image = base.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    radius = max(12, round(min(width, height) * 0.018))
    font = _font(round(radius * 1.1))

    drawn = set()
    pinned = [o for o in project.observations if o.pin and o.pin.sheet_id == sheet_id]
    for obs in sorted(pinned, key=lambda o: o.number):
        spot = (obs.number, round(obs.pin.x, 4), round(obs.pin.y, 4))
        if spot in drawn:
            continue
        drawn.add(spot)
        cx, cy = obs.pin.x * width, obs.pin.y * height
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                     fill=SEVERITY_COLORS[obs.severity], outline="white",
                     width=max(2, radius // 6))
        draw.text((cx, cy), str(obs.number), fill="white", font=font, anchor="mm")

    _legend(draw, radius, font)
    image.save(out_png)
    return out_png


def _legend(draw, radius: int, font) -> None:
    pad = radius
    row = round(radius * 2.4)
    dot = round(radius * 0.7)
    text_width = max(draw.textlength(s.value, font=font) for s in Severity)
    box_w = pad * 3 + dot * 2 + text_width
    box_h = pad * 2 + row * (len(Severity) - 1) + dot * 2
    draw.rectangle((0, 0, box_w, box_h), fill="white", outline="#333333", width=2)
    for i, severity in enumerate(Severity):
        cx, cy = pad + dot, pad + dot + i * row
        draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=SEVERITY_COLORS[severity])
        draw.text((cx + dot + pad, cy), severity.value, fill="#222222", font=font, anchor="lm")


def _font(size: int):
    from PIL import ImageFont

    return ImageFont.load_default(size=size)   # scalable since Pillow 10.1
