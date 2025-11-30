import re, json, os, sys, urllib.parse, urllib.request
from pathlib import Path

# --- CONFIG -------------------------------------------------------
REPO_ROOT = "https://github.com/SteelCompendium/data-md/tree/main/Bestiary"
OUT_DIR   = "abilities_converted"
# -----------------------------------------------------------------

def fetch(url: str) -> str:
    with urllib.request.urlopen(url) as r:
        return r.read().decode("utf-8", errors="replace")

def esc_angles(s: str) -> str:
    return s.replace("<", "\\<").replace(">", "\\>") if s else s

# ------------------------------- PARSER -------------------------------
def parse_markdown(md: str, fallback_name: str):
    lines = [l.rstrip() for l in md.splitlines()]

    # ---------- YAML frontmatter ----------
    front = {}
    if lines and lines[0].strip() == '---':
        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                end_idx = i
                break
        if end_idx is not None:
            i = 1
            while i < end_idx:
                line = lines[i]
                m = re.match(r'^\s*([^:]+)\s*:\s*(.*)$', line)
                if m:
                    key = m.group(1).strip()
                    val = m.group(2).strip()
                    if val == "":
                        items = []
                        j = i + 1
                        while j < end_idx:
                            m_item = re.match(r'^\s*-\s*(.+)$', lines[j])
                            if not m_item:
                                break
                            items.append(m_item.group(1).strip().strip("'\""))
                            j += 1
                        front[key] = items
                        i = j
                        continue
                    else:
                        front[key] = val.strip().strip("'\"")
                i += 1
            lines = lines[end_idx+1:]

    def _unquote(s):
        if s is None: return None
        s = s.strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1].strip()
        return s

    # ---------- Name (+ optional cost) ----------
    cost = None
    name = None
    raw_name = _unquote(front.get("item_name") or front.get("file_basename") or front.get("name"))
    if raw_name:
        m_cost = re.match(r'^(?P<base>.+?)\s*\(\s*(?P<amount>\d+)\s*(?P<resource>[A-Za-z]+)\s*\)\s*$', raw_name)
        if m_cost:
            name = m_cost.group('base').strip()
            cost = {"resource": m_cost.group('resource'), "amount": int(m_cost.group('amount'))}
        else:
            name = raw_name.strip()

    if not name:
        for i,l in enumerate(lines[:10]):
            m = re.match(r"^\s*#\s*(.+?)\s*$", l)
            if m:
                name = m.group(1).strip()
                break
    if not name:
        name = next((l.strip() for l in lines if l.strip()), fallback_name)

    # ---------- Flavor ----------
    flavor = _unquote(front.get("flavor")) if front.get("flavor") else None
    if flavor:
        flavor = esc_angles(flavor)
    else:
        start = 0
        for idx,l in enumerate(lines):
            if re.match(r"^\s*#\s*", l):
                start = idx + 1
                break
        paras = []
        for l in lines[start:]:
            if not l.strip(): break
            if re.search(r"(Melee|Ranged|Magic|Psionic)|Main action|Maneuver|Reaction", l, re.I):
                continue
            paras.append(l.strip())
        if paras:
            flavor = " ".join(paras)

    # ---------- Header scan (tags, action, range, target) ----------
    tags = []
    action = None
    target = None
    range_dict = {}
    header_chunk = "\n".join(lines[:50])

    # Prefer YAML keywords
    front_tags = None
    if "keywords" in front:
        if isinstance(front["keywords"], list):
            front_tags = [t for t in front["keywords"] if t]
        elif isinstance(front["keywords"], str) and front["keywords"].strip():
            front_tags = [t.strip() for t in re.split(r"[,\n]", front["keywords"]) if t.strip()]

    ALLOWED_TAG_WORDS = {
        # core usage/targeting
        "Melee","Ranged","Magic","Psionic","Strike","Weapon","Area","Charge",
        # common schools / subtypes on abilities
        "Telekinesis","Telepathy","Pyrokinesis","Chronopathy","Animapathy",
        "Metamorphosis","Green","Rot","Performance",
        # broader descriptors sometimes used
        "Supernatural","Mundane",
    }

    def _line_is_pure_tags(s: str):
        s = s.strip()
        if not s: return None
        s = re.sub(r'^[•\-\*\u2022]\s*', '', s)
        s = re.sub(r'[*_`]', '', s)
        tag_alt = "|".join(re.escape(w) for w in sorted(ALLOWED_TAG_WORDS, key=len, reverse=True))
        pattern = rf'^(?:{tag_alt})(?:\s*(?:,|•)\s*(?:{tag_alt}))*$'
        if not re.fullmatch(pattern, s, flags=re.IGNORECASE):
            return None
        parts = [w.strip() for w in re.split(r'\s*(?:,|•)\s*', s) if w.strip()]
        norm = []
        for p in parts:
            found = next((w for w in ALLOWED_TAG_WORDS if w.lower() == p.lower()), p)
            norm.append(found)
        return norm

    if front_tags:
        tags = [esc_angles(t) for t in front_tags]
    else:
        for l in lines[:20]:
            cand = _line_is_pure_tags(l)
            if cand:
                tags = cand
                break

    # Action (includes Maneuver/Reaction)
    m_action = re.search(r"\b(Main action|Maneuver|Reaction|Free action|Minor action)\b", header_chunk, re.I)
    if m_action:
        action = m_action.group(1).title()

    # Range (Self / Melee X / Ranged Y)
    for kind in ["melee", "ranged"]:
        m = re.search(rf"\b{kind}\s+(\d+)\b", header_chunk, re.I)
        if m:
            range_dict[kind] = int(m.group(1))
    if re.search(r"\bSelf\b", header_chunk, re.I):
        range_dict["self"] = True

    # >>> TARGET: multi-line aware (handles wrap after "who/that/can", etc.)
    target = None

    # 1) Prefer an explicit "Target:" label anywhere in the doc; capture until blank line / next label / header
    m_target_lbl = re.search(
        r'(?im)^\s*Target\s*:\s*(.+?)(?=\n\s*\n|^\s*#|\n\s*[A-Z][A-Za-z /]{1,40}:\s|\Z)',
        md,
        re.DOTALL
    )
    if m_target_lbl:
        target = " ".join(m_target_lbl.group(1).split()).rstrip(".")
    else:
        # 2) Fallback: a phrase starting with One/Two/Three/Each/Up to/Self + noun; allow wrap across lines
        m_target_phrase = re.search(
            r'(?is)\b(One|Two|Three|Each|Up to|Self)\b[\s]+'
            r'(ally|allies|creature|creatures|object|objects|enemy|enemies)\b'
            r'.*?(?=\n\s*\n|^\s*#|\n\s*[A-Z][A-Za-z /]{1,40}:\s|\Z)',
            md
        )
        if m_target_phrase:
            target = " ".join(m_target_phrase.group(0).split()).rstrip(" .")

    # 3) If still nothing but range is Self, assume target Self
    if not target and ("self" in range_dict):
        target = "Self"


    # ---------- Stats (only if a Power Roll line exists) ----------
    stats = []
    stat_line = None
    for l in lines:
        m = re.search(r"Power Roll\s*\+\s*(.+?):\s*$", l, re.I)
        if m:
            stat_line = m.group(1)
            break
    if stat_line:
        stat_map = {"might":"M","agility":"A","reason":"R","intellect":"I","presence":"P"}
        for word, short in stat_map.items():
            if re.search(rf"\b{word}\b", stat_line, re.I):
                stats.append(short)

    # ---------- Effect / Effects (non-roll) ----------
    effect_text = None
    m_eff = re.search(
        r'(?im)^(?:\*\*\s*)?Effects?\s*(?:\*\*)?\s*:\s*(.*?)'
        r'(?=\n\s*\n|^\s*#|\n\s*[A-Z][A-Za-z ]{1,40}:\s|\Z)',
        md,
        re.DOTALL | re.MULTILINE
    )
    if m_eff:
        effect_text = m_eff.group(1).strip()
        if not effect_text:
            after = md[m_eff.end():]
            bullets = []
            for line in after.splitlines():
                if not line.strip(): break
                if re.match(r'^\s*[-*]\s+', line):
                    bullets.append(re.sub(r'^\s*[-*]\s+', '', line).strip())
                else:
                    break
            if bullets:
                effect_text = " ".join(bullets)
        if effect_text:
            effect_text = esc_angles(effect_text)

    # ---------- Tiered damage/riders (for roll abilities) ----------
    def parse_t_line(line: str):
        mdmg = re.search(r"\b(\d+)\s*(?:\+|\b).*?damage", line, re.I)
        dmg = int(mdmg.group(1)) if mdmg else 0
        mrider = re.search(r"damage\s*[,;:]\s*(.+)$", line, re.I)
        rider = mrider.group(1).strip() if mrider else None
        return dmg, esc_angles(rider)

    def parse_tier_line(line: str):
        line = re.sub(r"^\s*[-*]\s*", "", line)
        return parse_t_line(line)

    tiers = {"1": {"damage": 0, "effects": [], "rider": None},
             "2": {"damage": 0, "effects": [], "rider": None},
             "3": {"damage": 0, "effects": [], "rider": None}}

    found_tx = False
    for l in lines:
        m = re.search(r"\bt([1-3])\s*:\s*(.+)$", l, re.I)
        if m:
            idx = m.group(1)
            rest = m.group(2).strip()
            dmg, rider = parse_t_line(rest)
            tiers[idx]["damage"] = dmg
            tiers[idx]["rider"]  = rider
            found_tx = True

    if not found_tx:
        tier_lines = []
        for l in lines:
            if re.search(r"^(?:≤\s*11|<=\s*11|11\s*or\s*less|12\s*[-–]\s*16|17\s*\+)", l):
                tier_lines.append(l.strip())
        if len(tier_lines) < 3:
            tier_lines = [l for l in lines if re.search(r"^\s*[-*]\s*(?:≤\s*11|12\s*[-–]\s*16|17\s*\+)", l)]
        for idx, tkey in enumerate(["1","2","3"]):
            if idx < len(tier_lines):
                dmg, rider = parse_tier_line(tier_lines[idx])
                tiers[tkey]["damage"] = dmg
                tiers[tkey]["rider"]  = rider
                found_tx = found_tx or True

    # ---------- Build JSON ----------
    # If there is no roll (no stats and no tier rows found), omit empty tiers.
    include_tiers = bool(stats) or found_tx

    out = {
        "name": name,
        "tags": tags,
        "action": action or "Main action",
        "range": range_dict or {},
        "target": target,
        "flavor": flavor,
        "stats": stats,
        "tiers": tiers if include_tiers else {}
    }
    if cost:
        out["cost"] = cost
    if effect_text:
        out["extra_effect"] = effect_text

    return out
# ----------------------------- END PARSER -----------------------------

# ------------ GitHub directory walking ------------
OWNER = "SteelCompendium"
REPO  = "data-md-dse"

CATEGORIES = [
    #"Rules/Abilities/Troubadour/1st-Level Features",
    #"Rules/Abilities/Kits/Shining Armor",
    #'Rules/Abilities/Common/Maneuvers',
    'Bestiary/Monsters/Monsters/Goblins',
]

URLS_TO_FETCH = []  # leave empty to use CATEGORIES via API

def github_list_files(path: str, token: str = None):
    api_path = urllib.parse.quote(path, safe="/")
    api = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{api_path}"
    headers = {"User-Agent": "convert_dse_repo.py"}
    if token:
        headers["Authorization"] = f"token {token}"
    req = urllib.request.Request(api, headers=headers)
    with urllib.request.urlopen(req) as r:
        data = r.read().decode("utf-8", errors="replace")
    arr = json.loads(data)
    files = []
    for item in arr:
        if item.get("type") == "file" and item.get("name","").lower().endswith(".md"):
            files.append(item.get("download_url"))
    return files

def main():
    outdir = Path(OUT_DIR)
    outdir.mkdir(parents=True, exist_ok=True)

    urls = []
    if not URLS_TO_FETCH:
        token = os.getenv("GITHUB_TOKEN")  # optional (avoids strict rate limits)
        for cat in CATEGORIES:
            try:
                found = github_list_files(cat, token=token)
            except Exception as e:
                print(f"[skip-list] {cat} -> {e}")
                continue
            urls.extend(found)
    else:
        for rel in URLS_TO_FETCH:
            if rel.startswith(("http://","https://")):
                urls.append(rel)
            else:
                urls.append(f"{REPO_ROOT}/{rel}")

    fetched = 0
    for url in urls:
        try:
            md = fetch(url)
        except Exception as e:
            print(f"[skip] {url} -> {e}")
            continue

        path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
        name_guess = Path(path).stem

        obj = parse_markdown(md, name_guess)
        fname = obj["name"].lower().replace(" ", "_").replace(",", "").replace("’","").replace("'","") + ".json"
        (outdir / fname).write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[ok] {obj['name']} -> {fname}")
        fetched += 1

    print(f"Done. Wrote {fetched} files to {outdir.resolve()}")

if __name__ == "__main__":
    main()
