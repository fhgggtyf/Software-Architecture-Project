# ADR-004: Returns/RMA (Return Merchandise Authorization) Design

**Status:** Accepted  
**Date:** 2025-11-14  
**Decision Makers:** Development Team 
**Technical Story:** Enable customer returns with refund processing and inventory management

## Context and Problem Statement

The retail system needs to support product returns (Return Merchandise Authorization - RMA) to:
- Allow customers to return purchased items
- Provide administrators with a workflow to review and approve/reject returns
- Process refunds automatically when returns are approved
- Restore inventory for returned items
- Track return metrics for business intelligence and SLOs

**Business Requirements:**
- Customers can request returns for completed purchases
- Each return has a unique RMA number for tracking
- Admin approval required before refund issuance
- Automatic refund processing via payment service
- Inventory restocking upon approval
- Audit trail of all return requests and decisions

**Technical Requirements:**
- New database table for return tracking
- Integration with existing payment refund API
- Metrics for return rates, approval rates, processing time
- RESTful API endpoints for return operations
- Admin UI for return management

## Decision Drivers

* **Customer Satisfaction**: Simple return process improves trust
* **Business Intelligence**: Track return reasons and patterns
* **Compliance**: Maintain audit trail for financial transactions
* **Inventory Accuracy**: Restock returned items automatically
* **SLO Tracking**: Measure return processing time
* **Data Consistency**: Ensure refunds match original payments
* **Fraud Prevention**: Admin review prevents abuse

## Considered Options

### Option 1: Manual Returns (No System Support)
**Pros:**
- No development required
- Flexible for unique cases

**Cons:**
- Manual effort for every return
- No audit trail
- Prone to errors
- No metrics/reporting
- Poor customer experience

### Option 2: Automatic Approval
**Pros:**
- Fast processing
- No admin overhead

**Cons:**
- Vulnerable to fraud/abuse
- No quality control
- Cannot reject invalid returns
- Risk of inventory/financial loss

### Option 3: Admin-Reviewed RMA Workflow  **SELECTED**
**Pros:**
- Fraud prevention through review
- Audit trail for compliance
- Flexible (approve/reject)
- Metrics for business intelligence
- Balances automation and control

**Cons:**
- Requires admin intervention
- Processing delay
- Admin UI/workflow needed

## Decision Outcome

**Chosen option:** Admin-Reviewed RMA Workflow with automatic refund processing (Option 3)

### Architecture

```
Customer Request → RMA Created (Pending) → Admin Review → Approve/Reject
                                              ↓
                                          Refund + Restock (if approved)
```

### Data Model

**Return Table Schema:**
```sql
CREATE TABLE IF NOT EXISTS Return (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    rma_number TEXT NOT NULL,              -- Unique tracking number
    reason TEXT NOT NULL,                   -- Customer-provided reason
    status TEXT NOT NULL,                   -- Pending, Approved, Rejected, Refunded
    request_timestamp TEXT NOT NULL,        -- ISO 8601 timestamp
    resolution_timestamp TEXT,              -- When admin processed
    refund_reference TEXT,                  -- Payment refund reference
    FOREIGN KEY (sale_id) REFERENCES Sale(id),
    FOREIGN KEY (user_id) REFERENCES User(id)
);
```

**Return Request Model:**
```python
@dataclass
class ReturnRequest:
    id: int
    sale_id: int
    user_id: int
    rma_number: str
    reason: str
    status: str                            # Pending, Approved, Rejected, Refunded
    request_timestamp: str
    resolution_timestamp: str | None
    refund_reference: str | None
```

### API Endpoints

| Endpoint | Method | Actor | Purpose |
|----------|--------|-------|---------|
| `/request_return` | POST | Customer | Submit return request |
| `/my_returns` | GET | Customer | View own returns |
| `/admin/returns` | GET | Admin | View all pending returns |
| `/admin/return/<id>/approve` | POST | Admin | Approve and refund |
| `/admin/return/<id>/reject` | POST | Admin | Reject return |

### Business Logic

#### 1. Request Return (`request_return`)
```python
def request_return(self, sale_id: int, reason: str) -> Tuple[bool, str]:
    # Validations:
    # 1. User is logged in
    # 2. Sale exists and belongs to user
    # 3. Sale status is "Completed" (not already refunded)
    # 4. No existing return for this sale
    
    # Generate unique RMA number
    rma_number = f"RMA-{int(time.time() * 1000)}"
    
    # Create return request with status "Pending"
    rma_id = self.return_dao.create_return_request(
        sale_id=sale_id,
        user_id=self._current_user_id,
        rma_number=rma_number,
        reason=reason,
        status="Pending"
    )
    
    # Record metrics
    RMA_REQUESTS_TOTAL.inc(status="Pending")
    
    # Log event
    logger.info("Return requested", extra={"rma_number": rma_number, ...})
    
    return True, f"Return request submitted. Your RMA number is {rma_number}."
```

**Validations:**
- User authentication required
- Sale must exist and belong to user
- Sale status must be "Completed"
- One return per sale (prevent duplicates)

#### 2. Approve Return (`approve_return`)
```python
def approve_return(self, rma_id: int) -> Tuple[bool, str]:
    rma = self.return_dao.get_return(rma_id)
    if not rma or rma.status != "Pending":
        return False, "Return not found or already processed"
    
    # Get original payment
    payment = self.payment_dao.get_payment_for_sale(rma.sale_id)
    if not payment:
        # Reject if no payment found
        self.return_dao.update_return_status(rma_id, "Rejected", None)
        RMA_REQUESTS_TOTAL.inc(status="Rejected")
        return False, "No payment record found"
    
    # Attempt refund via payment service
    approved, refund_ref = self.payment_service.refund_payment(
        payment.reference, payment.amount
    )
    
    if not approved:
        # Refund failed
        self.return_dao.update_return_status(rma_id, "Rejected", None)
        RMA_REQUESTS_TOTAL.inc(status="Rejected")
        return False, "Refund failed; return rejected"
    
    # Refund succeeded:
    # 1. Update return status to "Approved"
    self.return_dao.update_return_status(rma_id, "Approved", refund_ref)
    
    # 2. Update sale status to "Refunded"
    self.sale_dao.update_sale_status(rma.sale_id, "Refunded")
    
    # 3. Restock items
    items = self.sale_dao.get_sale_items(rma.sale_id)
    for item in items:
        self.product_dao.increase_stock(item.product_id, item.quantity)
    
    # 4. Record metrics
    duration = self._calculate_rma_duration(rma.request_timestamp)
    RMA_PROCESSING_DURATION_SECONDS.observe(duration)
    RMA_REQUESTS_TOTAL.inc(status="Approved")
    RMA_REFUNDS_TOTAL.inc(method=payment.method)
    
    # 5. Log approval
    logger.info("Return approved", extra={"rma_number": rma.rma_number, ...})
    
    return True, "Return approved and refund processed."
```

**Key Features:**
- Automatic refund processing (reuses payment service refund API from ADR-003)
- Atomic operations: refund → update DB → restock
- Comprehensive metrics tracking
- Structured logging for audit trail
- Graceful handling of refund failures

#### 3. Reject Return (`reject_return`)
```python
def reject_return(self, rma_id: int, reason: str) -> Tuple[bool, str]:
    rma = self.return_dao.get_return(rma_id)
    if not rma or rma.status != "Pending":
        return False, "Return not found or already processed"
    
    # Update status to "Rejected"
    self.return_dao.update_return_status(rma_id, "Rejected", None)
    
    # Record metrics
    duration = self._calculate_rma_duration(rma.request_timestamp)
    RMA_PROCESSING_DURATION_SECONDS.observe(duration)
    RMA_REQUESTS_TOTAL.inc(status="Rejected")
    
    # Log rejection
    logger.info("Return rejected", extra={
        "rma_number": rma.rma_number,
        "reason": reason
    })
    
    return True, "Return request rejected."
```

### State Diagram

```
        [Customer Request]
               ↓
          ┌─────────┐
          │ Pending │ ←─────────────────┐
          └─────────┘                   │
               ↓                        │
        [Admin Review]                  │
          ╱         ╲                   │
     Approve      Reject                │
        ↓             ↓                 │
   ┌─────────┐   ┌──────────┐         │
   │Approved │   │ Rejected │         │
   └─────────┘   └──────────┘         │
        ↓              ↓                │
   [Refund OK]    [No Refund]          │
        ↓                               │
  ┌──────────┐                         │
  │ Refunded │ (future status)         │
  └──────────┘                         │
        ↓                               │
   [Inventory                          │
    Restocked]                         │
        ↓                               │
    [Complete] ─────────────────────────┘
```

**Status Values:**
- **Pending**: Initial state, awaiting admin review
- **Approved**: Admin approved, refund processed
- **Rejected**: Admin rejected, no refund
- **Refunded**: (Future) Explicit refund completion status

### Metrics and Observability

**Key Metrics:**
```python
# Total return requests by status
RMA_REQUESTS_TOTAL = Counter(
    name="rma_requests_total",
    description="Total number of return (RMA) requests, labelled by status",
    label_names=["status"]  # Pending, Approved, Rejected, Refunded
)

# Processing duration (request to resolution)
RMA_PROCESSING_DURATION_SECONDS = Histogram(
    name="rma_processing_duration_seconds",
    description="Duration of RMA processing from request to resolution",
    label_names=[],
    buckets=[60.0, 3600.0, 86400.0, 604800.0]  # 1min, 1hr, 1day, 1week
)

# Refund operations
RMA_REFUNDS_TOTAL = Counter(
    name="rma_refunds_total",
    description="Total number of refunds issued as part of RMA processing",
    label_names=["method"]  # card, crypto, etc.
)
```

**SLO Tracking:**
| SLO | Metric Calculation | Target |
|-----|-------------------|--------|
| Return Approval Rate | `Approved / (Approved + Rejected)` | Context-dependent |
| Processing Time (median) | `rma_processing_duration_seconds` (p50) | <24 hours |
| Processing Time (p99) | `rma_processing_duration_seconds` (p99) | <7 days |
| Refund Success Rate | `RMA_REFUNDS_TOTAL / Approved` | >99% |

### User Interface

**Customer View:**
- "Request Return" button on completed orders
- Form: Select sale, enter reason
- Confirmation page with RMA number
- "My Returns" page showing status

**Admin View:**
- "Pending Returns" dashboard
- Return details: RMA number, customer, sale, reason, timestamp
- Actions: "Approve" or "Reject" with reason field
- Audit log of all return actions

### Consequences

**Positive:**
- Complete audit trail for compliance
- Fraud prevention through manual review
- Automatic refund processing reduces admin effort
- Inventory accuracy maintained
- Business intelligence via metrics
- Customer self-service for requests
- Reuses payment service refund API (consistency with ADR-003)

**Negative:**
- Processing delay (admin review required)
- Admin workload for high return volumes
- No partial returns (all-or-nothing)
- No return shipping label generation
- Manual reason analysis (no categorization)

**Neutral:**
- One return per sale (business rule)
- Refund amount matches original payment (no restocking fees)
- Return requests cannot be cancelled by customer

### Edge Cases and Error Handling

| Scenario | Handling |
|----------|----------|
| Payment record missing | Reject return, log error |
| Refund API fails | Reject return, log critical error |
| Database update fails after refund | Log critical error, manual intervention required |
| Concurrent approval attempts | Optimistic locking prevents double-refund |
| Return for already-refunded sale | Validation prevents duplicate returns |
| Out-of-stock during restock | Best-effort restock, log warning |

### Security Considerations

1. **Authorization:**
   - Customers can only request returns for their own sales
   - Only admins can approve/reject returns
   - Session-based authentication required

2. **Validation:**
   - Sale status must be "Completed"
   - Sale must belong to requesting user
   - Return must be in "Pending" state for approval/rejection

3. **Audit Trail:**
   - All actions logged with request_id, user_id, timestamps
   - Refund references stored for reconciliation
   - JSON logs enable forensic analysis

### Testing Strategy

**Unit Tests:**
- `test_request_return_success`
- `test_request_return_validation_failures`
- `test_approve_return_with_refund`
- `test_approve_return_refund_failure`
- `test_reject_return`
- `test_restock_on_approval`
- `test_duplicate_return_prevention`

**Integration Tests:**
- End-to-end RMA workflow
- Refund API integration
- Inventory consistency verification

**Performance Tests:**
- Return request throughput
- Admin dashboard load time with 1000+ returns
- Metrics collection overhead

## Related Decisions

- **ADR-002**: Observability - RMA metrics and structured logging
- **ADR-003**: Resilience - Refund API reused from payment service
- **ADR-001**: Docker - Return table persisted in database volume

## Future Enhancements

1. **Partial Returns**: Return subset of items in an order
2. **Return Reasons**: Categorize and analyze return reasons
3. **Automated Approvals**: ML-based fraud detection → auto-approve low-risk returns
4. **Shipping Labels**: Generate prepaid return shipping labels
5. **Restocking Fees**: Configurable fee deduction from refund
6. **Return Windows**: Enforce time limits (e.g., 30 days)
7. **Notifications**: Email/SMS alerts for status changes
8. **Analytics Dashboard**: Visual return trends and patterns

## Notes

- RMA number format: `RMA-{millisecond_timestamp}` (unique, sortable)
- Return status transitions are irreversible (no "unapprove")
- Refund amount always matches original payment (no partial refunds)
- Inventory restocking is best-effort (logs warning on failure)
- Future: Consider adding "Refunded" status for explicit completion tracking
