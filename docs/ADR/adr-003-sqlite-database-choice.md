# ADR-003: Use SQLite as the Primary Database

## Status
Accepted

## Context
The retail application needs a database to persist user accounts, product catalog, sales transactions, and payment records. The application should be easy to deploy and run without requiring a separate database server installation.

## Decision
Use SQLite as the primary database engine with the following characteristics:
- File-based database stored in `db/retail.db`
- Foreign key constraints enabled (`PRAGMA foreign_keys = ON`)
- Row factory for named column access
- Automatic table creation on first connection
- Environment variable `RETAIL_DB_PATH` for database path configuration

## Consequences

### Positive
- **Zero configuration** - No separate database server required
- **Portability** - Database file can be easily copied and moved
- **ACID compliance** - Full transaction support with rollback capabilities
- **Python integration** - Built-in `sqlite3` module requires no additional dependencies
- **Development simplicity** - Easy to reset database by deleting the file
- **Cross-platform** - Works on Windows, macOS, and Linux without changes

### Negative
- **Concurrency limitations** - Single writer limitation may impact performance
- **No network access** - Database file must be accessible to the application process
- **Limited scalability** - Not suitable for high-traffic production applications
- **No user management** - All database access uses the same file permissions
- **Backup complexity** - Requires file-level backup strategies

### Neutral
- **Feature set** - Sufficient for the application's requirements
- **Performance** - Adequate for single-user and small multi-user scenarios

## Database Schema
```sql
User (id, username, password_hash, is_admin)
Product (id, name, price, stock)
Sale (id, user_id, timestamp, subtotal, total, status)
SaleItem (id, sale_id, product_id, quantity, unit_price)
Payment (id, sale_id, method, reference, amount, status, timestamp)
```

## Alternative Considered
PostgreSQL was considered but rejected due to:
- Additional installation requirements
- Increased complexity for deployment
- Overkill for the application's scale requirements
