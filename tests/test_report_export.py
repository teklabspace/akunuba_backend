"""Pure tests for app/services/report_export.py.

The Export button was reported as "not working". GET /reports/{id}/download
only ever returned JSON: for pdf/csv/xlsx it served a stub body reading
"File generation for {format} format not yet implemented", with a
.json filename — so the user got a file that was neither the format they
asked for nor useful data.
"""
import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report_export import (
    RendererUnavailable,
    UnsupportedFormat,
    extension_for,
    media_type_for,
    render,
    tabulate,
)

# Shape of Report.parameters for a portfolio report: scalars, a nested dict of
# dicts, and (for transaction reports) lists of uniform records.
PORTFOLIO = {
    "total_value": 125000.5,
    "asset_count": 3,
    "asset_allocation": {
        "crypto": {"count": 2, "value": 25000.0, "percentage": 20.0},
        "stock": {"count": 1, "value": 100000.5, "percentage": 80.0},
    },
}

TRANSACTIONS = {
    "period": {"start": "2026-01-01", "end": "2026-03-01"},
    "transactions": [
        {"date": "2026-01-04", "symbol": "BTC", "amount": 1200.0},
        {"date": "2026-02-11", "symbol": "ETH", "amount": -300.5},
    ],
}


# --- turning report JSON into tables --------------------------------------

def test_scalars_become_a_summary_section():
    sections = tabulate(PORTFOLIO)
    summary = next(s for s in sections if s.title == "Summary")
    assert summary.headers == ["Field", "Value"]
    assert ["total_value", "125000.5"] in [
        [str(cell) for cell in row] for row in summary.rows
    ]


def test_nested_dicts_are_flattened_with_dotted_paths():
    sections = tabulate(PORTFOLIO)
    summary = next(s for s in sections if s.title == "Summary")
    keys = [str(row[0]) for row in summary.rows]
    assert "asset_allocation.crypto.percentage" in keys


def test_a_list_of_records_becomes_its_own_table_with_real_columns():
    sections = tabulate(TRANSACTIONS)
    table = next(s for s in sections if s.title == "transactions")
    assert table.headers == ["date", "symbol", "amount"]
    assert len(table.rows) == 2


def test_records_with_differing_keys_still_share_one_header_row():
    sections = tabulate({"rows": [{"a": 1}, {"b": 2}]})
    table = next(s for s in sections if s.title == "rows")
    assert table.headers == ["a", "b"]
    assert table.rows == [[1, ""], ["", 2]]


def test_empty_report_still_produces_a_section():
    # An empty report must download as a valid (if bare) file, not crash.
    assert tabulate({}) != []


# --- csv ------------------------------------------------------------------

def test_csv_contains_the_record_rows():
    payload = render(TRANSACTIONS, "csv")
    text = payload.decode("utf-8-sig")
    parsed = list(csv.reader(io.StringIO(text)))
    assert ["date", "symbol", "amount"] in parsed
    assert ["2026-01-04", "BTC", "1200.0"] in parsed


def test_csv_is_excel_friendly_utf8():
    # Without the BOM Excel mangles non-ASCII on open.
    assert render(PORTFOLIO, "csv").startswith(b"\xef\xbb\xbf")


def test_csv_separates_sections():
    text = render(TRANSACTIONS, "csv").decode("utf-8-sig")
    assert "Summary" in text and "transactions" in text


# --- xlsx -----------------------------------------------------------------

def test_xlsx_is_a_real_workbook():
    payload = render(TRANSACTIONS, "xlsx")
    assert payload[:2] == b"PK"  # xlsx is a zip container


def test_xlsx_has_a_sheet_per_section():
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.load_workbook(io.BytesIO(render(TRANSACTIONS, "xlsx")))
    assert "transactions" in workbook.sheetnames


# --- pdf ------------------------------------------------------------------

def test_pdf_has_a_pdf_header():
    assert render(PORTFOLIO, "pdf").startswith(b"%PDF")


# --- json -----------------------------------------------------------------

def test_json_round_trips_the_report_unchanged():
    import json

    assert json.loads(render(PORTFOLIO, "json")) == PORTFOLIO


# --- format plumbing ------------------------------------------------------

def test_media_types_are_correct_per_format():
    assert media_type_for("csv") == "text/csv"
    assert media_type_for("json") == "application/json"
    assert media_type_for("pdf") == "application/pdf"
    assert media_type_for("xlsx") == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_extensions_match_the_requested_format():
    assert [extension_for(f) for f in ("csv", "json", "pdf", "xlsx")] == [
        "csv",
        "json",
        "pdf",
        "xlsx",
    ]


def test_an_unknown_format_is_rejected():
    with pytest.raises(UnsupportedFormat):
        render(PORTFOLIO, "docx")


# --- the enum wiring that kept the reports table permanently empty ---------

def test_report_columns_send_lowercase_values_not_member_names():
    """Without values_callable SQLAlchemy sends "PORTFOLIO"/"CSV" while the PG
    types hold lowercase values, so every insert died and no report could ever
    be generated — let alone exported."""
    from app.models.report import Report

    columns = Report.__table__.c
    assert sorted(columns.report_type.type.enums) == [
        "custom",
        "performance",
        "portfolio",
        "tax",
        "transaction",
    ]
    assert sorted(columns.format.type.enums) == ["csv", "json", "pdf", "xlsx"]
    assert sorted(columns.status.type.enums) == [
        "completed",
        "failed",
        "generating",
        "pending",
    ]


def test_report_type_does_not_collide_with_the_asset_report_enum():
    """app/models/report.py and app/models/asset.py both define a class called
    ReportType with different members. Sharing the default PG type name
    "reporttype" meant `reports` inherited asset_reports' labels
    (summary/detailed/tax/insurance) and rejected every platform value."""
    from app.models.asset import ReportType as AssetReportType
    from app.models.report import Report, ReportType as PlatformReportType

    assert Report.__table__.c.report_type.type.name == "platformreporttype"
    assert {m.value for m in PlatformReportType} != {m.value for m in AssetReportType}


def test_renderer_unavailable_is_distinct_from_unknown_format():
    # A missing optional dependency must be reportable as "this deployment
    # can't render that", not confused with a bad request value.
    assert issubclass(RendererUnavailable, Exception)
    assert not issubclass(RendererUnavailable, UnsupportedFormat)
