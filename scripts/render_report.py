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
import dynasty_values as dv

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

    def value(self, ref, values, rostered=()):
        """KTC value of a player or pick token, or None."""
        if not values:
            return None
        pick = PICK_RE.match(str(ref or ""))
        if pick:
            y, tier, rnd = pick.group(1), (pick.group(2) or "Mid").title(), pick.group(3).lower()
            e = values.get(f"{y} {tier} {rnd}".lower())
            return e["value"] if e else None
        pid = self.resolve(ref, rostered)
        e = values.get(dv.norm(self.db.get(pid, {}).get("full_name"))) if pid else None
        return e["value"] if e else None

    def card(self, ref, rostered=(), size="", status=None, value=None):
        pick = PICK_RE.match(str(ref or ""))
        if pick:
            y, tier, rnd, frm = pick.groups()
            label = f"{y} {rnd}" + (f" · {tier.title()}" if tier else "")
            sub = (f"von {frm}" if frm else "Draft-Pick") + (f" · Wert {value:,}".replace(",", ".") if value else "")
            return (f'<div class="pl pick {size}"><div class="av"><span>R{rnd[0]}</span></div>'
                    f'<div class="pl-t"><b>{esc(label)}</b><small>{esc(sub)}</small></div></div>')
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
        if value:
            meta += f" · Wert {value:,}".replace(",", ".")
        return (f'<div class="pl {size}"><div class="av">{img}{badge}</div>'
                f'<div class="pl-t"><b>{esc(name)}</b><small>{esc(meta)} {pill}</small></div></div>')


PICK_RE = re.compile(r"^(20\d\d)\s+(?:(early|mid|late)\s+)?(1st|2nd|3rd|4th)(?:\s*\((?:von\s+)?(.+)\))?$", re.I)


def fmt(n):
    return f"{n:,.0f}".replace(",", ".")


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
        "starters": mine.get("starters") or [],
        "lid": league_id,
        "dynasty": league["settings"].get("type") == 2,
        "values": None,
    }
    if ctx["dynasty"]:
        try:
            values = dv.ktc(superflex=ctx["superflex"])
            ctx["values"] = values
            inv = dv.pick_inventory(league_id)
            rank_of = {r["roster_id"]: i for i, r in enumerate(ranked, 1)}
            season = int(league["season"])

            def pval(y, rnd, orig):
                tier = dv.pick_tier(rank_of[orig], len(rosters)) if int(y) == season + 1 else "Mid"
                return tier, dv.pick_value(values, y, rnd, tier)

            pdb = players_db()
            teams = []
            for r in rosters:
                pv = sum(values.get(dv.norm(pdb.get(p, {}).get("full_name")), {}).get("value", 0) for p in r.get("players") or [])
                kv = sum(pval(*pk)[1] for pk in inv.get(r["roster_id"], []))
                teams.append({"name": users.get(r["owner_id"], "?"), "players": pv, "picks": kv, "me": r is mine})
            teams.sort(key=lambda t: -(t["players"] + t["picks"]))
            ctx["team_values"] = teams
            owner_name = {r["roster_id"]: users.get(r["owner_id"], "?") for r in rosters}
            ctx["picks"] = [{"season": y, "round": rnd, "tier": pval(y, rnd, orig)[0], "value": pval(y, rnd, orig)[1],
                             "from": None if orig == mine["roster_id"] else owner_name[orig]}
                            for y, rnd, orig in inv.get(mine["roster_id"], [])]
            ages = []
            for p in mine.get("players") or []:
                e = values.get(dv.norm(pdb.get(p, {}).get("full_name")))
                if e and e.get("age"):
                    ages.append((e["age"], e["value"], p))
            ctx["ages"] = ages
        except Exception:
            ctx["values"] = None
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


def lineup_changes(P, la, ctx):
    """Diff the recommended lineup against the starters currently set in Sleeper."""
    R = ctx["rostered"]
    rows = [(P.resolve(r.get("player"), R), r) for r in la.get("lineup") or []]
    rec = [pid for pid, _ in rows if pid]
    current = list(ctx["starters"])
    outs = [c for c in current if c not in rec]
    ins = [(pid, r) for pid, r in rows if pid and pid not in current]
    pos = lambda pid: P.db.get(pid, {}).get("position")
    swaps = []
    for pid, row in ins:
        match = next((o for o in outs if o != "0" and pos(o) == pos(pid)), None) or (outs[0] if outs else None)
        if match is not None:
            outs.remove(match)
        swaps.append({"out": None if match in (None, "0") else match, "in": pid, "slot": row.get("slot"),
                      "note": row.get("note")})
    for o in outs:
        if o != "0":
            swaps.append({"out": o, "in": None, "slot": None, "note": None})
    conditional = [(pid, r) for pid, r in rows if pid and r.get("alt") and r.get("verdict") == "check"]
    return swaps, conditional


def render_overview(P, leagues, short):
    out = ['<section class="section"><h3>Überblick</h3><div class="ov">']
    for lid, la, ctx in leagues:
        swaps, _ = lineup_changes(P, la, ctx)
        mine_inj = [i for i in la.get("injuries") or [] if i.get("impact") == "mine"]
        stats = [("Wechsel", len(swaps), "bad" if swaps else "good"),
                 ("Waiver", len(la.get("free_agents") or []), "warn" if la.get("free_agents") else "good"),
                 ("Trades", len(la.get("trades") or []), "acc"),
                 ("Verletzt", len(mine_inj), "warn" if mine_inj else "good")]
        if ctx.get("team_values"):
            pos = next(i for i, t in enumerate(ctx["team_values"], 1) if t["me"])
            stats.append(("Kaderwert", f"{pos}.", "acc"))
        outlook = la.get("outlook") or (la.get("future") or {}).get("outlook")
        out.append(f'<a class="ov-t" href="#{esc(la.get("anchor") or "l" + lid)}"><div class="ov-h"><b>{esc(short[lid])}</b>'
                   f'<small>{ctx["rank"]}. Platz · {ctx["record"]}</small></div>'
                   + (f'<span class="chip week">{esc(outlook)}</span>' if outlook else "")
                   + '<div class="ov-s">' + "".join(
                       f'<div class="st {c}"><b>{v}</b><small>{l}</small></div>' for l, v, c in stats) + "</div></a>")
    out.append("</div></section>")
    return "".join(out)


def render_news(P, news, short, rostered):
    if not news:
        return ""
    out = ['<section class="section"><h3>News des Tages</h3><div class="news">']
    for n in news:
        imp = n.get("impact", "neutral")
        lab = {"good": "Gut für dich", "bad": "Schlecht für dich", "neutral": "Info"}.get(imp, imp)
        pls = "".join(P.card(r, rostered, "sm") for r in n.get("players") or [])
        src = (f'<a href="{html.escape(n["url"], quote=True)}" target="_blank" rel="noopener">{esc(n.get("source") or "Quelle")}</a>'
               if n.get("url") else esc(n.get("source")))
        lg = short.get(n.get("league"), "")
        out.append(f'<article class="nw {imp}"><div class="nw-h"><span class="chip {imp}">{lab}</span>'
                   + (f'<span class="chip">{esc(lg)}</span>' if lg else "") + f"<small>{src}</small></div>"
                   f"<b>{esc(n.get('title'))}</b><p>{esc(n.get('text'))}</p>"
                   + (f'<div class="pls">{pls}</div>' if pls else "") + "</article>")
    out.append("</div></section>")
    return "".join(out)


def render_future(P, la, ctx):
    fut = la.get("future") or {}
    if not (ctx.get("dynasty") and (fut or ctx.get("picks"))):
        return ""
    R, V = ctx["rostered"], ctx.get("values")
    out = ['<div class="section"><h3>Zukunft &amp; Dynasty-Plan</h3>']
    if fut.get("text"):
        out.append(f'<p class="summary">{esc(fut["text"])}</p>')
    out.append('<div class="grid2">')
    if ctx.get("team_values"):
        top = max(t["players"] + t["picks"] for t in ctx["team_values"]) or 1
        out.append('<div class="panel"><h3>Kaderwert der Liga</h3><small>KeepTradeCut, Spieler + Picks</small><div class="bars">')
        for i, t in enumerate(ctx["team_values"], 1):
            w1, w2 = 100 * t["players"] / top, 100 * t["picks"] / top
            out.append(f'<div class="bar{" me" if t["me"] else ""}"><span>{i}. {esc(t["name"])}</span>'
                       f'<div class="track"><i class="pv" style="width:{w1:.1f}%"></i><i class="kv" style="width:{w2:.1f}%"></i></div>'
                       f'<b>{fmt(t["players"] + t["picks"])}</b></div>')
        out.append('</div><small class="legend"><i class="pv"></i> Spieler <i class="kv"></i> Picks</small></div>')
    if ctx.get("picks"):
        out.append('<div class="panel"><h3>Deine Draft-Picks</h3><small>Prognose nach aktueller Tabelle</small><div class="picks">')
        for pk in ctx["picks"]:
            rn = dv.ROUND_NAMES[pk["round"]]
            out.append(f'<div class="pk r{pk["round"]}"><b>{pk["season"]} {rn}</b><small>{pk["tier"]}'
                       + (f' · von {esc(pk["from"])}' if pk["from"] else "") + f'</small><span>{fmt(pk["value"])}</span></div>')
        out.append("</div></div>")
    out.append("</div>")
    if ctx.get("ages"):
        buckets = [("bis 24", lambda a: a < 25), ("25–27", lambda a: 25 <= a < 28), ("28–30", lambda a: 28 <= a < 31), ("31+", lambda a: a >= 31)]
        tot = sum(v for _, v, _ in ctx["ages"]) or 1
        out.append('<div class="panel"><h3>Altersprofil deines Kaders</h3><small>Anteil am Kaderwert</small><div class="ages">')
        for name, f in buckets:
            share = sum(v for a, v, _ in ctx["ages"] if f(a)) / tot
            out.append(f'<div class="ag"><span>{name}</span><div class="track"><i class="pv" style="width:{100 * share:.0f}%"></i></div><b>{100 * share:.0f}%</b></div>')
        out.append("</div></div>")
    for key, title, cls in (("sell", "Verkaufen, solange der Wert da ist", "give"), ("buy", "Kaufen für die Zukunft", "get"), ("hold", "Halten", "")):
        if fut.get(key):
            out.append(f'<div class="panel"><h3>{title}</h3><div class="cards3 inner">')
            for it in fut[key]:
                out.append(f'<div class="item">{P.card(it.get("player"), R, value=P.value(it.get("player"), V, R))}<p>{esc(it.get("text"))}</p></div>')
            out.append("</div></div>")
    out.append("</div>")
    return "".join(out)


def render_experts(P, la, ctx):
    if not la.get("experts"):
        return ""
    R = ctx["rostered"]
    out = ['<div class="section"><h3>Was die Profis sagen</h3><div class="cards3">']
    for e in la["experts"]:
        v = (e.get("verdict") or "").lower()
        cls = "start" if v in ("start", "buy", "kaufen", "holen") else "check" if v in ("sit", "sell", "verkaufen", "bank") else "swap"
        src = (f'<a href="{html.escape(e["url"], quote=True)}" target="_blank" rel="noopener">{esc(e.get("source"))}</a>'
               if e.get("url") else esc(e.get("source")))
        out.append(f'<div class="panel"><div class="trade-head">{P.card(e.get("player"), R)}'
                   f'<span class="verdict {cls}">{esc(e.get("verdict"))}</span></div>'
                   f"<p>{esc(e.get('text'))}</p><small>{src}</small></div>")
    out.append("</div></div>")
    return "".join(out)


def render_changes(P, leagues, short):
    out = ['<section class="section" id="aendern"><h3>Bei Sleeper ändern</h3><div class="changes">']
    for lid, la, ctx in leagues:
        R = ctx["rostered"]
        swaps, conditional = lineup_changes(P, la, ctx)
        state = "todo" if swaps else "done"
        out.append(f'<div class="panel chg {state}"><div class="chg-head"><b>{esc(short[lid])}</b>'
                   f'<a class="btn" href="https://sleeper.com/leagues/{lid}/team" target="_blank" rel="noopener">'
                   "In Sleeper öffnen ↗</a></div>")
        if swaps:
            n = len(swaps)
            out.append(f'<p class="chg-sum">{n} {"Wechsel" if n == 1 else "Wechsel"} nötig</p>')
            for sw in swaps:
                left = P.card(sw["out"], R) if sw["out"] else '<span class="empty">leerer Slot</span>'
                right = P.card(sw["in"], R) if sw["in"] else '<span class="empty">auf die Bank, Slot neu besetzen</span>'
                slot = f'<span class="slot">{esc(sw["slot"])}</span>' if sw["slot"] else ""
                out.append('<div class="io">'
                           f'<div class="side out"><span class="lbl give">Raus</span>{left}</div>'
                           '<span class="arrow">→</span>'
                           f'<div class="side in"><span class="lbl get">Rein {slot}</span>{right}</div>'
                           + (f'<p class="io-note">{esc(sw["note"])}</p>' if sw["note"] else "") + "</div>")
        else:
            out.append('<p class="chg-sum ok">✓ Keine Änderung nötig. Deine Aufstellung in Sleeper passt.</p>')
        if conditional:
            out.append('<div class="cond"><span class="tag">Nur falls Out</span>')
            for pid, row in conditional:
                out.append('<div class="io sm">'
                           f'<div class="side out">{P.card(pid, R, "sm")}</div><span class="arrow">→</span>'
                           f'<div class="side in">{P.card(row["alt"], R, "sm")}</div></div>')
            out.append("</div>")
        out.append("</div>")
    out.append("</div></section>")
    return "".join(out)


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
.changes { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 14px; align-items: start; }
.chg { border-top: 5px solid var(--bad); }
.chg.done { border-top-color: var(--good); }
.chg-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }
.chg-head b { font-family: var(--f-display); font-size: 1.4rem; }
.btn { display: inline-block; padding: 6px 12px; border-radius: 6px; background: var(--accent); color: var(--surface); font-weight: 700; text-decoration: none; font-size: .9rem; }
.btn:focus-visible { outline: 2px solid var(--fg); outline-offset: 2px; }
.chg-sum { margin: 0; font-weight: 700; color: var(--bad); }
.chg-sum.ok { color: var(--good); }
.io { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 6px 10px; align-items: center;
  padding: 10px; border-radius: 8px; background: var(--sunk); }
.io .side { display: grid; gap: 6px; min-width: 0; }
.io .side.out { opacity: .85; }
.io .pl-t b { white-space: normal; overflow-wrap: anywhere; }
.io .slot { font-size: .8rem; margin-left: 4px; color: var(--good); }
.io-note { grid-column: 1 / -1; margin: 0; font-size: .88rem; color: var(--muted); }
.io.sm { padding: 6px 10px; }
.cond { display: grid; gap: 6px; }
.empty { font-style: italic; color: var(--muted); }
.items { display: grid; gap: 12px; }
.ov { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: 14px; }
.ov-t { display: grid; gap: 10px; padding: 14px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); color: var(--fg); text-decoration: none; }
.ov-t:hover { border-color: var(--accent); }
.ov-h { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.ov-h b { font-family: var(--f-display); font-size: 1.4rem; }
.ov-t > .chip { justify-self: start; }
.ov-s { display: grid; grid-template-columns: repeat(auto-fit, minmax(68px, 1fr)); gap: 6px; }
.st { display: grid; padding: 8px; border-radius: 6px; background: var(--sunk); font-variant-numeric: tabular-nums; }
.st b { font-family: var(--f-display); font-size: 1.5rem; line-height: 1; }
.st small { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; }
.st.bad b { color: var(--bad); } .st.warn b { color: var(--warn); } .st.good b { color: var(--good); } .st.acc b { color: var(--accent); }
.news { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 12px; }
.nw { display: grid; gap: 6px; align-content: start; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }
.nw p { margin: 0; }
.nw-h { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.nw .pls { display: flex; flex-wrap: wrap; gap: 10px; }
.chip.good { background: var(--good-soft); color: var(--good); } .chip.bad { background: var(--bad-soft); color: var(--bad); }
.chip.neutral { background: var(--sunk); color: var(--muted); }
.bal { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-variant-numeric: tabular-nums; }
.bal b { font-family: var(--f-display); font-size: 1.2rem; }
.bars, .ages { display: grid; gap: 6px; }
.bar, .ag { display: grid; grid-template-columns: minmax(0, 9rem) minmax(0, 1fr) 4.5rem; gap: 8px; align-items: center; font-size: .88rem; font-variant-numeric: tabular-nums; }
.ag { grid-template-columns: 4rem minmax(0, 1fr) 3rem; }
.bar span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar b, .ag b { text-align: right; }
.bar.me { font-weight: 700; } .bar.me span { color: var(--accent); }
.track { display: flex; height: 10px; border-radius: 5px; background: var(--sunk); overflow: hidden; }
.track i, .legend i { display: inline-block; height: 100%; }
i.pv { background: var(--accent); } i.kv { background: var(--warn); }
.legend { display: flex; gap: 6px; align-items: center; }
.legend i { width: 10px; height: 10px; border-radius: 2px; }
.picks { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
@media (max-width: 480px) { .picks { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.pk { display: grid; padding: 8px; border-radius: 6px; background: var(--sunk); font-variant-numeric: tabular-nums; }
.pk b { font-size: .9rem; } .pk span { font-family: var(--f-display); font-size: 1.2rem; }
.pk.r1 { box-shadow: inset 3px 0 0 var(--accent); } .pk.r2 { box-shadow: inset 3px 0 0 var(--warn); }
.pl.pick .av > span { width: 44px; height: 44px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); }
.pl.pick.sm .av > span { width: 30px; height: 30px; font-size: .8rem; }
.cards3.inner { gap: 16px; }
.cards3.inner .item { border-top: 0; padding-top: 0; }
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
        f'<a href="#{esc(la.get("anchor") or "l" + lid)}">{esc(short[lid])}</a>' for lid, la, _ in leagues)
        + '<a href="#aendern">Raus / Rein</a></nav>')
    out.append("</header>")

    out.append(render_overview(P, leagues, short))
    out.append(render_changes(P, leagues, short))

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

    out.append(render_news(P, analysis.get("news"), short, all_rostered))

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

        out.append(render_experts(P, la, ctx))

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
            V = ctx.get("values")
            for t in la["trades"]:
                gv = [P.value(x, V, R) for x in t.get("give") or []]
                tv = [P.value(x, V, R) for x in t.get("get") or []]
                give = "".join(P.card(x, R, "sm", value=v) for x, v in zip(t.get("give") or [], gv))
                getp = "".join(P.card(x, R, "sm", value=v) for x, v in zip(t.get("get") or [], tv))
                kind = TRADE_KINDS.get(t.get("kind"), t.get("kind") or "")
                balance = ""
                if V and any(gv) and any(tv):
                    g, b = sum(v or 0 for v in gv), sum(v or 0 for v in tv)
                    diff = (b - g) / max(g, b)
                    word, cls = (("fair", "ok") if abs(diff) <= .12 else ("du gewinnst Wert", "ok") if diff > 0
                                 else ("du zahlst drauf", "warn"))
                    balance = (f'<div class="bal"><small>KTC-Wert</small><b>{fmt(g)}</b><span>⇄</span><b>{fmt(b)}</b>'
                               f'<i class="inj {cls}">{word}</i></div>')
                out.append('<div class="panel"><div class="trade-head">'
                           f'<b>mit {esc(t.get("partner"))}</b><span class="chip week">{esc(kind)}</span></div>'
                           '<div class="swapline">'
                           f'<div class="side"><span class="lbl give">Du gibst</span>{give}</div>'
                           '<span class="arrow">⇄</span>'
                           f'<div class="side"><span class="lbl get">Du bekommst</span>{getp}</div></div>'
                           f'{balance}<p>{esc(t.get("text"))}</p></div>')
            out.append("</div></div>")
        out.append(render_future(P, la, ctx))
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
