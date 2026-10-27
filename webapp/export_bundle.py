"""Export bundle: the Word report plus the photos and plans that go with it.

    <report name>/
        site_visit_report.docx
        photos/<photo file>        each included photo, its entry written into
                                   EXIF, downscaled to 2560 px (HEIC -> JPEG)
        plans/<plan>_page<N>.png   each plan page that has a pin, pins drawn on

Takes the `Project` that bridge.to_project() built for the Word report, so
the visit is mapped and the plan pages rendered once per export, and writes
the zip straight to a file: a 60-photo visit is no longer held in memory
twice over.

Photos are shrunk before they go in. Phone originals run 3-12 MB each and a
zip of them is what made exports time out on the tunnel and fail to download
on a phone; at 2560 px a photo is still far larger than it prints and the zip
is a fifth the size. The originals stay on the server.
"""

from __future__ import annotations

import io
import re
import shutil
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

try:
    import sitescribe  # noqa: F401
except ImportError:  # started as `python server.py` from inside webapp/
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sitescribe import photos, plan_markup
from sitescribe.models import Observation, Project

PHOTO_MAX_PX = 2560
_JPEG_QUALITY = 88
_HEIC = {".heic", ".heif"}


def write_zip(project: Project | None, report_docx: bytes, *, name: str,
              out_path: Path, work_dir: Path) -> Path:
    """Write the bundle zip to out_path and return it. work_dir is scratch
    space for the tagged photo copies and pinned plan pages; the caller owns
    it. With no project (the visit could not be mapped) the zip holds the
    report alone."""
    folder = folder_name(name)
    out_path, work_dir = Path(out_path), Path(work_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # JPEG, PNG and docx are already compressed: storing them is as small and much faster
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(f"{folder}/site_visit_report.docx", report_docx)
        if project is None:
            return out_path
        included = [o for o in project.observations if o.include]
        for obs in included:
            for photo in _photo_paths(obs):
                try:
                    out = tagged_copy(obs, photo, work_dir / "photos")
                except Exception as exc:
                    # a photo that can't be read or tagged still belongs in the folder
                    print(f"[sitescribe] could not shrink/tag {photo}: {exc!r}", file=sys.stderr)
                    out = work_dir / "photos" / photo.name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(photo, out)
                zf.write(out, f"{folder}/photos/{out.name}")
        for arcname, png in pinned_plan_pages(project, included, work_dir / "marked"):
            zf.write(png, f"{folder}/plans/{arcname}")
    return out_path


def build_zip(project: Project | None, report_docx: bytes, *, name: str, work_dir: Path) -> io.BytesIO:
    """The same zip in memory, for the one-request /api/export/bundle route."""
    path = write_zip(project, report_docx, name=name, out_path=Path(work_dir) / "bundle.zip",
                     work_dir=work_dir)
    return io.BytesIO(path.read_bytes())


def _photo_paths(obs: Observation) -> list[Path]:
    paths = list(obs.photos) or ([obs.photo_path] if obs.photo_path else [])
    out, seen = [], set()
    for p in paths:
        p = Path(p)
        if p not in seen and p.is_file():
            seen.add(p)
            out.append(p)
    return out


def tagged_copy(obs: Observation, photo: Path, out_dir: Path) -> Path:
    """A copy of `photo` in out_dir, downscaled to PHOTO_MAX_PX and with the
    entry written into its EXIF. HEIC comes out as JPEG so it opens anywhere;
    a JPEG that is already small keeps its original pixels."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (photo.stem + ".jpg" if photo.suffix.lower() in _HEIC else photo.name)
    _shrink(photo, out)
    # the EXIF record names this photo's own caption, as the report does
    caption = (obs.captions.get(photo.name) or "").strip()
    description = obs.description.strip()
    if caption:
        description = f"{description} — {caption}" if description else caption
    tagged = replace(obs, photo_path=out, photos=[out], description=description)
    return photos.embed_observation(tagged, out)


def _shrink(src: Path, out: Path) -> None:
    from PIL import Image, ImageOps

    if src.suffix.lower() in _HEIC:
        try:
            from pillow_heif import register_heif_opener
        except ImportError as exc:
            raise ImportError("HEIC photos need pillow-heif: pip install pillow-heif") from exc
        register_heif_opener()
    with Image.open(src) as im:
        small = max(im.size) <= PHOTO_MAX_PX
        if small and src.suffix.lower() not in _HEIC:
            shutil.copyfile(src, out)      # nothing to gain from re-encoding
            return
        upright = ImageOps.exif_transpose(im)
        upright.thumbnail((PHOTO_MAX_PX, PHOTO_MAX_PX))
        exif = upright.info.get("exif")   # capture time and GPS come along; orientation is reset
        if out.suffix.lower() == ".png":
            upright.save(out, "PNG", optimize=True, **({"exif": exif} if exif else {}))
        else:
            upright.convert("RGB").save(out, "JPEG", quality=_JPEG_QUALITY,
                                        **({"exif": exif} if exif else {}))


def pinned_plan_pages(project: Project, observations: list[Observation], out_dir: Path):
    """(zip name, png path) for every plan page with at least one pin, pins
    drawn by plan_markup. Sheets come from the Project (rendered by bridge),
    so nothing is rendered twice."""
    pinned = {o.pin.sheet_id for o in observations if o.pin}
    shown = replace(project, observations=observations)
    used_stems: set = set()
    stems: dict[str, str] = {}          # one stem per source plan file
    for sheet in project.plans:
        key = str(sheet.source_pdf)
        if key not in stems:
            stems[key] = _unique(_safe(_plan_label(sheet.name)), used_stems)
        if sheet.id not in pinned:
            continue
        arcname = f"{stems[key]}_page{sheet.page_index + 1}.png"
        png = Path(out_dir) / _safe(key.replace("/", "_"))[-60:] / arcname
        try:
            yield arcname, plan_markup.sheet_image_with_pins(shown, sheet.id, png)
        except Exception as exc:
            print(f"[sitescribe] could not draw pins on {sheet.name}: {exc!r}", file=sys.stderr)


def _plan_label(sheet_name: str) -> str:
    """bridge names pages "<plan>, page N"; the zip wants "<plan>"."""
    return re.sub(r", page \d+$", "", sheet_name or "") or "plan"


def _unique(stem: str, used: set) -> str:
    """Plans.pdf uploaded twice -> "Plans", then "Plans (2)", so no image in
    the zip overwrites another when it is unzipped."""
    name, n = stem, 1
    while name.lower() in used:   # Windows and macOS file names ignore case
        n += 1
        name = f"{stem} ({n})"
    used.add(name.lower())
    return name


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9 _.-]+", "_", text).strip(" ._") or "plan"


def folder_name(name: str) -> str:
    """The report name, made safe for a folder and a zip file name."""
    return _safe(name or "Site visit report")[:80]
