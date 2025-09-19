# --- path/bootstrap (keep this at the very top) ---
from pathlib import Path
import sys, importlib.util

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"  # adjust if your code isn't in src/

# 1) Prefer adding search paths (works for normal imports)
for p in (SRC, ROOT):
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

def _load_module(name, file_path):
    """
    Fallback: force-load a module by path. IMPORTANT: register in sys.modules
    *before* exec so decorators (like @dataclass) can resolve __module__.
    """
    spec = importlib.util.spec_from_file_location(name, file_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"Cannot load {name} from {file_path}"
    sys.modules[name] = mod        # register FIRST
    spec.loader.exec_module(mod)   # then execute
    return mod

# 2) Try normal imports; if they fail, load by absolute path from src/
try:
    import dao  # noqa: F401
except ModuleNotFoundError:
    dao = _load_module("dao", (SRC / "dao.py"))

try:
    import app  # noqa: F401
except ModuleNotFoundError:
    app = _load_module("app", (SRC / "app.py"))

try:
    import payment_service  # noqa: F401
except ModuleNotFoundError:
    payment_service = _load_module("payment_service", (SRC / "payment_service.py"))
# --- end path/bootstrap ---

import os
import sqlite3
import tempfile
import unittest
import importlib

# IMPORTANT: import dao first so we can reset its thread-local connection safely
from dao import UserDAO, ProductDAO, SaleDAO, PaymentDAO, SaleItemData, get_request_connection

# Now import the business logic and payment service
from app import RetailApp
from payment_service import PaymentService


def fresh_db():
    """
    Create a fresh temporary DB file, point RETAIL_DB_PATH at it, and reset the
    dao thread-local connection so tests are fully isolated.
    """
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    os.environ["RETAIL_DB_PATH"] = tmp.name

    # Reset the cached thread-local connection if it exists
    if hasattr(dao, "_thread_local") and getattr(dao._thread_local, "conn", None):
        try:
            dao._thread_local.conn.close()
        except Exception:
            pass
        dao._thread_local.conn = None

    # (Re)import modules that read globals at import time, just to be safe
    importlib.reload(dao)
    importlib.reload(app)
    importlib.reload(__import__("payment_service"))

    return tmp.name


class TestBusinessLogic(unittest.TestCase):
    """
    Business-logic tests (no web server): registration, cart, totals, checkout.
    Uses the real DAOs against a temp SQLite file.
    """

    def setUp(self):
        self.db_path = fresh_db()
        # Build app AFTER resetting DB
        self.app = app.RetailApp()
        # Seed: user + product
        self.user = "alice"
        self.pwd = "secret"
        self.app.user_dao.register_user(self.user, self.pwd)
        # Make sure login works and sets current user id internally
        self.assertTrue(self.app.login(self.user, self.pwd))

        # One product in stock
        self.prod_id = self.app.product_dao.add_product("Widget", 9.99, 5)

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except FileNotFoundError:
            pass

    def test_add_to_cart_and_checkout_card_success(self):
        # Add to cart
        ok, msg = self.app.add_to_cart(self.prod_id, 2)
        self.assertTrue(ok, msg)
        totals = self.app.compute_cart_totals()
        self.assertAlmostEqual(totals.subtotal, 2 * 9.99, places=2)
        self.assertAlmostEqual(totals.total, totals.subtotal, places=2)

        # Card should ALWAYS succeed per PaymentService spec
        ok, receipt = self.app.checkout("Card")
        self.assertTrue(ok, f"Checkout failed unexpectedly: {receipt}")
        # Receipt should include basics
        self.assertIn("Sale ID:", receipt)
        self.assertIn("Payment Method: Card", receipt)
        self.assertIn("Payment Ref: ", receipt)

        # Stock decremented
        p = self.app.product_dao.get_product(self.prod_id)
        self.assertIsNotNone(p)
        self.assertEqual(p.stock, 5 - 2)

        # Payment recorded in DB
        conn = get_request_connection()
        row = conn.execute("SELECT COUNT(*) FROM Payment;").fetchone()
        self.assertEqual(row[0], 1)

        # Cart cleared after success
        self.assertEqual(len(self.app.view_cart()), 0)

    def test_checkout_cash_fails_and_does_not_persist(self):
        # Add 1 item and try to pay cash (should always fail)
        ok, msg = self.app.add_to_cart(self.prod_id, 1)
        self.assertTrue(ok, msg)

        ok, reason = self.app.checkout("Cash")
        self.assertFalse(ok)
        self.assertIn("Cash payments", reason)

        # Stock unchanged, no sale, no payment
        p = self.app.product_dao.get_product(self.prod_id)
        self.assertEqual(p.stock, 5)

        conn = get_request_connection()
        sale_count = conn.execute("SELECT COUNT(*) FROM Sale;").fetchone()[0]
        pay_count = conn.execute("SELECT COUNT(*) FROM Payment;").fetchone()[0]
        self.assertEqual(sale_count, 0)
        self.assertEqual(pay_count, 0)

        # Cart remains (since failure), user can try again
        self.assertGreaterEqual(len(self.app.view_cart()), 1)

    def test_add_to_cart_validation(self):
        # Non-existing product
        ok, msg = self.app.add_to_cart(9999, 1)
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

        # Non-positive qty
        ok, msg = self.app.add_to_cart(self.prod_id, 0)
        self.assertFalse(ok)
        self.assertIn("quantity", msg.lower())

        # Over stock
        ok, msg = self.app.add_to_cart(self.prod_id, 999)
        self.assertFalse(ok)
        self.assertIn("stock", msg.lower())


class TestDatabaseIntegration(unittest.TestCase):
    """
    Integration tests at the DAO level: tables, FK integrity, Sale/SaleItem/Payment,
    product updates & admin flags.
    """

    def setUp(self):
        self.db_path = fresh_db()
        # Instantiate DAOs (auto-creates tables)
        self.user_dao = UserDAO()
        self.product_dao = ProductDAO()
        self.sale_dao = SaleDAO()
        self.payment_dao = PaymentDAO()
        self.conn = get_request_connection()

        # Seed a user and a couple products
        self.user_dao.register_user("admin", "pw")
        self.user_dao.set_admin("admin", True)
        self.uid = self.user_dao.authenticate("admin", "pw")
        self.p1 = self.product_dao.add_product("A", 3.50, 10)
        self.p2 = self.product_dao.add_product("B", 1.25, 4)

    def tearDown(self):
        try:
            # Close and delete DB file
            # Close thread-local connection if present
            if hasattr(dao._thread_local, "conn") and dao._thread_local.conn:
                try:
                    dao._thread_local.conn.close()
                except Exception:
                    pass
                dao._thread_local.conn = None
            os.unlink(self.db_path)
        except FileNotFoundError:
            pass

    def test_admin_flag_and_listing(self):
        self.assertTrue(self.user_dao.is_admin("admin"))
        products = self.product_dao.list_products()
        self.assertEqual([p.id for p in products], [self.p1, self.p2])

    def test_update_stock_commits(self):
        # Update and immediately read back
        self.product_dao.update_stock(self.p1, 7)
        p = self.product_dao.get_product(self.p1)
        self.assertEqual(p.stock, 7)

    def test_sale_items_payment_and_fk_integrity(self):
        # Create a sale with two items
        items = [
            SaleItemData(product_id=self.p1, quantity=2, unit_price=3.50),
            SaleItemData(product_id=self.p2, quantity=1, unit_price=1.25),
        ]
        sale_id = self.sale_dao.create_sale(
            user_id=self.uid,
            items=items,
            subtotal=2 * 3.50 + 1 * 1.25,
            total=2 * 3.50 + 1 * 1.25,
            status="Completed",
        )

        # Record a payment
        pay_id = self.payment_dao.record_payment(
            sale_id=sale_id,
            method="Card",
            reference="TESTREF",
            amount=8.25,
            status="Approved",
        )

        # Verify rows exist
        srow = self.conn.execute("SELECT id, user_id, total FROM Sale WHERE id=?", (sale_id,)).fetchone()
        self.assertIsNotNone(srow)
        prow = self.conn.execute("SELECT id, sale_id, status FROM Payment WHERE id=?", (pay_id,)).fetchone()
        self.assertIsNotNone(prow)

        item_rows = self.conn.execute("SELECT COUNT(*) FROM SaleItem WHERE sale_id=?", (sale_id,)).fetchone()
        self.assertEqual(item_rows[0], 2)

        # FK integrity: deleting a referenced product should raise an IntegrityError
        with self.assertRaises(sqlite3.IntegrityError):
            self.product_dao.delete_product(self.p1)

    def test_get_product_absent_returns_none(self):
        self.assertIsNone(self.product_dao.get_product(999999))


if __name__ == "__main__":
    unittest.main(verbosity=2)
