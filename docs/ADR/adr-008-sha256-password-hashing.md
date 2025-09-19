# ADR-008: Use SHA-256 for Password Hashing

## Status
Accepted

## Context
The application needs to store user passwords securely. We must choose a hashing algorithm that provides reasonable security while being simple to implement using Python's standard library.

## Decision
Use SHA-256 for password hashing:
- Hash passwords using `hashlib.sha256()` before storing
- Store only the hash, never plaintext passwords
- Use UTF-8 encoding for consistent hash generation
- No salt implementation (simplified for demo purposes)

## Consequences

### Positive
- **Built-in support** - Available in Python's standard library
- **Simplicity** - Easy to implement and understand
- **Consistency** - Deterministic hashing for same input
- **No external dependencies** - No need for additional libraries
- **Fast performance** - Quick hash computation

### Negative
- **Vulnerable to rainbow tables** - No salt makes precomputed attacks possible
- **Not cryptographically secure** - SHA-256 is fast, making brute force easier
- **No key stretching** - Missing PBKDF2 or bcrypt iterations
- **Outdated practice** - Modern applications use Argon2 or bcrypt
- **No salt** - Identical passwords produce identical hashes

### Neutral
- **Hash length** - 64-character hex string for storage
- **Collision resistance** - SHA-256 provides good collision resistance

## Implementation Details
```python
def register_user(self, username: str, password: str) -> bool:
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    # Store password_hash in database

def authenticate(self, username: str, password: str) -> Optional[int]:
    password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    # Compare with stored hash
```

## Alternative Considered
Modern password hashing (bcrypt, Argon2) was considered but rejected due to:
- Need for external dependencies (bcrypt library)
- Added complexity for a demo application
- SHA-256 is sufficient to demonstrate password hashing concepts
- Focus on architecture rather than security best practices

## Security Note
This implementation is suitable for educational purposes only. Production applications should use:
- Argon2, bcrypt, or PBKDF2 with appropriate parameters
- Random salt for each password
- Key stretching with sufficient iterations
