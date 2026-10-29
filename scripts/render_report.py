#!/usr/bin/env python3
"""Render the daily fantasy report as one self-contained HTML page.

Usage: python3 scripts/render_report.py analysis.json -o report.html

analysis.json is written each day from the research (see docs/analysis-format.md).
Players may be referenced by Sleeper player_id, by full name, or by team code for
defenses ("PIT"). League data (record, rank, opponent) and headshots/logos come
from the Sleeper API; images are embedded as data: URIs because the artifact
sandbox blocks external images.
"""
import argparse
import base64
import html
import json
import os
import re
import urllib.request

from sleeper_snapshot import CACHE, USERNAME, get, players_db

IMG_CACHE = os.path.join(CACHE, "img")
ACTION_LABELS = {"lineup": "Aufstellen", "trade": "Trade", "waiver": "Waiver",
                 "injury": "Verletzung", "info": "News"}
URGENCY_LABELS = {"now": "Jetzt", "today": "Heute", "week": "Diese Woche"}
LEAGUE_KIND = {0: "Redraft", 1: "Keeper", 2: "Dynasty"}
VERDICTS = {"start": "Start", "swap": "Wechsel", "check": "Prüfen"}
TRADE_KINDS = {"buy-low": "Buy-low", "sell-high": "Sell-high", "upgrade": "Upgrade",
               "depth": "Tiefe", "rebuild": "Neuaufbau"}


def esc(text):
    """Escape text and allow **bold**."""
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(str(text or "")))


def shrink(body, name):
    """Downscale to thumbnail size so the page stays small; keep the original without Pillow."""
    if not body:
        return body
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(body))
        img.thumbnail((64, 64) if name.endswith(".png") else (112, 112))
        buf = io.BytesIO()
        if name.endswith(".png"):
            img.save(buf, "PNG", optimize=True)
        else:
            img.convert("RGB").save(buf, "JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return body


def data_uri(url, name):
    os.makedirs(IMG_CACHE, exist_ok=True)
    path = os.path.join(IMG_CACHE, name)
    if not os.path.exists(path):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                body = r.read()
        except Exception:
            body = b""
        body = shrink(body, name)
        with open(path, "wb") as f:
            f.write(body)
    with open(path, "rb") as f:
        body = f.read()
    if not body:
        return None
    mime = "image/png" if name.endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(body).decode()}"


class Players:
    def __init__(self):
        self.db = players_db()
        self.by_name = {}
        for pid, p in self.db.items():
            name = (p.get("full_name") or "").lower()
            if name:
                self.by_name.setdefault(name, []).append(pid)
        self._imgs = {}
        self.used = {}

    def resolve(self, ref, rostered=()):
        if ref is None:
            return None
        ref = str(ref).strip()
        if ref in self.db:
            return ref
        ids = self.by_name.get(ref.lower(), [])
        if not ids:
            return None
        ids.sort(key=lambda i: (i not in rostered, self.db[i].get("search_rank") or 9999))
        return ids[0]

    def _img(self, key, url):
        """Return a CSS class for the image, or None if it is unavailable."""
        if key not in self._imgs:
            self._imgs[key] = data_uri(url, key)
        if not self._imgs[key]:
            return None
        cls = "i-" + re.sub(r"[^a-z0-9]", "", key.lower())
        self.used[cls] = self._imgs[key]
        return cls

    def logo(self, team):
        if not team:
            return None
        return self._img(f"logo-{team.lower()}.png", f"https://sleepercdn.com/images/team_logos/nfl/{team.lower()}.png")

    def headshot(self, pid):
        p = self.db.get(pid, {})
        if p.get("position") == "DEF":
            return self.logo(pid)
        return self._img(f"p-{pid}.jpg", f"https://sleepercdn.com/content/nfl/players/thumb/{pid}.jpg")

    def image_css(self):
        return "".join(f".{c}{{background-image:url({u})}}" for c, u in self.used.items())

    def card(self, ref, rostered=(), size="", status=None):
        pid = self.resolve(ref, rostered)
        if not pid:
            return f'<div class="pl {size}"><div class="av"><span>?</span></div><div class="pl-t"><b>{esc(ref)}</b></div></div>'
        p = self.db[pid]
        name = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        if p.get("position") == "DEF":
            name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or pid
        team = p.get("team") or ("" if p.get("position") != "DEF" else pid)
        shot = self.headshot(pid)
        logo = self.logo(team) if p.get("position") != "DEF" else None
        initials = "".join(w[0] for w in name.split()[:2]).upper()
        img = f'<i class="ph {shot}" role="img" aria-label="{esc(name)}"></i>' if shot else f"<span>{esc(initials)}</span>"
        badge = f'<i class="lg {logo}" role="img" aria-label="{esc(team)}"></i>' if logo else ""
        status = status or p.get("injury_status")
        pill = f'<i class="inj {inj_class(status)}">{esc(status)}</i>' if status else ""
        meta = f"{p.get('position', '?')} · {team or 'FA'}"
        return (f'<div class="pl {size}"><div class="av">{img}{badge}</div>'
                f'<div class="pl-t"><b>{esc(name)}</b><small>{esc(meta)} {pill}</small></div></div>')


def inj_class(status):
    s = (status or "").lower()
    if s.startswith(("out", "ir", "pup", "sus", "doubt")):
        return "bad"
    if s.startswith("quest"):
        return "warn"
    return "ok"


def league_context(user_id, league_id, week):
    league = get(f"/league/{league_id}")
    users = {u["user_id"]: u["display_name"] for u in get(f"/league/{league_id}/users")}
    rosters = get(f"/league/{league_id}/rosters")
    mine = next(r for r in rosters if r["owner_id"] == user_id)
    ranked = sorted(rosters, key=lambda r: (-r["settings"].get("wins", 0), -r["settings"].get("fpts", 0)))
    ctx = {
        "name": league["name"],
        "kind": LEAGUE_KIND.get(league["settings"].get("type"), "Liga"),
        "teams": league["total_rosters"],
        "rank": ranked.index(mine) + 1,
        "record": f"{mine['settings'].get('wins', 0)}-{mine['settings'].get('losses', 0)}",
        "pf": mine["settings"].get("fpts", 0),
        "deadline": league["settings"].get("trade_deadline"),
        "playoffs": league["settings"].get("playoff_week_start"),
        "superflex": "SUPER_FLEX" in league["roster_positions"],
        "rostered": {p for r in rosters for p in (r.get("players") or [])},
        "opponent": None,
    }
    matchups = get(f"/league/{league_id}/matchups/{week}")
    me = next((m for m in matchups if m["roster_id"] == mine["roster_id"]), None)
    if me and me.get("matchup_id"):
        opp = next((m for m in matchups if m["matchup_id"] == me["matchup_id"] and m is not me), None)
        if opp:
            o = next(r for r in rosters if r["roster_id"] == opp["roster_id"])
            ctx["opponent"] = {
                "name": users.get(o["owner_id"], "?"),
                "record": f"{o['settings'].get('wins', 0)}-{o['settings'].get('losses', 0)}",
                "pts": opp.get("points") or 0,
                "my_pts": me.get("points") or 0,
            }
    return ctx


CSS = """
/* Layout: scoreboard header, one action queue, then one band per league. */
:root {
  --bg: #f3f5f2; --surface: #ffffff; --sunk: #e7ebe6; --fg: #15201b; --muted: #5b6862;
  --line: #d5dbd5; --accent: #1f4fa3; --accent-soft: #e3eaf8;
  --good: #1d7f48; --good-soft: #def2e5; --warn: #a76a0c; --warn-soft: #fbefd7;
  --bad: #b8322a; --bad-soft: #fae0dd;
  --f-display: "Barlow Condensed", "Arial Narrow", system-ui, sans-serif;
  --f-body: "Source Sans 3", "Segoe UI", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0f1412; --surface: #171e1b; --sunk: #1f2824; --fg: #e5ebe7; --muted: #95a39c;
  --line: #2b3631; --accent: #86a8f0; --accent-soft: #1d2a45;
  --good: #5fcf8d; --good-soft: #163325; --warn: #e9b450; --warn-soft: #3a2c12;
  --bad: #f07a70; --bad-soft: #3d1c19; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #0f1412; --surface: #171e1b; --sunk: #1f2824; --fg: #e5ebe7; --muted: #95a39c;
  --line: #2b3631; --accent: #86a8f0; --accent-soft: #1d2a45;
  --good: #5fcf8d; --good-soft: #163325; --warn: #e9b450; --warn-soft: #3a2c12;
  --bad: #f07a70; --bad-soft: #3d1c19; color-scheme: dark; }
body { background: var(--bg); color: var(--fg); font: 15px/1.5 var(--f-body); }
.wrap { max-width: 1080px; margin: 0 auto; padding-block: 20px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 28px; }
h1, h2, h3 { font-family: var(--f-display); text-wrap: balance; margin: 0; line-height: 1.1; }
h1 { font-size: 2.4rem; font-weight: 700; letter-spacing: .01em; }
h2 { font-size: 1.9rem; font-weight: 700; }
h3 { font-size: 1.05rem; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
a { color: var(--accent); }
small { color: var(--muted); }
.top { display: grid; gap: 10px; }
.eyebrow { font-family: var(--f-display); font-size: 1rem; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
.headline { font-size: 1.15rem; max-width: 65ch; }
.jump { display: flex; flex-wrap: wrap; gap: 8px; }
.jump a { text-decoration: none; padding: 4px 12px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); color: var(--fg); font-weight: 600; }
.jump a:focus-visible, a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.section { display: grid; gap: 12px; }
.actions { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.act { display: grid; grid-template-columns: auto 1fr; gap: 6px 14px; align-items: center; background: var(--surface);
  border: 1px solid var(--line); border-left: 5px solid var(--accent); border-radius: 8px; padding: 10px 14px; }
.act.now { border-left-color: var(--bad); } .act.today { border-left-color: var(--warn); }
.act .chips { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
.act p { margin: 0; min-width: 0; }
.act .pls { grid-column: 2; display: flex; flex-wrap: wrap; gap: 10px; }
.chip { font: 600 .72rem/1 var(--f-body); letter-spacing: .06em; text-transform: uppercase; padding: 4px 8px; border-radius: 4px; background: var(--sunk); color: var(--fg); white-space: nowrap; }
.chip.now { background: var(--bad-soft); color: var(--bad); } .chip.today { background: var(--warn-soft); color: var(--warn); }
.chip.week { background: var(--accent-soft); color: var(--accent); }
.league { display: grid; gap: 18px; scroll-margin-top: 12px; }
.lhead { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px 24px; align-items: end;
  padding-bottom: 12px; border-bottom: 3px solid var(--fg); }
.lhead .tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
.score { display: flex; gap: 22px; flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.score div { display: grid; }
.score b { font-family: var(--f-display); font-size: 1.7rem; line-height: 1; }
.score small { text-transform: uppercase; letter-spacing: .06em; font-size: .72rem; }
.summary { margin: 0; max-width: 70ch; }
.grid2 { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 18px; align-items: start; }
@media (max-width: 820px) { .grid2 { grid-template-columns: 1fr; } }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 14px; display: grid; gap: 10px; min-width: 0; }
.lineup { display: grid; gap: 2px; }
.row { display: grid; grid-template-columns: 4.2rem minmax(0, 1fr) auto; gap: 4px 12px; align-items: center; padding: 8px 4px; border-top: 1px solid var(--line); }
.row:first-child { border-top: 0; }
.slot { font: 700 .95rem/1 var(--f-display); letter-spacing: .05em; color: var(--muted); }
.verdict { font: 600 .72rem/1 var(--f-body); text-transform: uppercase; letter-spacing: .06em; padding: 5px 8px; border-radius: 4px; }
.verdict.start { background: var(--good-soft); color: var(--good); }
.verdict.swap { background: var(--accent-soft); color: var(--accent); }
.verdict.check { background: var(--warn-soft); color: var(--warn); }
.row .note { grid-column: 2 / 4; font-size: .9rem; color: var(--muted); display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: center; }
.alt { display: inline-flex; align-items: center; gap: 6px; font-size: .85rem; color: var(--fg); }
.pl { display: flex; gap: 10px; align-items: center; min-width: 0; }
.pl .av { position: relative; flex: none; width: 44px; height: 44px; border-radius: 50%; background: var(--sunk); display: grid; place-items: center; }
.pl .av > .ph, .pl .av > span { width: 44px; height: 44px; border-radius: 50%; background-position: center; background-size: cover; background-repeat: no-repeat; }
.pl .av > span { display: grid; place-items: center; font-weight: 700; color: var(--muted); }
.pl .lg { position: absolute; right: -5px; bottom: -3px; width: 20px; height: 20px; border-radius: 50%; background-color: var(--surface); background-position: center; background-size: 86%; background-repeat: no-repeat; box-shadow: 0 0 0 1px var(--line); }
.pl-t { display: grid; min-width: 0; }
.pl-t b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pl.sm .av, .pl.sm .av > .ph, .pl.sm .av > span { width: 30px; height: 30px; }
.pl.sm .lg { width: 14px; height: 14px; right: -4px; bottom: -2px; }
.pl.sm .pl-t b { font-size: .88rem; font-weight: 600; }
.swapline .pl-t b, .act .pl-t b { white-space: normal; overflow-wrap: anywhere; }
.inj { font-style: normal; font-weight: 700; font-size: .7rem; padding: 1px 6px; border-radius: 3px; margin-left: 4px; }
.inj.bad { background: var(--bad-soft); color: var(--bad); } .inj.warn { background: var(--warn-soft); color: var(--warn); }
.inj.ok { background: var(--good-soft); color: var(--good); }
.items { display: grid; gap: 12px; }
.item { display: grid; gap: 6px; padding-top: 12px; border-top: 1px solid var(--line); }
.item:first-child { border-top: 0; padding-top: 0; }
.item p { margin: 0; }
.tag { font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }
.cards3 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 14px; }
.swapline { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 10px; align-items: center; }
.swapline .side { display: grid; gap: 6px; min-width: 0; }
.swapline .lbl { font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
.lbl.get { color: var(--good); } .lbl.give { color: var(--bad); }
.arrow { font-family: var(--f-display); font-size: 1.4rem; color: var(--muted); }
.trade-head { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; align-items: baseline; }
.matchup { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: baseline; }
.sources { columns: 2 280px; margin: 0; padding-left: 18px; font-size: .9rem; }
.sources li { break-inside: avoid; margin-bottom: 4px; }
footer { color: var(--muted); font-size: .85rem; }
@media (max-width: 480px) { h1 { font-size: 2rem; } .act { grid-template-columns: 1fr; } .act .chips { flex-direction: row; } .act .pls { grid-column: 1; } .row { grid-template-columns: 3.2rem minmax(0, 1fr) auto; } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
"""


def render(analysis):
    P = Players()
    state = get("/state/nfl")
    week = analysis.get("week") or state["week"]
    user = get(f"/user/{USERNAME}")
    leagues = []
    for lid, la in analysis["leagues"].items():
        ctx = league_context(user["user_id"], lid, week)
        leagues.append((lid, la, ctx))
    all_rostered = set().union(*(c["rostered"] for _, _, c in leagues)) if leagues else set()
    short = {lid: la.get("short") or ctx["name"] for lid, la, ctx in leagues}

    out = [f"<title>Fantasy Tagesbericht</title>",
           '<meta name="claude:viewport-fit-sides" content="cover">',
           '<link rel="preconnect" href="https://fonts.googleapis.com">',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600;700&display=swap">',
           f"<style>{CSS}</style>", '<div class="wrap">']

    out.append('<header class="top">')
    out.append(f'<div class="eyebrow">Woche {week} · {esc(analysis.get("date_label") or analysis.get("date", ""))}</div>')
    out.append("<h1>Fantasy Tagesbericht</h1>")
    if analysis.get("headline"):
        out.append(f'<p class="headline">{esc(analysis["headline"])}</p>')
    if analysis.get("context"):
        out.append(f"<small>{esc(analysis['context'])}</small>")
    out.append('<nav class="jump" aria-label="Ligen">' + "".join(
        f'<a href="#{esc(la.get("anchor") or "l" + lid)}">{esc(short[lid])}</a>' for lid, la, _ in leagues) + "</nav>")
    out.append("</header>")

    acts = analysis.get("actions") or []
    order = {"now": 0, "today": 1, "week": 2}
    acts.sort(key=lambda a: order.get(a.get("urgency"), 3))
    if acts:
        out.append('<section class="section"><h3>Heute zu tun</h3><ol class="actions">')
        for a in acts:
            u = a.get("urgency", "week")
            lg = short.get(a.get("league"), a.get("league") or "")
            pls = "".join(P.card(r, all_rostered, "sm") for r in a.get("players") or [])
            out.append(
                f'<li class="act {u}"><div class="chips"><span class="chip {u}">{URGENCY_LABELS.get(u, u)}</span>'
                f'<span class="chip">{esc(ACTION_LABELS.get(a.get("type"), a.get("type", "")))}</span></div>'
                f'<p>{"<b>" + esc(lg) + ":</b> " if lg else ""}{esc(a.get("text"))}</p>'
                + (f'<div class="pls">{pls}</div>' if pls else "") + "</li>")
        out.append("</ol></section>")

    for lid, la, ctx in leagues:
        R = ctx["rostered"]
        anchor = la.get("anchor") or "l" + lid
        out.append(f'<section class="league" id="{esc(anchor)}">')
        tags = [ctx["kind"], f"{ctx['teams']} Teams"] + (["Superflex"] if ctx["superflex"] else [])
        out.append('<div class="lhead"><div>'
                   f"<h2>{esc(ctx['name'])}</h2>"
                   '<div class="tags">' + "".join(f'<span class="chip">{esc(t)}</span>' for t in tags) + "</div></div>"
                   '<div class="score">'
                   f"<div><b>{ctx['rank']}.</b><small>Platz</small></div>"
                   f"<div><b>{ctx['record']}</b><small>Bilanz</small></div>"
                   f"<div><b>{ctx['pf']:.0f}</b><small>Punkte</small></div>"
                   f"<div><b>W{ctx['deadline']}</b><small>Trade-Deadline</small></div>"
                   "</div></div>")
        opp = ctx["opponent"]
        if opp or la.get("matchup"):
            line = (f"<b>Gegner: {esc(opp['name'])}</b> <small>({opp['record']}) · Stand "
                    f"{opp['my_pts']:.1f} : {opp['pts']:.1f}</small>") if opp else ""
            out.append(f'<div class="matchup">{line}<span>{esc(la.get("matchup"))}</span></div>')
        if la.get("summary"):
            out.append(f'<p class="summary">{esc(la["summary"])}</p>')

        out.append('<div class="grid2">')
        out.append('<div class="panel"><h3>Aufstellung</h3><div class="lineup">')
        for row in la.get("lineup") or []:
            v = row.get("verdict") or ("swap" if row.get("replaces") else "start")
            note_bits = []
            if row.get("replaces"):
                note_bits.append(f'<span class="alt">statt {P.card(row["replaces"], R, "sm")}</span>')
            if row.get("alt"):
                note_bits.append(f'<span class="alt">Plan B: {P.card(row["alt"], R, "sm")}</span>')
            if row.get("note"):
                note_bits.append(f"<span>{esc(row['note'])}</span>")
            out.append(f'<div class="row"><span class="slot">{esc(row.get("slot"))}</span>'
                       f'{P.card(row.get("player"), R)}<span class="verdict {v}">{VERDICTS.get(v, v)}</span>'
                       + (f'<div class="note">{"".join(note_bits)}</div>' if note_bits else "") + "</div>")
        out.append("</div></div>")

        out.append('<div class="panel"><h3>Verletzungen</h3><div class="items">')
        for i in la.get("injuries") or []:
            who = {"mine": "Mein Team", "opponent": "Gegner", "league": "Liga"}.get(i.get("impact"), "")
            out.append(f'<div class="item">{P.card(i.get("player"), R, status=i.get("status"))}'
                       f'<span class="tag">{esc(who)}</span><p>{esc(i.get("text"))}</p></div>')
        if not la.get("injuries"):
            out.append("<p>Keine relevanten Verletzungen.</p>")
        out.append("</div></div></div>")

        if la.get("opportunities"):
            out.append('<div class="section"><h3>Von News profitieren</h3><div class="cards3">')
            for o in la["opportunities"]:
                free = " · frei" if (P.resolve(o.get("player"), R) or "") not in R else ""
                out.append(f'<div class="panel">{P.card(o.get("player"), R)}'
                           f'<span class="tag">{esc(o.get("action_label") or o.get("action", ""))}{free}</span>'
                           f'<p>{esc(o.get("text"))}</p></div>')
            out.append("</div></div>")

        if la.get("free_agents"):
            out.append('<div class="section"><h3>Free Agents</h3><div class="cards3">')
            for fa in la["free_agents"]:
                drop = (f'<div class="side"><span class="lbl give">Droppen</span>{P.card(fa["drop"], R, "sm")}</div>'
                        if fa.get("drop") else "<div></div>")
                out.append('<div class="panel"><div class="swapline">'
                           f'<div class="side"><span class="lbl get">Holen</span>{P.card(fa.get("add"), R)}</div>'
                           f'<span class="arrow">⇄</span>{drop}</div><p>{esc(fa.get("text"))}</p></div>')
            out.append("</div></div>")

        if la.get("trades"):
            out.append('<div class="section"><h3>Trade-Tipps</h3><div class="cards3">')
            for t in la["trades"]:
                give = "".join(P.card(x, R, "sm") for x in t.get("give") or [])
                getp = "".join(P.card(x, R, "sm") for x in t.get("get") or [])
                kind = TRADE_KINDS.get(t.get("kind"), t.get("kind") or "")
                out.append('<div class="panel"><div class="trade-head">'
                           f'<b>mit {esc(t.get("partner"))}</b><span class="chip week">{esc(kind)}</span></div>'
                           '<div class="swapline">'
                           f'<div class="side"><span class="lbl give">Du gibst</span>{give}</div>'
                           '<span class="arrow">⇄</span>'
                           f'<div class="side"><span class="lbl get">Du bekommst</span>{getp}</div></div>'
                           f'<p>{esc(t.get("text"))}</p></div>')
            out.append("</div></div>")
        out.append("</section>")

    if analysis.get("sources"):
        out.append('<section class="section"><h3>Quellen</h3><ul class="sources">')
        for s in analysis["sources"]:
            out.append(f'<li><a href="{html.escape(s["url"], quote=True)}" target="_blank" rel="noopener">{esc(s.get("title") or s["url"])}</a></li>')
        out.append("</ul></section>")
    out.append(f"<footer>Daten: Sleeper API · erstellt {esc(analysis.get('generated') or analysis.get('date', ''))}. "
               "Fragliche Spieler vor Spielbeginn im offiziellen Injury Report prüfen.</footer>")
    out.append("</div>")
    out[4] = f"<style>{CSS}{P.image_css()}</style>"
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis")
    ap.add_argument("-o", "--out", default="report.html")
    args = ap.parse_args()
    with open(args.analysis) as f:
        analysis = json.load(f)
    page = render(analysis)
    with open(args.out, "w") as f:
        f.write(page)
    print(f"{args.out}: {len(page) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
