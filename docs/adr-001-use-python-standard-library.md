# ADR-001: Use Python Standard Library Instead of External Frameworks

## Status
Accepted

## Context
We need to build a retail store web application that demonstrates software architecture principles without relying on external dependencies. The application should be self-contained and easy to deploy while still providing a complete web interface.

## Decision
Use only Python's standard library for the web server implementation, avoiding frameworks like Flask, Django, or FastAPI. This includes:
- `http.server` for HTTP request handling
- `sqlite3` for database operations
- `threading` for connection management
- `hashlib` for password hashing
- `urllib.parse` for form data parsing
- `html` for HTML escaping

## Consequences

### Positive
- **Zero external dependencies** - Application can run on any Python 3.10+ installation
- **Educational value** - Demonstrates low-level HTTP handling and web server concepts
- **Deployment simplicity** - No dependency management or virtual environment complexity
- **Performance transparency** - Clear understanding of where time is spent
- **Security control** - Full control over input validation and output escaping

### Negative
- **More boilerplate code** - Manual HTTP parsing, routing, and HTML generation
- **Limited features** - No built-in session management, CSRF protection, or advanced routing
- **Maintenance burden** - More code to maintain compared to framework-based solutions
- **No ecosystem benefits** - Missing plugins, middleware, and community extensions
- **Single-threaded by default** - Limited concurrent request handling

### Neutral
- **Learning curve** - Developers need to understand HTTP protocol details
- **Testing complexity** - More manual setup required for integration tests
