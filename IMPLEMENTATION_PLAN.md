# Entwicklungsplan · Der Odentaler

Die Reihenfolge priorisiert eindeutige Buchungsergebnisse und sichere Wiederaufnahme. Jeder Schritt benötigt die zugehörigen Tests bevor er für einen Eventbetrieb freigegeben werden kann.

| Paket | Umsetzung | Abnahme |
| --- | --- | --- |
| 1 · Build und Altclient | Vorhandene Android-Basis wieder bauen. Doppelbedienung verhindern. Scans und Antworten an den richtigen Vorgang binden. Mehrdeutige Ergebnisse dauerhaft sichtbar halten. | Debug-APK und ausgeführte Unit-Tests. Zwei schnelle Eingaben erzeugen höchstens einen Request. Ein unklarer Ausgang bleibt auch nach Neustart blockiert. |
| 2 · Buchungskern | Flask und PostgreSQL mit versioniertem Vertrag, exakten Einheiten, unveränderlichem Journal, Positionspreisen, Mandant/Event/Gerät und Idempotenz pro Vorgang. | Reale PostgreSQL-Tests für Aufladung, Auszahlung, Einzel- und Mehrproduktverkauf, unzureichendes Guthaben, Antwortverlust/Wiederholung, parallele Geräte, Isolation und fehlende Rolle. |
| 3 · Scanner und Sitzungen | Gemeinsame Validierung für internes NFC und explizit aktivierbares Bluetooth-HID. Sitzungsablauf auf monotone Zeit und Backend stützen. Geräteabhängige Serial-/SDK-Adapter nach Modellauswahl. | Unit-Tests für doppelte, fehlerhafte und unvollständige Scans sowie Scannerwechsel. Abgelaufene und abgebrochene Warenkörbe sind gesperrt. Internes NFC und konkretes externes Modell durch Hardwaretest. |
| 4 · Android an versionierte API anbinden | Repository mit dauerhafter Vorgangs-ID, Ergebnisabfrage, Schlüsselablage über Android Keystore und Zustandsmodell für Kasse/Theken. Geräteanmeldung und serverseitige Rollen/PIN mit Hash, Rate-Limit und Wechselpflicht. | Neustart und WLAN-Ausfall nach Commit lassen sich mit derselben ID klären. Direktaufrufe und widerrufene Geräte werden abgewiesen. Erneuter Scan startet nach bestätigtem Ergebnis. |
| 5 · Bedienung und Bereiche | Material 3, adaptive XML-Layouts, direkte Bereiche, strukturierte Produktkacheln, Warenkorb, Beträge, Bar- und getrennt bestätigte Kartenzahlung. Wein/Mobil/Bon über Eventkonfiguration. | Kleine/große Fenster, Hoch-/Querformat und große Schrift geprüft. Gerät sieht nur erlaubte Bereiche. Wein und Mobil einzeln testbar. Bons und Guthaben bleiben getrennte Vorgänge. |
| 6 · Administration und Berichte | Veranstalter, Veranstaltungen, Katalog, Kategorien, Geräte, PIN/Benutzer, historische Preis-Snapshots, Umsatz, Verbindlichkeiten, Storno, Kassenabschluss und CSV. | Eventwechsel, Mandantentrennung, Preisänderung, Kassenabschluss und Export mit Januar/Monatswechsel sowie Änderungsjournal getestet. |
| 7 · Selfhosting und Abnahme | Reproduzierbare Testumgebung, TLS, Secrets, Healthchecks, Backups und Wiederherstellung. Explizite Datenmigration mit Vorher-/Nachher-Abgleich. | Frischer Start und Restore in isolierter Umgebung, vollständige Testmatrix, dokumentierter belastbarer Mehrgeräte-Test sowie Geräte- und Bedienabnahme. |

## Schnittstellen- und Migrationsentscheidungen

- Die bestehende App-ID und der geprüfte Altcode bleiben erhalten. Ein neuer API-Vertrag wird separat versioniert und in einem freigegebenen Testsystem integriert.
- Beträge werden als ganzzahlige Basiseinheiten geführt. Geld, verkaufte Bons, ausgestelltes Guthaben und konsumierte Produkte sind fachlich getrennt. Die Altbestandsumrechnung erfordert ein freigegebenes Verhältnis und einen vollständigen Abgleich.
- Bei Netzverlust wird keine neue Buchung angenommen. Ein gesendeter Vorgang bleibt offen, bis er mit derselben Vorgangs-ID geklärt werden kann. Beim Altvertrag ohne Statusabfrage muss die Kasse den Vorgang mit der Abrechnung abgleichen.
- Scanner liefern Kennung und Herkunft. Zahlungsberechtigungen kommen aus der API. UID-basierte Medien können später durch kryptografisch authentifizierte Medien ersetzt werden.
- Historische Kontostände werden als bestätigte Eröffnungsbuchungen übernommen. Ein Datenexport und Restore-Probelauf gehen jeder freigegebenen produktiven Migration voraus.

## Zwischenstand und nächste Arbeitspakete

1. **Implementiert.** Android nutzt /v1 mit gerätespezifischem Keystore-Zugang, Bereichsanmeldung, zeitlich befristetem Scan, expliziter Buchungsbestätigung und Wiederaufnahme über persistierte Vorgangs-IDs. Flask und PostgreSQL sichern Guthabenänderungen, Preise und Buchungsjournal gemeinsam ab. NFC-A und HID, Material-3-Ansichten sowie der Grundbericht mit CSV sind vorhanden.
2. **Als Nächstes Ende-zu-Ende prüfen.** In einem LAN-Testaufbau mit passender CA eine Testveranstaltung einrichten. Mit mindestens zwei Android-Geräten alle Kassen-/Thekenpfade, Prozessabbruch nach POST, die Sichtbarkeit optionaler Bereiche und den Wechsel zwischen internem NFC und konkretem HID-Leser abnehmen.
3. **Verwaltung vervollständigen.** Ereignis- und Gerätewechsel, Veranstalter-, Katalog-, Benutzer- und PIN-Verwaltung im Android-Admin, Rollen je Bediener sowie wiederherstellbare Geräteeinrichtung umsetzen. Zu prüfen sind auch die administrative Klärung bereits abgeschickter Buchungen nach Geräteverlust und Berechtigungsentzug.
4. **Abrechnung vervollständigen.** Storno als verknüpfte Gegenbuchung, fachlich festgeschriebene Kassenabschlüsse, Bonverkauf und explizit abgesicherte Zahlungsarten implementieren. Kartenzahlungen erst nach Auswahl und Test des Zahlungsprozesses freischalten.
5. **Bestandsdaten übernehmen.** Freigegebenen Export und verbindlichen Tokenkurs beschaffen, Import der Eröffnungsbuchungen samt Summenabgleich schreiben und eine Umschaltung bei stillgelegtem Altbetrieb proben.
6. **Freigabe.** Android-UI- und Hardwareabnahme, Sicherheitsprüfung, Lasttest, getrennte Datenbankrollen sowie gesicherte Rotation und Wiederherstellung mit Testdaten nachweisen. Ergebnisse stehen in [TESTING.md](TESTING.md).
