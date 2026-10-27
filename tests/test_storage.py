from pathlib import Path

from sitescribe import storage
from sitescribe.models import GeoPoint, Observation, PlanPin, PlanSheet, Project, Severity


def test_project_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "PROJECTS_DIR", tmp_path)
    sheet = PlanSheet("S-201", Path("plans.pdf"), 0, Path("s201.png"), 3400, 2200,
                      calibration=[((10.0, 20.0), GeoPoint(61.2, -149.9))])
    project = Project(name="Test Job", plans=[sheet])
    project.observations.append(Observation(
        photo_path=Path("001.jpg"), description="Crack at beam end", severity=Severity.MAJOR,
        tags=["Crack"], pin=PlanPin(sheet.id, 0.4, 0.6), gps=GeoPoint(61.2, -149.9), number=1,
    ))

    loaded = storage.load_project(storage.save_project(project))

    assert loaded == project
