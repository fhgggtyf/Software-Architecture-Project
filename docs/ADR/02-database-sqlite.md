# ADR 02: Database — Choose SQLite over PostgreSQL
**Status:** Accepted   

## Context
The app stores products, inventory movements, and lightweight sales records. Expected usage: single instance, small team, modest write concurrency, database size well under a few GB. Operations should be zero-maintenance with easy backups.

## Decision
Use **SQLite** as the production database.

## Rationale
- **Zero-ops & portable:** single file DB; trivial to back up/copy/migrate.  
- **Built-in driver:** Python’s `sqlite3` module reduces dependencies.  
- **Performance for our profile:** fast reads, adequate single-writer throughput for a small retail back office.  
- **Simplicity:** no server to install, patch, or secure; ideal for kiosk/SMB.

### Why not PostgreSQL (for now)
- Powerful and scalable, but requires server setup, user/role mgmt, backups, monitoring—unnecessary overhead for the current scale.  
- Networked DB adds operational complexity we don’t currently need.

## Consequences
- **Concurrency limits:** single-writer; need short transactions and pragmatic batching.  
- **Migrations:** we’ll keep schema migration scripts (SQL files) under version control.  
- **Growth plan:** DAO abstraction (ADR 03) keeps us ready to lift-and-shift to PostgreSQL later by swapping drivers/sql dialect where needed.