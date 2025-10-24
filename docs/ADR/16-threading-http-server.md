# ADR-016: ThreadingHTTPServer for Concurrent Requests
**Status:** Accepted  


## Context
Standard HTTPServer handles one request at a time sequentially, blocking all other users. During flash sales with 500+ concurrent users, sequential processing creates unacceptable wait times (e.g., 500 users × 100ms = 50 seconds for last user).

## Decision
Use ThreadingHTTPServer for concurrent request handling:
- One thread per request - no blocking between users
- Built into Python stdlib - no external dependencies
- Simple migration - one line change from HTTPServer
- Implementation: app_web.py (line 650)

```python
from http.server import ThreadingHTTPServer

httpd = ThreadingHTTPServer(server_address, RetailHTTPRequestHandler)
httpd.serve_forever()
```

## Consequences
**Positive:**
- Handles 500+ concurrent users (tested with load generator)
- No blocking between requests - all users get immediate response
- Trivial implementation - one line change
- No external dependencies - meets assignment requirements

**Negative:**
- Thread overhead (~1-2MB per thread)
- Not suitable for 10,000+ connections (would need async/event-driven)
- Requires careful thread-local state management

**Trade-offs:**
- Threads vs async: Chose threads for simplicity; sufficient for assignment scale
- Multi-threading vs multi-processing: Chose threading - lower overhead, shared memory

## Alternatives Considered
- **AsyncIO Server (aiohttp)** - Deferred: More complex; threading sufficient for 500-1000 users
- **WSGI Server (gunicorn)** - Deferred: External dependency violates assignment constraint
- **Single-Threaded HTTPServer** - Rejected: Cannot handle concurrent users
