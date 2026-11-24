import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
import re

from flask import Response, request

from ledger import error


TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})")
EXPORT_LIMIT = 10_000


def report_range():
    start_text = request.args.get("from", "")
    end_text = request.args.get("until", "")
    if not TIMESTAMP.fullmatch(start_text) or not TIMESTAMP.fullmatch(end_text):
        return None
    try:
        start, end = (
            datetime.fromisoformat(value).astimezone(timezone.utc)
            for value in (start_text, end_text)
        )
    except (ValueError, OverflowError):
        return None
    return (start, end) if timedelta(0) < end - start <= timedelta(days=31) else None


def register_reporting(app, with_session):
    @app.get("/v1/admin/report")
    @with_session
    def admin_report(db, actor):
        if actor["area"] != "admin":
            return error(403, "operation_forbidden")
        interval = report_range()
        if interval is None:
            return error(400, "invalid_report_period")
        event_id = actor["event_id"]
        return db.execute(
            """WITH period AS (
                 SELECT * FROM transactions
                 WHERE event_id = %s AND created_at >= %s AND created_at < %s
               ), by_area AS (
                 SELECT area, SUM(amount_cents) AS sales_cents
                 FROM period WHERE kind = 'sale' GROUP BY area
               ), by_product AS (
                 SELECT s.product_id, s.product_name, SUM(s.quantity) AS quantity,
                        SUM(s.quantity::bigint * s.unit_price_cents) AS sales_cents
                 FROM period p JOIN sale_items s ON (s.event_id, s.transaction_id) = (p.event_id, p.id)
                 GROUP BY s.product_id, s.product_name
               ), by_device AS (
                 SELECT p.device_id, d.name, SUM(amount_cents) AS sales_cents
                 FROM period p JOIN devices d ON (d.event_id, d.id) = (p.event_id, p.device_id)
                 WHERE p.kind = 'sale' GROUP BY p.device_id, d.name
               )
               SELECT COUNT(*) AS transaction_count,
                      COALESCE(SUM(amount_cents) FILTER (WHERE kind = 'topup'), 0)::bigint AS cash_topups_cents,
                      COALESCE(SUM(amount_cents) FILTER (WHERE kind = 'refund'), 0)::bigint AS cash_refunds_cents,
                      COALESCE(SUM(amount_cents) FILTER (WHERE kind = 'sale'), 0)::bigint AS sales_cents,
                      COALESCE((SELECT SUM(balance_cents) FROM accounts WHERE event_id = %s), 0)::bigint
                          AS outstanding_balance_cents,
                      COALESCE((SELECT jsonb_agg(by_area ORDER BY area) FROM by_area), '[]') AS by_area,
                      COALESCE((SELECT jsonb_agg(by_product ORDER BY product_id, product_name) FROM by_product), '[]')
                          AS by_product,
                      COALESCE((SELECT jsonb_agg(by_device ORDER BY device_id) FROM by_device), '[]') AS by_device
               FROM period""",
            (event_id, *interval, event_id),
        ).fetchone()

    @app.get("/v1/admin/transactions.csv")
    @with_session
    def export_transactions(db, actor):
        if actor["area"] != "admin":
            return error(403, "operation_forbidden")
        interval = report_range()
        if interval is None:
            return error(400, "invalid_report_period")
        rows = db.execute(
            """SELECT id, created_at, kind, payment_method, area, device_id, amount_cents,
                      balance_before_cents, balance_after_cents
               FROM transactions WHERE event_id = %s AND created_at >= %s AND created_at < %s
               ORDER BY created_at, id LIMIT %s""",
            (actor["event_id"], *interval, EXPORT_LIMIT + 1),
        ).fetchall()
        if len(rows) > EXPORT_LIMIT:
            return error(422, "export_limit_exceeded")
        output = StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow((
            "Transaktion", "Zeitpunkt (UTC)", "Vorgang", "Zahlungsart", "Bereich", "Gerät",
            "Betrag (Token)", "Guthaben vorher (Token)", "Guthaben nachher (Token)",
        ))
        for row in rows:
            writer.writerow((
                row["id"], row["created_at"].astimezone(timezone.utc).isoformat(),
                row["kind"], row["payment_method"], row["area"], row["device_id"],
                *(format(Decimal(row[field]).scaleb(-2), "f").replace(".", ",")
                  for field in ("amount_cents", "balance_before_cents", "balance_after_cents")),
            ))
        return Response(
            output.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="odentaler-transaktionen.csv"',
                     "Cache-Control": "no-store"},
        )
