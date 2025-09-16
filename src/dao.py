"""
Data Access Objects (DAOs) and domain models for the minimal retail app.

This module contains all database schema definitions and related data
structures.  Each table has a corresponding DAO class that exposes
simple CRUD operations.  Using the DAO pattern encapsulates SQL
statements in a single place, making the rest of the application
agnostic of how data is persisted.
"""

import datetime
import hashlib
import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple


###############################################################################
# Domain Models
###############################################################################

@dataclass
class Product:
    """In‑memory representation of a product record."""

    id: int
    name: str
    price: float
    stock: int


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


###############################################################################
# Base DAO
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


###############################################################################
# User DAO
###############################################################################

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


###############################################################################
# Product DAO
###############################################################################

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


###############################################################################
# Payment DAO
###############################################################################

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


###############################################################################
# Sale DAO
###############################################################################

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