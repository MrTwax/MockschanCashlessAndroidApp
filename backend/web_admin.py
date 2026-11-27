import hmac
from hashlib import scrypt, sha256
import re
import secrets
from urllib.parse import urlsplit
from uuid import UUID

from flask import Blueprint, Response, abort, redirect, render_template_string, request, url_for
from itsdangerous import BadData, URLSafeTimedSerializer
import psycopg
from werkzeug.security import generate_password_hash

from provisioning import device_qr_data_uri


AREA_NAMES = {
    "cash": "Kasse", "drinks": "Getränketheke", "food": "Essenstheke",
    "wine": "Weintheke", "mobile": "Mobile Bedienung", "admin": "Administration",
}
CSRF_COOKIE = "__Host-OdentalerAdminCsrf"
CSRF_AGE_SECONDS = 3600
FLASH_MESSAGES = {
    "organizer": "Veranstalter gespeichert.",
    "event": "Veranstaltung aktualisiert.",
    "event_copied": "Veranstaltung kopiert. Du kannst jetzt Geräte für die Kopie registrieren.",
    "event_deleted": "Veranstaltung gelöscht.",
    "device": "Gerät gesperrt.",
    "product": "Produkt gespeichert.",
    "product_deleted": "Produkt gelöscht.",
    "pin": "PIN geändert. Der Bereich muss auf den Geräten erneut geöffnet werden.",
}


class InvalidForm(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def https_origin(value, *, allow_path=False):
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
        if (parts.scheme != "https" or not host or parts.username is not None or
                parts.password is not None or port == 0):
            return None
        if not allow_path and (parts.path not in ("", "/") or parts.query or parts.fragment):
            return None
        if ":" in host:
            host = f"[{host}]"
        else:
            host = host.encode("idna").decode("ascii")
        return f"https://{host}" + (f":{port}" if port not in (None, 443) else "")
    except (ValueError, UnicodeError):
        return None


def form_text(field, label, *, optional=False, limit=120):
    value = request.form.get(field, "").strip()
    if len(value) > limit or (not value and not optional):
        raise InvalidForm(f"Bitte {label} prüfen.")
    return value


def integer(value, label, minimum, maximum):
    if not re.fullmatch(r"-?[0-9]{1,12}", value):
        raise InvalidForm(f"Bitte {label} als ganze Zahl eingeben.")
    result = int(value)
    if not minimum <= result <= maximum:
        raise InvalidForm(f"{label} muss zwischen {minimum} und {maximum} liegen.")
    return result


def form_areas(eligible):
    chosen = set(request.form.getlist("areas"))
    if not chosen or not chosen.issubset(eligible):
        raise InvalidForm("Bitte mindestens einen gültigen Bereich auswählen.")
    return [area for area in eligible if area in chosen]


def format_tokens(units):
    whole, fraction = divmod(units, 100)
    return f"{whole},{fraction:02d}".rstrip("0") if fraction else str(whole)


def parse_tokens(value, label):
    value = value.strip().replace(",", ".")
    if not re.fullmatch(r"[0-9]{1,7}(?:\.[0-9]{1,2})?", value):
        raise InvalidForm(f"{label} bitte in Token mit höchstens zwei Nachkommastellen eingeben.")
    whole, _, fraction = value.partition(".")
    units = int(whole) * 100 + int(fraction.ljust(2, "0"))
    if not 1 <= units <= 100_000_000:
        raise InvalidForm(f"{label} muss zwischen 0,01 und 1.000.000 Token liegen.")
    return units


def require_half_tokens(units):
    if any(amount % 50 != 0 for amount in units):
        raise InvalidForm("Neue Beträge müssen in Schritten von 0,5 Token angegeben werden.")


def require_delete_confirmation():
    if request.form.get("confirm") != "yes":
        raise InvalidForm("Bitte die endgültige Löschung bestätigen.")


def form_price():
    if "price_tokens" in request.form:
        return parse_tokens(request.form["price_tokens"], "Den Preis")
    return integer(request.form.get("price_cents", ""), "Der Preis", 1, 100_000_000)


def form_presets():
    if "topup_amounts_tokens" in request.form:
        raw = form_text("topup_amounts_tokens", "die Aufladebeträge")
        amounts = [parse_tokens(value, "Den Aufladebetrag") for value in re.split(r"[;\s]+", raw)]
    else:
        raw = form_text("topup_amounts_cents", "die Aufladebeträge")
        amounts = [integer(value, "Der Aufladebetrag", 1, 100_000_000) for value in re.split(r"[,\s]+", raw)]
    presets = list(dict.fromkeys(amounts))
    if len(presets) > 8:
        raise InvalidForm("Bitte höchstens acht feste Aufladebeträge angeben.")
    return presets


PAGE = """<!doctype html>
<html lang="de">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Der Odentaler · Verwaltung</title>
<style>
:root { color-scheme: light; font: 17px/1.5 system-ui,sans-serif; color: #132d38; background: #f2f6f5; }
* { box-sizing: border-box; }
body { margin: 0; }
header { background: #0e3941; color: #fff; padding: 1.8rem max(1rem,calc((100% - 70rem)/2)); }
header p, header h1 { margin: 0; }
header p { color: #bfdfd9; }
main { max-width: 72rem; margin: auto; padding: 1.25rem 1rem 3rem; }
h2, h3 { line-height: 1.2; margin: 0 0 .7rem; }
p { margin: 0 0 .85rem; }
section, article, details { min-width: 0; background: white; border: 1px solid #c7d6d2; border-radius: .8rem; padding: 1rem; margin-bottom: 1rem; }
details section { margin: .8rem 0 0; }
summary { cursor: pointer; font-weight: 700; padding: .45rem 0; overflow-wrap: anywhere; }
form { display: grid; gap: .65rem; align-items: start; }
label { display: grid; gap: .25rem; font-weight: 650; }
input, select, button, textarea { min-width: 0; min-height: 2.8rem; border: 1px solid #829a98; border-radius: .45rem; padding: .45rem .6rem; font: inherit; }
button { background: #0e5855; border-color: #0e5855; color: white; cursor: pointer; justify-self: start; font-weight: 700; }
button.warn { background: #833624; border-color: #833624; }
button:hover { filter: brightness(.92); }
:focus-visible { outline: 3px solid #b95700; outline-offset: 3px; }
a { color: #084c55; font-weight: 650; }
fieldset { margin: 0; border: 1px solid #c7d6d2; border-radius: .45rem; padding: .4rem .7rem .6rem; min-width: 0; }
legend { font-weight: 650; padding: 0 .2rem; }
.check { display: flex; align-items: center; gap: .45rem; padding: .35rem .15rem; min-height: 2.7rem; font-weight: 500; }
.check input { width: 1.25rem; min-height: 1.25rem; flex: none; }
.grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,22rem),1fr)); gap: .8rem; align-items: start; }
.fields { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,10rem),1fr)); gap: .6rem; }
.checks { display: flex; flex-wrap: wrap; column-gap: 1rem; }
.note { background: #e4f4eb; padding: .65rem; border-radius: .45rem; }
.error { background: #fceae4; padding: .65rem; border-radius: .45rem; color: #762511; }
.muted { color: #425a64; }
.code { width: 100%; font-family: ui-monospace,monospace; overflow-wrap: anywhere; }
.provisioning-qr { display: block; width: min(100%, 18rem); height: auto; margin: .65rem 0; }
.device { display: grid; padding: .7rem 0; gap: .4rem; border-top: 1px solid #c7d6d2; overflow-wrap: anywhere; }
</style>
<header><h1>Der Odentaler</h1><p>Serververwaltung</p></header>
<main>
{% macro csrf() -%}<input type="hidden" name="csrf_token" value="{{ csrf_token }}">{%- endmacro %}
{% macro area_picker(eligible, chosen) -%}
<fieldset><legend>Bereiche</legend><div class="checks">
{% for a in eligible %}<label class="check"><input type="checkbox" name="areas" value="{{ a }}"{% if a in chosen %} checked{% endif %}>{{ area_names[a] }}</label>{% endfor %}
</div></fieldset>
{%- endmacro %}
{% macro product_fields(product) -%}
<div class="fields">
<label>Produktname<input name="name" maxlength="120" required value="{{ product.name if product else '' }}"></label>
<label>Kategorie<input name="category" maxlength="120" value="{{ product.category if product else '' }}"></label>
<label>Preis in Token<input name="price_tokens" inputmode="decimal" maxlength="10" required placeholder="0,5" value="{{ format_tokens(product.price_cents) if product else '' }}"></label>
<label>Reihenfolge<input name="sort_order" type="number" min="-2147483648" max="2147483647" value="{{ product.sort_order if product else 0 }}"></label>
</div>
{{ area_picker(sale_areas, product.areas if product else []) }}
<label class="check"><input name="active" type="checkbox"{% if not product or product.active %} checked{% endif %}>Aktiv im Verkauf</label>
{%- endmacro %}
{% if device_key %}
<section>
<h2>Einmaliger Gerätecode</h2>
<p>Übertrage den Code jetzt auf das Gerät <strong>{{ key_device }}</strong>. Er wird nur auf dieser Seite angezeigt.</p>
{% if qr_data_uri %}<img class="provisioning-qr" src="{{ qr_data_uri }}" alt="QR-Code zur Geräteanmeldung">{% endif %}
<label>Gerätecode<textarea class="code" readonly rows="2" spellcheck="false">{{ device_key }}</textarea></label>
<p><a href="{{ url_for('web_admin.board', event_id=key_event) }}">Zur Veranstaltung zurück</a></p>
</section>
{% elif error %}
<section>
<h2>Eingabe prüfen</h2>
<p class="error">{{ error }}</p>
<p><a href="{{ back_url }}">Zur Verwaltung zurück</a></p>
</section>
{% else %}
{% if flash %}<p class="note" role="status">{{ flash }}</p>{% endif %}
<div class="grid">
<section>
<h2>Veranstaltung auswählen</h2>
{% if events %}
<form action="{{ url_for('web_admin.board') }}" method="get">
<label>Veranstaltung<select name="event_id">
{% for item in events %}<option value="{{ item.id }}"{% if event and event.id == item.id %} selected{% endif %}>{{ item.organizer_name }} · {{ item.name }}{% if not item.active %} (inaktiv){% endif %}</option>{% endfor %}
</select></label><button type="submit">Öffnen</button>
</form>
{% else %}<p class="muted">Es gibt noch keine Veranstaltung.</p>{% endif %}
</section>
<section>
<h2>Veranstalter anlegen</h2>
<form action="{{ url_for('web_admin.create_organizer') }}" method="post">
{{ csrf() }}
<label>Name des Veranstalters<input name="name" maxlength="120" required></label>
<button type="submit">Veranstalter speichern</button>
</form>
</section>
</div>
{% if organizers %}
<details{% if not events %} open{% endif %}>
<summary>Neue Veranstaltung und erstes Gerät anlegen</summary>
<form action="{{ url_for('web_admin.create_event') }}" method="post">
{{ csrf() }}
<div class="fields">
<label>Veranstalter<select name="organizer_id" required>{% for org in organizers %}<option value="{{ org.id }}">{{ org.name }}</option>{% endfor %}</select></label>
<label>Veranstaltungsname<input name="name" maxlength="120" required></label>
<label>Name des ersten Geräts<input name="device_name" maxlength="120" required></label>
</div>
<div class="fields">
<label>Kassen-PIN<input name="cash_pin" type="password" inputmode="numeric" pattern="{{ pin_pattern }}" minlength="{{ minimum_pin }}" maxlength="12" autocomplete="new-password" required></label>
<label>Admin-PIN<input name="admin_pin" type="password" inputmode="numeric" pattern="{{ pin_pattern }}" minlength="{{ minimum_pin }}" maxlength="12" autocomplete="new-password" required></label>
</div>
<button type="submit">Veranstaltung anlegen</button>
</form>
</details>
{% endif %}
{% if event %}
<h2>{{ event.name }}</h2>
<details>
<summary>Veranstaltung kopieren</summary>
<form action="{{ url_for('web_admin.copy_event', event_id=event.id) }}" method="post">
{{ csrf() }}
<p>Die Kopie übernimmt Einstellungen und Produkte. Lege anschließend eigene Geräte dafür an.</p>
<div class="fields">
<label>Name der Kopie<input name="name" maxlength="120" required></label>
<label>Neue Kassen-PIN<input name="cash_pin" type="password" inputmode="numeric" pattern="{{ pin_pattern }}" minlength="{{ minimum_pin }}" maxlength="12" autocomplete="new-password" required></label>
<label>Neue Admin-PIN<input name="admin_pin" type="password" inputmode="numeric" pattern="{{ pin_pattern }}" minlength="{{ minimum_pin }}" maxlength="12" autocomplete="new-password" required></label>
</div>
<button type="submit">Veranstaltung kopieren</button>
</form>
</details>
<div class="grid">
<section>
<h3>Einstellungen</h3>
<form action="{{ url_for('web_admin.event_settings', event_id=event.id) }}" method="post">
{{ csrf() }}
<label>Veranstaltungsname<input name="name" maxlength="120" required value="{{ event.name }}"></label>
<label>Scanzeit in Sekunden<input name="scan_timeout_seconds" type="number" min="30" max="900" required value="{{ event.scan_timeout_seconds }}"></label>
<label>Aufladebeträge in Token<input name="topup_amounts_tokens" maxlength="120" required value="{% for amount in event.topup_amounts_cents %}{{ format_tokens(amount) }}{% if not loop.last %}; {% endif %}{% endfor %}" aria-describedby="preset-help"></label>
<p class="muted" id="preset-help">Mehrere Beträge mit Semikolon trennen, zum Beispiel 0,5; 5; 10.</p>
<label class="check"><input name="active" type="checkbox"{% if event.active %} checked{% endif %}>Veranstaltung aktiv</label>
<label class="check"><input name="wine" type="checkbox"{% if flags.wine %} checked{% endif %}>Weintheke freischalten</label>
<label class="check"><input name="mobile" type="checkbox"{% if flags.mobile %} checked{% endif %}>Mobile Bedienung freischalten</label>
<button type="submit">Einstellungen speichern</button>
</form>
{% if can_delete_event %}
<details><summary>Veranstaltung löschen</summary>
<form action="{{ url_for('web_admin.delete_event', event_id=event.id) }}" method="post">
{{ csrf() }}
<p>Die Veranstaltung, ihre Geräte und Produkte werden dauerhaft entfernt.</p>
<label class="check"><input name="confirm" value="yes" type="checkbox" required>Diese Veranstaltung endgültig löschen</label>
<button type="submit" class="warn">Löschen</button>
</form></details>
{% else %}<p class="muted">Diese Veranstaltung enthält Guthabenkonten oder Buchungen. Deaktiviere sie, um sie mit ihrem Journal aufzubewahren.</p>{% endif %}
</section>
<section>
<h3>PIN ändern</h3>
{% for area in pin_areas %}
<details><summary>{{ area_names[area] }}</summary>
<form action="{{ url_for('web_admin.change_event_pin', event_id=event.id, area=area) }}" method="post">
{{ csrf() }}
<label>Neue PIN<input name="pin" type="password" inputmode="numeric" minlength="{{ minimum_pin }}" maxlength="12" autocomplete="new-password" required></label>
<label>Neue PIN wiederholen<input name="pin_repeat" type="password" inputmode="numeric" minlength="{{ minimum_pin }}" maxlength="12" autocomplete="new-password" required></label>
<button type="submit">PIN speichern</button>
</form></details>
{% endfor %}
</section>
</div>
<div class="grid">
<section>
<h3>Geräte</h3>
<details><summary>Gerät registrieren</summary>
<form action="{{ url_for('web_admin.register_device', event_id=event.id) }}" method="post">
{{ csrf() }}
<label>Gerätename<input name="name" maxlength="120" required></label>
{{ area_picker(areas, []) }}
<button type="submit">Gerätecode erzeugen</button>
</form></details>
{% for d in devices %}
<div class="device">
<strong>{{ d.name }}{% if d.revoked_at %} · Gesperrt{% endif %}</strong>
<span class="muted">{% for a in d.areas %}{{ area_names[a] }}{% if not loop.last %}, {% endif %}{% endfor %}</span>
<span class="muted">Letzter Start: {{ d.last_seen_at if d.last_seen_at else 'Noch keine Anmeldung' }}</span>
{% if not d.revoked_at %}
<details><summary>Gerät sperren</summary>
<form action="{{ url_for('web_admin.revoke_device', event_id=event.id, device_id=d.id) }}" method="post">
{{ csrf() }}
<p>Gesperrte Geräte können keine Buchungen mehr ausführen.</p>
<button type="submit" class="warn">Sperrung bestätigen</button>
</form></details>
{% endif %}
</div>
{% endfor %}
</section>
<section>
<h3>Produkte</h3>
<details><summary>Produkt anlegen</summary>
<form action="{{ url_for('web_admin.create_product', event_id=event.id) }}" method="post">
{{ csrf() }}{{ product_fields(none) }}<button type="submit">Produkt anlegen</button>
</form></details>
{% for product in products %}
<details><summary>{{ product.name }}{% if not product.active %} · Inaktiv{% endif %}</summary>
<form action="{{ url_for('web_admin.edit_product', event_id=event.id, product_id=product.id) }}" method="post">
{{ csrf() }}{{ product_fields(product) }}<button type="submit">Änderungen speichern</button>
</form>
{% if product.has_sales %}
<p class="muted">Verkaufte Produkte bleiben für Berichte erhalten. Zum Ausblenden „Aktiv im Verkauf“ ausschalten und speichern.</p>
{% else %}
<details><summary>Produkt löschen</summary>
<form action="{{ url_for('web_admin.delete_product', event_id=event.id, product_id=product.id) }}" method="post">
{{ csrf() }}
<label class="check"><input name="confirm" value="yes" type="checkbox" required>Dieses Produkt endgültig löschen</label>
<button type="submit" class="warn">Löschen</button>
</form>
</details>
{% endif %}
</details>
{% endfor %}
</section>
</div>
{% endif %}
{% endif %}
</main>
</html>"""


def register_web_admin(app):
    from odentaler import AREAS, OPTIONAL_AREAS, PIN_AREAS, PIN_HASH_METHOD, SALE_AREAS, connect, insert_device, valid_pin

    password = app.config.get("WEB_ADMIN_PASSWORD")
    raw_origin = app.config.get("WEB_ADMIN_ORIGIN")
    origin = https_origin(raw_origin) if isinstance(raw_origin, str) else None
    if not isinstance(password, str) or len(password) < 16 or origin is None:
        return

    blueprint = Blueprint("web_admin", __name__, url_prefix="/admin")
    password_bytes = password.encode("utf-8")
    password_digest = sha256(password_bytes).digest()
    user_digest = sha256(b"admin").digest()
    csrf_key = scrypt(password_bytes, salt=sha256(origin.encode("ascii")).digest(), n=16384, r=8, p=1)
    signer = URLSafeTimedSerializer(csrf_key, salt="odentaler-web-admin-csrf", signer_kwargs={"digest_method": sha256})
    test_pins = app.config["TEST_PINS"]
    minimum_pin = 4 if test_pins else 6
    pin_pattern = f"[0-9]{{{minimum_pin},12}}"

    @blueprint.before_request
    def check_access():
        auth = request.authorization
        if auth is None or auth.type != "basic":
            return unauthorized()
        user_match = hmac.compare_digest(sha256((auth.username or "").encode("utf-8")).digest(), user_digest)
        password_match = hmac.compare_digest(sha256((auth.password or "").encode("utf-8")).digest(), password_digest)
        if not (user_match and password_match):
            return unauthorized()
        if request.method != "POST":
            return None
        source_origin = request.headers.get("Origin")
        if source_origin is None:
            source_origin = https_origin(request.headers.get("Referer", ""), allow_path=True)
        if source_origin != origin:
            abort(403)
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie):
            abort(403)
        try:
            payload = signer.loads(request.form.get("csrf_token", ""), max_age=CSRF_AGE_SECONDS)
        except BadData:
            abort(403)
        if not isinstance(payload, str) or not hmac.compare_digest(payload.encode("utf-8"), cookie.encode("ascii")):
            abort(403)
        return None

    def unauthorized():
        return Response(
            "Anmeldung als Administrator erforderlich.",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="Der Odentaler Verwaltung", charset="UTF-8"'},
            mimetype="text/plain",
        )

    @blueprint.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        return response

    @blueprint.errorhandler(InvalidForm)
    def invalid_form(exception):
        event_id = (request.view_args or {}).get("event_id")
        return render_template_string(PAGE, error=str(exception), back_url=board_url(event_id)), exception.status

    @blueprint.errorhandler(psycopg.errors.LockNotAvailable)
    @blueprint.errorhandler(psycopg.errors.DeadlockDetected)
    def concurrent_change(_exception):
        event_id = (request.view_args or {}).get("event_id")
        return render_template_string(
            PAGE, error="Die Veranstaltung wird gerade verwendet. Bitte versuche es erneut.",
            back_url=board_url(event_id),
        ), 409

    @blueprint.errorhandler(403)
    def rejected_form(_exception):
        return render_template_string(
            PAGE, error="Die Seite konnte die Eingabe nicht bestätigen. Bitte öffne die Verwaltung erneut.",
            back_url=board_url(),
        ), 403

    @blueprint.errorhandler(404)
    def missing_entry(_exception):
        return render_template_string(
            PAGE, error="Der Eintrag wurde nicht gefunden.", back_url=board_url(),
        ), 404

    def board_url(event_id=None, status=None):
        return url_for("web_admin.board", event_id=event_id, status=status)

    def go_back(event_id=None, status=None):
        return redirect(board_url(event_id, status), code=303)

    def show_key(event_id, name, device_key):
        return render_template_string(
            PAGE, device_key=device_key, key_device=name, key_event=event_id,
            qr_data_uri=device_qr_data_uri(origin, device_key),
        ), 201

    def db_connect():
        return connect(app.config["DATABASE_URL"])

    def event_exists(db, event_id):
        if db.execute("SELECT 1 FROM events WHERE id = %s", (event_id,)).fetchone() is None:
            abort(404)

    def find_event_for_update(db, event_id):
        event = db.execute(
            "SELECT topup_amounts_cents FROM events WHERE id = %s FOR UPDATE",
            (event_id,),
        ).fetchone()
        if event is None:
            abort(404)
        return event

    def has_financial_records(db, event_id):
        return db.execute(
            """SELECT EXISTS(
                 SELECT 1 FROM accounts WHERE event_id = %s
                 UNION ALL SELECT 1 FROM transactions WHERE event_id = %s
                 UNION ALL SELECT 1 FROM booking_requests WHERE event_id = %s
               ) AS present""",
            (event_id, event_id, event_id),
        ).fetchone()["present"]

    def hashed_pin(value):
        if not valid_pin(value, test_pins):
            raise InvalidForm(f"Eine PIN benötigt {minimum_pin} bis 12 Ziffern.")
        return generate_password_hash(value, method=PIN_HASH_METHOD)

    def form_pins():
        return {area: hashed_pin(request.form.get(f"{area}_pin")) for area in PIN_AREAS}

    def add_event_pins(db, event_id, pins):
        for area, pin_hash in pins.items():
            db.execute(
                "INSERT INTO pin_roles (event_id, area, pin_hash) VALUES (%s, %s, %s)",
                (event_id, area, pin_hash),
            )

    def product_values():
        return (
            form_text("name", "den Produktnamen"),
            form_text("category", "die Kategorie", optional=True),
            form_price(),
            form_areas(SALE_AREAS),
            integer(request.form.get("sort_order", "") or "0", "Die Reihenfolge", -2_147_483_648, 2_147_483_647),
            request.form.get("active") == "on",
        )

    @blueprint.get("", strict_slashes=False)
    def board():
        raw_event = request.args.get("event_id")
        try:
            event_id = UUID(raw_event) if raw_event else None
        except ValueError:
            abort(404)
        with db_connect() as db:
            organizers = db.execute("SELECT id, name FROM organizers ORDER BY name, id").fetchall()
            events = db.execute(
                """SELECT e.id, e.name, e.active, e.scan_timeout_seconds, e.topup_amounts_cents,
                          o.name AS organizer_name
                   FROM events e JOIN organizers o ON e.organizer_id = o.id ORDER BY o.name, e.name, e.id"""
            ).fetchall()
            event = next((e for e in events if e["id"] == event_id), None) if event_id else (events[0] if events else None)
            if event_id and event is None:
                abort(404)
            devices = []
            products = []
            flags = {}
            can_delete_event = False
            if event:
                can_delete_event = not has_financial_records(db, event["id"])
                devices = db.execute(
                    """SELECT d.id, d.name, d.revoked_at, d.last_seen_at,
                              ARRAY(SELECT a.area FROM device_areas a WHERE a.event_id = d.event_id
                                    AND a.device_id = d.id ORDER BY a.area) AS areas
                       FROM devices d WHERE d.event_id = %s ORDER BY d.name, d.id""",
                    (event["id"],),
                ).fetchall()
                products = db.execute(
                    """SELECT p.id, p.name, p.category, p.price_cents, p.areas, p.sort_order, p.active,
                              EXISTS(SELECT 1 FROM sale_items i WHERE i.event_id = p.event_id
                                     AND i.product_id = p.id) AS has_sales
                       FROM products p WHERE p.event_id = %s ORDER BY p.sort_order, p.name, p.id""",
                    (event["id"],),
                ).fetchall()
                flags = {
                    row["area"]: row["enabled"] for row in db.execute(
                        "SELECT area, enabled FROM event_areas WHERE event_id = %s",
                        (event["id"],),
                    ).fetchall()
                }
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", cookie):
            cookie = secrets.token_urlsafe(32)
        response = app.make_response(render_template_string(
            PAGE, organizers=organizers, events=events, event=event, devices=devices, products=products, flags=flags,
            area_names=AREA_NAMES, areas=AREAS, sale_areas=SALE_AREAS, pin_areas=PIN_AREAS,
            minimum_pin=minimum_pin, pin_pattern=pin_pattern, csrf_token=signer.dumps(cookie),
            format_tokens=format_tokens, can_delete_event=can_delete_event,
            flash=FLASH_MESSAGES.get(request.args.get("status")),
        ))
        response.set_cookie(CSRF_COOKIE, cookie, secure=True, httponly=True, samesite="Strict", path="/")
        return response

    @blueprint.post("/organizers")
    def create_organizer():
        name = form_text("name", "den Namen des Veranstalters")
        with db_connect() as db:
            db.execute("INSERT INTO organizers (name) VALUES (%s)", (name,))
        return go_back(status="organizer")

    @blueprint.post("/events")
    def create_event():
        try:
            organizer_id = UUID(request.form.get("organizer_id", ""))
        except ValueError:
            raise InvalidForm("Bitte einen Veranstalter auswählen.") from None
        name = form_text("name", "den Veranstaltungsnamen")
        device_name = form_text("device_name", "den Gerätenamen")
        pins = form_pins()
        with db_connect() as db:
            if not db.execute("SELECT 1 FROM organizers WHERE id = %s", (organizer_id,)).fetchone():
                raise InvalidForm("Veranstalter wurde nicht gefunden.")
            event_id = db.execute(
                "INSERT INTO events (organizer_id, name) VALUES (%s, %s) RETURNING id",
                (organizer_id, name),
            ).fetchone()["id"]
            for area in AREAS:
                db.execute(
                    "INSERT INTO event_areas (event_id, area, enabled) VALUES (%s, %s, %s)",
                    (event_id, area, area not in OPTIONAL_AREAS),
                )
            add_event_pins(db, event_id, pins)
            _, key = insert_device(db, event_id, device_name, AREAS)
        return show_key(event_id, device_name, key)

    @blueprint.post("/events/<uuid:event_id>/copy")
    def copy_event(event_id):
        name = form_text("name", "den Namen der Kopie")
        pins = form_pins()
        with db_connect() as db:
            db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            copied = db.execute(
                """INSERT INTO events (organizer_id, name, active, scan_timeout_seconds, topup_amounts_cents)
                   SELECT organizer_id, %s, active, scan_timeout_seconds, topup_amounts_cents
                   FROM events WHERE id = %s RETURNING id""",
                (name, event_id),
            ).fetchone()
            if copied is None:
                abort(404)
            new_event_id = copied["id"]
            db.execute(
                """INSERT INTO event_areas (event_id, area, enabled)
                   SELECT %s, area, enabled FROM event_areas WHERE event_id = %s""",
                (new_event_id, event_id),
            )
            db.execute(
                """INSERT INTO products (event_id, name, category, price_cents, areas, sort_order, image_url, active)
                   SELECT %s, name, category, price_cents, areas, sort_order, image_url, active
                   FROM products WHERE event_id = %s""",
                (new_event_id, event_id),
            )
            add_event_pins(db, new_event_id, pins)
        return go_back(new_event_id, "event_copied")

    @blueprint.post("/events/<uuid:event_id>/delete")
    def delete_event(event_id):
        require_delete_confirmation()
        with db_connect() as db:
            db.execute("SET LOCAL lock_timeout = '750ms'")
            find_event_for_update(db, event_id)
            if has_financial_records(db, event_id):
                raise InvalidForm(
                    "Diese Veranstaltung enthält Guthabenkonten oder Buchungen. Deaktiviere sie zum Archivieren.",
                    status=409,
                )
            # Leave accounts and all transaction-related tables untouched.
            for table in ("scans", "operator_sessions", "device_areas", "devices", "pin_roles", "event_areas", "products"):
                db.execute(
                    psycopg.sql.SQL("DELETE FROM {} WHERE event_id = %s").format(psycopg.sql.Identifier(table)),
                    (event_id,),
                )
            db.execute("DELETE FROM events WHERE id = %s", (event_id,))
        return go_back(status="event_deleted")

    @blueprint.post("/events/<uuid:event_id>/settings")
    def event_settings(event_id):
        name = form_text("name", "den Veranstaltungsnamen")
        timeout = integer(request.form.get("scan_timeout_seconds", ""), "Die Scanzeit", 30, 900)
        presets = form_presets()
        active = request.form.get("active") == "on"
        with db_connect() as db:
            previous = find_event_for_update(db, event_id)
            if presets != previous["topup_amounts_cents"]:
                require_half_tokens(presets)
            db.execute(
                """UPDATE events SET name = %s, active = %s, scan_timeout_seconds = %s, topup_amounts_cents = %s
                   WHERE id = %s""",
                (name, active, timeout, presets, event_id),
            )
            for area in OPTIONAL_AREAS:
                db.execute(
                    "UPDATE event_areas SET enabled = %s WHERE event_id = %s AND area = %s",
                    (request.form.get(area) == "on", event_id, area),
                )
        return go_back(event_id, "event")

    @blueprint.post("/events/<uuid:event_id>/devices")
    def register_device(event_id):
        name = form_text("name", "den Gerätenamen")
        areas = form_areas(AREAS)
        with db_connect() as db:
            event_exists(db, event_id)
            _, key = insert_device(db, event_id, name, areas)
        return show_key(event_id, name, key)

    @blueprint.post("/events/<uuid:event_id>/devices/<uuid:device_id>/revoke")
    def revoke_device(event_id, device_id):
        with db_connect() as db:
            updated = db.execute(
                "UPDATE devices SET revoked_at = COALESCE(revoked_at, clock_timestamp()) WHERE id = %s AND event_id = %s",
                (device_id, event_id),
            )
            if updated.rowcount != 1:
                abort(404)
        return go_back(event_id, "device")

    @blueprint.post("/events/<uuid:event_id>/products")
    def create_product(event_id):
        name, category, price, areas, sort_order, active = product_values()
        require_half_tokens((price,))
        with db_connect() as db:
            event_exists(db, event_id)
            db.execute(
                """INSERT INTO products (event_id, name, category, price_cents, areas, sort_order, active)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (event_id, name, category, price, areas, sort_order, active),
            )
        return go_back(event_id, "product")

    @blueprint.post("/events/<uuid:event_id>/products/<int:product_id>")
    def edit_product(event_id, product_id):
        name, category, price, areas, sort_order, active = product_values()
        with db_connect() as db:
            previous = find_product_for_update(db, event_id, product_id)
            if price != previous["price_cents"]:
                require_half_tokens((price,))
            db.execute(
                """UPDATE products SET name = %s, category = %s, price_cents = %s, areas = %s, sort_order = %s,
                                       active = %s WHERE event_id = %s AND id = %s""",
                (name, category, price, areas, sort_order, active, event_id, product_id),
            )
        return go_back(event_id, "product")

    def find_product_for_update(db, event_id, product_id):
        if not 1 <= product_id <= 2_147_483_647:
            abort(404)
        product = db.execute(
            "SELECT price_cents FROM products WHERE event_id = %s AND id = %s FOR UPDATE",
            (event_id, product_id),
        ).fetchone()
        if product is None:
            abort(404)
        return product

    @blueprint.post("/events/<uuid:event_id>/products/<int:product_id>/delete")
    def delete_product(event_id, product_id):
        require_delete_confirmation()
        with db_connect() as db:
            db.execute("SET LOCAL lock_timeout = '750ms'")
            find_product_for_update(db, event_id, product_id)
            if db.execute(
                "SELECT 1 FROM sale_items WHERE event_id = %s AND product_id = %s LIMIT 1",
                (event_id, product_id),
            ).fetchone():
                raise InvalidForm(
                    "Dieses Produkt wurde bereits verkauft. Deaktiviere es, um die bisherigen Verkäufe zu erhalten.",
                    status=409,
                )
            db.execute("DELETE FROM products WHERE event_id = %s AND id = %s", (event_id, product_id))
        return go_back(event_id, "product_deleted")

    @blueprint.post("/events/<uuid:event_id>/pins/<area>")
    def change_event_pin(event_id, area):
        if area not in PIN_AREAS:
            abort(404)
        pin = request.form.get("pin")
        if pin != request.form.get("pin_repeat"):
            raise InvalidForm("Die beiden PIN-Eingaben stimmen nicht überein.")
        pin_hash = hashed_pin(pin)
        with db_connect() as db:
            updated = db.execute(
                """UPDATE pin_roles SET pin_hash = %s, failed_attempts = 0, blocked_until = NULL
                   WHERE event_id = %s AND area = %s""",
                (pin_hash, event_id, area),
            )
            if updated.rowcount != 1:
                abort(404)
            db.execute(
                """UPDATE operator_sessions SET expires_at = clock_timestamp()
                   WHERE event_id = %s AND area = %s AND expires_at > clock_timestamp()""",
                (event_id, area),
            )
        return go_back(event_id, "pin")

    app.register_blueprint(blueprint)
