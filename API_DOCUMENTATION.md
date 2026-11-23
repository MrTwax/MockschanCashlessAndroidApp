# REST-API · Der Odentaler

Die API arbeitet per JSON und HTTPS. Der Buchungsdienst verwendet untenstehende `/v1`-Routen. Die Schnittstellen des gelieferten Archivs sind in [PROJECT_AUDIT.md](PROJECT_AUDIT.md) dokumentiert. Bestandsclients müssen den versionierten Vertrag verwenden.

## Anmeldung und Gerätekontext

- `GET /healthz` liefert HTTP 200 mit `{"status":"ok"}`, wenn Datenbank und Buchungsschema erreichbar sind.
- `GET /v1/bootstrap` erwartet `X-Device-Key` und liefert `event_id`, `event_name`, `areas`, `scan_timeout_seconds` und `topup_amounts_cents`.
- `POST /v1/session` erwartet `X-Device-Key`, `area` und für `cash` und `admin` eine als String übertragene `pin`. Antwort mit `token` und `expires_at`. Folgende Aufrufe verwenden `Authorization: Bearer <token>`.
- Bereiche sind `cash`, `drinks`, `food`, `wine`, `mobile` und `admin`. Aktive Veranstaltung, Zuteilung, Gerätesperre und Freischaltung begrenzen den Zugriff. Test-PINs sind bei der lokalen Einrichtung ausdrücklich einzutragen. Im Standardmodus sind mindestens sechs Stellen zulässig.

## Scanner, Warenkorb und Buchung

| Route | Inhalt |
| --- | --- |
| `POST /v1/scans` | `{"uid":"04A1B2C3"}` liefert `scan_id`, normalisierte `uid`, `balance_cents`, `expires_at`. Mehrfachlesen derselben UID im offenen Kontext liefert dieselbe Scan-ID. |
| `DELETE /v1/scans/{scan_id}` | Beendet einen Scan im eigenen Geräte-/Bereichskontext. HTTP 204 bei geschlossenem Scan ohne Buchung. |
| `GET /v1/products` | Aktiver Katalog für die angemeldete Theke. Felder `id`, `name`, `category`, `price_cents`, `image_url`. |
| `POST /v1/transactions` | Erfordert `Idempotency-Key` mit UUID und eine JSON-Nutzlast wie unten. |
| `GET /v1/transactions/{key}` | Liefert das festgehaltene Buchungsergebnis im selben Gerät-, Event- und Bereichskontext. |

Aufladung und Auszahlung verwenden `kind` gleich `topup` beziehungsweise `refund`, `scan_id`, positive ganze `amount_cents` sowie `payment_method` gleich `cash`. Nicht integrierte Kartenzahlungen werden abgewiesen.

Ein Warenverkauf verwendet `kind` gleich `sale`, `scan_id` und `items`. Jede Position hat `product_id`, positive ganze `quantity` und den erwarteten `unit_price_cents`. Der Server prüft die aktiven Produkte, berechnet den Betrag und meldet eine zwischenzeitliche Preisänderung. Erfolgreiche Buchungen liefern `id`, `kind`, `amount_cents`, `balance_before_cents` und `balance_after_cents`.

Bei unklarer Antwort zuerst den Status abfragen. `transaction_not_found` kann auch auftreten, während der erste Aufruf noch läuft. Die gespeicherte Nutzlast lässt sich mit **derselben** UUID erneut senden. Eine geänderte Nutzlast mit derselben UUID führt zu `idempotency_conflict`. Buchung, Positionen, Kontosaldo und Idempotenzantwort werden gemeinsam bestätigt. Ein bereits erfolgreich verwendeter Scan kann keine weitere Buchung auslösen.

## Verwaltung und Berichte

- `GET /v1/admin/areas` liefert die veranstaltungsbezogenen Schalter.
- `PUT /v1/admin/areas/{wine|mobile}` setzt `{"enabled":true}` oder `{"enabled":false}`. Ein Gerät braucht zusätzlich die passende Bereichszuteilung.
- `GET /v1/admin/report` liefert Bargeldaufladungen, Barauszahlungen, Produktumsatz und aktuelles Restguthaben sowie Verkäufe je Bereich, Produkt und Gerät.
- `GET /v1/admin/transactions.csv` liefert einen Semikolon-getrennten Export mit einer Zeile pro Buchung, Zeit in UTC, Buchungsart und Beträgen in Cent.
- Die Berichtsrouten benötigen `from` und `until` als RFC-3339-Datum mit Zeitzone und Sekunden. Der Zeitraum ist unten inklusive, oben exklusiv und höchstens 31 Tage groß. CSV fasst maximal 10.000 Zeilen. Bei Überschreitung muss der Zeitraum verkürzt werden.
- Geräteprovisionierung, PIN-Wechsel und die erste Anlage von Veranstaltungen und Produkten erfolgen über die [Verwaltungskommandos](DEPLOYMENT.md).

Fehler liefern, soweit sie durch eine Fachroute beantwortet werden, `{"error":"<code>"}`. Wichtige Beispiele sind `session_unauthorized`, `area_unavailable`, `pin_locked`, `scan_expired`, `insufficient_balance`, `price_changed` und `database_unavailable`. Ein Netzwerkfehler oder HTTP 5xx bestätigt keine Buchung.
