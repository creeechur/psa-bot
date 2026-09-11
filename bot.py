import asyncio
import datetime
import json
import os

import discord
from discord.ext import commands, tasks

import config
import sheets_client
from formatting import batch_embed, personal_lookup_embed, change_announcement_embed

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=config.COMMAND_PREFIX, intents=intents, help_command=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_admin(ctx: commands.Context) -> bool:
    if ctx.author.guild_permissions.administrator:
        return True
    user_roles = {r.name for r in getattr(ctx.author, "roles", [])}
    return bool(user_roles.intersection(config.ADMIN_ROLE_NAMES))


def load_state() -> dict:
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    os.makedirs(os.path.dirname(config.STATE_FILE), exist_ok=True)
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def state_key(batch_date: str, tier: str) -> str:
    return f"{batch_date}::{tier}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@bot.group(invoke_without_command=True)
async def psa(ctx: commands.Context, *args):
    """
    !psa submission                       -> lists batches, waits for a reply
    !psa submission <batch date>          -> shows the pipeline for that batch
    !psa submission <batch date> <email>  -> shows your personal card count
    """
    if not args:
        await ctx.send(
            "Try `!psa submission` to see current batches, "
            "or `!psa update <batch> <tier> <status>` if you're staff."
        )
        return
    if args[0].lower() == "submission":
        await handle_submission(ctx, args[1:])
    else:
        await ctx.send(f"Unknown subcommand `{args[0]}`. Try `!psa submission`.")


async def handle_submission(ctx: commands.Context, rest: tuple):
    if not rest:
        # Step 1: list batches, wait for a reply with the date
        try:
            dates = await asyncio.to_thread(sheets_client.list_batch_dates)
        except Exception as e:
            await ctx.send(f"⚠️ Couldn't reach the tracking sheet: `{e}`")
            return

        if not dates:
            await ctx.send("No submission batches are currently on file.")
            return

        await ctx.send(
            "Listing the current PSA submission batches. "
            f"Please reply with the batch date you'd like to look at: {', '.join(dates)}"
        )

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            reply = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("No reply received — run `!psa submission` again when you're ready.")
            return

        await show_batch(ctx, reply.content.strip())
        return

    # Direct form: !psa submission <date> [email]
    # "rest" arrives as separate words (e.g. "May" "31"), so a multi-word
    # date like "May 31" must be rejoined rather than taking rest[0] alone.
    tokens = list(rest)
    email = None
    if tokens and "@" in tokens[-1]:
        email = tokens.pop()
    batch_date = " ".join(tokens).strip()

    if not batch_date:
        await ctx.send("Please include a batch date, e.g. `!psa submission May 31`")
        return

    if email:
        await show_personal_lookup(ctx, batch_date, email)
    else:
        await show_batch(ctx, batch_date)


async def show_batch(ctx: commands.Context, batch_date: str):
    try:
        tier_status = await asyncio.to_thread(sheets_client.get_batch_tier_status, batch_date)
    except Exception as e:
        await ctx.send(f"⚠️ Couldn't reach the tracking sheet: `{e}`")
        return

    if not tier_status:
        await ctx.send(f"I couldn't find a batch matching `{batch_date}`. Try `!psa submission`.")
        return

    embed = batch_embed(batch_date, tier_status)
    embed.set_footer(
        text=embed.footer.text + " • Reply with your email if you'd like your personal card count."
    )
    await ctx.send(embed=embed)

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        reply = await bot.wait_for("message", check=check, timeout=45)
    except asyncio.TimeoutError:
        return

    if "@" in reply.content:
        await show_personal_lookup(ctx, batch_date, reply.content.strip())


async def show_personal_lookup(ctx: commands.Context, batch_date: str, email: str):
    try:
        rows = await asyncio.to_thread(sheets_client.find_submissions_for, batch_date, email)
    except Exception as e:
        await ctx.send(f"⚠️ Couldn't reach the tracking sheet: `{e}`")
        return
    await ctx.send(embed=personal_lookup_embed(batch_date, email, rows))


@psa.command(name="update")
async def psa_update(ctx: commands.Context, batch_date: str, tier: str, *, new_status: str):
    """Staff-only: !psa update "May 31" "Super Express" Assembly"""
    if not is_admin(ctx):
        await ctx.send("🚫 You need a PSA Staff/Admin role to update statuses.")
        return

    try:
        old_status = await asyncio.to_thread(
            sheets_client.update_status, batch_date, tier, new_status
        )
    except Exception as e:
        await ctx.send(f"⚠️ Couldn't write to the tracking sheet: `{e}`")
        return

    state = load_state()
    state[state_key(batch_date, tier)] = new_status
    save_state(state)

    embed = change_announcement_embed(batch_date, tier, old_status, new_status)
    await ctx.send(embed=embed)

    if config.UPDATES_CHANNEL_ID and ctx.channel.id != config.UPDATES_CHANNEL_ID:
        channel = bot.get_channel(config.UPDATES_CHANNEL_ID)
        if channel:
            await channel.send(embed=embed)


@bot.command(name="psahelp")
async def psa_help(ctx: commands.Context):
    embed = discord.Embed(
        title="PSA Submission Tracker — Commands",
        color=discord.Color.blurple(),
        description=(
            "`!psa submission` — see current batches and pick one\n"
            "`!psa submission <date>` — jump straight to a batch's status\n"
            "`!psa submission <date> <email>` — see your card count for that batch\n"
            "`!psa update <date> <tier> <status>` — staff only, updates a tier's stage\n"
        ),
    )
    await ctx.send(embed=embed)


# ---------------------------------------------------------------------------
# Background poller — auto-announces changes made directly in the sheet
# ---------------------------------------------------------------------------

@tasks.loop(seconds=config.POLL_INTERVAL_SECONDS)
async def poll_sheet_for_changes():
    if not config.UPDATES_CHANNEL_ID:
        return
    channel = bot.get_channel(config.UPDATES_CHANNEL_ID)
    if channel is None:
        return

    try:
        rows = await asyncio.to_thread(sheets_client.get_status_rows)
    except Exception:
        return  # stay quiet on transient sheet errors; next poll will retry

    state = load_state()
    changed = False

    for r in rows:
        batch_date = str(r.get("Batch Date", "")).strip()
        tier = str(r.get("Tier", "")).strip()
        status = str(r.get("Status", "")).strip()
        last_updated = str(r.get("Last Updated", "")).strip()
        if not batch_date or not tier:
            continue
 
        key = state_key(batch_date, tier)
        old_status = state.get(key)
 
        if old_status != status:
            if not first_run:
                embed = change_announcement_embed(batch_date, tier, old_status, status, last_updated)
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    print(
                        f"[poll_sheet_for_changes] Missing access to channel "
                        f"{config.UPDATES_CHANNEL_ID} — check the bot can view/send in it. "
                        "Skipping this announcement, will keep polling."
                    )
                except Exception as e:
                    print(f"[poll_sheet_for_changes] Failed to send announcement: {e}")
            state[key] = status
            changed = True
 
    if changed:
        try:
            save_state(state)
            print(f"[poll_sheet_for_changes] saved {len(state)} entries to {config.STATE_FILE}")
        except Exception as e:
            print(f"[poll_sheet_for_changes] ⚠️ FAILED to save state — this will cause repeated re-announcing next poll: {e}")
 
 


@poll_sheet_for_changes.before_loop
async def before_poll():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")
    if not poll_sheet_for_changes.is_running():
        poll_sheet_for_changes.start()


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set — check your .env file.")
    bot.run(config.DISCORD_TOKEN)
