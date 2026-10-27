"""Save and load a Project as a folder on disk.

    projects/<project-name>/
        project.json     everything in the Project object
        plans/           uploaded plan PDF + rendered sheet PNGs
        media/           photos and voice memos
        output/          generated Word report and marked-up plans

Owner: repo manager (glue code).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .models import GeoPoint, Observation, PlanPin, PlanSheet, Project, Severity

PROJECTS_DIR = Path("projects")


def project_dir(project: Project) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", project.name).strip("-") or "project"
    path = PROJECTS_DIR / slug
    for sub in ("plans", "media", "output"):
        (path / sub).mkdir(parents=True, exist_ok=True)
    return path


def save_project(project: Project) -> Path:
    path = project_dir(project) / "project.json"
    path.write_text(json.dumps(project.to_dict(), indent=2, default=_encode))
    return path


def load_project(path: Path) -> Project:
    data = json.loads(Path(path).read_text())
    return Project(
        name=data["name"],
        site_address=data["site_address"],
        engineer=data["engineer"],
        visit_date=datetime.fromisoformat(data["visit_date"]),
        plans=[_sheet(s) for s in data["plans"]],
        template_path=_path(data["template_path"]),
        observations=[_observation(o) for o in data["observations"]],
        summary=data["summary"],
        report_options=data.get("report_options", {}),
    )


def _encode(value):
    if isinstance(value, (Path, Severity)):
        return str(value.value if isinstance(value, Severity) else value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Can't save {type(value).__name__}")


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _geo(d: dict | None) -> GeoPoint | None:
    return GeoPoint(**d) if d else None


def _sheet(d: dict) -> PlanSheet:
    return PlanSheet(
        name=d["name"],
        source_pdf=Path(d["source_pdf"]),
        page_index=d["page_index"],
        image_path=Path(d["image_path"]),
        width_px=d["width_px"],
        height_px=d["height_px"],
        calibration=[(tuple(px), _geo(gps)) for px, gps in d["calibration"]],
        id=d["id"],
    )


def _observation(d: dict) -> Observation:
    return Observation(
        photo_path=_path(d["photo_path"]),
        photos=[Path(p) for p in d.get("photos", [])],
        audio_path=_path(d["audio_path"]),
        description=d["description"],
        severity=Severity(d["severity"]),
        tags=d["tags"],
        action_item=d["action_item"],
        pin=PlanPin(**d["pin"]) if d["pin"] else None,
        gps=_geo(d["gps"]),
        taken_at=datetime.fromisoformat(d["taken_at"]),
        number=d["number"],
        include=d.get("include", True),
        captions=dict(d.get("captions", {})),
        id=d["id"],
    )
