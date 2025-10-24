# ADR-012: Schema Versioning with PRAGMA user_version
**Status:** Accepted  


## Context
Database schema evolves between checkpoints (e.g., adding flash_sale_price, flash_sale_start, flash_sale_end fields). Need mechanism to: track schema version, apply migrations safely, prevent duplicate application, and support multiple developers/instances.

## Decision
Use SQLite's built-in PRAGMA user_version for schema versioning:
- Check version on every connection initialization
- Apply schema from init.sql only if version is 0
- Set version to 1 after successful application
- Idempotent: Safe to call multiple times, only applies once
- Implementation: dao.py (lines 45-65)

```python
def _apply_schema_if_needed(conn: sqlite3.Connection) -> None:
    (ver,) = conn.execute("PRAGMA user_version;").fetchone()
    if int(ver) > 0:
        return  # Schema already applied
    
    schema_path = _find_schema_path()  # Finds db/init.sql
    if not schema_path:
        raise FileNotFoundError("Cannot locate db/init.sql")
    
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    
    conn.execute("PRAGMA user_version = 1;")
```

## Consequences
**Positive:**
- Schema applied exactly once per database file
- Safe for multiple connections and concurrent access
- Future migrations easy: version 2, 3, etc. with conditional application
- No external migration tools needed (Alembic, Flyway)

**Negative:**
- Must manage migration scripts manually (acceptable for project scale)
- No automatic rollback (manual intervention required)

**Trade-offs:**
- Built-in vs external tool: Chose built-in for simplicity; Alembic overkill for 5 tables
- Manual vs automatic migrations: Chose manual - full control, sufficient for team size

## Alternatives Considered
- **Alembic/SQLAlchemy Migrations** - Rejected: Heavyweight for 5 tables; adds dependencies
- **Manual Schema Creation** - Rejected: Error-prone, not repeatable, not version-controlled
