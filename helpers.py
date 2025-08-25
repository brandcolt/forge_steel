import discord, random, json, os, re
from typing import Tuple, List

TRACKER_TAG = "[INITIATIVE TRACKER]"
JSON_RE = re.compile(r"```json\n(.*?)\n```", re.DOTALL)

ZWSP = "\u200B"

def empty_state():
    return {"entries": [], "active": 0, "round": 1, "current": None}

def render_content(state):
    data = json.dumps(state, separators=(",", ":"))
    return f"{TRACKER_TAG}\n||```json\n{data}\n```||"

async def find_or_create_tracker_message(channel: discord.TextChannel):
    # look through pinned messages for an existing tracker
    try:
        pins = await channel.pins()
    except Exception:
        pins = []
    for m in pins:
        if TRACKER_TAG in (m.content or ""):
            return m
    # create a new tracker message
    state = empty_state()
    msg = await channel.send(content=render_content(state), embed=render_embed(state))
    try:
        await msg.pin()
    except discord.Forbidden:
        pass
    return msg

async def load_state(channel: discord.TextChannel) -> Tuple[discord.Message, dict]:
    msg = await find_or_create_tracker_message(channel)
    state = extract_state_from_message(msg)
    if state["entries"]:
        state["active"] = max(0, min(state.get("active", 0), len(state["entries"]) - 1))
    else:
        state["active"] = 0
    return msg, state

async def save_state(msg: discord.Message, state: dict):
    await msg.edit(content=render_content(state), embed=render_embed(state))

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

# Kit / ability helpers
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def load_kit(name: str):
    if not name:
        return None
    path = os.path.join("kits", f"{name.strip().lower()}.json")
    return load_json(path) if os.path.exists(path) else None

def list_kit_names():
    folder = "kits"
    if not os.path.isdir(folder):
        return []
    out = []
    for fname in os.listdir(folder):
        if fname.lower().endswith(".json"):
            out.append(os.path.splitext(fname)[0])
    return sorted(out)[:25]

def list_ability_names():
    folder = "abilities"
    if not os.path.isdir(folder):
        return []
    names = []
    for fname in os.listdir(folder):
        if fname.lower().endswith(".json"):
            names.append(os.path.splitext(fname)[0])
    return sorted(names)[:25]

def load_ability(name: str):
    if not name:
        return None
    path = os.path.join("abilities", f"{name.strip().lower()}.json")
    return load_json(path) if os.path.exists(path) else None

async def list_character_names_in_channel(channel: discord.TextChannel) -> List[str]:
    _, state = await load_state(channel)
    return [e["name"] for e in state.get("entries", [])][:25]

def get_char(state, name: str):
    return next((e for e in state["entries"] if e["name"].lower() == name.lower()), None)

def parse_three_space_numbers(s: str):
    try:
        vals = [int(x) for x in str(s).split()]
        return vals[:3] + [0]*(3 - len(vals))
    except Exception:
        return [0,0,0]

# Dice evaluation
DICE_TERM_RE = re.compile(r"([+-]?)\s*(\d*)d(\d+)|([+-]?)\s*(\d+)")

def eval_dice_expr(expr: str, max_dice=200, max_sides=1000):
    expr = (expr or "").strip()
    total = 0
    details = []
    if expr and expr[0] not in "+-":
        expr = "+" + expr
    for m in DICE_TERM_RE.finditer(expr):
        sign1, count_str, sides_str, sign2, const_str = m.groups()
        if sides_str is not None:
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
        elif const_str is not None:
            sign = -1 if sign2 == "-" else 1
            const = int(const_str)
            total += sign * const
            sign_txt = "-" if sign < 0 else "+"
            details.append(f"{sign_txt}{const} → {sign*const:+d}")
    if not details:
        raise ValueError("No valid dice terms found.")
    return total, "\n".join(details)

# Rendering
def render_embed(state):
    e = discord.Embed(title=f"🧭 Draw Steel Tracker • Round {state.get('round',1)}", color=0x00AAFF)
    if not state["entries"]:
        e.description = "_Empty tracker_"
        return e

    cur = (state.get("current") or "").lower()

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

# Autocomplete helpers exported for use in cogs/bot
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

async def ac_ability(ctx: discord.AutocompleteContext):
    names = list_ability_names()
    q = (ctx.value or "").lower()
    if q:
        names = [n for n in names if q in n.lower()]
    return names[:25]