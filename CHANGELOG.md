# Änderungen · Der Odentaler

## 3.4

- Zeigt Preise, Guthaben und Belege in Token. Neue Preise und Aufladungen sind in halben Token möglich. Bereits gespeicherte Werte bleiben exakt erhalten.
- Erzeugt bei der Geräteregistrierung einen QR-Code für HTTPS-Adresse und Gerätecode. Die Android-App kann den Code bei der Servereinrichtung lesen.
- Kopiert Veranstaltungen mit Einstellungen und Produkten. Löschen ist für Veranstaltungen ohne Guthaben oder Buchungsnachweise und für Produkte ohne Verkaufspositionen möglich. Für historische Daten steht Deaktivieren zur Verfügung.

## Backend 3.3

- Browser-Verwaltung unter `/admin` für Veranstalter, Veranstaltungen, Geräte, Produkte und PINs.
- Separates globales Admin-Passwort, HTTPS-Konfiguration und Schutz für Formularaktionen. Geräteschlüssel werden nach der Registrierung einmal angezeigt.

## Entwicklungsversion

- Analysiert den Android-Workspace und den mitgelieferten Flask-Archivstand. Dokumentiert Schnittstellenabweichungen und Anforderungen an die Datenübernahme.
- Verbindet Android mit Flask/PostgreSQL über /v1. Bucht Aufladungen, Teilauszahlungen und Warenverkäufe in Cent mit festgehaltenem Buchungsergebnis und historischen Stückpreisen.
- Ergänzt serverseitige Bereichsanmeldung, getrennte Kassen-/Admin-PINs, Gerätesperre und verschlüsselte Ablage des Geräteschlüssels. Erfordert Android 7.0 (API 24) für den automatischen Schutz von Google Play.
- Ergänzt NFC-A und Bluetooth-HID, responsives Material-3-Grundlayout, Wein-/Mobilschalter, Abrechnung und CSV.
- Liefert Docker Compose mit TLS, versionierte Datenbankmigration, CLI-Verwaltung und automatisierte Android-/PostgreSQL-Tests.
