import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")  # used on Railway/Render
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")

SUBMISSIONS_TAB = os.getenv("SUBMISSIONS_TAB", "Submissions")
STATUS_TAB = os.getenv("STATUS_TAB", "Status")

# Channel the bot auto-posts updates to when the Status tab changes
UPDATES_CHANNEL_ID = int(os.getenv("UPDATES_CHANNEL_ID", "0") or 0)

# How often (seconds) the bot polls the sheet for changes
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))

# Comma-separated Discord role names allowed to run !psa update
ADMIN_ROLE_NAMES = [
    r.strip() for r in os.getenv("ADMIN_ROLE_NAMES", "PSA Staff,Admin").split(",") if r.strip()
]

STATE_FILE = os.getenv("STATE_FILE", "data/last_status.json")
