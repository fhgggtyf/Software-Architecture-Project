"""
Data Access Objects (DAOs) and domain models for the minimal retail app.

This module uses Python's built-in sqlite3.Connections are managed per 
thread via a module-level thread-local; call`get_request_connection()` to 
obtain the current thread's connection.

Database path resolution:
- `RETAIL_DB_PATH` environment variable, if set
- Otherwise defaults to ../db/retail.db (resolved relative to this file)

Each DAO lazily resolves a connection via `get_request_connection()` unless an
explicit `sqlite3.Connection` is passed to the DAO's constructor. Use an
explicit connection (and a `with conn:` block) to group operations atomically.

Foreign keys are enabled (`PRAGMA foreign_keys = ON`) for every new connection.
"""


from __future__ import annotations

import datetime
import hashlib
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import List, Optional, Tuple

# In the original implementation this module attempted to import
# ``flask.g`` and related functions in order to maintain a per‑request
# database connection when running under a Flask application.  Since
# Flask is no longer a dependency of this project, we instead rely on
# a thread‑local storage object to hold per‑session connections.  The
# ``has_app_context`` function now always returns ``False`` so that
# Flask‑specific code paths are bypassed.
g = threading.local()  # type: ignore

def has_app_context() -> bool:
    """Return False to indicate that no Flask app context is active."""
    return False

###############################################################################
# Connection management (per request with Flask, fallback to thread‑local)
###############################################################################

# Default DB path: ../db/retail.db relative to this file
_DEFAULT_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db", "retail.db")
)

_thread_local = threading.local()

def _ensure_parent_dir(path: str) -> None:
    """Ensure the parent directory of the given path exists."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

def _new_connection(db_path: str) -> sqlite3.Connection:
    """Create a new SQLite connection and enable foreign keys."""
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def _resolve_db_path() -> str:
    """
    Determine the path to the database file.

    Without Flask in the picture the configuration is simplified:
    * If the ``RETAIL_DB_PATH`` environment variable is set, its value
      is used.
    * Otherwise the built‑in default of ``db/retail.db`` relative to
      this source file is returned.
    """
    return os.environ.get("RETAIL_DB_PATH", _DEFAULT_DB_PATH)

def get_request_connection() -> sqlite3.Connection:
    """
    Return a per‑request connection if inside a Flask request, otherwise a
    thread‑local connection.
    """
    if has_app_context():
        if not hasattr(g, "_retail_db_conn"):
            setattr(g, "_retail_db_conn", _new_connection(_resolve_db_path()))
        return getattr(g, "_retail_db_conn")

    # Fallback for CLI/tests
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = _new_connection(_resolve_db_path())
    return _thread_local.conn  # type: ignore[attr-defined]

###############################################################################
# Domain models
###############################################################################

@dataclass
class Product:
    id: int
    name: str
    price: float
    stock: int

@dataclass
class Payment:
    id: int
    sale_id: int
    method: str
    reference: str
    amount: float
    status: str
    timestamp: str

@dataclass
class SaleItemData:
    product_id: int
    quantity: int
    unit_price: float

@dataclass
class Sale:
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
    """Base class for all DAOs. Ensures table creation on first instantiation."""

    def __init__(self, conn: Optional[sqlite3.Connection] = None) -> None:
        self._conn_explicit = conn
        self.create_table()

    def _conn(self) -> sqlite3.Connection:
        return self._conn_explicit or get_request_connection()

    def create_table(self) -> None:
        """Override to create the corresponding table(s)."""
        raise NotImplementedError

###############################################################################
# UserDAO
###############################################################################

class UserDAO(BaseDAO):
    """Data Access Object for the User table."""

    def create_table(self) -> None:
        """Create the User table with an is_admin flag (default 0)."""
        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS User (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0
            );
            """
        )

    def register_user(self, username: str, password: str) -> bool:
        """Register a new user with a SHA‑256 hashed password."""
        conn = self._conn()
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO User (username, password_hash) VALUES (?, ?);",
                    (username, password_hash),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def authenticate(self, username: str, password: str) -> Optional[int]:
        """Return user_id if the username/password matches, else None."""
        conn = self._conn()
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        cur = conn.execute(
            "SELECT id FROM User WHERE username = ? AND password_hash = ?;",
            (username, password_hash),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def set_admin(self, username: str, is_admin: bool = True) -> bool:
        """Grant or revoke admin privileges for a given user."""
        conn = self._conn()
        try:
            with conn:
                conn.execute(
                    "UPDATE User SET is_admin = ? WHERE username = ?;",
                    (1 if is_admin else 0, username),
                )
            return True
        except Exception:
            return False

    def is_admin(self, username: str) -> bool:
        """Check if the user has admin privileges."""
        conn = self._conn()
        cur = conn.execute("SELECT is_admin FROM User WHERE username = ?;", (username,))
        row = cur.fetchone()
        return bool(row["is_admin"]) if row else False

###############################################################################
# ProductDAO (unchanged except for bug fix in get_product and update_name_price)
###############################################################################

class ProductDAO(BaseDAO):
    """DAO for Product records."""

    def create_table(self) -> None:
        conn = self._conn()
        conn.execute(
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
        """Add a new product. Raises sqlite3.IntegrityError if the name already exists."""
        conn = self._conn()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO Product (name, price, stock) VALUES (?, ?, ?);",
                    (name, price, stock),
                )
            return cur.lastrowid
        except sqlite3.IntegrityError:
            # Raised if unique index idx_product_name rejects duplicate
            raise

    def get_product(self, product_id: int) -> Optional[Product]:
        """Return a Product or None if not found."""
        conn = self._conn()
        cur = conn.execute(
            "SELECT id, name, price, stock FROM Product WHERE id = ?;",
            (product_id,),
        )
        row = cur.fetchone()
        return Product(*row) if row else None

    def list_products(self) -> List[Product]:
        """Return all products in ascending ID order."""
        conn = self._conn()
        cur = conn.execute("SELECT id, name, price, stock FROM Product ORDER BY id;")
        return [Product(*row) for row in cur.fetchall()]

    def update_stock(self, product_id: int, new_stock: int) -> None:
        """
        Update a product's stock level and commit the change.

        Without explicitly committing, SQLite will defer transactions
        until another commit occurs.  Wrapping the ``UPDATE`` in a
        ``with conn:`` context manager ensures the change is written
        immediately—especially important when editing stock from the
        admin interface.
        """
        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE Product SET stock = ? WHERE id = ?;",
                (new_stock, product_id),
            )

    def update_name_price(self, product_id: int, name: str, price: float) -> None:
        """Update a product’s name and price in one statement."""
        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE Product SET name = ?, price = ? WHERE id = ?;",
                (name, price, product_id),
            )

    def delete_product(self, product_id: int) -> None:
        """
        Permanently remove a product from the catalogue.

        Attempts to delete the product row with the given ID. If there
        are existing `SaleItem` records referencing this product via
        foreign keys, SQLite will raise an ``IntegrityError`` (unless
        the foreign key is configured to cascade).  Callers should
        handle ``sqlite3.IntegrityError`` to provide user feedback.
        """
        conn = self._conn()
        with conn:
            conn.execute(
                "DELETE FROM Product WHERE id = ?;",
                (product_id,),
            )


###############################################################################
# Payment DAO
###############################################################################

class PaymentDAO(BaseDAO):
    """Data Access Object for the `Payment` table."""

    def create_table(self) -> None:
        conn = self._conn()
        conn.execute(
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
        conn = self._conn()
        timestamp = datetime.datetime.utcnow().isoformat()
        cur = conn.execute(
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
        conn = self._conn()
        # Create the Sale table
        conn.execute(
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
        conn.execute(
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
        """Create a sale and its associated line items in a single transaction."""
        conn = self._conn()
        timestamp = datetime.datetime.utcnow().isoformat()
        with conn:
            # Insert sale
            cur = conn.execute(
                "INSERT INTO Sale (user_id, timestamp, subtotal, total, status)"
                " VALUES (?, ?, ?, ?, ?);",
                (user_id, timestamp, subtotal, total, status),
            )
            sale_id = cur.lastrowid
            # Insert sale items
            for item in items:
                conn.execute(
                    "INSERT INTO SaleItem (sale_id, product_id, quantity, unit_price)"
                    " VALUES (?, ?, ?, ?);",
                    (sale_id, item.product_id, item.quantity, item.unit_price),
                )
        return sale_id

    def get_sale(self, sale_id: int) -> Tuple[Sale, List[SaleItemData]]:
        """Retrieve a sale and its line items by ID."""
        conn = self._conn()
        cur = conn.execute(
            "SELECT id, user_id, timestamp, subtotal, total, status FROM Sale WHERE id = ?;",
            (sale_id,),
        )
        sale_row = cur.fetchone()
        if not sale_row:
            raise ValueError(f"Sale with ID {sale_id} does not exist")
        sale = Sale(*sale_row)
        # Fetch sale items
        item_cur = conn.execute(
            "SELECT product_id, quantity, unit_price FROM SaleItem WHERE sale_id = ?;",
            (sale_id,),
        )
        items = [SaleItemData(*row) for row in item_cur.fetchall()]
        return sale, items

# NOTE: the functions below were originally defined at module scope.  They
# effectively duplicated the `set_admin` and `is_admin` methods on `UserDAO` and
# operated on whichever connection happened to be returned by
# `get_request_connection()`.  Having module‑level functions that shadow
# instance methods can lead to confusing behaviour and bugs, so these
# definitions were removed.  Please use the `UserDAO.set_admin` and
# `UserDAO.is_admin` methods on a DAO instance instead.
