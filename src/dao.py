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
def _new_connection(read_only: bool = False) -> sqlite3.Connection:
    """Create a new SQLite connection with concurrency safeguards.

    This helper sets a busy timeout and enables Write‑Ahead Logging (WAL) on
    write‑enabled connections to mitigate ``database is locked`` errors under
    multi‑threaded access.  WAL mode allows concurrent reads during a write
    transaction, and the timeout instructs SQLite to wait for a lock to clear
    rather than failing immediately.

    Args:
        read_only: Open the database in read‑only mode when True.  Read‑only
            connections do not attempt to enable WAL.

    Returns:
        A configured :class:`sqlite3.Connection` instance.

    Raises:
        sqlite3.OperationalError: If the database cannot be opened.
    """
    db_path = _resolve_db_path()
    _ensure_parent_dir(db_path)
    try:
        if read_only:
            # Use URI mode with ``mode=ro`` for read‑only access.  Provide a
            # timeout so SQLite will wait briefly if the database is busy.
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(
                uri,
                uri=True,
                check_same_thread=False,
                timeout=10.0,
            )
        else:
            # For write‑enabled connections, include a timeout and allow
            # multi‑thread access.
            conn = sqlite3.connect(
                db_path,
                check_same_thread=False,
                timeout=10.0,
            )
        # Rows behave like dictionaries for convenience
        conn.row_factory = sqlite3.Row
        # Enforce foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")
        # Set a busy timeout on every connection.  Although ``timeout`` in
        # sqlite3.connect() applies to the initial lock attempt, setting
        # PRAGMA busy_timeout extends the waiting period for locks acquired
        # within transactions.  This helps avoid ``database is locked`` errors
        # when concurrent writes overlap.
        try:
            conn.execute("PRAGMA busy_timeout = 10000;")  # 10 seconds
        except sqlite3.OperationalError:
            pass
        # Enable WAL mode on writable connections to improve concurrency
        if not read_only:
            try:
                conn.execute("PRAGMA journal_mode = WAL;")
            except sqlite3.OperationalError:
                # If enabling WAL fails (e.g. unsupported filesystem), continue
                pass
        # Apply schema if this is a brand‑new DB
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

    def increase_stock(self, product_id: int, qty: int) -> bool:
        """Increase the available stock of a product by a specified quantity.

        This method is used when processing approved returns to put items back
        into inventory.  It rejects negative increments.

        Args:
            product_id: ID of the product to update.
            qty: Quantity to add to stock.  Must be non-negative.

        Returns:
            True if the update succeeded (a row was affected), False otherwise.
        """
        if qty < 0:
            raise ValueError("Quantity to increase must be non-negative")
        conn = self._conn()
        with conn:
            cur = conn.execute(
                "UPDATE Product SET stock = stock + ? WHERE id = ?;",
                (qty, product_id),
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

    def get_payment_for_sale(self, sale_id: int) -> Optional[Payment]:
        """Return the first payment record associated with a sale.

        Args:
            sale_id: ID of the sale.

        Returns:
            A Payment dataclass instance or None if no payment exists.
        """
        row = self._conn().execute(
            "SELECT id, sale_id, method, reference, amount, status, timestamp FROM Payment WHERE sale_id = ? LIMIT 1;",
            (sale_id,),
        ).fetchone()
        return Payment(*row) if row else None


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

    def get_sale_items(self, sale_id: int) -> List[SaleItemData]:
        """Return all items associated with a sale.

        Args:
            sale_id: ID of the sale.

        Returns:
            A list of SaleItemData objects representing the items and quantities
            purchased in the sale.
        """
        rows = self._conn().execute(
            "SELECT product_id, quantity, unit_price FROM SaleItem WHERE sale_id = ?;",
            (sale_id,),
        ).fetchall()
        return [SaleItemData(product_id=r[0], quantity=r[1], unit_price=r[2]) for r in rows]

    def update_sale_status(self, sale_id: int, status: str) -> bool:
        """Update the status of a sale.

        This helper is used by the returns module to mark a sale as
        'Refunded' or other statuses.  Returns True if at least one row
        was updated.
        """
        conn = self._conn()
        with conn:
            cur = conn.execute(
                "UPDATE Sale SET status = ? WHERE id = ?;",
                (status, sale_id),
            )
        return cur.rowcount > 0

# ------------------------------------------------------------------------------
# Returns / RMA
# ------------------------------------------------------------------------------

@dataclass
class ReturnRequest:
    """Data model for a return (RMA) request."""

    id: int
    sale_id: int
    user_id: int
    rma_number: str
    reason: str
    status: str
    request_timestamp: str
    resolution_timestamp: str | None = None
    refund_reference: str | None = None


class ReturnDAO(BaseDAO):
    """DAO for managing return requests (RMAs)."""

    def create_table(self) -> None:
        """Ensure the Return table exists.  The schema is defined in init.sql,
        but we include a CREATE TABLE IF NOT EXISTS statement here for safety
        when init.sql has not yet been applied."""
        self._conn().execute(
            """
            CREATE TABLE IF NOT EXISTS Return (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sale_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rma_number TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                request_timestamp TEXT NOT NULL,
                resolution_timestamp TEXT,
                refund_reference TEXT,
                FOREIGN KEY (sale_id) REFERENCES Sale(id),
                FOREIGN KEY (user_id) REFERENCES User(id)
            );
            """
        )

    def create_return_request(
        self, sale_id: int, user_id: int, rma_number: str, reason: str, status: str = "Pending"
    ) -> int:
        """Insert a new return request into the database.

        Args:
            sale_id: ID of the sale being returned.
            user_id: ID of the user submitting the return.
            rma_number: Unique identifier for the return (e.g. generated by application).
            reason: Reason provided by the user.
            status: Initial status (default 'Pending').

        Returns:
            The new return request ID.
        """
        conn = self._conn()
        ts = datetime.now(UTC).isoformat()
        # Use a context manager to ensure the INSERT is committed. Without
        # wrapping in ``with conn``, SQLite defers the transaction until the
        # connection is closed, which may never happen for thread‑local
        # connections.  Committing immediately guarantees that the new return
        # request is persisted and visible to subsequent queries.
        with conn:
            cur = conn.execute(
                "INSERT INTO Return (sale_id, user_id, rma_number, reason, status, request_timestamp)"
                " VALUES (?, ?, ?, ?, ?, ?);",
                (sale_id, user_id, rma_number, reason, status, ts),
            )
        return cur.lastrowid

    def update_return_status(
        self, return_id: int, status: str, refund_reference: str | None = None
    ) -> bool:
        """Update the status and optionally refund reference for a return request.

        Args:
            return_id: The return request ID.
            status: New status ('Approved', 'Rejected', 'Refunded').
            refund_reference: Optional payment refund reference returned from payment service.

        Returns:
            True if the update affected at least one row; False otherwise.
        """
        conn = self._conn()
        ts = datetime.now(UTC).isoformat()
        with conn:
            cur = conn.execute(
                "UPDATE Return SET status = ?, resolution_timestamp = ?, refund_reference = ? WHERE id = ?;",
                (status, ts, refund_reference, return_id),
            )
        return cur.rowcount > 0

    def get_return(self, return_id: int) -> Optional[ReturnRequest]:
        """Fetch a return request by ID."""
        row = self._conn().execute(
            "SELECT id, sale_id, user_id, rma_number, reason, status, request_timestamp, resolution_timestamp, refund_reference"
            " FROM Return WHERE id = ?;",
            (return_id,),
        ).fetchone()
        return ReturnRequest(*row) if row else None

    def list_returns(self, user_id: int | None = None) -> list[ReturnRequest]:
        """List return requests.  If user_id is provided, returns only that user's requests; otherwise, returns all.

        Args:
            user_id: Optional user ID to filter by.

        Returns:
            List of ReturnRequest objects.
        """
        conn = self._conn()
        if user_id is not None:
            rows = conn.execute(
                "SELECT id, sale_id, user_id, rma_number, reason, status, request_timestamp, resolution_timestamp, refund_reference"
                " FROM Return WHERE user_id = ? ORDER BY id;",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, sale_id, user_id, rma_number, reason, status, request_timestamp, resolution_timestamp, refund_reference"
                " FROM Return ORDER BY id;"
            ).fetchall()
        return [ReturnRequest(*r) for r in rows]
