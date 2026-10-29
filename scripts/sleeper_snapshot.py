#!/usr/bin/env python3
"""Fetch a Sleeper snapshot (rosters, matchups, injuries, trending) for the daily briefing."""
import json
import os
import sys
import time
import urllib.request

API = "https://api.sleeper.app/v1"
USERNAME = os.environ.get("SLEEPER_USER", "eliasgrs")
CACHE = os.path.join(os.path.dirname(__file__), "..", ".cache")


def get(path):
    with urllib.request.urlopen(f"{API}{path}", timeout=30) as r:
        return json.load(r)


def players_db():
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "players.json")
    # Sleeper asks to fetch the full player list at most once per day.
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 86400:
        data = get("/players/nfl")
        with open(path, "w") as f:
            json.dump(data, f)
    with open(path) as f:
        return json.load(f)


def describe(pid, players, points=None):
    p = players.get(pid, {})
    name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or pid
    out = f"{name} ({p.get('position', '?')}, {p.get('team') or 'FA'})"
    if p.get("injury_status"):
        out += f" [{p['injury_status']}: {p.get('injury_body_part') or '?'}]"
    if points is not None:
        out += f" {points:.1f} pts"
    return out


def dynasty_section(lid, league, rosters, mine, ranked, users, players):
    from dynasty_values import ktc, norm, pick_inventory, pick_label, pick_tier, pick_value
    try:
        values = ktc(superflex="SUPER_FLEX" in league["roster_positions"])
    except Exception as e:  # KTC down should not break the daily report
        print(f"\n### Dynasty-Werte nicht verfügbar ({e})")
        return
    teams = len(rosters)
    rank_of = {r["roster_id"]: i for i, r in enumerate(ranked, 1)}
    inv = pick_inventory(lid)
    season = int(league["season"])

    def pval(y, rnd, orig):
        tier = pick_tier(rank_of[orig], teams) if int(y) == season + 1 else "Mid"
        return tier, pick_value(values, y, rnd, tier)

    def team_value(r):
        pv = sum(values.get(norm(players.get(p, {}).get("full_name")), {}).get("value", 0) for p in r.get("players") or [])
        kv = sum(pval(*pk)[1] for pk in inv.get(r["roster_id"], []))
        return pv, kv

    print("\n### Dynasty-Werte (KeepTradeCut, %s)" % ("Superflex" if "SUPER_FLEX" in league["roster_positions"] else "1QB"))
    totals = sorted(((sum(team_value(r)), r) for r in rosters), key=lambda x: -x[0])
    for i, (tot, r) in enumerate(totals, 1):
        pv, kv = team_value(r)
        flag = " <- DU" if r is mine else ""
        print(f"{i}. {users.get(r['owner_id'], '?')}: {tot} (Spieler {pv}, Picks {kv}){flag}")
    print("\nMein Kader nach Wert (Name – Wert, 7-Tage-Trend, Alter):")
    mine_vals = []
    for p in mine.get("players") or []:
        e = values.get(norm(players.get(p, {}).get("full_name")))
        mine_vals.append((e["value"] if e else 0, p, e))
    for v, p, e in sorted(mine_vals, key=lambda x: -x[0]):
        extra = f"{v}, Trend {e['trend7']:+d}, Alter {e['age']}" if e else "kein KTC-Wert"
        print(f"- {describe(p, players)} – {extra}")
    print("\nMeine Draft-Picks (Prognose nach aktueller Tabelle):")
    for y, rnd, orig in inv.get(mine["roster_id"], []):
        tier, v = pval(y, rnd, orig)
        frm = "" if orig == mine["roster_id"] else f" (von {users.get(next(r['owner_id'] for r in rosters if r['roster_id'] == orig), '?')})"
        print(f"- {pick_label(y, rnd, tier)}{frm} – Wert {v}")
    gone = [(y, rnd) for (y, rnd, orig) in (pk for rid, pks in inv.items() if rid != mine["roster_id"] for pk in pks)
            if orig == mine["roster_id"]]
    if gone:
        print("Abgegebene eigene Picks: " + ", ".join(pick_label(y, r) for y, r in gone))
    print("\nPick-Bestand der anderen Teams: " + "; ".join(
        f"{users.get(r['owner_id'], '?')} {len(inv.get(r['roster_id'], []))}" for r in rosters if r is not mine))


def main():
    state = get("/state/nfl")
    season, week = state["season"], state["week"]
    user = get(f"/user/{USERNAME}")
    players = players_db()
    print(f"# Sleeper snapshot – Season {season}, Week {week}\n")

    for league in get(f"/user/{user['user_id']}/leagues/nfl/{season}"):
        lid = league["league_id"]
        users = {u["user_id"]: u["display_name"] for u in get(f"/league/{lid}/users")}
        rosters = get(f"/league/{lid}/rosters")
        by_rid = {r["roster_id"]: r for r in rosters}
        mine = next((r for r in rosters if r["owner_id"] == user["user_id"]), None)
        kind = {0: "Redraft", 1: "Keeper", 2: "Dynasty"}.get(league["settings"].get("type"), "?")
        st = league["settings"]
        print(f"## {league['name']} ({kind}, {league['total_rosters']} Teams, "
              f"PPR {league['scoring_settings'].get('rec')}) – league_id {lid}")
        print(f"Trade-Deadline Woche {st.get('trade_deadline')}, Playoffs ab Woche {st.get('playoff_week_start')}, "
              f"IR-Slots {st.get('reserve_slots')}")
        print("Slots: " + ", ".join(s for s in league["roster_positions"] if s != "BN"))
        if not mine:
            print("Kein eigener Kader gefunden.\n")
            continue

        # Standings
        ranked = sorted(rosters, key=lambda r: (-r["settings"].get("wins", 0), -r["settings"].get("fpts", 0)))
        print("\n### Tabelle")
        for i, r in enumerate(ranked, 1):
            s = r["settings"]
            flag = " <- DU" if r is mine else ""
            print(f"{i}. {users.get(r['owner_id'], '?')} {s.get('wins', 0)}-{s.get('losses', 0)} "
                  f"({s.get('fpts', 0)} PF){flag}")

        starters = mine.get("starters") or []
        bench = [p for p in (mine.get("players") or []) if p not in starters and p not in (mine.get("reserve") or [])]
        print("\n### Mein Kader – Starter")
        for slot, pid in zip([s for s in league["roster_positions"] if s != "BN"], starters):
            print(f"- {slot}: {describe(pid, players)}")
        print("### Bank")
        for pid in bench:
            print(f"- {describe(pid, players)}")
        if mine.get("reserve"):
            print("### IR")
            for pid in mine["reserve"]:
                print(f"- {describe(pid, players)}")

        matchups = get(f"/league/{lid}/matchups/{week}")
        me = next((m for m in matchups if m["roster_id"] == mine["roster_id"]), None)
        if me and me.get("matchup_id"):
            opp = next((m for m in matchups if m["matchup_id"] == me["matchup_id"] and m is not me), None)
            if opp:
                o = by_rid[opp["roster_id"]]
                print(f"\n### Matchup Woche {week}: {me.get('points', 0):.1f} vs "
                      f"{opp.get('points', 0):.1f} – Gegner {users.get(o['owner_id'], '?')}")
                for pid in opp.get("starters") or []:
                    print(f"- {describe(pid, players, (opp.get('players_points') or {}).get(pid))}")

        rostered = {p for r in rosters for p in (r.get("players") or [])}
        print("\n### Trending Adds (24h), frei in dieser Liga")
        for t in get("/players/nfl/trending/add?lookback_hours=24&limit=40"):
            if t["player_id"] not in rostered:
                print(f"- {describe(t['player_id'], players)} – +{t['count']}")

        free = [(pid, p) for pid, p in players.items()
                if pid not in rostered and p.get("active") and p.get("team")
                and p.get("position") in ("QB", "RB", "WR", "TE") and p.get("search_rank")]
        free.sort(key=lambda x: x[1]["search_rank"])
        print("\n### Beste freie Spieler (nach Sleeper-Rang)")
        for pid, p in free[:25]:
            print(f"- {describe(pid, players)} – Alter {p.get('age')}, Rang {p['search_rank']}")

        if league["settings"].get("type") == 2:
            dynasty_section(lid, league, rosters, mine, ranked, users, players)

        print("\n### Andere Kader (für Trades)")
        for r in ranked:
            if r is mine:
                continue
            groups = {}
            for pid in r.get("players") or []:
                pos = players.get(pid, {}).get("position")
                if pos in ("QB", "RB", "WR", "TE"):
                    groups.setdefault(pos, []).append(describe(pid, players))
            s = r["settings"]
            print(f"- **{users.get(r['owner_id'], '?')}** ({s.get('wins', 0)}-{s.get('losses', 0)}): "
                  + " | ".join(f"{pos}: {', '.join(groups.get(pos, []))}" for pos in ("QB", "RB", "WR", "TE")))

        tx = [t for t in get(f"/league/{lid}/transactions/{week}") if t.get("status") == "complete"]
        if tx:
            print("\n### Transaktionen diese Woche")
            for t in tx[:15]:
                adds = ", ".join(describe(p, players) for p in (t.get("adds") or {}))
                drops = ", ".join(describe(p, players) for p in (t.get("drops") or {}))
                print(f"- {t['type']}: +[{adds}] -[{drops}]")
        print()


if __name__ == "__main__":
    sys.exit(main())
