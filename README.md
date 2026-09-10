# PSA Submission Tracker — Discord Bot

Pulls PSA submission data from a Google Sheet and lets customers check batch
status in Discord instead of messaging you directly.

## How it's structured

Rather than parsing raw files inside a Drive folder (fragile — filenames and
formats drift), the bot reads **one Google Sheet with two tabs**:

1. **`Submissions`** — this is what your Google Form should feed into
   automatically (Form → Responses → this Sheet). Columns:
   `Timestamp | Name | Email | Submission Date | Tier | Card Quantity | Notes`
   - `Submission Date` is the **batch** date you assign (e.g. `May 31`), not
     necessarily the form timestamp.
   - `Tier` = Super Express / Express / Regular / Value Max / TCG Bulk Grading.

2. **`Status`** — you (staff) maintain this one, either by editing the sheet
   directly or by running `!psa update` in Discord. Columns:
   `Batch Date | Tier | Status | Last Updated`
   - `Status` should be one of: `Order Received`, `Scans Pending`,
     `Research & ID`, `Grading`, `Assembly`, `Completing`.

Since PSA's own tracker is down, **you update the `Status` tab manually once
a week** (5 tiers × however many active batches = a couple minutes of
typing). The bot picks up the change automatically — either instantly if you
use `!psa update`, or within one polling cycle (default 5 min) if you just
edit the sheet by hand.

## What customers see

```
!psa submission
> Listing the current PSA submission batches. Please reply with the batch
> date you'd like to look at: May 11, May 31, June 13, June 28, July 4, July 27

May 31
> 📦 PSA Submission — May 31
> Super Express   ✅ Order Received → ✅ Scans Pending → ✅ Research & ID → 🔵 **Assembly** → ⬜ Completing
> Express         ✅ Order Received → ✅ Scans Pending → 🔵 **Grading** → ⬜ Assembly → ⬜ Completing
> Regular         ✅ Order Received → ✅ Scans Pending → 🔵 **Grading** → ⬜ Assembly → ⬜ Completing
> Value Max       ✅ Order Received → 🔵 **Research & ID** → ⬜ Grading → ⬜ Assembly → ⬜ Completing
> TCG Bulk        ✅ Order Received → 🔵 **Research & ID** → ⬜ Grading → ⬜ Assembly → ⬜ Completing
```

The embed colour shifts (grey → gold → orange → blue → green) based on how
far along the batch is. Customers can then reply with their email to get
their personal card count for that batch — no need to message you.

## Setup

### 1. Create the Google Sheet
Create a sheet with the two tabs described above, headers in row 1. Link
your PSA submission Google Form to write into `Submissions`.

### 2. Google service account (lets the bot read/write the sheet)
1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create
   a project (or reuse one).
2. Enable the **Google Sheets API** and **Google Drive API**.
3. Go to **IAM & Admin → Service Accounts → Create Service Account**.
4. Once created, open it → **Keys → Add Key → Create new key → JSON**.
   This downloads a `.json` file — rename it `service_account.json` and put
   it in this project folder. **Never commit or share this file.**
5. Open your Google Sheet → **Share** → paste the service account's email
   (looks like `xxx@xxx.iam.gserviceaccount.com`) → give it **Editor** access.

### 3. Discord bot
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. **Bot** tab → Add Bot → copy the token.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
4. **OAuth2 → URL Generator**: scopes = `bot`, permissions = `Send Messages`,
   `Embed Links`, `Read Message History`. Use the generated URL to invite it
   to your server.

### 4. Configure and run
```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste your DISCORD_TOKEN, GOOGLE_SHEET_ID (from the sheet's
# URL), and UPDATES_CHANNEL_ID (right-click a channel with Developer Mode
# on -> Copy Channel ID)

python bot.py
```

### 5. Give staff the update role
Create a Discord role (default expected name: `PSA Staff`) and assign it to
whoever should be allowed to run `!psa update`. Server Admins can always run
it too. Change allowed role names via `ADMIN_ROLE_NAMES` in `.env`.

## Commands

| Command | Who | What it does |
|---|---|---|
| `!psa submission` | anyone | Lists batches, waits for your reply |
| `!psa submission <date>` | anyone | Shows that batch's pipeline directly |
| `!psa submission <date> <email>` | anyone | Shows your personal card count for that batch |
| `!psa update <date> <tier> <status>` | staff | Updates a tier's stage, writes to the sheet, and auto-announces the change |
| `!psahelp` | anyone | Prints the command list |

Example staff update:
```
!psa update "May 31" "Super Express" Assembly
```
(Quote the batch date and tier if they contain spaces.)

## Notes / things you'll likely want to tweak
- **Stage names**: edit `STAGE_ORDER` in `formatting.py` if PSA's pipeline
  wording changes.
- **Tier names/order**: edit `TIER_ORDER` in `formatting.py`.
- **Polling interval**: `POLL_INTERVAL_SECONDS` in `.env` — lower this if you
  want near-instant announcements when someone edits the sheet by hand
  (mind Google Sheets API quotas: 300 read requests/min per project is the
  default, so 60s is a safe floor for a single sheet).
- **Hosting**: this needs to run 24/7 somewhere — a small VPS, Railway,
  Render, or a Raspberry Pi all work fine; `python bot.py` is the entrypoint.
- **Drive-folder version**: if you'd rather point this at individual files
  in a Drive submission folder instead of a Sheet, that's a heavier build
  (parsing filenames/PDFs/CSVs per submission, no consistent schema) — the
  Sheet-based approach above gets you the same customer-facing result with
  far less fragility, since Sheets already give you a clean row-per-submission
  structure that Forms populate automatically.
