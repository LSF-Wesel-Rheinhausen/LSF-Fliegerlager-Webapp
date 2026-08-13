# Mobile overlay scroll lock and safe navigation

- Sperrt den Seitenhintergrund zentral bei allen offenen nativen Dialogen und erhält die Scrollposition.
- Sichert interne Dialog-Scrollbereiche sowie mobile Kiosk-Touchflächen oberhalb der Safe Area.
- Ergänzt `viewport-fit=cover`, den Cache-Bump auf Version 33 und deterministische Browser-Regressionstests.
- Verankert die mobile Navigation an `bottom: 0`, deckt die Bottom-Safe-Area mit ihrem Hintergrund ab und schützt seitliche Safe-Areas für Touch-Ziele.
