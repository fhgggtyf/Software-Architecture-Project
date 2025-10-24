"""
Modified DAO module implementing Scenario 1.2 (Database Failure Recovery)

Adds:
 - automatic switch to READ-ONLY mode when DB fails
 - queuing of write operations during outage
 - background reconnection + replay of queued writes
"""

from __future__ import annotations
import hashlib, os, sqlite3, threading, time, logging
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Global fallback state
# ------------------------------------------------------------------------------
_thread_local = threading.local()
_read_only_mode = False
_write_queue = []
_last_failure_time = 0.0
_RETRY_INTERVAL = 10  # seconds

_THIS_FILE = Path(__file__).resolve()
_DEFAULT_DB_PATH = (_THIS_FILE.parent / ".." / "db" / "retail.db").resolve()

# ------------------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------------------
def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

def _resolve_db_path() -> str:
    return os.environ.get("RETAIL_DB_PATH", str(_DEFAULT_DB_PATH))

def _find_schema_path() -> Optional[Path]:
    env = os.environ.get("RETAIL_SCHEMA_PATH")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_file():
            return p
    candidates = [
        _THIS_FILE.parent / ".." / "db" / "init.sql",
        _THIS_FILE.parent / "db" / "init.sql",
        _THIS_FILE.parent / "../db/init.sql",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None

def _apply_schema_if_needed(conn: sqlite3.Connection) -> None:
    (ver,) = conn.execute("PRAGMA user_version;").fetchone()
    if int(ver) > 0:
        return
    schema_path = _find_schema_path()
    if not schema_path:
        conn.execute("PRAGMA user_version = 1;")
        return
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()
    conn.executescript(sql)
    conn.execute("PRAGMA user_version = 1;")

# ------------------------------------------------------------------------------
# Connection management with fallback
# ------------------------------------------------------------------------------
def _new_connection(read_only=False) -> sqlite3.Connection:
    db_path = _resolve_db_path()
    _ensure_parent_dir(db_path)
    try:
        if read_only:
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        _apply_schema_if_needed(conn)
        return conn
    except sqlite3.OperationalError as e:
        logger.error(f"DB open failed ({'ro' if read_only else 'rw'}): {e}")
        raise

def get_request_connection() -> sqlite3.Connection:
    """Return a per-thread connection (read-only if needed)."""
    global _read_only_mode, _last_failure_time
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        try:
            conn = _new_connection(read_only=_read_only_mode)
            _thread_local.conn = conn
        except sqlite3.OperationalError:
            _read_only_mode = True
            _last_failure_time = time.time()
            conn = _new_connection(read_only=True)
            _thread_local.conn = conn
    return conn

# ------------------------------------------------------------------------------
# Read/write wrappers (queueing)
# ------------------------------------------------------------------------------
def execute_read(query, params=()):
    conn = get_request_connection()
    with conn:
        cur = conn.execute(query, params)
        return cur.fetchall()

def execute_write(query, params=()):
    """Execute write; if DB down or in read-only, queue the statement."""
    global _read_only_mode
    try:
        if _read_only_mode:
            _write_queue.append((query, params))
            logger.warning("DB read-only; queued write.")
            return False
        conn = get_request_connection()
        with conn:
            conn.execute(query, params)
        return True
    except sqlite3.OperationalError as e:
        logger.error(f"Write failed: {e}")
        _read_only_mode = True
        _last_failure_time = time.time()
        _write_queue.append((query, params))
        return False

# ------------------------------------------------------------------------------
# Background reconnection worker
# ------------------------------------------------------------------------------
def _recovery_worker():
    global _read_only_mode
    while True:
        time.sleep(_RETRY_INTERVAL)
        if not _read_only_mode:
            continue
        try:
            conn = _new_connection(read_only=False)
            with conn:
                while _write_queue:
                    q, p = _write_queue.pop(0)
                    conn.execute(q, p)
            conn.close()
            _read_only_mode = False
            logger.info("DB recovered; queued writes flushed.")
        except sqlite3.OperationalError:
            logger.warning("Still cannot reconnect to DB.")

def start_recovery_thread():
    t = threading.Thread(target=_recovery_worker, daemon=True)
    t.start()

start_recovery_thread()
# ------------------------------------------------------------------------------
# Domain models
# ------------------------------------------------------------------------------

@dataclass
class Product:
    id: int
    name: str
    price: float
    stock: int
    # Optional flash sale fields.  If flash_sale_start and flash_sale_end
    # define a period encompassing the current time and flash_sale_price is
    # defined, the product may be sold at flash_sale_price instead of price.
    flash_sale_price: float | None = None
    flash_sale_start: str | None = None
    flash_sale_end: str | None = None


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
                stock INTEGER NOT NULL CHECK (stock >= 0),
                flash_sale_price REAL,
                flash_sale_start TEXT,
                flash_sale_end TEXT
            );
            """
        )

    def add_product(
        self,
        name: str,
        price: float,
        stock: int,
        flash_sale_price: float | None = None,
        flash_sale_start: str | None = None,
        flash_sale_end: str | None = None,
    ) -> int:
        """
        Add or update a product:
        - If same name & price & same sale window: increment stock.
        - If same name & price but different sale window: update sale fields.
        - Otherwise, insert a new product.
        """
        conn = self._conn()
        with conn:
            # 1️⃣ Try to find a product with same name & price
            cur = conn.execute(
                "SELECT id, stock, flash_sale_start, flash_sale_end FROM Product WHERE name = ? AND price = ?",
                (name, price),
            )
            existing = cur.fetchone()

            if existing:
                pid, current_stock, existing_start, existing_end = existing

                # 2️⃣ If flash sale window is the same → restock
                if (
                    existing_start == flash_sale_start
                    and existing_end == flash_sale_end
                ):
                    conn.execute(
                        "UPDATE Product SET stock = ? WHERE id = ?",
                        (current_stock + stock, pid),
                    )
                    return pid

                # 3️⃣ Otherwise (different window) → update the sale info instead
                conn.execute(
                    """
                    UPDATE Product
                    SET flash_sale_price = ?,
                        flash_sale_start = ?,
                        flash_sale_end = ?,
                        stock = stock + ?
                    WHERE id = ?;
                    """,
                    (flash_sale_price, flash_sale_start, flash_sale_end, stock, pid),
                )
                return pid

            # 4️⃣ No existing match — insert new product
            cur = conn.execute(
                """
                INSERT INTO Product (name, price, stock, flash_sale_price, flash_sale_start, flash_sale_end)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (name, price, stock, flash_sale_price, flash_sale_start, flash_sale_end),
            )
            return cur.lastrowid


    def get_product(self, product_id: int) -> Optional[Product]:
        row = self._conn().execute(
            "SELECT id, name, price, stock, flash_sale_price, flash_sale_start, flash_sale_end "
            "FROM Product WHERE id = ?;",
            (product_id,),
        ).fetchone()
        return Product(*row) if row else None

    def list_products(self) -> List[Product]:
        cur = self._conn().execute(
            "SELECT id, name, price, stock, flash_sale_price, flash_sale_start, flash_sale_end FROM Product ORDER BY id;"
        )
        return [Product(*r) for r in cur.fetchall()]

    def get_product_by_name(self, name: str) -> Optional[Product]:
        """Return the first product with the given name, or None if absent."""
        row = self._conn().execute(
            "SELECT id, name, price, stock, flash_sale_price, flash_sale_start, flash_sale_end "
            "FROM Product WHERE name = ? ORDER BY id LIMIT 1;",
            (name,),
        ).fetchone()
        return Product(*row) if row else None

    def upsert_product(
        self,
        name: str,
        price: float,
        stock: int,
        flash_sale_price: float | None = None,
        flash_sale_start: str | None = None,
        flash_sale_end: str | None = None,
    ) -> int:
        """
        Insert or update a product based on its name.  If a product with the
        given name exists, its price, stock, and flash sale attributes are
        updated.  Otherwise, a new product is inserted.  Returns the product ID.
        """
        conn = self._conn()
        existing = self.get_product_by_name(name)
        if existing:
            # Update existing product fields
            with conn:
                conn.execute(
                    "UPDATE Product SET price = ?, stock = ?, flash_sale_price = ?, "
                    "flash_sale_start = ?, flash_sale_end = ? WHERE id = ?;",
                    (price, stock, flash_sale_price, flash_sale_start, flash_sale_end, existing.id),
                )
            return existing.id
        else:
            return self.add_product(name, price, stock, flash_sale_price, flash_sale_start, flash_sale_end)

    def update_stock(self, product_id: int, new_stock: int) -> None:
        conn = self._conn()
        with conn:
            conn.execute("UPDATE Product SET stock = ? WHERE id = ?;", (new_stock, product_id))

    def decrease_stock_if_available(self, product_id: int, qty: int) -> bool:
        """
        Atomically decrease the stock for a product by ``qty`` only if enough
        inventory is available.  Returns True if the stock was decremented,
        False otherwise.  This method guards against race conditions in a
        concurrent checkout scenario by using a conditional update and
        inspecting the affected row count.

        :param product_id: ID of the product to update
        :param qty: Quantity to subtract from the current stock
        :returns: True if the update succeeded, False if there was insufficient stock
        """
        if qty < 0:
            raise ValueError("Quantity to decrease must be non-negative")
        conn = self._conn()
        # Use a single UPDATE statement with a WHERE clause that ensures the
        # product has sufficient stock.  SQLite guarantees that changes are
        # atomic within a transaction.  If stock would go negative, no rows
        # will be updated and rowcount will be 0.
        with conn:
            cur = conn.execute(
                "UPDATE Product SET stock = stock - ? WHERE id = ? AND stock >= ?;",
                (qty, product_id, qty),
            )
        return cur.rowcount > 0

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
