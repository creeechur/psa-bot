"""
A small public HTTP API sitting in front of the same Google Sheet the
Discord bot reads. This is what a Shopify (or any other) website's
JavaScript calls, since Shopify can't run Python/backend code directly.

Deliberately exposes LESS than the bot does:
  - Batch/tier status (no personal data) -> fully public, GET
  - Personal card lookup -> POST only, requires the customer's own exact
    email, and returns ONLY that one match — never the full sheet.

Run locally:   uvicorn web_api:app --reload
Run in prod:   uvicorn web_api:app --host 0.0.0.0 --port $PORT
"""

import time
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

import config
import sheets_client
from formatting import STAGE_ORDER, TIER_ORDER

app = FastAPI(title="PSA Submission Tracker API")

# Only your storefront's origin(s) can call this from a browser.
# Set ALLOWED_ORIGINS in your env, comma-separated, e.g.:
#   ALLOWED_ORIGINS=https://yourstore.myshopify.com,https://www.yourdomain.com
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- Minimal rate limiting on the lookup endpoint ---------------------------
# Prevents someone from scripting thousands of email guesses to enumerate
# who submitted what. In-memory only (resets on redeploy) — fine at this
# traffic scale; swap for Redis if this ever needs to survive restarts.
_lookup_attempts = defaultdict(list)
LOOKUP_LIMIT = 10
LOOKUP_WINDOW_SECONDS = 3600


def _rate_limited(ip: str) -> bool:
    now = time.time()
    attempts = [t for t in _lookup_attempts[ip] if now - t < LOOKUP_WINDOW_SECONDS]
    _lookup_attempts[ip] = attempts
    if len(attempts) >= LOOKUP_LIMIT:
        return True
    _lookup_attempts[ip].append(now)
    return False


# --- Schemas -----------------------------------------------------------------

class LookupRequest(BaseModel):
    batch_date: str
    email: EmailStr


class EmailLookupRequest(BaseModel):
    email: EmailStr


# --- Routes --------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/batches")
def batches():
    """Public: list of current batch dates, no personal data."""
    try:
        dates = sheets_client.list_batch_dates()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't reach the sheet: {e}")
    return {"batches": dates}


@app.get("/api/status/{batch_date}")
def batch_status(batch_date: str):
    """Public: tier pipeline status for one batch, no personal data."""
    try:
        tier_status = sheets_client.get_batch_tier_status(batch_date)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't reach the sheet: {e}")

    if not tier_status:
        raise HTTPException(status_code=404, detail=f"No batch matching '{batch_date}'")

    ordered_tiers = [t for t in TIER_ORDER if t in tier_status] + [
        t for t in tier_status if t not in TIER_ORDER
    ]
    return {
        "batch_date": batch_date,
        "stage_order": STAGE_ORDER,
        "tiers": {t: tier_status[t] for t in ordered_tiers},
    }


@app.post("/api/lookup")
def personal_lookup(payload: LookupRequest, request: Request):
    """
    Returns ONLY the submitter's own rows for one batch — never the full
    sheet. Rate-limited per IP to discourage email-guessing.
    """
    client_ip = request.client.host if request.client else "unknown"
    if _rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Too many lookups — try again later.")

    try:
        rows = sheets_client.find_submissions_for(payload.batch_date, payload.email)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't reach the sheet: {e}")

    if not rows:
        return {"found": False}

    submissions = [
        {"tier": r.get("tier", "Unknown"), "card_qty": int(r.get("card_qty") or 0)}
        for r in rows
    ]
    return {
        "found": True,
        "name": rows[0].get("name", ""),
        "submissions": submissions,
    }


@app.post("/api/lookup-by-email")
def personal_lookup_by_email(payload: EmailLookupRequest, request: Request):
    """
    Search across ALL batches for one email — used when a customer wants to
    find their submission without already knowing the batch date. Same
    rate limiting as /api/lookup, since this is just as scrapeable.
    """
    client_ip = request.client.host if request.client else "unknown"
    if _rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="Too many lookups — try again later.")

    try:
        rows = sheets_client.find_submissions_by_email(payload.email)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't reach the sheet: {e}")

    if not rows:
        return {"found": False}

    # Join each submission with its current pipeline status, looked up once
    # per unique batch (not once per row) to keep sheet reads bounded.
    unique_batches = {r.get("batch_date", "") for r in rows if r.get("batch_date")}
    status_by_batch = {}
    for b in unique_batches:
        try:
            status_by_batch[b] = sheets_client.get_batch_tier_status(b)
        except Exception:
            status_by_batch[b] = {}

    submissions = []
    for r in rows:
        batch = r.get("batch_date", "")
        tier = r.get("tier", "Unknown")
        tier_info = status_by_batch.get(batch, {}).get(tier, {})
        submissions.append(
            {
                "batch_date": batch,
                "tier": tier,
                "card_qty": int(r.get("card_qty") or 0),
                "status": tier_info.get("status", ""),
            }
        )
    return {
        "found": True,
        "name": rows[0].get("name", ""),
        "submissions": submissions,
    }
