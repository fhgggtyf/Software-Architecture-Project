# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records (ADRs) for the Retail Store Application. ADRs document the key architectural decisions made during development, including the context, decision rationale, and consequences.

## ADR Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-001](adr-001-use-python-standard-library.md) | Use Python Standard Library Instead of External Frameworks | Accepted |
| [ADR-002](adr-002-dao-pattern-for-data-access.md) | Use Data Access Object (DAO) Pattern for Database Operations | Accepted |
| [ADR-003](adr-003-sqlite-database-choice.md) | Use SQLite as the Primary Database | Accepted |
| [ADR-004](adr-004-in-memory-shopping-cart.md) | Use In-Memory Shopping Cart for Simplified State Management | Accepted |
| [ADR-005](adr-005-thread-local-database-connections.md) | Use Thread-Local Storage for Database Connection Management | Accepted |
| [ADR-006](adr-006-mock-payment-service.md) | Implement Mock Payment Service for Demonstration | Accepted |
| [ADR-007](adr-007-atomic-checkout-transactions.md) | Use Atomic Database Transactions for Checkout Operations | Accepted |
| [ADR-008](adr-008-sha256-password-hashing.md) | Use SHA-256 for Password Hashing | Accepted |
| [ADR-009](adr-009-html-escaping-for-xss-prevention.md) | Implement HTML Escaping for XSS Prevention | Accepted |
| [ADR-010](adr-010-single-user-architecture.md) | Design for Single-User Demonstration Architecture | Accepted |

## ADR Template

Each ADR follows this structure:

1. **Status** - Current state (Proposed, Accepted, Rejected, Deprecated, Superseded)
2. **Context** - The situation and problem that led to this decision
3. **Decision** - The architectural decision made
4. **Consequences** - The positive, negative, and neutral consequences of the decision
5. **Implementation Details** - Code examples and technical specifics
6. **Alternatives Considered** - Other options that were evaluated

## Purpose

These ADRs serve to:
- Document the reasoning behind architectural choices
- Provide context for future developers
- Explain trade-offs and consequences of decisions
- Guide future architectural evolution
- Support educational understanding of the codebase

## Maintenance

ADRs should be updated when:
- Architectural decisions change
- New constraints or requirements emerge
- Better alternatives are discovered
- Decisions are superseded by new ones
