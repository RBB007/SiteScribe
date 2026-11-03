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


def test_service_worker_clones_response_before_caching():
    # Cloning inside the async cache callback fails once the page has read the
    # body, so pages were never cached for offline use.
    worker = (ROOT / "webapp/static/service-worker.js").read_text("utf-8")
    assert "cache.put(request,response.clone())" not in worker
    assert "const copy=response.clone()" in worker


def test_offline_navigation_ignores_query_string():
    worker = (ROOT / "webapp/static/service-worker.js").read_text("utf-8")
    assert "caches.match(request,{ignoreSearch:true})" in worker
    assert '"/static/cloud_sync.js"' in worker


def test_capture_pages_load_offline_visit_helpers():
    for name in ("cloud_visit.html", "cloud_visit_overview.html"):
        markup = (ROOT / "webapp" / "templates" / name).read_text("utf-8")
        assert markup.index("/static/offline.js") < markup.index("/static/cloud_sync.js")
        assert markup.index("/static/cloud_sync.js") < markup.index("/static/cloud_" + (
            "capture.js" if name == "cloud_visit.html" else "overview.js"))


def test_offline_queue_never_drops_rejected_changes():
    queue = (ROOT / "webapp/static/offline.js").read_text("utf-8")
    assert 'createObjectStore("failed"' in queue
    assert "await park(job, response.status, detail)" in queue
    # A login redirect must not count as a successful sync.
    assert queue.index("response.redirected || isAuth") < queue.index("if (response.ok)")
