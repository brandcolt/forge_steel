import discord, random
from discord.ext import commands
from discord import option

# Import helpers from bot (bot.py defines these before importing this module)
from helpers import (
    load_state, save_state, render_embed,
    ac_kit, ac_character, ac_group, list_character_names_in_channel,
    list_ability_names, load_ability, load_kit,
    get_char, parse_three_space_numbers, eval_dice_expr
)

class InitCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ---------------- Add Character ----------------
    @discord.slash_command(description="Add a Draw Steel character to the tracker")
    @option("name", str)
    @option("stamina", int, description="Stamina")
    @option("stability", int, description="Stability (STA)")
    @option("m", int, description="Might")
    @option("a", int, description="Agility")
    @option("r", int, description="Reason")
    @option("i", int, description="Intuition")
    @option("p", int, description="Presence")
    @option("speed", int)
    @option("shift", int)
    @option("recoveries", int, description="Maximum recoveries")
    @option("kit", str, description="Pick a kit (or leave blank to enter custom bonuses)", required=False, autocomplete=ac_kit)
    @option("kit_melee", str, description="Melee kit bonuses (e.g. '1 2 2')", required=False, default="0 0 0")
    @option("kit_ranged", str, description="Ranged kit bonuses (e.g. '1 1 1')", required=False, default="0 0 0")
    @option("is_player", bool, default=True)
    @option("group", str, required=False, description="Monster initiative group (enemies only)", autocomplete=ac_group)
    @option("su", int, description="Surges", default=0)
    @option("hr", int, description="Heroic Resources", default=0)
    async def init_add(
        self, ctx, name: str, stamina: int, stability: int, 
                  m: int, a: int, r: int, i: int, p: int,
                  speed: int, shift: int, recoveries: int,
                  kit: str = None, kit_melee: str = "0 0 0", kit_ranged: str = "0 0 0",
                  is_player: bool = True, group: str = None, su: int = 0, hr: int = 0
    ):
        await ctx.defer()
        try:
            msg, state = await load_state(ctx.channel)

            # enforce groups for monsters only
            if group and is_player:
                await ctx.interaction.followup.send(
                    "Groups are for monsters only — set `is_player` to false to assign a group.", ephemeral=True
                )
                return

            # Resolve kit arrays
            kit_melee_arr = [0,0,0]
            kit_ranged_arr = [0,0,0]
            kit_name = None

            if group and group.strip():
                group = group.strip()
                state.setdefault("monster_groups", [])
                if group not in state["monster_groups"]:
                    state["monster_groups"].append(group)

            if kit and kit.strip():
                data = load_kit(kit)
                if not data:
                    await ctx.interaction.followup.send(f"Kit **{kit}** not found in `/kits`.", ephemeral=True)
                    return
                kit_melee_arr  = list(map(int, data.get("melee",  [0,0,0])))[:3]
                kit_ranged_arr = list(map(int, data.get("ranged", [0,0,0])))[:3]
                kit_name = data.get("name") or kit
            else:
                kit_melee_arr = parse_three_space_numbers(kit_melee)
                kit_ranged_arr = parse_three_space_numbers(kit_ranged)

            entry = {
                "name": name,
                "stamina": int(stamina),
                "max_stamina": int(stamina),
                "STA": int(stability),
                "M": int(m), "A": int(a), "R": int(r), "I": int(i), "P": int(p),
                "speed": int(speed), 
                "shift": int(shift),
                "recoveries": int(recoveries),     # Current recoveries starts at max
                "max_recoveries": int(recoveries), # Max recoveries from parameter
                "kit": kit_name,
                "kit_melee": kit_melee_arr,
                "kit_ranged": kit_ranged_arr,
                "is_player": bool(is_player),
                "status": "ready",
                "group": group or None,
                "Su": su,   # Initialize Surge to parameter
                "HR": hr,   # Initialize Heroic Resource to parameter
            }

            # ensure group is registered
            if group:
                state.setdefault("monster_groups", [])
                if group not in state["monster_groups"]:
                    state["monster_groups"].append(group)

            # prevent dup names
            if any(e["name"].lower() == entry["name"].lower() for e in state["entries"]):
                await ctx.interaction.followup.send(f"A character named **{entry['name']}** already exists.", ephemeral=True)
                return

            state["entries"].append(entry)
            await save_state(msg, state)
            await ctx.interaction.followup.send(embed=render_embed(state))
        except Exception as ex:
            await ctx.interaction.followup.send(f"Init add failed: `{ex}`", ephemeral=True)
            raise


    # ---------------- Update Character Field ----------------
    @discord.slash_command(description="Update a single field on a character in the tracker")
    @option("name", str, description="Existing character name", autocomplete=ac_character)
    @option("field", str, description="Which field to update",
            choices=["name","stamina","max_stamina","group","STA","M","A","R","I","P",
                    "speed","shift","recoveries","kit_melee","kit_ranged","is_player",
                    "Su","HR"])
    @option("value", str, description="New value (e.g. '27' or '1 2 2' or 'true')")  
    async def init_update(self, ctx, name: str, field: str, value: str):
        msg, state = await load_state(ctx.channel)
        idx = next((ix for ix,e in enumerate(state["entries"]) if e["name"].lower()==name.lower()), None)
        if idx is None:
            await ctx.respond(f"Character **{name}** not found.", ephemeral=True)
            return

        entry = state["entries"][idx]
        old_value = entry.get(field, "0")  # Store old value for comparison
        try:
            if field in ["stamina","max_stamina","group","STA","M","A","R","I","P","speed","shift","recoveries"]:
                if field == "stamina":
                    entry["stamina"] = int(value)
                    if "max_stamina" in entry:
                        entry["stamina"] = max(0, min(entry["stamina"], int(entry["max_stamina"])))
                elif field == "max_stamina":
                    new_max = int(value)
                    entry["max_stamina"] = new_max
                    entry["stamina"] = max(0, min(int(entry.get("stamina", new_max)), new_max))
                elif field == "group":
                    new_group = value.strip() or None
                    if entry.get("is_player", True) and new_group:
                        await ctx.respond("Cannot assign a group to a player.", ephemeral=True)
                        return
                    entry["group"] = new_group
                    if new_group:
                        state.setdefault("monster_groups", [])
                        if new_group not in state["monster_groups"]:
                            state["monster_groups"].append(new_group)
                else:
                    entry[field] = int(value)
            elif field in ["kit_melee","kit_ranged"]:
                old_value = " ".join(map(str, entry.get(field, [0,0,0])))  # Format old array
                entry[field] = parse_three_space_numbers(value)
                value = " ".join(map(str, entry[field]))  # Format new array
            elif field == "is_player":
                old_value = str(entry.get(field, True)).lower()
                entry[field] = str(value).strip().lower() in ["1","true","yes","y","on"]
                value = str(entry[field]).lower()
            elif field == "name":
                new_name = value.strip()
                if not new_name:
                    await ctx.respond("Name cannot be empty.", ephemeral=True)
                    return
                if any(e["name"].lower()==new_name.lower() for e in state["entries"] if e is not entry):
                    await ctx.respond(f"A character named **{new_name}** already exists.", ephemeral=True)
                    return
                entry["name"] = new_name
            elif field in ["Su", "HR"]:
                try:
                    val = int(value)
                    if val < 0:
                        await ctx.respond(f"Value for {field} cannot be negative", ephemeral=True)
                        return
                    entry[field] = val
                except ValueError:
                    await ctx.respond(f"Invalid value for {field}. Must be a number.", ephemeral=True)
                    return
            else:
                await ctx.respond(f"Unsupported field: `{field}`", ephemeral=True)
                return
        except ValueError:
            await ctx.respond(f"Could not parse `{value}` for `{field}`.", ephemeral=True)
            return

        state["entries"][idx] = entry
        await save_state(msg, state)
        
        # Create an embed to show the change
        e = discord.Embed(title="✏️ Character Updated", color=0x3498DB)
        e.add_field(name="Character", value=entry["name"], inline=True)
        e.add_field(name="Field", value=field, inline=True)
        e.add_field(name="Change", value=f"`{old_value}` → `{value}`", inline=True)
        
        await ctx.respond(embed=e)

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

        # notify and then show the updated tracker (uses followup so both messages are allowed)
        await ctx.respond(f"🔁 **Round {state['round']}** begins. {changed} combatant(s) readied.", ephemeral=False)
        await ctx.interaction.followup.send(embed=render_embed(state))


    # ---------------- Set Round ----------------
    @discord.slash_command(description="Set the current round number (e.g., 1)")
    @option("round_number", int, min_value=1)
    @option("ready_all", bool, required=False, default=False,
            description="If true, move everyone to Ready")
    async def init_set_round(self, ctx, round_number: int, ready_all: bool = False):
        msg, state = await load_state(ctx.channel)
        state["round"] = int(round_number)
        if ready_all:
            for e in state.get("entries", []):
                e["status"] = "ready"
        state["current"] = None
        await save_state(msg, state)
        await ctx.respond(
            f"⏱️ Round set to **{state['round']}**" + (" and all combatants readied." if ready_all else "."),
            ephemeral=False
        )
        await ctx.interaction.followup.send(embed=render_embed(state))

    # Resets round to 1, optionally readying everyone
    @discord.slash_command(description="Reset the round counter to 1 (optionally ready everyone)")
    @option("ready_all", bool, required=False, default=False)
    async def init_reset_round(self, ctx, ready_all: bool = False):
        await self.init_set_round.callback(self, ctx, 1, ready_all)  # reuse logic above

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
        if status == "done" and (state.get("current") or "").lower() == entry["name"].lower():
            state["current"] = None
        await save_state(msg, state)
        await ctx.respond(f"Set **{entry['name']}** to `{status}`.", ephemeral=False)


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

        cur_stam = entry.get("stamina", 0)
        max_stam = entry.get("max_stamina", cur_stam)
        stab = entry.get("STA", 0)

        e = discord.Embed(title=f"📜 {entry['name']} — {role}", color=0x00AAFF)
        e.add_field(name="Stamina", value=f"{cur_stam}/{max_stam}", inline=True)
        e.add_field(name="Stability (STA)", value=str(stab), inline=True)
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
    @option("field", str, choices=["name","stamina","max_stamina","M","A","R","I","P","speed","shift","recoveries","kit_melee","kit_ranged","is_player","kit","Su","HR"])
    @option("value", str)
    async def ds_edit(self, ctx, character: str, field: str, value: str):
        msg, state = await load_state(ctx.channel)
        idx = next((ix for ix,e in enumerate(state["entries"]) if e["name"].lower()==character.lower()), None)
        if idx is None:
            await ctx.respond(f"Character **{character}** not found.", ephemeral=True); return

        entry = state["entries"][idx]
        try:
            if field in ["stamina","max_stamina","M","A","R","I","P","speed","shift","recoveries"]:
                if field == "stamina":
                    # update current only
                    entry["stamina"] = int(value)
                    if "max_stamina" in entry:
                        entry["stamina"] = max(0, min(entry["stamina"], int(entry["max_stamina"])))
                elif field == "max_stamina":
                    new_max = int(value)
                    entry["max_stamina"] = new_max
                    entry["stamina"] = max(0, min(int(entry.get("stamina", new_max)), new_max))
                else:
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
            # Update the value handling section to support the new fields:
            elif field in ["Su", "HR"]:
                try:
                    val = int(value)
                    if val < 0:
                        await ctx.respond(f"Value for {field} cannot be negative", ephemeral=True)
                        return
                    entry[field] = val
                except ValueError:
                    await ctx.respond(f"Invalid value for {field}. Must be a number.", ephemeral=True)
                    return
            else:
                await ctx.respond(f"Unsupported field: `{field}`", ephemeral=True); return
        except ValueError:
            await ctx.respond(f"Could not parse `{value}` for `{field}`.", ephemeral=True); return

        state["entries"][idx] = entry
        await save_state(msg, state)
        await ctx.respond(embed=render_embed(state), ephemeral=False)

    # ---------------- Damage command ----------------
    @discord.slash_command(description="Deal damage to a character in the tracker")
    @option("target", str, autocomplete=_auto_character)
    @option("amount", int, description="Damage to apply (positive integer)")
    async def ds_damage(self, ctx, target: str, amount: int):
        if amount < 0:
            await ctx.respond("Amount must be a positive integer.", ephemeral=True)
            return

        msg, state = await load_state(ctx.channel)
        target_entry = get_char(state, target)
        if not target_entry:
            await ctx.respond(f"Target **{target}** not found in this channel’s tracker.", ephemeral=True)
            return

        prev = int(target_entry.get("stamina", 0))
        new = max(0, prev - int(amount))
        target_entry["stamina"] = new
        # ensure max exists
        if "max_stamina" not in target_entry:
            target_entry["max_stamina"] = prev

        await save_state(msg, state)

        e = discord.Embed(title="⚔️ Damage Applied", color=0xE74C3C)
        e.add_field(name="Target", value=f"**{target_entry['name']}**", inline=True)
        e.add_field(name="Damage", value=str(amount), inline=True)
        e.add_field(name="Stamina", value=f"{new}/{target_entry.get('max_stamina', new)}", inline=False)
        await ctx.respond(embed=e)
        
        # Displays updated tracker
        #await ctx.interaction.followup.send(embed=render_embed(state)) # Commented out to reduce spam, as /ds_damage is often used in combat

    # ---------------- Heal command ----------------
    @discord.slash_command(description="Heal a character in the tracker (cannot exceed max_stamina)")
    @option("target", str, autocomplete=_auto_character)
    @option("amount", int, description="Healing amount (positive integer)")
    async def ds_heal(self, ctx, target: str, amount: int):
        
        # Handle if healing amount is negative
        if amount < 0:
            await ctx.respond("Amount must be a positive integer.", ephemeral=True)
            return

        # Load state and find target
        msg, state = await load_state(ctx.channel)
        target_entry = get_char(state, target)
        if not target_entry:
            await ctx.respond(f"Target **{target}** not found in this channel’s tracker.", ephemeral=True)
            return

        cur = int(target_entry.get("stamina", 0))
        max_stam = int(target_entry.get("max_stamina", cur))
        new = min(max_stam, cur + int(amount))
        target_entry["stamina"] = new
        if "max_stamina" not in target_entry:
            target_entry["max_stamina"] = max_stam

        await save_state(msg, state)

        # Repastes the tracker to show updated stamina
        e = discord.Embed(title="🩹 Healing Applied", color=0x2ECC71)
        e.add_field(name="Target", value=f"**{target_entry['name']}**", inline=True)
        e.add_field(name="Healed", value=str(amount), inline=True)
        e.add_field(name="Stamina", value=f"{new}/{target_entry.get('max_stamina', new)}", inline=False)
        await ctx.respond(embed=e)
        
        # Displays updated tracker
        #await ctx.interaction.followup.send(embed=render_embed(state)) # Commented out to reduce spam, as /ds_heal is often used in combat

    # ---------------- Use Ability (loads JSON, applies kit bonuses, edges/banes) ----------------
    @discord.slash_command(description="Use a Draw Steel ability from /abilities (applies kit bonuses)")
    @option("character", str, description="Character name in this channel's tracker", autocomplete=_auto_character)
    @option("ability",   str, description="Ability file name (e.g., Fade)", autocomplete=_auto_ability)
    @option("mode",      str, choices=["Melee","Ranged"])
    @option("stat",      str, choices=["Auto","M","A","R","I","P"], default="Auto")
    @option("edges",     int, description="0, 1 (+2), or 2 (tier ↑1)", default=0, min_value=0, max_value=2)
    @option("banes",     int, description="0, 1 (-2), or 2 (tier ↓1)", default=0, min_value=0, max_value=2)
    @option("surges",    int, description="Number of surges to use (adds stat bonus damage per surge)", default=0, min_value=0)
    @option("target",    str, required=False, description="Target character to apply damage to", autocomplete=_auto_character)
    async def ds_use_ability(self, ctx, character: str, ability: str, mode: str,
                             stat: str = "Auto", edges: int = 0, banes: int = 0, surges: int = 0, target: str = None):
        # load tracker & character
        msg, state = await load_state(ctx.channel)
        entry = get_char(state, character)
        if not entry:
            await ctx.respond(f"Character **{character}** not found in this channel's tracker.", ephemeral=True)
            return

        # Check surge availability
        if surges > 0:
            current_surges = int(entry.get("Su", 0))
            if surges > current_surges:
                await ctx.respond(f"You only have {current_surges} surge(s) to use but you selected {surges}.", ephemeral=True)
                return

        ability_data = load_ability(ability)
        if not ability_data:
            await ctx.respond(f"Ability **{ability}** not found in `/abilities`.", ephemeral=True)
            return

        # top-level metadata
        tags = ability_data.get("tags", [])
        range_info = ability_data.get("range")
        action_text = ability_data.get("action")
        ability_target = ability_data.get("target")
        allowed_stats = [s.upper() for s in ability_data.get("stats", [])]

        # determine stat to use
        if stat != "Auto":
            chosen_stat_key = stat.upper()
        else:
            # prefer ability's allowed stats if present, otherwise pick character's highest stat
            candidates = ["M", "A", "R", "I", "P"]
            if allowed_stats:
                # limit candidates to allowed_stats intersection (preserve order of candidates)
                candidates = [c for c in candidates if c in allowed_stats]
                if not candidates:
                    candidates = allowed_stats
            # pick highest stat value from entry
            chosen_stat_key = max(candidates, key=lambda k: int(entry.get(k, 0)))

        stat_value = int(entry.get(chosen_stat_key, 0) or 0)

        # roll
        d1, d2 = random.randint(1, 10), random.randint(1, 10)
        base_total = d1 + d2 + stat_value

        # edges/banes handling
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

        total = base_total + numeric_mod

        # determine base tier and apply tier_adjust
        if total <= 11:
            tier = 1
        elif total <= 16:
            tier = 2
        else:
            tier = 3
        original_tier = tier
        tier = max(1, min(3, tier + tier_adjust))
        tkey = str(tier)

        tier_block = ability_data.get("tiers", {}).get(tkey, {})
        base_damage = int(tier_block.get("damage", 0))
        effects = tier_block.get("effects", [])
        rider = tier_block.get("rider") or tier_block.get("rider_text") or None

        # Calculate surge bonus (highest stat × number of surges)
        surge_bonus = 0
        if surges > 0:
            highest_stat = max(
                int(entry.get("M", 0) or 0),
                int(entry.get("A", 0) or 0),
                int(entry.get("R", 0) or 0),
                int(entry.get("I", 0) or 0),
                int(entry.get("P", 0) or 0)
            )
            surge_bonus = highest_stat * surges

        # Only add stat and kit bonus if base damage is greater than 0
        total_damage = base_damage
        kit_bonus = 0
        if base_damage > 0:
            # kit bonus
            kit_array = entry.get("kit_melee" if mode == "Melee" else "kit_ranged", [0, 0, 0])
            kit_bonus = int(kit_array[tier - 1]) if len(kit_array) >= tier else 0
            total_damage = base_damage + stat_value + kit_bonus + surge_bonus

        # Setup the tracker embed to render
        color = 0xE74C3C if tier == 1 else (0x2ECC71 if tier == 2 else 0xF1C40F)
        title = ability_data.get("name", ability)
        e = discord.Embed(title=f"✨ {title}", color=color)

        if tags:
            e.add_field(name="Tags", value=", ".join(map(str, tags)), inline=True)
        if range_info:
            if isinstance(range_info, dict):
                range_parts = [f"{k}: {v}" for k, v in range_info.items()]
                e.add_field(name="Range", value="; ".join(range_parts), inline=True)
            else:
                e.add_field(name="Range", value=str(range_info), inline=True)
        if action_text:
            e.add_field(name="Action", value=str(action_text), inline=True)
        if ability_target:
            e.add_field(name="Ability Target", value=str(ability_target), inline=True)
        if allowed_stats:
            e.add_field(name="Allowed Stats", value=", ".join(allowed_stats), inline=False)

        # roll breakdown
        parts = [f"{d1}", f"{d2}", f"{stat_value}({chosen_stat_key})"]
        if numeric_mod:
            sign = "+" if numeric_mod > 0 else ""
            parts.append(f"{sign}{numeric_mod} (edge/bane)")
        roll_txt = " + ".join(parts) + f" = **{total}**"
        e.add_field(name="Roll", value=roll_txt, inline=False)

        tier_note = ""
        if tier_adjust == +1 and original_tier != tier:
            tier_note = " (↑ from Double Edge)"
        elif tier_adjust == -1 and original_tier != tier:
            tier_note = " (↓ from Double Bane)"
        e.add_field(name="Tier", value=f"{tier}{tier_note}", inline=True)

        e.add_field(
            name="Damage",
            value=(f"{base_damage} + {stat_value} (stat) + {kit_bonus} (kit)" + 
                   (f" + {surge_bonus} (surges)" if surge_bonus > 0 else "") +
                   f" = **{total_damage}**" if base_damage > 0
                  else f"**{total_damage}**" if base_damage == 0 else f"**{base_damage}**"),
            inline=True,
        )

        # Add effects if present
        if effects:
            e.add_field(name="Effects", value="\n".join(f"• {eff}" for eff in effects), inline=False)
        
        # Add rider if present
        if rider:
            e.add_field(name="Rider", value=str(rider), inline=False)

        e.set_footer(text=f"{mode} • Stat {chosen_stat_key} • Edges {edges} • Banes {banes}" + 
                         (f" • Surges {surges}" if surges > 0 else ""))

        # apply to target if provided
        if target:
            target_entry = get_char(state, target)
            if not target_entry:
                await ctx.respond(f"Target **{target}** not found in this channel's tracker.", ephemeral=True)
                return
            prev = int(target_entry.get("stamina", 0))
            new = max(0, prev - int(total_damage))
            target_entry["stamina"] = new
            if "max_stamina" not in target_entry:
                target_entry["max_stamina"] = prev
            
            # Deduct surges from attacker
            if surges > 0:
                entry["Su"] = int(entry.get("Su", 0)) - surges
            
            await save_state(msg, state)
            e.add_field(name="Target", value=f"**{target_entry['name']}** took **{total_damage}** damage — Stamina {new}/{target_entry.get('max_stamina', new)}", inline=False)
            await ctx.respond(embed=e)
            #await ctx.interaction.followup.send(embed=render_embed(state))
            return

        await ctx.respond(embed=e)

    # ---------------- Remove Character ----------------
    @discord.slash_command(description="Remove a character from the tracker")
    @option("character", str, autocomplete=_auto_character)
    async def ds_remove(self, ctx, character: str):
        msg, state = await load_state(ctx.channel)
        idx = next((ix for ix,e in enumerate(state["entries"]) if e["name"].lower() == character.lower()), None)
        if idx is None:
            await ctx.respond(f"Character **{character}** not found.", ephemeral=True)
            return

        removed = state["entries"].pop(idx)
        # If active index pointed past end, clamp it
        if state.get("active", 0) >= len(state["entries"]):
            state["active"] = max(0, len(state["entries"]) - 1)
        await save_state(msg, state)

        e = discord.Embed(title="🗑️ Removed", color=0xE74C3C)
        e.add_field(name="Removed", value=f"**{removed['name']}**", inline=True)
        e.add_field(name="Remaining", value=f"{len(state['entries'])} combatant(s)", inline=True)
        await ctx.respond(embed=e)
        # show updated tracker as followup
        #await ctx.interaction.followup.send(embed=render_embed(state)) # Commented out to reduce spam, as /ds_remove is often used in combat

    # ---------------- Add Effect ----------------
    @discord.slash_command(description="Add an effect to a character (shows in tracker)")
    @option("target", str, description="Character to apply effect to", autocomplete=_auto_character)
    @option("effect", str, description="Effect description (e.g., 'Stunned until round 3')")
    async def add_effect(self, ctx, target: str, effect: str):
        msg, state = await load_state(ctx.channel)
        target_entry = get_char(state, target)
        
        if not target_entry:
            await ctx.respond(f"Target **{target}** not found in this channel's tracker.", ephemeral=True)
            return
            
        # Initialize effects list if needed
        if 'effects' not in target_entry:
            target_entry['effects'] = []
            
        # Add the new effect
        target_entry['effects'].append(effect)
        
        # Save state and respond
        await save_state(msg, state)
        
        e = discord.Embed(title="✨ Effect Added", color=0x9B59B6)
        e.add_field(name="Target", value=f"**{target_entry['name']}**", inline=True)
        e.add_field(name="Effect", value=effect, inline=True)
        await ctx.respond(embed=e)
        await ctx.interaction.followup.send(embed=render_embed(state))

    # ---------------- Remove Effect ----------------
    @discord.slash_command(description="Remove an effect from a character")
    @option("target", str, description="Character to remove effect from", autocomplete=_auto_character)
    @option("effect_index", int, description="Effect number to remove (1 = first effect)", min_value=1)
    async def remove_effect(self, ctx, target: str, effect_index: int):
        msg, state = await load_state(ctx.channel)
        target_entry = get_char(state, target)
        
        if not target_entry:
            await ctx.respond(f"Target **{target}** not found in this channel's tracker.", ephemeral=True)
            return
            
        effects = target_entry.get('effects', [])
        if not effects:
            await ctx.respond(f"**{target}** has no effects to remove.", ephemeral=True)
            return
            
        try:
            # Convert to 0-based index
            idx = effect_index - 1
            removed = effects.pop(idx)
            
            # If no effects left, remove the key entirely
            if not effects:
                target_entry.pop('effects', None)
            
            await save_state(msg, state)
            
            e = discord.Embed(title="🗑️ Effect Removed", color=0xE74C3C)
            e.add_field(name="Target", value=f"**{target_entry['name']}**", inline=True)
            e.add_field(name="Removed", value=removed, inline=True)
            await ctx.respond(embed=e)
            await ctx.interaction.followup.send(embed=render_embed(state))
            
        except IndexError:
            await ctx.respond(f"Effect #{effect_index} not found. Character has {len(effects)} effect(s).", ephemeral=True)

    # ---------------- Use or Restore Recoveries ----------------
    @discord.slash_command(description="Use or restore recoveries for a character")
    @option("character", str, autocomplete=_auto_character)
    @option("amount", int, description="Amount to change (negative to use, positive to restore)")
    async def ds_recoveries(self, ctx, character: str, amount: int):
        msg, state = await load_state(ctx.channel)
        entry = get_char(state, character)

        if not entry:
            await ctx.respond(f"Character **{character}** not found.", ephemeral=True)
            return

        current = int(entry.get("recoveries", 0))
        maximum = int(entry.get("max_recoveries", current))
        new_value = max(0, min(maximum, current + amount))
        entry["recoveries"] = new_value

        # ensure max_recoveries exists
        if "max_recoveries" not in entry:
            entry["max_recoveries"] = maximum

        # Compute actual recoveries used (if any)
        used_count = max(0, current - new_value)  # number of recoveries actually used
        healed_amount = 0
        if used_count > 0:
            # Each recovery heals floor(max_stamina / 3)
            max_stam = int(entry.get("max_stamina", entry.get("stamina", 0)))
            per_recovery = max_stam // 3
            if per_recovery > 0:
                prev_stam = int(entry.get("stamina", 0))
                healed_amount_total = per_recovery * used_count
                new_stam = min(max_stam, prev_stam + healed_amount_total)
                entry["stamina"] = new_stam
                healed_amount = new_stam - prev_stam  # actual healed, which may be smaller than healed_amount_total if capped by max

        await save_state(msg, state)

        # Compute delta (positive => restored recs, negative => used recs)
        delta = new_value - current
        if delta > 0:
            action, color = "restored", 0x2ECC71
        elif delta < 0:
            action, color = "used", 0xE74C3C
        else:
            action, color = "unchanged", 0x95A5A6

        e = discord.Embed(title="🔄 Recoveries Updated", color=color)
        e.add_field(name="Character", value=entry["name"], inline=True)
        e.add_field(name=f"Recoveries {action}", value=str(abs(delta)), inline=True)
        e.add_field(name="Recoveries (Now)", value=f"{new_value}/{maximum}", inline=True)

        if healed_amount > 0:
            max_stam = int(entry.get("max_stamina", entry.get("stamina", 0)))
            e.add_field(name="Healed", value=f"{healed_amount} • Stamina {entry['stamina']}/{max_stam}", inline=False)

        await ctx.respond(embed=e)
        await ctx.interaction.followup.send(embed=render_embed(state))