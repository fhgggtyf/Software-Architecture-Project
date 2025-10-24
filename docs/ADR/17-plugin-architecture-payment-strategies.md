# ADR-017: Plugin Architecture for Payment Strategies
**Status:** Accepted  


## Context
Payment methods need runtime addition/removal/configuration without code changes. Business requirements: enable/disable methods by region, A/B test providers, add methods without redeployment. Hard-coded methods prevent operational flexibility.

## Decision
Implement plugin-style strategy registration:
- register_strategy(method, strategy) API for runtime addition
- Strategy registry dictionary with case-insensitive lookup
- No code changes required to add new methods
- Implementation: payment_service.py (lines 55-58)

```python
def register_strategy(self, method: str, strategy: PaymentStrategy) -> None:
    self.strategies[method.strip().lower()] = strategy

# In __init__:
self.register_strategy("card", CardPaymentStrategy())
self.register_strategy("crypto", CryptoPaymentStrategy())

# Runtime addition:
payment_service.register_strategy("paypal", PayPalPaymentStrategy())
```

## Consequences
**Positive:**
- New methods added at runtime without code modification
- Can enable/disable methods via configuration
- A/B testing different providers
- Regional payment method support

**Negative:**
- String keys have no compile-time type safety
- Need validation at registration time

**Trade-offs:**
- Runtime flexibility vs type safety: Chose flexibility - operational benefits outweigh development-time checks
- Registry vs hard-coded: Chose registry - enables configuration-driven behavior

## Alternatives Considered
- **Hardcoded Strategies Only** - Rejected: Cannot add methods without redeployment
- **Dynamic Class Loading** - Rejected: Security concerns; complex; overkill for use case
