"""SiteScribe app. Run with:  streamlit run app.py

Open the Network URL it prints on your phone (same Wi-Fi) to use the camera
and microphone on site.

Owner: ________ (UI). The app only calls functions in the sitescribe package,
so each module can be built and swapped in separately. Until a module is
written, the app shows "not built yet" instead of crashing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st
from PIL import Image
from streamlit_image_coordinates import streamlit_image_coordinates

from sitescribe import ai_writer, locate, photos, plan_markup, plans, voice, word_report
from sitescribe.models import Observation, PlanPin, Project, Severity
from sitescribe.storage import project_dir, save_project

COMMON_TAGS = ["Concrete", "Steel", "Wood", "Masonry", "Connection", "Crack",
               "Corrosion", "Deflection", "Water", "Install per plans", "RFI needed"]


def try_step(label: str, fn, *args, default=None):
    """Run one module function; if it isn't written yet, say so and move on."""
    try:
        return fn(*args)
    except NotImplementedError:
        st.info(f"{label}: not built yet ({fn.__module__}.{fn.__name__})")
    except Exception as exc:  # show teammates' errors without killing the app
        st.error(f"{label} failed: {exc}")
    return default


st.set_page_config(page_title="SiteScribe", page_icon="🏗️", layout="centered")
st.title("SiteScribe")

if "project" not in st.session_state:
    st.session_state.project = Project(name="Untitled site visit")
project: Project = st.session_state.project
folder = project_dir(project)

setup_tab, capture_tab, report_tab = st.tabs(["1 · Before visit", "2 · On site", "3 · Report"])

# ---------------------------------------------------------------- before visit
with setup_tab:
    project.name = st.text_input("Project name", project.name)
    project.site_address = st.text_input("Site address", project.site_address)
    project.engineer = st.text_input("Engineer", project.engineer)

    plan_pdf = st.file_uploader("Plan set (PDF) — required", type=["pdf"])
    if plan_pdf and not project.plans:
        pdf_path = folder / "plans" / plan_pdf.name
        pdf_path.write_bytes(plan_pdf.getvalue())
        project.plans = try_step("Load plans", plans.load_plan_set, pdf_path, folder / "plans", default=[])

    template = st.file_uploader("Report template (Word, optional)", type=["docx"])
    if template:
        project.template_path = folder / template.name
        project.template_path.write_bytes(template.getvalue())

    if project.plans:
        st.success(f"{len(project.plans)} plan sheets loaded")
    if st.button("Save project"):
        st.toast(f"Saved to {save_project(project)}")

# --------------------------------------------------------------------- on site
with capture_tab:
    if not project.plans:
        st.warning("Upload a plan set first (tab 1).")
    else:
        sheet = st.selectbox("Sheet", project.plans, format_func=lambda s: s.name)
        st.caption("Tap the plan where this observation is.")
        image = Image.open(sheet.image_path)
        display_width = 700
        click = streamlit_image_coordinates(image, width=display_width, key=f"plan-{sheet.id}")
        pin = None
        if click:
            pin = PlanPin(sheet.id, click["x"] / display_width,
                          click["y"] / (display_width * image.height / image.width))
            st.caption(f"Pinned at {pin.x:.0%} across, {pin.y:.0%} down")

        shot = st.camera_input("Take photo") or st.file_uploader("…or pick a photo", type=["jpg", "jpeg", "png", "heic"])
        memo = st.audio_input("Voice description")
        typed = st.text_area("…or type a description")
        severity = st.radio("Importance", list(Severity), format_func=lambda s: s.value, horizontal=True)
        tags = st.multiselect("Tags", COMMON_TAGS)
        action = st.text_input("Engineer action / action item")

        if st.button("Save observation", type="primary", disabled=shot is None):
            obs = Observation(severity=severity, tags=tags, action_item=action, pin=pin,
                              number=len(project.observations) + 1)
            obs.photo_path = folder / "media" / f"{obs.number:03d}_{obs.id}.jpg"
            obs.photo_path.write_bytes(shot.getvalue())

            taken_at, obs.gps = try_step("Read photo GPS/time", photos.read_photo_metadata,
                                         obs.photo_path, default=(None, None))
            obs.taken_at = taken_at or datetime.now()
            if obs.pin is None and obs.gps:
                obs.pin = try_step("Pin from GPS", locate.gps_to_pin, obs.gps, sheet)

            obs.description = typed
            if memo:
                obs.audio_path = folder / "media" / f"{obs.number:03d}_{obs.id}.wav"
                obs.audio_path.write_bytes(memo.getvalue())
                spoken = try_step("Transcribe", voice.transcribe, obs.audio_path, default="")
                obs.description = " ".join(filter(None, [typed, spoken]))
                if obs.pin is None and spoken:
                    obs.pin = try_step("Location from speech", voice.location_from_speech,
                                       spoken, project.plans)

            project.observations.append(obs)
            save_project(project)
            st.success(f"Observation #{obs.number} saved")

    for obs in reversed(project.observations):
        st.write(f"**#{obs.number}** · {obs.severity.value} · {obs.description or '(no description)'}")

# ---------------------------------------------------------------------- report
with report_tab:
    st.write(f"{len(project.observations)} observations")
    if st.button("Draft with AI"):
        for obs in project.observations:
            obs.description = try_step("Clean caption", ai_writer.clean_up_description, obs,
                                       default=obs.description)
            if not obs.action_item and obs.severity in (Severity.MAJOR, Severity.CRITICAL, Severity.SAFETY):
                obs.action_item = try_step("Action item", ai_writer.suggest_action_item, obs, default="")
        project.summary = try_step("Summary", ai_writer.draft_summary, project, default=project.summary)
    project.summary = st.text_area("Summary", project.summary, height=200)

    if st.button("Export report", type="primary", disabled=not project.observations):
        out = folder / "output"
        for obs in project.observations:
            try_step("Embed photo info", photos.embed_observation, obs, out / obs.photo_path.name)
        docx = try_step("Word report", word_report.build_report, project, out / "site_visit_report.docx")
        marked = try_step("Marked-up plans", plan_markup.export_marked_plans, project, out / "marked_plans.pdf")
        save_project(project)
        for path in filter(None, [docx, marked]):
            st.download_button(f"Download {Path(path).name}", Path(path).read_bytes(), file_name=Path(path).name)
