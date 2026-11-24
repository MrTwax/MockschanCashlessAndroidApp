from functools import wraps
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets

import click
from flask import Flask, request
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import check_password_hash, generate_password_hash

from ledger import (
    HALF_TOKEN_UNITS, SALE_AREAS, book, booking_status, close_scan, error, open_scan, uuid_value,
)
from reporting import register_reporting
from web_admin import register_web_admin


AREAS = ("cash", *SALE_AREAS, "admin")
PIN_AREAS = ("cash", "admin")
OPTIONAL_AREAS = ("wine", "mobile")
PIN_ATTEMPTS = 5
PIN_HASH_METHOD = "scrypt:32768:8:1"


def connect(dsn):
    return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=5)


def secret_hash(value):
    return sha256(value.encode("utf-8")).digest()


def secret_header(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", value) else None


def authorized_device(db, device_key):
    if not device_key:
        return None
    return db.execute(
        """SELECT d.id AS device_id, e.id AS event_id, e.name AS event_name,
                  e.scan_timeout_seconds, e.topup_amounts_cents
           FROM devices d JOIN events e ON e.id = d.event_id
           WHERE d.key_hash = %s AND d.revoked_at IS NULL AND e.active
           FOR SHARE OF d, e""",
        (secret_hash(device_key),),
    ).fetchone()


def authorized_session(db, token):
    if not token:
        return None
    return db.execute(
        """SELECT s.id AS session_id, s.event_id, s.device_id, s.area, e.scan_timeout_seconds
           FROM operator_sessions s
           JOIN devices d ON (s.event_id, s.device_id) = (d.event_id, d.id)
           JOIN events e ON e.id = s.event_id
           JOIN event_areas ea ON (s.event_id, s.area) = (ea.event_id, ea.area)
           WHERE s.token_hash = %s AND s.expires_at > clock_timestamp()
                 AND d.revoked_at IS NULL AND e.active AND ea.enabled
           FOR SHARE OF s, d, e, ea""",
        (secret_hash(token),),
    ).fetchone()


def offered_areas(db, device):
    return [
        row["area"] for row in db.execute(
            """SELECT da.area FROM device_areas da
               JOIN event_areas ea USING (event_id, area)
               WHERE da.device_id = %s AND da.event_id = %s AND ea.enabled""",
            (device["device_id"], device["event_id"]),
        ).fetchall()
    ]


def valid_pin(pin, test_mode):
    minimum = 4 if test_mode else 6
    return isinstance(pin, str) and re.fullmatch(rf"[0-9]{{{minimum},12}}", pin) is not None


def check_pin(db, event_id, area, pin, test_mode):
    role = db.execute(
        """SELECT pin_hash, failed_attempts, blocked_until > clock_timestamp() AS blocked,
                  blocked_until IS NOT NULL AS lock_elapsed
           FROM pin_roles WHERE event_id = %s AND area = %s FOR UPDATE""",
        (event_id, area),
    ).fetchone()
    if not role:
        return error(403, "area_unavailable")
    if role["blocked"]:
        return error(429, "pin_locked")
    if valid_pin(pin, test_mode) and check_password_hash(role["pin_hash"], pin):
        db.execute(
            "UPDATE pin_roles SET failed_attempts = 0, blocked_until = NULL WHERE event_id = %s AND area = %s",
            (event_id, area),
        )
        return None
    attempts = 1 if role["lock_elapsed"] else role["failed_attempts"] + 1
    db.execute(
        """UPDATE pin_roles
           SET failed_attempts = %s,
               blocked_until = CASE WHEN %s >= %s THEN clock_timestamp() + interval '5 minutes' ELSE NULL END
           WHERE event_id = %s AND area = %s""",
        (attempts, attempts, PIN_ATTEMPTS, event_id, area),
    )
    return error(429, "pin_locked") if attempts >= PIN_ATTEMPTS else error(401, "invalid_pin")


def payload_object():
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATABASE_URL=os.environ.get("DATABASE_URL"),
        TEST_PINS=os.environ.get("ODENTALER_ENV") == "test",
        WEB_ADMIN_PASSWORD=os.environ.get("ODENTALER_WEB_ADMIN_PASSWORD"),
        WEB_ADMIN_ORIGIN=os.environ.get("ODENTALER_WEB_ADMIN_ORIGIN"),
        MAX_CONTENT_LENGTH=65_536,
    )
    app.config.update(config or {})
    if not app.config["DATABASE_URL"]:
        raise RuntimeError("DATABASE_URL mit PostgreSQL-Verbindungsdaten erforderlich.")

    def with_session(handler):
        @wraps(handler)
        def run(*args, **kwargs):
            prefix, _, token = request.headers.get("Authorization", "").partition(" ")
            token = secret_header(token) if prefix.lower() == "bearer" else None
            if not token:
                return error(401, "session_unauthorized")
            with connect(app.config["DATABASE_URL"]) as db:
                actor = authorized_session(db, token)
                if actor is None:
                    return error(401, "session_unauthorized")
                return handler(db, actor, *args, **kwargs)
        return run

    @app.errorhandler(psycopg.Error)
    def database_error(exception):
        app.logger.error("Datenbankoperation fehlgeschlagen (%s, %s)", type(exception).__name__, exception.sqlstate)
        return error(503, "database_unavailable")

    @app.get("/healthz")
    def health():
        with connect(app.config["DATABASE_URL"]) as db:
            schema = db.execute("SELECT to_regclass('public.booking_requests') AS ready").fetchone()
        return ({"status": "ok"}, 200) if schema["ready"] else error(503, "schema_unavailable")

    @app.get("/v1/bootstrap")
    def bootstrap():
        device_key = secret_header(request.headers.get("X-Device-Key"))
        if not device_key:
            return error(401, "device_unauthorized")
        with connect(app.config["DATABASE_URL"]) as db:
            # Update owns the device row before the authentication query takes a row lock.
            updated = db.execute(
                "UPDATE devices SET last_seen_at = clock_timestamp() WHERE key_hash = %s AND revoked_at IS NULL",
                (secret_hash(device_key),),
            )
            if updated.rowcount != 1:
                return error(401, "device_unauthorized")
            device = authorized_device(db, device_key)
            if not device:
                return error(401, "device_unauthorized")
            areas = offered_areas(db, device)
            return {
                "event_id": str(device["event_id"]),
                "event_name": device["event_name"],
                "areas": [area for area in AREAS if area in areas],
                "scan_timeout_seconds": device["scan_timeout_seconds"],
                "topup_amounts_cents": device["topup_amounts_cents"],
            }

    @app.post("/v1/session")
    def open_session():
        device_key = secret_header(request.headers.get("X-Device-Key"))
        if not device_key:
            return error(401, "device_unauthorized")
        body = payload_object()
        if body is None or body.get("area") not in AREAS:
            return error(400, "invalid_request")
        area = body["area"]
        with connect(app.config["DATABASE_URL"]) as db:
            device = authorized_device(db, device_key)
            if not device:
                return error(401, "device_unauthorized")
            assignment = db.execute(
                """SELECT 1 FROM device_areas da JOIN event_areas ea USING (event_id, area)
                   WHERE da.event_id = %s AND da.device_id = %s AND da.area = %s AND ea.enabled
                   FOR SHARE OF da, ea""",
                (device["event_id"], device["device_id"], area),
            ).fetchone()
            if not assignment:
                return error(403, "area_unavailable")
            if area in PIN_AREAS:
                rejection = check_pin(db, device["event_id"], area, body.get("pin"), app.config["TEST_PINS"])
                if rejection is not None:
                    return rejection
            token = secrets.token_urlsafe(32)
            expires_at = db.execute(
                """INSERT INTO operator_sessions (event_id, device_id, area, token_hash, expires_at)
                   VALUES (%s, %s, %s, %s, clock_timestamp() + interval '8 hours') RETURNING expires_at""",
                (device["event_id"], device["device_id"], area, secret_hash(token)),
            ).fetchone()["expires_at"]
            return {"token": token, "expires_at": expires_at.isoformat()}

    @app.post("/v1/scans")
    @with_session
    def scan(db, actor):
        body = payload_object()
        return open_scan(db, actor, body) if body is not None else error(400, "invalid_request")

    @app.delete("/v1/scans/<uuid:scan_id>")
    @with_session
    def cancel(db, actor, scan_id):
        return close_scan(db, actor, scan_id)

    @app.get("/v1/products")
    @with_session
    def catalog(db, actor):
        if actor["area"] not in SALE_AREAS:
            return error(403, "operation_forbidden")
        return db.execute(
            """SELECT id, name, price_cents, category, image_url FROM products
               WHERE event_id = %s AND active AND %s = ANY(areas)
               ORDER BY sort_order, name, id""",
            (actor["event_id"], actor["area"]),
        ).fetchall()

    @app.post("/v1/transactions")
    @with_session
    def transaction(db, actor):
        key = uuid_value(request.headers.get("Idempotency-Key"))
        if key is None:
            return error(400, "invalid_idempotency_key")
        body = payload_object()
        if body is None:
            return error(400, "invalid_request")
        return book(db, actor, key, body)

    @app.get("/v1/transactions/<uuid:key>")
    @with_session
    def transaction_status(db, actor, key):
        return booking_status(db, actor, key)

    @app.get("/v1/admin/areas")
    @with_session
    def list_areas(db, actor):
        if actor["area"] != "admin":
            return error(403, "operation_forbidden")
        rows = db.execute(
            "SELECT area, enabled FROM event_areas WHERE event_id = %s",
            (actor["event_id"],),
        ).fetchall()
        return {row["area"]: row["enabled"] for row in rows}

    @app.put("/v1/admin/areas/<area>")
    @with_session
    def set_area(db, actor, area):
        if actor["area"] != "admin":
            return error(403, "operation_forbidden")
        body = payload_object()
        if area not in OPTIONAL_AREAS or body is None or type(body.get("enabled")) is not bool:
            return error(400, "invalid_request")
        db.execute(
            "UPDATE event_areas SET enabled = %s WHERE event_id = %s AND area = %s",
            (body["enabled"], actor["event_id"], area),
        )
        return {"area": area, "enabled": body["enabled"]}

    register_reporting(app, with_session)
    register_web_admin(app)
    register_cli(app)
    return app


def migrate(dsn):
    with connect(dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(31079, 1)")
        db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY)")
        for migration in sorted(Path(__file__).with_name("migrations").glob("*.sql")):
            if db.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (migration.name,)).fetchone():
                continue
            db.execute(migration.read_text(encoding="utf-8"), prepare=False)
            db.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (migration.name,))


def insert_device(db, event_id, name, areas):
    key = secrets.token_urlsafe(32)
    device_id = db.execute(
        "INSERT INTO devices (event_id, name, key_hash) VALUES (%s, %s, %s) RETURNING id",
        (event_id, name, secret_hash(key)),
    ).fetchone()["id"]
    for area in set(areas):
        db.execute(
            "INSERT INTO device_areas (event_id, device_id, area) VALUES (%s, %s, %s)",
            (event_id, device_id, area),
        )
    return device_id, key


def register_cli(app):
    @app.cli.command("migrate")
    def migrate_command():
        migrate(app.config["DATABASE_URL"])
        click.echo("Migrationen angewendet.")

    def pin_prompt(prompt):
        pin = click.prompt(prompt, hide_input=True, confirmation_prompt=True)
        if not valid_pin(pin, app.config["TEST_PINS"]):
            minimum = 4 if app.config["TEST_PINS"] else 6
            raise click.ClickException(f"Die PIN muss {minimum} bis 12 Ziffern enthalten.")
        return generate_password_hash(pin, method=PIN_HASH_METHOD)

    @app.cli.command("create-event")
    @click.option("--organizer")
    @click.option("--organizer-id", type=click.UUID)
    @click.option("--event", required=True)
    @click.option("--device", required=True)
    def create_event(organizer, organizer_id, event, device):
        if bool(organizer) == bool(organizer_id):
            raise click.ClickException("Genau eine Option angeben: --organizer oder --organizer-id.")
        pins = {area: pin_prompt(f"PIN für {label}") for area, label in (("cash", "Kasse"), ("admin", "Administration"))}
        with connect(app.config["DATABASE_URL"]) as db:
            if organizer:
                organizer_id = db.execute(
                    "INSERT INTO organizers (name) VALUES (%s) RETURNING id",
                    (organizer.strip(),),
                ).fetchone()["id"]
            elif not db.execute("SELECT 1 FROM organizers WHERE id = %s", (organizer_id,)).fetchone():
                raise click.ClickException("Veranstalter wurde nicht gefunden.")
            event_id = db.execute(
                "INSERT INTO events (organizer_id, name) VALUES (%s, %s) RETURNING id",
                (organizer_id, event.strip()),
            ).fetchone()["id"]
            for area in AREAS:
                db.execute(
                    "INSERT INTO event_areas (event_id, area, enabled) VALUES (%s, %s, %s)",
                    (event_id, area, area not in OPTIONAL_AREAS),
                )
            for area, pin_hash in pins.items():
                db.execute("INSERT INTO pin_roles VALUES (%s, %s, %s)", (event_id, area, pin_hash))
            device_id, key = insert_device(db, event_id, device.strip(), AREAS)
        click.echo(f"Veranstalter-ID: {organizer_id}")
        click.echo(f"Veranstaltungs-ID: {event_id}")
        click.echo(f"Geräte-ID: {device_id}")
        click.echo(f"Einmalig angezeigter Geräteschlüssel: {key}")

    @app.cli.command("register-device")
    @click.option("--event-id", required=True, type=click.UUID)
    @click.option("--name", required=True)
    @click.option("--area", required=True, multiple=True, type=click.Choice(AREAS))
    def register_device(event_id, name, area):
        with connect(app.config["DATABASE_URL"]) as db:
            if not db.execute("SELECT 1 FROM events WHERE id = %s", (event_id,)).fetchone():
                raise click.ClickException("Veranstaltung wurde nicht gefunden.")
            device_id, key = insert_device(db, event_id, name.strip(), area)
        click.echo(f"Geräte-ID: {device_id}")
        click.echo(f"Einmalig angezeigter Geräteschlüssel: {key}")

    @app.cli.command("revoke-device")
    @click.option("--device-id", required=True, type=click.UUID)
    def revoke_device(device_id):
        with connect(app.config["DATABASE_URL"]) as db:
            result = db.execute(
                "UPDATE devices SET revoked_at = COALESCE(revoked_at, clock_timestamp()) WHERE id = %s",
                (device_id,),
            )
            if result.rowcount != 1:
                raise click.ClickException("Gerät wurde nicht gefunden.")
        click.echo("Gerät gesperrt.")

    @app.cli.command("change-pin")
    @click.option("--event-id", required=True, type=click.UUID)
    @click.option("--area", required=True, type=click.Choice(PIN_AREAS))
    def change_pin(event_id, area):
        pin_hash = pin_prompt("Neue PIN")
        with connect(app.config["DATABASE_URL"]) as db:
            result = db.execute(
                """UPDATE pin_roles SET pin_hash = %s, failed_attempts = 0, blocked_until = NULL
                   WHERE event_id = %s AND area = %s""",
                (pin_hash, event_id, area),
            )
            if result.rowcount != 1:
                raise click.ClickException("PIN-Bereich wurde nicht gefunden.")
            db.execute(
                """UPDATE operator_sessions SET expires_at = clock_timestamp()
                   WHERE event_id = %s AND area = %s AND expires_at > clock_timestamp()""",
                (event_id, area),
            )
        click.echo("PIN geändert. Der Bereich muss erneut geöffnet werden.")

    @app.cli.command("add-product")
    @click.option("--event-id", required=True, type=click.UUID)
    @click.option("--name", required=True)
    @click.option("--category", default="")
    @click.option("--price-cents", required=True, type=click.IntRange(1, 100_000_000))
    @click.option("--area", required=True, multiple=True, type=click.Choice(SALE_AREAS))
    def add_product(event_id, name, category, price_cents, area):
        if price_cents % HALF_TOKEN_UNITS:
            raise click.ClickException("Der Preis muss einem halben oder ganzen Token entsprechen.")
        with connect(app.config["DATABASE_URL"]) as db:
            if not db.execute("SELECT 1 FROM events WHERE id = %s", (event_id,)).fetchone():
                raise click.ClickException("Veranstaltung wurde nicht gefunden.")
            product_id = db.execute(
                """INSERT INTO products (event_id, name, category, price_cents, areas)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (event_id, name.strip(), category.strip(), price_cents, list(set(area))),
            ).fetchone()["id"]
        click.echo(f"Produkt-ID: {product_id}")

    @app.cli.command("edit-product")
    @click.option("--event-id", required=True, type=click.UUID)
    @click.option("--product-id", required=True, type=click.IntRange(1, 2_147_483_647))
    @click.option("--name")
    @click.option("--category")
    @click.option("--price-cents", type=click.IntRange(1, 100_000_000))
    @click.option("--area", multiple=True, type=click.Choice(SALE_AREAS))
    @click.option("--sort-order", type=click.IntRange(-2_147_483_648, 2_147_483_647))
    @click.option("--active/--inactive", default=None)
    def edit_product(event_id, product_id, name, category, price_cents, area, sort_order, active):
        if price_cents is not None and price_cents % HALF_TOKEN_UNITS:
            raise click.ClickException("Der neue Preis muss einem halben oder ganzen Token entsprechen.")
        if name is not None and not name.strip():
            raise click.ClickException("Produktname darf nicht leer sein.")
        with connect(app.config["DATABASE_URL"]) as db:
            result = db.execute(
                """UPDATE products SET name = COALESCE(%s, name), category = COALESCE(%s, category),
                       price_cents = COALESCE(%s, price_cents), areas = COALESCE(%s, areas),
                       sort_order = COALESCE(%s, sort_order), active = COALESCE(%s, active)
                   WHERE event_id = %s AND id = %s""",
                (name.strip() if name is not None else None, category.strip() if category is not None else None,
                 price_cents, list(dict.fromkeys(area)) or None, sort_order, active, event_id, product_id),
            )
            if result.rowcount != 1:
                raise click.ClickException("Produkt wurde in dieser Veranstaltung nicht gefunden.")
        click.echo("Produkt aktualisiert.")

    @app.cli.command("configure-event")
    @click.option("--event-id", required=True, type=click.UUID)
    @click.option("--name")
    @click.option("--scan-timeout-seconds", type=click.IntRange(30, 900))
    @click.option("--topup-cents", multiple=True, type=click.IntRange(1, 100_000_000))
    @click.option("--active/--inactive", default=None)
    def configure_event(event_id, name, scan_timeout_seconds, topup_cents, active):
        if name is not None and not name.strip():
            raise click.ClickException("Veranstaltungsname darf nicht leer sein.")
        presets = list(dict.fromkeys(topup_cents))
        if any(value % HALF_TOKEN_UNITS for value in presets):
            raise click.ClickException("Aufladebeträge müssen in halben Token angegeben werden.")
        if len(presets) > 8:
            raise click.ClickException("Maximal acht feste Aufladebeträge angeben.")
        with connect(app.config["DATABASE_URL"]) as db:
            result = db.execute(
                """UPDATE events SET name = COALESCE(%s, name), active = COALESCE(%s, active),
                       scan_timeout_seconds = COALESCE(%s, scan_timeout_seconds),
                       topup_amounts_cents = COALESCE(%s, topup_amounts_cents)
                   WHERE id = %s""",
                (name.strip() if name is not None else None, active, scan_timeout_seconds, presets or None, event_id),
            )
            if result.rowcount != 1:
                raise click.ClickException("Veranstaltung wurde nicht gefunden.")
        click.echo("Veranstaltung aktualisiert.")

