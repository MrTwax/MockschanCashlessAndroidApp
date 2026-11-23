# Bestandsaufnahme · Der Odentaler

## Untersuchte Quellen

- Android-Studio-Workspace `MockschanCashless`, App-ID `com.mockschan.cashless`, Modul `:app`. Der Arbeitsbaum enthielt bereits Änderungen an Gradle, MainActivity, Administration, Launcher-Ressourcen und IDE-Dateien sowie Release-Artefakte. Sie sind Teil der Ausgangslage.
- Bereitgestelltes Archiv `cashmockless-pi-stable.zip`, insbesondere `PiBackend/app.py`, `Dockerfile`, `docker-compose.txt`, `requirements.txt` und zwei ältere Android-Quellen. Der geöffnete Workspace enthielt zu Beginn keinen Serverquellcode.
- Quellcodebefunde beschreiben vorhandene Implementierungen. Ein produktives Backend, Bestandsdaten, Geräte und physische Armbänder wurden für die Bestandsaufnahme nicht verwendet.

## Android

| Teil | Vorhanden | Befund |
| --- | --- | --- |
| Einstieg | Kotlin, eine MainActivity, AppCompat und XML, Startseite, Thekenauswahl | Die Activity verwaltet Navigation, UI, NFC, Netzwerk und Buchungen gemeinsam. Kein Compose und keine getrennten State- oder Repository-Klassen. |
| Kasse | NFC-Lookup, Aufladedialog, vollständige Rückzahlung | Anmeldung durch lokale feste PIN. Scan setzt veränderliche globale UID, bevor das Guthaben bestätigt ist. Bestätigungsdialog nutzt die jeweils aktuelle UID. Alte Antworten können neue Scans überschreiben. Aufladung/Rückzahlung zeigen auch bei HTTP-Fehlern Erfolg. Kein Zahlungsarten- oder Bonmodell. |
| Theken | Getränke, Essen, optional Wein, Mengen, Gesamtbetrag, Zahlungs- und Bestellanzeige | Weinoption nur in Gerätepräferenzen. Kein Mobilbereich. Client verwendet Double und liefert Preise mit. Katalog, Scan und Kontostand haben getrennte asynchrone Callbacks. Eine feste POS-ID gilt für alle Installationen. Ablauf nach 120 Sekunden lässt Warenkorb/Ansicht teilweise stehen. Beleg kann nach Rückkehr aus HTTP aus veränderlichen UI-Daten entstehen. |
| Administration | Produktliste, Bearbeitung, Guthabenliste, Summen/Verlauf und lokale Einstellungen | Lokale feste Admin-PIN, gemeinsam genutzter API-Key in SharedPreferences, App-Backup an. Einige Schreibaktionen zeigen ungeprüften Erfolg. Globaler Guthaben-Reset ist im UI erreichbar. Veranstalter, Veranstaltungen, Benutzerrollen, Gerätewiderruf und CSV fehlen. |
| NFC | Interner ReaderMode für NFC-A, UID als Hex | Auf allen Ansichten aktiv. Manuelle UID-Eingabe auf der Startseite. Kein zentraler Scannervertrag und kein HID/Serial/Herstelleradapter. UID ist klonbar. |
| Oberfläche | 11 XML-Layouts, Launcher-Assets, Farben | Listen, Reihen und Dialoge mit festen Höhen und Inline-Texten. Keine separaten Tabletansichten. Kasse und Thekenauswahl ohne durchgehend scrollbar angelegten Inhalt. |
| Netzwerk | OkHttp, Standard `https://cashless.local`, eingebettete öffentliche CA für diesen Host | Konfiguration erlaubt HTTP und zeigt den vorhandenen API-Key. Fehlgeschlagene Guthabenabfragen können als 0 erscheinen. Keine persistierte Vorgangs-ID oder Wiederabfrage. |
| Build und Tests | minSdk 21, compile/target 35, JDK 17, AGP 8.1.1, Kotlin 1.9.10, Gradle-Einstellung 8.5 | Doppelte Varianten dreier Bibliotheksabhängigkeiten, auffällige Kotlin-Zeile in der Produktansicht, fehlendes Release-ProGuard-Regelwerk und unvollständiger Wrapper. Der Ausgangsstand baute mit einer separat installierten Gradle-8.5-Distribution erfolgreich. Der Unit-Test-Task meldete NO-SOURCE. |

## Schnittstellenvergleich

| Funktion | Aktueller Android-Client | Flask im gelieferten Archiv |
| --- | --- | --- |
| Guthaben | `GET /balance/{uid}` | Vorhanden. Unbekannte UID liefert 0. |
| Aufladung | `POST /load` mit UID und Betrag | Vorhanden. |
| Rückzahlung | `POST /refund` mit UID | Vorhanden. Zahlt vollständiges Guthaben zurück. |
| Warenverkauf | `POST /charge` mit Betrag, Positionen und `X-Scan-Session` | Erwartet UID und Betrag. Keine Positionsbuchung. |
| Scan | `POST /pos/scan`, `GET /pos/products`, `POST /pos/cancel` | Fehlt. |
| Katalog | `GET/POST /products`, `PUT/DELETE /products/{id}` | Vorhanden, mit Preis, Bild und Theken-Flags. |
| Verwaltung | `GET /users?nonzero=1`, `DELETE /reset`, `GET /admin/summary`, `GET /admin/history`, `POST /admin/reset` | Benutzerliste und globaler Reset vorhanden. Drei Admin-Routen fehlen. |

App und Archiv bilden damit keinen durchgängig kompatiblen Thekenbetrieb. Eine anderweitig betriebene Backend-Version ist möglich. Sie wurde nicht vorgelegt oder kontaktiert.

## Backend und Daten

Flask/SQLAlchemy verwalten `User(uid,balance)` und `Product(id,name,price,image,drinks,food,wine)`. Beträge sind Float. PostgreSQL 15 ist im Archiv per Compose vorgesehen, SQLite als Fallback im Code. Initialisierung legt Tabellen ohne versionierte Migration an. Es gibt keine wirksame Rollenprüfung, Journaltabellen, Idempotenz, mandantenbezogene Fremdschlüssel oder Sperrung widersprüchlicher paralleler Buchungen. Das Compose-Archiv verweist auf ein vorgebautes ARM64-Image, enthält Zugangskonfiguration, hat keine eigenen Healthchecks und definiert TLS sowie persistente Uploads nicht vollständig. Die Konfiguration wird nicht als Vorlage übernommen.

Historische Android-Versionen behandeln Werte als Token, inklusive Nachkommabeträgen in Modell und Preisen. Eine belegte EUR-Umrechnung gibt es in den untersuchten Quellen nicht. Vor der Migration sind Preise und Guthaben aus einem freigegebenen Export auf gültiges Raster, eindeutige UID-Zuordnung und exakte Abbildung in Ganzzahleinheiten zu prüfen. Altbestände sind als belegte Eröffnungsbuchungen zu importieren. Die vorhandene Datenstruktur liefert keinen rekonstruierbaren Einzelumsatzverlauf.

## Erhalt und Modernisierung

Kotlin, App-ID, XML-Layouts, Android-NFC und OkHttp können für den Einstieg erhalten bleiben. XML erlaubt eine schrittweise Integration im bestehenden Betriebsablauf. Buchungen und Scan-Zustand werden zuerst aus der Activity herausgelöst. Flask/PostgreSQL bleiben Grundlage. Der abgesicherte Pfad erhält einen versionierten Vertrag, weil der ausgelieferte Archiv-Server und die geöffnete App unterschiedliche Altverträge haben.
