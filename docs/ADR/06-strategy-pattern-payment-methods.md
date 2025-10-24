# ADR-006: Strategy Pattern for Payment Methods
**Status:** Accepted  


## Context
System must support multiple payment methods (Card, Cash, Crypto) with different processing logic. Future requirements include BNPL, digital wallets (Apple Pay, Google Pay), and regional payment methods. Hard-coded if-else chains violate Open/Closed Principle and become unmaintainable.

## Decision
Implement Strategy Pattern with plugin architecture:
- Abstract interface: PaymentStrategy with process(amount) -> (bool, str)
- Concrete strategies: CardPaymentStrategy, CashPaymentStrategy, CryptoPaymentStrategy
- Registry: register_strategy(method, strategy) for runtime addition
- Selection: Case-insensitive method name mapping
- Implementation: payment_service.py (lines 15-130)

```python
class PaymentStrategy:
    def process(self, amount: float) -> Tuple[bool, str]:
        raise NotImplementedError

class CardPaymentStrategy(PaymentStrategy):
    def process(self, amount: float):
        # Card-specific logic
        return (approved, reference)

# In PaymentService:
def register_strategy(self, method: str, strategy: PaymentStrategy):
    self.strategies[method.strip().lower()] = strategy

# Usage:
self.register_strategy("card", CardPaymentStrategy())
```

## Consequences
**Positive:**
- New payment methods added without modifying existing code (Open/Closed Principle)
- Each strategy independently testable in isolation
- Runtime registration enables plugin architecture and A/B testing
- Clear separation of concerns - one class per payment method

**Negative:**
- More classes to maintain (one per payment method)
- Slight indirection overhead (<1μs, negligible vs 100ms+ network I/O)

**Trade-offs:**
- More classes vs maintainability: Chose maintainability - easier to add new methods (1 day vs 1 week)
- Performance vs flexibility: Negligible performance cost for significant flexibility gain

## Alternatives Considered
- **If-Else Chain** - Rejected: Violates Open/Closed Principle; becomes unmaintainable with 10+ payment methods
- **Command Pattern** - Rejected: More complex than needed; Strategy simpler for algorithm encapsulation
- **Factory Pattern Only** - Rejected: Doesn't encapsulate payment algorithms, just creation
