# PR #318: Django 6.0.8 Dependency Compatibility

## Zusammenfassung

- Aktualisiert Django auf `>=6.0.8,<6.1`.
- Behält die auf `main` gewünschte Cryptography-Linie `>=50.0.0,<51` bei und entfernt den widersprüchlichen Bereich `>=49.0.0,<50` aus dem Dependabot-Diff.

## Geaenderte Dateien

- `requirements.txt`

## Tests

- Temporärer Python-3.13-Resolverlauf mit den PR-Requirements reproduzierte `ResolutionImpossible` wegen der widersprüchlichen Cryptography-Bereiche.
- Die konfliktfreien Requirements wurden in einem isolierten Python-3.13-Venv installiert und auf Django 6.0.8 verifiziert.

## Offene Punkte

- Keine Anwendungscode-Anpassungen erforderlich.
