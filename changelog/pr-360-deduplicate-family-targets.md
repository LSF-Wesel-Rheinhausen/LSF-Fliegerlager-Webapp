# P1: Keine doppelten Begleiter-Ziele im Kiosk

Die Kiosk-Zielauswahl dedupliziert Begleiter anhand des stabilen `family-<PK>`-Tokens, wenn derselbe Datensatz über eigene und verknüpfte Haushaltsdaten geliefert wird. Unterschiedliche Begleiter mit gleichem Namen bleiben getrennt; inaktive Begleiter und der unveränderte Login-Vertrag bleiben erhalten. Die Link-Abfrage schließt den aktuellen Teilnehmer zusätzlich aus. Abrechnung und Datenmodell bleiben unverändert.
