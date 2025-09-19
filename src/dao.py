"""
Data Access Objects (DAOs) and domain models for the minimal retail app.

- Uses Python's built-in sqlite3 with per-thread connection.
- Resolves DB path from RETAIL_DB_PATH or defaults to ../db/retail.db relative to this file.
- On first connection, runs db/init.sql (or RETAIL_SCHEMA_PATH) to create the schema.
- Foreign keys are enforced for every connection (PRAGMA foreign_keys = ON).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import List, Optional, Tuple

# ------------------------------------------------------------------------------
# Connection management (thread-local)
# ------------------------------------------------------------------------------

# Default DB path: ../db/retail.db relative to this file
_THIS_FILE = Path(__file__).resolve()
_DEFAULT_DB_PATH = (_THIS_FILE.parent / ".." / "db" / "retail.db").resolve()

_thread_local = threading.local()


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _find_schema_path() -> Optional[Path]:
    """Find db/init.sql, preferring RETAIL_SCHEMA_PATH if provided."""
    env = os.environ.get("RETAIL_SCHEMA_PATH")
    if env:
        p = Path(env).expanduser().resolve()
        return p if p.is_file() else None

    candidates = [
        # repo root layout
        _THIS_FILE.parent / ".." / "db" / "init.sql",
        # if someone runs from root and code is *also* in root
        _THIS_FILE.parent / "db" / "init.sql",
        # one level up fallback
        _THIS_FILE.parent / "../db/init.sql",
    ]
    for c in candidates:
        c = c.resolve()
        if c.is_file():
            return c
    return None


def _apply_schema_if_needed(conn: sqlite3.Connection) -> None:
    """
    Apply schema from init.sql exactly once per DB file using PRAGMA user_version.
    If user_version == 0, attempt to run schema and then set it to 1.
    """
    # If user_version already set, assume schema applied
    (ver,) = conn.execute("PRAGMA user_version;").fetchone()
    if int(ver) > 0:
        return

    schema_path = _find_schema_path()
    if not schema_path:
        # If we can't find a schema file but tables already exist, just set a version.
        # Otherwise, raise a helpful error.
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('User','Product','Sale','SaleItem','Payment');"
        ).fetchall()
        if existing:
            conn.execute("PRAGMA user_version = 1;")
            return
        raise FileNotFoundError(
            "Could not locate db/init.sql and schema tables do not exist. "
            "Set RETAIL_SCHEMA_PATH or place init.sql under ./db/."
        )

    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()
    conn.executescript(sql)
    conn.execute("PRAGMA user_version = 1;")


def _resolve_db_path() -> str:
    return os.environ.get("RETAIL_DB_PATH", str(_DEFAULT_DB_PATH))


def _new_connection(db_path: str) -> sqlite3.Connection:
    """Create a new SQLite connection, enforce FKs, and ensure schema exists."""
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    _apply_schema_if_needed(conn)
    return conn


def get_request_connection() -> sqlite3.Connection:
    """Return a per-thread connection."""
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = _new_connection(_resolve_db_path())
    return _thread_local.conn  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------
# Domain models
# ------------------------------------------------------------------------------

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


# ------------------------------------------------------------------------------
# Base DAO
# ------------------------------------------------------------------------------

class BaseDAO:
    """
    Base class for all DAOs.

    NOTE: Schema creation is now handled centrally via init.sql at connection time.
    The create_table() methods below remain as no-ops (or use IF NOT EXISTS) so
    the public API is unchanged.
    """

    def __init__(self, conn: Optional[sqlite3.Connection] = None) -> None:
        self._conn_explicit = conn
        # keep behavior: subclasses may still call create_table (safe with IF NOT EXISTS)
        try:
            self.create_table()
        except Exception:
            # Silently ignore if schema already exists or we rely on init.sql only.
            pass

    def _conn(self) -> sqlite3.Connection:
        return self._conn_explicit if self._conn_explicit is not None else get_request_connection()

    def create_table(self) -> None:
        """Default no-op; subclasses may override with IF NOT EXISTS."""
        return


# ------------------------------------------------------------------------------
# User DAO
# ------------------------------------------------------------------------------

class UserDAO(BaseDAO):
    """Data Access Object for the User table."""

    def create_table(self) -> None:
        # Safe no-op: CREATE TABLE IF NOT EXISTS
        self._conn().execute(
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
        conn = self._conn()
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        row = conn.execute(
            "SELECT id FROM User WHERE username = ? AND password_hash = ?;",
            (username, password_hash),
        ).fetchone()
        return row[0] if row else None

    def set_admin(self, username: str, is_admin: bool = True) -> bool:
        conn = self._conn()
        with conn:
            cur = conn.execute(
                "UPDATE User SET is_admin = ? WHERE username = ?;",
                (1 if is_admin else 0, username),
            )
        return cur.rowcount > 0

    def is_admin(self, username: str) -> bool:
        conn = self._conn()
        row = conn.execute("SELECT is_admin FROM User WHERE username = ?;", (username,)).fetchone()
        return bool(row["is_admin"]) if row else False


# ------------------------------------------------------------------------------
# Product DAO
# ------------------------------------------------------------------------------

class ProductDAO(BaseDAO):
    """DAO for Product records."""

    def create_table(self) -> None:
        self._conn().execute(
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
        conn = self._conn()
        with conn:
            cur = conn.execute(
                "INSERT INTO Product (name, price, stock) VALUES (?, ?, ?);",
                (name, price, stock),
            )
        return cur.lastrowid

    def get_product(self, product_id: int) -> Optional[Product]:
        row = self._conn().execute(
            "SELECT id, name, price, stock FROM Product WHERE id = ?;", (product_id,)
        ).fetchone()
        return Product(*row) if row else None

    def list_products(self) -> List[Product]:
        cur = self._conn().execute("SELECT id, name, price, stock FROM Product ORDER BY id;")
        return [Product(*r) for r in cur.fetchall()]

    def update_stock(self, product_id: int, new_stock: int) -> None:
        conn = self._conn()
        with conn:
            conn.execute("UPDATE Product SET stock = ? WHERE id = ?;", (new_stock, product_id))

    def update_name_price(self, product_id: int, name: str, price: float) -> None:
        conn = self._conn()
        with conn:
            conn.execute(
                "UPDATE Product SET name = ?, price = ? WHERE id = ?;", (name, price, product_id)
            )

    def delete_product(self, product_id: int) -> None:
        conn = self._conn()
        with conn:
            conn.execute("DELETE FROM Product WHERE id = ?;", (product_id,))


# ------------------------------------------------------------------------------
# Payment DAO
# ------------------------------------------------------------------------------

class PaymentDAO(BaseDAO):
    """DAO for the Payment table."""

    def create_table(self) -> None:
        self._conn().execute(
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
        conn = self._conn()
        ts = datetime.now(UTC).isoformat()
        cur = conn.execute(
            "INSERT INTO Payment (sale_id, method, reference, amount, status, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?);",
            (sale_id, method, reference, amount, status, ts),
        )
        return cur.lastrowid


# ------------------------------------------------------------------------------
# Sale DAO
# ------------------------------------------------------------------------------

class SaleDAO(BaseDAO):
    """DAO for the Sale and SaleItem tables."""

    def create_table(self) -> None:
        conn = self._conn()
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
        status: str,
    ) -> int:
        conn = self._conn()
        ts = datetime.now(UTC).isoformat()
        with conn:
            cur = conn.execute(
                "INSERT INTO Sale (user_id, timestamp, subtotal, total, status)"
                " VALUES (?, ?, ?, ?, ?);",
                (user_id, ts, subtotal, total, status),
            )
            sale_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO SaleItem (sale_id, product_id, quantity, unit_price)"
                " VALUES (?, ?, ?, ?);",
                [(sale_id, it.product_id, it.quantity, it.unit_price) for it in items],
            )
        return sale_id
