# ADR 01: Programming Language — Choose Python over C#, Node.js, Java
**Status:** Accepted    

## Context
We need a language for a small-to-mid scope retail app with simple CRUD, reporting, and occasional data processing. Priorities: fast developer velocity, minimal runtime footprint, rich stdlib, and easy onboarding for contributors with mixed backgrounds.

## Decision
Use **Python 3.10+** as the primary implementation language.

## Rationale
- **Developer velocity:** concise syntax, batteries-included stdlib (sqlite3, http.server, csv, logging, unittest/pytest).  
- **Learning curve:** easiest for mixed teams; abundant docs and examples.  
- **Rapid iteration:** great for scripting data imports, one-off reports, ETL.  
- **Deployment:** can run with few external deps; fits “native toolchain” goals.

### Why not C#
- Strong ecosystem, but typically implies Windows/ASP.NET hosting or extra runtime packaging on Linux; overkill for the target scope.

### Why not Node.js
- Excellent for web, but for this project it adds npm dependency sprawl; less “batteries-included” for DB/report tasks; team skill tilt favors Python.

### Why not Java
- Rock-solid, but verbose for a lightweight CRUD app; startup and build tooling are heavier than needed.

## Consequences
- Performance for extreme concurrency isn’t a goal; Python is fine.  
- If we later need heavy async I/O, we can introduce `asyncio` selectively.  
- CI should pin Python version and run type checks (mypy/pyright) to keep code quality high.