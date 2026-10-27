"""SiteScribe app. Run with:  streamlit run app.py

Open the Network URL it prints on your phone (same Wi-Fi) to use the camera
and microphone on site. Works in Safari (iPhone) and Chrome (Android).

Owner: RBB007 (UI / integration).

This file is the frame everything else plugs into. It only calls functions in
the sitescribe package, so each module can be built and swapped in separately.
Until a module is written, the app shows "not built yet" instead of crashing.

Screens (top bar):
    Setup    - project info, plan set, Word template, open a saved project
    Capture  - big buttons to start an entry, then the entry editor:
                 <prev> Item # <next>
                 photo(s)           (take/select photo button if none)
                 <prev> Photo # <next>
                 location           (pick-on-plan button if none)
                 description        (typed and/or voice note)
                 importance flag
                 tags, action item
    Report   - AI draft, summary, export options, export (Word + marked plans)

Who plugs in where (see README "Code layout"):
    plans.py        Setup: plan PDF -> sheets
    photos.py       Capture: photo EXIF read;  Report: embed info into photos
    voice.py        Capture: voice note -> text, spoken location -> pin
    locate.py       Capture: GPS -> pin
    ai_writer.py    Report: summary, captions, action items
    plan_markup.py  Report: marked-up plan PDF
    word_report.py  Report: Word document
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates

from sitescribe import ai_writer, locate, photos, plan_markup, plans, voice, word_report
from sitescribe.models import SEVERITY_COLORS, Observation, PlanPin, PlanSheet, Project, Severity
from sitescribe.storage import PROJECTS_DIR, load_project, project_dir, save_project

COMMON_TAGS = ["Concrete", "Steel", "Wood", "Masonry", "Connection", "Crack",
               "Corrosion", "Deflection", "Water", "Install per plans", "RFI needed"]

SEVERITY_ICON = {
    Severity.INFO: "🔵",
    Severity.MINOR: "🟢",
    Severity.MAJOR: "🟠",
    Severity.CRITICAL: "🔴",
    Severity.SAFETY: "🟣",
}

VIEWS = ["Setup", "Capture", "Report"]
IMAGE_TYPES = ["jpg", "jpeg", "png", "heic", "webp"]

S = st.session_state


# ------------------------------------------------------------------ plumbing
def try_step(label: str, fn, *args, default=None):
    """Run one module function; if it isn't written yet, say so and move on."""
    try:
        return fn(*args)
    except NotImplementedError:
        st.info(f"{label}: not built yet ({fn.__module__}.{fn.__name__})")
    except Exception as exc:  # show teammates' errors without killing the app
        st.error(f"{label} failed: {exc}")
    return default


def sev_label(s: Severity) -> str:
    return f"{SEVERITY_ICON[s]} {s.value}"


def go(view: str, editing: str | None = None):
    """Switch screen (and optionally open an entry), then rerun."""
    S.goto = view
    S.editing = editing
    S.photo_idx = 0
    S.show_location_picker = False
    st.rerun()


def current_obs() -> Observation | None:
    return next((o for o in project.observations if o.id == S.get("editing")), None)


def renumber():
    for i, obs in enumerate(project.observations, start=1):
        obs.number = i


def new_entry(open_location: bool = False):
    obs = Observation(number=len(project.observations) + 1)
    project.observations.append(obs)
    save_project(project)
    S.editing = obs.id
    S.photo_idx = 0
    S.show_location_picker = open_location
    S.goto = "Capture"
    st.rerun()


def add_photo(obs: Observation, data: bytes, ext: str):
    """Store a photo on disk, attach it to the entry, pull EXIF time/GPS."""
    path = folder / "media" / f"{obs.number:03d}_{obs.id}_{len(obs.photos) + 1}.{ext}"
    path.write_bytes(data)
    obs.photos.append(path)
    obs.photo_path = obs.photos[0]
    if len(obs.photos) == 1:
        taken_at, gps = try_step("Read photo GPS/time", photos.read_photo_metadata,
                                 path, default=(None, None))
        obs.taken_at = taken_at or obs.taken_at
        obs.gps = gps or obs.gps
        if obs.pin is None and obs.gps and project.plans:
            obs.pin = try_step("Pin from GPS", locate.gps_to_pin, obs.gps, project.plans[0])
    S.photo_idx = len(obs.photos) - 1
    save_project(project)


def add_voice_note(obs: Observation, data: bytes):
    obs.audio_path = folder / "media" / f"{obs.number:03d}_{obs.id}.wav"
    obs.audio_path.write_bytes(data)
    spoken = try_step("Transcribe", voice.transcribe, obs.audio_path, default="")
    if spoken:
        obs.description = " ".join(filter(None, [obs.description.strip(), spoken.strip()]))
        S.pop(f"desc-{obs.id}", None)  # let the text box pick up the new text
        if obs.pin is None:
            obs.pin = try_step("Location from speech", voice.location_from_speech,
                               spoken, project.plans)
    save_project(project)


def bump(key: str) -> int:
    """Counter used in widget keys so a file/camera/audio widget resets after use."""
    S[key] = S.get(key, 0) + 1
    return S[key]


# ------------------------------------------------------------- plan drawing
def sheet_image_with_pins(sheet: PlanSheet, highlight_id: str | None = None,
                          max_width: int = 1400) -> Image.Image:
    """The sheet with every pinned observation drawn on it (preview only; the
    exported version comes from plan_markup.py)."""
    img = Image.open(sheet.image_path).convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)))
    draw = ImageDraw.Draw(img)
    r = max(10, img.width // 60)
    try:
        font = ImageFont.load_default(size=int(r * 1.1))
    except TypeError:  # old Pillow
        font = ImageFont.load_default()
    for obs in project.observations:
        if not obs.pin or obs.pin.sheet_id != sheet.id:
            continue
        cx, cy = obs.pin.x * img.width, obs.pin.y * img.height
        outline = "black" if obs.id == highlight_id else "white"
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=SEVERITY_COLORS[obs.severity],
                     outline=outline, width=3 if obs.id == highlight_id else 2)
        draw.text((cx, cy), str(obs.number), fill="white", font=font, anchor="mm")
    return img


def make_sample_sheet() -> PlanSheet:
    """A blank grid sheet so the app can be tried before plans.py exists."""
    w, h = 1600, 1100
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=36)
    except TypeError:
        font = ImageFont.load_default()
    cols, rows, m = "ABCDEF", 5, 120
    for i, c in enumerate(cols):
        x = m + i * (w - 2 * m) // (len(cols) - 1)
        d.line((x, m, x, h - m), fill="#999", width=2)
        d.text((x, m // 2), c, fill="black", font=font, anchor="mm")
    for j in range(rows):
        y = m + j * (h - 2 * m) // (rows - 1)
        d.line((m, y, w - m, y), fill="#999", width=2)
        d.text((m // 2, y), str(j + 1), fill="black", font=font, anchor="mm")
    d.rectangle((w - 520, h - 100, w - 20, h - 20), outline="black", width=3)
    d.text((w - 270, h - 60), "S-101  SAMPLE PLAN", fill="black", font=font, anchor="mm")
    path = folder / "plans" / "sample_S-101.png"
    img.save(path)
    return PlanSheet(name="S-101 Sample plan", source_pdf=folder / "plans" / "sample.pdf",
                     page_index=0, image_path=path, width_px=w, height_px=h)


def location_picker(obs: Observation):
    """Tap the plan to set obs.pin."""
    if not project.plans:
        st.warning("No plan set loaded. Upload one in Setup, or use a sample sheet to test.")
        if st.button("Use sample plan sheet", width="stretch"):
            project.plans.append(make_sample_sheet())
            save_project(project)
            st.rerun()
        return
    default = project.sheet(obs.pin.sheet_id) if obs.pin else project.plans[0]
    sheet = st.selectbox("Sheet", project.plans, index=project.plans.index(default),
                         format_func=lambda s: s.name, key=f"sheet-{obs.id}")
    st.caption("Tap the spot on the plan.")
    click = streamlit_image_coordinates(sheet_image_with_pins(sheet, obs.id), width="stretch",
                                        key=f"plan-{sheet.id}-{obs.id}-{S.get('pick_n', 0)}",
                                        cursor="crosshair")
    if click and "x" in click:
        obs.pin = PlanPin(sheet.id, click["x"] / click["width"], click["y"] / click["height"])
        S.show_location_picker = False
        bump("pick_n")
        save_project(project)
        st.rerun()
    if st.button("Cancel", key=f"cancel-pick-{obs.id}", width="stretch"):
        S.show_location_picker = False
        st.rerun()


def photo_picker(obs: Observation, label: str):
    """Take or choose a photo. On a phone the file picker offers the camera."""
    n = S.get(f"photo-n-{obs.id}", 0)
    shot = st.file_uploader(label, type=IMAGE_TYPES, key=f"file-{obs.id}-{n}",
                            label_visibility="collapsed")
    cam = None   # only ask for camera permission once the user opts in
    if st.toggle("Use in-app camera", key=f"camtoggle-{obs.id}"):
        cam = st.camera_input("Camera", key=f"cam-{obs.id}-{n}", label_visibility="collapsed")
    got = shot or cam
    if got:
        ext = Path(got.name).suffix.lstrip(".").lower() or "jpg"
        add_photo(obs, got.getvalue(), ext)
        bump(f"photo-n-{obs.id}")
        st.rerun()


# ------------------------------------------------------------------- screens
def setup_screen():
    st.subheader("Project")
    project.name = st.text_input("Project name", project.name)
    project.site_address = st.text_input("Site address", project.site_address)
    project.engineer = st.text_input("Engineer", project.engineer)

    st.subheader("Plan set")
    plan_pdf = st.file_uploader("Plan set (PDF)", type=["pdf"])
    if plan_pdf and not project.plans:
        pdf_path = folder / "plans" / plan_pdf.name
        pdf_path.write_bytes(plan_pdf.getvalue())
        project.plans = try_step("Load plans", plans.load_plan_set, pdf_path, folder / "plans",
                                 default=[])
        if project.plans:
            save_project(project)
    if project.plans:
        st.success(f"{len(project.plans)} sheet(s): " + ", ".join(s.name for s in project.plans))
        if st.button("Remove plan sheets"):
            project.plans = []
            save_project(project)
            st.rerun()
    elif st.button("Use sample plan sheet (for testing)"):
        project.plans.append(make_sample_sheet())
        save_project(project)
        st.rerun()

    st.subheader("Report template")
    template = st.file_uploader("Word template (.docx, optional)", type=["docx"])
    if template:
        project.template_path = folder / template.name
        project.template_path.write_bytes(template.getvalue())
    if project.template_path:
        st.caption(f"Template: {project.template_path.name}")

    if st.button("Save project", type="primary", width="stretch"):
        st.success(f"Saved to {save_project(project)}", icon="💾")

    saved = sorted(p for p in PROJECTS_DIR.glob("*/project.json")) if PROJECTS_DIR.exists() else []
    if saved:
        st.subheader("Open a saved project")
        pick = st.selectbox("Saved projects", saved, format_func=lambda p: p.parent.name)
        if st.button("Open", width="stretch"):
            S.project = load_project(pick)
            go("Capture")


def capture_home():
    st.subheader(project.name)
    st.caption(f"{len(project.observations)} entries · "
               f"{len(project.plans)} plan sheet(s)" if project.plans else
               f"{len(project.observations)} entries · no plan set (Setup tab)")

    if st.button("📷 Take / select photo", type="primary", width="stretch"):
        new_entry()
    if st.button("📍 Select location on plan", width="stretch"):
        new_entry(open_location=True)
    if st.button("✏️ Text or voice note", width="stretch"):
        new_entry()

    if project.observations:
        st.divider()
    for obs in reversed(project.observations):
        with st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center"):
                if obs.photos:
                    st.image(str(obs.photos[0]), width=72)
                else:
                    st.markdown("### 📝")
                with st.container():
                    st.markdown(f"**#{obs.number}** {sev_label(obs.severity)}")
                    st.caption((obs.description or "(no description)")[:90]
                               + (" · 📍" if obs.pin else ""))
                if st.button("Open", key=f"open-{obs.id}"):
                    go("Capture", obs.id)


def entry_editor(obs: Observation):
    items = project.observations
    i = items.index(obs)

    # <previous> Item # <next>
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button("◀", key="prev-item", disabled=i == 0):
            go("Capture", items[i - 1].id)
        st.markdown(f"**Item {obs.number} of {len(items)}**")
        if st.button("▶", key="next-item", disabled=i == len(items) - 1):
            go("Capture", items[i + 1].id)
        if st.button("✕ Close", key="close-item"):
            save_project(project)
            go("Capture")

    # Image  (if no image, shows take photo button)
    if obs.photos:
        k = min(S.get("photo_idx", 0), len(obs.photos) - 1)
        st.image(str(obs.photos[k]), width="stretch")
        with st.container(horizontal=True, vertical_alignment="center"):
            if st.button("◀", key="prev-photo", disabled=k == 0):
                S.photo_idx = k - 1
                st.rerun()
            st.markdown(f"**Photo {k + 1} of {len(obs.photos)}**")
            if st.button("▶", key="next-photo", disabled=k == len(obs.photos) - 1):
                S.photo_idx = k + 1
                st.rerun()
            if st.button("🗑", key="del-photo", help="Remove this photo"):
                obs.photos.pop(k)
                obs.photo_path = obs.photos[0] if obs.photos else None
                S.photo_idx = max(0, k - 1)
                save_project(project)
                st.rerun()
        with st.expander("➕ Add another photo"):
            photo_picker(obs, "Add photo")
    else:
        st.markdown("**📷 Take / select photo**")
        photo_picker(obs, "Take or choose photo")

    # Location  (if no location, shows pick location button)
    st.markdown("**📍 Location**")
    if obs.pin and not S.get("show_location_picker"):
        sheet = project.sheet(obs.pin.sheet_id)
        with st.container(horizontal=True, vertical_alignment="center"):
            st.write(f"{sheet.name} · {obs.pin.x:.0%} across, {obs.pin.y:.0%} down "
                     f"({obs.pin.source})")
            if st.button("Change", key="change-pin"):
                S.show_location_picker = True
                st.rerun()
    elif not S.get("show_location_picker"):
        if st.button("Pick location on plan", key="pick-pin", width="stretch"):
            S.show_location_picker = True
            st.rerun()
    if S.get("show_location_picker"):
        location_picker(obs)

    # Description: typed and/or voice
    obs.description = st.text_area("Description", obs.description, key=f"desc-{obs.id}",
                                   placeholder="What do you see?")
    n = S.get(f"audio-n-{obs.id}", 0)
    memo = st.audio_input("🎙️ Voice note (added to description)", key=f"audio-{obs.id}-{n}")
    if memo:
        add_voice_note(obs, memo.getvalue())
        bump(f"audio-n-{obs.id}")
        st.rerun()
    if obs.audio_path and obs.audio_path.exists():
        st.audio(str(obs.audio_path))

    # Importance flag
    obs.severity = st.pills("Importance flag", list(Severity), format_func=sev_label,
                            default=obs.severity, key=f"sev-{obs.id}") or obs.severity

    # Tags + action item
    obs.tags = st.multiselect("Tags", sorted(set(COMMON_TAGS) | set(obs.tags)), default=obs.tags,
                              accept_new_options=True, key=f"tags-{obs.id}")
    obs.action_item = st.text_input("Action item", obs.action_item, key=f"action-{obs.id}",
                                    placeholder="What needs to happen?")

    with st.container(horizontal=True):
        if st.button("💾 Save", type="primary", key="save-item", width="stretch"):
            save_project(project)
            S.saved_msg = f"Entry #{obs.number} saved"
        if st.button("🗑 Delete entry", key="del-item", width="stretch"):
            project.observations.remove(obs)
            renumber()
            save_project(project)
            go("Capture")
    if msg := S.pop("saved_msg", None):
        st.success(msg, icon="💾")


def report_screen():
    obs_list = project.observations
    st.subheader("Report")
    counts = {s: sum(o.severity == s for o in obs_list) for s in Severity}
    st.write(f"{len(obs_list)} entries · " +
             " · ".join(f"{SEVERITY_ICON[s]} {n}" for s, n in counts.items() if n))

    if st.button("✨ Draft with AI", width="stretch", disabled=not obs_list):
        for obs in obs_list:
            obs.description = try_step("Clean caption", ai_writer.clean_up_description, obs,
                                       default=obs.description)
            if not obs.action_item and obs.severity in (Severity.MAJOR, Severity.CRITICAL,
                                                        Severity.SAFETY):
                obs.action_item = try_step("Action item", ai_writer.suggest_action_item, obs,
                                           default="")
        project.summary = try_step("Summary", ai_writer.draft_summary, project,
                                   default=project.summary)
        save_project(project)
    project.summary = st.text_area("Summary", project.summary, height=180)

    # Options dialog
    opts = project.report_options
    with st.expander("Export options"):
        opts["include_marked_plans"] = st.checkbox("Plan sheets with pins", opts.get("include_marked_plans", True))
        opts["include_photo_log"] = st.checkbox("Photo log table", opts.get("include_photo_log", True))
        opts["include_action_items"] = st.checkbox("Action items table", opts.get("include_action_items", True))
        opts["embed_photo_info"] = st.checkbox("Write caption/severity into photo files", opts.get("embed_photo_info", True))
        opts["min_severity"] = st.selectbox("Include entries at or above", list(Severity),
                                            index=list(Severity).index(Severity(opts.get("min_severity", "Info"))),
                                            format_func=sev_label).value

    if st.button("📄 Export report", type="primary", width="stretch", disabled=not obs_list):
        out = folder / "output"
        if opts.get("embed_photo_info", True):
            for obs in obs_list:
                for p in obs.photos:
                    try_step("Embed photo info", photos.embed_observation, obs, out / p.name)
        docx = try_step("Word report", word_report.build_report, project, out / "site_visit_report.docx")
        marked = None
        if opts.get("include_marked_plans", True) and project.plans:
            marked = try_step("Marked-up plans", plan_markup.export_marked_plans, project,
                              out / "marked_plans.pdf")
        save_project(project)
        for path in filter(None, [docx, marked]):
            path = Path(path)
            st.download_button(f"⬇️ {path.name}", path.read_bytes(), file_name=path.name,
                               width="stretch")

    if obs_list:
        st.subheader("Entries")
        for obs in obs_list:
            with st.container(border=True):
                with st.container(horizontal=True, vertical_alignment="center"):
                    if obs.photos:
                        st.image(str(obs.photos[0]), width=72)
                    st.markdown(f"**#{obs.number}** {sev_label(obs.severity)}  \n"
                                f"{obs.description or '(no description)'}")
                    if st.button("Edit", key=f"edit-{obs.id}"):
                        go("Capture", obs.id)


# ---------------------------------------------------------------------- main
st.set_page_config(page_title="SiteScribe", page_icon="🏗️", layout="centered",
                   initial_sidebar_state="collapsed")
st.markdown("""
<style>
  header[data-testid="stHeader"], footer { display: none; }
  .block-container { padding: 0.75rem 0.9rem 4rem; max-width: 720px; }
  .stButton > button { min-height: 2.8rem; }
  h3 { margin-top: 0.4rem; }
</style>
""", unsafe_allow_html=True)

if "project" not in S:
    S.project = Project(name="Untitled site visit")
project: Project = S.project
folder = project_dir(project)

S.setdefault("nav", "Capture")
S.setdefault("editing", None)
if "goto" in S:                 # a button asked to switch screens (see go())
    S.nav = S.pop("goto")
st.segmented_control("Screen", VIEWS, key="nav", required=True, width="stretch",
                     label_visibility="collapsed")

if S.nav == "Setup":
    setup_screen()
elif S.nav == "Report":
    report_screen()
else:
    obs = current_obs()
    if obs:
        entry_editor(obs)
    else:
        capture_home()
