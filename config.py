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

# Comma-separated list of origins allowed to call the public web API (used by
# web_api.py, e.g. your Shopify storefront). Leave unset to allow all origins
# (fine for testing, but set this in production).
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
] or None

# Optional: your Discord server's ID. If set, slash commands sync instantly
# to that one server (great for testing). If unset, commands sync globally,
# which can take up to an hour to show up everywhere.
TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0") or 0) or None

# Railway auto-injects RAILWAY_VOLUME_MOUNT_PATH once a volume is attached to
# this service, pointing at wherever it actually mounted it — using that
# directly means we never have to guess/hardcode the right path.
_volume_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
if os.getenv("STATE_FILE"):
    STATE_FILE = os.getenv("STATE_FILE")
elif _volume_mount:
    STATE_FILE = os.path.join(_volume_mount, "last_status.json")
else:
    STATE_FILE = "data/last_status.json"
