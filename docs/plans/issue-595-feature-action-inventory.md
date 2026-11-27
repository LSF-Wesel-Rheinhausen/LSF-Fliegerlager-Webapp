# Issue #595: Nutzeraktionen und Funktionsschalter

Die bekannten Schalter liegen pro Lager in `CampFeatureOverride`. Fehlende Overrides für Katalog-IDs bedeuten „an“; unbekannte IDs sind gesperrt. Änderungen wirken nur auf Teilnehmeraktionen. Lagerverwaltung, bestehende Datensätze und finanzielle Auswertungen bleiben erhalten.

| Schalter | Teilnehmeraktionen | Serverseitige Prüfung | Erhaltene Wege |
| --- | --- | --- | --- |
| `profile` | Stammdaten der eigenen Person ändern | Private und zentrale Profilroute: POST verweigert; GET zeigt deaktivierte Formularfelder | Profil bleibt lesbar; Anmeldung, PIN, Wiederherstellung und Admin-Korrektur |
| `family` | Familie/Begleitpersonen anlegen, PIN setzen, entfernen; Familienprofil ändern | Home-Aktionen und Familienprofil-POST; Familienprofil-GET bleibt lesbar | Bestehende Familienbuchungen, Abrechnung, Anmelden, eigene PIN und PIN-Recovery |
| `partners` | Partner einladen und Einladung annehmen; Partnerkonten für Buchungen/Check-in verwenden | Partnerroute prüft Invite/Accept; gemeinsame Zielauflösung liefert bei Sperre keine Partner; Buchungs- und Attendance-Ziele werden dadurch eingeschränkt | Partnerhistorie, Einladung ablehnen, bestehende Vollmacht widerrufen, Admin-Verwaltung und Abrechnung |
| `meals` | Abendessen, Frühstück und Snacks buchen oder Essensanmeldungen zurücknehmen | Home-Aktionen prüfen Preisregel/Charge; beide Kioskmodi verwenden denselben Handler | Bestehende Buchungs- und Abrechnungsdaten bleiben erhalten; vorhandene Vorbestellungsflags bleiben zusätzliche, unveränderte Bedingungen |
| `drinks` | Getränke buchen und kürzlich gebuchte Getränke stornieren | Home-Aktionen prüfen Preisregel/Charge; beide Kioskmodi verwenden denselben Handler | Abrechnung und Historie bleiben erhalten |
| `attendance` | Check-in sowie An- und Abreisedaten pflegen | Beide Attendance-Aktionen im gemeinsamen Kiosk-Handler | Admin-Anwesenheitsmatrix, historische Anwesenheit und Korrekturen |
| `shifts` | Dienste ansehen, buchen, abgeben und tauschen | Private und zentrale Dienstplanroute vor GET/POST | Admin-Schichtplanung und Finanz-/Diensthistorie |
| `donations` | Spenden im Kiosk eintragen | Home-POST prüft vor Buchung; Dialog im Kiosk ausgeblendet | Bestehende Spendendatensätze und Admin-Finanzverwaltung |
| `expenses` | Gemeinschaftsauslage beantragen | Private und zentrale Formularroute vor GET/POST | Bereits eingereichte Auslagen, Status, Belege, Admin-Prüfung und Abrechnung |
| `self_registration` | Neues Teilnehmerkonto beantragen | Private und zentrale Registrierungsroute; Login zeigt das Formular nur bei Freigabe | Bestehende Kontoanmeldung, Kontowiederherstellung und Admin-Freigabe |
| `notifications` | Optionale Teilnehmer-Pushes erhalten und neue Pushes konfigurieren/testen | Queue prüft Master- und Quellfunktion; Versand prüft erneut; Ausschalten beendet offene optionale Pushes terminal | Entfernen/Widerrufen registrierter Geräte, Account-Security- und Recovery-Pushes, Admin-Benachrichtigungen |

`Camp.show_kiosk_invoices` bleibt die maßgebliche Rechnungsfreigabe. `allow_breakfast_prebooking_before_camp` und `allow_dinner_prebooking_before_camp` bleiben mit ihren bestehenden Werten erhalten und wirken zusätzlich zum Essensschalter. Die Essens-Reminderfelder steuern vorhandene Teilnehmer-/Essens-Pushes; eine separate Teilnehmer-Reminder-E-Mail-Routine existiert nicht. Settlement-, manuelle Admin-Informations- und Recovery-E-Mails bleiben eigene Admin-/Sicherheitswege.

Login, Logout, rechtliche Informationen, PIN ändern/setzten, PIN- und Kontowiederherstellung, Ablauf/Widerruf von Kiosk-Zugriffen, Ablehnung/Widerruf vorhandener Partnerfreigaben und Finanz-/Historienansichten sind nicht abschaltbar. Technische PWA-Ressourcen sind keine Teilnehmeraktionen.
