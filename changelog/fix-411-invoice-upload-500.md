# Rechnung-Upload darf bei Storage-Fehlern nicht mit 500 abbrechen

- Behandelt Fehler beim Speichern hochgeladener Rechnungsbelege in den Auslagen-Endpunkten als Formularfehler.
- Verhindert, dass bei einem fehlgeschlagenen Upload ein unvollständiger Auslagen-Datensatz oder eine Benachrichtigung entsteht.
