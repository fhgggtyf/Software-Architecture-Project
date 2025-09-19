# ADR-006: Implement Mock Payment Service for Demonstration

## Status
Accepted

## Context
The retail application needs to process payments during checkout, but integrating with real payment gateways would add complexity, external dependencies, and security concerns. We need a solution that demonstrates the payment flow without requiring actual financial transactions.

## Decision
Implement a `PaymentService` class that simulates payment processing:
- Always approve card payments with generated transaction references
- Always reject cash payments (assignment requirement)
- Generate unique transaction IDs using timestamps
- Return structured responses `(approved: bool, reference: str)`
- Decoupled from business logic for easy replacement

## Consequences

### Positive
- **No external dependencies** - No need for payment gateway APIs or credentials
- **Predictable behavior** - Consistent responses for testing and demonstration
- **Security** - No risk of processing real payments during development
- **Cost** - No transaction fees or gateway setup costs
- **Simplicity** - Easy to understand and modify payment logic
- **Testability** - Easy to test both success and failure scenarios

### Negative
- **Not production-ready** - Cannot be used for real transactions
- **Limited realism** - Doesn't demonstrate real payment gateway integration
- **No fraud detection** - Missing real-world payment validation
- **No refund handling** - Cannot process refunds or chargebacks
- **Limited payment methods** - Only supports card and cash simulation

### Neutral
- **Educational value** - Demonstrates payment service integration patterns
- **Maintainability** - Simple code that's easy to modify

## Implementation Details
```python
class PaymentService:
    def __init__(self, always_approve: bool = True)
    def process_payment(self, amount: float, method: str) -> Tuple[bool, str]
    
    # Payment logic:
    # - Card payments: Always succeed
    # - Cash payments: Always fail
    # - Other methods: Based on always_approve flag
```

## Alternative Considered
Real payment gateway integration was considered but rejected due to:
- Security concerns for a demo application
- Additional external dependencies
- Need for merchant accounts and credentials
- Complexity that would distract from architectural learning objectives
