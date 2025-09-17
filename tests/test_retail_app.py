"""
Functional tests for the RetailApp and DAO layer.

These tests exercise the core behaviour of the application:

* User registration and authentication
* Product creation and retrieval
* Cart operations and total calculations
* Checkout workflow (success and failure cases)

pytest is used as the test runner.  Each test operates on its own
temporary SQLite database to guarantee isolation.  The `RETAIL_DB_PATH`
environment variable is set for the lifetime of the test to point at
the temporary database file.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
import sys

import pytest

# Ensure that the application source code is on the import path.  When running
# pytest from the project root the current working directory will not
# necessarily include ``src``.  Adding the parent of the ``src`` directory
# here allows ``import app`` and ``import dao`` to resolve correctly.
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from app import RetailApp  # type: ignore
# Intentionally do not import DAO symbols here; they are imported within the
# fixture as needed.  Importing them at module scope would bind them to a
# potentially stale connection when tests are collected.


@contextmanager
def temp_database() -> str:
    """Context manager that yields a path to a temporary database file and
    cleans it up afterwards.

    The caller is responsible for setting the RETAIL_DB_PATH environment
    variable if required.  The returned filename is created using
    ``tempfile.mkstemp`` and unlinked on exit.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    # Close the file descriptor immediately; sqlite3 will open the file itself.
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


@pytest.fixture
def retail_app() -> RetailApp:
    """
    Provide a fresh :class:`RetailApp` instance bound to a temporary
    database.

    Each test gets its own SQLite database file.  The
    ``RETAIL_DB_PATH`` environment variable is set for the duration of
    the test so that the DAO layer uses the correct database.  At
    teardown the connection is explicitly closed and the file is
    removed.  This prevents reuse of the same connection across
    tests, which would otherwise lead to "attempt to write a readonly
    database" errors when the underlying file is deleted.
    """
    from dao import get_request_connection  # imported here to avoid circular import
    import dao as dao_module
    with temp_database() as db_file:
        os.environ["RETAIL_DB_PATH"] = db_file
        app = RetailApp()
        try:
            yield app
        finally:
            # Close and reset the thread‑local connection so subsequent
            # RetailApp instances do not reuse a closed connection.
            try:
                conn = get_request_connection()
                conn.close()
            except Exception:
                pass
            # Explicitly clear the thread‑local variable if present
            if hasattr(dao_module, "_thread_local") and hasattr(dao_module._thread_local, "conn"):
                dao_module._thread_local.conn = None  # type: ignore[attr-defined]
            # Remove the environment variable and let the file cleanup run
            os.environ.pop("RETAIL_DB_PATH", None)


def test_user_registration_and_login(retail_app: RetailApp) -> None:
    # Register a new user
    ok, msg = retail_app.register("alice", "secret")
    assert ok is True
    # Attempting to register the same user again should fail
    ok2, _ = retail_app.register("alice", "secret")
    assert ok2 is False
    # Authenticate with the correct password
    assert retail_app.login("alice", "secret") is True
    # Wrong password should not authenticate
    assert retail_app.login("alice", "wrong") is False


def test_product_creation_and_listing(retail_app: RetailApp) -> None:
    # Initially the product catalogue is empty
    assert retail_app.list_products() == []
    # Add a few products
    pid1 = retail_app.product_dao.add_product("Widget", price=9.99, stock=10)
    pid2 = retail_app.product_dao.add_product("Gadget", price=14.99, stock=5)
    products = retail_app.list_products()
    # Ensure both products are returned in ascending order by ID
    assert [p.id for p in products] == [pid1, pid2]
    names = [p.name for p in products]
    assert names == ["Widget", "Gadget"]


def test_add_to_cart_and_totals(retail_app: RetailApp) -> None:
    # Create a user and product to work with
    retail_app.register("bob", "pw")
    retail_app.login("bob", "pw")
    pid = retail_app.product_dao.add_product("Thing", price=2.50, stock=3)
    # Add one item to the cart
    ok, msg = retail_app.add_to_cart(pid, 2)
    assert ok is True
    # The cart should reflect the line
    cart_items = retail_app.view_cart()
    assert len(cart_items) == 1
    line = cart_items[0]
    assert line.product_id == pid and line.qty == 2 and line.unit_price == 2.50
    # Totals should compute correctly (no tax or shipping implemented)
    totals = retail_app.compute_cart_totals()
    assert totals.subtotal == pytest.approx(5.0)
    assert totals.total == pytest.approx(5.0)


def test_checkout_successful_card_payment(retail_app: RetailApp) -> None:
    # Register and log in a user
    retail_app.register("carol", "pw")
    retail_app.login("carol", "pw")
    # Create a product and add it to the cart
    pid = retail_app.product_dao.add_product("Book", price=12.00, stock=2)
    ok, msg = retail_app.add_to_cart(pid, 1)
    assert ok is True
    # Perform checkout with a card; should succeed
    ok2, receipt = retail_app.checkout("Card")
    assert ok2 is True
    # The receipt should include the sale ID and payment reference
    assert "Sale ID:" in receipt
    assert "Payment Method: Card" in receipt
    assert "Payment Ref:" in receipt
    # After checkout the cart should be empty
    assert retail_app.view_cart() == []


def test_checkout_fails_when_insufficient_stock(retail_app: RetailApp) -> None:
    # User
    retail_app.register("dave", "pw")
    retail_app.login("dave", "pw")
    # Product with limited stock
    pid = retail_app.product_dao.add_product("Lamp", price=20.00, stock=1)
    # Add more than available
    ok, msg = retail_app.add_to_cart(pid, 2)
    assert ok is False
    # The message should mention the available quantity
    assert msg.startswith("Only 1 in stock")


def test_checkout_fails_for_cash_payment(retail_app: RetailApp) -> None:
    # User and product
    retail_app.register("eve", "pw")
    retail_app.login("eve", "pw")
    pid = retail_app.product_dao.add_product("Pen", price=1.00, stock=10)
    retail_app.add_to_cart(pid, 1)
    # Checkout with cash should be rejected by PaymentService
    ok, reason = retail_app.checkout("Cash")
    assert ok is False
    assert "not accepted" in reason