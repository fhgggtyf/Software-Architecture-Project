# ADR-007: Use Atomic Database Transactions for Checkout Operations

## Status
Accepted

## Context
The checkout process involves multiple database operations that must succeed or fail together to maintain data consistency:
- Create sale record
- Create sale item records
- Update product stock levels
- Record payment information

If any operation fails, all changes must be rolled back to prevent inconsistent data.

## Decision
Implement atomic transactions using SQLite's transaction support:
- Wrap all checkout operations in a single `with conn:` block
- Use explicit connection for checkout to ensure transaction scope
- Validate stock levels twice (before payment and at commit time)
- Rollback entire transaction if any operation fails
- Generate receipt only after successful transaction commit

## Consequences

### Positive
- **Data consistency** - All-or-nothing guarantee for checkout operations
- **Race condition protection** - Prevents overselling when multiple users checkout simultaneously
- **Error recovery** - Automatic rollback on any failure
- **ACID compliance** - Leverages SQLite's transaction capabilities
- **Audit trail** - Complete transaction history maintained

### Negative
- **Performance impact** - Longer lock duration during checkout
- **Complexity** - More complex error handling and validation logic
- **Single-threaded bottleneck** - SQLite's single-writer limitation
- **Debugging difficulty** - Transaction failures can be harder to debug

### Neutral
- **Memory usage** - Transaction log uses additional memory
- **Concurrency** - Limits concurrent checkouts but ensures data integrity

## Implementation Details
```python
def checkout(self, payment_method: str) -> Tuple[bool, str]:
    # ... validation logic ...
    
    conn = get_request_connection()
    with conn:  # Atomic transaction
        # Double-check stock at commit time
        for line in self._cart.values():
            p = product_dao.get_product(line.product_id)
            if not p or p.stock < line.qty:
                raise RuntimeError("Insufficient stock at commit time.")
        
        # Create sale and items
        sale_id = sale_dao.create_sale(...)
        
        # Update stock
        for line in self._cart.values():
            product_dao.update_stock(...)
        
        # Record payment
        payment_dao.record_payment(...)
```

## Alternative Considered
Non-atomic operations were considered but rejected due to:
- Risk of data inconsistency
- Potential for overselling products
- Difficulty in handling partial failures
- Violation of ACID principles
