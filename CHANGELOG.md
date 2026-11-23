# Änderungen · Der Odentaler

## Entwicklungsversion

- Analysiert den Android-Workspace und den mitgelieferten Flask-Archivstand. Dokumentiert Schnittstellenabweichungen und Anforderungen an die Datenübernahme.
- Verbindet Android mit Flask/PostgreSQL über /v1. Bucht Aufladungen, Teilauszahlungen und Warenverkäufe in Cent mit festgehaltenem Buchungsergebnis und historischen Stückpreisen.
- Ergänzt serverseitige Bereichsanmeldung, getrennte Kassen-/Admin-PINs, Gerätesperre und verschlüsselte Ablage des Geräteschlüssels. Erfordert Android 7.0 (API 24) für den automatischen Schutz von Google Play.
- Ergänzt NFC-A und Bluetooth-HID, responsives Material-3-Grundlayout, Wein-/Mobilschalter, Abrechnung und CSV.
- Liefert Docker Compose mit TLS, versionierte Datenbankmigration, CLI-Verwaltung und automatisierte Android-/PostgreSQL-Tests.
