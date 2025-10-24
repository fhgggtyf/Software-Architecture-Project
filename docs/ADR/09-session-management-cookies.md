# ADR-009: Session Management with Cookies
**Status:** Accepted  


## Context
Multiple users need concurrent access with independent shopping carts and authentication state. Original single-user design used global state (current_username, shared _cart), causing users to interfere with each other's sessions.

## Decision
Implement cookie-based in-memory session management:
- Storage: In-memory dict {session_id: {app: RetailApp(), username: str}}
- Session ID: UUID in HTTP cookie
- Per-session state: Each session gets own RetailApp() instance with isolated cart
- Thread safety: threading.RLock protects session dictionary
- Implementation: app_web.py (lines 40-90)

```python
_SESSIONS: Dict[str, Dict[str, object]] = {}
_SESS_LOCK = threading.RLock()

def _get_or_create_session(handler):
    sid = extract_from_cookie() or uuid.uuid4().hex
    with _SESS_LOCK:
        if sid not in _SESSIONS:
            _SESSIONS[sid] = {"app": RetailApp(), "username": None}
    return sid, _SESSIONS[sid]
```

## Consequences
**Positive:**
- Supports multiple concurrent users with complete isolation
- No external dependencies (stdlib only) - meets assignment requirements
- Simple implementation - works with ThreadingHTTPServer
- Zero configuration needed

**Negative:**
- Sessions lost on server restart (acceptable for development/demo)
- Memory grows with active sessions (mitigated by short session lifetime)
- Doesn't scale across multiple server instances
- No session expiration (future enhancement)

**Trade-offs:**
- In-memory vs Redis: Chose in-memory for simplicity; sufficient for assignment scope and demo
- Session persistence vs statelessness: Chose persistence - required for shopping cart functionality

## Alternatives Considered
- **Stateless JWT Tokens** - Rejected: Cannot store mutable cart state without database hit per request
- **Redis Session Store** - Deferred: Adds external dependency; good for production but overkill for assignment
- **File-Based Sessions** - Rejected: Poor performance; file I/O bottleneck
