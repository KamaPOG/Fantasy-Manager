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
        print(f"## {league['name']} ({kind}, {league['total_rosters']} Teams, "
              f"PPR {league['scoring_settings'].get('rec')})")
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
