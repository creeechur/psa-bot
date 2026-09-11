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
   - `Tier` = Value Bulk / Value Max / Standard / Regular / Express / Super Express / Walkthrough
     (matches `TIER_ORDER` in `formatting.py` — update both together if this changes again).

2. **`Status`** — you (staff) maintain this one, either by editing the sheet
   directly or by running `/psa update` in Discord. Columns:
   `Batch Date | Tier | Status | Last Updated`
   - `Status` should be one of: `Order Received`, `Scans Pending`,
     `Research & ID`, `Grading`, `Assembly`, `Completing`.

Since PSA's own tracker is down, **you update the `Status` tab manually once
a week** (5 tiers × however many active batches = a couple minutes of
typing). The bot picks up the change automatically — either instantly if you
use `/psa update`, or within one polling cycle (default 5 min) if you just
edit the sheet by hand.

## What customers see

The bot uses Discord **slash commands** — type `/psa` and Discord shows the
options, no need to remember exact syntax.

```
/psa submission
> (leave batch_date blank) → a dropdown appears with the current batches:
> May 11, May 31, June 13, June 28, July 4, July 27
> Pick one → shows that batch's status

/psa submission batch_date: May 31
> 📦 PSA Submission — May 31
> Super Express   ~~Order Received~~ ↓ ~~Scans Pending~~ ↓ ~~Research & ID~~ ↓ 🟠 **Assembly**
> Express         ~~Order Received~~ ↓ ~~Scans Pending~~ ↓ 🟡 **Grading**
> ...
> [🔎 Check my cards] ← button, opens a small form for their email, no typing a reply needed
```

The embed colour shifts based on how far along the batch is. Customers tap
**Check my cards** to see their personal card count for that batch — this
opens a small popup form (a "modal"), so nothing needs to be typed as a
regular message.

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
3. **Privileged Gateway Intents**: none of these need to be enabled — slash
   commands don't read raw message content, so this bot doesn't need
   Message Content Intent at all.
4. **OAuth2 → URL Generator**: scopes = `bot` **and** `applications.commands`
   (both — slash commands won't register without the second one),
   permissions = `Send Messages`, `Embed Links`, `Read Message History`,
   `Use Slash Commands`. Use the generated URL to invite it to your server.

### 4. Configure and run
```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste your DISCORD_TOKEN, GOOGLE_SHEET_ID (from the sheet's
# URL), UPDATES_CHANNEL_ID (right-click a channel with Developer Mode on ->
# Copy Channel ID), and optionally TEST_GUILD_ID (right-click your server
# icon -> Copy Server ID) so slash commands sync instantly while you test

python bot.py
```
On startup, watch the logs for `Synced N slash command(s)`. With
`TEST_GUILD_ID` set, the `/psa` commands appear in your server within
seconds. Without it, Discord's global sync can take up to an hour to
propagate the first time.

### 5. Give staff the update role
Create a Discord role (default expected name: `PSA Staff`) and assign it to
whoever should be allowed to run `/psa update`. Server Admins can always run
it too. Change allowed role names via `ADMIN_ROLE_NAMES` in `.env`.

## Commands

All commands are Discord slash commands — type `/psa` in any channel the bot
can see and Discord will show the options and autocomplete valid values
(batch dates, tiers, stages) as you type.

| Command | Who | What it does |
|---|---|---|
| `/psa submission` | anyone | Leave `batch_date` blank to get a dropdown of current batches |
| `/psa submission batch_date:` | anyone | Shows that batch's pipeline directly |
| `/psa submission batch_date: email:` | anyone | Also shows your personal card count for that batch |
| *(button on the result) 🔎 Check my cards* | anyone | Opens a small form to enter your email — no typing a reply message |
| `/psa update` | staff | Prompts for batch/tier/new status (autocompleted), writes to the sheet, and auto-announces the change |
| `/psa help` | anyone | Prints the command list |

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
