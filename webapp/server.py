"""SiteScribe — structural site-visit observation tool.

Single-file Flask backend. Visits hold items (observations); items hold photos.
State lives in data/visit.json; uploads live under uploads/.
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
import shutil
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
DATA_FILE = os.path.join(DATA_DIR, "visit.json")
UPLOADS = os.path.join(BASE, "uploads")
PLANS_DIR = os.path.join(UPLOADS, "plans")

for d in (DATA_DIR, UPLOADS, PLANS_DIR):
    os.makedirs(d, exist_ok=True)

IMPORTANCE = ["Info", "Minor", "Major", "Critical", "Safety"]

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


def _blank():
    return {"items": [], "plans": []}


def load():
    if not os.path.exists(DATA_FILE):
        return _blank()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"[sitescribe] visit.json unreadable ({exc}); starting empty", file=sys.stderr)
        return _blank()
    data.setdefault("items", [])
    data.setdefault("plans", [])
    return data


def save(data):
    # write to a temp file first so a crash mid-write cannot truncate the visit
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, DATA_FILE)


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


def item_dir(item_id):
    return os.path.join(UPLOADS, secure_filename(item_id))


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


# ---------------------------------------------------------------- pages

@app.route("/")
@require_pin
def index():
    return render_template("index.html")


@app.route("/uploads/<path:relpath>")
@require_pin
def uploaded(relpath):
    # send_from_directory rejects anything that escapes UPLOADS
    return send_from_directory(UPLOADS, relpath)


# ---------------------------------------------------------------- visit / items

@app.route("/api/visit")
@require_pin
def api_visit():
    with _lock:
        data = load()
        return jsonify(items=sorted_items(data), plans=data["plans"])


@app.route("/api/item", methods=["POST"])
@require_pin
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
def api_photo_add(item_id):
    f = request.files.get("photo")
    if not f or not f.filename:
        raise ApiError("no photo uploaded")
    with _lock:
        data = load()
        item = need_item(data, item_id)
        photo_id = next_photo_id(item)
        safe = secure_filename(f.filename) or "photo.jpg"
        filename = f"{photo_id}_{safe}"
        d = item_dir(item_id)
        os.makedirs(d, exist_ok=True)
        f.save(os.path.join(d, filename))
        photo = {
            "photo_id": photo_id,
            "filename": filename,
            "url": f"/uploads/{item_id}/{filename}",
            "caption": "",
            "created": _now(),
        }
        item.setdefault("photos", []).append(photo)
        save(data)
        return jsonify(photo)


@app.route("/api/item/<item_id>/photo/<photo_id>", methods=["PATCH"])
@require_pin
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
def api_audio(item_id):
    f = request.files.get("audio")
    if not f or not f.filename:
        raise ApiError("no audio uploaded")

    with _lock:
        data = load()
        item = need_item(data, item_id)
        safe = secure_filename(f.filename) or "audio.webm"
        filename = f"{item_id}_audio_{safe}"
        d = item_dir(item_id)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, filename)
        f.save(path)

    # transcription can take many seconds — do it outside the lock
    transcript = transcribe(path)

    with _lock:
        data = load()
        item = need_item(data, item_id)
        item["audio"] = {"filename": filename, "transcript": transcript}
        if transcript and not (item.get("description") or "").strip():
            item["description"] = transcript
        save(data)
        return jsonify(transcript=transcript, description=item.get("description", ""))


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
def api_plan():
    f = request.files.get("plan")
    if not f or not f.filename:
        raise ApiError("no plan uploaded")
    with _lock:
        data = load()
        plan_id = next_plan_id(data)
        safe = secure_filename(f.filename) or "plan.pdf"
        filename = f"{plan_id}_{safe}"
        path = os.path.join(PLANS_DIR, filename)
        f.save(path)
        # the frontend picks PDF.js vs <img> off `name`, so keep the real extension
        name = os.path.basename(f.filename)
        pages = pdf_pages(path) if name.lower().endswith(".pdf") else 1
        plan = {
            "plan_id": plan_id,
            "name": name,
            "file": filename,
            "url": f"/uploads/plans/{filename}",
            "pages": pages,
        }
        data["plans"].append(plan)
        save(data)
        return jsonify(plan)


# ---------------------------------------------------------------- export

@app.route("/api/export/docx")
@require_pin
def api_export_docx():
    try:
        from docx import Document
        from docx.shared import Inches, Pt
    except ImportError:
        return jsonify(error="python-docx not installed"), 501

    with _lock:
        data = load()
        items = [it for it in sorted_items(data) if it.get("include", True)]
        plan_names = {p["plan_id"]: p.get("name", p["plan_id"]) for p in data["plans"]}

        doc = Document()
        doc.add_heading("Site Visit Report", level=0)
        doc.add_paragraph(datetime.date.today().strftime("%B %d, %Y"))

        for it in items:
            doc.add_heading(f"{it['item_id']} — {it.get('importance', 'Info')}", level=1)
            if (it.get("description") or "").strip():
                doc.add_paragraph(it["description"])
            tags = it.get("tags") or []
            if tags:
                doc.add_paragraph("Tags: " + ", ".join(tags))
            loc = it.get("location")
            if loc:
                name = plan_names.get(loc.get("plan_id"), loc.get("plan_id") or "unknown")
                doc.add_paragraph(
                    f"Plan {name}, page {loc.get('page', 1)} "
                    f"(x={float(loc.get('x', 0)):.2f}, y={float(loc.get('y', 0)):.2f})")
            for ph in it.get("photos", []):
                path = os.path.join(item_dir(it["item_id"]), ph["filename"])
                if not os.path.exists(path):
                    continue
                try:
                    doc.add_picture(path, width=Inches(4.5))
                except Exception as exc:
                    print(f"[sitescribe] could not embed {path}: {exc!r}", file=sys.stderr)
                    continue
                if (ph.get("caption") or "").strip():
                    cap = doc.add_paragraph()
                    run = cap.add_run(ph["caption"])
                    run.italic = True
                    run.font.size = Pt(9)

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name="site_visit_report.docx",
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
