# ADR-004: Use In-Memory Shopping Cart for Simplified State Management

## Status
Accepted

## Context
The application needs to manage shopping cart state across multiple HTTP requests. We need to decide between persisting cart data in the database versus keeping it in memory. The application is designed as a single-user demo system.

## Decision
Implement shopping cart as in-memory data structure within the `RetailApp` class:
- Cart stored as `Dict[int, CartLine]` keyed by product_id
- Cart state tied to the global `RetailApp` instance
- Cart cleared on logout and after successful checkout
- No persistence of cart data across application restarts

## Consequences

### Positive
- **Simplicity** - No complex state management or session handling
- **Performance** - Fast cart operations without database queries
- **Memory efficiency** - Cart data is automatically garbage collected
- **Implementation speed** - Quick to implement and test
- **Demo-friendly** - Clear separation between temporary cart and persistent data

### Negative
- **Data loss** - Cart is lost if application crashes or restarts
- **Single-user limitation** - Only one user can have a cart at a time
- **No cart persistence** - Users cannot save carts for later
- **Memory usage** - Cart data consumes application memory
- **No cart history** - Cannot track abandoned carts

### Neutral
- **Scalability** - Not suitable for production multi-user systems
- **Testing** - Easy to test but requires careful state management

## Implementation Details
```python
class RetailApp:
    def __init__(self):
        self._cart: Dict[int, CartLine] = {}
        self._current_user_id: int | None = None
    
    def add_to_cart(self, product_id: int, qty: int) -> Tuple[bool, str]
    def remove_from_cart(self, product_id: int) -> None
    def clear_cart(self) -> None
    def view_cart(self) -> List[CartLine]
```

## Alternative Considered
Database-persisted cart was considered but rejected due to:
- Increased complexity for a demo application
- Need for session management
- Additional database queries for every cart operation
- Overkill for single-user scenario
