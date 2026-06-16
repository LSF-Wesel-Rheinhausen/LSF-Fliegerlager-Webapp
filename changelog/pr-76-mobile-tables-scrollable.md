# Mobile Tabellen Scrollbar

## Zusammenfassung

- Mobile Tabellen bleiben seitlich scrollbar.
- Tabellenzellen bekommen `white-space: nowrap`, damit Spalten keine unnötigen Umbrüche erzeugen.
- Links in Tabellen dürfen weiterhin sauber umbrechen.
- Body-Overflow bleibt verhindert (`table { display: block; width: 100%; max-width: 100%; overflow-x: auto; }`).

## Tests

- E2E Tests bestanden.
- Layout auf mobilen Ansichten ist stabil ohne horizontales Scrollen der ganzen Seite.
