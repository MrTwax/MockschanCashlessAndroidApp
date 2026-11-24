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
5. Öffne vom selben WLAN aus `https://<Serveradresse>/healthz` mit einem Client, der dem Serverzertifikat vertraut. Erwartet wird HTTP 200 mit `{"status":"ok"}`. Prüfe außerdem `/v1/bootstrap`. Ohne Geräteschlüssel ist hier HTTP 401 zu erwarten. HTTP 404 weist auf eine falsche Adresse, eine falsche Proxy-Route oder einen älteren Server hin.

In der App unter „Server einrichten“ die HTTPS-Basisadresse ohne `/v1` und den ausgegebenen Schlüssel des jeweiligen Geräts eingeben. „Verbinden“ überprüft die Daten und öffnet bei Erfolg die freigegebenen Bereiche. Der alte API-Key des Pi-Servers ist kein Geräteschlüssel der neuen API. Für „Einstellungen / Administration“ muss das Gerät den Bereich `admin` zugeteilt bekommen. Die Admin-PIN wird beim Öffnen abgefragt.

## Browser-Verwaltung unter /admin

Für die Verwaltung im Browser hinterlege in Portainer unter **Stacks → dein v1-Stack → Environment variables** diese beiden Variablen. Verwende dafür den Stack mit Browser-Verwaltung ab Image-Tag `3.3`.

| Variable | Wert |
| --- | --- |
| `ODENTALER_WEB_ADMIN_ORIGIN` | Exakte Adresse, unter der der Browser den Dienst erreicht, z. B. `https://kasse.example.de` oder `https://cashless.local:8443`. Ohne `/admin` und ohne abschließenden Schrägstrich. |
| `ODENTALER_WEB_ADMIN_PASSWORD` | Eigenes zufälliges Passwort mit mindestens 16 Zeichen. Für `.env` eignet sich ein Zufallswert aus Hex-Zeichen, etwa erzeugt mit `openssl rand -hex 24`. |

Öffne danach `https://deine-domain.de/admin` und melde dich mit dem Benutzernamen `admin` und dem konfigurierten Passwort an. Dieser Zugang verwaltet alle Veranstaltungen dieses Servers. Der Zugang ist getrennt von der Android-PIN und vom Gerätecode. Ohne die Konfiguration ist die Browser-Verwaltung deaktiviert.

1. Lege einen Veranstalter und anschließend eine Veranstaltung mit Kassen-PIN und Admin-PIN an.
2. Registriere ein Gerät für die Veranstaltung und wähle seine freigegebenen Bereiche. Wähle in der Android-App ab 3.4 unter **Server einrichten** die Aktion **QR-Code scannen**. Der Code übernimmt Serveradresse und Geräteschlüssel. Prüfe die Adresse und tippe **Verbinden**. Die manuelle Eingabe bleibt verfügbar. Der QR-Code enthält den Gerätezugang und gehört nur auf das einzurichtende Gerät.
3. Lege Produkte an und ordne sie den gewünschten Theken zu. In den Veranstaltungseinstellungen kannst du Wein und Mobil schalten, die Scan-Frist und Aufladebeträge konfigurieren oder die Veranstaltung deaktivieren.

Verwende die URL nur über HTTPS mit einem Zertifikat, dem der Browser vertraut. Wenn deine Domain bereits über einen Reverse Proxy läuft, leite auch `/admin` und dessen Unterpfade an die Odentaler-API weiter. Die API bleibt im Docker-Netz. Bei einem eigenen Proxy kann dieser TLS terminieren, wenn die Verbindung zur API im vertrauenswürdigen internen Netz bleibt. Der Standard-Stack mit Caddy stellt alternativ eine private CA bereit. Für den globalen Admin-Zugang empfiehlt sich Zugriff aus LAN oder VPN.

Unter **Veranstaltung kopieren** werden die Einstellungen und Produkte für einen neuen Termin vorbereitet. Geräte, Guthaben und Buchungen bleiben bei der ursprünglichen Veranstaltung. Produkte ohne Verkäufe und Veranstaltungen ohne Guthaben oder Buchungsnachweise lassen sich löschen. Ansonsten kannst du sie deaktivieren.

## Docker-Hub-Release 3.4

Das Archiv `cashmockless_latest_release_with_wrapper.zip` enthält den Altclient und Gradle-Dateien. Das API-Image wird aus `backend/` dieses Repositories gebaut. `3.4` ergänzt Token, Registrierungs-QR und die Kopier- und Löschfunktionen.

### Image veröffentlichen

Führe die folgenden Befehle aus dem Projektordner in PowerShell aus. Ersetze `mrtwax/cashless-backend` bei Bedarf durch dein Docker-Hub-Repository. Der Mehrarchitektur-Build unterstützt x86-64 und 64-Bit-ARM, etwa einen Raspberry Pi mit 64-Bit-System.

```powershell
docker login
docker buildx build --builder odentaler-builder --platform linux/amd64,linux/arm64 --build-arg ODENTALER_VERSION=3.4 --tag mrtwax/cashless-backend:3.4 --push ./backend
docker buildx imagetools inspect mrtwax/cashless-backend:3.4
```

Wenn `odentaler-builder` auf deinem Rechner noch fehlt, richte ihn einmal ein und wiederhole den Build.

```powershell
docker buildx create --name odentaler-builder --driver docker-container --use --bootstrap
```

### Auf dem Docker-Server starten oder aktualisieren

Verwende [compose.stack.yaml](compose.stack.yaml) mit Docker Compose v2 ab 2.23.1. Die Datei enthält die Proxy-Konfiguration und zieht das fertige Image. Auf einem privaten Docker-Hub-Repository braucht der Server bzw. Portainer Zugriff auf die Registry.

| Variable | Beispiel oder Bedeutung |
| --- | --- |
| `ODENTALER_IMAGE` | `mrtwax/cashless-backend:3.4` |
| `ODENTALER_DB_PASSWORD` | Eigenes zufälliges hexadezimales Passwort, bei Updates eines vorhandenen v1-Stacks dessen bisheriges Passwort |
| `ODENTALER_HOST` | HTTPS-Hostname für die Android-Geräte, z. B. `cashless.local` |
| `ODENTALER_BIND_ADDRESS` | LAN-IP des Docker-Hosts, damit Geräte im selben WLAN den Proxy erreichen |
| `ODENTALER_TLS_PORT` | Optional, Standard `443`. Bei abweichendem Port gehört er in die Serveradresse der App. |

In Portainer unter **Stacks** einen Compose-Stack anlegen oder den vorhandenen **v1**-Stack bearbeiten. Die Variablen im Stack hinterlegen und bereitstellen beziehungsweise aktualisieren. Auf der Kommandozeile die Variablen in die lokale `.env` eintragen und im Stack-Ordner ausführen.

```sh
docker compose -f compose.stack.yaml -p odentaler pull
docker compose -f compose.stack.yaml -p odentaler up -d --wait
docker compose -f compose.stack.yaml -p odentaler ps -a
```

Der Dienst `migrate` führt die Schema-Migration aus und endet bei Erfolg mit Exit-Code 0. Danach startet die API. Für ein Update eines bestehenden v1-Stacks Projektname, Volumes und Datenbankpasswort beibehalten sowie vorher sichern. Beim ersten Update auf 3.3 die neue Stack-Datei übernehmen und den Browser-Zugang wie oben konfigurieren. Bei weiteren Updates dieser Stack-Datei den Image-Tag ändern und die Befehle erneut ausführen.

**Umstieg vom alten Pi-Stack.** Wenn bisher `mrtwax/cashless-backend:arm64` mit der Datenbank `cashmockless` läuft, sichere den Altbestand und lege für v1 einen separaten Stack mit eigenen Volumes an. Die v1-Migration erzeugt das neue Schema. Die Übernahme alter Guthaben und Produkte erfordert einen geprüften Import und den bestätigten Tokenkurs. Bei einem parallelen Test einen freien HTTPS-Port verwenden. Für die erste Einrichtung legst du unter `/admin` eine Veranstaltung an und registrierst Smartphone und Tablet separat.

Prüfe danach `https://<Host>/healthz` und die Zertifikatskette vom Android-Netz aus. Wenn bereits ein vertrauenswürdiger HTTPS-Reverse-Proxy vorhanden ist, muss er die neue API auf Port 8000 im Docker-Netz erreichen. Die enthaltene Caddy-Variante verwendet eine private CA. Die Android-App muss dieser CA vertrauen, wie unten beschrieben.

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
