# Der Odentaler

Selbst gehostetes Kassen- und Cashless-System für das Festkomitee Bergische Jecken e. V. und weitere Veranstalter. Android-Geräte arbeiten per HTTPS im lokalen WLAN mit einem gemeinsamen Flask-/PostgreSQL-Backend.

**Stand: Entwicklungsversion für isolierte Tests.** Die App setzt Android 7.0 (API 24) voraus und verwendet den versionierten Buchungsdienst. Kasse und Theken unterstützen Bargeldaufladung, Teilauszahlung und Warenkörbe. Wein- und Mobilbereich werden pro Veranstaltung freigeschaltet. Administration bietet Bereichsschalter, Abrechnung und CSV. Weitere Verwaltung erfolgt teilweise über die Server-CLI. Vor einer Freigabe für einen Event sind die offenen Nachweise in [TESTING.md](TESTING.md) und eine freigegebene Migration für Bestandsdaten erforderlich.

## Einstieg

1. Öffne das Projekt in Android Studio. Installiere JDK 17, Android SDK 36 und Gradle 8.13. Der Checkout enthält die Wrapper-Einstellungen. Verwende eine installierte Gradle-Distribution für den Kommandozeilenbuild.
2. Führe `gradle :app:assembleDebug :app:testDebugUnitTest` aus. Die Debug-APK liegt in `app/build/outputs/apk/debug/`.
3. Starte ein getrenntes Backend nach [DEPLOYMENT.md](DEPLOYMENT.md). Richte eine Veranstaltung und ein Testgerät ein und hinterlege auf dem Gerät den HTTPS-Endpunkt und dessen Geräteschlüssel.
4. Führe die Freigabetests mit Testarmbändern und Testdaten durch.

## Verzeichnisse und Dokumente

- `app/` enthält Android-Code, Oberflächen und Android-Tests.
- `backend/` enthält Flask, Ledger, SQL-Migrationen und PostgreSQL-Integrationstests.
- `deploy/` enthält die TLS-Konfiguration. `compose.yaml` definiert die lokale Infrastruktur.
- [Bestandsaufnahme](PROJECT_AUDIT.md) und [Entwicklungsplan](IMPLEMENTATION_PLAN.md)
- [Architektur](ARCHITECTURE.md), [API](API_DOCUMENTATION.md) und [Datenbankschema](DATABASE_SCHEMA.md)
- [Betrieb und Wiederherstellung](DEPLOYMENT.md), [Testnachweise](TESTING.md) und [Änderungen](CHANGELOG.md)
