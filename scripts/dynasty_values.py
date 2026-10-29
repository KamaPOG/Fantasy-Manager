#!/usr/bin/env python3
"""Dynasty trade values from KeepTradeCut and draft-pick ownership from Sleeper."""
import json
import os
import re
import time
import urllib.request

from sleeper_snapshot import CACHE, get

KTC_URL = "https://keeptradecut.com/dynasty-rankings?format={fmt}"
ROUND_NAMES = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm(name):
    name = SUFFIX.sub("", (name or "").lower().replace(".", "").replace("'", ""))
    return re.sub(r"[^a-z]", "", name)


def ktc(superflex=True):
    """Return {normalized name: entry} with value, 7-day trend, age; picks keyed like '2027 mid 1st'."""
    os.makedirs(CACHE, exist_ok=True)
    fmt = 2 if superflex else 1
    path = os.path.join(CACHE, f"ktc-{fmt}.json")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 12 * 3600:
        req = urllib.request.Request(KTC_URL.format(fmt=fmt), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            page = r.read().decode("utf-8", "replace")
        m = re.search(r'<script[^>]*id="ktc-players"[^>]*>(.*?)</script>', page, re.S)
        with open(path, "w") as f:
            f.write(m.group(1) if m else "[]")
    with open(path) as f:
        rows = json.load(f)
    key = "superflexValues" if superflex else "oneQBValues"
    out = {}
    for row in rows:
        vals = row.get(key) or {}
        entry = {"name": row["playerName"], "value": vals.get("value", 0), "rank": vals.get("rank"),
                 "trend7": vals.get("overall7DayTrend", 0), "age": row.get("age"),
                 "position": row.get("position"), "team": row.get("team")}
        k = row["playerName"].lower() if row.get("position") == "RDP" else norm(row["playerName"])
        out[k] = entry
    return out


def pick_tier(rank, teams):
    """Projected draft slot from current standings (worst record picks first)."""
    slot = teams - rank + 1
    if slot <= teams / 3:
        return "Early"
    if slot <= 2 * teams / 3:
        return "Mid"
    return "Late"


def pick_inventory(league_id):
    """Every future pick per roster: {roster_id: [(season, round, original_roster_id)]}."""
    league = get(f"/league/{league_id}")
    rounds = league["settings"].get("draft_rounds") or 4
    season = int(league["season"])
    rosters = [r["roster_id"] for r in get(f"/league/{league_id}/rosters")]
    owner = {(str(y), rnd, rid): rid for y in range(season + 1, season + 4)
             for rnd in range(1, rounds + 1) for rid in rosters}
    for t in get(f"/league/{league_id}/traded_picks"):
        k = (str(t["season"]), t["round"], t["roster_id"])
        if k in owner:
            owner[k] = t["owner_id"]
    inv = {rid: [] for rid in rosters}
    for (y, rnd, orig), cur in sorted(owner.items()):
        inv[cur].append((y, rnd, orig))
    return inv


def pick_label(season, rnd, tier=None):
    return f"{season} {tier + ' ' if tier else ''}{ROUND_NAMES.get(rnd, str(rnd))}"


def pick_value(values, season, rnd, tier):
    entry = values.get(pick_label(season, rnd, tier).lower())
    return entry["value"] if entry else 0
