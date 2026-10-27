"""Export bundle: the Word report plus the photos and plans that go with it.

    <report name>/
        site_visit_report.docx
        photos/<photo file>        each photo, with its entry written into EXIF
        plans/<plan>_page<N>.png   each plan page that has a pin, pins drawn on

Glue between visit.json and the sitescribe modules (photos, plans,
plan_markup). The JSON -> models mapping here is the minimum this export
needs; bridge.py (#8) takes it over when it lands.

Each photo entry is an observation with its own details (#27); the item's
are the fallback for records written before that. Pins are numbered by item
(001_02 -> 1), and entries of one item at the same spot share a pin.
"""

from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

try:
    import sitescribe  # noqa: F401
except ImportError:  # started as `python server.py` from inside webapp/
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sitescribe import photos, plan_markup, plans
from sitescribe.models import Observation, PlanPin, Project, Severity

_DETAILS = ("description", "importance", "tags", "location", "include")


def build_zip(data: dict, report_docx: bytes, *, name: str, item_dir, plans_dir: str) -> io.BytesIO:
    """Zip the report, tagged photos and pinned plan pages under one folder.

    item_dir(item_id) gives the folder an item's photos live in; plans_dir
    is the folder the plan files live in.
    """
    folder = folder_name(name)
    entries = list(_entries(data, item_dir))
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp, \
            zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        tmp = Path(tmp)
        zf.writestr(f"{folder}/site_visit_report.docx", report_docx)

        for obs, photo in entries:
            if photo is None:
                continue
            out = tmp / "photos" / photo.name
            try:
                photos.embed_observation(obs, out)
            except Exception as exc:
                # a photo that can't take EXIF still belongs in the folder
                print(f"[sitescribe] could not write EXIF into {photo}: {exc!r}",
                      file=sys.stderr)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(photo, out)
            zf.write(out, f"{folder}/photos/{photo.name}")

        for arcname, png in _pinned_plan_pages(data, entries, plans_dir, tmp):
            zf.write(png, f"{folder}/plans/{arcname}")
    buf.seek(0)
    return buf


def _entries(data: dict, item_dir):
    """(Observation, photo path or None) for every included entry. An entry
    whose image isn't taken yet (or an item with no entries) still has a pin
    for the plans; it just has no photo to tag."""
    for item in sorted(data.get("items", []), key=lambda it: str(it.get("item_id"))):
        entries = sorted(item.get("photos") or [], key=lambda ph: ph.get("seq") or 0)
        if not entries:
            if item.get("include", True):
                yield _observation(item, {}, None), None
            continue
        for ph in entries:
            if ph.get("include", item.get("include", True)) is False:
                continue
            path = Path(item_dir(item["item_id"])) / ph["filename"] if ph.get("filename") else None
            if path is not None and not path.exists():
                path = None
            yield _observation(item, ph, path), path


def _observation(item: dict, ph: dict, path: Path | None) -> Observation:
    details = {k: ph.get(k, item.get(k)) for k in _DETAILS}
    description = (details["description"] or "").strip()
    caption = (ph.get("caption") or "").strip()
    if caption:
        description = f"{description} — {caption}" if description else caption
    obs = Observation(
        photo_path=path,
        description=description,
        severity=_severity(details["importance"]),
        tags=list(details["tags"] or []),
        pin=_pin(details["location"]),
        number=_number(item.get("item_id")),
        id=str(ph.get("photo_id") or item.get("item_id")),
    )
    taken = _parse_time(ph.get("created") or item.get("created"))
    if taken:
        obs.taken_at = taken
    return obs


def _pinned_plan_pages(data: dict, entries, plans_dir: str, tmp: Path):
    """(zip name, png path) for every plan page with at least one pin."""
    observations = [obs for obs, _ in entries]
    pinned = {obs.pin.sheet_id for obs in observations if obs.pin}
    used_stems = set()
    for plan in data.get("plans", []):
        plan_id = plan.get("plan_id")
        if not any(sheet_id.startswith(f"{plan_id}:") for sheet_id in pinned):
            continue
        source = Path(plans_dir) / plan["file"]
        try:
            sheets = plans.load_plan_set(source, tmp / "sheets" / str(plan_id))
        except Exception as exc:
            print(f"[sitescribe] could not render plan {source}: {exc!r}", file=sys.stderr)
            continue
        for sheet in sheets:
            sheet.id = _sheet_id(plan_id, sheet.page_index + 1)
        project = Project(name="export", plans=sheets, observations=observations)
        stem = _unique(_safe(Path(plan.get("name") or plan["file"]).stem), used_stems)
        for sheet in sheets:
            if sheet.id not in pinned:
                continue
            arcname = f"{stem}_page{sheet.page_index + 1}.png"
            png = tmp / "marked" / str(plan_id) / arcname
            yield arcname, plan_markup.sheet_image_with_pins(project, sheet.id, png)


def _unique(stem: str, used: set) -> str:
    """Plans.pdf uploaded twice -> "Plans", then "Plans (2)", so no image in
    the zip overwrites another when it is unzipped."""
    name, n = stem, 1
    while name.lower() in used:   # Windows and macOS file names ignore case
        n += 1
        name = f"{stem} ({n})"
    used.add(name.lower())
    return name


def _sheet_id(plan_id, page) -> str:
    return f"{plan_id}:{page}"


def _pin(location) -> PlanPin | None:
    if not location or not location.get("plan_id"):
        return None
    return PlanPin(_sheet_id(location["plan_id"], int(location.get("page") or 1)),
                   float(location["x"]), float(location["y"]))


def _severity(value) -> Severity:
    try:
        return Severity(value)
    except ValueError:
        return Severity.INFO


def _number(item_id) -> int:
    """I-003 -> 3, and 003 -> 3 after #27's ids."""
    match = re.search(r"\d+", str(item_id or ""))
    return int(match.group()) if match else 0


def _parse_time(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _.-]+", "_", text).strip(" ._") or "plan"


def folder_name(name: str) -> str:
    """The report name, made safe for a folder and a zip file name."""
    return _safe(name or "Site visit report")[:80]
