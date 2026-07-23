# Manueller E-Mail-Versand

Admins konfigurieren den SMTP-Zugang unter **E-Mail** vollständig im Webinterface. Die Anwendung versendet keine
fachlichen E-Mails automatisch: Informationsmails und Rechnungen werden immer ausgewählt, als exakte
Empfängerzuordnung vorab angezeigt und anschließend ausdrücklich bestätigt.

## Konfiguration

Die globale Konfiguration umfasst SMTP-Host, Port, Benutzername, Passwort, STARTTLS oder SSL/TLS, Absender,
Antwortadresse und Verbindungszeitlimit. Eine Test-E-Mail wird nur über die Aktion
**Speichern und Test-E-Mail senden** ausgelöst.
Erfolgreiche und fehlgeschlagene Tests werden mit Zeitpunkt, Admin, Zieladresse und sicherem Fehlercode protokolliert;
SMTP-Antworttexte und Zugangsdaten werden nicht gespeichert.

Das SMTP-Passwort wird authentifiziert verschlüsselt in der Datenbank gespeichert und nie wieder an den Browser
ausgegeben. Der Schlüssel wird aus `DJANGO_SECRET_KEY` abgeleitet. Nach einer Rotation dieses Schlüssels muss das
SMTP-Passwort im Webinterface neu eingegeben werden. Backups der Datenbank enthalten den verschlüsselten Wert und
müssen wie andere produktive Anwendungsdaten geschützt werden.

## Informationsmails

Auf der Lagerübersicht öffnet **Information versenden** die manuelle Auswahl:

1. Betreff und Plaintext-Nachricht erfassen.
2. Teilnehmer mit E-Mail-Adresse auswählen.
3. Die normalisierten Adressen und zugeordneten Namen prüfen.
4. Den Versand verbindlich bestätigen.

Mehrere ausgewählte Teilnehmer mit derselben normalisierten Adresse werden in genau einer E-Mail zusammengefasst.
Teilnehmer ohne Adresse bleiben sichtbar, können aber nicht ausgewählt werden. Jede Nachricht besitzt genau einen
Empfänger; CC und BCC werden nicht verwendet.

## Rechnungen

**Rechnungen versenden** steht in einem gespeicherten Abrechnungslauf zur Verfügung. Die Vorschau zeigt je Auswahl
Empfängeradresse, Teilnehmer und den versionsgebundenen PDF-Dateinamen. Der Worker erzeugt den Anhang ausschließlich
aus dem unveränderlichen `Settlement`-Snapshot. Bereits versendete Rechnungen erfordern eine zusätzliche
Wiederholungsbestätigung.

## Zustellung und Fehler

Die Bestätigung erzeugt einen `EmailBatch` mit empfängerbezogenen `EmailDelivery`-Einträgen. Der Service
`email-worker` führt ausschließlich diese manuell bestätigte Outbox aus:

```bash
python manage.py run_email_worker --loop
```

Temporäre SMTP-Fehler werden mit begrenztem Backoff erneut versucht. Permanente Fehler bleiben im Versandauftrag
sichtbar und können nur durch eine Admin-Aktion erneut eingeplant werden. Logs enthalten Zustellungs-IDs,
Versuchszähler und sichere Fehlercodes, aber keine Adressen, Nachrichten, Rechnungsdaten oder SMTP-Zugangsdaten.

SMTP kann nicht garantieren, dass eine vom Server angenommene Nachricht nach einem unmittelbar folgenden
Prozessabbruch nie doppelt zugestellt wird. Die Outbox verhindert doppelte Aufträge und parallele Verarbeitung,
kann diese Transportgrenze aber nicht vollständig aufheben.
