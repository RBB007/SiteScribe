"""Local server for the offline-sync browser test (offline_sync.js).

Real capture blueprint, templates, static files and service worker; SQLite and
fake auth (every request is signed in). POST /test/fail/<status> makes every
API write return that status (0 turns it off). Never deploy this.
"""
import pathlib
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from flask import Flask, render_template, send_from_directory, session
from test_cloud_capture import setup_app  # noqa: E402

ROOT = REPO / "webapp"
tmp = pathlib.Path(tempfile.mkdtemp())
client, store, visit_id = setup_app(tmp)
capture_app = client.application
app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
app.secret_key = "test"
# reuse the blueprint's db/auth/store by re-registering from the fixture app
bp = capture_app.blueprints["cloud_capture"]
app.register_blueprint(bp)

@app.before_request
def sign_in():
    session["cloud_sid"] = "valid"

@app.get("/")
def home():
    return "<html><body><div id=message></div>dashboard</body></html>"

@app.get("/visits/<vid>")
def capture(vid):
    return render_template("cloud_visit.html", visit_id=vid, user=None)

@app.get("/visits/<vid>/overview")
def overview(vid):
    return render_template("cloud_visit_overview.html", visit_id=vid, user=None)

@app.get("/service-worker.js")
def sw():
    r = send_from_directory(app.static_folder, "service-worker.js", mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"; r.headers["Service-Worker-Allowed"] = "/"
    return r

@app.get("/visit-id")
def vid():
    return str(visit_id)

FAIL = {"status": 0}
@app.before_request
def inject_failure():
    from flask import request, jsonify
    if FAIL["status"] and request.method != "GET" and request.path.startswith("/api/"):
        return jsonify(error="injected"), FAIL["status"]

@app.post("/test/fail/<int:status>")
def set_fail(status):
    FAIL["status"] = status
    return "ok"

app.run(port=5055)
