# bot.py
import discord, random, json, os, re, configparser
from discord.ext import commands
from discord import option

# ───────────────────────── Setup ───────────────────────── #
INTENTS = discord.Intents.default()
bot = commands.Bot(intents=INTENTS)

TRACKER_TITLE = "🧭 Draw Steel Tracker"
ZWSP = "\u200B"  # zero-width space

# ──────────────────────── Helpers (from helpers.py) ──────────────────────── #
from helpers import (
    empty_state, render_content, find_or_create_tracker_message, extract_state_from_message,
    load_kit, list_kit_names, load_state, save_state, render_embed,
    load_json, load_ability, list_ability_names, list_character_names_in_channel,
    get_char, parse_three_space_numbers, eval_dice_expr
)

# Autocomplete helpers (keep these local so they don't force circular imports)
async def ac_character(ctx: discord.AutocompleteContext):
    names = await list_character_names_in_channel(ctx.interaction.channel)
    q = (ctx.value or "").lower()
    if q:
        names = [n for n in names if q in n.lower()]
    return names[:25]

async def ac_kit(ctx: discord.AutocompleteContext):
    names = list_kit_names()
    q = (ctx.value or "").lower()
    if q:
        names = [n for n in names if q in n.lower()]
    return names[:25]

# ───────────────────────── Cogs ───────────────────────── #
from cogs import InitCog, DSCog

# ───────────────────────── Events ───────────────────────── #
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (commands may still propagate)")
    tree = getattr(bot, "tree", None)
    if tree is not None:
        try:
            names = [c.name for c in tree.get_commands()]
        except Exception:
            names = []
        print("Registered application commands:", names)
    else:
        print("No command tree available on this Bot instance; skipping registered-commands listing.")

    # optional: force-sync to a dev guild for instant updates (set DEV_GUILD in config.ini)
    # try:
    #     dev_guild = int(os.environ.get("DEV_GUILD") or config.get("discord","dev_guild","fallback","0") or 0) or None
    # except Exception:
    #     dev_guild = None
    # if dev_guild:
    #     await bot.sync_commands(guild=discord.Object(id=dev_guild), force=True)
    #     print("Synced commands to dev guild", dev_guild)
    # else:
    #     await bot.sync_commands(force=True)

def setup_bot():
    bot.add_cog(InitCog(bot))
    bot.add_cog(DSCog(bot))

if __name__ == "__main__":
    setup_bot()

    # Load token from config.ini (or environment variable DISCORD_TOKEN as override)
    config = configparser.ConfigParser()
    cfg_path = os.path.join(os.path.dirname(__file__), "config.ini")
    if not os.path.exists(cfg_path):
        raise SystemExit("Missing config.ini in project root. Create c:\\Programming\\forge_steel\\config.ini with a [discord] section and token value.")

    config.read(cfg_path)
    try:
        token = os.environ.get("DISCORD_TOKEN") or config["discord"]["token"].strip()
    except Exception:
        raise SystemExit("Could not read token from config.ini. Ensure [discord] section with token key exists.")

    if not token:
        raise SystemExit("Empty token. Set DISCORD_TOKEN or put token in config.ini.")

    bot.run(token)
