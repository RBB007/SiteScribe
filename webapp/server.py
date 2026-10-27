"""SiteScribe — structural site-visit observation tool.

Single-file Flask backend. Projects hold a visit; a visit holds items
(observations); items hold photos and audio clips.

Storage:
    data/projects.json            index of every project
    data/<pid>/visit.json         that project's items + plans
    data/<pid>/template.docx      that project's Word report template, if any
    uploads/<pid>/<item_id>/...   that project's photos + audio
    uploads/<pid>/plans/...       that project's plan files

The open project lives in session["pid"], so the item/photo/audio/plan
routes keep their original URLs and resolve their paths against it.
"""

from flask import (Flask, render_template, render_template_string, request,
                   jsonify, session, redirect, url_for, send_file,
                   send_from_directory)
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

import datetime
import functools
import io
import json
import os
import re
import shutil
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
UPLOADS = os.path.join(BASE, "uploads")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
LEGACY_DATA_FILE = os.path.join(DATA_DIR, "visit.json")

for d in (DATA_DIR, UPLOADS):
    os.makedirs(d, exist_ok=True)

IMPORTANCE = ["Info", "Minor", "Major", "Critical", "Safety"]
PID_RE = re.compile(r"^P-\d{3}$")
MAX_NAME = 120

app = Flask(__name__)
app.secret_key = os.environ.get("SITESCRIBE_SECRET", os.urandom(32).hex())
app.permanent_session_lifetime = datetime.timedelta(hours=12)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

PIN = os.environ.get("SITESCRIBE_PIN", "2424")

# ---------------------------------------------------------------- auth

# crude per-IP throttle: a 4-digit PIN is only 10k guesses
_fails = {}
MAX_FAILS, LOCK_SECONDS = 8, 300


def _ip():
    fwd = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or "?"


def locked(ip):
    n, until = _fails.get(ip, (0, 0))
    return time.time() < until


def require_pin(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("ok"):
            if request.path.startswith("/api/"):
                return jsonify(error="unauthorized"), 401
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


LOGIN_HTML = """<!DOCTYPE html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>SiteScribe</title><style>
:root{--bg:#fff;--fg:#14181d;--mut:#667085;--line:#e4e7ec;--card:#f9fafb;--accent:#1554b8;--bad:#b42318}
@media(prefers-color-scheme:dark){:root{--bg:#101418;--fg:#e8eaed;--mut:#98a2b3;--line:#272c33;--card:#171b20;--accent:#4d8df0;--bad:#ff8a80}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;
background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,sans-serif;padding:24px}
.box{width:100%;max-width:340px;text-align:center}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}h1 span{color:var(--accent)}
p{color:var(--mut);font-size:14px;margin:0 0 22px}
input{width:100%;padding:15px;font:600 22px/1 system-ui;text-align:center;letter-spacing:.5em;
border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);margin-bottom:12px}
button{width:100%;padding:14px;border:0;border-radius:10px;background:var(--accent);color:#fff;font:600 16px system-ui}
.err{color:var(--bad);font-size:14px;margin-top:12px}
</style></head><body><div class=box>
<h1>Site<span>Scribe</span></h1>
<p>Structural observation reports from your phone.</p>
<form method=post>
<input name=pin type=tel inputmode=numeric maxlength=12 autocomplete=off
       placeholder="PIN" autofocus aria-label="PIN">
<button>Enter</button>
</form>
{% if error %}<div class=err>{{ error }}</div>{% endif %}
</div></body></html>"""


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    ip = _ip()
    if locked(ip):
        error = "Too many attempts. Try again in a few minutes."
    elif request.method == "POST":
        if request.form.get("pin", "").strip() == PIN:
            session.permanent = True
            session["ok"] = True
            _fails.pop(ip, None)
            return redirect(request.args.get("next") or url_for("index"))
        n, _ = _fails.get(ip, (0, 0))
        n += 1
        _fails[ip] = (n, time.time() + LOCK_SECONDS if n >= MAX_FAILS else 0)
        error = "Incorrect PIN."
    return render_template_string(LOGIN_HTML, error=error), (200 if not error else 401)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    return jsonify(status="ok", service="sitescribe", time=_now())


# ---------------------------------------------------------------- storage

_lock = threading.Lock()


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def _iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def valid_pid(pid):
    return isinstance(pid, str) and PID_RE.match(pid) is not None


def project_data_dir(pid):
    return os.path.join(DATA_DIR, pid)


def project_uploads(pid):
    return os.path.join(UPLOADS, pid)


def current_pid():
    """The project this browser session has open, or None."""
    pid = session.get("pid")
    if not valid_pid(pid) or not os.path.isdir(project_data_dir(pid)):
        return None
    return pid


def require_project(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if current_pid() is None:
            if request.path.startswith("/api/"):
                return jsonify(error="no project open"), 409
            return redirect(url_for("index"))
        return fn(*a, **kw)
    return wrapper


def data_file(pid=None):
    pid = pid or current_pid()
    return os.path.join(project_data_dir(pid), "visit.json")


def plans_dir(pid=None):
    pid = pid or current_pid()
    return os.path.join(project_uploads(pid), "plans")


def item_dir(item_id, pid=None):
    pid = pid or current_pid()
    return os.path.join(project_uploads(pid), secure_filename(item_id))


def _blank():
    return {"items": [], "plans": [], "template": None}


def load(pid=None):
    path = data_file(pid)
    if not os.path.exists(path):
        return _blank()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("visit.json is not an object")
    except (OSError, ValueError) as exc:
        print(f"[sitescribe] {path} unreadable ({exc}); starting empty", file=sys.stderr)
        return _blank()
    data.setdefault("items", [])
    data.setdefault("plans", [])
    data.setdefault("template", None)
    # backfill fields added after some records were written, so an older
    # visit.json never 500s or silently drops data
    for it in data["items"]:
        it.setdefault("audio_clips", [])
        it.setdefault("photos", [])
        it.setdefault("tags", [])
        it.setdefault("include", True)
        it.setdefault("importance", "Info")
        it.setdefault("description", "")
        it.setdefault("location", None)
        it.setdefault("audio", None)
    return data


def save(data, pid=None):
    # write to a temp file first so a crash mid-write cannot truncate the visit
    path = data_file(pid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def find_item(data, item_id):
    for it in data["items"]:
        if it["item_id"] == item_id:
            return it
    return None


def find_photo(item, photo_id):
    for p in item.get("photos", []):
        if p["photo_id"] == photo_id:
            return p
    return None


def next_item_id(data):
    n = 0
    for it in data["items"]:
        try:
            n = max(n, int(str(it["item_id"]).split("-")[-1]))
        except (ValueError, IndexError):
            continue
    return f"I-{n + 1:03d}"


def next_photo_id(item):
    n = 0
    for p in item.get("photos", []):
        try:
            n = max(n, int(str(p["photo_id"]).split("-")[-1]))
        except (ValueError, IndexError):
            continue
    return f"{item['item_id']}-P-{n + 1:02d}"


def next_plan_id(data):
    n = 0
    for p in data["plans"]:
        try:
            n = max(n, int(str(p["plan_id"]).split("-")[-1]))
        except (ValueError, IndexError):
            continue
    return f"PL-{n + 1:02d}"


def sorted_items(data):
    return sorted(data["items"], key=lambda it: it["item_id"])


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def need_item(data, item_id):
    it = find_item(data, item_id)
    if it is None:
        raise ApiError(f"no such item: {item_id}", 404)
    return it


def need_photo(item, photo_id):
    p = find_photo(item, photo_id)
    if p is None:
        raise ApiError(f"no such photo: {photo_id}", 404)
    return p


# ---------------------------------------------------------------- projects

def load_index():
    if not os.path.exists(PROJECTS_FILE):
        return {"projects": []}
    try:
        with open(PROJECTS_FILE, "r", encoding="utf-8") as fh:
            idx = json.load(fh)
        if not isinstance(idx, dict) or not isinstance(idx.get("projects"), list):
            raise ValueError("projects.json is not an index object")
    except (OSError, ValueError) as exc:
        print(f"[sitescribe] projects.json unreadable ({exc}); starting empty", file=sys.stderr)
        return {"projects": []}
    idx["projects"] = [p for p in idx["projects"]
                       if isinstance(p, dict) and valid_pid(p.get("project_id"))]
    return idx


def save_index(idx):
    tmp = PROJECTS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(idx, fh, indent=2)
    os.replace(tmp, PROJECTS_FILE)


def find_project(idx, pid):
    for p in idx["projects"]:
        if p.get("project_id") == pid:
            return p
    return None


def need_project(idx, pid):
    # a pid off the wire must never reach a filesystem path unvalidated
    if not valid_pid(pid):
        raise ApiError(f"no such project: {pid}", 404)
    p = find_project(idx, pid)
    if p is None:
        raise ApiError(f"no such project: {pid}", 404)
    return p


def next_pid(idx):
    """Max existing id + 1, so deleting a project never recycles its id."""
    n = 0
    for p in idx["projects"]:
        try:
            n = max(n, int(str(p.get("project_id", "")).split("-")[-1]))
        except (ValueError, IndexError):
            continue
    try:
        for entry in os.listdir(DATA_DIR):
            if PID_RE.match(entry):
                n = max(n, int(entry.split("-")[-1]))
    except OSError:
        pass
    return f"P-{n + 1:03d}"


def _counts(pid):
    """(items, photos, included) for a project; zeros if its file is unusable."""
    items = photos = included = 0
    try:
        with open(data_file(pid), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for it in data["items"]:
            items += 1
            photos += len(it.get("photos") or [])
            if it.get("include", True):
                included += 1
    except Exception:
        # one corrupt project must never break the whole listing
        return 0, 0, 0
    return items, photos, included


def project_dict(p):
    pid = p["project_id"]
    created = p.get("created") or _now()
    try:
        updated = _iso(os.path.getmtime(data_file(pid)))
    except OSError:
        updated = created
    items, photos, included = _counts(pid)
    return {"project_id": pid, "name": p.get("name") or pid, "created": created,
            "updated": updated, "items": items, "photos": photos,
            "included": included}


def clean_name(raw, default=None):
    name = ("" if raw is None else str(raw)).strip()
    if not name:
        if default is None:
            raise ApiError("name required")
        return default
    if len(name) > MAX_NAME:
        raise ApiError(f"name must be {MAX_NAME} characters or fewer")
    return name


def auto_name(ts=None):
    when = (datetime.datetime.now(datetime.timezone.utc) if ts is None
            else datetime.datetime.fromtimestamp(ts, datetime.timezone.utc))
    return "Site Visit " + when.strftime("%Y-%m-%d %H:%M")


def make_project(name, created=None, idx=None):
    """Allocate a pid, build its directories and an empty visit, index it."""
    own = idx is None
    if own:
        idx = load_index()
    pid = next_pid(idx)
    os.makedirs(project_data_dir(pid), exist_ok=True)
    os.makedirs(plans_dir(pid), exist_ok=True)
    entry = {"project_id": pid, "name": name, "created": created or _now()}
    save(_blank(), pid)
    idx["projects"].append(entry)
    if own:
        save_index(idx)
    return entry


@app.route("/api/projects")
@require_pin
def api_projects():
    with _lock:
        idx = load_index()
        out = [project_dict(p) for p in idx["projects"]]
    out.sort(key=lambda p: (p["updated"], p["project_id"]), reverse=True)
    return jsonify(projects=out, current=current_pid())


@app.route("/api/projects", methods=["POST"])
@require_pin
def api_project_create():
    body = request.get_json(silent=True) or {}
    name = clean_name(body.get("name"), default=auto_name())
    with _lock:
        entry = make_project(name)
        out = project_dict(entry)
    session["pid"] = entry["project_id"]
    return jsonify(out)


@app.route("/api/projects/close", methods=["POST"])
@require_pin
def api_project_close():
    session.pop("pid", None)
    return jsonify(ok=True)


@app.route("/api/projects/<pid>/open", methods=["POST"])
@require_pin
def api_project_open(pid):
    with _lock:
        entry = need_project(load_index(), pid)
        out = project_dict(entry)
    session["pid"] = pid
    return jsonify(out)


@app.route("/api/projects/<pid>", methods=["PATCH"])
@require_pin
def api_project_patch(pid):
    body = request.get_json(silent=True) or {}
    name = clean_name(body.get("name"))
    with _lock:
        idx = load_index()
        entry = need_project(idx, pid)
        entry["name"] = name
        save_index(idx)
        return jsonify(project_dict(entry))


@app.route("/api/projects/<pid>", methods=["DELETE"])
@require_pin
def api_project_delete(pid):
    with _lock:
        idx = load_index()
        entry = need_project(idx, pid)
        idx["projects"].remove(entry)
        save_index(idx)
        shutil.rmtree(project_data_dir(pid), ignore_errors=True)
        shutil.rmtree(project_uploads(pid), ignore_errors=True)
    if session.get("pid") == pid:
        session.pop("pid", None)
    return jsonify(ok=True)


# ---------------------------------------------------------------- pages

@app.route("/")
@require_pin
def index():
    return render_template("landing.html")


@app.route("/capture")
@require_pin
@require_project
def capture():
    return render_template("index.html")


@app.route("/uploads/<path:relpath>")
@require_pin
def uploaded(relpath):
    # send_from_directory rejects anything that escapes UPLOADS; the project id
    # is already part of relpath, so no project needs to be open to view a file
    return send_from_directory(UPLOADS, relpath)


# ---------------------------------------------------------------- visit / items

@app.route("/api/visit")
@require_pin
@require_project
def api_visit():
    with _lock:
        data = load()
        return jsonify(items=sorted_items(data), plans=data["plans"])


@app.route("/api/item", methods=["POST"])
@require_pin
@require_project
def api_item_create():
    with _lock:
        data = load()
        item = {
            "item_id": next_item_id(data),
            "include": True,
            "description": "",
            "importance": "Info",
            "tags": [],
            "location": None,
            "audio": None,
            "audio_clips": [],
            "created": _now(),
            "photos": [],
        }
        data["items"].append(item)
        os.makedirs(item_dir(item["item_id"]), exist_ok=True)
        save(data)
        return jsonify(item)


def _clean_location(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ApiError("location must be an object or null")
    try:
        x = float(value.get("x"))
        y = float(value.get("y"))
    except (TypeError, ValueError):
        raise ApiError("location x and y must be numbers")
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ApiError("location x and y must be normalized fractions 0.0-1.0")
    try:
        page = int(value.get("page", 1) or 1)
    except (TypeError, ValueError):
        raise ApiError("location page must be an integer")
    return {"plan_id": str(value.get("plan_id") or ""), "page": page, "x": x, "y": y}


@app.route("/api/item/<item_id>", methods=["PATCH"])
@require_pin
@require_project
def api_item_patch(item_id):
    body = request.get_json(silent=True) or {}
    with _lock:
        data = load()
        item = need_item(data, item_id)

        if "description" in body:
            item["description"] = "" if body["description"] is None else str(body["description"])
        if "importance" in body:
            imp = body["importance"]
            if imp not in IMPORTANCE:
                raise ApiError(f"importance must be one of {', '.join(IMPORTANCE)}")
            item["importance"] = imp
        if "tags" in body:
            tags = body["tags"]
            if tags is None:
                tags = []
            if not isinstance(tags, list):
                raise ApiError("tags must be a list of strings")
            item["tags"] = [str(t).strip() for t in tags if str(t).strip()]
        if "include" in body:
            item["include"] = bool(body["include"])
        if "location" in body:
            item["location"] = _clean_location(body["location"])

        save(data)
        return jsonify(item)


@app.route("/api/item/<item_id>", methods=["DELETE"])
@require_pin
@require_project
def api_item_delete(item_id):
    with _lock:
        data = load()
        item = need_item(data, item_id)
        data["items"].remove(item)
        shutil.rmtree(item_dir(item_id), ignore_errors=True)
        save(data)
        return jsonify(ok=True)


# ---------------------------------------------------------------- photos

@app.route("/api/item/<item_id>/photo", methods=["POST"])
@require_pin
@require_project
def api_photo_add(item_id):
    f = request.files.get("photo")
    if not f or not f.filename:
        raise ApiError("no photo uploaded")
    pid = current_pid()
    with _lock:
        data = load()
        item = need_item(data, item_id)
        photo_id = next_photo_id(item)
        safe = secure_filename(f.filename) or "photo.jpg"
        filename = f"{photo_id}_{safe}"
        d = item_dir(item_id, pid)
        os.makedirs(d, exist_ok=True)
        f.save(os.path.join(d, filename))
        photo = {
            "photo_id": photo_id,
            "filename": filename,
            "url": f"/uploads/{pid}/{item_id}/{filename}",
            "caption": "",
            "created": _now(),
        }
        item.setdefault("photos", []).append(photo)
        save(data)
        return jsonify(photo)


@app.route("/api/item/<item_id>/photo/<photo_id>", methods=["PATCH"])
@require_pin
@require_project
def api_photo_patch(item_id, photo_id):
    body = request.get_json(silent=True) or {}
    with _lock:
        data = load()
        item = need_item(data, item_id)
        photo = need_photo(item, photo_id)
        if "caption" in body:
            photo["caption"] = "" if body["caption"] is None else str(body["caption"])
        save(data)
        return jsonify(photo)


@app.route("/api/item/<item_id>/photo/<photo_id>", methods=["DELETE"])
@require_pin
@require_project
def api_photo_delete(item_id, photo_id):
    with _lock:
        data = load()
        item = need_item(data, item_id)
        photo = need_photo(item, photo_id)
        try:
            os.remove(os.path.join(item_dir(item_id), photo["filename"]))
        except OSError:
            pass  # record removal is what matters; a missing file is not an error
        item["photos"].remove(photo)
        save(data)
        return jsonify(ok=True)


# ---------------------------------------------------------------- audio

def transcribe(path):
    """Whisper transcription, or "" if unavailable. Never raises."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("[sitescribe] no OPENAI_API_KEY; skipping transcription", file=sys.stderr)
        return ""
    try:
        import requests
        with open(path, "rb") as fh:
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                data={"model": "whisper-1"},
                files={"file": (os.path.basename(path), fh, "application/octet-stream")},
                timeout=60,
            )
        if r.status_code != 200:
            print(f"[sitescribe] whisper HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
            return ""
        return (r.json().get("text") or "").strip()
    except Exception as exc:
        print(f"[sitescribe] transcription failed: {exc!r}", file=sys.stderr)
        return ""


@app.route("/api/item/<item_id>/audio", methods=["POST"])
@require_pin
@require_project
def api_audio(item_id):
    f = request.files.get("audio")
    if not f or not f.filename:
        raise ApiError("no audio uploaded")

    # "false"/"0"/"no" means: keep the recording, do not send it anywhere
    want_text = str(request.form.get("transcribe", "true")).lower() not in ("false", "0", "no")
    pid = current_pid()

    with _lock:
        data = load(pid)
        item = need_item(data, item_id)
        safe = secure_filename(f.filename) or "audio.webm"
        # keep every recording: <item>_audio_01_<name>
        existing = item.get("audio_clips") or []
        seq = f"{len(existing) + 1:02d}"
        filename = f"{item_id}_audio_{seq}_{safe}"
        d = item_dir(item_id, pid)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, filename)
        f.save(path)
        size = os.path.getsize(path)

    # transcription can take many seconds — do it outside the lock
    transcript = transcribe(path) if want_text else ""

    with _lock:
        data = load(pid)
        item = need_item(data, item_id)
        clip = {
            "clip_id": f"{item_id}-A-{seq}",
            "filename": filename,
            "url": f"/uploads/{pid}/{item_id}/{filename}",
            "bytes": size,
            "transcript": transcript,
            "created": _now(),
        }
        item.setdefault("audio_clips", []).append(clip)
        # keep the legacy single-audio field pointing at the most recent clip
        item["audio"] = {"filename": filename, "transcript": transcript}
        if transcript and not (item.get("description") or "").strip():
            item["description"] = transcript
        save(data, pid)
        return jsonify(clip=clip, transcript=transcript,
                       description=item.get("description", ""))


@app.route("/api/item/<item_id>/audio/<clip_id>", methods=["DELETE"])
@require_pin
@require_project
def api_audio_delete(item_id, clip_id):
    with _lock:
        data = load()
        item = need_item(data, item_id)
        clips = item.get("audio_clips") or []
        hit = next((c for c in clips if c["clip_id"] == clip_id), None)
        if hit is None:
            raise ApiError(f"no such clip: {clip_id}", 404)
        clips.remove(hit)
        try:
            os.remove(os.path.join(item_dir(item_id), hit["filename"]))
        except OSError:
            pass
        item["audio"] = ({"filename": clips[-1]["filename"],
                          "transcript": clips[-1]["transcript"]} if clips else None)
        save(data)
        return jsonify(ok=True)


# ---------------------------------------------------------------- plans

def pdf_pages(path):
    try:
        import pypdf
        with open(path, "rb") as fh:
            return max(1, len(pypdf.PdfReader(fh).pages))
    except Exception as exc:
        print(f"[sitescribe] page count unavailable ({exc!r}); assuming 1", file=sys.stderr)
        return 1


@app.route("/api/plan", methods=["POST"])
@require_pin
@require_project
def api_plan():
    f = request.files.get("plan")
    if not f or not f.filename:
        raise ApiError("no plan uploaded")
    pid = current_pid()
    with _lock:
        data = load()
        plan_id = next_plan_id(data)
        safe = secure_filename(f.filename) or "plan.pdf"
        filename = f"{plan_id}_{safe}"
        d = plans_dir(pid)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, filename)
        f.save(path)
        # the frontend picks PDF.js vs <img> off `name`, so keep the real extension
        name = os.path.basename(f.filename)
        pages = pdf_pages(path) if name.lower().endswith(".pdf") else 1
        plan = {
            "plan_id": plan_id,
            "name": name,
            "file": filename,
            "url": f"/uploads/{pid}/plans/{filename}",
            "pages": pages,
        }
        data["plans"].append(plan)
        save(data)
        return jsonify(plan)


# ---------------------------------------------------------------- template

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def template_path(pid=None):
    pid = pid or current_pid()
    return os.path.join(project_data_dir(pid), "template.docx")


def has_template(data, pid):
    """A template counts only when both the record and the file are there."""
    return bool(data.get("template")) and os.path.exists(template_path(pid))


def _template_json(rec):
    """Flat record for convenience plus `template` so a client can test None."""
    return jsonify(template=rec, **(rec or {}))


@app.route("/api/template")
@require_pin
@require_project
def api_template_get():
    with _lock:
        data = load()
        return _template_json(data.get("template"))


@app.route("/api/template", methods=["POST"])
@require_pin
@require_project
def api_template_upload():
    try:
        from docx import Document
        from docx.enum.style import WD_STYLE_TYPE
    except ImportError:
        return jsonify(error="python-docx not installed"), 501

    f = request.files.get("template")
    if not f or not f.filename:
        raise ApiError("no template uploaded")
    name = os.path.basename(f.filename)
    low = name.lower()
    if low.endswith(".doc"):
        raise ApiError("legacy .doc files are not supported — open it in Word "
                       "and use Save As to make a .docx, then upload that")
    if not low.endswith(".docx"):
        raise ApiError("template must be a Word .docx file")

    pid = current_pid()
    with _lock:
        path = template_path(pid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # land it beside the real name first: a file that will not open must
        # not replace a template that already works
        tmp = path + ".tmp"
        f.save(tmp)
        try:
            doc = Document(tmp)
            styles = [s.name for s in doc.styles if s.type == WD_STYLE_TYPE.PARAGRAPH]
        except Exception as exc:
            print(f"[sitescribe] rejected template {name!r}: {exc!r}", file=sys.stderr)
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise ApiError("not a readable .docx file")
        os.replace(tmp, path)
        data = load(pid)
        rec = {"name": name, "uploaded": _now(), "styles": styles}
        data["template"] = rec
        save(data, pid)
        return _template_json(rec)


@app.route("/api/template", methods=["DELETE"])
@require_pin
@require_project
def api_template_delete():
    pid = current_pid()
    with _lock:
        try:
            os.remove(template_path(pid))
        except OSError:
            pass  # record removal is what matters; a missing file is not an error
        data = load(pid)
        data["template"] = None
        save(data, pid)
        return jsonify(ok=True)


# ---------------------------------------------------------------- export

def styled(doc, text, *candidates):
    """Add a paragraph using the first style the document actually has.

    Uploaded templates differ wildly in which named styles they define, so a
    missing one steps to the next candidate and finally to Normal. The style is
    applied after the paragraph exists — add_paragraph(style=...) inserts the
    text before it validates the name, which on failure would strand a
    duplicate. ValueError covers a template where the name exists but belongs
    to a character or table style.
    """
    p = doc.add_paragraph(text)
    for name in candidates:
        try:
            p.style = name
            break
        except (KeyError, ValueError):
            continue
    return p


def _strip_body(doc):
    """Empty the template's body but keep its trailing <w:sectPr>.

    sectPr holds page size, margins and the header/footer references, so
    dropping it would lose the letterhead. Everything before it is the
    template's own prose — a user may well upload a filled-in past report
    rather than a blank shell, and that content must not reach the output.
    """
    body = doc.element.body
    for child in list(body):
        if not child.tag.endswith("}sectPr"):
            body.remove(child)


def _write_report(doc, data, pid, *, title, heading, body, caption, Inches):
    """The report itself: same content and ordering for either export path."""
    items = [it for it in sorted_items(data) if it.get("include", True)]
    plan_names = {p["plan_id"]: p.get("name", p["plan_id"]) for p in data["plans"]}

    title("Site Visit Report")
    body(datetime.date.today().strftime("%B %d, %Y"))

    for it in items:
        heading(f"{it['item_id']} — {it.get('importance', 'Info')}")
        if (it.get("description") or "").strip():
            body(it["description"])
        tags = it.get("tags") or []
        if tags:
            body("Tags: " + ", ".join(tags))
        loc = it.get("location")
        if loc:
            name = plan_names.get(loc.get("plan_id"), loc.get("plan_id") or "unknown")
            body(f"Plan {name}, page {loc.get('page', 1)} "
                 f"(x={float(loc.get('x', 0)):.2f}, y={float(loc.get('y', 0)):.2f})")
        for ph in it.get("photos", []):
            path = os.path.join(item_dir(it["item_id"], pid), ph["filename"])
            if not os.path.exists(path):
                continue
            try:
                doc.add_picture(path, width=Inches(4.5))
            except Exception as exc:
                print(f"[sitescribe] could not embed {path}: {exc!r}", file=sys.stderr)
                continue
            if (ph.get("caption") or "").strip():
                caption(ph["caption"])


def _italic_caption(doc, text, Pt):
    cap = doc.add_paragraph()
    run = cap.add_run(text)
    run.italic = True
    run.font.size = Pt(9)
    return cap


def _styled_caption(doc, text, Pt):
    """Caption style when the template has one, hand-italicised otherwise."""
    cap = doc.add_paragraph(text)
    try:
        cap.style = "Caption"
    except (KeyError, ValueError):
        for run in cap.runs:
            run.italic = True
            run.font.size = Pt(9)
    return cap


def _plain_doc(data, pid, Document, Inches, Pt):
    """The original report, built on python-docx's own default template."""
    doc = Document()
    _write_report(
        doc, data, pid,
        title=lambda t: doc.add_heading(t, level=0),
        heading=lambda t: doc.add_heading(t, level=1),
        body=doc.add_paragraph,
        caption=lambda t: _italic_caption(doc, t, Pt),
        Inches=Inches,
    )
    return doc


def _styled_doc(data, pid, path, Document, Inches, Pt):
    """The same report written into the firm's template: styles, margins,
    headers and footers all come along because the template *is* the base."""
    doc = Document(path)
    _strip_body(doc)
    _write_report(
        doc, data, pid,
        title=lambda t: styled(doc, t, "Title", "Heading 1"),
        heading=lambda t: styled(doc, t, "Heading 1", "Heading 2"),
        body=lambda t: styled(doc, t, "Body Text", "Normal"),
        caption=lambda t: _styled_caption(doc, t, Pt),
        Inches=Inches,
    )
    return doc


def _to_buffer(doc):
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf


def _report_buffer(data, pid):
    """The Word report as a buffer: in the template if there is one, else plain.
    Raises ImportError when python-docx is missing."""
    from docx import Document
    from docx.shared import Inches, Pt

    if has_template(data, pid):
        path = template_path(pid)
        try:
            return _to_buffer(_styled_doc(data, pid, path, Document, Inches, Pt))
        except Exception as exc:
            # a template gone bad must never stand between the user and a
            # report — say so on the log and fall back to the plain one
            print(f"[sitescribe] template {path} unusable ({exc!r}); "
                  "exporting plain report", file=sys.stderr)
    return _to_buffer(_plain_doc(data, pid, Document, Inches, Pt))


@app.route("/api/export/docx")
@require_pin
@require_project
def api_export_docx():
    pid = current_pid()
    with _lock:
        data = load(pid)
        try:
            buf = _report_buffer(data, pid)
        except ImportError:
            return jsonify(error="python-docx not installed"), 501

    return send_file(
        buf,
        mimetype=DOCX_MIME,
        as_attachment=True,
        download_name="site_visit_report.docx",
    )


def _export_bundle():
    try:
        from webapp import export_bundle   # python run.py, from the repo root
    except ImportError:
        import export_bundle               # python server.py, from inside webapp/
    return export_bundle


@app.route("/api/export/bundle")
@require_pin
@require_project
def api_export_bundle():
    """A zip of one folder: the Word report, photos/ with each entry written
    into the photo's EXIF, and plans/ with every pinned plan page."""
    pid = current_pid()
    with _lock:
        data = load(pid)
        try:
            report = _report_buffer(data, pid).getvalue()
        except ImportError:
            return jsonify(error="python-docx not installed"), 501
        entry = find_project(load_index(), pid) or {}
    name = entry.get("name") or pid
    try:
        bundle = _export_bundle()
    except ImportError as exc:
        return jsonify(error=f"photo/plan export unavailable: {exc}"), 501

    buf = bundle.build_zip(data, report, name=name,
                           item_dir=lambda item_id: item_dir(item_id, pid),
                           plans_dir=plans_dir(pid))
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{bundle.folder_name(name)}.zip",
    )


# ---------------------------------------------------------------- errors

@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error=exc.message), exc.status


@app.errorhandler(Exception)
def handle_any(exc):
    if isinstance(exc, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=exc.description), exc.code
        return exc
    print(f"[sitescribe] unhandled error on {request.path}: {exc!r}", file=sys.stderr)
    if request.path.startswith("/api/"):
        return jsonify(error="internal server error"), 500
    return "Internal Server Error", 500


# ---------------------------------------------------------------- migration

def migrate_legacy():
    """Fold a pre-projects single visit into its own project. Idempotent."""
    if not os.path.exists(LEGACY_DATA_FILE):
        return None
    with _lock:
        if not os.path.exists(LEGACY_DATA_FILE):
            return None
        mtime = os.path.getmtime(LEGACY_DATA_FILE)
        idx = load_index()
        pid = next_pid(idx)
        os.makedirs(project_data_dir(pid), exist_ok=True)
        os.makedirs(project_uploads(pid), exist_ok=True)
        dest = os.path.join(project_data_dir(pid), "visit.json")
        os.replace(LEGACY_DATA_FILE, dest)

        moved = []
        for entry in sorted(os.listdir(UPLOADS)):
            src = os.path.join(UPLOADS, entry)
            # leave already-migrated project trees alone
            if not os.path.isdir(src) or PID_RE.match(entry):
                continue
            shutil.move(src, os.path.join(project_uploads(pid), entry))
            moved.append(entry)
        os.makedirs(plans_dir(pid), exist_ok=True)

        _reprefix_urls(dest, pid, mtime)

        idx["projects"].append({"project_id": pid, "name": auto_name(mtime),
                                "created": _iso(mtime)})
        save_index(idx)
    print(f"[sitescribe] migrated legacy visit.json into {pid} "
          f"({auto_name(mtime)}); moved {len(moved)} upload dir(s): "
          f"{', '.join(moved) or 'none'}", file=sys.stderr)
    return pid


def _reprefix_urls(path, pid, mtime):
    """Legacy /uploads/<item>/... urls now live one level deeper."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"[sitescribe] could not rewrite urls in {path}: {exc}", file=sys.stderr)
        return

    def fix(rec):
        url = rec.get("url")
        if isinstance(url, str) and url.startswith("/uploads/") and \
                not url.startswith(f"/uploads/{pid}/"):
            rec["url"] = "/uploads/" + pid + url[len("/uploads"):]

    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        for rec in (it.get("photos") or []) + (it.get("audio_clips") or []):
            if isinstance(rec, dict):
                fix(rec)
    for pl in data.get("plans") or []:
        if isinstance(pl, dict):
            fix(pl)

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
    os.utime(path, (mtime, mtime))  # keep "updated" honest for the listing


migrate_legacy()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
