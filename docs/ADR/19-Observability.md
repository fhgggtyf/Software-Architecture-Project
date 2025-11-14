# ADR-002: Observability with Structured Logging and Metrics

**Status:** Accepted  
**Date:** 2025-11-14  
**Decision Makers:** Development Team  
**Technical Story:** Enable monitoring, debugging, and SLO tracking

## Context and Problem Statement

The retail management system requires comprehensive observability to:
- Monitor system health and performance
- Track business metrics (sales, returns, refunds)
- Debug issues in production
- Meet Service Level Objectives (SLOs)
- Provide audit trails for compliance

We need to implement logging and metrics using **only the Python standard library** (no external dependencies like Prometheus client or structlog).

## Decision Drivers

* **Debuggability**: Quickly identify and diagnose issues
* **Performance Monitoring**: Track latency, throughput, errors
* **Business Insights**: Monitor RMA rates, checkout success, payment failures
* **SLO Compliance**: Measure and report against service objectives
* **Standard Library Only**: No external observability dependencies
* **Machine-Readable**: Enable automated log parsing and alerting
* **Scalability**: Support high-volume logging without bottlenecks

## Considered Options

### Option 1: Print Statements and Basic Logging
**Pros:**
- Simple to implement
- No dependencies

**Cons:**
- Unstructured data (hard to parse)
- No metrics support
- Limited context
- Not machine-readable

### Option 2: External Libraries (Prometheus Client, structlog)
**Pros:**
- Rich feature set
- Industry standard
- Well-tested

**Cons:**
- Violates "standard library only" constraint
- Additional dependencies
- Potential version conflicts

### Option 3: Custom Structured Logging + Metrics Library  **SELECTED**
**Pros:**
- Meets "standard library only" requirement
- Structured JSON logs (machine-readable)
- Prometheus-compatible metrics format
- Full control over implementation
- No external dependencies

**Cons:**
- Initial development effort
- Need to maintain custom code
- Less battle-tested than libraries

## Decision Outcome

**Chosen option:** Custom implementation using Python standard library (Option 3)

We will implement observability through two custom modules:

### 1. Structured Logging (`logging_config.py`)

#### Features:
- **JSON Formatter**: All logs emitted as JSON for structured parsing
- **Rotating File Handler**: Prevents disk exhaustion (5MB x 3 backups)
- **Console Handler**: Stdout for container log aggregation
- **Context Fields**: request_id, user_id, extra metadata

#### Implementation:
```python
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "timestamp": datetime.utcfromtimestamp(record.created).isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        # Include context fields
        if hasattr(record, "request_id"):
            log_record["request_id"] = getattr(record, "request_id")
        if hasattr(record, "user_id"):
            log_record["user_id"] = getattr(record, "user_id")
        if hasattr(record, "extra"):
            log_record.update(getattr(record, "extra"))
        return json.dumps(log_record)
```

#### Usage:
```python
logger.info(
    "Return approved",
    extra={
        "request_id": rma.rma_number,
        "user_id": self._current_user_id,
        "extra": {"sale_id": rma.sale_id, "refund_ref": refund_ref}
    }
)
```

#### Log Format Example:
```json
{
  "timestamp": "2025-11-14T10:30:45Z",
  "level": "INFO",
  "module": "app",
  "message": "Return approved",
  "request_id": "RMA-1731582645123",
  "user_id": 42,
  "sale_id": 789,
  "refund_ref": "REFUND-TXN-12345"
}
```

### 2. Custom Metrics Library (`metrics.py`)

#### Metric Types:
1. **Counter**: Monotonically increasing (e.g., request count, error count)
2. **Gauge**: Point-in-time value (e.g., circuit breaker state, active sessions)
3. **Histogram**: Distribution with buckets (e.g., latency, processing time)

#### Implementation:
- Thread-safe using `threading.Lock`
- Prometheus text exposition format
- Label support for multi-dimensional metrics
- Global registry pattern

#### Key Metrics Defined:

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `http_requests_total` | Counter | endpoint, method, status | Track HTTP traffic |
| `http_request_latency_seconds` | Histogram | endpoint | Measure response times |
| `checkout_duration_seconds` | Histogram | payment_method | Track checkout performance |
| `circuit_breaker_open` | Gauge | - | Monitor payment service health |
| `checkout_error_total` | Counter | type | Track error categories |
| `rma_requests_total` | Counter | status | Track return requests |
| `rma_processing_duration_seconds` | Histogram | - | Measure RMA processing time |
| `rma_refunds_total` | Counter | method | Track refund operations |

#### Metrics Endpoint:
```python
def do_GET(self):
    if self.path == "/metrics":
        metrics_text = generate_metrics_text()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(metrics_text)
```

#### Example Output:
```
# HELP http_requests_total Total number of HTTP requests
# TYPE http_requests_total counter
http_requests_total{endpoint="/products",method="GET",status="200"} 1523
http_requests_total{endpoint="/checkout",method="POST",status="200"} 342

# HELP rma_requests_total Total number of return (RMA) requests
# TYPE rma_requests_total counter
rma_requests_total{status="Pending"} 15
rma_requests_total{status="Approved"} 12
rma_requests_total{status="Rejected"} 3
```

### Consequences

**Positive:**
- Structured logs enable automated parsing (jq, grep, log aggregators)
- Prometheus-compatible metrics work with existing monitoring tools
- Request tracing via request_id correlation
- Business metrics enable SLO tracking
- Zero external dependencies
- Full control over implementation
- Rotating logs prevent disk exhaustion

**Negative:**
- Custom code requires maintenance
- Less feature-rich than mature libraries
- Team needs to understand custom implementation
- No built-in alerting (requires external scraper)

**Neutral:**
- Metrics stored in-memory (acceptable for single-instance deployment)
- JSON logs may increase disk usage vs. plain text
- Manual metric instrumentation required (not auto-instrumented)

## Validation

Observability implementation will be validated by:

1. **Log Structure**: Verify all logs are valid JSON
2. **Metrics Endpoint**: Confirm `/metrics` returns Prometheus format
3. **Context Propagation**: Verify request_id appears in all related logs
4. **SLO Measurement**: Calculate RMA approval rate from metrics
5. **Performance**: Ensure logging/metrics don't add >5ms latency

### Example Validation Queries:

```bash
# Find all errors for a specific request
jq 'select(.level=="ERROR" and .request_id=="req-123")' logs/retail_app.log

# Calculate RMA approval rate
curl http://localhost:8000/metrics | grep rma_requests_total
# Approval rate = Approved / (Approved + Rejected)

# Find slowest endpoints
jq 'select(.message=="Request completed") | .duration' logs/retail_app.log | sort -rn | head
```

## Compliance and SLOs

This observability system enables tracking of:

| SLO | Metric Source | Target |
|-----|---------------|--------|
| **Availability** | `http_requests_total{status!~"5.."}` | 99.9% |
| **Latency (p99)** | `http_request_latency_seconds` | <500ms |
| **Checkout Success** | `checkout_error_total` / `http_requests_total{endpoint="/checkout"}` | >95% |
| **RMA Processing Time** | `rma_processing_duration_seconds` (median) | <24h |
| **RMA Approval Rate** | `rma_requests_total{status="Approved"}` / total | Context-dependent |

## Integration Points

1. **Monitoring Systems**: Prometheus, Grafana, Datadog (via /metrics endpoint)
2. **Log Aggregation**: ELK Stack, Splunk, CloudWatch Logs (JSON format)
3. **Alerting**: AlertManager, PagerDuty (based on metric thresholds)
4. **Tracing**: Request IDs enable distributed tracing correlation

## Related Decisions

- **ADR-001**: Docker - Logs persisted via volume mounts
- **ADR-003**: Resilience - Circuit breaker state exposed via metrics
- **ADR-004**: Returns Design - RMA metrics track business SLOs

## Notes

- Metric retention is in-memory only; consider external time-series DB for long-term storage
- Logs rotated every 5MB (configurable); adjust based on volume
- Future enhancement: Distributed tracing with OpenTelemetry
- Consider log sampling for very high-traffic scenarios
