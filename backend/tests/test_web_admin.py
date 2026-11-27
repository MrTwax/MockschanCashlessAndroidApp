from base64 import b64encode
from html.parser import HTMLParser
import os
import re
import unittest
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict

from odentaler import connect, create_app, migrate


ORIGIN = "https://cashless.example.test"
PASSWORD = "Integration-only-" + uuid4().hex
AUTH = "Basic " + b64encode(f"admin:{PASSWORD}".encode()).decode()


class CredentialsPage(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.csrf = None
        self.feed(response.get_data(as_text=True))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("name") == "csrf_token":
            self.csrf = attributes.get("value")


class TestWebAdmin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ.get("ODENTALER_TEST_DATABASE_URL")
        if cls.dsn is None:
            raise unittest.SkipTest("Entbehrliche PostgreSQL-Testdatenbank erforderlich.")
        if not re.fullmatch(r"odentaler_test(?:_[a-z0-9]+)*", conninfo_to_dict(cls.dsn).get("dbname", "")):
            raise RuntimeError("Der Datenbankname muss mit odentaler_test beginnen.")
        migrate(cls.dsn)

    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "DATABASE_URL": self.dsn,
            "WEB_ADMIN_ORIGIN": ORIGIN,
            "WEB_ADMIN_PASSWORD": PASSWORD,
        })
        self.client = self.app.test_client()

    def get(self, path="/admin"):
        return self.client.get(path, base_url=ORIGIN, headers={"Authorization": AUTH})

    def post(self, path, data, *, origin=ORIGIN, csrf=True):
        if csrf:
            page = self.get()
            self.assertEqual(200, page.status_code)
            token = CredentialsPage(page).csrf
            self.assertTrue(token)
            data = {**data, "csrf_token": token}
        return self.client.post(
            path, base_url=ORIGIN, data=data,
            headers={"Authorization": AUTH, "Origin": origin},
        )

    def device_key(self, response):
        for candidate in re.findall(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])", response.get_data(as_text=True)):
            if self.bootstrap(candidate).status_code == 200:
                return candidate
        self.fail("Die Antwort hat keinen gültigen Gerätecode ausgegeben.")

    def bootstrap(self, key):
        return self.client.get("/v1/bootstrap", headers={"X-Device-Key": key})

    def test_configuration_authentication_and_csrf(self):
        disabled = create_app({
            "TESTING": True, "DATABASE_URL": self.dsn, "WEB_ADMIN_PASSWORD": None, "WEB_ADMIN_ORIGIN": None,
        }).test_client()
        self.assertEqual(404, disabled.get("/admin", base_url=ORIGIN).status_code)
        self.assertEqual(401, self.client.get("/admin", base_url=ORIGIN).status_code)
        self.assertEqual(401, self.client.get(
            "/admin", base_url=ORIGIN, headers={"Authorization": "Bearer " + PASSWORD},
        ).status_code)
        marker = f"CSRF-{uuid4()}"
        self.assertEqual(403, self.post("/admin/organizers", {"name": marker}, csrf=False).status_code)
        self.assertEqual(403, self.post(
            "/admin/organizers", {"name": marker}, origin="https://fremd.example.test",
        ).status_code)
        self.assertNotIn(marker, self.get().get_data(as_text=True))

    def test_provisioning_and_existing_android_api(self):
        name = f"Browser-Test {uuid4()}"
        self.assertEqual(303, self.post("/admin/organizers", {"name": name}).status_code)
        with connect(self.dsn) as db:
            organizer = db.execute("SELECT id FROM organizers WHERE name = %s", (name,)).fetchone()["id"]
        result = self.post("/admin/events", {
            "organizer_id": str(organizer), "name": name, "device_name": "Admin-Tablet",
            "cash_pin": "123456", "admin_pin": "654321",
        })
        self.assertEqual(201, result.status_code)
        self.assertIn("no-store", result.headers.get("Cache-Control", ""))
        self.assertIn('src="data:image/svg+xml;base64,', result.get_data(as_text=True))
        self.assertIn("img-src data:", result.headers.get("Content-Security-Policy", ""))
        first_key = self.device_key(result)
        event = self.bootstrap(first_key).get_json()["event_id"]
        path = f"/admin/events/{event}"
        self.assertNotIn(first_key, self.get(f"/admin?event_id={event}").get_data(as_text=True))

        self.assertEqual(303, self.post(f"{path}/settings", {
            "name": name, "active": "on", "scan_timeout_seconds": "90",
            "topup_amounts_tokens": "0,5; 5; 10", "wine": "on",
        }).status_code)
        configuration = self.bootstrap(first_key).get_json()
        self.assertIn("wine", configuration["areas"])
        self.assertEqual([50, 500, 1000], configuration["topup_amounts_cents"])

        result = self.post(f"{path}/devices", {"name": "Theke", "areas": ["drinks"]})
        self.assertEqual(201, result.status_code)
        second_key = self.device_key(result)
        self.assertEqual(["drinks"], self.bootstrap(second_key).get_json()["areas"])
        product = {"name": "Wasser", "category": "Getränke", "price_cents": "150",
                   "areas": ["drinks"], "sort_order": "0", "active": "on"}
        self.assertEqual(303, self.post(f"{path}/products", product).status_code)
        with connect(self.dsn) as db:
            product_id = db.execute("SELECT id FROM products WHERE event_id = %s", (event,)).fetchone()["id"]
            device_id = db.execute(
                "SELECT id FROM devices WHERE event_id = %s AND name = %s", (event, "Theke"),
            ).fetchone()["id"]
        self.assertEqual(303, self.post(f"{path}/products/{product_id}", {**product, "price_tokens": "2"}).status_code)
        session = self.client.post("/v1/session", json={"area": "drinks"}, headers={"X-Device-Key": second_key})
        self.assertEqual(200, session.status_code)
        catalog = self.client.get("/v1/products", headers={"Authorization": "Bearer " + session.get_json()["token"]})
        self.assertEqual(200, catalog.get_json()[0]["price_cents"])
        self.assertEqual(303, self.post(f"{path}/pins/cash", {"pin": "918273", "pin_repeat": "918273"}).status_code)
        new_pin = self.client.post("/v1/session", json={"area": "cash", "pin": "918273"},
                                   headers={"X-Device-Key": first_key})
        self.assertEqual(200, new_pin.status_code)
        self.assertEqual(303, self.post(f"{path}/devices/{device_id}/revoke", {}).status_code)
        self.assertEqual(401, self.bootstrap(second_key).status_code)

    def create_event(self):
        with connect(self.dsn) as db:
            organization = db.execute(
                "INSERT INTO organizers (name) VALUES ('Web integration') RETURNING id",
            ).fetchone()["id"]
        response = self.post("/admin/events", {
            "organizer_id": str(organization), "name": "Quellveranstaltung", "device_name": "Verwaltung",
            "cash_pin": "123456", "admin_pin": "654321",
        })
        self.assertEqual(201, response.status_code)
        key = self.device_key(response)
        return self.bootstrap(key).get_json()["event_id"], key

    def session(self, device_key, area, pin=None):
        response = self.client.post(
            "/v1/session", json={"area": area, "pin": pin}, headers={"X-Device-Key": device_key},
        )
        self.assertEqual(200, response.status_code, response.get_json())
        return {"Authorization": "Bearer " + response.get_json()["token"]}

    def booking(self, headers, order):
        scanned = self.client.post("/v1/scans", json={"uid": "A1B2C3D4"}, headers=headers)
        self.assertEqual(200, scanned.status_code, scanned.get_json())
        result = self.client.post("/v1/transactions", json={**order, "scan_id": scanned.get_json()["scan_id"]},
                                  headers={**headers, "Idempotency-Key": str(uuid4())})
        self.assertEqual(200, result.status_code, result.get_json())
        return result.get_json()

    def test_copy_preserves_configuration_and_excludes_bookings_and_devices(self):
        event, device_key = self.create_event()
        cash = self.session(device_key, "cash", "123456")
        self.booking(cash, {"kind": "topup", "amount_cents": 500, "payment_method": "cash"})
        with connect(self.dsn) as db:
            db.execute("UPDATE events SET scan_timeout_seconds = 95, topup_amounts_cents = '{50,150}' WHERE id = %s",
                       (event,))
            db.execute("UPDATE event_areas SET enabled = true WHERE event_id = %s AND area = 'wine'", (event,))
            original = db.execute(
                """INSERT INTO products (event_id, name, category, price_cents, areas, sort_order, image_url, active)
                   VALUES (%s, 'Archivpreis', 'Getränke', 175, '{drinks,wine}', 4, 'https://bilder.example.test/wasser', false)
                   RETURNING id""",
                (event,),
            ).fetchone()["id"]
        path = f"/admin/events/{event}"
        self.assertIn('value="1,75"', self.get(f"/admin?event_id={event}").get_data(as_text=True))
        edit = {"name": "Archivpreis geändert", "category": "Getränke", "price_tokens": "1,75",
                "areas": ["drinks", "wine"], "sort_order": "4"}
        self.assertEqual(303, self.post(f"{path}/products/{original}", edit).status_code)
        self.assertEqual(400, self.post(f"{path}/products/{original}", {**edit, "price_tokens": "1,74"}).status_code)
        copied = self.post(f"{path}/copy", {"name": "Kopie Probe", "cash_pin": "778899", "admin_pin": "998877"})
        self.assertEqual(303, copied.status_code)
        with connect(self.dsn) as db:
            clone = db.execute(
                """SELECT * FROM events WHERE name = 'Kopie Probe'
                   AND organizer_id = (SELECT organizer_id FROM events WHERE id = %s)""",
                (event,),
            ).fetchone()
            self.assertEqual((95, [50, 150]), (clone["scan_timeout_seconds"], clone["topup_amounts_cents"]))
            self.assertTrue(db.execute(
                "SELECT enabled FROM event_areas WHERE event_id = %s AND area = 'wine'", (clone["id"],),
            ).fetchone()["enabled"])
            product = db.execute("SELECT * FROM products WHERE event_id = %s", (clone["id"],)).fetchone()
            self.assertNotEqual(original, product["id"])
            self.assertEqual(("Archivpreis geändert", 175, ["drinks", "wine"], 4, False),
                             (product["name"], product["price_cents"], product["areas"], product["sort_order"], product["active"]))
            self.assertEqual("https://bilder.example.test/wasser", product["image_url"])
            counts = db.execute(
                """SELECT (SELECT count(*) FROM devices WHERE event_id = %s) AS devices,
                          (SELECT count(*) FROM accounts WHERE event_id = %s) AS accounts,
                          (SELECT count(*) FROM transactions WHERE event_id = %s) AS journal,
                          (SELECT count(*) FROM booking_requests WHERE event_id = %s) AS requests""",
                (clone["id"],) * 4,
            ).fetchone()
            self.assertEqual({"devices": 0, "accounts": 0, "journal": 0, "requests": 0}, counts)
        new_key = self.device_key(self.post(f"/admin/events/{clone['id']}/devices", {"name": "Kopiekasse", "areas": ["cash"]}))
        self.session(new_key, "cash", "778899")
        bad_pin = self.client.post("/v1/session", json={"area": "cash", "pin": "123456"},
                                   headers={"X-Device-Key": new_key})
        self.assertEqual(401, bad_pin.status_code)

    def test_delete_only_unbooked_records(self):
        empty_event, empty_key = self.create_event()
        blank_path = f"/admin/events/{empty_event}"
        product = {"name": "Wasser", "category": "Getränke", "price_tokens": "0,5",
                   "areas": ["drinks"], "sort_order": "0", "active": "on"}
        self.assertEqual(303, self.post(f"{blank_path}/products", product).status_code)
        with connect(self.dsn) as db:
            unbooked_product = db.execute(
                "SELECT id, price_cents FROM products WHERE event_id = %s", (empty_event,),
            ).fetchone()
        self.assertEqual(50, unbooked_product["price_cents"])
        self.assertEqual(400, self.post(f"{blank_path}/products", {**product, "price_tokens": "0,25"}).status_code)
        delete_product = f"{blank_path}/products/{unbooked_product['id']}/delete"
        self.assertEqual(400, self.post(delete_product, {}).status_code)
        self.assertEqual(303, self.post(delete_product, {"confirm": "yes"}).status_code)
        self.assertEqual(404, self.post(delete_product, {"confirm": "yes"}).status_code)
        cash = self.session(empty_key, "cash", "123456")
        self.assertEqual(200, self.client.post("/v1/scans", json={"uid": "A1B2C3D4"}, headers=cash).status_code)
        self.assertEqual(400, self.post(f"{blank_path}/delete", {}).status_code)
        self.assertEqual(303, self.post(f"{blank_path}/delete", {"confirm": "yes"}).status_code)
        self.assertEqual(401, self.bootstrap(empty_key).status_code)
        self.assertEqual(404, self.get(f"/admin?event_id={empty_event}").status_code)

        sold_event, sold_key = self.create_event()
        history_path = f"/admin/events/{sold_event}"
        self.assertEqual(303, self.post(f"{history_path}/products", product).status_code)
        cash = self.session(sold_key, "cash", "123456")
        drinks = self.session(sold_key, "drinks")
        self.booking(cash, {"kind": "topup", "amount_cents": 50, "payment_method": "cash"})
        catalog = self.client.get("/v1/products", headers=drinks).get_json()
        sold_id = catalog[0]["id"]
        receipt = self.booking(drinks, {
            "kind": "sale", "items": [{"product_id": sold_id, "quantity": 1, "unit_price_cents": 50}],
        })
        self.assertEqual(0, receipt["balance_after_cents"])
        self.assertEqual(409, self.post(f"{history_path}/products/{sold_id}/delete", {"confirm": "yes"}).status_code)
        self.assertEqual(409, self.post(f"{history_path}/delete", {"confirm": "yes"}).status_code)
        self.assertEqual(303, self.post(f"{history_path}/products/{sold_id}", {**product, "active": ""}).status_code)
        self.assertEqual([], self.client.get("/v1/products", headers=drinks).get_json())
        with connect(self.dsn) as db:
            self.assertEqual(50, db.execute(
                "SELECT unit_price_cents FROM sale_items WHERE event_id = %s AND product_id = %s", (sold_event, sold_id),
            ).fetchone()["unit_price_cents"])

