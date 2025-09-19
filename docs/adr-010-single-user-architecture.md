# ADR-010: Design for Single-User Demonstration Architecture

## Status
Accepted

## Context
The retail application is designed as an educational demonstration of software architecture patterns. We need to decide between implementing a full multi-user system with proper session management versus a simplified single-user architecture that focuses on architectural concepts.

## Decision
Design the application for single-user demonstration with the following characteristics:
- Global `current_username` variable for session state
- Single `RetailApp` instance shared across all requests
- In-memory shopping cart tied to the global instance
- No proper session management or user isolation
- Admin functionality accessible to any logged-in admin user

## Consequences

### Positive
- **Simplicity** - Easy to understand and demonstrate architectural concepts
- **No session complexity** - Avoids session storage, cookies, and session management
- **Clear data flow** - Straightforward request-to-response flow
- **Educational focus** - Emphasizes architecture over user management
- **Quick implementation** - Faster development without session infrastructure
- **Easy testing** - Simple state management for automated tests

### Negative
- **Not production-ready** - Cannot handle multiple concurrent users
- **Security limitations** - No proper user isolation or session security
- **State conflicts** - Multiple users would interfere with each other
- **No scalability** - Cannot be extended to multi-user without major changes
- **Limited realism** - Doesn't demonstrate real-world user management

### Neutral
- **Memory usage** - Single instance uses minimal memory
- **Performance** - No session lookup overhead

## Implementation Details
```python
# Global state in app_web.py
retail = RetailApp()
current_username: Optional[str] = None

class RetailApp:
    def __init__(self):
        self._cart: Dict[int, CartLine] = {}
        self._current_user_id: int | None = None
```

## Alternative Considered
Multi-user architecture was considered but rejected due to:
- Added complexity that would distract from architectural learning
- Need for session management infrastructure
- Cookie handling and session storage
- User isolation and security concerns
- Focus on demonstrating clean architecture patterns rather than user management

## Future Considerations
If extending to multi-user, would need:
- Proper session management (cookies, session storage)
- User-specific cart storage in database
- Session-based authentication
- User isolation and security measures
- Concurrent access handling
