"""
Business logic layer for the minimal retail application.

This module defines the ``RetailApp`` class which orchestrates
interactions between the data access layer (DAOs) and the payment
service.  It exposes high‑level methods for user registration,
authentication, product management, cart operations, and checkout.
All database updates related to a sale are performed atomically
inside a transaction to satisfy the postconditions described in the
assignment.
"""

import sqlite3
from typing import Dict, List, Optional, Tuple

from dao import (
    Product,
    ProductDAO,
    SaleDAO,
    SaleItemData,
    UserDAO,
    PaymentDAO,
)
from payment_service import PaymentService


class RetailApp:
    """Main application class encapsulating business logic for the retail app."""

    def __init__(self, db_path: str = "retail.db") -> None:
        """Initialize the application.

        :param db_path: Path to the SQLite database file.  If the file does
            not exist it will be created automatically.  Using a file
            rather than an in‑memory database ensures persistence across
            restarts as required by the specification.
        """
        self.conn = sqlite3.connect(db_path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        # Instantiate DAOs
        self.user_dao = UserDAO(self.conn)
        self.product_dao = ProductDAO(self.conn)
        self.sale_dao = SaleDAO(self.conn)
        self.payment_dao = PaymentDAO(self.conn)
        # Payment service always approves by default; set always_approve=False
        # during testing to simulate failures.
        self.payment_service = PaymentService(always_approve=True)
        # Session state
        self.current_user_id: Optional[int] = None
        self.cart: Dict[int, int] = {}

    # -------------------------------------------------------------------------
    # User management
    # -------------------------------------------------------------------------
    def register(self, username: str, password: str) -> bool:
        """Create a new user account."""
        return self.user_dao.register_user(username, password)

    def login(self, username: str, password: str) -> bool:
        """Authenticate a user and populate `current_user_id` on success."""
        user_id = self.user_dao.authenticate(username, password)
        if user_id is not None:
            self.current_user_id = user_id
            return True
        return False

    # -------------------------------------------------------------------------
    # Product management
    # -------------------------------------------------------------------------
    def add_product(self, name: str, price: float, stock: int) -> int:
        """Add a new product to the catalog."""
        return self.product_dao.add_product(name, price, stock)

    def list_products(self) -> List[Product]:
        """Return a list of all products available in the store."""
        return self.product_dao.list_products()

    # -------------------------------------------------------------------------
    # Cart operations
    # -------------------------------------------------------------------------
    def add_to_cart(self, product_id: int, quantity: int) -> Tuple[bool, str]:
        """Attempt to add a product to the current user's cart.

        Validates that the product exists and that the quantity requested
        does not exceed available stock.  It also merges quantities if
        the product is already in the cart.
        """
        product = self.product_dao.get_product(product_id)
        if product is None:
            return False, "Product not found"
        existing_qty = self.cart.get(product_id, 0)
        if quantity + existing_qty > product.stock:
            return False, f"Only {product.stock - existing_qty} in stock"
        self.cart[product_id] = existing_qty + quantity
        return True, f"Added {quantity} x {product.name} to cart"

    def view_cart(self) -> List[Tuple[Product, int, float]]:
        """Return a list of cart items along with quantity and line total."""
        items: List[Tuple[Product, int, float]] = []
        for product_id, qty in self.cart.items():
            product = self.product_dao.get_product(product_id)
            if product:
                items.append((product, qty, product.price * qty))
        return items

    # -------------------------------------------------------------------------
    # Checkout / Purchase workflow
    # -------------------------------------------------------------------------
    def checkout(self, payment_method: str) -> Tuple[bool, str]:
        """Complete the purchase and record a sale.

        Implements the main success scenario for registering a sale.  Steps:
        1. Validate cart is not empty and user is logged in.
        2. Validate stock levels for each item; if any product is
           insufficient, rollback and return an error message.
        3. Compute subtotal and total (the implementation uses no
           additional taxes/fees for simplicity but could be extended).
        4. Process the payment via ``PaymentService``.  If the payment
           fails, do not persist the sale or update stock.
        5. Within a single transaction: create the sale and sale items,
           decrement stock accordingly, and record the payment.  If
           anything goes wrong the transaction will rollback.
        6. Clear the cart and return success status and receipt info.
        """
        if self.current_user_id is None:
            return False, "User must be logged in to checkout"
        if not self.cart:
            return False, "Cart is empty"
        # Validate stock and prepare sale items
        sale_items: List[SaleItemData] = []
        subtotal = 0.0
        for product_id, qty in self.cart.items():
            product = self.product_dao.get_product(product_id)
            if product is None:
                return False, f"Product with ID {product_id} not found"
            if qty > product.stock:
                return False, f"Insufficient stock for {product.name}; only {product.stock} available"
            sale_items.append(SaleItemData(product_id, qty, product.price))
            subtotal += product.price * qty
        total = subtotal  # Extend here for taxes/fees/discounts
        # Process payment
        approved, reference = self.payment_service.process_payment(total, payment_method)
        if not approved:
            return False, f"Payment was declined (reference: {reference})"
        # Persist sale, sale items, decrement stock and record payment
        try:
            with self.conn:
                sale_id = self.sale_dao.create_sale(
                    user_id=self.current_user_id,
                    items=sale_items,
                    subtotal=subtotal,
                    total=total,
                    status="Completed",
                )
                # Update stock
                for item in sale_items:
                    product = self.product_dao.get_product(item.product_id)
                    if product is None:
                        raise ValueError(f"Product with ID {item.product_id} missing during checkout")
                    new_stock = product.stock - item.quantity
                    if new_stock < 0:
                        raise RuntimeError(
                            f"Concurrency conflict: insufficient stock for {product.name}"
                        )
                    self.product_dao.update_stock(item.product_id, new_stock)
                # Record payment
                self.payment_dao.record_payment(
                    sale_id=sale_id,
                    method=payment_method,
                    reference=reference,
                    amount=total,
                    status="Approved",
                )
            # Clear cart and build receipt
            self.cart.clear()
            receipt_lines = [f"Sale ID: {sale_id}"]
            for item in sale_items:
                product = self.product_dao.get_product(item.product_id)
                line_total = item.unit_price * item.quantity
                receipt_lines.append(
                    f" - {product.name} x {item.quantity} @ {item.unit_price:.2f} = {line_total:.2f}"
                )
            receipt_lines.append(f"Subtotal: {subtotal:.2f}")
            receipt_lines.append(f"Total: {total:.2f}")
            receipt_lines.append(f"Payment Method: {payment_method}")
            receipt_lines.append(f"Payment Ref: {reference}")
            return True, "\n".join(receipt_lines)
        except Exception as e:
            return False, str(e)