import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cloud_pages_install_and_register_pwa():
    for name in ("cloud_dashboard.html", "cloud_visit.html", "cloud_visit_overview.html"):
        markup = (ROOT / "webapp" / "templates" / name).read_text("utf-8")
        assert 'rel="manifest" href="/static/manifest.webmanifest"' in markup
        assert '/static/cloud_pwa.js' in markup


def test_manifest_is_standalone_and_scoped_to_app():
    manifest = json.loads((ROOT / "webapp/static/manifest.webmanifest").read_text("utf-8"))
    assert manifest["name"] == "MKA Site Visit Buddy"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["icons"]


def test_service_worker_never_caches_private_api_responses():
    worker = (ROOT / "webapp/static/service-worker.js").read_text("utf-8")
    assert 'url.pathname.startsWith("/api/")' in worker
    assert 'url.pathname.startsWith("/auth/")' in worker
    assert "cache.put(request" in worker


def test_cloud_app_exposes_root_scoped_service_worker():
    source = (ROOT / "webapp/cloud_app.py").read_text("utf-8")
    assert '@app.get("/service-worker.js")' in source
    assert 'response.headers["Service-Worker-Allowed"] = "/"' in source
