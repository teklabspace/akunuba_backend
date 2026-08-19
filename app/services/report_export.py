"""Render a stored report into a real downloadable file.

``GET /reports/{id}/download`` used to serve JSON for every format, including
a stub body reading "File generation for {format} format not yet implemented"
under a ``.json`` filename — the reported "Export button doesn't work".

``Report.parameters`` is free-form JSON whose shape depends on the report
type, so rendering happens in two steps: ``tabulate`` turns any such payload
into flat titled tables, and the per-format renderers draw those tables. That
keeps the renderers ignorant of report types and means a new report type is
exportable the day it is added.

xlsx and pdf need optional dependencies (openpyxl, reportlab). If a deployment
lacks them the renderer raises ``RendererUnavailable`` so the endpoint can
answer 400 UNSUPPORTED_REPORT_FORMAT instead of silently serving the wrong
thing. csv and json have no dependencies and always work.
"""
import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

SUPPORTED_FORMATS = ("csv", "json", "pdf", "xlsx")

MEDIA_TYPES = {
    "csv": "text/csv",
    "json": "application/json",
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class UnsupportedFormat(ValueError):
    """The requested format is not one this module knows how to render."""


class RendererUnavailable(RuntimeError):
    """A known format whose optional renderer dependency is not installed."""


@dataclass
class Section:
    title: str
    headers: List[str]
    rows: List[List[Any]] = field(default_factory=list)


def media_type_for(fmt: str) -> str:
    fmt = _normalize(fmt)
    return MEDIA_TYPES[fmt]


def extension_for(fmt: str) -> str:
    return _normalize(fmt)


def _normalize(fmt: str) -> str:
    normalized = str(fmt or "").strip().lower()
    if normalized not in SUPPORTED_FORMATS:
        raise UnsupportedFormat(
            f"Unsupported export format: {fmt}. Supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    return normalized


def _flatten(value: Any, prefix: str = "") -> List[List[Any]]:
    """Depth-first (dotted.path, value) rows for scalars and nested dicts."""
    rows: List[List[Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten(nested, path))
    elif isinstance(value, list):
        # Lists of records get their own table; anything else renders inline.
        rows.append([prefix, json.dumps(value)])
    else:
        rows.append([prefix, value])
    return rows


def _is_record_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) > 0
        and all(isinstance(item, dict) for item in value)
    )


def tabulate(data: Any) -> List[Section]:
    """Turn a report payload into titled tables.

    Every top-level list-of-records becomes its own table with real columns;
    everything else is folded into a single flat "Summary" key/value table.
    """
    if not isinstance(data, dict):
        data = {"value": data}

    record_lists = {k: v for k, v in data.items() if _is_record_list(v)}
    scalars = {k: v for k, v in data.items() if k not in record_lists}

    sections = [Section(title="Summary", headers=["Field", "Value"], rows=_flatten(scalars))]

    for title, records in record_lists.items():
        headers: List[str] = []
        for record in records:  # union of keys, first-seen order
            for key in record:
                if key not in headers:
                    headers.append(key)
        sections.append(
            Section(
                title=str(title),
                headers=headers,
                # "" for absent keys keeps every row the same width.
                rows=[[record.get(header, "") for header in headers] for record in records],
            )
        )
    return sections


def _cell(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return "" if value is None else value


def _render_csv(sections: List[Section]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    for index, section in enumerate(sections):
        if index:
            writer.writerow([])
        writer.writerow([section.title])
        writer.writerow(section.headers)
        for row in section.rows:
            writer.writerow([_cell(cell) for cell in row])
    # utf-8-sig: without the BOM Excel mangles non-ASCII on open.
    return buffer.getvalue().encode("utf-8-sig")


def _render_xlsx(sections: List[Section]) -> bytes:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RendererUnavailable("xlsx export requires the openpyxl package") from exc

    workbook = Workbook()
    workbook.remove(workbook.active)
    for section in sections:
        # Excel sheet names cap at 31 chars and forbid []:*?/\
        safe_title = "".join(
            char for char in section.title if char not in "[]:*?/\\"
        )[:31] or "Sheet"
        sheet = workbook.create_sheet(title=safe_title)
        sheet.append(section.headers)
        for row in section.rows:
            sheet.append([_cell(cell) for cell in row])

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _render_pdf(sections: List[Section]) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise RendererUnavailable("pdf export requires the reportlab package") from exc

    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(letter), title="Report")
    styles = getSampleStyleSheet()

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])

    story: List[Any] = []
    for index, section in enumerate(sections):
        if index:
            story.append(PageBreak())
        story.append(Paragraph(section.title, styles["Heading2"]))
        story.append(Spacer(1, 8))
        data = [section.headers] + [
            [Paragraph(str(_cell(cell)), styles["BodyText"]) for cell in row]
            for row in section.rows
        ]
        if not section.rows:
            data.append(["" for _ in section.headers] or [""])
        table = Table(data, repeatRows=1)
        table.setStyle(table_style)
        story.append(table)

    document.build(story)
    return buffer.getvalue()


def render(data: Any, fmt: str) -> bytes:
    """Render a report payload as bytes in the requested format."""
    normalized = _normalize(fmt)

    if normalized == "json":
        return json.dumps(data, indent=2, default=str).encode("utf-8")

    sections = tabulate(data)
    if normalized == "csv":
        return _render_csv(sections)
    if normalized == "xlsx":
        return _render_xlsx(sections)
    return _render_pdf(sections)
