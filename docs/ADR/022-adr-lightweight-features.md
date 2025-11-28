# ADR: Lightweight Features – Order Filtering, Low-Stock Alerts, and RMA Notifications

**Status**: Accepted – 2025-11-28  

## Context

Checkpoint 4 introduced three lightweight features expected to enhance usability and admin workflows without modifying the core architecture. These features needed to be implemented with minimal disruption to existing modules while aligning with prior design decisions (DAO isolation, session-based state, no external JS/CSS dependencies, minimal code additions).

The three required features were:
1. Order History Filtering & Search  
2. Low-Stock Alerts  
3. Return (RMA) Status Notifications  

These features have no impact on concurrency, transactions, partner ingestion, or the circuit breaker logic and therefore must remain inside the web controller layer.

---

## Decision

### **1. Order History Filtering & Search**
Filtering is performed inside `app_web.py` at the controller layer:
- Uses query parameters (`status`, `start`, `end`, `q`) in `/orders`
- Used the existing DAO methods: no DAO changes required
- Keyword search uses sale items + product lookup
- Filtering is done in Python instead of SQL to avoid schema changes

### **2. Low-Stock Alerts**
- Low-stock threshold controlled via **environment variable** `LOW_STOCK_THRESHOLD`
- Implemented entirely in the admin dashboard handler in `app_web.py`
- Uses `product_dao.list_products()`
- No schema changes required

### **3. Return Status Notifications**
- Implemented via **session-based delta detection**
- Session stores last-known statuses: `session["rma_statuses"] = {...}`
- `_get_rma_notifications()` compares new vs old and emits HTML notifications
- Non-blocking popups implemented using inline `<div>` + `setTimeout()` (no CSS files)

---

## Consequences

### Benefits
- Minimal changes to system design
- No changes needed to DAOs or database schema
- Fully consistent with existing architecture patterns
- Lightweight implementation avoids complexity
- No external dependencies added

### Trade-offs
- Filtering in Python instead of SQL may be less efficient at large scale, but acceptable for a local SQLite project
- Notification UX intentionally lightweight, not reactive or websocket-based
- Low-stock threshold is global rather than per-category or dynamic

### Future Considerations
- Could move filtering into SQL for scaling
- Could add CSS-based toast notifications
- Could push RMA notifications to a user inbox or event queue
