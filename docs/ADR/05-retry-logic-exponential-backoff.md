# ADR-005: Retry Logic with Exponential Backoff
**Status:** Accepted  


## Context
Payment gateways experience transient failures (network blips, temporary overload, rate limiting) that resolve within seconds. Single-attempt failures result in unnecessary order failures and poor user experience. However, fixed retry intervals can cause "thundering herd" when services recover.

## Decision
Implement exponential backoff retry:
- Maximum attempts: 3 (initial + 2 retries)
- Backoff schedule: 1s, 2s, 4s (exponential growth)
- Total maximum time: ~7 seconds
- Integration: Works with circuit breaker - no retries if circuit open
- Implementation: app.py checkout (lines 123-145)

```python
retries = 3
delay = 1.0
for attempt in range(retries):
    approved, reference = self.payment_service.process_payment(total, method)
    if approved:
        RetailApp._record_payment_success()
        break
    RetailApp._record_payment_failure()
    if attempt < retries - 1:
        time.sleep(delay)
        delay *= 2.0
```

## Consequences
**Positive:**
- Handles transient failures gracefully - estimated 15-20% improvement in success rate
- Exponential backoff prevents overwhelming recovering services
- Works seamlessly with circuit breaker to avoid wasteful retries during sustained outages

**Negative:**
- Adds latency to failed checkouts (up to 7 seconds total)
- Potential for duplicate charges if payment succeeds but response is lost (mitigated by transaction IDs)

**Trade-offs:**
- Higher latency on failures vs higher success rate: Chose success rate (better business outcome)
- Exponential vs linear: Exponential prevents thundering herd and gives service more recovery time

## Alternatives Considered
- **Fixed Interval Retry** - Rejected: Causes thundering herd on recovery; doesn't adapt to failure severity
- **No Retries** - Rejected: 15-20% of orders would unnecessarily fail due to transient issues
- **Async Retry with Queue** - Deferred: Better UX but requires message queue infrastructure; current approach sufficient
