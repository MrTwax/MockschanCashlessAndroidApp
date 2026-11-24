# Datenbankschema · Der Odentaler

Der neue PostgreSQL-Bestand wird durch [001_core.sql](backend/migrations/001_core.sql) angelegt. Der Migrationslauf erfasst angewendete Migrationen. Die Tabellen für den neuen API-Vertrag sind separat vom alten Flask-Schema.

| Tabelle | Zweck und Integritätsregeln |
| --- | --- |
| `organizers`, `events`, `event_areas` | Veranstalter, Veranstaltung, verfügbare Bereiche, Scan-Frist und Aufladevorschläge. |
| `devices`, `device_areas` | Gerätezuteilung je Veranstaltung samt Hash des Geräteschlüssels, letzter Aktivität und Widerruf. |
| `pin_roles`, `operator_sessions` | Gesalzene PIN-Hashes, Fehlversuche und befristete Sitzungen im Geräte-/Bereichskontext. |
| `accounts` | Guthabenkonto mit zusammengesetztem Schlüssel aus Veranstaltung und NFC-UID. Ganzzahlige Token-Einheiten und nichtnegatives Guthaben. |
| `scans` | Zeitlich befristeter Scan mit Bereich, Gerät, UID und Ablauf. Höchstens ein offener Scan pro Gerätekontext. |
| `products` | Veranstaltungsbezogener Katalog mit Preis in ganzzahligen Token-Einheiten, Kategorie, Bereichen und Sortierung. |
| `booking_requests` | Idempotenzschlüssel je Gerät und Veranstaltung, Nutzlast-Fingerabdruck und unverändertes Ergebnis eines wiederholten Vorgangs. |
| `transactions` | Journal mit Betrag, Art, Zahlungstyp, Datum, Konto, Scan, Geräte-/Bereichs-/Sitzungsbezug und Guthaben vor/nach der Buchung. |
| `sale_items` | Beim Verkauf festgehaltene Produkt-ID, Produktname, Menge und Stückpreis. |

Mandanten- und Ereigniskontext werden durch API-Abfragen und zusammengesetzte Fremdschlüssel durchgesetzt. Die Kontosperre serialisiert konkurrierende Zugriffe. Journalzeilen und Verkaufspositionen sind gegen UPDATE, DELETE und TRUNCATE per Trigger geschützt. Datenbankadministratoren und berechtigte Migrationen liegen außerhalb dieser technischen Grenze.

## Token-Einheiten

Die vorhandenen v1-Spalten mit Suffix `_cents` speichern ab Version 3.4 die gleichen Ganzzahlwerte wie zuvor. 100 Einheiten werden als 1 Token angezeigt. Es gibt keine Umrechnung oder Rundung bestehender Werte. Der Import aus dem früheren Pi-Backend bleibt separat.

## Datenübernahme

1. Freigegebenen Altbestand sichern. Für die Probe wird ein logischer Export in einer getrennten Datenbank wiederhergestellt.
2. Veranstalter, Veranstaltungen, Thekenzuordnung, eindeutige UIDs und Produktpreise im Export abgleichen. Das Umrechnungsverhältnis von Token zu Cent schriftlich festlegen. Bei einem halben Token muss das Produkt aus Verhältnis und Wert exakt in Cent darstellbar sein.
3. Werte in Dezimaldarstellung übernehmen und Abweichungen, ungültige UIDs und Dubletten einzeln klären. Prüfsummen bilden, darunter Anzahl der Konten und Summe der Guthaben je Veranstaltung.
4. Ein versionierter Import für Eröffnungsbuchungen ist offen. Solange er fehlt, dürfen Altguthaben ausschließlich als getrennte Testdaten verarbeitet werden.
5. Vor einer späteren Umschaltung wird der Altverkauf angehalten, der Endexport abgeglichen und die neue Infrastruktur aus einer dokumentierten Sicherung wiederherstellbar gemacht. Gibt es nach Umschaltung neue Transaktionen, müssen die Journale vor einer Rückkehr abgestimmt werden.

Die Alttabellen liefern Kontostände und Preise. Fehlende historische Buchungspositionen lassen sich daraus nicht rekonstruieren.
