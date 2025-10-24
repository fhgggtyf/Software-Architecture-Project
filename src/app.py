# src/app.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import os  # added for path handling in feed ingestion
import time  # added for retry/circuit breaker timing

from dao import (
    UserDAO,
    ProductDAO,
    PaymentDAO,
    SaleDAO,
    SaleItemData,
    get_request_connection,
)
from payment_service import PaymentService

@dataclass
class CartLine:
    """A line in the in‑memory shopping cart."""
    product_id: int
    qty: int
    unit_price: float

class RetailApp:
    """
    Business logic for the retail system. Exposes methods for registration,
    login, cart management, and checkout. Uses per‑request DB connections.
    """

    # Circuit breaker configuration and state (shared across RetailApp instances)
    _payment_failures: int = 0
    _payment_last_failure_time: float | None = None
    _payment_failure_threshold: int = 3
    _payment_cooldown: int = 30  # seconds

    @classmethod
    def _record_payment_failure(cls) -> None:
        """Record a payment failure and update the last failure timestamp."""
        cls._payment_failures += 1
        cls._payment_last_failure_time = time.time()

    @classmethod
    def _record_payment_success(cls) -> None:
        """Reset the failure count and last failure time on successful payment."""
        cls._payment_failures = 0
        cls._payment_last_failure_time = None

    @classmethod
    def _is_circuit_open(cls) -> bool:
        """
        Determine whether the circuit breaker is open.

        The circuit is considered open if the number of consecutive failures
        exceeds the threshold and the cooldown period has not yet expired.

        Returns:
            True if the circuit is open and payment attempts should be halted.
            False otherwise.
        """
        # If we've hit the failure threshold and we're within the cooldown window, the circuit is open
        if cls._payment_failures >= cls._payment_failure_threshold:
            if cls._payment_last_failure_time is not None:
                elapsed = time.time() - cls._payment_last_failure_time
                if elapsed < cls._payment_cooldown:
                    return True
                else:
                    # Cooldown has passed; reset failures
                    cls._payment_failures = 0
                    cls._payment_last_failure_time = None
        return False

    def __init__(self) -> None:
        # DAOs use per‑request connections
        self.user_dao = UserDAO()
        self.product_dao = ProductDAO()
        self.sale_dao = SaleDAO()
        self.payment_dao = PaymentDAO()
        self.payment_service = PaymentService()

        # Cart keyed by product_id
        self._cart: Dict[int, CartLine] = {}
        self._current_user_id: int | None = None

    # ---- Authentication ----

    def register(self, username: str, password: str) -> Tuple[bool, str]:
        ok = self.user_dao.register_user(username, password)
        return (ok, "User registered." if ok else "Username already exists.")

    def login(self, username: str, password: str) -> bool:
        uid = self.user_dao.authenticate(username, password)
        self._current_user_id = uid
        return uid is not None

    def current_user_is_admin(self, username: str) -> bool:
        """Return True if the specified user has admin rights."""
        return self.user_dao.is_admin(username)

    # ---- Product catalogue ----

    def list_products(self):
        return self.product_dao.list_products()

    # ---- Cart operations ----

    def add_to_cart(self, product_id: int, qty: int) -> Tuple[bool, str]:
        if qty <= 0:
            return False, "Quantity must be positive."

        p = self.product_dao.get_product(product_id)
        if not p:
            return False, "Product not found."

        if qty > p.stock:
            return False, f"Only {p.stock} in stock"
        # Determine the unit price: use flash sale price if the sale is active.
        unit_price = p.price
        try:
            # Flash sale is active if both start and end are defined and the current
            # time is within the inclusive range.  Use UTC timestamps to avoid
            # timezone ambiguity.
            from datetime import datetime, UTC

            if p.flash_sale_price is not None and p.flash_sale_start and p.flash_sale_end:
                start = datetime.fromisoformat(p.flash_sale_start)
                end = datetime.fromisoformat(p.flash_sale_end)
                now = datetime.now(UTC)
                # If the flash sale period has timezone information, Python will
                # preserve it.  Compare naive/aware times carefully.
                if start.tzinfo is None:
                    start = start.replace(tzinfo=UTC)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=UTC)
                if start <= now <= end:
                    unit_price = p.flash_sale_price
        except Exception:
            # If parsing fails, fall back to regular price
            unit_price = p.price

        self._cart[product_id] = CartLine(product_id=product_id, qty=qty, unit_price=unit_price)
        return True, f"Added {qty} x {p.name} to cart"

    def remove_from_cart(self, product_id: int) -> None:
        self._cart.pop(product_id, None)

    def clear_cart(self) -> None:
        self._cart.clear()

    def view_cart(self) -> List[CartLine]:
        return list(self._cart.values())

    @dataclass
    class Totals:
        subtotal: float
        total: float

    def compute_cart_totals(self) -> Totals:
        subtotal = sum(line.unit_price * line.qty for line in self._cart.values())
        return RetailApp.Totals(subtotal=subtotal, total=subtotal)

    # ---- Checkout ----

    def checkout(self, payment_method: str) -> Tuple[bool, str]:
        if not self._current_user_id:
            return False, "You must be logged in."
        if not self._cart:
            return False, "Cart is empty."

        # Revalidate stock before payment
        for line in self._cart.values():
            p = self.product_dao.get_product(line.product_id)
            if not p:
                return False, "A product in your cart no longer exists."
            if line.qty > p.stock:
                return False, f"Only {p.stock} in stock for {p.name}"

        totals = self.compute_cart_totals()
        total = totals.total

        # Check circuit breaker before attempting payment
        if RetailApp._is_circuit_open():
            # If the circuit is open, reject the request immediately
            return False, "Payment service is temporarily unavailable. Please try again later."

        # Attempt payment with retry logic and exponential backoff
        retries = 3
        delay = 1.0
        approved = False
        reference = ""
        for attempt in range(retries):
            approved, reference = self.payment_service.process_payment(total, payment_method)
            if approved:
                # Reset failure count on success
                RetailApp._record_payment_success()
                break
            else:
                # Record a failure and potentially open the circuit
                RetailApp._record_payment_failure()
                # On last attempt, fail with the payment error
                if attempt >= retries - 1:
                    return False, reference
                # Wait before retrying (exponential backoff)
                time.sleep(delay)
                delay *= 2.0

        # If payment was not approved after retries, return the reason
        if not approved:
            return False, reference

        # Persist sale and decrement stock atomically; rollback on failure
        conn = get_request_connection()
        user_dao = UserDAO(conn)
        product_dao = ProductDAO(conn)
        sale_dao = SaleDAO(conn)
        payment_dao = PaymentDAO(conn)

        items = [
            SaleItemData(product_id=ln.product_id, quantity=ln.qty, unit_price=ln.unit_price)
            for ln in self._cart.values()
        ]

        try:
            with conn:
                # Extra check for concurrency at commit time
                for ln in self._cart.values():
                    p = product_dao.get_product(ln.product_id)
                    if not p or p.stock < ln.qty:
                        raise RuntimeError("Insufficient stock at commit time.")
                # Create the sale first; this reserves the sale ID.  If stock
                # adjustments fail, the transaction will roll back and the sale
                # record will not persist.
                sale_id = sale_dao.create_sale(
                    user_id=self._current_user_id,
                    items=items,
                    subtotal=totals.subtotal,
                    total=totals.total,
                    status="Completed",
                )

                # Atomically decrease stock for each product.  Using a conditional
                # update prevents overselling if another concurrent transaction
                # decremented the stock in the meantime.  We check the rowcount
                # from decrease_stock_if_available and abort if insufficient.
                for ln in self._cart.values():
                    success = product_dao.decrease_stock_if_available(ln.product_id, ln.qty)
                    if not success:
                        # Roll back the entire transaction by raising an exception.
                        raise RuntimeError("Insufficient stock at commit time.")

                # Record payment
                payment_dao.record_payment(
                    sale_id=sale_id,
                    method=payment_method,
                    reference=reference,
                    amount=total,
                    status="Approved",
                )
        except Exception as ex:
            # If any exception occurs during DB operations, refund the payment
            try:
                self.payment_service.refund_payment(reference)
            except Exception:
                pass
            return False, f"Order processing failed after payment: {ex}"

        # Build receipt text
        receipt_lines = [f"Sale ID: {sale_id}"]
        for ln in self._cart.values():
            p = self.product_dao.get_product(ln.product_id)
            receipt_lines.append(
                f" - {p.name} x {ln.qty} @ {ln.unit_price:.2f} = {ln.unit_price * ln.qty:.2f}"
            )
        receipt_lines.append(f"Subtotal: {totals.subtotal:.2f}")
        receipt_lines.append(f"Total: {totals.total:.2f}")
        receipt_lines.append(f"Payment Method: {payment_method}")
        receipt_lines.append(f"Payment Ref: {reference}")

        self.clear_cart()
        return True, "\n".join(receipt_lines)

    # ---- Partner Catalog Ingest ----
    def ingest_partner_feed(self, partner_name: str, feed_source: str, schedule_interval_seconds: float | None = None) -> Tuple[int, int]:
        """
        Ingest a partner's product feed into the catalog.

        Args:
            partner_name: Name of the partner providing the feed (for logging).
            feed_source: Path or URL to a CSV or JSON feed. If the string contains "://" it is treated as a URL and fetched via urllib.
            schedule_interval_seconds: If provided and greater than zero, ingestion will be scheduled
                to run periodically at this interval (in seconds) using a daemon thread. The first ingestion runs immediately.

        Returns:
            A tuple (inserted_count, updated_count) indicating how many products were inserted or updated on the initial run.

        Raises:
            ValueError: If the feed format is unsupported or validation fails.
        """
        import csv
        import json
        from urllib.parse import urlparse
        from urllib.request import urlopen
        import threading

        def _ingest_once(source: str) -> Tuple[int, int]:
            # Determine if source is a URL or local file
            is_url = "://" in source and not source.startswith("file://")
            # Load data
            if is_url:
                with urlopen(source) as f:  # type: ignore[call-arg]
                    raw = f.read()
                path = urlparse(source).path
                ext = os.path.splitext(path)[1].lower()
                if ext.endswith(".json"):
                    data = json.loads(raw.decode("utf-8"))
                elif ext.endswith(".csv"):
                    text = raw.decode("utf-8").splitlines()
                    reader = csv.DictReader(text)
                    data = [dict(r) for r in reader]
                else:
                    try:
                        data = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        raise ValueError(f"Unsupported remote feed format for {source}")
            else:
                path = source[7:] if source.startswith("file://") else source
                ext = os.path.splitext(path)[1].lower()
                if ext.endswith(".json"):
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                elif ext.endswith(".csv"):
                    with open(path, newline="", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        data = [dict(r) for r in reader]
                else:
                    raise ValueError(f"Unsupported feed format for {path}")

            if not isinstance(data, list):
                raise ValueError("Feed must be a list of product objects/records")

            inserted = 0
            updated = 0
            for idx, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(f"Feed record at index {idx} is not an object/dict")
                lower_keys = {k.lower(): v for k, v in item.items()}
                name = lower_keys.get("name") or lower_keys.get("product_name")
                price = lower_keys.get("price")
                stock = lower_keys.get("stock") or lower_keys.get("inventory")
                flash_price = lower_keys.get("flash_sale_price")
                flash_start = lower_keys.get("flash_sale_start")
                flash_end = lower_keys.get("flash_sale_end")
                if name is None or price is None or stock is None:
                    raise ValueError(f"Feed record missing required fields (name, price, stock) at index {idx}")
                try:
                    name_str = str(name).strip()
                    price_val = float(price)
                    stock_val = int(stock)
                except Exception:
                    raise ValueError(f"Invalid types for name/price/stock in feed record at index {idx}")
                if flash_price is not None and flash_price != "":
                    try:
                        flash_price_val = float(flash_price)
                    except Exception:
                        raise ValueError(f"Invalid flash_sale_price in feed record at index {idx}")
                else:
                    flash_price_val = None
                flash_start_str = str(flash_start) if flash_start else None
                flash_end_str = str(flash_end) if flash_end else None
                existing = self.product_dao.get_product_by_name(name_str)
                self.product_dao.upsert_product(
                    name=name_str,
                    price=price_val,
                    stock=stock_val,
                    flash_sale_price=flash_price_val,
                    flash_sale_start=flash_start_str,
                    flash_sale_end=flash_end_str,
                )
                if existing:
                    updated += 1
                else:
                    inserted += 1
            return inserted, updated

        inserted_count, updated_count = _ingest_once(feed_source)

        if schedule_interval_seconds is not None and schedule_interval_seconds > 0:
            def _scheduled_ingest() -> None:
                import time
                while True:
                    try:
                        _ingest_once(feed_source)
                    except Exception:
                        pass
                    time.sleep(schedule_interval_seconds)

            t = threading.Thread(target=_scheduled_ingest, daemon=True)
            t.start()

        return inserted_count, updated_count
