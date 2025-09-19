# ADR-002: Use Data Access Object (DAO) Pattern for Database Operations

## Status
Accepted

## Context
We need to manage database operations for multiple entities (Users, Products, Sales, Payments) while maintaining clean separation between business logic and data persistence. The application uses SQLite as the database engine and needs to support both single-user and multi-user scenarios.

## Decision
Implement the Data Access Object (DAO) pattern with the following structure:
- `BaseDAO` - Abstract base class with common database connection management
- `UserDAO` - Handles user authentication, registration, and admin privileges
- `ProductDAO` - Manages product catalog operations (CRUD)
- `SaleDAO` - Handles sales transactions and line items
- `PaymentDAO` - Records payment information
- Thread-local connection management via `get_request_connection()`

## Consequences

### Positive
- **Separation of concerns** - Business logic is decoupled from database implementation
- **Testability** - Easy to mock DAOs for unit testing
- **Consistency** - Standardized approach to database operations across all entities
- **Maintainability** - Database schema changes are isolated to specific DAO classes
- **Reusability** - DAO methods can be reused across different parts of the application
- **Transaction management** - Explicit control over database transactions

### Negative
- **Code duplication** - Similar CRUD operations across different DAOs
- **Abstraction overhead** - Additional layer between business logic and database
- **Learning curve** - Developers need to understand the DAO pattern
- **Connection management complexity** - Thread-local storage adds complexity

### Neutral
- **Performance** - Minimal overhead compared to direct database access
- **Flexibility** - Easy to swap database implementations (though not implemented)

## Implementation Details
```python
class BaseDAO:
    def __init__(self, conn: Optional[sqlite3.Connection] = None)
    def _conn(self) -> sqlite3.Connection
    def create_table(self) -> None  # Abstract method

class UserDAO(BaseDAO):
    def register_user(self, username: str, password: str) -> bool
    def authenticate(self, username: str, password: str) -> Optional[int]
    def is_admin(self, username: str) -> bool
```
