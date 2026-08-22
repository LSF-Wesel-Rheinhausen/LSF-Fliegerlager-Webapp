# Kioskprofil-Layout korrigieren

- Closes #461: Profilfelder nutzen mobil die verfügbare Breite und bleiben auf Desktop auf eine lesbare Breite begrenzt.
- Speichern und Abbrechen sind gleich breit, nicht überdehnt und mindestens 44 Pixel hoch.
- Gleichmäßige Abstände zwischen Feldgruppen halten Labels, Hilfetexte und Validierungsfehler überlappungsfrei.
- Der bestehende native Datumstyp, die Formularvalidierung, Fokusmarkierung und Tab-Reihenfolge bleiben erhalten.
- Closes #505: Geburtsdaten werden in Teilnehmer- und Familienprofilen auch unter deutscher Locale als natives ISO-Datum gerendert, sodass unverändertes Speichern den vorhandenen Wert bewahrt.
- Closes #506: Alle editierbaren Felder im Kioskprofil haben profilgescopte, mindestens 44 Pixel hohe Touch-Ziele mit stabiler Date-Input-Boxgröße.
