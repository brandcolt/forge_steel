# bot.py
import discord, random, json, os, re
from discord.ext import commands
from discord import option

# ───────────────────────── Setup ───────────────────────── #

INTENTS = discord.Intents.default()
bot = commands.Bot(intents=INTENTS)

TRACKER_TITLE = "🧭 Draw Steel Tracker"
TRACKER_TAG = "[INITIATIVE TRACKER]"  # marker to find the state message
JSON_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)
ZWSP = "\u200B"  # zero-width space (not required for spoiler, but harmless)

# ──────────────────────── State helpers ──────────────────────── #

# Create an empty state
def empty_state():
    # entries: list of characters (each has status: "ready" or "done")
    # current: name of the character currently taking a turn (or None)
    return {"entries": [], "active": 0, "round": 1, "current": None}

def render_content(state):
    data = json.dumps(state, separators=(",", ":"))
    # Keep a tiny visible tag so we can find the message, but hide the JSON in a spoiler
    return f"{TRACKER_TAG}\n||```json\n{data}\n```||"

async def find_or_create_tracker_message(channel: discord.TextChannel):
    pins = await channel.pins()
    for m in pins:
        if m.author == bot.user and TRACKER_TAG in (m.content or ""):
            return m
    state = empty_state()
    msg = await channel.send(content=render_content(state), embed=render_embed(state))
    try:
        await msg.pin()
    except discord.Forbidden:
        pass
    return msg

# Autocomplete helper
async def ac_character(ctx: discord.AutocompleteContext):
    names = await list_character_names_in_channel(ctx.interaction.channel)
    q = (ctx.value or "").lower()
    if q:
        names = [n for n in names if q in n.lower()]
    return names[:25]

# Extract state from a message's content
def extract_state_from_message(msg: discord.Message):
    if not msg or not msg.content:
        return empty_state()
    m = JSON_RE.search(msg.content)
    if not m:
        return empty_state()
    try:
        return json.loads(m.group(1))
    except Exception:
        return empty_state()

# ---- Kit helpers ----
def load_kit(name: str):
    if not name: return None
    path = os.path.join("kits", f"{name.strip().lower()}.json")
    return load_json(path) if os.path.exists(path) else None

def list_kit_names():
    folder = "kits"
    if not os.path.isdir(folder): return []
    out = []
    for fname in os.listdir(folder):
        if fname.lower().endswith(".json"):
            out.append(os.path.splitext(fname)[0])
    return sorted(out)[:25]

async def ac_kit(ctx: discord.AutocompleteContext):
    names = list_kit_names()
    q = (ctx.value or "").lower()
    if q:
        names = [n for n in names if q in n.lower()]
    return names[:25]

# Load state from channel (find or create message, parse JSON)
async def load_state(channel):
    msg = await find_or_create_tracker_message(channel)
    state = extract_state_from_message(msg)
    if state["entries"]:
        state["active"] = max(0, min(state["active"], len(state["entries"]) - 1))
    else:
        state["active"] = 0
    return msg, state

# Save state back to the message
async def save_state(msg: discord.Message, state):
    await msg.edit(content=render_content(state), embed=render_embed(state))

# ───────────────────────── Rendering ───────────────────────── #

# Render the embed view of the tracker state
def render_embed(state):
    e = discord.Embed(title=f"{TRACKER_TITLE} • Round {state.get('round',1)}", color=0x00AAFF)
    if not state["entries"]:
        e.description = "_Empty tracker_"
        return e

    cur = (state.get("current") or "").lower()

    # Split by status then role
    heroes_ready   = [it for it in state["entries"] if it.get("is_player", True) and it.get("status","ready") == "ready"]
    monsters_ready = [it for it in state["entries"] if not it.get("is_player", True) and it.get("status","ready") == "ready"]
    heroes_done    = [it for it in state["entries"] if it.get("is_player", True) and it.get("status","ready") == "done"]
    monsters_done  = [it for it in state["entries"] if not it.get("is_player", True) and it.get("status","ready") == "done"]

    def line(it):
        arrow = "➡️ " if it["name"].lower() == cur else "• "
        stats = f"M:{it.get('M',0)} A:{it.get('A',0)} R:{it.get('R',0)} I:{it.get('I',0)} P:{it.get('P',0)}"
        extra = f"SPD:{it.get('speed',0)} SHIFT:{it.get('shift',0)} REC:{it.get('recoveries',0)}"
        return f"{arrow}**{it['name']}** — Stamina {it.get('stamina',0)} | {stats} | {extra}"

    chunks = []

    if heroes_ready or monsters_ready:
        if heroes_ready:
            chunks.append("__**Heroes**__")
            chunks += [line(it) for it in heroes_ready]
            chunks.append("")
        if monsters_ready:
            chunks.append("__**Monsters**__")
            chunks += [line(it) for it in monsters_ready]
            chunks.append("")

    if heroes_done or monsters_done:
        chunks.append("__**Turn Over**__")
        if heroes_done:
            chunks.append("_Heroes_")
            chunks += [line(it) for it in heroes_done]
            chunks.append("")
        if monsters_done:
            chunks.append("_Monsters_")
            chunks += [line(it) for it in monsters_done]
            chunks.append("")

    e.description = "\n".join(chunks) if chunks else "_No combatants._"
    return e

# ─────────────────────── JSON + Rolls ─────────────────────── #
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_ability(name: str):
    path = os.path.join("abilities", f"{name.strip().lower()}.json")
    return load_json(path) if os.path.exists(path) else None

def list_ability_names():
    folder = "abilities"
    if not os.path.isdir(folder):
        return []
    names = []
    for fname in os.listdir(folder):
        if fname.lower().endswith(".json"):
            names.append(os.path.splitext(fname)[0])
    return sorted(names)[:25]

async def list_character_names_in_channel(channel: discord.TextChannel):
    _, state = await load_state(channel)
    return [e["name"] for e in state.get("entries", [])][:25]

def power_roll(stat_value: int, skilled: bool = False):
    d1, d2 = random.randint(1,10), random.randint(1,10)
    total = d1 + d2 + int(stat_value) + (2 if skilled else 0)
    if total <= 11:
        tier = 1
    elif total <= 16:
        tier = 2
    else:
        tier = 3
    return {"dice": (d1, d2), "total": total, "tier": tier}

def get_char(state, name: str):
    return next((e for e in state["entries"] if e["name"].lower()==name.lower()), None)

def parse_three_space_numbers(s: str):
    try:
        vals = [int(x) for x in str(s).split()]
        return vals[:3] + [0]*(3-len(vals)) if vals else [0,0,0]
    except:
        return [0,0,0]

DICE_TERM_RE = re.compile(r"([+-]?)\s*(\d*)d(\d+)|([+-]?)\s*(\d+)")

def eval_dice_expr(expr: str, max_dice=200, max_sides=1000):
    expr = expr.strip()
    total = 0
    details = []
    if expr and expr[0] not in "+-":
        expr = "+" + expr
    for m in DICE_TERM_RE.finditer(expr):
        sign1, count_str, sides_str, sign2, const_str = m.groups()
        if count_str is not None and sides_str is not None:
            sign = -1 if sign1 == "-" else 1
            count = int(count_str) if count_str else 1
            sides = int(sides_str)
            if count < 1 or count > max_dice or sides < 2 or sides > max_sides:
                raise ValueError("Dice limits exceeded.")
            rolls = [random.randint(1, sides) for _ in range(count)]
            subtotal = sum(rolls) * sign
            total += subtotal
            sign_txt = "-" if sign < 0 else "+"
            details.append(f"{sign_txt}{count}d{sides} [{', '.join(map(str, rolls))}] → {subtotal:+d}")
        else:
            sign = -1 if sign2 == "-" else 1
            const = int(const_str)
            total += sign * const
            sign_txt = "-" if sign < 0 else "+"
            details.append(f"{sign_txt}{const} → {sign*const:+d}")
    if not details:
        raise ValueError("No valid dice terms found.")
    return total, "\n".join(details)

# ───────────────────────── Cogs ───────────────────────── #
class InitCog(commands.Cog):
    def __init__(self, bot): self.bot = bot

    # ---------------- Add Character ----------------
    @discord.slash_command(description="Add a Draw Steel character to the tracker")
    @option("name", str)
    @option("stamina", int, description="Stamina")
    @option("m", int, description="Might")
    @option("a", int, description="Agility")
    @option("r", int, description="Reason")
    @option("i", int, description="Intuition")
    @option("p", int, description="Presence")
    @option("speed", int)
    @option("shift", int)
    @option("recoveries", int)
    @option("kit", str, description="Pick a kit (or leave blank to enter custom bonuses)", required=False, autocomplete=ac_kit)
    @option("kit_melee", str, description="Melee kit bonuses (e.g. '1 2 2')", required=False, default="0 0 0")
    @option("kit_ranged", str, description="Ranged kit bonuses (e.g. '1 1 1')", required=False, default="0 0 0")
    @option("is_player", bool, default=True)
    async def init_add(
        self, ctx, name: str, stamina: int, m: int, a: int, r: int, i: int, p: int,
        speed: int, shift: int, recoveries: int,
        kit: str = None, kit_melee: str = "0 0 0", kit_ranged: str = "0 0 0",
        is_player: bool = True
    ):
        msg, state = await load_state(ctx.channel)

        # Enforce: either choose a kit, or enter custom arrays — not both.
        custom_melee = (kit_melee.strip() != "0 0 0")
        custom_ranged = (kit_ranged.strip() != "0 0 0")
        using_custom = custom_melee or custom_ranged
        using_named  = bool(kit and kit.strip())

        if using_named and using_custom:
            await ctx.respond("Pick **either** a Kit **or** custom bonuses — not both. Clear the custom fields or remove the kit.", ephemeral=True)
            return

        # Resolve kit arrays
        kit_melee_arr = [0,0,0]
        kit_ranged_arr = [0,0,0]
        kit_name = None

        if using_named:
            data = load_kit(kit)
            if not data:
                await ctx.respond(f"Kit **{kit}** not found in `/kits`.", ephemeral=True)
                return
            kit_melee_arr = list(map(int, data.get("melee", [0,0,0])))[:3] + [0]*3
            kit_ranged_arr = list(map(int, data.get("ranged", [0,0,0])))[:3] + [0]*3
            kit_melee_arr = kit_melee_arr[:3]
            kit_ranged_arr = kit_ranged_arr[:3]
            kit_name = data.get("name") or kit
        else:
            kit_melee_arr = parse_three_space_numbers(kit_melee)
            kit_ranged_arr = parse_three_space_numbers(kit_ranged)

        entry = {
            "name": name,
            "stamina": int(stamina),
            "M": int(m), "A": int(a), "R": int(r), "I": int(i), "P": int(p),
            "speed": int(speed), "shift": int(shift), "recoveries": int(recoveries),
            "kit": kit_name,
            "kit_melee": kit_melee_arr,
            "kit_ranged": kit_ranged_arr,
            "is_player": bool(is_player),
            "status": "ready",
        }
        idx = next((ix for ix,e in enumerate(state["entries"]) if e["name"].lower()==name.lower()), None)
        if idx is not None:
            state["entries"][idx] = entry
        else:
            state["entries"].append(entry)

        await save_state(msg, state)
        await ctx.respond(embed=render_embed(state), ephemeral=False)

    # ---------------- Update Character Field ----------------
    @discord.slash_command(description="Update a single field on a character in the tracker")
    @option("name", str, description="Existing character name", autocomplete=ac_character)
    @option("field", str, description="Which field to update",
            choices=["name","stamina","M","A","R","I","P","speed","shift","recoveries","kit_melee","kit_ranged","is_player"])
    @option("value", str, description="New value (e.g. '27' or '1 2 2' or 'true')")  
    async def init_update(self, ctx, name: str, field: str, value: str):
        msg, state = await load_state(ctx.channel)
        idx = next((ix for ix,e in enumerate(state["entries"]) if e["name"].lower()==name.lower()), None)
        if idx is None:
            await ctx.respond(f"Character **{name}** not found.", ephemeral=True)
            return

        entry = state["entries"][idx]
        try:
            if field in ["stamina","M","A","R","I","P","speed","shift","recoveries"]:
                entry[field] = int(value)
            elif field in ["kit_melee","kit_ranged"]:
                entry[field] = parse_three_space_numbers(value)
            elif field == "is_player":
                entry[field] = str(value).strip().lower() in ["1","true","yes","y","on"]
            elif field == "name":
                new_name = value.strip()
                if not new_name:
                    await ctx.respond("Name cannot be empty.", ephemeral=True); return
                if any(e["name"].lower()==new_name.lower() for e in state["entries"] if e is not entry):
                    await ctx.respond(f"A character named **{new_name}** already exists.", ephemeral=True); return
                entry["name"] = new_name
            else:
                await ctx.respond(f"Unsupported field: `{field}`", ephemeral=True); return
        except ValueError:
            await ctx.respond(f"Could not parse `{value}` for `{field}`.", ephemeral=True); return

        state["entries"][idx] = entry
        await save_state(msg, state)
        await ctx.respond(embed=render_embed(state), ephemeral=False)

    # ---------------- Clear Tracker ----------------
    @discord.slash_command(description="Clear the tracker")
    async def init_clear(self, ctx):
        msg, state = await load_state(ctx.channel)
        state["entries"].clear()
        state["active"] = 0
        state["round"] = 1
        state["current"] = None
        await save_state(msg, state)
        await ctx.respond("Cleared.", ephemeral=True)

    # ---------------- Turn Management ----------------
    @discord.slash_command(description="Start a character's turn (sets the arrow)")
    @option("character", str, autocomplete=ac_character)
    async def init_turn(self, ctx, character: str):
        msg, state = await load_state(ctx.channel)
        entry = next((e for e in state["entries"] if e["name"].lower()==character.lower()), None)
        if not entry:
            await ctx.respond(f"Character **{character}** not found.", ephemeral=True); return
        if entry.get("status","ready") == "done":
            await ctx.respond(f"**{entry['name']}** is already in Turn Over. Use `/init_next_round` or edit their status.", ephemeral=True); return
        state["current"] = entry["name"]
        await save_state(msg, state)
        await ctx.respond(f"➡️ It is now **{entry['name']}**’s turn.", ephemeral=False)

    # ---------------- End Turn ----------------
    @discord.slash_command(description="End a character's turn (moves them to Turn Over)")
    @option("character", str, required=False, description="Defaults to the current turn", autocomplete=ac_character)
    async def init_end_turn(self, ctx, character: str = None):
        msg, state = await load_state(ctx.channel)

        # pick target: explicit OR whoever is "current"
        target_name = character or state.get("current")
        if not target_name:
            await ctx.respond("No active character. Use `/init_turn` first or specify a character.", ephemeral=True)
            return

        entry = next((e for e in state["entries"] if e["name"].lower() == target_name.lower()), None)
        if not entry:
            await ctx.respond(f"Character **{target_name}** not found.", ephemeral=True)
            return

        # mark as done
        entry["status"] = "done"

        # clear current pointer if it was pointing to this character
        cur = state.get("current")
        if cur and cur.lower() == entry["name"].lower():
            state["current"] = None

        await save_state(msg, state)
        await ctx.respond(f"✅ **{entry['name']}** moved to **Turn Over**.", ephemeral=False)

    # ---------------- Next Round ----------------
    @discord.slash_command(description="Start next round (move everyone from Turn Over back to ready)")
    async def init_next_round(self, ctx):
        msg, state = await load_state(ctx.channel)
        changed = 0
        for e in state["entries"]:
            if e.get("status","ready") == "done":
                e["status"] = "ready"
                changed += 1
        state["current"] = None
        state["round"] = int(state.get("round",1)) + 1
        await save_state(msg, state)
        await ctx.respond(f"🔁 **Round {state['round']}** begins. {changed} combatant(s) readied.", ephemeral=False)

    # ---------------- Show Tracker ----------------
    @discord.slash_command(description="Show the current initiative tracker state")
    async def init_show(self, ctx):
        msg, state = await load_state(ctx.channel)
        await ctx.respond(embed=render_embed(state), ephemeral=False)

    # ---------------- Set Status ----------------
    @discord.slash_command(description="Manually set a character's status (ready/done)")
    @option("character", str, autocomplete=ac_character)
    @option("status", str, choices=["ready","done"])
    async def init_set_status(self, ctx, character: str, status: str):
        msg, state = await load_state(ctx.channel)
        entry = next((e for e in state["entries"] if e["name"].lower()==character.lower()), None)
        if not entry:
            await ctx.respond(f"Character **{character}** not found.", ephemeral=True); return
        entry["status"] = status
        if status == "done" and state.get("current","").lower() == entry["name"].lower():
            state["current"] = None
        await save_state(msg, state)
        await ctx.respond(f"Set **{entry['name']}** to `{status}`.", ephemeral=False)

# ───────────────────────── Draw Steel Cog ───────────────────────── #

class DSCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _auto_character(self, ctx: discord.AutocompleteContext):
        names = await list_character_names_in_channel(ctx.interaction.channel)
        q = (ctx.value or "").lower()
        if q:
            names = [n for n in names if q in n.lower()]
        return names[:25]

    def _auto_ability(self, ctx: discord.AutocompleteContext):
        options = list_ability_names()
        q = (ctx.value or "").lower()
        if q:
            options = [n for n in options if q in n.lower()]
        return options[:25]

    # ---------------- Freeform roll ----------------
    @discord.slash_command(description="Freeform dice roll like '2d10+3+1d4-2'")
    @option("expr", str, description="Dice expression (e.g., 2d10+3+1d4-2)")
    async def roll(self, ctx, expr: str):
        try:
            total, breakdown = eval_dice_expr(expr)
            e = discord.Embed(title="🎲 Roll", color=0x9B59B6)
            e.add_field(name="Expression", value=expr, inline=False)
            e.add_field(name="Breakdown", value=breakdown, inline=False)
            e.add_field(name="Total", value=f"**{total}**", inline=True)
            await ctx.respond(embed=e)
        except Exception as ex:
            await ctx.respond(f"Couldn’t parse that: {ex}", ephemeral=True)

    # ---------------- Power Roll ----------------
    @discord.slash_command(description="Power Roll (2d10 + stat [+2 if Skilled] + mod). If a character is given, pulls their stat.")
    @option("stat", str, choices=["M","A","R","I","P"])
    @option("character", str, required=False, autocomplete=_auto_character)
    @option("skilled", bool, default=False)
    @option("mod", int, required=False, default=0)
    async def ds_roll(self, ctx, stat: str, character: str = None, skilled: bool = False, mod: int = 0):
        stat_value = 0
        if character:
            _, state = await load_state(ctx.channel)
            entry = get_char(state, character)
            if not entry:
                await ctx.respond(f"Character **{character}** not found.", ephemeral=True); return
            stat_value = int(entry.get(stat, 0))

        d1, d2 = random.randint(1,10), random.randint(1,10)
        total = d1 + d2 + stat_value + (2 if skilled else 0) + int(mod)

        if total <= 11: tier, color = "Tier 1 (≤11)", 0xE74C3C
        elif total <= 16: tier, color = "Tier 2 (12–16)", 0x2ECC71
        else: tier, color = "Tier 3 (17+)", 0xF1C40F

        parts = [f"{d1}", f"{d2}"]
        if stat_value: parts.append(f"{stat_value}({stat})")
        if skilled:    parts.append("2(skill)")
        if mod:        parts.append(str(mod))
        breakdown = " + ".join(parts)

        e = discord.Embed(title="🎲 Draw Steel Power Roll", color=color)
        foot = f"Stat {stat} • {'Skilled' if skilled else 'Unskilled'}"
        if character: foot = f"{character} • " + foot
        e.set_footer(text=foot)
        e.add_field(name="Roll", value=f"({breakdown}) = **{total}**", inline=False)
        e.add_field(name="Result", value=tier, inline=True)
        await ctx.respond(embed=e)

    # ---------------- Show Character ----------------
    @discord.slash_command(description="Show a character's full stats")
    @option("character", str, autocomplete=_auto_character)
    async def ds_show(self, ctx, character: str):
        _, state = await load_state(ctx.channel)
        entry = get_char(state, character)
        if not entry:
            await ctx.respond(f"Character **{character}** not found.", ephemeral=True); return

        role = "PC" if entry.get("is_player", True) else "NPC"
        melee = " ".join(map(str, entry.get("kit_melee",[0,0,0])))
        ranged = " ".join(map(str, entry.get("kit_ranged",[0,0,0])))
        kit_name = entry.get("kit")

        e = discord.Embed(title=f"📜 {entry['name']} — {role}", color=0x00AAFF)
        e.add_field(name="Stamina", value=str(entry.get("stamina",0)), inline=True)
        e.add_field(name="Speed / Shift / Rec", value=f"{entry.get('speed',0)} / {entry.get('shift',0)} / {entry.get('recoveries',0)}", inline=True)
        e.add_field(
            name="Stats",
            value=f"M {entry.get('M',0)} | A {entry.get('A',0)} | R {entry.get('R',0)} | I {entry.get('I',0)} | P {entry.get('P',0)}",
            inline=False
        )
        if kit_name:
            e.add_field(name="Kit", value=str(kit_name), inline=True)
        e.add_field(name="Kit (Melee)", value=melee or "0 0 0", inline=True)
        e.add_field(name="Kit (Ranged)", value=ranged or "0 0 0", inline=True)

        await ctx.respond(embed=e)

    # ---------------- Edit Character ----------------
    @discord.slash_command(description="Edit one field on a character")
    @option("character", str, autocomplete=_auto_character)
    @option("field", str, choices=["name","stamina","M","A","R","I","P","speed","shift","recoveries","kit_melee","kit_ranged","is_player","kit"])
    @option("value", str)
    async def ds_edit(self, ctx, character: str, field: str, value: str):
        msg, state = await load_state(ctx.channel)
        idx = next((ix for ix,e in enumerate(state["entries"]) if e["name"].lower()==character.lower()), None)
        if idx is None:
            await ctx.respond(f"Character **{character}** not found.", ephemeral=True); return

        entry = state["entries"][idx]
        try:
            if field in ["stamina","M","A","R","I","P","speed","shift","recoveries"]:
                entry[field] = int(value)
            elif field in ["kit_melee","kit_ranged"]:
                entry[field] = parse_three_space_numbers(value)
            elif field == "is_player":
                entry[field] = str(value).strip().lower() in ["1","true","yes","y","on"]
            elif field == "name":
                new_name = value.strip()
                if not new_name:
                    await ctx.respond("Name cannot be empty.", ephemeral=True); return
                if any(e["name"].lower()==new_name.lower() for e in state["entries"] if e is not entry):
                    await ctx.respond(f"A character named **{new_name}** already exists.", ephemeral=True); return
                entry["name"] = new_name
            elif field == "kit":
                if not value.strip():
                    entry["kit"] = None
                    entry["kit_melee"] = [0,0,0]
                    entry["kit_ranged"] = [0,0,0]
                else:
                    data = load_kit(value)
                    if not data:
                        await ctx.respond(f"Kit **{value}** not found in `/kits`.", ephemeral=True); return
                    entry["kit"] = data.get("name") or value
                    entry["kit_melee"] = list(map(int, data.get("melee",[0,0,0])))[:3] + [0]*3
                    entry["kit_ranged"] = list(map(int, data.get("ranged",[0,0,0])))[:3] + [0]*3
                    entry["kit_melee"] = entry["kit_melee"][:3]
                    entry["kit_ranged"] = entry["kit_ranged"][:3]
            else:
                await ctx.respond(f"Unsupported field: `{field}`", ephemeral=True); return
        except ValueError:
            await ctx.respond(f"Could not parse `{value}` for `{field}`.", ephemeral=True); return

        state["entries"][idx] = entry
        await save_state(msg, state)
        await ctx.respond(embed=render_embed(state), ephemeral=False)


    # ---------------- Use Ability (loads JSON, applies kit bonuses, edges/banes) ----------------
    @discord.slash_command(description="Use a Draw Steel ability from /abilities (applies kit bonuses)")
    @option("character", str, description="Character name in this channel's tracker",
            autocomplete=_auto_character)
    @option("ability",   str, description="Ability file name (e.g., Fade)",
            autocomplete=_auto_ability)
    @option("mode",      str, choices=["Melee","Ranged"])
    @option("stat",      str, choices=["Auto","M","A","R","I","P"], default="Auto")
    @option("edges",     int, description="0, 1 (+2), or 2 (tier ↑1)", default=0, min_value=0, max_value=2)
    @option("banes",     int, description="0, 1 (-2), or 2 (tier ↓1)", default=0, min_value=0, max_value=2)
    async def ds_use_ability(self, ctx, character: str, ability: str, mode: str,
                            stat: str = "Auto", edges: int = 0, banes: int = 0):
        # Load tracker + character
        msg, state = await load_state(ctx.channel)
        entry = get_char(state, character)
        if not entry:
            await ctx.respond(f"Character **{character}** not found in this channel’s tracker.", ephemeral=True)
            return

        # Load ability JSON
        ability_data = load_ability(ability)
        if not ability_data:
            await ctx.respond(f"Ability **{ability}** not found in `/abilities`.", ephemeral=True)
            return

        # Choose stat (Auto picks the first allowed that exists on the character)
        allowed_stats = [s.upper() for s in ability_data.get("stats", [])]
        if stat != "Auto":
            chosen_stat_key = stat.upper()
        else:
            chosen_stat_key = next((s for s in allowed_stats if s in entry),
                                allowed_stats[0] if allowed_stats else "M")
        stat_value = int(entry.get(chosen_stat_key, 0))

        # ---- Roll (edges/banes logic) ----
        # Single Edge = +2 to total. Single Bane = -2 to total.
        # Double Edge/Bane = no numeric change; adjust tier by +1/-1 afterwards.
        d1, d2 = random.randint(1, 10), random.randint(1, 10)
        base_total = d1 + d2 + stat_value

        numeric_mod = 0
        tier_adjust = 0
        if edges == 1 and banes == 0:
            numeric_mod = +2
        elif banes == 1 and edges == 0:
            numeric_mod = -2
        elif edges == 2 and banes == 0:
            tier_adjust = +1
        elif banes == 2 and edges == 0:
            tier_adjust = -1
        # If edges==1 and banes==1, they cancel (no mod, no adjust).

        total = base_total + numeric_mod

        # Determine tier from numeric total, then apply tier adjust (clamped 1–3)
        if total <= 11:
            tier = 1
        elif total <= 16:
            tier = 2
        else:
            tier = 3
        original_tier = tier
        tier = max(1, min(3, tier + tier_adjust))

        # Tier block from ability
        tkey = str(tier)
        tier_block = ability_data.get("tiers", {}).get(tkey, {})
        base_damage = int(tier_block.get("damage", 0))
        effects = tier_block.get("effects", [])

        # Kit bonuses (per character) by mode
        kit_array = entry.get("kit_melee" if mode == "Melee" else "kit_ranged", [0, 0, 0])
        kit_bonus = int(kit_array[tier - 1]) if len(kit_array) >= tier else 0

        # Final damage = base + stat + kit
        total_damage = base_damage + stat_value + kit_bonus

        # ---- Build embed ----
        color = 0xE74C3C if tier == 1 else (0x2ECC71 if tier == 2 else 0xF1C40F)
        title = ability_data.get("name", ability)
        e = discord.Embed(title=f"✨ {title}", color=color)

        # Roll line (show +/-2 only for single edge/bane, not doubles)
        parts = [f"{d1}", f"{d2}", f"{stat_value}({chosen_stat_key})"]
        if numeric_mod:  # only present for single edge/bane
            sign = "+" if numeric_mod > 0 else ""
            parts.append(f"{sign}{numeric_mod} (edge/bane)")
        roll_txt = " + ".join(parts) + f" = **{total}**"
        e.add_field(name="Roll", value=roll_txt, inline=False)

        # Tier line with arrow note for double edge/bane
        tier_note = ""
        if tier_adjust == +1 and original_tier != tier:
            tier_note = " (↑ from Double Edge)"
        elif tier_adjust == -1 and original_tier != tier:
            tier_note = " (↓ from Double Bane)"
        e.add_field(name="Tier", value=f"{tier}{tier_note}", inline=True)

        e.add_field(
            name="Damage",
            value=f"{base_damage} + {stat_value} (stat) + {kit_bonus} (kit) = **{total_damage}**",
            inline=True,
        )
        if effects:
            e.add_field(name="Effects", value="\n".join(effects), inline=False)

        extra_note = ability_data.get("extra_effect")
        if extra_note:
            e.add_field(name="Extra", value=extra_note, inline=False)

        # Small footer summary
        e.set_footer(text=f"{mode} • Stat {chosen_stat_key} • Edges {edges} • Banes {banes}")

        await ctx.respond(embed=e)

# ───────────────────────── Events ───────────────────────── #
@bot.event
async def on_ready():
    await bot.sync_commands(force=True)
    print(f"Logged in as {bot.user} (commands synced)")

def setup_bot():
    bot.add_cog(InitCog(bot))
    bot.add_cog(DSCog(bot))

if __name__ == "__main__":
    setup_bot()
    bot.run("MTQwMzE1MDExMTQ0NTM1NjY4Ng.GMg6-s.YiNXgloDYR-mBmEFjUXFqgiAtukACbgWEnrGsI")
