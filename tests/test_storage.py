import json
from pathlib import Path

from sitescribe import storage
from sitescribe.models import GeoPoint, Observation, PlanPin, PlanSheet, Project, Severity


def test_project_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path)
    sheet = PlanSheet("S-201", Path("plans.pdf"), 0, Path("s201.png"), 3400, 2200,
                      calibration=[((10.0, 20.0), GeoPoint(61.2, -149.9))])
    project = Project(name="Test Job", plans=[sheet], report_options={"include_photo_log": True})
    project.observations.append(Observation(
        photo_path=Path("001.jpg"), photos=[Path("001.jpg"), Path("001b.jpg")], description="Crack at beam end", severity=Severity.MAJOR,
        tags=["Crack"], pin=PlanPin(sheet.id, 0.4, 0.6), gps=GeoPoint(61.2, -149.9), number=1,
        include=False, captions={"001.jpg": "Beam end", "001b.jpg": "Close-up"},
    ))

    loaded = storage.load_project(storage.save_project(project))

    assert loaded == project


def test_observation_defaults_include_everything():
    obs = Observation()
    assert obs.include is True
    assert obs.captions == {}


def test_load_project_saved_before_include_and_captions(tmp_path):
    # A project.json written before these fields existed must still load,
    # with every observation included and no captions.
    project = Project(name="Old Job", observations=[Observation(description="x")])
    data = project.to_dict()
    for obs in data["observations"]:
        del obs["include"]
        del obs["captions"]
    path = tmp_path / "project.json"
    path.write_text(json.dumps(data, default=storage._encode))

    loaded = storage.load_project(path)

    assert loaded.observations[0].include is True
    assert loaded.observations[0].captions == {}
