import json
from datetime import datetime

import piexif
import pytest
from piexif.helper import UserComment
from PIL import Image

from sitescribe import photos
from sitescribe.models import GeoPoint, Observation, PlanPin, Severity


def _photo(path, exif=None):
    image = Image.new("RGB", (64, 48), "gray")
    if exif is None:
        image.save(path)
    else:
        image.save(path, exif=piexif.dump(exif))
    return path


def _phone_exif(lat=61.2181, lon=-149.9003, taken="2026:10:27 09:15:00"):
    return {
        "0th": {}, "1st": {}, "Interop": {}, "thumbnail": None,
        "Exif": {piexif.ExifIFD.DateTimeOriginal: taken},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: "N" if lat >= 0 else "S",
            piexif.GPSIFD.GPSLatitude: photos._to_dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: "E" if lon >= 0 else "W",
            piexif.GPSIFD.GPSLongitude: photos._to_dms(lon),
        },
    }


def _observation(photo_path, **kw):
    fields = dict(
        photo_path=photo_path, description="Cracked beam at grid C-4 — 3 mm wide",
        severity=Severity.MAJOR, tags=["Crack", "Concrete"], action_item="EOR to review",
        pin=PlanPin("sheet1", 0.4, 0.6), number=3, taken_at=datetime(2026, 10, 27, 10, 0),
    )
    fields.update(kw)
    return Observation(**fields)


def _xp_text(value):
    return bytes(value).decode("utf-16-le").rstrip("\x00")


def test_read_time_and_gps_from_phone_photo(tmp_path):
    path = _photo(tmp_path / "a.jpg", _phone_exif())

    taken, gps = photos.read_photo_metadata(path)

    assert taken == datetime(2026, 10, 27, 9, 15)
    assert gps.lat == pytest.approx(61.2181, abs=1e-5)
    assert gps.lon == pytest.approx(-149.9003, abs=1e-5)


def test_read_photo_without_exif_returns_none(tmp_path):
    assert photos.read_photo_metadata(_photo(tmp_path / "plain.jpg")) == (None, None)
    assert photos.read_photo_metadata(_photo(tmp_path / "plain.png")) == (None, None)


def test_embed_writes_entry_into_jpeg(tmp_path):
    src = _photo(tmp_path / "001.jpg", _phone_exif())
    obs = _observation(src)

    out = photos.embed_observation(obs, tmp_path / "output" / "001.jpg")

    assert out == tmp_path / "output" / "001.jpg"
    exif = piexif.load(str(out))
    zeroth = exif["0th"]
    assert zeroth[piexif.ImageIFD.ImageDescription].decode("utf-8") == (
        "#3 [Major] Cracked beam at grid C-4 — 3 mm wide")
    assert _xp_text(zeroth[piexif.ImageIFD.XPTitle]) == "SiteScribe #3 - Major"
    assert _xp_text(zeroth[piexif.ImageIFD.XPKeywords]) == "Major;Crack;Concrete"
    assert _xp_text(zeroth[piexif.ImageIFD.XPSubject]) == obs.description
    assert _xp_text(zeroth[piexif.ImageIFD.XPComment]) == "Action: EOR to review"

    record = json.loads(UserComment.load(exif["Exif"][piexif.ExifIFD.UserComment]))
    assert record["number"] == 3
    assert record["severity"] == "Major"
    assert record["tags"] == ["Crack", "Concrete"]
    assert record["pin"] == {"sheet_id": "sheet1", "x": 0.4, "y": 0.6, "source": "manual"}

    # the phone's own capture time and GPS are kept, not overwritten
    taken, gps = photos.read_photo_metadata(out)
    assert taken == datetime(2026, 10, 27, 9, 15)
    assert gps.lat == pytest.approx(61.2181, abs=1e-5)
    # the source photo is left alone, and the pixels are not re-encoded
    assert piexif.ImageIFD.XPTitle not in piexif.load(str(src))["0th"]
    assert Image.open(out).tobytes() == Image.open(src).tobytes()


def test_embed_fills_in_missing_time_and_gps(tmp_path):
    src = _photo(tmp_path / "002.jpg")
    obs = _observation(src, gps=GeoPoint(-33.8688, 151.2093))

    taken, gps = photos.read_photo_metadata(photos.embed_observation(obs, tmp_path / "out.jpg"))

    assert taken == datetime(2026, 10, 27, 10, 0)
    assert gps.lat == pytest.approx(-33.8688, abs=1e-5)
    assert gps.lon == pytest.approx(151.2093, abs=1e-5)


def test_embed_writes_entry_into_png(tmp_path):
    src = _photo(tmp_path / "003.png")
    out = photos.embed_observation(_observation(src, description=""), tmp_path / "out.png")

    exif = photos._load_exif(out)
    assert exif["0th"][piexif.ImageIFD.ImageDescription] == b"#3 [Major]"
    assert piexif.ImageIFD.XPSubject not in exif["0th"]
    assert Image.open(out).tobytes() == Image.open(src).tobytes()


def test_embed_copies_the_photo_named_by_out_path(tmp_path):
    main = tmp_path / "003_main.jpg"
    Image.new("RGB", (64, 48), "red").save(main)
    second = tmp_path / "003_second.jpg"
    Image.new("RGB", (64, 48), "blue").save(second)
    obs = _observation(main)
    obs.photos = [main, second]   # Observation.photos once models.py has it

    out_second = photos.embed_observation(obs, tmp_path / "output" / second.name)
    out_other = photos.embed_observation(obs, tmp_path / "output" / "renamed.jpg")

    assert Image.open(out_second).tobytes() == Image.open(second).tobytes()
    assert Image.open(out_other).tobytes() == Image.open(main).tobytes()
    assert piexif.ImageIFD.XPTitle in piexif.load(str(out_second))["0th"]


def test_embed_without_photo_raises():
    with pytest.raises(ValueError, match="no photo"):
        photos.embed_observation(Observation(number=1), "out.jpg")
