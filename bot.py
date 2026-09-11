import asyncio
import datetime
import json
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import sheets_client
from formatting import batch_embed, personal_lookup_embed, change_announcement_embed, TIER_ORDER, STAGE_ORDER

# Slash commands don't need to read raw message text, so no privileged
# Message Content Intent is required anymore — this sidesteps that whole
# class of setup issue for good.
intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if not isinstance(member, discord.Member):
        return False
    if member.guild_permissions.administrator:
        return True
    user_roles = {r.name for r in member.roles}
    return bool(user_roles.intersection(config.ADMIN_ROLE_NAMES))


def load_state() -> dict:
    if os.path.exists(config.STATE_FILE):
        with open(config.STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    os.makedirs(os.path.dirname(config.STATE_FILE) or ".", exist_ok=True)
    with open(config.STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def state_key(batch_date: str, tier: str) -> str:
    return f"{batch_date}::{tier}"


# ---------------------------------------------------------------------------
# UI components — replace the old "reply with a message" flow
# ---------------------------------------------------------------------------

class EmailModal(discord.ui.Modal, title="Check your submission"):
    email = discord.ui.TextInput(
        label="Email used on your submission form",
        placeholder="you@example.com",
        required=True,
    )

    def __init__(self, batch_date: str):
        super().__init__()
        self.batch_date = batch_date

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await asyncio.to_thread(
                sheets_client.find_submissions_for, self.batch_date, str(self.email)
            )
        except Exception as e:
            await interaction.followup.send(f"⚠️ Couldn't reach the tracking sheet: `{e}`", ephemeral=True)
            return
        await interaction.followup.send(
            embed=personal_lookup_embed(self.batch_date, str(self.email), rows), ephemeral=True
        )


class BatchResultView(discord.ui.View):
    """Attached to a batch status embed — lets the customer check their own
    card count without typing anything, via a modal instead of a reply."""

    def __init__(self, batch_date: str):
        super().__init__(timeout=180)
        self.batch_date = batch_date

    @discord.ui.button(label="Check my cards", style=discord.ButtonStyle.primary, emoji="🔎")
    async def check_cards(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmailModal(self.batch_date))


async def send_batch_result(send_func, batch_date: str, email: str = None):
    """Shared logic for showing a batch's pipeline, used by both the direct
    slash command path and the dropdown-selection path."""
    try:
        tier_status = await asyncio.to_thread(sheets_client.get_batch_tier_status, batch_date)
    except Exception as e:
        await send_func(f"⚠️ Couldn't reach the tracking sheet: `{e}`", ephemeral=True)
        return

    if not tier_status:
        await send_func(f"I couldn't find a batch matching `{batch_date}`.", ephemeral=True)
        return

    embed = batch_embed(batch_date, tier_status)
    view = BatchResultView(batch_date)
    await send_func(embed=embed, view=view)

    if email:
        try:
            rows = await asyncio.to_thread(sheets_client.find_submissions_for, batch_date, email)
        except Exception as e:
            await send_func(f"⚠️ Couldn't reach the tracking sheet: `{e}`", ephemeral=True)
            return
        await send_func(embed=personal_lookup_embed(batch_date, email, rows), ephemeral=True)


class BatchSelect(discord.ui.Select):
    def __init__(self, dates: list):
        # Discord caps select menus at 25 options
        options = [discord.SelectOption(label=d) for d in dates[:25]]
        super().__init__(placeholder="Choose a batch date...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        batch_date = self.values[0]
        await send_batch_result(interaction.followup.send, batch_date)


class BatchSelectView(discord.ui.View):
    def __init__(self, dates: list):
        super().__init__(timeout=60)
        self.add_item(BatchSelect(dates))


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

psa_group = app_commands.Group(name="psa", description="PSA submission tracker")


@psa_group.command(name="submission", description="Check a PSA submission batch's status")
@app_commands.describe(
    batch_date="Batch date (e.g. May 31) — leave blank to pick from a list",
    email="Your submission email, to see your personal card count",
)
async def psa_submission(interaction: discord.Interaction, batch_date: str = None, email: str = None):
    await interaction.response.defer(thinking=True)

    if batch_date is None:
        try:
            dates = await asyncio.to_thread(sheets_client.list_batch_dates)
        except Exception as e:
            await interaction.followup.send(f"⚠️ Couldn't reach the tracking sheet: `{e}`")
            return
        if not dates:
            await interaction.followup.send("No submission batches are currently on file.")
            return
        await interaction.followup.send(
            "Pick a batch to view its status:", view=BatchSelectView(dates)
        )
        return

    await send_batch_result(interaction.followup.send, batch_date, email)


@psa_submission.autocomplete("batch_date")
async def batch_date_autocomplete(interaction: discord.Interaction, current: str):
    try:
        dates = await asyncio.to_thread(sheets_client.list_batch_dates)
    except Exception:
        return []
    return [
        app_commands.Choice(name=d, value=d) for d in dates if current.lower() in d.lower()
    ][:25]


@psa_group.command(name="update", description="Staff only: update a tier's stage for a batch")
@app_commands.describe(
    batch_date="Batch date, e.g. May 31",
    tier="Service tier",
    new_status="New pipeline stage",
)
async def psa_update(interaction: discord.Interaction, batch_date: str, tier: str, new_status: str):
    if not is_admin(interaction):
        await interaction.response.send_message(
            "🚫 You need a PSA Staff/Admin role to update statuses.", ephemeral=True
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        old_status = await asyncio.to_thread(
            sheets_client.update_status, batch_date, tier, new_status
        )
    except Exception as e:
        await interaction.followup.send(f"⚠️ Couldn't write to the tracking sheet: `{e}`")
        return

    state = load_state()
    state[state_key(batch_date, tier)] = new_status
    save_state(state)

    # update_status() just wrote today's date into the Last Updated column,
    # so that's the date to show if this new status is "Order Arrived"
    today = datetime.date.today().isoformat()
    embed = change_announcement_embed(batch_date, tier, old_status, new_status, today)
    await interaction.followup.send(embed=embed)

    if config.UPDATES_CHANNEL_ID and interaction.channel_id != config.UPDATES_CHANNEL_ID:
        channel = bot.get_channel(config.UPDATES_CHANNEL_ID)
        if channel:
            try:
                await channel.send(embed=embed)
            except discord.Forbidden:
                await interaction.followup.send(
                    f"⚠️ Status updated, but I don't have access to post in the updates channel "
                    f"(ID {config.UPDATES_CHANNEL_ID}). Check its permissions.",
                    ephemeral=True,
                )
        else:
            print(f"[psa_update] Can't find updates channel ID {config.UPDATES_CHANNEL_ID}.")


@psa_update.autocomplete("batch_date")
async def update_batch_date_autocomplete(interaction: discord.Interaction, current: str):
    try:
        dates = await asyncio.to_thread(sheets_client.list_batch_dates)
    except Exception:
        return []
    return [app_commands.Choice(name=d, value=d) for d in dates if current.lower() in d.lower()][:25]


@psa_update.autocomplete("tier")
async def update_tier_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=t, value=t) for t in TIER_ORDER if current.lower() in t.lower()
    ][:25]


@psa_update.autocomplete("new_status")
async def update_status_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=s, value=s) for s in STAGE_ORDER if current.lower() in s.lower()
    ][:25]


@psa_group.command(name="help", description="Show PSA tracker commands")
async def psa_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="PSA Submission Tracker — Commands",
        color=discord.Color.blurple(),
        description=(
            "`/psa submission` — see current batches and pick one\n"
            "`/psa submission batch_date:` — jump straight to a batch's status\n"
            "`/psa submission batch_date: email:` — see your card count for that batch\n"
            "`/psa update` — staff only, updates a tier's stage\n"
        ),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(psa_group)


# ---------------------------------------------------------------------------
# Background poller — auto-announces changes made directly in the sheet
# ---------------------------------------------------------------------------

@tasks.loop(seconds=config.POLL_INTERVAL_SECONDS)
async def poll_sheet_for_changes():
    if not config.UPDATES_CHANNEL_ID:
        return
    channel = bot.get_channel(config.UPDATES_CHANNEL_ID)
    if channel is None:
        print(
            f"[poll_sheet_for_changes] Can't find channel ID {config.UPDATES_CHANNEL_ID}. "
            "Check UPDATES_CHANNEL_ID is correct and the bot is a member of that server."
        )
        return

    try:
        rows = await asyncio.to_thread(sheets_client.get_status_rows)
    except Exception:
        return  # stay quiet on transient sheet errors; next poll will retry

    state = load_state()
    first_run = not state  # nothing recorded yet -> seed quietly, don't spam
    print(f"[poll_sheet_for_changes] loaded {len(state)} saved entries from {config.STATE_FILE} (first_run={first_run})")
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


_commands_synced = False  # on_ready fires on every reconnect, not just startup —
                          # this stops the sync/clear logic from running more than once


@bot.event
async def on_ready():
    global _commands_synced
    print(f"Logged in as {bot.user} (id: {bot.user.id})")

    if not _commands_synced:
        try:
            if config.TEST_GUILD_ID:
                # Guild-scoped sync propagates instantly — best for a single-server
                # bot like this one, vs. a global sync which can take up to an hour.
                guild = discord.Object(id=config.TEST_GUILD_ID)
                bot.tree.copy_global_to(guild=guild)
                synced = await bot.tree.sync(guild=guild)
                print(f"Synced {len(synced)} slash command(s) to guild {config.TEST_GUILD_ID}")

                # If an earlier deploy ever synced globally (e.g. before
                # TEST_GUILD_ID was set), that global copy is still registered on
                # Discord's servers and will show up as a duplicate alongside the
                # guild-scoped one above. Wipe it so only one copy remains.
                # IMPORTANT: this must only ever run once — see _commands_synced
                # guard above, since clearing the local global cache and then
                # re-running copy_global_to on a later reconnect would copy
                # nothing and wipe out the guild commands too.
                bot.tree.clear_commands(guild=None)
                await bot.tree.sync()
                print("Cleared any stale globally-registered commands")
            else:
                synced = await bot.tree.sync()
                print(f"Synced {len(synced)} slash command(s) globally (may take up to an hour to appear)")
            _commands_synced = True
        except Exception as e:
            print(f"⚠️ Slash command sync failed: {e}")

    if not poll_sheet_for_changes.is_running():
        poll_sheet_for_changes.start()


if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set — check your .env file.")
    bot.run(config.DISCORD_TOKEN)
