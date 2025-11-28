# ADR: Documentation and Repository Organization Improvements

**Status**: Accepted – 2025-11-28  

## Context

The final checkpoint required updating the architectural documentation and organizing the repository so that diagrams, ADRs, and the README remain consistent with the implemented features. Previously:
- Several diagrams were outdated
- README did not reflect new features
- ADRs were missing entries for new decisions
- Documentation was scattered and needed consolidation

---

## Decision

### **1. Update all 4+1 architectural views**
- Use Case View updated with:
  - Filtering/Search Orders
  - Low-Stock Alerts
  - RMA Notification Use Case
- Logical View updated with:
  - `_get_rma_notifications()`
  - filtering paths on `/orders`
  - environment variable–based threshold logic
- Process View updated with one sequence diagram (Order Filtering or RMA Notification)
- Deployment View updated with:
  - `LOW_STOCK_THRESHOLD` env variable
  - Updated data flow between app_web and DAOs

### **2. Improve repository structure under `docs/`**
- ADRs grouped under `docs/ADR/`
- UML diagrams stored consistently under `docs/UML/`
- Ensured naming consistency across diagrams

### **3. Update README**
- Added section summarizing new lightweight features
- Added instructions for low-stock threshold configuration
- Updated documentation pointers
- Added usage notes for notifications and filtering

---

## Consequences

### Benefits
- Documentation now accurately reflects system behavior
- Repository easier to navigate
- ADRs track key architectural choices for future reference
- Instructors and reviewers can quickly understand Checkpoint 4 additions

### Trade-offs
- Some duplication between diagrams and README, but acceptable
- Inline HTML notifications are documented but not formalized in the design

### Future Considerations
- Could add scripts to auto-generate UML diagrams
- Could maintain an ADR index for easier browsing
