"""POST-VISIT: build the site visit report as a Word file.

Owner: Pengyu Chen (@GFDS-PC)
Library: python-docx (docxtpl only for Jinja-tagged firm templates)

Report sections, in order:
    1. Header: project, address, engineer, visit date
    2. Summary                       (project.summary)
    3. Plan sheets with color-coded pins   (plan_markup.sheet_image_with_pins)
    4. Observations: photo + caption + severity + tags, one per block
    5. Action items table            (observations with an action_item)
    6. Photo log: number, time, sheet, severity, short description

Two ways to build, picked by project.template_path:

* No template, or an ordinary .docx (a letterhead, a blank shell, an old
  report): the template's body is emptied, its page setup, headers, footers
  and styles are kept, and the six sections above are written in with
  python-docx. Layout follows the GFDS Structural Observation Record:
  "ITEM 3.1 <tab> description", a "Location:" and "Action:" line, photos
  sized 2.92" tall (one portrait), 4.3" wide (one landscape) or 2.58" tall
  (two side by side).

* A template with Jinja tags ({{ ... }} / {%p ... %}), e.g. GFDS's
  SOR_Template.docx: rendered with docxtpl, so the template decides the
  layout. The context it gets is listed in _template_context().

Item numbering: observations sharing a number are entries of one item.
A lone entry is "ITEM 3"; several are "ITEM 3.1", "ITEM 3.2", ...

Captions: the description is printed once, on the ITEM line. Under a photo
only its own entry in Observation.captions is printed, so the description is
not repeated under every photo.

Report options read from project.report_options (all optional):
    include_marked_plans  bool, default True   section 3
    include_photo_log     bool, default True   section 6
    job_no, site_visit_no str                  header (no Project field yet)

Large phone photos are downscaled to 1600 px on the long side before they go
into the document, so a 60-photo report stays a few MB.
"""

from __future__ import annotations

import io
import logging
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .models import SEVERITY_COLORS, Observation, PlanSheet, Project, Severity

log = logging.getLogger(__name__)

# Photo sizes, measured from GFDS sample reports (inches)
_SINGLE_PORTRAIT_H = 2.92
_SINGLE_LANDSCAPE_W = 4.30
_PAIR_H = 2.58
_PHOTO_MAX_PX = 1600
_PLAN_MAX_PX = 2400
_INDENT_IN = 1.0          # hanging indent for ITEM / Location / Action lines
_SHORT_DESC = 80          # characters of description in the photo log

_TAG_RE = re.compile(rb"\{\{|\{%")
_STEP_RE = re.compile(r"^\d+[\).]\s*")


# ----------------------------------------------------------------------------
# public
# ----------------------------------------------------------------------------
def build_report(project: Project, out_docx: Path) -> Path:
    """Write the report to out_docx and return it. If project.template_path is
    set, start from that .docx so the firm's styles, logo and header carry
    over."""
    _require("docx", "python-docx")
    out_docx = Path(out_docx)
    template = Path(project.template_path) if project.template_path else None
    if template is not None and not template.is_file():
        raise FileNotFoundError(f"Report template not found: {template}")

    entries = _entries(project)
    out_docx.parent.mkdir(parents=True, exist_ok=True)

    if template is not None and _has_jinja_tags(template):
        _build_from_tagged_template(project, entries, template, out_docx)
    else:
        _build_with_python_docx(project, entries, template, out_docx)
    return out_docx


# ----------------------------------------------------------------------------
# what goes in the report
# ----------------------------------------------------------------------------
@dataclass
class _Entry:
    obs: Observation
    label: str                       # "3" or "3.1"
    photos: list[Path] = field(default_factory=list)
    sheet_name: str = ""


def _entries(project: Project) -> list[_Entry]:
    """Included observations in report order, with their ITEM labels."""
    included = [o for o in project.observations if o.include]
    # number 0 means "not numbered yet": each such entry becomes its own item
    next_free = max([o.number for o in included if o.number > 0], default=0)
    numbered: list[tuple[int, int, Observation]] = []
    for i, o in enumerate(included):
        n = o.number
        if n <= 0:
            next_free += 1
            n = next_free
        numbered.append((n, i, o))
    numbered.sort(key=lambda t: (t[0], t[1]))

    counts: dict[int, int] = {}
    for n, _, _ in numbered:
        counts[n] = counts.get(n, 0) + 1

    seen: dict[int, int] = {}
    out = []
    for n, _, o in numbered:
        seen[n] = seen.get(n, 0) + 1
        label = str(n) if counts[n] == 1 else f"{n}.{seen[n]}"
        out.append(_Entry(o, label, _photo_list(o), _sheet_name(project, o)))
    return out


def _photo_list(o: Observation) -> list[Path]:
    paths = list(o.photos) or ([o.photo_path] if o.photo_path else [])
    seen, out = set(), []
    for p in paths:
        p = Path(p)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _sheet_name(project: Project, o: Observation) -> str:
    if o.pin is None:
        return ""
    sheet = next((s for s in project.plans if s.id == o.pin.sheet_id), None)
    return sheet.name if sheet else ""


def _explicit_caption(o: Observation, photo: Path) -> str:
    return (o.captions.get(Path(photo).name) or "").strip()


def _action_parts(action: str) -> tuple[str, list[str]]:
    """'Intro\\n1) step\\n2) step' -> ('Intro', ['step', 'step'])."""
    lines = [ln.strip() for ln in (action or "").splitlines() if ln.strip()]
    if len(lines) > 1 and all(_STEP_RE.match(ln) for ln in lines[1:]):
        return lines[0], [_STEP_RE.sub("", ln) for ln in lines[1:]]
    return " ".join(lines), []


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _sev(o: Observation) -> Severity:
    return o.severity if isinstance(o.severity, Severity) else Severity(o.severity)


def _short(text: str, n: int = _SHORT_DESC) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _time(o: Observation) -> str:
    t = o.taken_at
    return f"{t:%m/%d/%y %H:%M}" if t else ""


def _long_date(project: Project) -> str:
    d = project.visit_date
    return f"{d:%B} {d.day}, {d.year}"


# ----------------------------------------------------------------------------
# images
# ----------------------------------------------------------------------------
def _open_image(path: Path):
    from PIL import Image, ImageOps

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Photo not found: {path}")
    if path.suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif
        except ImportError as exc:
            raise ImportError(
                f"{path.name} is a HEIC photo: pip install pillow-heif") from exc
        pillow_heif.register_heif_opener()
    im = Image.open(path)
    return ImageOps.exif_transpose(im)


def _image_stream(path: Path, max_px: int) -> tuple[io.BytesIO, int, int]:
    """Upright, downscaled copy of the image in memory, plus its size."""
    with _open_image(path) as im:
        im.thumbnail((max_px, max_px))
        buf = io.BytesIO()
        if im.mode in ("RGBA", "LA", "P") or path.suffix.lower() == ".png":
            im.save(buf, "PNG", optimize=True)
        else:
            im.convert("RGB").save(buf, "JPEG", quality=85)
        w, h = im.size
    buf.seek(0)
    return buf, w, h


def _photo_size(w: int, h: int, n: int, max_w_in: float) -> dict:
    """Width or height (inches) for one photo of a group of n."""
    from docx.shared import Inches

    if n == 1:
        if w > h:
            return {"width": Inches(min(_SINGLE_LANDSCAPE_W, max_w_in))}
        hh = _SINGLE_PORTRAIT_H
    else:
        hh = _PAIR_H
    if w / h * hh > max_w_in:
        return {"width": Inches(max_w_in)}
    return {"height": Inches(hh)}


def _plan_image(project: Project, sheet: PlanSheet, entries: list[_Entry],
                tmp: Path) -> Path | None:
    """Sheet PNG with pins: plan_markup's if it is written, else our own."""
    from . import plan_markup

    out = tmp / f"plan_{sheet.id}.png"
    try:
        return Path(plan_markup.sheet_image_with_pins(project, sheet.id, out))
    except NotImplementedError:
        pass
    if not sheet.image_path or not Path(sheet.image_path).is_file():
        log.warning("Plan sheet %s has no rendered image; left out of report", sheet.name)
        return None
    return _draw_pins(sheet, entries, out)


def _draw_pins(sheet: PlanSheet, entries: list[_Entry], out: Path) -> Path:
    from PIL import ImageDraw, ImageFont

    with _open_image(Path(sheet.image_path)) as src:
        im = src.convert("RGB")
    im.thumbnail((_PLAN_MAX_PX, _PLAN_MAX_PX))
    w, h = im.size
    r = max(10, round(max(w, h) / 90))
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=round(r * 1.1))
    except TypeError:              # Pillow < 10.1
        font = ImageFont.load_default()
    for e in entries:
        pin = e.obs.pin
        if pin is None or pin.sheet_id != sheet.id:
            continue
        x, y = pin.x * w, pin.y * h
        color = SEVERITY_COLORS[_sev(e.obs)]
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color, outline="white", width=max(2, r // 6))
        draw.text((x, y), e.label, fill="white", font=font, anchor="mm")
    im.save(out, "PNG", optimize=True)
    return out


# ----------------------------------------------------------------------------
# path 1: python-docx
# ----------------------------------------------------------------------------
def _build_with_python_docx(project: Project, entries: list[_Entry],
                            template: Path | None, out_docx: Path) -> None:
    from docx import Document
    from docx.shared import Pt

    if template is not None:
        doc = Document(str(template))
        _strip_body(doc)
    else:
        doc = Document()
        normal = doc.styles["Normal"]
        normal.font.name = "Arial"
        normal.font.size = Pt(10)

    w = _Writer(doc)
    opts = project.report_options or {}

    w.header(project)
    if project.summary.strip():
        w.heading("Summary")
        for para in _paragraphs(project.summary):
            w.body(para)
    if opts.get("include_marked_plans", True):
        with tempfile.TemporaryDirectory() as tmp:
            w.plan_sheets(project, entries, Path(tmp))
    if entries:
        w.heading("Observations")
        for e in entries:
            w.observation(e)
    w.action_items(entries)
    if opts.get("include_photo_log", True):
        w.photo_log(entries)

    doc.core_properties.title = f"Site Visit Report - {project.name}"
    _zero_image_padding(doc)
    doc.save(str(out_docx))


def _strip_body(doc) -> None:
    """Empty the template's body but keep the final <w:sectPr> (page setup,
    header/footer references), so the letterhead carries over."""
    body = doc.element.body
    for child in list(body):
        if not child.tag.endswith("}sectPr"):
            body.remove(child)


def _zero_image_padding(doc) -> None:
    from docx.oxml.ns import qn

    for inline in doc.element.body.iter(qn("wp:inline")):
        for a in ("distT", "distB", "distL", "distR"):
            inline.set(a, "0")


class _Writer:
    """Writes the six sections. Uses the template's styles where they exist
    and falls back to direct formatting where they don't."""

    def __init__(self, doc):
        from docx.shared import Emu

        self.doc = doc
        s = doc.sections[-1]
        text_w = (s.page_width or Emu(7772400)) - (s.left_margin or Emu(914400)) \
            - (s.right_margin or Emu(914400))
        self.text_w_in = text_w / 914400

    # -- basic blocks ---------------------------------------------------
    def _styled(self, text: str, *styles: str):
        p = self.doc.add_paragraph(text)
        for name in styles:
            try:
                p.style = name
                return p
            except (KeyError, ValueError):
                continue
        return p

    def heading(self, text: str):
        from docx.shared import Pt

        p = self.doc.add_paragraph()
        try:
            p.style = "Heading 1"
        except (KeyError, ValueError):
            pass
        run = p.add_run(text)
        run.bold = True
        if p.style.name != "Heading 1":
            run.font.size = Pt(12)
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.keep_with_next = True
        return p

    def body(self, text: str):
        from docx.shared import Pt

        p = self._styled(text, "Body Text", "Normal")
        p.paragraph_format.space_after = Pt(6)
        return p

    def _hanging(self, p):
        from docx.shared import Inches

        pf = p.paragraph_format
        pf.left_indent = Inches(_INDENT_IN)
        pf.first_line_indent = Inches(-_INDENT_IN)
        pf.tab_stops.add_tab_stop(Inches(_INDENT_IN))
        return p

    def _indented(self, p):
        from docx.shared import Inches

        p.paragraph_format.left_indent = Inches(_INDENT_IN)
        return p

    def _table(self, rows: int, cols: int, widths_in: list[float], header: list[str]):
        from docx.shared import Pt

        t = self.doc.add_table(rows=rows, cols=cols)
        try:
            t.style = "Table Grid"
        except (KeyError, ValueError):
            _set_borders(t)
        _col_widths(t, widths_in)
        for c, text in enumerate(header):
            cell = t.rows[0].cells[c]
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            run.bold = True
            _shade(cell, "D9D9D9")
        _repeat_header(t.rows[0])
        for row in t.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.space_after = Pt(0)
        return t

    def _fit(self, widths: list[float]) -> list[float]:
        k = min(1.0, self.text_w_in / sum(widths))
        return [w * k for w in widths]

    # -- 1. header -------------------------------------------------------
    def header(self, project: Project):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt

        opts = project.report_options or {}
        p = self._styled("", "Title")
        run = p.add_run("Site Visit Report")
        if p.style.name != "Title":
            run.bold = True
            run.font.size = Pt(16)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

        rows = [("Project:", project.name, "Date:", f"{project.visit_date:%m/%d/%y}"),
                ("Address:", project.site_address, "Job No:", str(opts.get("job_no", "") or "")),
                ("Engineer:", project.engineer, "Site Visit No:", str(opts.get("site_visit_no", "") or ""))]
        widths = self._fit([1.0, 3.0, 1.1, 1.4])
        t = self.doc.add_table(rows=len(rows), cols=4)
        _col_widths(t, widths)
        for r, vals in enumerate(rows):
            for c, val in enumerate(vals):
                cell = t.rows[r].cells[c]
                cell.text = ""
                run = cell.paragraphs[0].add_run(val or "")
                run.bold = c in (0, 2)
                cell.paragraphs[0].paragraph_format.space_after = Pt(2)
        self.doc.add_paragraph()

    # -- 3. plan sheets ----------------------------------------------------
    def plan_sheets(self, project: Project, entries: list[_Entry], tmp: Path):
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Inches

        pinned = {e.obs.pin.sheet_id for e in entries if e.obs.pin is not None}
        sheets = [s for s in project.plans if s.id in pinned]
        if not sheets:
            return
        self.heading("Plan Sheets")
        self.legend()
        for sheet in sheets:
            img = _plan_image(project, sheet, entries, tmp)
            if img is None:
                continue
            cap = self.body(sheet.name)
            cap.runs[0].bold = True
            cap.paragraph_format.keep_with_next = True
            stream, w, h = _image_stream(img, _PLAN_MAX_PX)
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            max_h = 7.5
            size = {"width": Inches(self.text_w_in)}
            if h / w * self.text_w_in > max_h:
                size = {"height": Inches(max_h)}
            p.add_run().add_picture(stream, **size)

    def legend(self):
        from docx.shared import RGBColor

        p = self.body("")
        p.add_run("Pin colors:  ")
        for sev in Severity:
            run = p.add_run("● ")
            run.font.color.rgb = RGBColor.from_string(SEVERITY_COLORS[sev].lstrip("#"))
            p.add_run(f"{sev.value}   ")

    # -- 4. observations -----------------------------------------------------
    def observation(self, e: _Entry):
        from docx.shared import Inches, Pt, RGBColor

        o = e.obs
        p = self._hanging(self.body(""))
        p.add_run(f"ITEM {e.label}").bold = True
        p.add_run("\t" + (o.description.strip() or "(no description)"))
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.space_before = Pt(6)

        sev = _sev(o)
        p = self._indented(self.body(""))
        p.add_run("Severity: ")
        run = p.add_run(sev.value)
        run.bold = True
        run.font.color.rgb = RGBColor.from_string(SEVERITY_COLORS[sev].lstrip("#"))
        if o.tags:
            p.add_run("      Tags: " + ", ".join(o.tags))
        p.paragraph_format.keep_with_next = True

        if e.sheet_name:
            p = self._hanging(self.body(""))
            p.add_run("Location:\t" + e.sheet_name)
            p.paragraph_format.keep_with_next = True

        if e.photos:
            self.photos(e)

        intro, steps = _action_parts(o.action_item)
        if intro or steps:
            p = self._hanging(self.body(""))
            p.add_run("Action:\t" + intro)
            for i, step in enumerate(steps, 1):
                sp = self.body(f"{i})\t{step}")
                sp.paragraph_format.left_indent = Inches(_INDENT_IN + 0.25)
                sp.paragraph_format.first_line_indent = Inches(-0.25)
                sp.paragraph_format.tab_stops.add_tab_stop(Inches(_INDENT_IN + 0.25))
                sp.paragraph_format.space_after = Pt(2)

    def photos(self, e: _Entry):
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt

        avail = self.text_w_in - _INDENT_IN
        if len(e.photos) == 1:
            photo = e.photos[0]
            stream, w, h = _image_stream(photo, _PHOTO_MAX_PX)
            p = self._indented(self.doc.add_paragraph())
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(stream, **_photo_size(w, h, 1, avail))
            cap = _explicit_caption(e.obs, photo)
            if cap:
                # keep the photo with its caption only; chaining further would
                # glue every observation together and push them off the page
                p.paragraph_format.keep_with_next = True
                c = self._indented(self.body(cap))
                c.alignment = WD_ALIGN_PARAGRAPH.CENTER
                c.runs[0].italic = True
            else:
                p.paragraph_format.space_after = Pt(6)
            return

        # two or more: two per row in a borderless table, caption under each
        col_w = (self.text_w_in - _INDENT_IN) / 2
        rows = (len(e.photos) + 1) // 2
        t = self.doc.add_table(rows=rows, cols=2)
        t.alignment = WD_TABLE_ALIGNMENT.RIGHT
        _col_widths(t, [col_w, col_w])
        _no_borders(t)
        for i, photo in enumerate(e.photos):
            cell = t.rows[i // 2].cells[i % 2]
            stream, w, h = _image_stream(photo, _PHOTO_MAX_PX)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            p.add_run().add_picture(stream, **_photo_size(w, h, 2, col_w - 0.15))
            cap = _explicit_caption(e.obs, photo)
            if cap:
                cp = cell.add_paragraph()
                cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                cp.add_run(cap).italic = True
        for row in t.rows:
            _cant_split(row)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(0)

    # -- 5. action items -----------------------------------------------------
    def action_items(self, entries: list[_Entry]):
        from docx.shared import RGBColor

        rows = [e for e in entries if e.obs.action_item.strip()]
        if not rows:
            return
        self.heading("Action Items")
        t = self._table(len(rows) + 1, 3, self._fit([0.8, 1.0, 4.7]), ["Item", "Severity", "Action"])
        for r, e in enumerate(rows, 1):
            cells = t.rows[r].cells
            cells[0].text = e.label
            sev = _sev(e.obs)
            cells[1].text = ""
            run = cells[1].paragraphs[0].add_run(sev.value)
            run.font.color.rgb = RGBColor.from_string(SEVERITY_COLORS[sev].lstrip("#"))
            intro, steps = _action_parts(e.obs.action_item)
            cells[2].text = intro
            for i, step in enumerate(steps, 1):
                cells[2].add_paragraph(f"{i}) {step}")

    # -- 6. photo log ----------------------------------------------------------
    def photo_log(self, entries: list[_Entry]):
        rows = [e for e in entries if e.photos]
        if not rows:
            return
        self.heading("Photo Log")
        t = self._table(len(rows) + 1, 5, self._fit([0.6, 1.25, 1.45, 0.8, 2.4]),
                        ["No.", "Time", "Sheet", "Severity", "Description"])
        for r, e in enumerate(rows, 1):
            n = len(e.photos)
            vals = [e.label + (f" ({n})" if n > 1 else ""), _time(e.obs), e.sheet_name,
                    _sev(e.obs).value, _short(e.obs.description)]
            for c, v in enumerate(vals):
                t.rows[r].cells[c].text = v


# -- table XML helpers ---------------------------------------------------------
def _col_widths(table, widths_in: list[float]) -> None:
    """Fixed column widths that Word, LibreOffice and Google Docs all honour:
    grid columns + cell widths + fixed layout."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls, qn
    from docx.shared import Inches

    table.autofit = False
    tblPr = table._tbl.tblPr
    for tag in ("w:tblW", "w:tblLayout"):
        old = tblPr.find(qn(tag))
        if old is not None:
            tblPr.remove(old)
    total = sum(round(w * 1440) for w in widths_in)
    tblPr.append(parse_xml(f'<w:tblW {nsdecls("w")} w:w="{total}" w:type="dxa"/>'))
    tblPr.append(parse_xml(f'<w:tblLayout {nsdecls("w")} w:type="fixed"/>'))
    for gc, w in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths_in):
        gc.set(qn("w:w"), str(round(w * 1440)))
    for row in table.rows:
        for cell, w in zip(row.cells, widths_in):
            cell.width = Inches(w)


def _borders_xml(val: str) -> str:
    from docx.oxml.ns import nsdecls

    edges = "".join(f'<w:{k} w:val="{val}" w:sz="4" w:space="0" w:color="808080"/>'
                    for k in ("top", "left", "bottom", "right", "insideH", "insideV"))
    return f"<w:tblBorders {nsdecls('w')}>{edges}</w:tblBorders>"


def _put_borders(table, val: str) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import qn

    tblPr = table._tbl.tblPr
    old = tblPr.find(qn("w:tblBorders"))
    if old is not None:
        tblPr.remove(old)
    tblPr.append(parse_xml(_borders_xml(val)))


def _set_borders(table) -> None:
    _put_borders(table, "single")


def _no_borders(table) -> None:
    _put_borders(table, "nil")


def _shade(cell, hex_fill: str) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    cell._tc.get_or_add_tcPr().append(
        parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{hex_fill}"/>'))


def _repeat_header(row) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    row._tr.get_or_add_trPr().append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))


def _cant_split(row) -> None:
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    row._tr.get_or_add_trPr().append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))


# ----------------------------------------------------------------------------
# path 2: Jinja-tagged template (docxtpl)
# ----------------------------------------------------------------------------
def _has_jinja_tags(template: Path) -> bool:
    with zipfile.ZipFile(template) as z:
        for name in z.namelist():
            if name.startswith("word/") and name.endswith(".xml") and (
                    "document" in name or "header" in name or "footer" in name):
                if _TAG_RE.search(z.read(name)):
                    return True
    return False


def _build_from_tagged_template(project: Project, entries: list[_Entry],
                                template: Path, out_docx: Path) -> None:
    _require("docxtpl", "docxtpl")
    from docxtpl import DocxTemplate

    tpl = DocxTemplate(str(template))
    with tempfile.TemporaryDirectory() as tmp:
        ctx = _template_context(tpl, project, entries, Path(tmp))
        tpl.render(ctx, autoescape=True)
    _zero_image_padding(tpl.docx)
    tpl.docx.core_properties.title = f"Site Visit Report - {project.name}"
    tpl.save(str(out_docx))


def _template_context(tpl, project: Project, entries: list[_Entry], tmp: Path) -> dict:
    """Variables a tagged template can use.

    GFDS SOR_Template.docx names (unchanged from SOR_Report_App):
        date_short, date_long, job_no, project_name, project_address,
        observer, site_visit_no, stage_of_construction [paragraphs],
        structural_elements_observed [paragraphs], previous_items [],
        items [{number, description, location, caption, photos [images],
                action, action_list [str], photos_after_action []}]
    Extra, for templates that want them:
        summary [paragraphs], legend [{name, color}],
        items[].severity, .severity_color, .tags, .time, .captions [str],
        action_items [{number, severity, action, action_list}],
        photo_log [{number, time, sheet, severity, description}],
        plans [{name, image}]
    """
    from docx.shared import Inches
    from docxtpl import InlineImage

    opts = project.report_options or {}

    def images(e: _Entry) -> list:
        # SOR template: a group sits on one line right of a 1.5" indent (~4.4"
        # usable) with ~0.55" gaps between photos
        n = len(e.photos)
        max_w = 4.3 if n <= 1 else (4.2 - 0.6 * (n - 1)) / n
        out = []
        for p in e.photos:
            stream, w, h = _image_stream(p, _PHOTO_MAX_PX)
            out.append(InlineImage(tpl, stream, **_photo_size(w, h, n, max_w)))
        return out

    items = []
    for e in entries:
        o = e.obs
        caps = [_explicit_caption(o, p) for p in e.photos]
        distinct = [c for c in dict.fromkeys(caps) if c]
        action, steps = _action_parts(o.action_item)
        sev = _sev(o)
        items.append({
            "number": e.label,
            "description": o.description.strip(),
            "location": e.sheet_name,
            "caption": "; ".join(distinct),
            "captions": caps,
            "photos": images(e),
            "action": action,
            "action_list": steps,
            "photos_after_action": [],
            "severity": sev.value,
            "severity_color": SEVERITY_COLORS[sev],
            "tags": list(o.tags),
            "time": _time(o),
        })

    plans = []
    if opts.get("include_marked_plans", True):
        pinned = {e.obs.pin.sheet_id for e in entries if e.obs.pin is not None}
        for sheet in (s for s in project.plans if s.id in pinned):
            img = _plan_image(project, sheet, entries, tmp)
            if img is not None:
                stream, _, _ = _image_stream(img, _PLAN_MAX_PX)
                plans.append({"name": sheet.name, "image": InlineImage(tpl, stream, width=Inches(6.5))})

    summary = _paragraphs(project.summary)
    stage = opts.get("stage_of_construction")
    return {
        "date_short": f"{project.visit_date:%m/%d/%y}",
        "date_long": _long_date(project),
        "job_no": str(opts.get("job_no", "") or ""),
        "project_name": project.name,
        "project_address": project.site_address,
        "observer": project.engineer,
        "site_visit_no": str(opts.get("site_visit_no", "") or ""),
        "stage_of_construction": _paragraphs(stage) if stage else summary,
        "structural_elements_observed": _paragraphs(
            opts.get("structural_elements_observed")
            or "The structural framing was observed to be in general conformance with the "
               "structural drawings except for the following items:"),
        "summary": summary,
        "items": items,
        "previous_items": list(opts.get("previous_items") or []),
        "action_items": [{"number": i["number"], "severity": i["severity"],
                          "action": i["action"], "action_list": i["action_list"]}
                         for i in items if i["action"] or i["action_list"]],
        "photo_log": [{"number": e.label, "time": _time(e.obs), "sheet": e.sheet_name,
                       "severity": _sev(e.obs).value, "description": _short(e.obs.description)}
                      for e in entries if e.photos],
        "plans": plans,
        "legend": [{"name": s.value, "color": SEVERITY_COLORS[s]} for s in Severity],
    }


# ----------------------------------------------------------------------------
def _require(module: str, package: str) -> None:
    try:
        __import__(module)
    except ImportError as exc:
        raise ImportError(f"word_report needs {package}: pip install {package}") from exc
