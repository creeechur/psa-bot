import discord

# The PSA pipeline, in order. Edit this list if PSA's stages change.
STAGE_ORDER = [
    "Order Received",
    "Scans Pending",
    "Research & ID",
    "Grading",
    "Assembly",
    "Completing",
    "Order Arrived",
]

# Emoji + colour used per stage (colour-coding requested in the spec)
STAGE_EMOJI = {
    "Order Received": "⚪",
    "Scans Pending": "⚫",
    "Research & ID": "🔴",
    "Grading": "🟡",
    "Assembly": "🟠",
    "Completing": "🟢",
    "Order Arrived": "🟣",
}

STAGE_COLOR = {
    "Order Received": discord.Color.light_grey(),
    "Scans Pending": discord.Color.dark_grey(),
    "Research & ID": discord.Color.red(),
    "Grading": discord.Color.orange(),
    "Assembly": discord.Color.yellow(),
    "Completing": discord.Color.green(),
    "Order Arrived": discord.Color.purple(),
    
}

TIER_ORDER = ["Value Bulk", "Value Max", "Standard", "Regular", "Express", "Super Express", "Walkthrough"]




def normalize_stage(stage: str) -> str:
    """Match a free-typed status string to the closest known stage name."""
    if not stage:
        return STAGE_ORDER[0]
    stage_clean = stage.strip().lower()
    for known in STAGE_ORDER:
        if known.lower() == stage_clean:
            return known
    # loose contains-match fallback (e.g. "grading" -> "Grading")
    for known in STAGE_ORDER:
        if stage_clean in known.lower() or known.lower() in stage_clean:
            return known
    return stage.strip()  # unknown stage, show as-is
 
 
def pipeline_string(current_stage: str, last_updated: str = None) -> str:
    """Builds a vertical pipeline, e.g.:
    ~~Order Received~~
    ↓
    ~~Scans Pending~~
    ↓
    🔵 **Grading**
    ↓
    Assembly
 
    If the current stage is "Order Arrived" and a last_updated date is given,
    that date is shown next to it (this is the only stage we can reliably date,
    since the sheet only stores one "Last Updated" timestamp per row — the
    date it was last set to whatever the current status is).
    """
    current_stage = normalize_stage(current_stage)
    try:
        idx = STAGE_ORDER.index(current_stage)
    except ValueError:
        return f"❓ {current_stage}"
 
    parts = []
    for i, stage in enumerate(STAGE_ORDER):
        if i < idx:
            parts.append(f"~~{stage}~~")
        elif i == idx:
            emoji = STAGE_EMOJI.get(stage, "🔵")
            label = f"{emoji} **{stage}**"
            if stage == "Order Arrived" and last_updated:
                label += f" (**{last_updated}**)"
            parts.append(label)
        else:
            parts.append(stage)
    return "\n↓\n".join(parts)
 
 
def batch_embed(batch_date: str, tier_status: dict) -> discord.Embed:
    """tier_status: {tier_name: {"status": ..., "last_updated": ...}}
    (a plain {tier_name: status_string} dict is also accepted for backward
    compatibility, just without a date shown on Order Arrived)."""
 
    def _status(v):
        return v["status"] if isinstance(v, dict) else v
 
    def _last_updated(v):
        return v.get("last_updated") if isinstance(v, dict) else None
 
    # colour the embed by the *least advanced* tier so the overall card reflects
    # the earliest stage still in progress
    stages_present = [normalize_stage(_status(v)) for v in tier_status.values() if _status(v)]
    color = discord.Color.blurple()
    if stages_present:
        earliest = min(stages_present, key=lambda s: STAGE_ORDER.index(s) if s in STAGE_ORDER else 0)
        color = STAGE_COLOR.get(earliest, discord.Color.blurple())
 
    embed = discord.Embed(
        title=f"📦 PSA Submission — {batch_date}",
        description="Current status per service tier:",
        color=color,
    )
 
    ordered_tiers = [t for t in TIER_ORDER if t in tier_status] + [
        t for t in tier_status if t not in TIER_ORDER
    ]
    for tier in ordered_tiers:
        v = tier_status[tier]
        embed.add_field(
            name=tier,
            value=pipeline_string(_status(v), _last_updated(v)),
            inline=False,
        )
 
    embed.set_footer(text="Statuses are updated manually on a weekly basis while PSA's own tracker is down.")
    return embed
 
 
def personal_lookup_embed(batch_date: str, email: str, rows: list) -> discord.Embed:
    """rows: list of dicts with keys name, tier, card_qty"""
    total_cards = sum(int(r.get("card_qty") or 0) for r in rows)
    embed = discord.Embed(
        title=f"🔎 Your PSA Submission — {batch_date}",
        color=discord.Color.blurple(),
    )
    if not rows:
        embed.description = f"No submissions found for `{email}` in the {batch_date} batch."
        return embed
 
    tiers = ", ".join(sorted({r.get("tier", "Unknown") for r in rows}))
    embed.add_field(name="Name", value=rows[0].get("name", "—"), inline=True)
    embed.add_field(name="Tier(s)", value=tiers, inline=True)
    embed.add_field(name="Total Cards Submitted", value=str(total_cards), inline=True)
    return embed
 
 
def change_announcement_embed(
    batch_date: str, tier: str, old_stage: str, new_stage: str, last_updated: str = None
) -> discord.Embed:
    emoji = STAGE_EMOJI.get(normalize_stage(new_stage), "🔵")
    embed = discord.Embed(
        title=f"{emoji} PSA Update — {batch_date}",
        description=f"**{tier}** moved from *{old_stage or 'Unknown'}* → **{new_stage}**",
        color=STAGE_COLOR.get(normalize_stage(new_stage), discord.Color.blurple()),
    )
    embed.add_field(name="Pipeline", value=pipeline_string(new_stage, last_updated), inline=False)
    return embed
 
