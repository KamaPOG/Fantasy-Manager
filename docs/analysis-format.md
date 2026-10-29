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
| `sources[]` | `title`, `url` |

`**fett**` ist in allen Texten erlaubt.
