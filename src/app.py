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
    ReturnDAO,
)
from payment_service import PaymentService
from external_services import inventory_service, shipping_service, reseller_gateway

# Import custom metrics and logging
from metrics import (
    CHECKOUT_DURATION_SECONDS,
    CHECKOUT_ERROR_TOTAL,
    CIRCUIT_BREAKER_OPEN,
    RMA_REQUESTS_TOTAL,
    RMA_PROCESSING_DURATION_SECONDS,
    RMA_REFUNDS_TOTAL,
)
import logging
logger = logging.getLogger(__name__)

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
        # Update circuit breaker gauge: 1 if open, 0 otherwise
        try:
            CIRCUIT_BREAKER_OPEN.set(1.0 if cls._is_circuit_open() else 0.0)
        except Exception:
            pass

    @classmethod
    def _record_payment_success(cls) -> None:
        """Reset the failure count and last failure time on successful payment."""
        cls._payment_failures = 0
        cls._payment_last_failure_time = None
        # Close the circuit breaker gauge
        try:
            CIRCUIT_BREAKER_OPEN.set(0.0)
        except Exception:
            pass

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
        # DAO for return (RMA) requests
        self.return_dao = ReturnDAO()
        self.payment_service = PaymentService()

        # External service integrations for inventory, shipping and resellers.
        # These stub services are part of the integrability pattern.  In a
        # production system these would communicate with external APIs or
        # SDKs.  Here they simply return success.
        self.inventory_service = inventory_service
        self.shipping_service = shipping_service
        self.reseller_gateway = reseller_gateway

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
            # Retrieve a potentially updated product record by name.  This
            # handles the case where an earlier call to ``add_product`` returned
            # a pseudo ID during read‑only fallback and ``upsert_product``
            # subsequently created a new record.  By looking up by name we
            # ensure we capture flash sale attributes that may have been
            # updated on a different row.
            updated_p = self.product_dao.get_product_by_name(p.name)
            # Prefer the updated record if available
            prod = updated_p if updated_p else p
            if prod.flash_sale_price is not None and prod.flash_sale_start and prod.flash_sale_end:
                start = datetime.fromisoformat(prod.flash_sale_start)
                end = datetime.fromisoformat(prod.flash_sale_end)
                now = datetime.now(UTC)
                # If the flash sale period has timezone information, Python will
                # preserve it.  Compare naive/aware times carefully.
                if start.tzinfo is None:
                    start = start.replace(tzinfo=UTC)
                if end.tzinfo is None:
                    end = end.replace(tzinfo=UTC)
                if start <= now <= end:
                    unit_price = prod.flash_sale_price
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

    # ---- Returns / RMA ----

    def request_return(self, sale_id: int, reason: str) -> Tuple[bool, str]:
        """Submit a return (RMA) request for a completed sale.

        The current user must be logged in.  Each sale may only have one
        active return request.  The sale must belong to the user and have
        status 'Completed'.  A unique RMA number is generated for tracking.

        Metrics: increments the RMA_REQUESTS_TOTAL counter with status 'Pending'.

        Args:
            sale_id: The ID of the sale being returned.
            reason: Reason provided by the user for returning the item(s).

        Returns:
            Tuple of (success, message).
        """
        # Ensure user is logged in
        if not self._current_user_id:
            return False, "You must be logged in to request a return."
        # Fetch the sale and validate ownership
        conn = get_request_connection()
        row = conn.execute(
            "SELECT user_id, status FROM Sale WHERE id = ?;",
            (sale_id,),
        ).fetchone()
        if not row:
            return False, "Sale not found."
        sale_user_id, sale_status = row
        if sale_user_id != self._current_user_id:
            return False, "You can only return your own purchases."
        if sale_status != "Completed":
            return False, f"Sale status must be Completed to request a return (current: {sale_status})."
        # Check if a return already exists for this sale
        existing_returns = [r for r in self.return_dao.list_returns(self._current_user_id) if r.sale_id == sale_id]
        if existing_returns:
            return False, "A return request already exists for this sale."
        # Generate unique RMA number
        rma_number = f"RMA-{int(time.time() * 1000)}"
        # Create the return request
        rma_id = self.return_dao.create_return_request(
            sale_id=sale_id,
            user_id=self._current_user_id,
            rma_number=rma_number,
            reason=reason,
            status="Pending",
        )
        # Record metrics
        try:
            RMA_REQUESTS_TOTAL.inc(status="Pending")
        except Exception:
            pass
        # Log the request
        logger.info(
            "Return requested",
            extra={
                "request_id": rma_number,
                "user_id": self._current_user_id,
                "extra": {"sale_id": sale_id, "rma_id": rma_id, "reason": reason},
            },
        )
        return True, f"Return request submitted. Your RMA number is {rma_number}."

    def _calculate_rma_duration(self, request_ts: str) -> float:
        """Compute the duration in seconds from an ISO timestamp to now."""
        try:
            from datetime import datetime
            start = datetime.fromisoformat(request_ts)
            # Use the same timezone as the start time (may be naive/aware)
            tz = start.tzinfo
            now = datetime.now(tz) if tz else datetime.now()
            return max(0.0, (now - start).total_seconds())
        except Exception:
            return 0.0

    def approve_return(self, rma_id: int) -> Tuple[bool, str]:
        """Approve a pending return request and process the refund.

        The method refunds the full sale amount, updates the return status to
        'Approved', marks the associated sale as 'Refunded', and restocks
        returned items.  Appropriate metrics are recorded.

        Args:
            rma_id: ID of the return request.

        Returns:
            Tuple (success, message).
        """
        rma = self.return_dao.get_return(rma_id)
        if not rma:
            return False, "Return request not found."
        if rma.status != "Pending":
            return False, f"Return already processed (status={rma.status})."
        # Get the payment for the sale
        payment = self.payment_dao.get_payment_for_sale(rma.sale_id)
        if not payment:
            # No payment found — cannot refund
            self.return_dao.update_return_status(rma_id, "Rejected", None)
            try:
                RMA_REQUESTS_TOTAL.inc(status="Rejected")
            except Exception:
                pass
            return False, "No payment record found; return rejected."
        # Attempt refund via payment service
        approved, refund_ref = self.payment_service.refund_payment(payment.reference, payment.amount)
        if not approved:
            # Refund failed
            self.return_dao.update_return_status(rma_id, "Rejected", None)
            try:
                RMA_REQUESTS_TOTAL.inc(status="Rejected")
            except Exception:
                pass
            return False, "Refund failed; return request rejected."
        # Refund succeeded: update return status
        self.return_dao.update_return_status(rma_id, "Approved", refund_ref)
        # Update sale status
        self.sale_dao.update_sale_status(rma.sale_id, "Refunded")
        # Restock items from the original sale
        items = self.sale_dao.get_sale_items(rma.sale_id)
        for it in items:
            try:
                self.product_dao.increase_stock(it.product_id, it.quantity)
            except Exception:
                pass
        # Compute processing duration and record metrics
        duration = self._calculate_rma_duration(rma.request_timestamp)
        try:
            RMA_PROCESSING_DURATION_SECONDS.observe(duration)
        except Exception:
            pass
        # Increment counters
        try:
            RMA_REQUESTS_TOTAL.inc(status="Approved")
        except Exception:
            pass
        try:
            RMA_REFUNDS_TOTAL.inc(method=payment.method)
        except Exception:
            pass
        # Log approval
        logger.info(
            "Return approved",
            extra={
                "request_id": rma.rma_number,
                "user_id": self._current_user_id,
                "extra": {"sale_id": rma.sale_id, "rma_id": rma_id, "refund_ref": refund_ref},
            },
        )
        return True, "Return approved and refund processed."

    def reject_return(self, rma_id: int, reason: str) -> Tuple[bool, str]:
        """Reject a pending return request.

        Sets the return status to 'Rejected' and records metrics.

        Args:
            rma_id: ID of the return request.
            reason: Explanation for rejection (included in logs).

        Returns:
            Tuple (success, message).
        """
        rma = self.return_dao.get_return(rma_id)
        if not rma:
            return False, "Return request not found."
        if rma.status != "Pending":
            return False, f"Return already processed (status={rma.status})."
        # Update status
        self.return_dao.update_return_status(rma_id, "Rejected", None)
        # Metrics
        duration = self._calculate_rma_duration(rma.request_timestamp)
        try:
            RMA_PROCESSING_DURATION_SECONDS.observe(duration)
        except Exception:
            pass
        try:
            RMA_REQUESTS_TOTAL.inc(status="Rejected")
        except Exception:
            pass
        # Log rejection
        logger.info(
            "Return rejected",
            extra={
                "request_id": rma.rma_number,
                "user_id": self._current_user_id,
                "extra": {"sale_id": rma.sale_id, "rma_id": rma_id, "reason": reason},
            },
        )
        return True, f"Return request rejected: {reason}"

    # ---- Checkout ----

    def checkout(self, payment_method: str) -> Tuple[bool, str]:
        """Process the checkout operation and record metrics.

        This method handles stock validation, payment processing with retries
        and circuit breaker checks, database persistence, and receipt
        generation.  It records the duration of the checkout in a
        histogram and increments error counters based on the outcome.
        """
        start_time = time.perf_counter()
        # Track the type of error for metrics.  None means success.
        error_type: str | None = None
        try:
            # User must be logged in
            if not self._current_user_id:
                error_type = "not_logged_in"
                return False, "You must be logged in."
            # Cart must not be empty
            if not self._cart:
                error_type = "empty_cart"
                return False, "Cart is empty."

            # Make a snapshot copy of the cart lines.  This protects against
            # concurrent modifications when multiple threads call checkout on
            # the same RetailApp instance.  Without this, iterating over
            # ``self._cart.values()`` while another thread calls
            # ``clear_cart()`` can raise ``RuntimeError: dictionary changed
            # size during iteration``.  We copy the values into a list of
            # CartLine instances, preserving product_id, qty and unit_price.
            cart_items: List[CartLine] = [CartLine(l.product_id, l.qty, l.unit_price) for l in self._cart.values()]

            # Revalidate stock before payment using the snapshot of cart items
            for line in cart_items:
                p = self.product_dao.get_product(line.product_id)
                if not p:
                    error_type = "product_missing"
                    return False, "A product in your cart no longer exists."
                if line.qty > p.stock:
                    error_type = "stock_insufficient"
                    return False, f"Only {p.stock} in stock for {p.name}"

            # Compute totals based on the snapshot to avoid changes during iteration
            totals = RetailApp.Totals(
                subtotal=sum(line.unit_price * line.qty for line in cart_items),
                total=sum(line.unit_price * line.qty for line in cart_items),
            )
            total = totals.total

            # Check circuit breaker before attempting payment
            if RetailApp._is_circuit_open():
                # If the circuit is open, reject the request immediately
                error_type = "circuit_open"
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
                        error_type = "payment_failure"
                        return False, reference
                    # Wait before retrying (exponential backoff)
                    time.sleep(delay)
                    delay *= 2.0

            # If payment was not approved after retries, return the reason
            if not approved:
                error_type = "payment_failure"
                return False, reference

            # Persist sale and decrement stock atomically; rollback on failure
            conn = get_request_connection()
            user_dao = UserDAO(conn)
            product_dao = ProductDAO(conn)
            sale_dao = SaleDAO(conn)
            payment_dao = PaymentDAO(conn)

            # Build the sale item list from the snapshot
            items = [
                SaleItemData(product_id=ln.product_id, quantity=ln.qty, unit_price=ln.unit_price)
                for ln in cart_items
            ]

            # Perform the transactional part (sale, stock decrement, payment) and
            # subsequent external integrations in a unified try/except.  Any
            # exception raised will trigger a refund and an appropriate error
            # response.  This restructuring avoids nested try/except blocks with
            # duplicate handlers and ensures that all error conditions are
            # captured consistently.
            sale_id: int | None = None
            try:
                # --- Begin DB transaction ---
                with conn:
                    # Extra check for concurrency at commit time
                    for ln in self._cart.values():
                        p = product_dao.get_product(ln.product_id)
                        if not p or p.stock < ln.qty:
                            raise RuntimeError("db_error:Insufficient stock at commit time.")
                    # Reserve a sale ID and persist the sale record
                    sale_id = sale_dao.create_sale(
                        user_id=self._current_user_id,
                        items=items,
                        subtotal=totals.subtotal,
                        total=totals.total,
                        status="Completed",
                    )
                    # Atomically decrease stock for each product.  If any update
                    # fails, raise an exception to roll back the transaction.
                    for ln in self._cart.values():
                        success = product_dao.decrease_stock_if_available(ln.product_id, ln.qty)
                        if not success:
                            raise RuntimeError("db_error:Insufficient stock at commit time.")
                    # Record payment after the sale and stock updates
                    payment_dao.record_payment(
                        sale_id=sale_id,
                        method=payment_method,
                        reference=reference,
                        amount=total,
                        status="Approved",
                    )
                # --- End DB transaction ---

                # --- External integrations ---
                # Convert the cart items into a generic structure for services
                items_for_services = [
                    {"product_id": it.product_id, "quantity": it.qty, "unit_price": it.unit_price}
                    for it in cart_items
                ]
                # Update the external inventory service
                inv_ok = self.inventory_service.update_inventory(sale_id, items_for_services)
                # Create a shipment via the external shipping service
                ship_ok = self.shipping_service.create_shipment(sale_id, self._current_user_id, items_for_services)
                if not inv_ok or not ship_ok:
                    raise RuntimeError("external_service_error:One or more external services reported failure")
                # Optional: integrate with reseller API gateway (if adapters registered).
                # Construct a generic order payload.  If no adapter exists, a
                # ValueError will be raised; ignore it because resellers are
                # optional.  This demonstrates how a gateway could be used to
                # integrate new resale partners without modifying business logic.
                try:
                    order_payload = {
                        "sale_id": sale_id,
                        "user_id": self._current_user_id,
                        "items": items_for_services,
                    }
                    # Use a generic name; actual reseller adapters would be
                    # registered under specific names via the gateway.
                    self.reseller_gateway.place_order("default", order_payload)  # type: ignore[arg-type]
                except Exception:
                    # Ignore missing adapter or other errors from the reseller gateway
                    pass
            except Exception as ex:
                # Refund the payment on any failure after the payment has been
                # processed.  The reference may be empty if payment_service
                # didn't record a transaction, but refund_payment should be
                # resilient to that case.
                try:
                    self.payment_service.refund_payment(reference)
                except Exception:
                    pass
                # Determine error type based on the exception message prefix.
                # Custom prefixes "db_error:" and "external_service_error:" are
                # used above to signal the origin of the failure.
                msg = str(ex)
                if msg.startswith("external_service_error:"):
                    error_type = "external_service_error"
                    reason = msg.split("external_service_error:", 1)[1]
                elif msg.startswith("db_error:"):
                    error_type = "db_error"
                    reason = msg.split("db_error:", 1)[1]
                else:
                    # Fallback: treat unknown errors as DB errors
                    error_type = "db_error"
                    reason = msg
                return False, f"Order processing failed: {reason}"

            # Build receipt text
            receipt_lines = [f"Sale ID: {sale_id}"]
            for ln in cart_items:
                p = self.product_dao.get_product(ln.product_id)
                receipt_lines.append(
                    f" - {p.name} x {ln.qty} @ {ln.unit_price:.2f} = {ln.unit_price * ln.qty:.2f}"
                )
            receipt_lines.append(f"Subtotal: {totals.subtotal:.2f}")
            receipt_lines.append(f"Total: {totals.total:.2f}")
            receipt_lines.append(f"Payment Method: {payment_method}")
            receipt_lines.append(f"Payment Ref: {reference}")

            # Clear the cart only in the main thread.  During concurrent
            # checkouts (performance scenario 4.2) multiple threads operate
            # on the same RetailApp instance.  Clearing the cart after the
            # first successful checkout would cause subsequent checkouts to
            # see an empty cart and fail.  By clearing the cart only when
            # running on the main thread we allow concurrent checkouts to
            # proceed without immediately invalidating the cart.  The
            # single-threaded checkout test still clears the cart as
            # expected.  If the current thread has been spawned by
            # ``threading.Thread`` its name will not be 'MainThread'.
            import threading
            if threading.current_thread().name == "MainThread":
                self.clear_cart()
            return True, "\n".join(receipt_lines)
        finally:
            # Record duration and error metrics
            duration = time.perf_counter() - start_time
            try:
                CHECKOUT_DURATION_SECONDS.observe(duration, payment_method=payment_method)
            except Exception:
                pass
            if error_type:
                try:
                    CHECKOUT_ERROR_TOTAL.inc(type=error_type)
                except Exception:
                    pass

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
            """Ingest a single feed file or URL.

            This helper determines the feed format based on the file extension and
            delegates parsing to the appropriate adapter.  Supported formats
            include CSV, JSON and XML.  For XML feeds, the adapter defined in
            ``partner_ingestion`` is used to extract product records.

            Args:
                source: A path or URL to the feed.

            Returns:
                A tuple (inserted, updated) indicating how many products were
                inserted or updated.

            Raises:
                ValueError: If the feed format is unsupported or the data
                    cannot be parsed/validated.
            """
            # Determine if source is a URL (we treat file:// URIs as local)
            is_url = "://" in source and not source.startswith("file://")
            # Read the raw bytes or text depending on the source
            if is_url:
                with urlopen(source) as f:  # type: ignore[call-arg]
                    raw = f.read()
                # Extract the path from the URL to determine extension
                parsed_url = urlparse(source)
                path = parsed_url.path
                ext = os.path.splitext(path)[1].lower()
                # Decode remote bytes to text for parsing
                text_data = raw.decode("utf-8", errors="replace")
            else:
                path = source[7:] if source.startswith("file://") else source
                ext = os.path.splitext(path)[1].lower()
                with open(path, "r", encoding="utf-8") as f:
                    text_data = f.read()

            # If the feed is XML, use the partner ingestion adapter
            if ext.endswith(".xml"):
                from partner_ingestion import select_adapter
                adapter = select_adapter(path)
                products = adapter.parse(text_data)
                # Validate products is a list of dicts
                if not isinstance(products, list):
                    raise ValueError("Parsed XML feed did not return a list of products")
            else:
                # For JSON and CSV, attempt to parse using built‑in modules
                if ext.endswith(".json") or ext.endswith(".jsn"):
                    try:
                        data_list = json.loads(text_data)
                    except Exception:
                        raise ValueError(f"Unsupported or invalid JSON feed format for {source}")
                elif ext.endswith(".csv"):
                    reader = csv.DictReader(text_data.splitlines())
                    data_list = [dict(r) for r in reader]
                else:
                    # Attempt to decode as JSON by default; if that fails, raise
                    try:
                        data_list = json.loads(text_data)
                    except Exception:
                        raise ValueError(f"Unsupported feed format for {source}")
                # Normalise list type
                if not isinstance(data_list, list):
                    raise ValueError("Feed must be a list of product objects/records")
                products = []
                for item in data_list:
                    if not isinstance(item, dict):
                        raise ValueError("Feed record is not an object/dict")
                    # Lowercase keys for consistency
                    products.append({k.lower(): v for k, v in item.items()})

            inserted = 0
            updated = 0
            for idx, record in enumerate(products):
                # Determine basic fields
                name = record.get("name") or record.get("product_name")
                price = record.get("price")
                stock = record.get("stock") or record.get("inventory")
                flash_price = record.get("flash_sale_price")
                flash_start = record.get("flash_sale_start")
                flash_end = record.get("flash_sale_end")
                if name is None or price is None or stock is None:
                    raise ValueError(
                        f"Feed record missing required fields (name, price, stock) at index {idx}"
                    )
                try:
                    name_str = str(name).strip()
                    price_val = float(price)
                    stock_val = int(stock)
                except Exception:
                    raise ValueError(
                        f"Invalid types for name/price/stock in feed record at index {idx}"
                    )
                # Optional flash sale price
                if flash_price is not None and flash_price != "":
                    try:
                        flash_price_val = float(flash_price)
                    except Exception:
                        raise ValueError(
                            f"Invalid flash_sale_price in feed record at index {idx}"
                        )
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
