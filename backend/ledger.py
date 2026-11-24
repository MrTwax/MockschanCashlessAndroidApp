from datetime import timedelta
from hashlib import sha256
import json
import re
from uuid import UUID

from psycopg.types.json import Jsonb


SALE_AREAS = ("drinks", "food", "wine", "mobile")
MAX_BOOKING_CENTS = 100_000_000
HALF_TOKEN_UNITS = 50
MAX_BALANCE_CENTS = 1_000_000_000_000
UID_PATTERN = re.compile(r"(?:[0-9A-F]{2}){4,16}", re.ASCII | re.IGNORECASE)


def error(status, code):
    return {"error": code}, status


def uuid_value(value):
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    return None


def scoped(actor):
    return actor["event_id"], actor["device_id"], actor["area"]


def open_scan(db, actor, payload):
    value = payload.get("uid")
    if not isinstance(value, str) or not UID_PATTERN.fullmatch(value):
        return error(400, "invalid_uid")
    uid = value.upper()
    if actor["area"] not in ("cash", *SALE_AREAS):
        return error(403, "operation_forbidden")

    # Serialize simultaneous scans on this device and area without locking other devices.
    event_id, device_id, area = scoped(actor)
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{device_id}:{area}",))
    open_row = db.execute(
        """SELECT id, uid, expires_at, expires_at > clock_timestamp() AS valid FROM scans
           WHERE event_id = %s AND device_id = %s AND area = %s AND closed_at IS NULL
           FOR UPDATE""",
        scoped(actor),
    ).fetchone()
    if open_row and (open_row["uid"] != uid or not open_row["valid"]):
        db.execute("UPDATE scans SET closed_at = clock_timestamp() WHERE id = %s", (open_row["id"],))
        open_row = None

    account = db.execute(
        "SELECT balance_cents FROM accounts WHERE event_id = %s AND uid = %s",
        (event_id, uid),
    ).fetchone()
    if account is None and area != "cash":
        return error(404, "account_not_found")
    if open_row is None:
        open_row = db.execute(
            """INSERT INTO scans (event_id, device_id, area, uid, expires_at)
               VALUES (%s, %s, %s, %s, clock_timestamp() + make_interval(secs => %s))
               RETURNING id, expires_at""",
            (event_id, device_id, area, uid, actor["scan_timeout_seconds"]),
        ).fetchone()
    now = db.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
    remaining_ms = max(0, (open_row["expires_at"] - now) // timedelta(milliseconds=1))
    return {
        "scan_id": str(open_row["id"]),
        "uid": uid,
        "balance_cents": account["balance_cents"] if account else 0,
        "expires_at": open_row["expires_at"].isoformat(),
        "expires_in_ms": remaining_ms,
    }, 200


def close_scan(db, actor, scan_id):
    scan = db.execute(
        """SELECT id FROM scans WHERE event_id = %s AND device_id = %s AND area = %s AND id = %s
           FOR UPDATE""",
        (*scoped(actor), scan_id),
    ).fetchone()
    if not scan:
        return error(404, "scan_not_found")
    if db.execute("SELECT 1 FROM transactions WHERE scan_id = %s", (scan_id,)).fetchone():
        return error(409, "scan_closed")
    db.execute(
        "UPDATE scans SET closed_at = clock_timestamp() WHERE id = %s AND closed_at IS NULL",
        (scan_id,),
    )
    return "", 204


def booking_status(db, actor, key):
    result = db.execute(
        """SELECT response, status_code FROM booking_requests
           WHERE event_id = %s AND device_id = %s AND area = %s AND request_id = %s""",
        (*scoped(actor), key),
    ).fetchone()
    if not result or result["status_code"] is None:
        return error(404, "transaction_not_found")
    return result["response"], result["status_code"]


def book(db, actor, key, payload):
    event_id, device_id, area = scoped(actor)
    fingerprint = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).digest()
    reservation = db.execute(
        """INSERT INTO booking_requests (event_id, device_id, area, request_id, fingerprint)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (event_id, device_id, request_id) DO NOTHING RETURNING request_id""",
        (event_id, device_id, area, key, fingerprint),
    ).fetchone()
    if reservation is None:
        prior = db.execute(
            """SELECT area, fingerprint, response, status_code FROM booking_requests
               WHERE event_id = %s AND device_id = %s AND request_id = %s""",
            (event_id, device_id, key),
        ).fetchone()
        if prior["area"] != area or prior["fingerprint"] != fingerprint:
            return error(409, "idempotency_conflict")
        return prior["response"], prior["status_code"]

    response, status = apply_booking(db, actor, key, payload)
    db.execute(
        """UPDATE booking_requests SET response = %s, status_code = %s
           WHERE event_id = %s AND device_id = %s AND request_id = %s""",
        (Jsonb(response), status, event_id, device_id, key),
    )
    return response, status


def apply_booking(db, actor, key, payload):
    event_id, device_id, area = scoped(actor)
    kind = payload.get("kind")
    if kind not in ("topup", "refund", "sale"):
        return error(400, "invalid_request")
    if (kind == "sale" and area not in SALE_AREAS) or (kind != "sale" and area != "cash"):
        return error(403, "operation_forbidden")
    scan_id = uuid_value(payload.get("scan_id"))
    if scan_id is None:
        return error(400, "invalid_request")
    scan = db.execute(
        """SELECT uid, expires_at, closed_at FROM scans
           WHERE event_id = %s AND device_id = %s AND area = %s AND id = %s FOR UPDATE""",
        (event_id, device_id, area, scan_id),
    ).fetchone()
    if scan is None:
        return error(404, "scan_not_found")
    if scan["closed_at"] is not None:
        return error(409, "scan_closed")
    if db.execute("SELECT clock_timestamp() AS now").fetchone()["now"] >= scan["expires_at"]:
        return error(409, "scan_expired")

    payment_method = None
    sale_items = []
    if kind == "sale":
        sale_items, rejection = read_sale(db, actor, payload.get("items"))
        if rejection is not None:
            return rejection
        amount = sum(item["price_cents"] * item["quantity"] for item in sale_items)
    else:
        if payload.get("payment_method") != "cash":
            return error(409, "unsupported_payment_method")
        payment_method = "cash"
        amount = payload.get("amount_cents")

    if type(amount) is not int or not 1 <= amount <= MAX_BOOKING_CENTS:
        return error(400, "invalid_request")
    uid = scan["uid"]
    if kind == "topup":
        if amount % HALF_TOKEN_UNITS:
            return error(400, "invalid_token_step")
        db.execute(
            "INSERT INTO accounts (event_id, uid) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (event_id, uid),
        )
    account = db.execute(
        "SELECT balance_cents FROM accounts WHERE event_id = %s AND uid = %s FOR UPDATE",
        (event_id, uid),
    ).fetchone()
    if account is None:
        return error(404, "account_not_found")
    before = account["balance_cents"]
    after = before + amount if kind == "topup" else before - amount
    if after < 0:
        return error(409, "insufficient_balance")
    # A complete refund can return a historical balance outside the half-token grid.
    if kind == "refund" and amount % HALF_TOKEN_UNITS and after != 0:
        return error(400, "invalid_token_step")
    if after > MAX_BALANCE_CENTS:
        return error(409, "balance_limit")

    # The preliminary check provides a quick rejection. This check also covers lock waits.
    if db.execute("SELECT clock_timestamp() AS now").fetchone()["now"] >= scan["expires_at"]:
        return error(409, "scan_expired")

    transaction_id = db.execute(
        """INSERT INTO transactions (
               event_id, device_id, area, request_id, scan_id, auth_session_id, uid, kind,
               payment_method, amount_cents, balance_before_cents, balance_after_cents
           ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (event_id, device_id, area, key, scan_id, actor["session_id"], uid, kind,
         payment_method, amount, before, after),
    ).fetchone()["id"]
    for item in sale_items:
        db.execute(
            """INSERT INTO sale_items (event_id, transaction_id, product_id, product_name, quantity, unit_price_cents)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (event_id, transaction_id, item["id"], item["name"], item["quantity"], item["price_cents"]),
        )
    db.execute("UPDATE accounts SET balance_cents = %s WHERE event_id = %s AND uid = %s", (after, event_id, uid))
    db.execute("UPDATE scans SET closed_at = clock_timestamp() WHERE id = %s", (scan_id,))
    return {
        "id": str(transaction_id),
        "kind": kind,
        "amount_cents": amount,
        "balance_before_cents": before,
        "balance_after_cents": after,
    }, 200


def read_sale(db, actor, items):
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        return None, error(400, "invalid_request")
    selection = {}
    for item in items:
        if not isinstance(item, dict):
            return None, error(400, "invalid_request")
        product_id, quantity, price = (item.get(field) for field in ("product_id", "quantity", "unit_price_cents"))
        if (type(product_id) is not int or not 1 <= product_id <= 2_147_483_647
                or type(quantity) is not int or not 1 <= quantity <= 99
                or type(price) is not int or not 1 <= price <= MAX_BOOKING_CENTS
                or product_id in selection):
            return None, error(400, "invalid_request")
        selection[product_id] = quantity, price

    products = db.execute(
        """SELECT id, name, price_cents FROM products
           WHERE event_id = %s AND active AND %s = ANY(areas) AND id = ANY(%s)
           ORDER BY id FOR SHARE""",
        (actor["event_id"], actor["area"], list(selection)),
    ).fetchall()
    if len(products) != len(selection):
        return None, error(409, "product_unavailable")
    for product in products:
        quantity, expected_price = selection[product["id"]]
        if product["price_cents"] != expected_price:
            return None, error(409, "price_changed")
        product["quantity"] = quantity
    return products, None
