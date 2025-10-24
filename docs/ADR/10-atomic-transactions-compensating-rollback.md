# ADR-010: Atomic Transactions with Compensating Rollback
**Status:** Accepted  


## Context
Checkout involves multiple steps across two systems: payment gateway (external) and database (internal). Partial failures create inconsistency: user charged but order not recorded, or order recorded but payment failed. Cannot use 2-phase commit as payment gateway doesn't support it.

## Decision
Implement Atomic Transactions with Compensating Transaction pattern:
- Process payment first (external system)
- Database transaction (all-or-nothing for sale/inventory/payment records)
- Compensating action if database fails: Refund the payment
- Implementation: app.py checkout (lines 155-195)

```python
# 1. Process payment
approved, reference = payment_service.process_payment(total, method)
if not approved:
    return False, reference

# 2. Atomic database transaction
try:
    with conn:  # Automatic rollback on exception
        sale_id = sale_dao.create_sale(...)
        for item in cart:
            success = product_dao.decrease_stock_if_available(item.id, item.qty)
            if not success:
                raise RuntimeError("Insufficient stock at commit")
        payment_dao.record_payment(sale_id, method, reference, total, "Approved")
except Exception as ex:
    # 3. Compensating transaction
    payment_service.refund_payment(reference, total)
    return False, f"Order failed after payment - refund initiated: {ex}"
```

## Consequences
**Positive:**
- Ensures eventual consistency across payment gateway and database
- Users never charged without order record (or refunded if database fails)
- Automatic compensation - no manual intervention needed

**Negative:**
- Small time window (~100ms) where payment succeeded but not yet recorded
- Refund is asynchronous - takes time to process (acceptable: user sees confirmation)

**Trade-offs:**
- Payment-first vs database-first: Chose payment-first because payments cannot be rolled back, but database can
- Synchronous vs async compensation: Chose synchronous refund call for immediate confirmation

## Alternatives Considered
- **Database First, Then Payment** - Rejected: Cannot rollback payment if it succeeds; would leave charged customers with no order
- **Saga Pattern** - Deferred: More robust for distributed systems but overkill for 2-tier architecture
- **Two-Phase Commit (2PC)** - Rejected: Payment gateway doesn't support prepare/commit protocol
