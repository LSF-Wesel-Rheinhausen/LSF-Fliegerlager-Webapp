# Dienstpläne und Kiosk-Dienste (PR #53)

Dieses Feature erweitert die LSF Fliegerlager Webapp um ein umfassendes System für Dienstpläne. Gleichzeitig wurden weitreichende Verbesserungen an der Test-Suite (E2E) vorgenommen, um die Stabilität bei parallelen Testläufen zu garantieren.

## 🌟 Neue Features & UX-Verbesserungen

- **Dienstvorlagen:** Über das Admin-Interface können tägliche Vorlagen für Dienste (z. B. Spüldienst, Küchendienst) angelegt werden. Diese definieren Startzeit, Endzeit und die Anzahl der benötigten Personen. Tageweise Ausnahmen können ebenfalls definiert werden.
- **Kiosk-Integration:** Im Kiosk sehen die Teilnehmer nun nicht nur ihre Essensbestellungen, sondern auch ihre eingeteilten und offenen Dienste.
- **Dienste übernehmen:** Offene Dienste können von den Teilnehmern direkt am Kiosk übernommen werden.
- **Dienste tauschen:** Teilnehmer können ihre zugeteilten Dienste zum Tausch anbieten. Andere Teilnehmer können diese dann per Mausklick übernehmen.
- **Fortschrittsbalken:** Ein visuell ansprechender Fortschrittsbalken im Kiosk (und im Admin-Dashboard) visualisiert den Erfüllungsgrad der Pflichtdienste pro Teilnehmer.
- **UX-Tweaks im Kiosk:**
  - Im Kiosk-Header steht nun nur noch "Hallo [Vorname]" (statt des vollen Namens), da der Vorname zur persönlichen Ansprache vollkommen ausreicht.
  - Das Logo und der Header verhalten sich responsive und passen sich besser an die Bildschirmbreite an.
  - Bei Diensten wird nun angezeigt, welche anderen Mitstreiter sich ebenfalls für denselben Dienst eingetragen haben.
  - Native HTML5-Dialoge (`<dialog>`) werden zur besseren Kontext-Erhaltung genutzt, anstatt die Nutzer beim Bearbeiten von Preisregeln auf separate Seiten umzuleiten.

## 🛠️ Technische Bugfixes & Code-Qualität

- **Idempotente Dienst-Generierung (CodeQL/Codex Finding):** Die Logik zur Generierung von Einzeldiensten nutzt nun das Attribut `start_time` im `update_or_create`-Block. Dadurch können mehrere Dienste mit demselben Namen am selben Tag existieren, solange sie unterschiedliche Startzeiten haben, ohne dass sie sich gegenseitig überschreiben.
- **Sicherheits-Guard für Lagerdaten:** Die Generierungslogik fängt nun sauber ab, wenn ein Lager angelegt wurde, bei dem das Start- oder Enddatum fehlt.
- **Playwright E2E-Infrastruktur repariert:**
  - **Zombie-Prozesse:** Das Skript `start-e2e.sh` verwendet nun `exec`, um den Python-Prozess direkt an Bash zu binden. Dadurch werden Playwright-`SIGTERM`-Signale sauber durchgereicht. Zuvor haben Zombie-Server-Prozesse die Datenbank gelockt oder Ports blockiert, was zu massiven 500er-Fehlern und "Flakiness" führte.
  - **URL-Race-Condition:** Der Regex für die Überprüfung der erfolgreichen Lager-Anlage in `setupFirstAdmin` wurde von einem fehleranfälligen `/\/$/` (das versehentlich schon bei `/setup/` ansprang) auf `/\/camps\/?$/` präzisiert. So wartet Playwright nun verlässlich ab, bis der Backend-Redirect abgeschlossen ist.
  - **Robustes Text-Matching im Kiosk:** Playwright-Assertions greifen bei Fortschrittsbalken oder Tausch-Erfolgsmeldungen nicht mehr auf unflexibles Exact-Text-Matching zurück, sondern auf dedizierte CSS-Klassen (`.progress-fill`) oder stabile Suffix-Substrings, um HTML-Fragmentierungen zu tolerieren.
