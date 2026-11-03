from datetime import date
from pathlib import Path

from webapp.cloud.report_output import create_outputs


ROOT = Path(__file__).resolve().parents[1]


def test_report_output_creates_word_and_pdf(tmp_path):
    project = {"name": "[Project name]", "address": "", "project_number": "", "client": ""}
    visit = {
        "visit_date": date(2026, 11, 3), "engineer": "", "report_number": "",
        "conditions": "", "visit_time": "", "report_options": {},
    }
    observations = [{
        "id": "obs-1", "number": 1, "description": "[Observation summary]",
        "severity": "High", "tags": ["[Tag]"], "action": "Review in field",
        "include_in_report": True,
    }]
    drafted = {
        "summary": "Draft site visit summary.",
        "observations": [{
            "id": "obs-1", "description": "[Observation summary]",
            "severity": "High", "action": "Review in field",
        }],
    }

    docx, pdf = create_outputs(project, visit, observations, drafted, {}, tmp_path)

    assert docx.read_bytes().startswith(b"PK")
    assert pdf.read_bytes().startswith(b"%PDF")


def test_report_assets_are_versioned_with_the_application():
    instructions = ROOT / "webapp/report_assets/AGENTS.md"
    template = ROOT / "MKA Report Template/MKA Site Visit Observation Template.docx"

    assert "Never invent" in instructions.read_text("utf-8")
    assert template.is_file()
