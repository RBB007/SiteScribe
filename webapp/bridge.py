"""JSON <-> models adapter: a visit.json plus its files as a `Project`.

Owner: RBB007

The web app stores a visit as JSON (items, photo entries, plans); the
`sitescribe/` modules take the dataclasses in `sitescribe/models.py`. This
file converts one to the other so a route can hand a whole visit to a module
(today: `word_report.build_report`) without either side knowing about the
other's shape. Routes never see the dataclasses; modules never see the JSON.

Mapping (see INTEGRATION_PLAN.md):

    photo entry 003_02            Observation, number 3 (the item), id "003_02"
    entry filename                photo_path and photos[0] (left out if missing)
    entry caption                 captions[filename]; description stays description
    importance                    severity
    location {plan_id,page,x,y}   PlanPin("<plan_id>:<page>", x, y)
    audio_clips[0]                audio_path
    include                       include
    plan page                     PlanSheet with id "<plan_id>:<page>", rendered
                                  by plans.load_plan_set (only plans that have
                                  a pin, since only those appear in the report)

An item with no entries at all (pre-#27 data) becomes one Observation from
the item's own fields, as the export bundle does.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Callable

try:
    import sitescribe  # noqa: F401
except ImportError:  # started as `python server.py` from inside webapp/
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sitescribe import plans
from sitescribe.models import Observation, PlanPin, PlanSheet, Project, Severity

_DETAILS = ("description", "importance", "tags", "location", "include")


def to_project(data: dict, *, name: str, item_dir: Callable[[str], Path | str],
               plans_dir: Path | str, work_dir: Path | str,
               template: Path | str | None = None,
               visit_date: datetime | None = None,
               tz: tzinfo | None = None) -> Project:
    """Build a `Project` from a visit's JSON.

    item_dir(item_id) is the folder an item's photos live in and plans_dir the
    folder the plan files live in. Plan pages are rendered into work_dir, which
    must outlive whatever uses the Project (the Word report reads the PNGs
    while it builds). template is the project's Word template, if any. Aware
    timestamps are shown in tz when given.
    """
    observations = [obs for obs, _ in entries(data, item_dir, tz=tz)]
    sheets = _sheets(data, observations, Path(plans_dir), Path(work_dir))
    project = Project(
        name=name,
        site_address=str(data.get("site_address") or ""),
        engineer=str(data.get("engineer") or ""),
        plans=sheets,
        template_path=Path(template) if template else None,
        observations=observations,
        summary=str(data.get("summary") or ""),
        report_options=dict(data.get("report_options") or {}),
    )
    if visit_date is not None:
        project.visit_date = visit_date
    return project


def entries(data: dict, item_dir: Callable[[str], Path | str], *, tz: tzinfo | None = None):
    """(Observation, photo path or None) for every entry, included or not, in
    item then seq order. An entry whose image is not taken yet (or whose file
    is gone) still has its pin and text; it just has no photo."""
    for item in sorted(data.get("items", []), key=lambda it: str(it.get("item_id"))):
        photos = sorted(item.get("photos") or [], key=lambda ph: ph.get("seq") or 0)
        folder = Path(item_dir(item["item_id"]))
        if not photos:
            yield observation(item, {}, None, folder=folder, tz=tz), None
            continue
        for ph in photos:
            path = folder / ph["filename"] if ph.get("filename") else None
            if path is not None and not path.exists():
                path = None
            yield observation(item, ph, path, folder=folder, tz=tz), path


def observation(item: dict, ph: dict, path: Path | None, *, folder: Path | None = None,
                tz: tzinfo | None = None) -> Observation:
    """One entry as an Observation. The entry's own details win; the item's
    are the fallback for records written before #27. folder is where the
    entry's files live (for its audio clip)."""
    details = {k: ph.get(k, item.get(k)) for k in _DETAILS}
    obs = Observation(
        photo_path=path,
        photos=[path] if path is not None else [],
        description=str(details["description"] or "").strip(),
        severity=severity(details["importance"]),
        tags=[str(t) for t in (details["tags"] or [])],
        pin=pin(details["location"]),
        number=item_number(item.get("item_id")),
        include=details["include"] is not False,
        id=str(ph.get("photo_id") or item.get("item_id") or ""),
    )
    caption = str(ph.get("caption") or "").strip()
    if caption and path is not None:
        obs.captions[path.name] = caption
    clips = ph.get("audio_clips") or []
    if folder is not None and clips and clips[0].get("filename"):
        clip = folder / clips[0]["filename"]
        if clip.exists():
            obs.audio_path = clip
    taken = parse_time(ph.get("created") or item.get("created"), tz)
    if taken is not None:
        obs.taken_at = taken
    return obs


def _sheets(data: dict, observations: list[Observation], plans_dir: Path, work_dir: Path) -> list[PlanSheet]:
    """One PlanSheet per page of every plan that has at least one pin on it,
    rendered to PNG under work_dir. Plans nobody pinned are skipped: the
    report only shows pinned sheets, and rendering is the slow part."""
    pinned = {obs.pin.sheet_id for obs in observations if obs.pin is not None and obs.include}
    sheets: list[PlanSheet] = []
    for plan in data.get("plans", []):
        plan_id = plan.get("plan_id")
        if not plan_id or not plan.get("file"):
            continue
        if not any(sid.startswith(f"{plan_id}:") for sid in pinned):
            continue
        source = plans_dir / plan["file"]
        if not source.exists():
            continue
        try:
            pages = plans.load_plan_set(source, work_dir / str(plan_id))
        except Exception as exc:
            # one unreadable plan file must not cost the whole report; its
            # pins then show no sheet name and no marked-up page
            print(f"[sitescribe] could not render plan {source}: {exc!r}", file=sys.stderr)
            continue
        label = _plan_label(plan)
        for sheet in pages:
            sheet.id = sheet_id(plan_id, sheet.page_index + 1)
            sheet.name = label if len(pages) == 1 else f"{label}, page {sheet.page_index + 1}"
            sheets.append(sheet)
    return sheets


def _plan_label(plan: dict) -> str:
    """The plan's name without a trailing file extension: "S-201.pdf" -> "S-201"."""
    label = str(plan.get("name") or plan["file"]).strip()
    return re.sub(r"\.(pdf|png|jpe?g|heic)$", "", label, flags=re.IGNORECASE) or label


def sheet_id(plan_id, page) -> str:
    return f"{plan_id}:{page}"


def pin(location) -> PlanPin | None:
    if not location or not location.get("plan_id"):
        return None
    try:
        return PlanPin(sheet_id(location["plan_id"], int(location.get("page") or 1)),
                       float(location["x"]), float(location["y"]))
    except (KeyError, TypeError, ValueError):
        return None


def severity(value) -> Severity:
    try:
        return Severity(value)
    except ValueError:
        return Severity.INFO


def item_number(item_id) -> int:
    """003 -> 3 (and I-003 -> 3 for ids written before #27)."""
    match = re.search(r"\d+", str(item_id or ""))
    return int(match.group()) if match else 0


def parse_time(value, tz: tzinfo | None = None) -> datetime | None:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if tz is not None and when.tzinfo is not None:
        when = when.astimezone(tz)
    return when
