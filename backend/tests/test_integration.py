from concurrent.futures import ThreadPoolExecutor
import os
import re
import threading
import unittest
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from werkzeug.security import generate_password_hash

from ledger import MAX_BALANCE_CENTS
from odentaler import AREAS, OPTIONAL_AREAS, PIN_HASH_METHOD, connect, create_app, insert_device, migrate


TEST_PIN = "7482"
UID = "04A1B2C3"
TOPUP = "topup"


class PostgresIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get("ODENTALER_TEST_DATABASE_URL")
        if cls.dsn is None:
            raise unittest.SkipTest("ODENTALER_TEST_DATABASE_URL für eine entbehrliche PostgreSQL-Datenbank setzen.")
        database = conninfo_to_dict(cls.dsn).get("dbname", "")
        if not re.fullmatch(r"odentaler_test(?:_[a-z0-9]+)*", database):
            raise RuntimeError("Der Name der Testdatenbank muss mit odentaler_test beginnen.")
        migrate(cls.dsn)
        cls.app = create_app({"TESTING": True, "TEST_PINS": True, "DATABASE_URL": cls.dsn})
        cls.pin_hash = generate_password_hash(TEST_PIN, method=PIN_HASH_METHOD)

    def setUp(self):
        with connect(self.dsn) as db:
            self.organization = self.create_organizer(db)
            self.event = self.create_event(db, self.organization)
            self.device, self.key = insert_device(db, self.event, "Kasse und Theke", AREAS)
            self.second_device, self.second_key = insert_device(db, self.event, "Zweite Theke", ("drinks",))
            self.beer = self.create_product(db, self.event, "Bier", 250, ["drinks", "mobile"])
            self.water = self.create_product(db, self.event, "Wasser", 150, ["drinks"])
        self.client = self.app.test_client()
        self.cash = self.session("cash")
        self.drinks = self.session("drinks")

    def create_organizer(self, db):
        return db.execute(
            "INSERT INTO organizers (name) VALUES ('Testverein') RETURNING id",
        ).fetchone()["id"]

    def create_event(self, db, organization):
        event = db.execute(
            "INSERT INTO events (organizer_id, name) VALUES (%s, 'Testveranstaltung') RETURNING id",
            (organization,),
        ).fetchone()["id"]
        for area in AREAS:
            db.execute(
                "INSERT INTO event_areas VALUES (%s, %s, %s)",
                (event, area, area not in OPTIONAL_AREAS),
            )
        for area in ("cash", "admin"):
            db.execute("INSERT INTO pin_roles (event_id, area, pin_hash) VALUES (%s, %s, %s)", (event, area, self.pin_hash))
        return event

    def create_product(self, db, event, name, price, areas):
        return db.execute(
            "INSERT INTO products (event_id, name, price_cents, areas) VALUES (%s, %s, %s, %s) RETURNING id",
            (event, name, price, areas),
        ).fetchone()["id"]

    def session(self, area, key=None):
        response = self.client.post(
            "/v1/session",
            headers={"X-Device-Key": key or self.key},
            json={"area": area, "pin": TEST_PIN},
        )
        self.assertEqual(200, response.status_code, response.get_json())
        return {"Authorization": f"Bearer {response.get_json()['token']}"}

    def scan(self, scope, uid=UID):
        response = self.client.post("/v1/scans", headers=scope, json={"uid": uid})
        self.assertEqual(200, response.status_code, response.get_json())
        return response.get_json()

    def post_booking(self, scope, body, key=None, client=None):
        return (client or self.client).post(
            "/v1/transactions",
            headers={**scope, "Idempotency-Key": str(key or uuid4())},
            json=body,
        )

    def cash_order(self, scan, amount, kind=TOPUP):
        return {"kind": kind, "scan_id": scan["scan_id"], "amount_cents": amount, "payment_method": "cash"}

    def sale_order(self, scan, *items):
        return {
            "kind": "sale",
            "scan_id": scan["scan_id"],
            "items": [{"product_id": item, "quantity": quantity, "unit_price_cents": price}
                      for item, quantity, price in items],
        }

    def fund(self, amount):
        response = self.post_booking(self.cash, self.cash_order(self.scan(self.cash), amount))
        self.assertEqual(200, response.status_code, response.get_json())
        return response.get_json()

    def assert_error(self, status, code, response):
        self.assertEqual(status, response.status_code, response.get_json())
        self.assertEqual({"error": code}, response.get_json())

    def test_reports_separate_cash_movements_and_historical_sales(self):
        self.fund(1500)
        sale = self.post_booking(self.drinks, self.sale_order(self.scan(self.drinks), (self.beer, 2, 250)))
        self.assertEqual(200, sale.status_code)
        refund = self.post_booking(self.cash, self.cash_order(self.scan(self.cash), 250, "refund"))
        self.assertEqual(200, refund.status_code)
        with connect(self.dsn) as db:
            db.execute("UPDATE products SET price_cents = 999 WHERE id = %s", (self.beer,))
            db.execute(
                "UPDATE events SET name = 'Andere Veranstaltung' WHERE id <> %s AND organizer_id = %s",
                (self.event, self.organization),
            )
            clock = db.execute(
                "SELECT clock_timestamp() - interval '1 day' AS start, clock_timestamp() + interval '1 day' AS finish"
            ).fetchone()
        interval = {"from": clock["start"].isoformat(), "until": clock["finish"].isoformat()}
        admin = self.session("admin")
        report = self.client.get("/v1/admin/report", headers=admin, query_string=interval)
        self.assertEqual(200, report.status_code)
        data = report.get_json()
        self.assertEqual(3, data["transaction_count"])
        self.assertEqual(1500, data["cash_topups_cents"])
        self.assertEqual(250, data["cash_refunds_cents"])
        self.assertEqual(500, data["sales_cents"])
        self.assertEqual(750, data["outstanding_balance_cents"])
        self.assertEqual([{"area": "drinks", "sales_cents": 500}], data["by_area"])
        self.assertEqual(500, data["by_product"][0]["sales_cents"])
        self.assertEqual(500, data["by_device"][0]["sales_cents"])
        export = self.client.get("/v1/admin/transactions.csv", headers=admin, query_string=interval)
        self.assertEqual(200, export.status_code)
        self.assertEqual("text/csv", export.mimetype)
        body = export.get_data(as_text=True)
        self.assertEqual(4, len(body.splitlines()))
        self.assertEqual(1, body.count(sale.get_json()["id"]))
        self.assertNotIn(UID, body)

    def test_reports_reject_other_roles_and_invalid_intervals(self):
        for path in ("/v1/admin/report", "/v1/admin/transactions.csv"):
            self.assert_error(403, "operation_forbidden", self.client.get(path, headers=self.drinks))
            self.assert_error(400, "invalid_report_period", self.client.get(path, headers=self.session("admin")))

    def test_topup_partial_refund_and_card_rejected(self):
        account = self.scan(self.cash, UID.lower())
        self.assertEqual(0, account["balance_cents"])
        card = {**self.cash_order(account, 500), "payment_method": "card"}
        self.assert_error(409, "unsupported_payment_method", self.post_booking(self.cash, card))
        self.assertEqual(500, self.fund(500)["balance_after_cents"])
        response = self.post_booking(self.cash, self.cash_order(self.scan(self.cash), 175, "refund"))
        self.assertEqual(200, response.status_code)
        receipt = response.get_json()
        self.assertEqual((500, 325), (receipt["balance_before_cents"], receipt["balance_after_cents"]))
        self.assert_error(
            409, "insufficient_balance",
            self.post_booking(self.cash, self.cash_order(self.scan(self.cash), 326, "refund")),
        )

    def test_sale_multiple_products_and_price_snapshot(self):
        self.fund(1500)
        order = self.sale_order(self.scan(self.drinks), (self.beer, 2, 250), (self.water, 3, 150))
        response = self.post_booking(self.drinks, order)
        self.assertEqual(200, response.status_code, response.get_json())
        receipt = response.get_json()
        self.assertEqual((950, 550), (receipt["amount_cents"], receipt["balance_after_cents"]))
        with connect(self.dsn) as db:
            db.execute("UPDATE products SET price_cents = 999 WHERE id = %s", (self.beer,))
            rows = db.execute(
                "SELECT quantity, unit_price_cents FROM sale_items WHERE transaction_id = %s ORDER BY product_id",
                (receipt["id"],),
            ).fetchall()
        self.assertEqual([(2, 250), (3, 150)], [(row["quantity"], row["unit_price_cents"]) for row in rows])
        with self.assertRaises(psycopg.errors.RaiseException):
            with connect(self.dsn) as db:
                db.execute("UPDATE transactions SET amount_cents = 1 WHERE id = %s", (receipt["id"],))
        stale = self.sale_order(self.scan(self.drinks), (self.beer, 1, 250))
        self.assert_error(409, "price_changed", self.post_booking(self.drinks, stale))
        self.assertEqual(550, self.scan(self.drinks)["balance_cents"])

    def test_scan_deduplication_cancellation_expiry_and_next_customer(self):
        self.fund(500)
        first = self.scan(self.drinks)
        self.assertEqual(first["scan_id"], self.scan(self.drinks)["scan_id"])
        self.assertEqual(204, self.client.delete(f"/v1/scans/{first['scan_id']}", headers=self.drinks).status_code)
        self.assert_error(
            409, "scan_closed", self.post_booking(self.drinks, self.sale_order(first, (self.beer, 1, 250))),
        )
        second = self.scan(self.drinks)
        self.assertNotEqual(first["scan_id"], second["scan_id"])
        with connect(self.dsn) as db:
            db.execute("UPDATE scans SET expires_at = clock_timestamp() WHERE id = %s", (second["scan_id"],))
        self.assert_error(
            409, "scan_expired", self.post_booking(self.drinks, self.sale_order(second, (self.beer, 1, 250))),
        )
        third = self.scan(self.drinks)
        result = self.post_booking(self.drinks, self.sale_order(third, (self.beer, 1, 250)))
        self.assertEqual(250, result.get_json()["balance_after_cents"])
        self.assertNotEqual(third["scan_id"], self.scan(self.drinks)["scan_id"])

    def test_lost_response_then_status_retry_and_payload_conflict(self):
        key = uuid4()
        body = self.cash_order(self.scan(self.cash), 500)
        self.assert_error(
            404, "transaction_not_found", self.client.get(f"/v1/transactions/{key}", headers=self.cash),
        )
        sent = self.post_booking(self.cash, body, key)
        self.assertEqual(200, sent.status_code)

        fresh_client = self.app.test_client()
        fresh_session = self.session("cash")
        recovered = fresh_client.get(f"/v1/transactions/{key}", headers=fresh_session)
        self.assertEqual(sent.get_json(), recovered.get_json())
        replay = self.post_booking(fresh_session, body, key, fresh_client)
        self.assertEqual(sent.get_json(), replay.get_json())
        self.assert_error(
            409, "idempotency_conflict", self.post_booking(self.cash, {**body, "amount_cents": 800}, key),
        )
        self.assert_error(404, "transaction_not_found", self.client.get(f"/v1/transactions/{key}", headers=self.drinks))
        self.assertEqual(500, self.scan(self.cash)["balance_cents"])

    def test_rejected_outcome_does_not_change_after_topup(self):
        self.fund(100)
        body = self.sale_order(self.scan(self.drinks), (self.beer, 1, 250))
        key = uuid4()
        self.assert_error(409, "insufficient_balance", self.post_booking(self.drinks, body, key))
        self.fund(300)
        self.assert_error(409, "insufficient_balance", self.post_booking(self.drinks, body, key))
        self.assert_error(
            409, "insufficient_balance", self.client.get(f"/v1/transactions/{key}", headers=self.drinks),
        )

    def test_parallel_devices_preserve_non_negative_balance(self):
        self.fund(400)
        second_scope = self.session("drinks", self.second_key)
        sale1 = self.sale_order(self.scan(self.drinks), (self.beer, 1, 250))
        sale2 = self.sale_order(self.scan(second_scope), (self.beer, 1, 250))
        barrier = threading.Barrier(2)

        def submit(operation):
            scope, body = operation
            barrier.wait(timeout=5)
            response = self.post_booking(scope, body, client=self.app.test_client())
            return response.status_code, response.get_json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = dict(pool.map(submit, [(self.drinks, sale1), (second_scope, sale2)]))
        self.assertEqual({200, 409}, set(results))
        self.assertEqual("insufficient_balance", results[409]["error"])
        self.assertEqual(150, results[200]["balance_after_cents"])

    def test_simultaneous_same_key_returns_one_receipt(self):
        key = uuid4()
        body = self.cash_order(self.scan(self.cash), 650)
        barrier = threading.Barrier(2)

        def submit():
            barrier.wait(timeout=5)
            response = self.post_booking(self.cash, body, key, client=self.app.test_client())
            self.assertEqual(200, response.status_code, response.get_json())
            return response.get_json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(submit), pool.submit(submit)]
            results = [future.result(timeout=15) for future in requests]
        self.assertEqual(results[0], results[1])
        self.assertEqual(650, self.scan(self.cash)["balance_cents"])

    def test_event_and_organizer_isolation(self):
        self.fund(400)
        key = uuid4()
        sale = self.post_booking(self.drinks, self.sale_order(self.scan(self.drinks), (self.beer, 1, 250)), key)
        self.assertEqual(200, sale.status_code)
        with connect(self.dsn) as db:
            other_organizer = self.create_organizer(db)
            other_devices = [
                insert_device(db, self.create_event(db, organizer), "Fremdgerät", AREAS)[1]
                for organizer in (self.organization, other_organizer)
            ]
        for other_device in other_devices:
            foreign_cash = self.session("cash", other_device)
            foreign_drinks = self.session("drinks", other_device)
            self.assertEqual(0, self.scan(foreign_cash)["balance_cents"])
            self.assertEqual([], self.client.get("/v1/products", headers=foreign_drinks).get_json())
            self.assert_error(
                404, "transaction_not_found",
                self.client.get(f"/v1/transactions/{key}", headers=foreign_drinks),
            )
            self.assert_error(
                404, "account_not_found", self.client.post("/v1/scans", headers=foreign_drinks, json={"uid": UID}),
            )

    def test_optional_areas_rights_and_device_revocation(self):
        admin = self.session("admin")
        self.assert_error(403, "operation_forbidden", self.client.get("/v1/admin/areas", headers=self.drinks))
        self.assert_error(
            403, "area_unavailable",
            self.client.post("/v1/session", headers={"X-Device-Key": self.second_key}, json={"area": "cash", "pin": TEST_PIN}),
        )
        for area in OPTIONAL_AREAS:
            self.assertNotIn(area, self.client.get("/v1/bootstrap", headers={"X-Device-Key": self.key}).get_json()["areas"])
            route = f"/v1/admin/areas/{area}"
            self.assertEqual(200, self.client.put(route, headers=admin, json={"enabled": True}).status_code)
            self.assertIn(area, self.client.get("/v1/bootstrap", headers={"X-Device-Key": self.key}).get_json()["areas"])
            previous_session = self.session(area)
            self.assertEqual(200, self.client.put(route, headers=admin, json={"enabled": False}).status_code)
            self.assert_error(401, "session_unauthorized", self.client.get("/v1/products", headers=previous_session))
        second_scope = self.session("drinks", self.second_key)
        with connect(self.dsn) as db:
            db.execute("UPDATE devices SET revoked_at = clock_timestamp() WHERE id = %s", (self.second_device,))
        self.assert_error(401, "session_unauthorized", self.client.get("/v1/products", headers=second_scope))

    def test_cli_product_and_event_edits_are_scoped(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=[
            "edit-product", "--event-id", str(self.event), "--product-id", str(self.beer),
            "--name", "Bier klein", "--category", "Getränke", "--price-cents", "200",
            "--area", "drinks", "--sort-order", "-1",
        ])
        self.assertEqual(0, result.exit_code, result.output)
        catalog = self.client.get("/v1/products", headers=self.drinks).get_json()
        self.assertEqual(("Bier klein", 200), (catalog[0]["name"], catalog[0]["price_cents"]))

        result = runner.invoke(args=[
            "edit-product", "--event-id", str(uuid4()), "--product-id", str(self.beer), "--inactive",
        ])
        self.assertEqual(1, result.exit_code)
        result = runner.invoke(args=[
            "edit-product", "--event-id", str(self.event), "--product-id", str(self.beer), "--inactive",
        ])
        self.assertEqual(0, result.exit_code, result.output)
        self.assertEqual([self.water], [p["id"] for p in self.client.get("/v1/products", headers=self.drinks).get_json()])

        result = runner.invoke(args=[
            "configure-event", "--event-id", str(self.event), "--name", "Sommerfest",
            "--scan-timeout-seconds", "90", "--topup-cents", "600", "--topup-cents", "1200",
        ])
        self.assertEqual(0, result.exit_code, result.output)
        bootstrap = self.client.get("/v1/bootstrap", headers={"X-Device-Key": self.key}).get_json()
        self.assertEqual(("Sommerfest", 90, [600, 1200]),
                         (bootstrap["event_name"], bootstrap["scan_timeout_seconds"], bootstrap["topup_amounts_cents"]))
        result = runner.invoke(args=["configure-event", "--event-id", str(self.event), "--inactive"])
        self.assertEqual(0, result.exit_code, result.output)
        self.assert_error(401, "session_unauthorized", self.client.get("/v1/products", headers=self.drinks))

    def test_cash_pin_lockout_is_server_enforced(self):
        for attempt in range(5):
            response = self.client.post(
                "/v1/session", headers={"X-Device-Key": self.key}, json={"area": "cash", "pin": "0000"},
            )
            self.assert_error(401, "invalid_pin", response) if attempt < 4 else self.assert_error(429, "pin_locked", response)
        self.assert_error(
            429, "pin_locked",
            self.client.post("/v1/session", headers={"X-Device-Key": self.key}, json={"area": "cash", "pin": TEST_PIN}),
        )
        self.session("admin")

    def test_cross_device_scan_and_integer_bounds(self):
        self.fund(1000)
        with connect(self.dsn) as db:
            db.execute("UPDATE accounts SET balance_cents = %s WHERE event_id = %s AND uid = %s",
                       (MAX_BALANCE_CENTS, self.event, UID))
        scan = self.scan(self.cash)
        self.assert_error(409, "balance_limit", self.post_booking(self.cash, self.cash_order(scan, 1)))
        self.assert_error(400, "invalid_request", self.post_booking(self.cash, self.cash_order(scan, 0.5)))
        second_scope = self.session("drinks", self.second_key)
        order = self.sale_order(self.scan(self.drinks), (self.beer, 1, 250))
        self.assert_error(404, "scan_not_found", self.post_booking(second_scope, order))
