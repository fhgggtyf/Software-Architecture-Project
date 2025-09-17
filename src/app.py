# src/app.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

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

        self._cart[product_id] = CartLine(product_id=product_id, qty=qty, unit_price=p.price)
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

        # Call mock payment gateway
        approved, reference = self.payment_service.process_payment(total, payment_method)
        if not approved:
            # Payment failed: nothing persisted
            return False, reference

        # Persist sale and decrement stock atomically
        conn = get_request_connection()
        user_dao = UserDAO(conn)
        product_dao = ProductDAO(conn)
        sale_dao = SaleDAO(conn)
        payment_dao = PaymentDAO(conn)

        items = [
            SaleItemData(product_id=ln.product_id, quantity=ln.qty, unit_price=ln.unit_price)
            for ln in self._cart.values()
        ]

        with conn:
            # Extra check for concurrency at commit time
            for ln in self._cart.values():
                p = product_dao.get_product(ln.product_id)
                if not p or p.stock < ln.qty:
                    raise RuntimeError("Insufficient stock at commit time.")

            sale_id = sale_dao.create_sale(
                user_id=self._current_user_id,
                items=items,
                subtotal=totals.subtotal,
                total=totals.total,
                status="Completed",
            )

            # Update stock
            for ln in self._cart.values():
                p = product_dao.get_product(ln.product_id)
                product_dao.update_stock(p.id, p.stock - ln.qty)

            # Record payment
            payment_dao.record_payment(
                sale_id=sale_id,
                method=payment_method,
                reference=reference,
                amount=total,
                status="Approved",
            )

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
