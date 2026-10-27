"""DURING VISIT: read and write photo metadata.

Owner: allenmarden
Suggested library: Pillow + piexif (pip install pillow piexif)

What embed_observation writes, so the info travels with the photo file:

    ImageDescription   "#3 [Major] Cracked beam at grid C-4"   Windows: Title
    XPSubject          the description                        Windows: Subject
    XPKeywords         severity + tags, ";"-separated          Windows: Tags
    UserComment        the whole observation as JSON          Windows: Comments
    XPTitle            "SiteScribe #3 - Major"   (other viewers; Windows prefers
    XPComment          "Action: ..."              the two tags above)
    DateTimeOriginal   obs.taken_at, only if the photo has no capture time
    GPS                obs.gps, only if the photo has no GPS of its own

JPEGs are written with piexif.insert, so the image data is not re-encoded.
PNG and WebP are re-saved losslessly through Pillow. HEIC needs pillow-heif.
"""

from __future__ import annotations

import io
import json
import shutil
from datetime import datetime
from fractions import Fraction
from pathlib import Path

from .models import GeoPoint, Observation

_EXIF_TIME_FORMAT = "%Y:%m:%d %H:%M:%S"
_JPEG_SUFFIXES = {".jpg", ".jpeg"}


def read_photo_metadata(photo_path: Path) -> tuple[datetime | None, GeoPoint | None]:
    """Return (time taken, GPS location) from the photo's EXIF, or None for
    whichever is missing."""
    exif = _load_exif(Path(photo_path))
    return _taken_at(exif), _gps(exif)


def embed_observation(obs: Observation, out_path: Path) -> Path:
    """Write a copy of obs.photo_path to out_path with the observation number,
    severity, tags and description stored in the photo's EXIF/metadata, so the
    info travels with the photo file. Return out_path."""
    piexif = _piexif()
    if obs.photo_path is None:
        raise ValueError(f"Observation #{obs.number} has no photo to embed info into")
    src = Path(obs.photo_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    exif = _load_exif(src)
    _write_observation(exif, obs)
    _fix_known_bad_tags(exif)
    exif_bytes = piexif.dump(exif)

    if src.suffix.lower() in _JPEG_SUFFIXES:
        if src.resolve() != out_path.resolve():
            shutil.copyfile(src, out_path)
        piexif.insert(exif_bytes, str(out_path))
    else:
        with _open_image(src) as image:
            fmt = image.format
            options = {"lossless": True} if fmt == "WEBP" else {}
            buffer = io.BytesIO()
            image.save(buffer, format=fmt, exif=exif_bytes, **options)
        out_path.write_bytes(buffer.getvalue())
    return out_path


# ---------------------------------------------------------------- writing

def _write_observation(exif: dict, obs: Observation) -> None:
    piexif = _piexif()
    from piexif.helper import UserComment

    zeroth, exif_ifd, gps = exif["0th"], exif["Exif"], exif["GPS"]
    severity = obs.severity.value
    description = obs.description.strip()

    headline = f"#{obs.number} [{severity}]"
    zeroth[piexif.ImageIFD.ImageDescription] = (
        f"{headline} {description}" if description else headline
    ).encode("utf-8")
    zeroth[piexif.ImageIFD.XPTitle] = _xp(f"SiteScribe #{obs.number} - {severity}")
    zeroth[piexif.ImageIFD.XPKeywords] = _xp(";".join([severity, *obs.tags]))
    if description:
        zeroth[piexif.ImageIFD.XPSubject] = _xp(description)
    if obs.action_item:
        zeroth[piexif.ImageIFD.XPComment] = _xp(f"Action: {obs.action_item}")

    exif_ifd[piexif.ExifIFD.UserComment] = UserComment.dump(
        json.dumps(_observation_record(obs), ensure_ascii=False), encoding="unicode"
    )
    if piexif.ExifIFD.DateTimeOriginal not in exif_ifd:
        exif_ifd[piexif.ExifIFD.DateTimeOriginal] = obs.taken_at.strftime(_EXIF_TIME_FORMAT)

    if obs.gps and piexif.GPSIFD.GPSLatitude not in gps:
        gps[piexif.GPSIFD.GPSVersionID] = (2, 3, 0, 0)
        gps[piexif.GPSIFD.GPSLatitudeRef] = "N" if obs.gps.lat >= 0 else "S"
        gps[piexif.GPSIFD.GPSLatitude] = _to_dms(obs.gps.lat)
        gps[piexif.GPSIFD.GPSLongitudeRef] = "E" if obs.gps.lon >= 0 else "W"
        gps[piexif.GPSIFD.GPSLongitude] = _to_dms(obs.gps.lon)


def _observation_record(obs: Observation) -> dict:
    pin = obs.pin
    return {
        "app": "SiteScribe",
        "id": obs.id,
        "number": obs.number,
        "severity": obs.severity.value,
        "tags": list(obs.tags),
        "description": obs.description,
        "action_item": obs.action_item,
        "taken_at": obs.taken_at.isoformat(timespec="seconds"),
        "gps": {"lat": obs.gps.lat, "lon": obs.gps.lon} if obs.gps else None,
        "pin": {"sheet_id": pin.sheet_id, "x": pin.x, "y": pin.y, "source": pin.source}
        if pin else None,
    }


def _xp(text: str) -> tuple[int, ...]:
    """Windows XP* tags are UTF-16LE, null-terminated, stored as BYTE."""
    return tuple((text + "\x00").encode("utf-16-le"))


def _to_dms(value: float) -> tuple[tuple[int, int], ...]:
    value = abs(value)
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = Fraction((value - degrees - minutes / 60) * 3600).limit_denominator(10000)
    return ((degrees, 1), (minutes, 1), (seconds.numerator, seconds.denominator))


def _fix_known_bad_tags(exif: dict) -> None:
    """Some phones store SceneType as an int, which piexif.dump rejects."""
    piexif = _piexif()
    scene = exif["Exif"].get(piexif.ExifIFD.SceneType)
    if isinstance(scene, int):
        exif["Exif"][piexif.ExifIFD.SceneType] = bytes([scene])


# ---------------------------------------------------------------- reading

def _load_exif(path: Path) -> dict:
    """The photo's EXIF as a piexif dict; empty IFDs if it has none."""
    piexif = _piexif()
    empty = {"0th": {}, "Exif": {}, "GPS": {}, "Interop": {}, "1st": {}, "thumbnail": None}
    if path.suffix.lower() in _JPEG_SUFFIXES:
        try:
            return piexif.load(str(path))
        except (piexif.InvalidImageDataError, ValueError):
            return empty
    with _open_image(path) as image:
        raw = image.info.get("exif")
    if not raw:
        return empty
    if not raw.startswith(b"Exif"):
        raw = b"Exif\x00\x00" + raw
    return piexif.load(raw)


def _taken_at(exif: dict) -> datetime | None:
    piexif = _piexif()
    for ifd, tag in (("Exif", piexif.ExifIFD.DateTimeOriginal),
                     ("Exif", piexif.ExifIFD.DateTimeDigitized),
                     ("0th", piexif.ImageIFD.DateTime)):
        raw = exif.get(ifd, {}).get(tag)
        if raw:
            text = raw.decode("ascii", "ignore") if isinstance(raw, bytes) else str(raw)
            try:
                return datetime.strptime(text.strip("\x00 "), _EXIF_TIME_FORMAT)
            except ValueError:
                continue
    return None


def _gps(exif: dict) -> GeoPoint | None:
    piexif = _piexif()
    gps = exif.get("GPS", {})
    try:
        lat = _from_dms(gps[piexif.GPSIFD.GPSLatitude], gps.get(piexif.GPSIFD.GPSLatitudeRef))
        lon = _from_dms(gps[piexif.GPSIFD.GPSLongitude], gps.get(piexif.GPSIFD.GPSLongitudeRef))
    except (KeyError, ZeroDivisionError, TypeError, ValueError, IndexError):
        return None
    return GeoPoint(lat, lon)


def _from_dms(dms, ref) -> float:
    degrees, minutes, seconds = (num / den for num, den in dms)
    value = degrees + minutes / 60 + seconds / 3600
    ref = ref.decode() if isinstance(ref, bytes) else (ref or "")
    return -value if ref.upper() in ("S", "W") else value


# ---------------------------------------------------------------- libraries

def _piexif():
    try:
        import piexif
    except ImportError as exc:
        raise ImportError("photos.py needs piexif: pip install piexif") from exc
    return piexif


def _open_image(path: Path):
    from PIL import Image

    if path.suffix.lower() in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener
        except ImportError as exc:
            raise ImportError("HEIC photos need pillow-heif: pip install pillow-heif") from exc
        register_heif_opener()
    return Image.open(path)
