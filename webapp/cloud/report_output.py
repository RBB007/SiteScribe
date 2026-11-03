"""Materialize cloud visit data as the MKA DOCX and a companion PDF."""
from __future__ import annotations

from datetime import datetime, time
from pathlib import Path

import pymupdf as fitz

from sitescribe.models import Observation as ReportObservation
from sitescribe.models import Project as ReportProject
from sitescribe.models import Severity
from sitescribe.word_report import build_report


SEVERITY = {"Low": Severity.INFO, "Med": Severity.MINOR, "High": Severity.MAJOR,
            "Critical": Severity.CRITICAL, "Minor": Severity.MINOR,
            "Moderate": Severity.MINOR, "Major": Severity.MAJOR}


def create_outputs(project, visit, observations, drafted, photo_paths, directory, template_path=None):
    edits = {row["id"]: row for row in drafted.get("observations", [])}
    report_observations = []
    for row in observations:
        edit = edits.get(row["id"], {})
        photos = photo_paths.get(row["id"], [])
        report_observations.append(ReportObservation(
            photos=photos, photo_path=photos[0] if photos else None,
            description=edit.get("description") or row["description"] or "",
            severity=SEVERITY.get(edit.get("severity") or row.get("severity"), Severity.INFO),
            tags=list(row.get("tags") or []),
            action_item=edit.get("action") or row.get("action") or "",
            number=row["number"], include=bool(row.get("include_in_report", True)),
        ))
    model = ReportProject(
        name=project["name"], site_address=project.get("address") or "",
        engineer=visit.get("engineer") or "", visit_date=datetime.combine(visit["visit_date"], time()),
        observations=report_observations, summary=drafted.get("summary") or "",
        template_path=template_path,
        report_options={
            **(visit.get("report_options") or {}), "project_no": project.get("project_number") or "",
            "report_no": visit.get("report_number") or "", "client": project.get("client") or "",
            "conditions": visit.get("conditions") or "", "visit_time": visit.get("visit_time") or "",
        },
    )
    directory = Path(directory)
    docx = directory / "MKA_Site_Visit_Observation_Report.docx"
    pdf = directory / "MKA_Site_Visit_Observation_Report.pdf"
    build_report(model, docx)
    _build_pdf(model, pdf)
    return docx, pdf


def _build_pdf(project, output):
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    y = 54
    y = _text(page, (54, y, 558, y + 42), "MKA Site Visit Observation Report", 18, True) + 10
    y = _text(page, (54, y, 558, y + 34), project.name, 14, True) + 4
    details = f"Site visit: {project.visit_date:%B %d, %Y}\nEngineer: {project.engineer}\nAddress: {project.site_address}"
    y = _text(page, (54, y, 558, y + 60), details, 10) + 14
    if project.summary:
        y = _section(document, page, y, "Visit summary", project.summary)
        page = document[-1]
    for observation in (row for row in project.observations if row.include):
        needed = 190 if observation.photos else 100
        if y + needed > 744:
            page = document.new_page(width=612, height=792); y = 54
        title = f"Item {observation.number}  |  {observation.severity.value}"
        y = _text(page, (54, y, 558, y + 24), title, 12, True) + 4
        y = _text(page, (54, y, 558, y + 80), observation.description or "(No description)", 10) + 6
        if observation.action_item:
            y = _text(page, (54, y, 558, y + 55), "Action: " + observation.action_item, 9) + 6
        if observation.photos:
            photo = Path(observation.photos[0])
            if photo.is_file():
                if y + 180 > 744:
                    page = document.new_page(width=612, height=792); y = 54
                page.insert_image(fitz.Rect(54, y, 310, y + 180), filename=str(photo), keep_proportion=True)
                y += 190
        page.draw_line((54, y), (558, y), color=(.8, .8, .8), width=.5); y += 14
    for page in document:
        page.insert_text((54, 770), "Draft - engineer review required", fontsize=8, color=(.35, .35, .35))
    document.set_metadata({"title": "MKA Site Visit Observation Report"})
    document.save(output)


def _text(page, rect, text, size, bold=False):
    font = "hebo" if bold else "helv"
    page.insert_textbox(fitz.Rect(rect), str(text), fontsize=size, fontname=font, color=(.09, .1, .12), lineheight=1.25)
    return rect[3]


def _section(document, page, y, heading, body):
    if y + 100 > 744:
        page = document.new_page(width=612, height=792); y = 54
    y = _text(page, (54, y, 558, y + 24), heading, 12, True) + 4
    return _text(page, (54, y, 558, y + 90), body, 10) + 12
