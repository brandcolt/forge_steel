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

    # Heroes (ready/done) unaffected
    heroes_ready   = [it for it in state["entries"] if it.get("is_player", True) and it.get("status","ready") == "ready"]
    heroes_done    = [it for it in state["entries"] if it.get("is_player", True) and it.get("status","ready") == "done"]

    # Monsters split into groups + ungrouped
    monsters = [it for it in state["entries"] if not it.get("is_player", True)]
    # gather group order: explicit state list first, then any groups discovered
    group_order = list(dict.fromkeys(state.get("monster_groups", []) + [it.get("group") for it in monsters if it.get("group")]))

    def line(it):
        arrow = "➡️ " if it["name"].lower() == cur else "• "
        stats = f"M:{it.get('M',0)} A:{it.get('A',0)} R:{it.get('R',0)} I:{it.get('I',0)} P:{it.get('P',0)} STA:{it.get('STA',0)}"
        extra = f"SPD:{it.get('speed',0)} SHIFT:{it.get('shift',0)} REC:{it.get('recoveries',0)}"
        cur_stam = it.get('stamina', 0)
        max_stam = it.get('max_stamina', cur_stam)
        return f"{arrow}**{it['name']}** — Stamina {cur_stam}/{max_stam} | {stats} | {extra}"

    chunks = []

    # Heroes ready
    if heroes_ready:
        chunks.append("__**Heroes**__")
        chunks += [line(it) for it in heroes_ready]
        chunks.append("")

    # Monsters: render grouped ready members and ungrouped ready members
    monsters_ready_lines = []
    monsters_done_lines = []

    # process groups in group_order
    seen_group_members = set()
    for g in group_order:
        if not g:
            continue
        members = [m for m in monsters if m.get("group") == g]
        if not members:
            continue
        seen_group_members.update(m['name'] for m in members)
        ready_members = [m for m in members if m.get("status","ready") == "ready"]
        done_members  = [m for m in members if m.get("status","ready") == "done"]
        # If any ready members exist, show the group header and the ready members under Monsters
        if ready_members:
            monsters_ready_lines.append(f"__**{g} ({len(ready_members)})**__")
            monsters_ready_lines += [line(m) for m in ready_members]
            monsters_ready_lines.append("")
        # If no ready members but done_members exist -> entire group is in Turn Over; will be rendered later grouped
        # If mixed (some done, some ready) the done ones will be shown individually in Turn Over section.

    # ungrouped monsters (ready / done)
    ungrouped_ready = [m for m in monsters if not m.get("group") and m.get("status","ready") == "ready"]
    ungrouped_done  = [m for m in monsters if not m.get("group") and m.get("status","ready") == "done"]

    if monsters_ready_lines or ungrouped_ready:
        chunks.append("__**Monsters**__")
        if monsters_ready_lines:
            chunks += monsters_ready_lines
        if ungrouped_ready:
            chunks += [line(m) for m in ungrouped_ready]
            chunks.append("")
        # ensure a blank line after Monsters section
        chunks.append("")

    # Turn Over: heroes done + grouped done + ungrouped done + any individually-done members from mixed groups
    if heroes_done or any(True for g in group_order if (
            # group is "fully done" -> include as grouped
            [m for m in monsters if m.get("group")==g and m.get("status","ready")=="done"] and
            not [m for m in monsters if m.get("group")==g and m.get("status","ready")=="ready"]
        )) or ungrouped_done:
        chunks.append("__**Turn Over**__")

        # heroes done
        if heroes_done:
            chunks.append("_Heroes_")
            chunks += [line(it) for it in heroes_done]
            chunks.append("")

        # fully-done groups (show as grouped)
        for g in group_order:
            if not g:
                continue
            members = [m for m in monsters if m.get("group")==g]
            if not members:
                continue
            ready_members = [m for m in members if m.get("status","ready") == "ready"]
            done_members  = [m for m in members if m.get("status","ready") == "done"]
            if done_members and not ready_members:
                chunks.append(f"__**{g} ({len(done_members)})**__")
                chunks += [line(m) for m in done_members]
                chunks.append("")

        # individually done monsters from mixed groups: show under Turn Over but not grouped
        mixed_done = []
        for g in group_order:
            members = [m for m in monsters if m.get("group")==g]
            if not members:
                continue
            ready_members = [m for m in members if m.get("status","ready") == "ready"]
            done_members = [m for m in members if m.get("status","ready") == "done"]
            if ready_members and done_members:
                mixed_done += done_members
        if mixed_done:
            chunks += [line(m) for m in mixed_done]
            chunks.append("")

        # ungrouped done monsters
        if ungrouped_done:
            chunks.append("_Monsters_")
            chunks += [line(m) for m in ungrouped_done]
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

async def ac_group(ctx: discord.AutocompleteContext):
    # list groups present in this channel's tracker + any registered names
    try:
        _, state = await load_state(ctx.interaction.channel)
    except Exception:
        return []
    groups = list(dict.fromkeys(state.get("monster_groups", []) + [e.get("group") for e in state.get("entries", []) if e.get("group")]))
    q = (ctx.value or "").lower()
    if q:
        groups = [g for g in groups if g and q in g.lower()]
    return [g for g in (groups or [])][:25]