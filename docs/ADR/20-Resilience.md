# ADR-003: Resilience Patterns (Circuit Breaker, Retry, Fallback)

**Status:** Accepted  
**Date:** 2025-11-14  
**Decision Makers:** Development Team  
**Technical Story:** Graceful degradation and fault tolerance for payment processing

## Context and Problem Statement

The retail system depends on external services (payment gateway, inventory systems, shipping) that may experience:
- Transient failures (network blips, temporary overload)
- Sustained outages (service down, database unavailable)
- Slow responses (degraded performance)

Without resilience patterns, the system would:
- Fail immediately on transient errors
- Cascade failures to dependent services
- Provide poor user experience during outages
- Risk data inconsistency from partial failures

## Decision Drivers

* **Availability**: Maintain functionality during partial outages
* **User Experience**: Avoid immediate failures on transient errors
* **Data Consistency**: Prevent partial updates (atomicity)
* **Service Protection**: Avoid overwhelming failing services
* **Observability**: Expose circuit breaker state for monitoring
* **Testability**: Patterns should be testable and configurable

## Considered Options

### Option 1: Fail Fast (No Resilience)
**Pros:**
- Simple implementation
- Clear error propagation
- No complexity

**Cons:**
- Poor user experience
- Cascading failures
- No protection for downstream services
- Transient errors cause permanent failures

### Option 2: Infinite Retries
**Pros:**
- Eventually succeeds on transient failures

**Cons:**
- Long delays on sustained failures
- Can overwhelm failing services
- Poor user experience (indefinite waits)
- Resource exhaustion

### Option 3: Resilience Patterns (Circuit Breaker + Retry + Fallback)  **SELECTED**
**Pros:**
- Graceful degradation
- Protection for downstream services
- Better user experience
- Configurable behavior
- Industry best practice

**Cons:**
- Implementation complexity
- Requires careful tuning
- State management overhead

## Decision Outcome

**Chosen option:** Implement comprehensive resilience patterns (Option 3)

We will implement three complementary resilience tactics:

### 1. Circuit Breaker Pattern

#### Purpose:
Prevent cascading failures by "opening" when a service is failing, allowing it time to recover.

#### Implementation (Two-Level):

**A. Instance-Level Circuit Breaker (`payment_service.py`)**
```python
class PaymentService:
    def __init__(self, failure_threshold=3, cooldown_seconds=30):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._circuit_open_until = None
    
    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until is None:
            return False
        now = datetime.now(UTC)
        if now >= self._circuit_open_until:
            # Cooldown elapsed -> close breaker
            self._circuit_open_until = None
            self._failure_count = 0
            return False
        return True
    
    def process_payment(self, amount, method):
        if self._is_circuit_open():
            return False, "Payment service unavailable (circuit breaker open)"
        # ... attempt payment with retry ...
```

**B. Class-Level Circuit Breaker (`app.py`)**
```python
class RetailApp:
    _payment_failures = 0
    _payment_last_failure_time = None
    _payment_failure_threshold = 3
    _payment_cooldown = 30
    
    @classmethod
    def _is_circuit_open(cls) -> bool:
        if cls._payment_failures >= cls._payment_failure_threshold:
            if cls._payment_last_failure_time is not None:
                elapsed = time.time() - cls._payment_last_failure_time
                if elapsed < cls._payment_cooldown:
                    return True
                else:
                    cls._payment_failures = 0
                    cls._payment_last_failure_time = None
        return False
```

#### States:
1. **CLOSED**: Normal operation, requests pass through
2. **OPEN**: Failure threshold exceeded, requests fail fast
3. **HALF-OPEN**: After cooldown, test if service recovered

#### Configuration:
- **Failure Threshold**: 3 consecutive failures
- **Cooldown Period**: 30 seconds
- **Success Reset**: Reset counter on successful payment

### 2. Retry with Exponential Backoff + Jitter

#### Purpose:
Automatically retry transient failures with increasing delays to avoid thundering herd.

#### Implementation:
```python
def process_payment(self, amount: float, method: str) -> Tuple[bool, str]:
    last_error = "Unknown error"
    
    for attempt in range(self.max_attempts):  # max_attempts = 3
        if strategy:
            approved, ref_or_reason = strategy.process(amount)
        else:
            # ... fallback logic ...
        
        if approved:
            self._failure_count = 0
            return True, ref_or_reason
        
        # Failure - record and retry
        last_error = ref_or_reason
        self._failure_count += 1
        
        # Trip breaker if threshold reached
        if self._failure_count >= self.failure_threshold:
            self._trip_breaker()
            return False, last_error
        
        # Exponential backoff with jitter (if retries remain)
        if attempt < self.max_attempts - 1:
            self._backoff_sleep(attempt)
    
    return False, last_error

def _backoff_sleep(self, attempt_index: int) -> None:
    # Delay: 0.25s, 0.5s, 1.0s, ... (capped at backoff_max=2.0s)
    delay = min(self.backoff_base * (2 ** attempt_index), self.backoff_max)
    # Add random jitter (+/- backoff_jitter=0.10s)
    jitter = (random.random() * 2 - 1) * self.backoff_jitter
    time.sleep(max(0.0, delay + jitter))
```

#### Configuration:
- **Max Attempts**: 3 retries
- **Base Delay**: 0.25 seconds
- **Max Delay**: 2.0 seconds (cap)
- **Jitter**: ±0.10 seconds

#### Example Retry Schedule:
| Attempt | Base Delay | With Jitter (±0.1s) |
|---------|------------|---------------------|
| 1 | 0.25s | 0.15s - 0.35s |
| 2 | 0.50s | 0.40s - 0.60s |
| 3 | 1.00s | 0.90s - 1.10s |

### 3. Compensating Transactions (Refund on Failure)

#### Purpose:
Maintain data consistency by rolling back partial transactions.

#### Scenario:
1. Payment approved 
2. Database commit fails 
3. **Compensating action**: Refund payment

#### Implementation:
```python
def checkout(self, payment_method: str) -> Tuple[bool, str]:
    approved, ref_or_reason = self.payment_service.process_payment(total, payment_method)
    if not approved:
        return False, "Payment failed"
    
    try:
        # Record sale and payment in database (atomic)
        sale_id = self.sale_dao.create_sale(...)
        self.payment_dao.record_payment(sale_id, ...)
        
        # External integrations
        self.inventory_service.update_inventory(sale_id, items)
        self.shipping_service.create_shipment(sale_id, ...)
        
    except Exception as e:
        # Database or external service failed AFTER payment
        # COMPENSATING TRANSACTION: Refund the payment
        try:
            refund_ok, refund_ref = self.payment_service.refund_payment(ref_or_reason, total)
            logger.error(f"Order failed, refund issued: {refund_ref}")
        except Exception:
            logger.critical(f"REFUND FAILED after payment approval: {ref_or_reason}")
        return False, "Order processing failed, payment refunded"
    
    return True, receipt
```

### 4. Database Resilience (Read-Only Fallback)

#### Purpose:
Continue serving read requests when database write fails.

#### Implementation (`dao.py`):
```python
_read_only_mode = False
_write_queue = []

def execute_write(query, params=()):
    global _read_only_mode
    try:
        if _read_only_mode:
            _write_queue.append((query, params))
            logger.warning("DB read-only; queued write.")
            return False
        
        conn = get_request_connection()
        with conn:
            conn.execute(query, params)
        return True
    except sqlite3.OperationalError as e:
        logger.error(f"Write failed: {e}")
        _read_only_mode = True
        _write_queue.append((query, params))
        return False

def _recovery_worker():
    """Background thread attempts reconnection every 10s"""
    while True:
        time.sleep(_RETRY_INTERVAL)
        if not _read_only_mode:
            continue
        try:
            conn = _new_connection(read_only=False)
            with conn:
                while _write_queue:
                    q, p = _write_queue.pop(0)
                    conn.execute(q, p)
            conn.close()
            _read_only_mode = False
            logger.info("DB recovered; queued writes flushed.")
        except sqlite3.OperationalError:
            logger.warning("Still cannot reconnect to DB.")
```

#### Features:
- **Automatic Fallback**: Switch to read-only on write failure
- **Write Queue**: Buffer writes during outage
- **Background Recovery**: Attempt reconnection every 10s
- **Automatic Replay**: Flush queued writes on recovery

### Consequences

**Positive:**
- System remains partially functional during outages
- Transient failures automatically retried
- Circuit breaker prevents cascading failures
- Exponential backoff avoids overwhelming services
- Jitter prevents thundering herd
- Compensating transactions maintain consistency
- Database fallback enables read operations during write outage
- Observability via circuit breaker gauge metric

**Negative:**
- Increased complexity in error handling
- Requires careful tuning of thresholds and timeouts
- Potential for "stuck open" circuits if misconfigured
- Write queue grows unbounded during long DB outage
- Compensating transactions may fail (critical error path)

**Neutral:**
- Some user requests will fail fast during circuit open (desired behavior)
- Retry delays add latency (acceptable tradeoff for reliability)
- Two-level circuit breaker (class + instance) provides defense in depth

## Validation

Resilience patterns will be validated by:

### 1. Circuit Breaker Tests
```python
def test_circuit_breaker_opens_after_threshold():
    # Fail 3 times -> circuit opens
    for _ in range(3):
        success, msg = app.checkout("card")
        assert not success
    
    # 4th attempt fails fast without calling payment service
    with mock.patch.object(payment_service, 'process_payment') as mock_payment:
        success, msg = app.checkout("card")
        assert not success
        assert "circuit breaker" in msg.lower()
        mock_payment.assert_not_called()

def test_circuit_breaker_closes_after_cooldown():
    # Open circuit
    for _ in range(3):
        app.checkout("card")
    
    # Wait for cooldown
    time.sleep(31)
    
    # Circuit should be closed now
    success, msg = app.checkout("card")
    # (outcome depends on payment service state)
```

### 2. Retry Tests
```python
def test_retry_with_eventual_success():
    # Mock: fail twice, succeed on 3rd attempt
    payment_service.strategy.success_sequence = [False, False, True]
    
    start = time.time()
    success, msg = app.checkout("card")
    duration = time.time() - start
    
    assert success
    # Verify exponential backoff occurred (~0.75s total)
    assert 0.6 < duration < 1.0
```

### 3. Compensating Transaction Tests
```python
def test_refund_on_database_failure():
    # Mock: payment succeeds, database fails
    with mock.patch.object(sale_dao, 'create_sale', side_effect=Exception("DB Error")):
        success, msg = app.checkout("card")
        
        assert not success
        assert "refund" in msg.lower()
        # Verify refund was called
        assert payment_service.refund_called
```

### 4. Database Fallback Tests
```python
def test_read_only_fallback():
    # Simulate DB write failure
    with mock.patch('dao.execute_write', side_effect=sqlite3.OperationalError):
        # Write operations queue
        success = dao.execute_write("INSERT ...", ())
        assert not success
        assert len(dao._write_queue) == 1
        
        # Reads still work
        products = dao.execute_read("SELECT * FROM Product")
        assert products is not None
```

## Monitoring and Alerting

**Key Metrics:**
- `circuit_breaker_open{} = 1` → Alert: Payment service degraded
- `checkout_error_total{type="payment_declined"}` → Spike may indicate fraud
- `checkout_duration_seconds{payment_method="card"} > 5s` → Latency SLO violation

**Dashboards:**
- Circuit breaker state over time
- Retry attempt distribution
- Compensating transaction count
- Database fallback events

## Related Decisions

- **ADR-002**: Observability - Circuit breaker state exposed via metrics
- **ADR-004**: Returns Design - Refund API reused for RMA processing
- **ADR-001**: Docker - Container restart policy handles application crashes

## Tuning Guidance

| Parameter | Current Value | Tuning Guidance |
|-----------|---------------|-----------------|
| Failure Threshold | 3 | Lower for stricter failure detection; higher for tolerance |
| Cooldown Period | 30s | Match expected recovery time of downstream services |
| Max Retry Attempts | 3 | Balance latency vs. success rate |
| Backoff Base | 0.25s | Start low for fast transient recovery |
| Backoff Max | 2.0s | Cap to limit user wait time |
| Jitter | ±0.10s | ~10% of base delay prevents synchronization |

## Notes

- Circuit breaker pattern based on Michael Nygard's "Release It!" book
- Exponential backoff follows AWS SDK best practices
- Jitter formula: `delay + (random() * 2 - 1) * jitter_range`
- Consider implementing half-open state for more sophisticated circuit breaker
- Future enhancement: Adaptive retry based on error type (don't retry 4xx errors)
