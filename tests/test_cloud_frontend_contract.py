from pathlib import Path

from flask import Flask

from webapp.cloud.auth.blueprint import require_cloud_user


ROOT = Path(__file__).resolve().parents[1]


class MissingAuth:
    def resolve(self, _opaque_id):
        return None


def test_browser_page_guard_redirects_to_login():
    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.get("/")
    @require_cloud_user(MissingAuth(), redirect_to_login=True)
    def dashboard():
        return "protected"

    response = app.test_client().get("/")
    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/login"


def test_project_form_is_single_submit_and_opens_initial_visit():
    markup = (ROOT / "webapp/templates/cloud_dashboard.html").read_text("utf-8")

    assert "let creatingProject=false" in markup
    assert "if(creatingProject)return" in markup
    assert 'name="visit_date"' in markup
    assert 'location.assign("/visits/"+project.initial_visit.id)' in markup


def test_cloud_visit_exposes_mobile_capture_controls():
    markup = (ROOT / "webapp/templates/cloud_visit.html").read_text("utf-8")

    assert "MKA Site Visit Buddy" in markup
    assert "Record voice" in markup
    assert "MediaRecorder" in markup
    assert 'accept=\'image/*\'' in markup
    assert 'form.append("kind",kind)' in markup
