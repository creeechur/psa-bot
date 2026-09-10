"""
Thin wrapper around gspread for reading the Submissions form-responses tab
and the manually-maintained Status tab, plus writing status updates back.

Expected sheet layout
----------------------
Tab "Submissions" (this is what a linked Google Form dumps into):
    Timestamp | Name | Email | Submission Date | Tier | Card Quantity | Notes

    - "Submission Date" is the BATCH date (e.g. "May 31"), not the form
      timestamp. If your form only captures the timestamp, add a column
      (or a lookup formula) for the batch date your team assigns.
    - "Tier" should be one of: Super Express, Express, Regular, Value Max,
      TCG Bulk Grading (free text also works, it's just displayed as-is).

Tab "Status" (maintained by staff, weekly):
    Batch Date | Tier | Status | Last Updated

    - "Status" should be one of the STAGE_ORDER values in formatting.py:
      Order Received, Scans Pending, Research & ID, Grading, Assembly,
      Completing
"""

import datetime
import json
import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_gc = None
_sheet = None


def _load_credentials():
    """
    Loads the service account credentials either from:
      - GOOGLE_SERVICE_ACCOUNT_JSON (the raw JSON pasted as one env var — used
        on Railway/Render, where you can't just drop a file on disk), or
      - GOOGLE_SERVICE_ACCOUNT_FILE (a local service_account.json path — used
        for local development).
    """
    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file(
        config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )


def _client():
    global _gc, _sheet
    if _gc is None:
        creds = _load_credentials()
        _gc = gspread.authorize(creds)
        _sheet = _gc.open_by_key(config.GOOGLE_SHEET_ID)
    return _sheet


def get_submissions() -> list[dict]:
    """Returns every row of the Submissions tab as a list of dicts."""
    ws = _client().worksheet(config.SUBMISSIONS_TAB)
    return ws.get_all_records()


def get_status_rows() -> list[dict]:
    """Returns every row of the Status tab as a list of dicts."""
    ws = _client().worksheet(config.STATUS_TAB)
    return ws.get_all_records()


def list_batch_dates() -> list[str]:
    """Distinct batch dates, in first-seen order, sourced from the Status tab
    (falls back to Submissions if Status is empty)."""
    rows = get_status_rows()
    dates = []
    for r in rows:
        d = str(r.get("Batch Date", "")).strip()
        if d and d not in dates:
            dates.append(d)
    if dates:
        return dates

    rows = get_submissions()
    for r in rows:
        d = str(r.get("Submission Date", "")).strip()
        if d and d not in dates:
            dates.append(d)
    return dates


def get_batch_tier_status(batch_date: str) -> dict:
    """{tier: status} for one batch date."""
    rows = get_status_rows()
    result = {}
    for r in rows:
        if str(r.get("Batch Date", "")).strip().lower() == batch_date.strip().lower():
            tier = str(r.get("Tier", "")).strip()
            status = str(r.get("Status", "")).strip()
            if tier:
                result[tier] = status
    return result


def find_submissions_for(batch_date: str, email: str) -> list[dict]:
    rows = get_submissions()
    out = []
    for r in rows:
        row_date = str(r.get("Submission Date", "")).strip().lower()
        row_email = str(r.get("Email", "")).strip().lower()
        if row_date == batch_date.strip().lower() and row_email == email.strip().lower():
            out.append(
                {
                    "name": r.get("Name", ""),
                    "tier": r.get("Tier", ""),
                    "card_qty": r.get("Card Quantity", 0),
                }
            )
    return out


def update_status(batch_date: str, tier: str, new_status: str) -> str:
    """
    Updates (or creates) the Status row for (batch_date, tier).
    Returns the OLD status string (empty if the row was just created).
    """
    ws = _client().worksheet(config.STATUS_TAB)
    records = ws.get_all_records()
    header = ws.row_values(1)

    col_batch = header.index("Batch Date") + 1
    col_tier = header.index("Tier") + 1
    col_status = header.index("Status") + 1
    col_updated = header.index("Last Updated") + 1 if "Last Updated" in header else None

    for i, r in enumerate(records, start=2):  # row 1 is header
        if (
            str(r.get("Batch Date", "")).strip().lower() == batch_date.strip().lower()
            and str(r.get("Tier", "")).strip().lower() == tier.strip().lower()
        ):
            old_status = str(r.get("Status", ""))
            ws.update_cell(i, col_status, new_status)
            if col_updated:
                ws.update_cell(i, col_updated, datetime.date.today().isoformat())
            return old_status

    # no existing row — append a new one
    new_row = [""] * len(header)
    new_row[col_batch - 1] = batch_date
    new_row[col_tier - 1] = tier
    new_row[col_status - 1] = new_status
    if col_updated:
        new_row[col_updated - 1] = datetime.date.today().isoformat()
    ws.append_row(new_row)
    return ""
