# Tests für Der Odentaler

Für Buchungs- und Wiederherstellungstests ausschließlich leere, entbehrliche Testdatenbanken und Testarmbänder verwenden. In der Testumgebung den Android-Client mit einem eigens eingerichteten Gerätecode verbinden.

## Automatisierte Tests ausführen

Android aus dem Projektverzeichnis mit JDK 17, Android SDK 36 und Gradle 8.13 bauen und testen. Die Ausgaben in `app/build/reports/tests/testDebugUnitTest/` zeigen die ausgeführten Tests.

```powershell
gradle :app:assembleDebug :app:testDebugUnitTest
```

Die PostgreSQL-Integrationstests aus `backend/` starten. `ODENTALER_TEST_DATABASE_URL` muss auf eine leere, entbehrliche PostgreSQL-Datenbank hinweisen. Die Tests führen die Projektmigrationen aus und legen eigene Datensätze an. Für den Datenbanknamen `odentaler_test` oder einen Namen wie `odentaler_test_lokal` wählen. Die Python-Abhängigkeiten und der Start von PostgreSQL sind in [DEPLOYMENT.md](DEPLOYMENT.md) beschrieben.

```powershell
python -m unittest discover -s tests
```

Bei fehlender Datenbankverbindung oder übersprungenen PostgreSQL-Tests gilt die Datenbankprüfung als offen. Für Ergebnisse eines Testlaufs Datum, Build, Datenbankversion sowie Anzahl bestandener, fehlgeschlagener und übersprungener Tests festhalten.

## Akzeptanzmatrix

Die Spalte „Nachweis“ beschreibt Tests auf Komponentenebene und noch notwendige Prüfungen. Ein automatisierter Backend-Test deckt den entsprechenden Android-Bedienablauf erst mit einem zusätzlichen UI- oder Gerätetest ab.

| Nr. | Testfall | Prüfkriterium | Nachweis |
| --- | --- | --- | --- |
| 1 | Guthabenaufladung | Betrag einmalig im Journal, Guthaben und Zahlungsart stimmen. | PostgreSQL-Integration, Android-Bedienablauf offen |
| 2 | Auszahlung | Teilbetrag und Restguthaben stimmen, Überschreitung wird abgewiesen. | PostgreSQL-Integration, Android-Bedienablauf offen |
| 3 | Einzelverkauf | Artikel und Preis stehen im Beleg, Guthaben sinkt genau einmal. | PostgreSQL-Integration, Android-Bedienablauf offen |
| 4 | Verkauf mehrerer Artikel | Mengen, Preise, Beleg und Guthaben ändern sich gemeinsam. | PostgreSQL-Integration, Android-Bedienablauf offen |
| 5 | Verkauf abbrechen | Abgebrochene Sitzung kann keine Buchung auslösen. | PostgreSQL-Integration, Android-Bedienablauf offen |
| 6 | Zu wenig Guthaben | Server lehnt den Kauf ab, Saldo und Journal bleiben konsistent. | PostgreSQL-Integration, Warnanzeige offen |
| 7 | Doppelter NFC-Scan | Identischer Scan wird gedämpft, wiederholte Scan-Anfragen behalten dieselbe offene Scan-Sitzung. | Android-Unit-Test und PostgreSQL-Integration, Hardware offen |
| 8 | Verbindungsabbruch während Buchung | Antwortverlust nach Commit ergibt einen offenen Status und erlaubt die Auflösung über denselben Schlüssel. | Simulierter Antwortverlust in PostgreSQL-Integration und Android-Unit-Test, echter WLAN-Unterbruch offen |
| 9 | Gleiche Transaktions-ID wiederholen | Gleicher Schlüssel liefert den ursprünglichen Ausgang, Payload-Wechsel wird abgewiesen. | PostgreSQL-Integration und Android-Unit-Test zur Wiederaufnahme, UI-Bedienablauf offen |
| 10 | Gleichzeitige Verkäufe auf verschiedenen Geräten | Bei Guthaben für genau einen Verkauf gelingt genau einer. | PostgreSQL-Integration, Lasttest offen |
| 11 | Veranstaltung wechseln | Geräteberechtigung, Produkte und Kundensitzung gehören zur gewählten Veranstaltung. | PostgreSQL-Integration, Android-Veranstaltungswechsel offen |
| 12 | Veranstalter trennen | Identische UID in verschiedenen Mandanten zeigt getrennten Saldo. | PostgreSQL-Integration |
| 13 | Fehlende Berechtigung | Ungültige Rolle und gesperrtes Gerät können keine unzulässige Aktion ausführen. | PostgreSQL-Integration, Anzeige in der App offen |
| 14 | Weintheke aktivieren und deaktivieren | Server berücksichtigt den Veranstaltungsstatus, Startseite übernimmt die Einstellung. | PostgreSQL-Integration, Android-Bedienablauf offen |
| 15 | Mobile Bedienung aktivieren und deaktivieren | Server berücksichtigt den Veranstaltungsstatus, Startseite übernimmt die Einstellung. | PostgreSQL-Integration, Android-Bedienablauf offen |
| 16 | Internen und externen Scanner wechseln | Beide Pfade liefern dieselbe UID, Teilframes überstehen einen Wechsel nicht. | Parser und Deduplizierung per Android-Unit-Test, physischer Wechsel offen |
| 17 | Nächster Kunde | Erfolg wird gezeigt, danach sind Warenkorb und Bandkontext leer. | Neuer Scan nach Buchung in PostgreSQL-Integration, Android-Bedienablauf offen |
| 18 | App-Neustart während Buchung | Offener Auftrag wird nach Neustart mit ursprünglichem Schlüssel zugeordnet. | Wiederherstellungsschlüssel per Android-Unit-Test, Prozessneustart auf Gerät offen |
| 19 | Preisänderung | Frühere Belegposition behält ihren ursprünglichen Preis. | PostgreSQL-Integration der Preis-Snapshots und des Berichts |
| 20 | Kassenabschluss und CSV-Export | Summen, Zahlarten, Verbindlichkeit und CSV stimmen mit Journal und Abschluss überein. | Bericht und CSV in PostgreSQL-Integration, verbindlicher Kassenabschluss offen |

## Gerätetest für NFC und Bluetooth-HID

1. Auf einem Gerät mit internem NFC und auf einem Tablet mit externem Lesegerät denselben Testveranstalter und dieselbe Testveranstaltung einrichten. Je Gerät einen separaten Testzugang verwenden.
2. Beim internen NFC zuerst mit deaktiviertem NFC prüfen, ob die App den Zustand verständlich meldet. Danach NFC aktivieren. Ein NFC-A-Armband mit 4, 7 oder 10 Byte UID in Kasse und Theke scannen. Aufladung, Auszahlung, Verkauf und Wechsel zum nächsten Gast prüfen.
3. Den externen Scanner über die Android-Bluetooth-Einstellungen als Tastatur koppeln. Im Scannerprofil das Präfix `OD`, die UID als Hexadezimalzeichen und Enter als Abschluss einstellen. Die Byte-Reihenfolge muss der Ausgabe des internen Lesers entsprechen. Im Administrationsbereich den externen NFC-Leser wählen.
4. Dasselbe Armband mit dem externen Scanner prüfen. Der Saldo und die Vorgänge müssen dem Konto des internen Scans entsprechen. Ein normales Tippen ohne Präfix, eine ungültige UID, ein unvollständiger Rahmen und ein Scannerprofil mit abweichendem Abschluss dürfen keinen Gast auswählen und keine Buchung auslösen.
5. Nach einem erkannten Scan Bluetooth trennen und Meldung prüfen. Nach Wiederverbindung muss ein vollständig neuer Scan funktionieren. Anschließend zum internen Leser zurückwechseln. Während einer PIN- oder Betragseingabe darf die Scanner-Eingabe keinen Gast wechseln.
6. Modell, Firmware, Android-Version, Profil und getestete Armbänder festhalten. Ein Android-Emulator kann die UID- und Rahmenlogik ergänzend prüfen. Physische NFC-Kopplung, Reichweite und Bluetooth-Wiederverbindung erfordern reale Geräte.

Externes HID wird von Android wie eine Tastatur bereitgestellt. Die App kann die Trennung eines bereits erkannten Lesers melden, sobald Android das Eingabegerät entfernt. Für Bluetooth-Serial und herstellerspezifische SDKs fehlen Gerät und Protokollspezifikation.

## Bedienung und Belastung

- Hoch- und Querformat auf Smartphone und Tablet, jeweils bei normaler und erhöhter Schriftgröße. Startseite, Kasse, alle Theken, Einstellungen und Fehlermeldungen prüfen. Bei 600 dp Fensterbreite muss die Theke Produkte und Zahlungsbereich nebeneinander zeigen. Darstellung, Fokus und Bedienbarkeit anhand von Screenshots des ausgeführten Builds festhalten.
- WLAN vor dem Senden, nach einem bestätigten Datenbank-Commit und während der Statusabfrage unterbrechen. Nach jeder Wiederherstellung müssen sichtbarer Status, Journal und Guthaben übereinstimmen.
- Belastung mit mehreren Geräten über längere Zeit prüfen. Die parallelen Integrationstests stellen eine einzelne Kollision nach. Dauerlast, Verhalten auf dem Zielserver und die Bedienbarkeit mit Testpersonal bleiben eigene Abnahmen.

## Protokoll der tatsächlichen Testläufe

- Gradle 8.5 mit JDK 17 und SDK 35. `:app:assembleDebug :app:testDebugUnitTest :app:assembleRelease` erfolgreich. Zwölf JUnit-Tests für Buchungsschutz, Wiederaufnahme, Betragsparser und Scanner. Release-Artefakt ohne Produktionssignatur.
- Android-Emulator Medium Phone mit API 36. Debug-APK kalt gestartet, Startansicht und Geräteverbindung geöffnet und als Screenshot im IDE-Testlauf erfasst. Statusleistenkontrast und Material-Schaltflächen nach Korrektur erneut visuell geprüft.
- PostgreSQL 15 im entbehrlichen Testcontainer. 14 Integrationstests bestanden, einschließlich Bericht, CSV und Verwaltung per CLI.
- Separater Docker-Compose-Test. Datenbank, API und lokaler TLS-Proxy gestartet. Migration zweimal ausgeführt, HTTPS-Gesundheitsprüfung mit Test-CA erfolgreich, Berichtsabruf ohne Anmeldung mit HTTP 401 abgewiesen. PostgreSQL-Dump in eine leere Testdatenbank eingespielt und den Testdatensatz sowie die Migration wiedergefunden.
- Vollständige Android-Buchungs- und Wiederanlaufabläufe gegen die Test-API sowie NFC, Bluetooth-HID-Hardware, Tablet-/Großschrift-Darstellung und Dauerlast sind offen.
