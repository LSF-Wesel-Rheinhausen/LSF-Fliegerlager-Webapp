# Passkeys und WebAuthn

Die Passkey-Funktion ergänzt den Verwaltungslogin für aktive Django-Konten. Kiosk-PINs bleiben ein vollständig
getrennter Anmeldeweg. Passwortlogin und optionales Authelia-SSO bleiben als Recovery verfügbar.

## Aktivierung

```dotenv
PASSKEY_ENABLED=1
PASSKEY_RP_ID=app.example.org
PASSKEY_RP_NAME=Fliegerlager-Abrechnung
PASSKEY_ORIGIN=https://app.example.org
```

`PASSKEY_RP_ID` ist der öffentliche Hostname ohne Schema oder Port. `PASSKEY_ORIGIN` ist der exakte öffentliche
Origin. HTTP wird ausschließlich für localhost akzeptiert. Änderungen an RP-ID oder Domain trennen bestehende
Credentials technisch von der Anwendung.

## Sicherheitsmodell

- Registrierung erfordert eine bestehende authentifizierte Django-Session.
- Discoverable Credentials und User Verification sind verpflichtend.
- Registrierung und Anmeldung verwenden getrennte, fünf Minuten gültige Einmal-Challenges in der Django-Session.
- Die Serverprüfung bindet jede Antwort an Challenge, RP-ID und Origin.
- Credential-IDs sind global eindeutig; Public Keys, Signaturzähler, Transport- und Backup-Metadaten liegen in der
  Datenbank. Private Schlüssel verlassen den Authenticator nicht.
- Der Signaturzähler wird mit einer Zeilensperre atomar aktualisiert. Inaktive Konten werden vor der Prüfung abgelehnt.
- JSON-Endpunkte sind größenbegrenzt, CSRF-geschützt und liefern bei Anmeldefehlern keine kontenbezogenen Details.
- Nutzer können ausschließlich eigene Passkeys anzeigen und widerrufen.

## Recovery und Betrieb

Vor Aktivierung muss mindestens ein getesteter Passwort- oder Authelia-Zugang bestehen. Vor Domain-, Proxy- oder
Origin-Änderungen ist dieser Fallback erneut zu prüfen. Verlorene Geräte werden nach Fallback-Anmeldung unter
**Passkeys** entfernt. Das Deaktivieren eines Django-Kontos sperrt dessen Passkeys ohne Löschung der Audit-relevanten
Kontodaten.

Ein kompromittierter, bereits authentifizierter Browser kann bis zum Ablauf der Django-Session einen neuen Passkey
registrieren. Deshalb gelten für Session-Cookies, HTTPS, Logout und Gerätezugriff dieselben Schutzanforderungen wie für
andere administrative Sitzungen.
