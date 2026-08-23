# Gepinnte Deployments wieder aktualisierbar machen

- Closes #479: Der Update-Check leitet den Releasekanal `:latest` aus Registry und Repository eines gepinnten App-Images ab.
- Closes #377: Installation, Laufzeitprüfung und Rollback bleiben vollständig an verifizierte OCI-Manifest-Digests gebunden.
- Closes #508: Der Updater liest `APP_IMAGE` ausschließlich aus dem Portainer-Stack, sodass Imagewechsel seine eigene Servicekonfiguration nicht mehr verändern.
- Closes #509: Update-Prüfung und Installation sind exklusiv serialisiert und die Bestätigung ist an einen serverseitig gespeicherten Digest-Kandidaten gebunden.
- Closes #510: Der Updater verhindert Downgrades anhand numerischer Release-Buildnummern und konsumiert bestätigte Kandidaten atomar vor dem Installationsstart.
- Closes #511: Der Updater blockiert veraltete Stack-Definitionen und gleicht unterbrochene digestgebundene Updates anhand atomar persistierter Recovery-Daten sicher ab.
- Closes #512: Update-Kandidaten werden an den beim Check laufenden unveränderlichen Runtime-Digest gebunden und bei einer zwischenzeitlichen Änderung sicher verworfen.
- Closes #514: Registry-Discovery ist auf eine exakte Host-Allowlist begrenzt; Redirects und Credential-Weitergabe an andere Hosts werden blockiert.
- Closes #515: Der aktive Updater-Stack weist YAML-Aliase, Anchors und Merge-Keys im `updater`-Service vor Registryzugriff oder Zustandsänderungen sicher zurück.
- Closes #516: Multiarch-Indizes werden nur bei genau einem vollständig validierten Baseline-`linux/amd64`-Manifest aufgelöst; Fallbacks und mehrdeutige Deskriptoren werden abgewiesen.
- Closes #517: Registry-IP-Literale werden vor Netzwerkzugriff anhand aller speziellen `ipaddress`-Kategorien einschließlich Multicast abgewiesen; explizit erlaubte globale Literale bleiben unterstützt.
