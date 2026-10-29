# Format von analysis.json

`scripts/render_report.py analysis.json -o report.html` baut daraus die Berichtsseite.
Ein vollständiges Beispiel steht in `example-analysis.json`.

Spieler werden per Sleeper-`player_id`, per vollem Namen (wie bei Sleeper geschrieben)
oder bei Defenses per Teamkürzel (`"PIT"`) angegeben. Bilanz, Platz, Punkte, Deadline
und Gegner holt der Renderer selbst aus der Sleeper-API.

| Feld | Inhalt |
|---|---|
| `date`, `date_label`, `week` | Datum (ISO), Datum als Text, NFL-Woche |
| `headline` | Ein Satz: das Wichtigste heute |
| `context` | Bye-Teams, Spiele heute |
| `actions[]` | `type` (`lineup` · `trade` · `waiver` · `injury` · `info`), `urgency` (`now` · `today` · `week`), `league` (league_id), `text`, `players[]` |
| `leagues.{league_id}` | `short`, `anchor`, `summary`, `matchup` |
| `…lineup[]` | `slot`, `player`, `verdict` (`start` · `swap` · `check`), `replaces`, `alt` (Plan B), `note` |
| `…injuries[]` | `player`, `status` (optional, sonst aus Sleeper), `impact` (`mine` · `opponent` · `league`), `text` |
| `…opportunities[]` | `player`, `action` (z. B. „Holen“), `text` |
| `…free_agents[]` | `add`, `drop` (optional), `text` |
| `…trades[]` | `partner`, `kind` (`buy-low` · `sell-high` · `upgrade` · `depth` · `rebuild`), `give[]`, `get[]`, `text` |
| `news[]` | `title`, `text`, `impact` (`good` · `bad` · `neutral`, aus meiner Sicht), `league` (optional), `players[]`, `source`, `url` |
| `…outlook` | Kurzlage der Liga, z. B. „Angreifen: Platz 8, aber Top-2-Kaderwert“ |
| `…experts[]` | `player`, `verdict` (Start · Sit · Buy · Sell · Halten), `text`, `source`, `url` |
| `…future` (Dynasty) | `text` (Plan), `sell[]`, `buy[]`, `hold[]` mit `player` und `text` |
| `sources[]` | `title`, `url` |

In Trades (`give`/`get`) gehen auch Draft-Picks: `"2027 1st"`, `"2027 Early 2nd"` oder
`"2027 Late 2nd (Yannick0315)"` für einen fremden Pick. In Dynasty-Ligen zeigt die Seite für
jeden Spieler und Pick den KeepTradeCut-Wert und bewertet den Trade (fair / du gewinnst / du
zahlst drauf). Kaderwert der Liga, deine Picks mit Prognose und das Altersprofil berechnet
der Renderer selbst.

`**fett**` ist in allen Texten erlaubt.
