# ADR-009: Implement HTML Escaping for XSS Prevention

## Status
Accepted

## Context
The web application displays user-generated content and database values in HTML responses. Without proper escaping, malicious input could lead to Cross-Site Scripting (XSS) attacks. We need a simple but effective solution using only Python's standard library.

## Decision
Use Python's built-in `html.escape()` function for all user input and database values displayed in HTML:
- Escape all text content before including in HTML responses
- Use `quote=True` parameter to escape both single and double quotes
- Apply escaping in the web server layer before sending responses
- Create a helper function `html_escape()` for consistent usage

## Consequences

### Positive
- **XSS prevention** - Protects against script injection attacks
- **Built-in solution** - No external dependencies required
- **Simple implementation** - Easy to understand and maintain
- **Consistent protection** - Single function used throughout the application
- **Performance** - Fast escaping with minimal overhead

### Negative
- **Manual application** - Must remember to escape all user content
- **No automatic protection** - Easy to forget escaping in new code
- **Limited functionality** - Only basic HTML escaping, no advanced sanitization
- **No context awareness** - Escapes everything regardless of context
- **Maintenance burden** - Requires careful review of all HTML generation

### Neutral
- **Output encoding** - All responses use UTF-8 encoding
- **Browser compatibility** - Standard HTML entities work in all browsers

## Implementation Details
```python
def html_escape(s: str) -> str:
    """Escape text for inclusion in HTML."""
    return html.escape(s, quote=True)

# Usage in HTML generation:
def _wrap_page(self, title: str, body: str) -> str:
    return f"<title>{html_escape(title)}</title>"

def _handle_products_get(self) -> None:
    row = f"<td>{html_escape(p.name)}</td>"
```

## Alternative Considered
Template engines (Jinja2, etc.) were considered but rejected due to:
- External dependency requirement
- Overkill for simple HTML generation
- Focus on demonstrating manual HTML escaping concepts
- Desire to keep the application dependency-free

## Security Note
This provides basic XSS protection but production applications should consider:
- Content Security Policy (CSP) headers
- Input validation and sanitization
- Output encoding based on context (HTML, URL, JavaScript)
- Template engines with automatic escaping
