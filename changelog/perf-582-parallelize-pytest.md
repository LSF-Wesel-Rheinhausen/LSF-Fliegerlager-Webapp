# Schnellere lokale Pytest-Suite

## Zusammenfassung

Der vollständige lokale Testlauf nutzt standardmäßig vier plattformunabhängige Pytest-Worker. Der direkte Pytest-Befehl und CI bleiben seriell; ein dokumentierter lokaler Fallback stellt das bisherige Verhalten jederzeit wieder her.

## Geänderte Bereiche

- `pytest-xdist` wird ausschließlich als Entwicklungsabhängigkeit installiert.
- `npm run test:local` verteilt normale Python-Tests mit vier Workern nach Testdateien.
- Schemaverändernde Migrationstests laufen weiterhin als unabhängiger Schritt seriell, auch wenn der parallele Schritt fehlschlägt.
- `PYTEST_WORKERS=2` reduziert die Parallelität auf ressourcenarmen Systemen; `PYTEST_WORKERS=0 npm run test:local` erzwingt den vollständig seriellen Diagnosepfad.
- Test- und Beitragsdokumentation beschreiben Worker-Default, Plattformunabhängigkeit und Fallback.
- Ein zeitkritischer Pytest-Grenzwerttest verwendet eine feste Uhr; ein umfangreicher WebKit-Test erhält das bestehende lokale 60-Sekunden-Limit. Assertions und Testabdeckung bleiben unverändert.

## Tests und Messungen

- Ein statischer Regressionstest schützt Dependency-, Worker-, Scheduler- und Fallback-Vertrag.
- Serielle Baseline: etwa 22:55 Minuten.
- Zwei Worker: 12:03 Minuten plus 20 Sekunden für 13 serielle Migrationstests.
- Vier Worker: 6:39 Minuten plus serielle Migrationstests; der Stabilitätslauf bestätigte das Ergebnis mit 6:38 Minuten.
- Maßgeblicher Python-3.13.14-Abschlusslauf: 4:50 Minuten plus 20 Sekunden für 13 serielle Migrationstests.
- Beide parallelen Konfigurationen bestanden wiederholt ohne Fehler; vier Worker reduzieren den Pytest-Anteil unter Python 3.13 damit um rund 79 Prozent.

## Offene Punkte

Keine.
