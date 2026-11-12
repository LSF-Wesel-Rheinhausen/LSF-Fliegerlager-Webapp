Lokale Testdaten schützen bestehende Datensätze auch bei gleichen Namen und Schlüsseln. Explizite Seed-Zuordnung verhindert ungewollte Übernahmen; Konflikte und Fehler rollen den gesamten Lauf zurück. Alte Demo-Daten ohne Zuordnung benötigen eine separate neue Testdatenbank.

Geändert: Seed-Kommando, Eigentumsmodell und Migration 0082, Löschsignale, optionale Erhaltung gemeinsamer Rollenrechte, Seed- und Migrationstests sowie Entwicklerdokumentation.

Prüfung: 40 fokussierte Seed-Tests; vollständige Python-Abnahme mit 2.274 bestandenen Tests und 18 Skips; alle drei Browser mit 365 bestandenen Tests und einem Skip. Ruff, Django, Migrationsabgleich und mypy bestanden. Unabhängiges Review ohne weitere Befunde.

Offen: Remote-CI und Übernahme der Migration. Bestehende unmarkierte Demo-Daten werden nicht automatisch übernommen.
