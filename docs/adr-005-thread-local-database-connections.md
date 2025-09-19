# ADR-005: Use Thread-Local Storage for Database Connection Management

## Status
Accepted

## Context
The application needs to manage database connections across multiple HTTP requests. We need a strategy that ensures each request gets its own database connection while avoiding connection leaks and ensuring proper transaction isolation.

## Decision
Use Python's `threading.local()` to store database connections per thread:
- `_thread_local = threading.local()` for connection storage
- `get_request_connection()` function to retrieve or create connections
- Automatic connection creation on first access
- Foreign key constraints enabled on each new connection
- Connection cleanup handled by garbage collection

## Consequences

### Positive
- **Request isolation** - Each HTTP request gets its own database connection
- **Transaction safety** - No connection sharing between concurrent requests
- **Automatic cleanup** - Connections are garbage collected when threads end
- **Simple API** - Single function to get connections throughout the application
- **No connection pooling complexity** - Avoids the overhead of connection pool management

### Negative
- **Thread dependency** - Relies on Python's threading model
- **Connection overhead** - New connection created for each thread
- **No connection reuse** - Cannot benefit from connection pooling
- **Debugging complexity** - Thread-local state can be hard to debug
- **Limited scalability** - Not suitable for high-concurrency scenarios

### Neutral
- **Memory usage** - Each thread holds one connection
- **Performance** - SQLite handles concurrent reads well, single writer limitation

## Implementation Details
```python
_thread_local = threading.local()

def get_request_connection() -> sqlite3.Connection:
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = _new_connection(_resolve_db_path())
    return _thread_local.conn
```

## Alternative Considered
Connection pooling was considered but rejected due to:
- Added complexity for a demo application
- SQLite's single-writer limitation makes pooling less beneficial
- Thread-local approach is simpler and sufficient for the use case
