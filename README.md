# Fantasy-Manager

Täglicher Fantasy-Football-Bericht für den Sleeper-Account `eliasgrs`.

- `python3 scripts/sleeper_snapshot.py` holt aus der öffentlichen Sleeper-API für jede Liga
  Tabelle, eigenen Kader (inkl. Verletzungsstatus), Matchup, beste freie Spieler, Trending-Adds,
  die Kader aller anderen Teams und die Transaktionen der Woche.
- `python3 scripts/render_report.py analysis.json -o report.html` baut aus der täglichen Analyse
  eine Seite mit Spielerbildern und Team-Logos (Format: `docs/analysis-format.md`). Oben vergleicht
  sie die empfohlene Aufstellung mit den aktuell in Sleeper gesetzten Startern und zeigt, wer raus
  und wer rein muss.

Ein anderer Account geht per `SLEEPER_USER=<name>`. Spielerdatenbank und Bilder werden in
`.cache/` zwischengespeichert.
