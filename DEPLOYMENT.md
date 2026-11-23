# Installation und Betrieb · Der Odentaler

## Isolierter Testbetrieb

Voraussetzungen sind Docker Engine und Docker Compose, ein lokaler Linux-Host oder Docker Desktop zum Testen sowie freier Plattenplatz für Images, Datenbank und Sicherungen. Ersteinrichtung und Imagebau laden Abhängigkeiten. Das installierte System kann danach im lokalen Netz ohne Internet arbeiten.

1. Lege aus `.env.example` eine lokale `.env` an. Setze ein eigenes zufälliges hexadezimales Datenbankpasswort mit mindestens 32 Zeichen. Für Testdaten kann `ODENTALER_ENV=test` gesetzt werden. Standardmäßig lauscht TLS nur auf der Loopback-Adresse.
2. Starte die Datenbank und führe die Migration aus.

   ```sh
   docker compose -p odentaler-lokal up -d --wait db
   docker compose -p odentaler-lokal build api
   docker compose -p odentaler-lokal run --rm api flask --app odentaler migrate
   docker compose -p odentaler-lokal up -d --wait
   ```

3. Zeige die verfügbaren Verwaltungsbefehle an und lege eine Testveranstaltung sowie ein Testgerät an.

   ```sh
   docker compose -p odentaler-lokal exec api flask --app odentaler create-event --organizer "Testverein" --event "Probe" --device "Eingang"
   docker compose -p odentaler-lokal exec api flask --app odentaler register-device --event-id <event-id> --name "Theke 1" --area drinks
   docker compose -p odentaler-lokal exec api flask --app odentaler add-product --event-id <event-id> --name "Testgetränk" --price-cents 250 --area drinks
   docker compose -p odentaler-lokal exec api flask --app odentaler edit-product --event-id <event-id> --product-id <produkt-id> --inactive
   docker compose -p odentaler-lokal exec api flask --app odentaler configure-event --event-id <event-id> --scan-timeout-seconds 120 --topup-cents 500 --topup-cents 1000
   docker compose -p odentaler-lokal exec api flask --app odentaler change-pin --event-id <event-id> --area cash
   docker compose -p odentaler-lokal exec api flask --app odentaler revoke-device --device-id <device-id>
   ```

4. Öffne in der App die Servereinrichtung. Übertrage den Geräteschlüssel nur an dieses Gerät. Teile Funktionsrechte je Gerät auf. Widerrufe einen verlorenen Zugang serverseitig.
5. Stelle die Verbindung zum Netzbetreiber her und prüfe `GET /healthz` mit einem Client, der der lokalen CA vertraut. Erwartet wird HTTP 200 bei erreichbarer Datenbank mit installiertem Schema.

## HTTPS im Veranstaltungsnetz

Setze `ODENTALER_BIND_ADDRESS` explizit auf die LAN-IP des Hosts und richte einen im lokalen Netz auflösbaren DNS-Namen für `ODENTALER_HOST` ein. Der Android-Client prüft Hostname und Zertifikatskette. Caddy erstellt im Testaufbau eine lokale CA. Deren öffentlicher Teil liegt im Caddy-Container unter `/data/caddy/pki/authorities/local/root.crt`. Für Android muss der Build dem passenden öffentlichen CA-Zertifikat und Namen vertrauen. Das vorhandene Trust-Profil enthält ein früheres CA-Zertifikat für `cashless.local`. Beim Einsatz einer neuen CA ersetze die öffentliche Ressource `app/src/main/res/raw/local_ca.crt` und passe bei abweichendem Host den Eintrag in `network_security_config.xml` an. Der private CA-Schlüssel verbleibt im TLS-Datenvolume beziehungsweise dessen gesicherter Ablage. Schalte den Zertifikatsabgleich auf keinem Gerät ab.

Im LAN wird nur HTTPS veröffentlicht. Das Datenbank- und das API-Backend liegen im Compose-Netz. Die Entwicklungsumgebung verwendet eine gemeinsame Datenbankrolle für Migration und API. Vor produktiver Freigabe müssen getrennte DDL- und Runtime-Rechte, Rotation, Firewall und Backup-Berechtigungen geprüft werden.

## Sichern und wiederherstellen

- Sichere PostgreSQL regelmäßig mit `pg_dump` im Custom-Format, die TLS-Daten inklusive lokalem CA-Schlüssel getrennt und verschlüsselt. Lege Sicherungen auf einen separaten Datenträger. Der Dump enthält personenbezogene und sicherheitsrelevante Daten.
- Beispiel für eine Linux-Sicherung in ein bereits geschütztes Verzeichnis

  ```sh
  docker compose -p odentaler-lokal exec -T db pg_dump -U odentaler -d odentaler -Fc > odentaler.dump
  ```

- Wiederherstellung zunächst in einem frischen Compose-Projekt und in einer leeren Datenbank. Beispiel mit dem isolierten Projekt `odentaler-restore`. Starte für den Restore nur `db` mit eigener Konfiguration.

  ```sh
  docker compose -p odentaler-restore up -d --wait db
  docker compose -p odentaler-restore exec -T db pg_restore --exit-on-error -U odentaler -d odentaler < odentaler.dump
  ```

- Nach dem Restore Migrationen prüfen und Probeläufe für Kontosalden, Journal, Wiederabfrage und Gerätezugänge durchführen. Vor einer produktiven Wiederaufnahme sind Wartungsfenster und Abgleich seit der letzten Sicherung erforderlich.
