# PR 14: Fix E2E Script Python Path

## Zusammenfassung
Behebung eines Bugs im E2E-Test-Startskript (`start-e2e.sh`), bei dem der Pfad zur Python-Umgebung hart kodiert auf `.venv/bin/python` war. Dies führte in der GitHub Actions CI (wo Python global installiert ist) zu einem Fehler. Das Skript verwendet nun einen dynamischen Fallback auf das System-`python`.

## Geänderte Dateien
- `scripts/start-e2e.sh`

## Tests
- GitHub Actions CI (Quality and browser tests) durchlaufen.

## Offene Punkte
- Keine.
