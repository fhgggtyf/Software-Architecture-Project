# ADR-004: Circuit Breaker Pattern for Payment Service
**Status:** Accepted  


## Context
During flash sales, the external payment gateway may experience failures or become unavailable. Without protection, failed payment attempts cascade through the system, exhausting resources (threads, connections) and causing complete service outages. During a 2-minute payment gateway outage with 500 concurrent users, our system would have 500 threads blocked waiting for timeouts, leading to complete unresponsiveness.

## Decision
Implement Circuit Breaker pattern with:
- Failure threshold: 3 consecutive failures trigger circuit open
- Cooldown period: 30 seconds before attempting recovery
- Scope: Class-level state in RetailApp shared across all sessions
- Behavior: Fast-fail with immediate error when circuit is open
- Implementation: payment_service.py (lines 63-78), app.py (lines 44-66)

```python
@classmethod
def _is_circuit_open(cls) -> bool:
    if cls._payment_failures >= cls._payment_failure_threshold:
        if cls._payment_last_failure_time is not None:
            elapsed = time.time() - cls._payment_last_failure_time
            if elapsed < cls._payment_cooldown:
                return True
            cls._payment_failures = 0  # Reset after cooldown
    return False

# In checkout():
if RetailApp._is_circuit_open():
    return False, "Payment service temporarily unavailable"
```

## Consequences
**Positive:**
- Prevents cascade failures - other operations remain available
- Fast user feedback (<10ms vs 30s timeout)
- Automatic recovery after cooldown
- Resource protection - threads not wasted on doomed requests
- Observable state via breaker_state() API

**Negative:**
- May reject valid requests during cooldown (~50 requests vs 500+ failures)
- Requires tuning (3 failures = 6-9s before opening; 30s cooldown balances recovery time vs availability)

**Trade-offs:**
- Chose availability over consistency: Better to reject some requests than crash entire system
- Tuning parameters based on historical payment gateway recovery times (15-45 seconds)

## Alternatives Considered
- **Timeout Only** - Rejected: Still wastes resources on every failure; doesn't prevent cascade
- **Rate Limiting** - Rejected: Wrong tool - manages load, not failures; doesn't help during complete outages
- **Bulkhead Pattern** - Deferred: Provides isolation, but circuit breaker more critical for failure handling
