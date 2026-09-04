# Sichere administrative Dienstbesetzung

Administratoren können beim Bearbeiten eines Dienstes Teilnehmende und aktive
Begleitpersonen suchen, eintragen und austragen. Kapazitäts- und historische
Ausnahmen erfordern eine ausdrückliche Bestätigung; parallele Änderungen werden
erkannt und jede erfolgreiche Änderung wird datensparsam auditiert.

Die Bedienung funktioniert auch ohne JavaScript und bleibt auf mobilen Geräten
tastatur- und touchgerecht. Dienstzuordnungen zählen weiterhin unmittelbar zum
Dienstfortschritt und verändern keine Abrechnungsbeträge oder Snapshots.

Entfernungen benötigen immer eine ausdrückliche Bestätigung. Historische
Kapazitätsänderungen werden gesondert bestätigt und auditiert; Dienst-Audits
behalten auch nach einer Löschung die minimale Dienstreferenz. Admin- und
Kioskänderungen verwenden dieselbe Sperrreihenfolge, und abgewiesene
Eintragungen behalten die aktive Personensuche bei.

Direkte Kapazitätsabsenkungen unter die bestehende Besetzung werden an der
Modellgrenze blockiert; die Vorlagen-Generierung bewahrt diese Kapazität und
der bestätigte Admin-Override bleibt mit Revision und Audit unverändert.

Closes #578
