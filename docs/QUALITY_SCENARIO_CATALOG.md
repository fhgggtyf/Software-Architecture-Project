# Quality Scenario Catalog

**Project:** Retail Management System - Checkpoint 2  
**Team Members:** Kwabena Sekyi-Djan, Jason Xia  


## 1. AVAILABILITY

### Scenario 1.1: Graceful Degradation During Flash Sale Overload

| Element | Description |
|---------|-------------|
| **Source** | Flash sale event with massive user traffic |
| **Stimulus** | 10,000+ concurrent users attempt to access limited inventory during flash sale |
| **Environment** | Peak load conditions, limited server resources |
| **Artifact** | Retail application system and inventory management |
| **Response** | System maintains core functionality while gracefully degrading non-essential features |
| **Response Measure** | 99% of users can complete purchases, system remains responsive, no complete failures |

**Mapped Tactic/Pattern:** Circuit Breaker Pattern

**Implementation:**
- Circuit breaker in `payment_service.py` (lines 63-78)
- Class-level circuit breaker in `app.py` (lines 44-66)
- Failure threshold: 3 consecutive failures
- Cooldown period: 30 seconds
- Fast-fail when circuit is open

**Code Reference:**
```python
# app.py
if RetailApp._is_circuit_open():
    return False, "Payment service is temporarily unavailable. Please try again later."
```

### Scenario 1.2: Database Connection Failure Recovery

| Element | Description |
|---------|-------------|
| **Source** | Database server |
| **Stimulus** | Database connection pool exhausted or database becomes unresponsive |
| **Environment** | Production system during business hours |
| **Artifact** | Retail application system and data access layer |
| **Response** | System switches to read-only mode and queues write operations |
| **Response Measure** | Service maintains read operations within 5 seconds, write operations queued for later processing |

**Mapped Tactic/Pattern:** Database Connection Pooling with Fallback

**Implementation:**
- Thread-local connection pooling in `dao.py` (lines 65-75)
- Automatic connection creation on first access
- Connection reuse within thread
- Atomic transaction support with rollback

**Code Reference:**
```python
# dao.py
_thread_local = threading.local()

def get_request_connection():
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        _thread_local.conn = _new_connection(_resolve_db_path())
    return _thread_local.conn
```

## 2. SECURITY

### Scenario 2.1: Partner Feed Authentication

| Element | Description |
|---------|-------------|
| **Source** | External partner system |
| **Stimulus** | Partner attempts to send product feed data to retail system |
| **Environment** | Production system with multiple partner integrations |
| **Artifact** | Partner API endpoints and authentication system |
| **Response** | System validates partner credentials and authorizes data access |
| **Response Measure** | 100% of unauthorized access attempts are blocked, valid partners authenticated within 200ms |

**Mapped Tactic/Pattern:** API Key Authentication with JWT

**Implementation:**
- Partner name parameter for tracking in `app.py` (line 203)
- Feed source validation
- Future enhancement: API key validation framework ready

**Code Reference:**
```python
# app.py
def ingest_partner_feed(self, partner_name: str, feed_source: str, ...):
    # Partner authentication placeholder
    # Future: validate API key for partner_name
```

### Scenario 2.2: Protection from Malicious Input

| Element | Description |
|---------|-------------|
| **Source** | Malicious user or automated attack |
| **Stimulus** | Attempts to inject malicious code through product descriptions, user inputs, or API calls |
| **Environment** | Web application with multiple input channels |
| **Artifact** | Input validation system and data processing components |
| **Response** | System sanitizes all inputs and prevents malicious code execution |
| **Response Measure** | 100% of malicious inputs are blocked, no unauthorized code execution, all attempts logged |

**Mapped Tactic/Pattern:** Input Validation and Sanitization

**Implementation:**
- Type validation in `partner_ingestion.py` (lines 40-70)
- HTML escaping in `app_web.py` (line 58)
- ValueError handling for invalid data
- Skips invalid rows instead of crashing

**Code Reference:**
```python
# partner_ingestion.py
try:
    name_str = str(name).strip()
    price_val = float(price)
    stock_val = int(stock)
except Exception:
    raise ValueError(f"Invalid types for name/price/stock in feed record at index {idx}")

# app_web.py
def html_escape(s: str) -> str:
    return html.escape(s, quote=True)
```

## 3. MODIFIABILITY

### Scenario 3.1: Adding New Partner Formats Without Major Code Change

| Element | Description |
|---------|-------------|
| **Source** | Business development team |
| **Stimulus** | New partner requires different data format (XML instead of JSON) for product feeds |
| **Environment** | Production system with existing partner integrations |
| **Artifact** | Partner integration system and data processing components |
| **Response** | New partner format integrated without modifying existing partner code |
| **Response Measure** | New partner format added within 1 day, existing partners unaffected, no system downtime |

**Mapped Tactic/Pattern:** Adapter Pattern

**Implementation:**
- Abstract `PartnerAdapter` base class
- Concrete adapters: `CSVPartnerAdapter`, `JSONPartnerAdapter`
- Factory method: `select_adapter()` based on file extension
- Easy to add new adapters (e.g., `XMLPartnerAdapter`)

**Code Reference:**
```python
# partner_ingestion.py
class PartnerAdapter:
    def parse(self, data: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

class CSVPartnerAdapter(PartnerAdapter):
    def parse(self, data: str) -> List[Dict[str, Any]]:
        # CSV-specific parsing logic
        
class JSONPartnerAdapter(PartnerAdapter):
    def parse(self, data: str) -> List[Dict[str, Any]]:
        # JSON-specific parsing logic

def select_adapter(file_path: str) -> PartnerAdapter:
    ext = Path(file_path).suffix.lower()
    if ext == ".csv":
        return CSVPartnerAdapter()
    if ext in {".json", ".jsn"}:
        return JSONPartnerAdapter()
    raise ValueError(f"Unsupported format: {ext}")
```

### Scenario 3.2: Payment Method Extension

| Element | Description |
|---------|-------------|
| **Source** | Business requirements |
| **Stimulus** | Need to add cryptocurrency payment option alongside existing card/cash methods |
| **Environment** | Production system with existing payment infrastructure |
| **Artifact** | Payment processing system and checkout flow |
| **Response** | New payment method integrated without affecting existing payment flows |
| **Response Measure** | New payment method added within 3 days, existing payment methods continue working, no regression |

**Mapped Tactic/Pattern:** Strategy Pattern with Plugin Architecture

**Implementation:**
- Abstract `PaymentStrategy` interface
- Concrete strategies: `CardPaymentStrategy`, `CashPaymentStrategy`, `CryptoPaymentStrategy`
- Strategy registry with `register_strategy()`
- Runtime strategy selection

**Code Reference:**
```python
# payment_service.py
class PaymentStrategy:
    def process(self, amount: float) -> Tuple[bool, str]:
        raise NotImplementedError

class CardPaymentStrategy(PaymentStrategy):
    def process(self, amount: float) -> Tuple[bool, str]:
        # Card processing logic
        
class CryptoPaymentStrategy(PaymentStrategy):
    def process(self, amount: float) -> Tuple[bool, str]:
        # Crypto processing logic

# In PaymentService.__init__:
def register_strategy(self, method: str, strategy: PaymentStrategy) -> None:
    self.strategies[method.strip().lower()] = strategy

# Easy to add new methods:
payment_service.register_strategy("paypal", PayPalPaymentStrategy())
```

## 4. PERFORMANCE

### Scenario 4.1: Bounded Latency Under 1,000 req/s During Flash Sales

| Element | Description |
|---------|-------------|
| **Source** | Flash sale event |
| **Stimulus** | 1,000 requests per second during limited-time flash sale event |
| **Environment** | High load conditions with limited inventory |
| **Artifact** | Web application and database system |
| **Response** | System maintains response times under specified thresholds |
| **Response Measure** | 95% of requests respond within 200ms, 99% within 500ms, no timeouts |

**Mapped Tactic/Pattern:** Connection Pooling and Database Indexing

**Implementation:**
- Thread-local connection pooling in `dao.py`
- Connection reuse within threads
- Flash sale price pre-calculation
- Efficient datetime comparison for time windows

**Code Reference:**
```python
# dao.py
_thread_local = threading.local()

def get_request_connection():
    if not hasattr(_thread_local, "conn"):
        _thread_local.conn = _new_connection(...)
    return _thread_local.conn

# app.py - Flash sale optimization
if p.flash_sale_price and start <= now <= end:
    unit_price = p.flash_sale_price
```

### Scenario 4.2: Concurrent Checkout Performance

| Element | Description |
|---------|-------------|
| **Source** | Multiple simultaneous users |
| **Stimulus** | 500 concurrent users attempting checkout during peak hours |
| **Environment** | High load conditions, database under stress |
| **Artifact** | Checkout transaction processing system |
| **Response** | All checkout requests are processed successfully with consistent performance |
| **Response Measure** | 99% of transactions complete within 2 seconds, no deadlocks or timeouts |

**Mapped Tactic/Pattern:** Optimistic Locking and Transaction Optimization

**Implementation:**
- Conditional UPDATE in `dao.py` (line 195-210)
- `decrease_stock_if_available()` prevents race conditions
- Atomic operations without explicit locks
- ThreadingHTTPServer for concurrent request handling

**Code Reference:**
```python
# dao.py
def decrease_stock_if_available(self, product_id: int, qty: int) -> bool:
    conn = self._conn()
    with conn:
        cur = conn.execute(
            "UPDATE Product SET stock = stock - ? WHERE id = ? AND stock >= ?;",
            (qty, product_id, qty),
        )
    return cur.rowcount > 0  # True if update succeeded

# app_web.py
httpd = ThreadingHTTPServer(server_address, RetailHTTPRequestHandler)
```

## 5. INTEGRABILITY

### Scenario 5.1: Onboarding New Reseller APIs with Adapters

| Element | Description |
|---------|-------------|
| **Source** | New reseller partner |
| **Stimulus** | New reseller requires integration with different API structure and authentication |
| **Environment** | Production system with existing reseller integrations |
| **Artifact** | Reseller integration system and API management |
| **Response** | New reseller API integrated using adapter pattern without affecting existing integrations |
| **Response Measure** | New reseller integrated within 2 days, existing resellers unaffected, API calls successful |

**Mapped Tactic/Pattern:** Adapter Pattern with API Gateway

**Implementation:**
- Format detection based on file extension
- URL and local file support
- Automatic adapter selection
- Extensible to new formats

**Code Reference:**
```python
# partner_ingestion.py
def select_adapter(file_path: str) -> PartnerAdapter:
    ext = Path(file_path).suffix.lower()
    if ext == ".csv":
        return CSVPartnerAdapter()
    if ext in {".json", ".jsn"}:
        return JSONPartnerAdapter()
    # Easy to add: if ext == ".xml": return XMLPartnerAdapter()
    raise ValueError(f"Unsupported format: {ext}")
```

### Scenario 5.2: Third-Party Service Integration

| Element | Description |
|---------|-------------|
| **Source** | Business requirements |
| **Stimulus** | Need to integrate with external inventory management service and shipping provider |
| **Environment** | Production system with existing external integrations |
| **Artifact** | External service integration layer |
| **Response** | New services integrated without disrupting existing functionality |
| **Response Measure** | New services integrated within 1 week, existing integrations continue working, data synchronization successful |

**Mapped Tactic/Pattern:** Service-Oriented Architecture (SOA)

**Implementation:**
- `PaymentService` abstracts payment gateway details
- Strategy pattern allows multiple gateways
- `refund_payment()` API for compensation
- Easy to add new external services

**Code Reference:**
```python
# payment_service.py
class PaymentService:
    def process_payment(self, amount: float, method: str) -> Tuple[bool, str]:
        # Abstracts gateway interaction
        
    def refund_payment(self, reference: str, amount: float) -> Tuple[bool, str]:
        # Compensating transaction support
```

## 6. TESTABILITY

### Scenario 6.1: Automated Replay of Flash-Sale Workloads

| Element | Description |
|---------|-------------|
| **Source** | QA and performance testing team |
| **Stimulus** | Need to reproduce and test flash sale scenarios for performance validation |
| **Environment** | Test environment with production-like data |
| **Artifact** | Performance testing framework and load generation system |
| **Response** | Automated tests can replay exact flash sale conditions and validate system behavior |
| **Response Measure** | Tests can reproduce 100% of flash sale scenarios, performance metrics validated, regression testing automated |

**Mapped Tactic/Pattern:** Test Data Management and Load Testing

**Implementation:**
- `fresh_db()` creates isolated test databases
- Repeatable test scenarios
- Configurable mock payment service
- Test-specific environment variables

**Code Reference:**
```python
# test_retail_app.py
def fresh_db():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    os.environ["RETAIL_DB_PATH"] = tmp.name
    
    # Reset thread-local connection
    if hasattr(dao._thread_local, "conn"):
        dao._thread_local.conn.close()
        dao._thread_local.conn = None
    
    importlib.reload(dao)
    return tmp.name
```

### Scenario 6.2: Integration Testing with External Services

| Element | Description |
|---------|-------------|
| **Source** | Development and QA teams |
| **Stimulus** | Need to test integrations with partner APIs and external services |
| **Environment** | Test environment with mock external services |
| **Artifact** | Integration testing framework and external service mocks |
| **Response** | Automated tests validate all external integrations without depending on live services |
| **Response Measure** | 100% of external integrations tested, mock services provide realistic responses, integration failures detected |

**Mapped Tactic/Pattern:** Mock Services and Contract Testing

**Implementation:**
- Mock payment strategies with configurable success rates
- `breaker_state()` API for circuit breaker inspection
- Observable internal state for testing
- No external dependencies required

**Code Reference:**
```python
# payment_service.py
class CardPaymentStrategy(PaymentStrategy):
    def __init__(self, success_rate: float = 0.5) -> None:
        self.success_rate = success_rate  # Configurable for testing

def breaker_state(self) -> Dict[str, object]:
    return {
        "is_open": self._is_circuit_open(),
        "failure_count": self._failure_count,
        "open_until": self._circuit_open_until.isoformat() if self._circuit_open_until else None
    }
```

## 7. USABILITY

### Scenario 7.1: Clear Error Feedback for Failed Orders

| Element | Description |
|---------|-------------|
| **Source** | Customer during checkout |
| **Stimulus** | Order fails due to payment processing error or inventory shortage |
| **Environment** | Production system during normal operation |
| **Artifact** | User interface and error handling system |
| **Response** | System provides clear, actionable error messages and recovery options |
| **Response Measure** | 95% of users understand error messages, 90% can resolve issues without support, error recovery rate > 80% |

**Mapped Tactic/Pattern:** Progressive Error Handling with User Guidance

**Implementation:**
- Specific error messages for each failure type
- Links back to relevant pages
- Contextual help for recovery
- Clear explanation of circuit breaker state

**Code Reference:**
```python
# app_web.py
if not ok:
    self._send_html(
        self._wrap_page(
            "Payment Failed",
            f"<p>Payment failed: {html_escape(res)}</p>"
            f"<p><a href='/cart'>Back to cart</a> to try again</p>"
        )
    )

# Circuit breaker message
if RetailApp._is_circuit_open():
    return False, "Payment service is temporarily unavailable. Please try again later."
```

### Scenario 7.2: Intuitive Flash Sale Interface

| Element | Description |
|---------|-------------|
| **Source** | Customer during flash sale |
| **Stimulus** | User attempts to purchase limited-time offer during high-traffic flash sale |
| **Environment** | High load conditions with time pressure |
| **Artifact** | Flash sale user interface and purchase flow |
| **Response** | Interface provides clear status updates, countdown timers, and purchase confirmation |
| **Response Measure** | 90% of users complete flash sale purchases successfully, average purchase time < 30 seconds, user satisfaction > 85% |

**Mapped Tactic/Pattern:** Real-time UI Updates with Status Communication

**Implementation:**
- Strikethrough on original price
- Bold flash sale price in red
- Time window display
- Stock limits on quantity input
- Visual indicators for active sales

**Code Reference:**
```python
# app_web.py
if on_sale:
    price_html = (
        f"<span style='text-decoration:line-through;color:#777'>{p.price:.2f}</span> "
        f"<span style='color:#d00;font-weight:bold'>{p.flash_sale_price:.2f}</span>"
        f"<br><small>Sale: {p.flash_sale_start} → {p.flash_sale_end}</small>"
    )

# Limit quantity to available stock
f"<input type='number' name='quantity' min='1' max='{p.stock}' value='1' />"
```

## Tactic Mapping Summary

| Quality Attribute | Scenario # | Tactic/Pattern | Implementation File | Lines |
|------------------|------------|----------------|-------------------|-------|
| Availability | 1.1 | Circuit Breaker Pattern | payment_service.py, app.py | 63-78, 44-66 |
| Availability | 1.2 | Connection Pooling | dao.py | 65-75 |
| Security | 2.1 | API Key Authentication | app.py | 203 |
| Security | 2.2 | Input Validation | partner_ingestion.py, app_web.py | 40-70, 58 |
| Modifiability | 3.1 | Adapter Pattern | partner_ingestion.py | 20-100 |
| Modifiability | 3.2 | Strategy Pattern | payment_service.py | 15-45 |
| Performance | 4.1 | Connection Pooling | dao.py | 65-75 |
| Performance | 4.2 | Optimistic Locking | dao.py | 195-210 |
| Integrability | 5.1 | Adapter Pattern | partner_ingestion.py | 20-100 |
| Integrability | 5.2 | Service Abstraction | payment_service.py | 50-130 |
| Testability | 6.1 | Test Data Management | test_retail_app.py | 30-50 |
| Testability | 6.2 | Mock Services | payment_service.py | 15-45 |
| Usability | 7.1 | Progressive Error Handling | app_web.py | 400-450 |
| Usability | 7.2 | Real-time UI Updates | app_web.py | 250-280 |

## Additional Tactics Implemented

Beyond the 14 required scenarios, we implemented additional tactics:

### 15. Compensating Transaction (Availability)
- **Location:** `app.py` checkout method
- **Purpose:** Refund payment if database operations fail after payment approval
- **Benefit:** Ensures data consistency across payment gateway and database

### 16. Schema Versioning (Modifiability)
- **Location:** `dao.py` `_apply_schema_if_needed()`
- **Purpose:** Track and manage database schema changes
- **Benefit:** Safe schema migrations without manual intervention

### 17. Session Management (Security + Performance)
- **Location:** `app_web.py`
- **Purpose:** Cookie-based multi-user session support
- **Benefit:** Concurrent users with isolated state

## Traceability Matrix

| Scenario | Tactic | Code Location | Test Coverage | ADR |
|----------|--------|---------------|---------------|-----|
| Availability 1.1 | Circuit Breaker | payment_service.py:63-78 | test_retail_app.py | ADR-001 |
| Availability 1.2 | Connection Pool | dao.py:65-75 | test_retail_app.py | ADR-012 |
| Security 2.1 | API Auth | app.py:203 | Manual | ADR-008 |
| Security 2.2 | Input Validation | partner_ingestion.py:40-70 | test_retail_app.py | ADR-008 |
| Modifiability 3.1 | Adapter | partner_ingestion.py:20-100 | test_retail_app.py | ADR-004 |
| Modifiability 3.2 | Strategy | payment_service.py:15-45 | test_retail_app.py | ADR-003 |
| Performance 4.1 | Connection Pool | dao.py:65-75 | test_retail_app.py | ADR-012 |
| Performance 4.2 | Optimistic Lock | dao.py:195-210 | test_retail_app.py | ADR-005 |
| Integrability 5.1 | Adapter | partner_ingestion.py | test_retail_app.py | ADR-004 |
| Integrability 5.2 | Service Abstract | payment_service.py | test_retail_app.py | ADR-003 |
| Testability 6.1 | Test Data Mgmt | test_retail_app.py:30-50 | Self-testing | N/A |
| Testability 6.2 | Mock Services | payment_service.py | test_retail_app.py | N/A |
| Usability 7.1 | Error Handling | app_web.py:400-450 | Manual | ADR-011 |
| Usability 7.2 | Real-time UI | app_web.py:250-280 | Manual | ADR-010 |
