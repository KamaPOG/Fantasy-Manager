# Fantasy-Manager

Täglicher Fantasy-Football-Bericht für den Sleeper-Account `eliasgrs`.

`python3 scripts/sleeper_snapshot.py` holt aus der öffentlichen Sleeper-API für jede Liga:
Tabelle, eigenen Kader (inkl. Verletzungsstatus), das aktuelle Matchup, freie Trending-Adds
und die Transaktionen der Woche. Ein anderer Account geht per `SLEEPER_USER=<name>`.

Die Spielerdatenbank wird in `.cache/` höchstens einmal pro Tag neu geladen.
