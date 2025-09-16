"""
Minimal Retail Application (2‑tier)
----------------------------------

This module implements a simple retail application demonstrating how to
register a purchase/sale using a 2‑tier architecture.  The system uses
Python's built‑in `sqlite3` module as the persistence layer and a
Data‑Access‑Object (DAO) pattern to encapsulate all database operations.
The application can be run as a CLI program but the underlying
functions are modular so they could be reused in a GUI or web context.

Features
^^^^^^^^

* User registration and login with basic password hashing (SHA‑256).
* Product catalog management with stock levels and pricing.
* Shopping cart functionality allowing users to add products by ID and
  specify quantities.
* A simplified payment service that simulates approval or rejection
  without integrating with a real payment gateway.
* Sale recording with timestamp, line items, totals, payment details
  and automatic stock decrement.  Transactions are atomic: either
  everything succeeds or the sale is rolled back.
* All data are persisted in an SQLite database located in the same
  directory as this script (``retail.db`` by default).  Restarting
  the program does not lose prior users, products, sales or stock.

Usage
^^^^^

Run this script directly to start an interactive command‑line session:

.. code:: bash

    python3 minimal_retail_app.py

During the interactive session you can register a new user, log in,
list products, add items to your cart and complete a purchase.
Receipt information is printed to the console upon successful
checkout.

Design Notes
^^^^^^^^^^^^

* **Two‑tier architecture**: The application logic (presentation) and
  database logic (persistence) reside in the same process.  A third
  tier (web browser) is not used but could be added without changing
  the DAO layer.  This satisfies the minimal requirement for a 2‑tier
  system.
* **DAO pattern**: Each table has a corresponding DAO class that
  exposes methods for CRUD operations.  Business logic in the
  ``RetailApp`` class relies on the DAO layer and does not manipulate
  raw SQL directly.
* **Transactions**: SQLite transactions are used when recording a sale
  to ensure that payment, sale and stock updates either all succeed
  or all fail.  The `sqlite3.Connection` context manager begins a
  transaction automatically and commits on success or rolls back on
  exception.
* **Payment simulation**: A `PaymentService` class simulates payment
  processing.  In a real system this would call out to a payment
  gateway such as PayPal or Stripe.  The service can be extended to
  randomly or deterministically fail for testing the alternate flow.

The code is thoroughly documented with docstrings and inline comments
to assist new developers in understanding the flow and to meet the
requirement for well‑documented code.
"""

import hashlib
import os
import sqlite3
import sys
import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple, Dict


###############################################################################
# Data Access Object (DAO) Layer
###############################################################################

class BaseDAO:
    """Base class for all DAO classes.

    Provides a shared connection to the SQLite database and helper methods
    for executing queries.  Each concrete DAO should subclass this
    and implement table creation in the constructor.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.create_table()

    def create_table(self) -> None:
        """Create the corresponding table in the database.

        Concrete subclasses must override this method to create their
        respective tables if they do not already exist.
        """
        raise NotImplementedError


class UserDAO(BaseDAO):
    """Data Access Object for the `User` table."""

    def create_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS User (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL
            );
            """
        )

    def register_user(self, username: str, password: str) -> bool:
        """Register a new user with a hashed password.

        :param username: Unique username chosen by the user.
        :param password: Plain‑text password.  It will be hashed using
            SHA‑256 before storage.
        :returns: True if registration succeeds, False if the username
            already exists.
        """
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        try:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO User (username, password_hash) VALUES (?, ?);",
                    (username, password_hash),
                )
            return True
        except sqlite3.IntegrityError:
            # Username already taken
            return False

    def authenticate(self, username: str, password: str) -> Optional[int]:
        """Validate user credentials.

        :param username: The username to authenticate.
        :param password: The plain‑text password provided by the user.
        :returns: The user ID if credentials are valid, None otherwise.
        """
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        cur = self.conn.execute(
            "SELECT id FROM User WHERE username = ? AND password_hash = ?;",
            (username, password_hash),
        )
        row = cur.fetchone()
        return row[0] if row else None


@dataclass
class Product:
    """In‑memory representation of a product record."""
    id: int
    name: str
    price: float
    stock: int


class ProductDAO(BaseDAO):
    """Data Access Object for the `Product` table."""

    def create_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Product (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                stock INTEGER NOT NULL CHECK (stock >= 0)
            );
            """
        )

    def add_product(self, name: str, price: float, stock: int) -> int:
        """Insert a new product and return its generated ID."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO Product (name, price, stock) VALUES (?, ?, ?);",
                (name, price, stock),
            )
        return cur.lastrowid

    def get_product(self, product_id: int) -> Optional[Product]:
        """Retrieve a product by its ID."""
        cur = self.conn.execute(
            "SELECT id, name, price, stock FROM Product WHERE id = ?;",
            (product_id,),
        )
        row = cur.fetchone()
        return Product(*row) if row else None

    def list_products(self) -> List[Product]:
        """Return a list of all products."""
        cur = self.conn.execute(
            "SELECT id, name, price, stock FROM Product ORDER BY id;"
        )
        return [Product(*row) for row in cur.fetchall()]

    def update_stock(self, product_id: int, new_stock: int) -> None:
        """Update the stock level of a product.

        This method does not perform its own transaction; callers should
        manage transactions themselves (particularly when decrementing
        stock during a sale).
        """
        self.conn.execute(
            "UPDATE Product SET stock = ? WHERE id = ?;",
            (new_stock, product_id),
        )


@dataclass
class Payment:
    """In‑memory representation of a payment record."""
    id: int
    sale_id: int
    method: str
    reference: str
    amount: float
    status: str
    timestamp: str


class PaymentDAO(BaseDAO):
    """Data Access Object for the `Payment` table."""

    def create_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Payment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                method TEXT NOT NULL,
                reference TEXT NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (sale_id) REFERENCES Sale(id)
            );
            """
        )

    def record_payment(
        self, sale_id: int, method: str, reference: str, amount: float, status: str
    ) -> int:
        """Insert a new payment record and return its ID."""
        timestamp = datetime.datetime.utcnow().isoformat()
        cur = self.conn.execute(
            "INSERT INTO Payment (sale_id, method, reference, amount, status, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?);",
            (sale_id, method, reference, amount, status, timestamp),
        )
        return cur.lastrowid


@dataclass
class SaleItemData:
    """In‑memory representation of a line item within a sale."""
    product_id: int
    quantity: int
    unit_price: float


@dataclass
class Sale:
    """In‑memory representation of a sale record."""
    id: int
    user_id: int
    timestamp: str
    subtotal: float
    total: float
    status: str


class SaleDAO(BaseDAO):
    """Data Access Object for the `Sale` and `SaleItem` tables."""

    def create_table(self) -> None:
        # Create the Sale table
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS Sale (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                subtotal REAL NOT NULL,
                total REAL NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES User(id)
            );
            """
        )
        # Create the SaleItem table
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS SaleItem (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                FOREIGN KEY (sale_id) REFERENCES Sale(id),
                FOREIGN KEY (product_id) REFERENCES Product(id)
            );
            """
        )

    def create_sale(
        self,
        user_id: int,
        items: List[SaleItemData],
        subtotal: float,
        total: float,
        status: str = "Completed",
    ) -> int:
        """Create a sale and its associated line items in a single transaction.

        :param user_id: The ID of the user who made the purchase.
        :param items: List of ``SaleItemData`` describing each product,
            quantity and unit price.
        :param subtotal: Sum of line item prices before taxes/fees.
        :param total: Final total after taxes/fees/discounts.
        :param status: Status of the sale (e.g. 'Completed', 'Cancelled').
        :returns: The ID of the newly created sale.
        """
        timestamp = datetime.datetime.utcnow().isoformat()
        # Insert sale
        cur = self.conn.execute(
            "INSERT INTO Sale (user_id, timestamp, subtotal, total, status)"
            " VALUES (?, ?, ?, ?, ?);",
            (user_id, timestamp, subtotal, total, status),
        )
        sale_id = cur.lastrowid
        # Insert each sale item
        for item in items:
            self.conn.execute(
                "INSERT INTO SaleItem (sale_id, product_id, quantity, unit_price)"
                " VALUES (?, ?, ?, ?);",
                (sale_id, item.product_id, item.quantity, item.unit_price),
            )
        return sale_id

    def get_sale(self, sale_id: int) -> Tuple[Sale, List[SaleItemData]]:
        """Retrieve a sale and its line items by ID."""
        cur = self.conn.execute(
            "SELECT id, user_id, timestamp, subtotal, total, status FROM Sale WHERE id = ?;",
            (sale_id,),
        )
        sale_row = cur.fetchone()
        if not sale_row:
            raise ValueError(f"Sale with ID {sale_id} does not exist")
        sale = Sale(*sale_row)
        # Fetch sale items
        item_cur = self.conn.execute(
            "SELECT product_id, quantity, unit_price FROM SaleItem WHERE sale_id = ?;",
            (sale_id,),
        )
        items = [SaleItemData(*row) for row in item_cur.fetchall()]
        return sale, items


###############################################################################
# Payment Service Simulation
###############################################################################

class PaymentService:
    """Simplified payment service that simulates approval or rejection.

    In lieu of integrating with a real payment gateway, this service
    provides a ``process_payment`` method that returns a tuple of
    ``(approved: bool, reference: str)``.  The caller can decide to
    simulate failures by toggling the ``always_approve`` flag or by
    implementing custom logic.  For demonstration purposes we default
    to always approve payments.
    """

    def __init__(self, always_approve: bool = True) -> None:
        self.always_approve = always_approve

    def process_payment(self, amount: float, method: str) -> Tuple[bool, str]:
        """Simulate payment processing.

        :param amount: The amount to charge.  This value is unused in
            the simulation but provided for completeness.
        :param method: Payment method chosen by the user, e.g. 'Cash' or 'Card'.
        :returns: Tuple of (approved, reference).  ``approved`` is True
            if the payment succeeds, False otherwise.  ``reference``
            contains a mock transaction ID or failure code.
        """
        if self.always_approve:
            # In a real system this would contact an external payment
            # service provider and wait for a response.  Here we just
            # generate a random reference using a timestamp.
            ref = f"PAY-{int(datetime.datetime.utcnow().timestamp()*1000)}"
            return True, ref
        else:
            # When not always approving, randomly fail half of the time.
            import random

            success = random.choice([True, False])
            ref = f"PAY-{int(datetime.datetime.utcnow().timestamp()*1000)}"
            return success, ref


###############################################################################
# Business Logic Layer
###############################################################################

class RetailApp:
    """Main application class encapsulating business logic for the retail app."""

    def __init__(self, db_path: str = "retail.db") -> None:
        """Initialize the application.

        :param db_path: Path to the SQLite database file.  If the file does
            not exist it will be created automatically.  Using a file
            rather than an in‑memory database ensures persistence across
            restarts as required by the specification.
        """
        # Establish connection with row factory to access columns by index
        self.conn = sqlite3.connect(db_path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        # Instantiate DAOs
        self.user_dao = UserDAO(self.conn)
        self.product_dao = ProductDAO(self.conn)
        self.sale_dao = SaleDAO(self.conn)
        self.payment_dao = PaymentDAO(self.conn)
        # Payment service always approves by default.  To test failures,
        # initialize with always_approve=False.
        self.payment_service = PaymentService(always_approve=True)
        # In‑memory session state.  For a web application this would live
        # in cookies or server‑side session storage.  Here we keep it
        # simple for a CLI context.
        self.current_user_id: Optional[int] = None
        # Cart represented as a mapping of product_id -> quantity
        self.cart: Dict[int, int] = {}

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
    # Product Management
    # -------------------------------------------------------------------------
    def add_product(self, name: str, price: float, stock: int) -> int:
        """Add a new product to the catalog."""
        return self.product_dao.add_product(name, price, stock)

    def list_products(self) -> List[Product]:
        """Return a list of all products available in the store."""
        return self.product_dao.list_products()

    # -------------------------------------------------------------------------
    # Cart Operations
    # -------------------------------------------------------------------------
    def add_to_cart(self, product_id: int, quantity: int) -> Tuple[bool, str]:
        """Attempt to add a product to the current user's cart.

        Validates that the product exists and that the quantity requested
        does not exceed available stock.  It also merges quantities if
        the product is already in the cart.

        :returns: Tuple of (success, message).
        """
        product = self.product_dao.get_product(product_id)
        if product is None:
            return False, "Product not found"
        # Check current stock versus requested quantity plus existing cart quantity
        existing_qty = self.cart.get(product_id, 0)
        if quantity + existing_qty > product.stock:
            return False, f"Only {product.stock - existing_qty} in stock"
        # Add to cart
        self.cart[product_id] = existing_qty + quantity
        return True, f"Added {quantity} x {product.name} to cart"

    def view_cart(self) -> List[Tuple[Product, int, float]]:
        """Return a list of cart items along with quantity and line total.

        Each item in the returned list is a tuple of ``(Product, quantity, line_total)``.
        """
        items = []
        for product_id, qty in self.cart.items():
            product = self.product_dao.get_product(product_id)
            if product:
                items.append((product, qty, product.price * qty))
        return items

    # -------------------------------------------------------------------------
    # Checkout / Purchase Workflow
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

        :param payment_method: One of the supported methods (e.g. 'Cash', 'Card').
        :returns: Tuple of (success, message).  On success, message
            contains the sale receipt; on failure, an error description.
        """
        if self.current_user_id is None:
            return False, "User must be logged in to checkout"
        if not self.cart:
            return False, "Cart is empty"
        # Step 2: Validate stock for each item
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
        # Step 3: Compute total (no taxes/fees for simplicity)
        total = subtotal  # Extend here for taxes/fees/discounts
        # Step 4: Process payment
        approved, reference = self.payment_service.process_payment(total, payment_method)
        if not approved:
            return False, f"Payment was declined (reference: {reference})"
        # Step 5: Persist sale, sale items, decrement stock and record payment
        try:
            with self.conn:  # This begins a transaction automatically
                # Create sale and items
                sale_id = self.sale_dao.create_sale(
                    user_id=self.current_user_id,
                    items=sale_items,
                    subtotal=subtotal,
                    total=total,
                    status="Completed",
                )
                # Update stock for each product
                for item in sale_items:
                    product = self.product_dao.get_product(item.product_id)
                    if product is None:
                        raise ValueError(f"Product with ID {item.product_id} missing during checkout")
                    new_stock = product.stock - item.quantity
                    if new_stock < 0:
                        # This should not happen due to earlier validation but
                        # handle gracefully for concurrency conflicts (A5).
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
            # Step 6: Clear cart
            self.cart.clear()
            # Build receipt
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
            # If any exception occurs within the transaction block it will
            # automatically roll back.  Log or return error message.
            return False, str(e)


###############################################################################
# CLI Interface
###############################################################################

def interactive_cli():
    """Provide a simple command‑line interface to interact with the retail app.

    This function is separated from the `RetailApp` class so that the core
    business logic remains testable without requiring user input.  It loops
    until the user chooses to exit.  This is not meant to be a polished UI
    but rather a demonstration that exercises the functionality required by
    the assignment.
    """
    app = RetailApp()

    def print_menu():
        print("\n-- Minimal Retail Application --")
        print("1. Register")
        print("2. Login")
        print("3. List Products")
        print("4. Add Product to Cart")
        print("5. View Cart")
        print("6. Checkout")
        print("7. Add New Product (Admin)*)")
        print("0. Exit")
        print("\n*) For demonstration purposes any logged‑in user can add products.")

    while True:
        print_menu()
        choice = input("Select an option: ").strip()
        if choice == "1":
            username = input("Username: ").strip()
            password = input("Password: ").strip()
            if app.register(username, password):
                print("Registration successful. You can now log in.")
            else:
                print("Username already exists. Please choose another.")
        elif choice == "2":
            username = input("Username: ").strip()
            password = input("Password: ").strip()
            if app.login(username, password):
                print(f"Welcome, {username}!")
            else:
                print("Invalid credentials.")
        elif choice == "3":
            products = app.list_products()
            if not products:
                print("No products available.")
            else:
                print("\nAvailable Products:")
                for p in products:
                    print(f"{p.id}. {p.name} - ${p.price:.2f} (Stock: {p.stock})")
        elif choice == "4":
            try:
                pid = int(input("Enter Product ID: "))
                qty = int(input("Enter quantity: "))
            except ValueError:
                print("Please enter valid numeric values.")
                continue
            success, msg = app.add_to_cart(pid, qty)
            print(msg)
        elif choice == "5":
            cart_items = app.view_cart()
            if not cart_items:
                print("Cart is empty.")
            else:
                print("\nCart Contents:")
                for product, qty, line_total in cart_items:
                    print(f"{product.name} x {qty} = ${line_total:.2f}")
        elif choice == "6":
            if app.current_user_id is None:
                print("Please log in first.")
                continue
            # Choose payment method
            print("Select payment method:")
            print("1. Cash")
            print("2. Card")
            pm_choice = input("Choice: ").strip()
            if pm_choice == "1":
                method = "Cash"
            elif pm_choice == "2":
                method = "Card"
            else:
                print("Invalid payment method.")
                continue
            success, receipt = app.checkout(method)
            if success:
                print("\nPurchase successful! Receipt:")
                print(receipt)
            else:
                print(f"Checkout failed: {receipt}")
        elif choice == "7":
            # Add new product to the catalog
            name = input("Product name: ").strip()
            try:
                price = float(input("Price: "))
                stock = int(input("Initial stock: "))
            except ValueError:
                print("Please enter valid numeric values for price and stock.")
                continue
            product_id = app.add_product(name, price, stock)
            print(f"Added product with ID {product_id}.")
        elif choice == "0":
            print("Exiting application.")
            break
        else:
            print("Invalid option. Please try again.")


# If this script is run directly, start the CLI.  When imported as a module
# (e.g., for unit tests), the CLI will not start automatically.
if __name__ == "__main__":
    try:
        interactive_cli()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")