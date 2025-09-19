# ADR 03: Data Access — DAO
**Status:** Accepted   

## Context
We need predictable queries for products, inventory adjustments, and basic reports. The team wants transparency over SQL, low dependency count, and easy portability to a different RDBMS if scale changes.

## Decision
Use a **DAO (Data Access Object) pattern** with hand-written SQL (parameterized) instead of a full ORM.

## Rationale
- **Explicit SQL:** full control over queries, indexes, and performance; easy to review and reason about.  
- **Low dependencies:** standard library `sqlite3` is sufficient; aligns with a “native toolchain” preference.  
- **Portability:** SQL is close to the metal; changing engines later is localized to DAO layer.  
- **Testability:** DAOs are simple to unit/integration test with small fixtures.

### Why not an ORM
- ORMs add an abstraction that can hide performance costs and dialect edge cases.  
- Learning curve and migration scripts can be heavier than the app warrants.  
- For small schemas, ORM advantages (relationship management, migrations, schema reflection) don’t offset the added complexity.

## Consequences
- Slightly more boilerplate for mapping rows ↔ domain objects.  
- Engineers must maintain SQL hygiene (named parameters, avoiding N+1, adding indexes).  
- If domain complexity grows, we can introduce a light query builder later without rewriting the whole layer.
