# Security-Härtung für Produktion, Import und Kiosk

- Produktionsstarts erfordern einen starken geheimen Schlüssel und explizite erlaubte Hosts.
- HTTPS-, Cookie-, Proxy- und HSTS-Einstellungen sind kontrolliert konfigurierbar.
- Teilnehmerimporte werden nach Dateityp, Größe, Kodierung und Zeilenanzahl begrenzt.
- Wiederholte falsche Kiosk-PIN-Eingaben führen zu einer temporären Sperre.
- Security-Werkzeuge und die Trivy-GitHub-Action wurden aktualisiert und unveränderlich gepinnt.
