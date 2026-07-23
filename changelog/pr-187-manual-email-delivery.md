# Manueller E-Mail-Versand

- Admins konfigurieren den verschlüsselten SMTP-Zugang und eine Test-E-Mail vollständig im Webinterface.
- Informations- und Rechnungs-E-Mails werden erst nach manueller Auswahl und exakter Empfängervorschau vorgemerkt.
- Ein eigener Worker verarbeitet die nachvollziehbare Outbox, hängt unveränderliche Rechnungs-PDFs an und behandelt
  temporäre sowie permanente SMTP-Fehler ohne personenbezogene Logdaten.
- Tests decken Verschlüsselung, Berechtigungen, Empfängerzuordnung, Wiederholungsbestätigung, PDF-Anhänge, Compose und
  Retry-Verhalten ab.
