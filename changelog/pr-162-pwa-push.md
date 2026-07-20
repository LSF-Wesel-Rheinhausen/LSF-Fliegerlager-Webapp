# PWA und Push-Benachrichtigungen

- Verwaltung, private Teilnehmergeräte und zentrale Kiosk-Tablets sind als getrennte PWAs installierbar.
- Private Kiosk-Sessions bleiben bis zum Schließen der App aktiv; `/central/kiosk/` erzwingt weiterhin den kurzen Auto-Logout.
- Optionale Push-Benachrichtigungen informieren über Dienste, Buchungen, Essensfristen, Auslagen und offene Verwaltungsaufgaben.
- Eine Datenbank-Outbox und ein eigener Compose-Worker übernehmen Wiederholungen und zeitgesteuerte Erinnerungen.
- Stornos verknüpfter Buchungen nennen den tatsächlich handelnden Teilnehmer und benachrichtigen die andere Person.
- Der Push-Worker nutzt neben dem internen Datenbanknetz ein ausgehendes Netzwerk für die Push-Anbieter.
