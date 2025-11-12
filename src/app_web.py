# app_web.py — multi-user, stdlib-only, drop-in replacement

"""
Simple HTTP server for the retail application.

This module provides a minimal web interface built entirely on
Python's standard library. It preserves the same URL structure and
functionality while adding per-session state so multiple users can
use the app concurrently.

Key changes from the single-user version:
- ThreadingHTTPServer (handles concurrent requests)
- Cookie-based in-memory sessions (one RetailApp() per session)
- No global current user or shared cart; state is per-session

Run the server with:

    python app_web.py

It will listen on localhost:8000 by default. Use CTRL+C to stop.
"""

from __future__ import annotations

import html
import os
import urllib.parse
import uuid
import threading
import time
import logging
from http import cookies
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional

# Import the business logic
from app import RetailApp
from external_services import reseller_gateway  # ensure gateway imported for future use
import json

# Configure logging and import metrics
import logging_config  # custom logging configuration module
from metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_LATENCY_SECONDS,
    generate_metrics_text,
    RMA_REQUESTS_TOTAL,
    RMA_PROCESSING_DURATION_SECONDS,
    RMA_REFUNDS_TOTAL,
    CHECKOUT_ERROR_TOTAL,
    CIRCUIT_BREAKER_OPEN,
)

# Initialize logging as soon as the module is loaded.  This sets up
# JSON formatting and file/console handlers.  It will no‑op if called
# multiple times.
logging_config.configure_logging()

try:
    from sqlite3 import IntegrityError
except ImportError:
    IntegrityError = Exception  # fallback, should not happen

# -----------------------------------------------------------------------------
# In-memory cookie sessions: sid -> {"app": RetailApp(), "username": Optional[str]}
# -----------------------------------------------------------------------------
_SESSIONS: Dict[str, Dict[str, object]] = {}
_SESS_LOCK = threading.RLock()
SESSION_COOKIE_NAME = "sid"

# -----------------------------------------------------------------------------
# Partner API keys and workload recording
#
# Scenario 2.1 requires that partner feed ingestion be authenticated.  Keys
# can be provided via the PARTNER_API_KEYS environment variable in the form
# "key1:partnerA,key2:partnerB".  If none are set, a default dummy key is
# registered for testing purposes.

def _load_partner_api_keys() -> Dict[str, str]:
    keys: Dict[str, str] = {}
    env = os.environ.get("PARTNER_API_KEYS")
    if env:
        for pair in env.split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                keys[k.strip()] = v.strip()
    # Fallback dummy key to support the test harness
    if not keys:
        keys["dummy"] = "default"
    return keys

# Dictionary mapping API keys to partner names
_PARTNER_API_KEYS: Dict[str, str] = _load_partner_api_keys()

# Request log storage for workload capture and replay (testability scenario 6.1)
_REQUEST_LOG: list[Dict[str, object]] = []
_REQUEST_LOG_LOCK = threading.Lock()

def _warmup_db():
    try:
        # this import matches your existing DAO module name
        from dao import get_request_connection
        conn = get_request_connection()  # triggers init.sql on first connection
        conn.execute("SELECT 1;")
        print("DB warmup: OK")
    except Exception as e:
        print(f"DB warmup: warning: {e}")

def _get_or_create_session(handler: BaseHTTPRequestHandler):
    """Return (sid, session_dict, set_cookie_fn). Creates a session if missing."""
    jar = cookies.SimpleCookie()
    raw = handler.headers.get("Cookie")
    if raw:
        try:
            jar.load(raw)
        except Exception:
            pass

    sid = jar.get(SESSION_COOKIE_NAME).value if (jar and SESSION_COOKIE_NAME in jar) else None

    with _SESS_LOCK:
        if not sid or sid not in _SESSIONS:
            sid = uuid.uuid4().hex
            _SESSIONS[sid] = {"app": RetailApp(), "username": None}
        session = _SESSIONS[sid]

    def set_cookie_header():
        c = cookies.SimpleCookie()
        c[SESSION_COOKIE_NAME] = sid
        c[SESSION_COOKIE_NAME]["path"] = "/"
        # For real deployments, consider uncommenting:
        # c[SESSION_COOKIE_NAME]["httponly"] = True
        # c[SESSION_COOKIE_NAME]["samesite"] = "Lax"
        handler.send_header("Set-Cookie", c.output(header="").strip())

    return sid, session, set_cookie_header


def html_escape(s: str) -> str:
    return html.escape(s, quote=True)


class RetailHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler implementing the retail web interface (per-session)."""

    # Per-request/session fields
    sid: str
    session: Dict[str, object]
    set_cookie_header = None

    # -------------------
    # Response utilities
    # -------------------
    def _send_html(self, content: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        # Always refresh the cookie on responses
        if self.set_cookie_header:
            self.set_cookie_header()
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))
        # Record metrics for this request after sending the response
        try:
            self._record_metrics(status)
        except Exception:
            pass

    def _redirect(self, location: str) -> None:
        status = 302
        self.send_response(status)
        self.send_header("Location", location)
        if self.set_cookie_header:
            self.set_cookie_header()
        self.end_headers()
        # Record metrics for this redirect
        try:
            self._record_metrics(status)
        except Exception:
            pass

    # -------------------
    # Metrics helper
    # -------------------
    def _record_metrics(self, status: int) -> None:
        """Record metrics for the current request.

        This helper updates the global request counter and latency histogram.
        It ensures that metrics are recorded only once per request.  The
        ``status`` parameter should be the HTTP status code that was sent
        in the response.
        """
        # Only record metrics once per request
        if getattr(self, "_metrics_recorded", False):
            return
        # Determine endpoint (path without query string)
        try:
            endpoint = self.path.partition("?")[0]
        except Exception:
            endpoint = "unknown"
        method = getattr(self, "command", "?")
        # Increment request counter
        try:
            HTTP_REQUESTS_TOTAL.inc(endpoint=endpoint, method=method, status=str(status))
        except Exception:
            pass
        # Observe latency
        try:
            # If start time recorded, compute latency; otherwise zero
            start = getattr(self, "_request_start_time", None)
            if start is not None:
                latency = time.perf_counter() - start
            else:
                latency = 0.0
            HTTP_REQUEST_LATENCY_SECONDS.observe(latency, endpoint=endpoint)
        except Exception:
            pass
        # Record the request in the workload log for replay/testing purposes
        try:
            with _REQUEST_LOG_LOCK:
                _REQUEST_LOG.append({
                    "method": method,
                    "endpoint": endpoint,
                    "timestamp": time.time(),
                })
        except Exception:
            pass
        # Mark as recorded
        self._metrics_recorded = True

    # -------------
    # Page chrome
    # -------------
    def _render_nav(self) -> str:
        username = self.session.get("username")
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        parts = [
            "<nav>",
            '<a href="/products">Products</a>',
            '<a href="/cart">Cart</a>',
        ]
        if username:
            # Show admin link if the current user has admin rights
            if app.current_user_is_admin(username):  # type: ignore[arg-type]
                parts.append('<a href="/admin/products">Admin</a>')
                # Admins can manage returns from a dedicated page
                parts.append('<a href="/admin/returns">Returns</a>')
            parts.append(f"<span>Hi, {html_escape(str(username))}</span>")
            # Logged in users can view their order history and returns
            parts.append('<a href="/orders">Orders</a>')
            parts.append('<a href="/returns">My Returns</a>')
            parts.append('<a href="/logout">Logout</a>')
        else:
            parts.append('<a href="/login">Login</a>')
            parts.append('<a href="/register">Register</a>')
        parts.append("</nav>")
        return "".join(parts)

    def _wrap_page(self, title: str, body: str) -> str:
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{html_escape(title)}</title>
  <style>
    body {{ font-family: system-ui, Arial, sans-serif; margin: 2rem; }}
    nav a {{ margin-right: 1rem; }}
    form {{ margin: .5rem 0; }}
    table {{ border-collapse: collapse; }}
    th, td {{ padding: .4rem; border: 1px solid #ccc; }}
    .ok {{ color: green; }} .err {{ color: #b00; }}
  </style>
</head>
<body>
{self._render_nav()}
<main>
{body}
</main>
</body>
</html>"""

    # --------------
    # Request entry
    # --------------
    def _begin_request(self):
        # Create or retrieve the session.  Each request gets a session and a cookie setter.
        self.sid, self.session, self.set_cookie_header = _get_or_create_session(self)
        # Record the start time for metrics.  This is used to compute latency.
        self._request_start_time = time.perf_counter()
        # Flag to ensure we record metrics only once per request
        self._metrics_recorded = False

    def do_GET(self) -> None:
        # Special endpoint for metrics.  Do not create a session or set cookies.
        metrics_path = self.path.partition("?")[0]
        if metrics_path == "/metrics":
            output = generate_metrics_text()
            # Send plain text in Prometheus exposition format
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.end_headers()
            try:
                self.wfile.write(output)
            except Exception:
                pass
            return

        # Normal request handling: set up session and record start time
        self._begin_request()
        path, _, _ = self.path.partition("?")

        if path == "/" or path == "":
            self._redirect("/products")
            return
        # Partner feed ingestion (authenticated).  Scenario 2.1.
        if path.startswith("/partner/feed"):
            self._handle_partner_feed_get()
            return
        # Workload capture and replay endpoints (testability).  Scenario 6.1.
        if path == "/workload/log":
            self._handle_workload_log_get()
            return
        if path == "/workload/clear":
            self._handle_workload_clear_get()
            return
        if path == "/workload/replay":
            self._handle_workload_replay_get()
            return
        if path == "/register":
            self._handle_register_get()
            return
        if path == "/login":
            self._handle_login_get()
            return
        if path == "/logout":
            self._handle_logout_get()
            return
        if path == "/products":
            self._handle_products_get()
            return
        if path.startswith("/admin/product/") and path.endswith("/edit"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, pid_str, _ = parts
                try:
                    pid = int(pid_str)
                except ValueError:
                    self._send_html(self._wrap_page("Error", "Invalid product ID."), 404)
                    return
                self._handle_admin_product_edit_get(pid)
                return
        if path == "/admin/products":
            self._handle_admin_products_get()
            return
        if path == "/admin/product/new":
            self._handle_admin_new_product_get()
            return
        if path == "/cart":
            self._handle_cart_get()
            return
        if path == "/checkout":
            self._handle_checkout_get()
            return

        # New endpoints for orders and returns
        if path == "/orders":
            self._handle_orders_get()
            return
        if path == "/return-request":
            self._handle_return_request_get()
            return
        if path == "/returns":
            self._handle_returns_get()
            return
        if path == "/admin/returns":
            self._handle_admin_returns_get()
            return
        if path == "/dashboard":
            self._handle_dashboard_get()
            return

        self._send_html(self._wrap_page("404 Not Found", "<p>Page not found.</p>"), 404)

    def do_POST(self) -> None:
        self._begin_request()
        path = self.path

        if path == "/register":
            self._handle_register_post()
            return
        if path == "/login":
            self._handle_login_post()
            return
        if path == "/admin/product/new":
            self._handle_admin_new_product_post()
            return
        if path.startswith("/admin/product/") and path.endswith("/edit"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, pid_str, _ = parts
                try:
                    pid = int(pid_str)
                except ValueError:
                    self._send_html(self._wrap_page("Error", "Invalid product ID."), 404)
                    return
                self._handle_admin_product_edit_post(pid)
                return
        if path.startswith("/admin/product/") and path.endswith("/delete"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, _, pid_str, _ = parts
                try:
                    pid = int(pid_str)
                except ValueError:
                    self._send_html(self._wrap_page("Error", "Invalid product ID."), 404)
                    return
                self._handle_admin_product_delete_post(pid)
                return
        if path == "/cart/add":
            self._handle_cart_add_post()
            return
        if path == "/cart/remove":
            self._handle_cart_remove_post()
            return
        if path == "/cart/clear":
            self._handle_cart_clear_post()
            return
        # New reseller order endpoint (integrability scenario 5.1).
        # Allows external resellers or marketplace adapters to submit orders
        # to the system.  Orders are forwarded to the ResellerAPIGateway
        # configured in the current RetailApp instance.  The request body
        # should contain a JSON object with at least a ``reseller`` name
        # and an ``items`` list.  Unknown reseller names will result in
        # a 400 error.  On success, a confirmation page is returned.  This
        # endpoint demonstrates how new reseller APIs can be onboarded via
        # the adapter/gateway pattern without modifying business logic.
        if path == "/reseller/order":
            self._handle_reseller_order_post()
            return
        if path == "/checkout":
            self._handle_checkout_post()
            return

        # New endpoints: handle return request submission
        if path == "/return-request":
            self._handle_return_request_post()
            return
        # Admin actions on returns: approve or reject
        if path.startswith("/admin/returns/") and (path.endswith("/approve") or path.endswith("/reject")):
            # URL pattern: /admin/returns/<id>/approve or /reject
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _, section, rma_id_str, action = parts
                try:
                    rma_id = int(rma_id_str)
                except ValueError:
                    self._send_html(self._wrap_page("Error", "Invalid return ID."), 400)
                    return
                if action == "approve":
                    self._handle_admin_return_action_post(rma_id, approve=True)
                    return
                elif action == "reject":
                    self._handle_admin_return_action_post(rma_id, approve=False)
                    return
            # Fallback 404 if pattern does not match
            self._send_html(self._wrap_page("Not Found", "Invalid return action."), 404)
            return

        self._send_html(self._wrap_page("404 Not Found", "<p>Page not found.</p>"), 404)

    # -----------------------
    # Helpers / form parsing
    # -----------------------
    def _parse_post_data(self) -> Dict[str, str]:
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(data, keep_blank_values=True)
        return {k: v[0] for k, v in params.items()}

    # ----------------
    # GET handlers
    # ----------------
    def _handle_register_get(self) -> None:
        body = """
<h1>Register</h1>
<form method="post" action="/register">
  <label>Username: <input type="text" name="username" required></label><br>
  <label>Password: <input type="password" name="password" required></label><br>
  <button type="submit">Register</button>
</form>
"""
        self._send_html(self._wrap_page("Register", body))

    def _handle_login_get(self) -> None:
        body = """
<h1>Login</h1>
<form method="post" action="/login">
  <label>Username: <input type="text" name="username" required></label><br>
  <label>Password: <input type="password" name="password" required></label><br>
  <button type="submit">Login</button>
</form>
"""
        self._send_html(self._wrap_page("Login", body))

    def _handle_logout_get(self) -> None:
        # Reset per-session state: new RetailApp + clear username
        with _SESS_LOCK:
            self.session["username"] = None
            self.session["app"] = RetailApp()
        body = '<p>You have been logged out.</p><p><a href="/products">Continue shopping</a>.</p>'
        self._send_html(self._wrap_page("Logged Out", body))

    def _handle_products_get(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        products = app.list_products()
        rows = []
        from datetime import datetime, UTC
        for p in products:
            # Determine effective price based on flash sale
            effective_price = p.price
            on_sale = False
            try:
                if p.flash_sale_price is not None and p.flash_sale_start and p.flash_sale_end:
                    start = datetime.fromisoformat(p.flash_sale_start)
                    end = datetime.fromisoformat(p.flash_sale_end)
                    now = datetime.now(UTC)
                    if start.tzinfo is None:
                        start = start.replace(tzinfo=UTC)
                    if end.tzinfo is None:
                        end = end.replace(tzinfo=UTC)
                    if start <= now <= end:
                        effective_price = p.flash_sale_price
                        on_sale = True
            except Exception:
                pass
            price_html = f"{effective_price:.2f}"
            if on_sale:
                # When on sale, show the original price struck through, the sale price,
                # and a countdown timer placeholder that will be updated via JS.
                sale_info = (
                    f"<span style='text-decoration:line-through;color:#777'>{p.price:.2f}</span> "
                    f"<span style='color:#d00;font-weight:bold'>{p.flash_sale_price:.2f}</span>"
                )
                sale_info += (
                    f"<br><small>Sale: {p.flash_sale_start} → {p.flash_sale_end}</small>"
                    f"<br><span class='flash-countdown' data-end='{p.flash_sale_end}'></span>"
                )
                price_html = sale_info
            else:
                price_html = f"{p.price:.2f}"

            row = (
                f"<tr><td>{p.id}</td><td>{html_escape(p.name)}</td><td>{price_html}</td><td>{p.stock}</td>"
                "<td>"
                f"<form method='post' action='/cart/add' style='display:inline'>"
                f"<input type='hidden' name='product_id' value='{p.id}' />"
                # Limit the quantity input to available stock so users cannot
                # request more than what's in inventory.  HTML5 browsers will
                # prevent submission if the value exceeds this maximum.
                f"<input type='number' name='quantity' min='1' max='{p.stock}' value='1' style='width:4rem' />"
                "<button type='submit'>Add</button></form>"
                "</td></tr>"
            )
            rows.append(row)
        # Join table rows into a single HTML string outside the f-string to avoid
        # embedding backslashes in f-string expressions (Python 3.12+ restriction).
        rows_html = "\n".join(rows)
        table_html = f"""
<h1>Products</h1>
<table>
  <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th>Add to Cart</th></tr>
  {rows_html}
</table>
"""
        username = self.session.get("username")
        admin_html = ""
        if username and app.current_user_is_admin(username):  # type: ignore[arg-type]
            admin_html = "<p><a href='/admin/product/new'>Add New Product</a></p>"
        # Include a countdown script for flash sale items (usability scenario 7.2)
        countdown_script = """
<script>
function updateCountdown() {
  document.querySelectorAll('.flash-countdown').forEach(function(el) {
    var end = el.dataset.end;
    var endMs = Date.parse(end);
    var now = Date.now();
    var diff = endMs - now;
    if (diff > 0) {
      var secs = Math.floor(diff / 1000);
      var mins = Math.floor(secs / 60);
      var hrs = Math.floor(mins / 60);
      secs = secs % 60;
      mins = mins % 60;
      el.textContent = hrs + 'h ' + mins + 'm ' + secs + 's remaining';
    } else {
      el.textContent = 'Sale ended';
    }
  });
}
setInterval(updateCountdown, 1000);
window.addEventListener('load', updateCountdown);
</script>
"""
        self._send_html(self._wrap_page("Products", table_html + admin_html + countdown_script))

    def _handle_admin_products_get(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to access this page.</p>"), 403)
            return
        products = app.list_products()
        rows = []
        for p in products:
            rows.append(
                f"<tr><td>{p.id}</td><td>{html_escape(p.name)}</td><td>{p.price:.2f}</td><td>{p.stock}</td>"
                f"<td><a href='/admin/product/{p.id}/edit'>Edit</a></td>"
                f"<td><form method='post' action='/admin/product/{p.id}/delete' style='display:inline'>"
                f"<button type='submit'>Delete</button></form></td></tr>"
            )
        # Avoid using a backslash in f-string expressions by joining rows outside
        # of the f-string.
        rows_html = "\n".join(rows)
        table_html = f"""
<h1>Admin Products</h1>
<p><a href='/admin/product/new'>Add New Product</a></p>
<table>
  <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th></th><th></th></tr>
  {rows_html}
</table>
"""
        self._send_html(self._wrap_page("Admin Products", table_html))

    def _handle_admin_new_product_get(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to access this page.</p>"), 403)
            return
        body = """
<h1>New Product</h1>
<form method="post" action="/admin/product/new">
  <label>Name: <input type="text" name="name" required></label><br>
  <label>Price: <input type="text" name="price" required></label><br>
  <label>Stock: <input type="number" name="stock" min="0" required></label><br>
  <button type="submit">Create</button>
</form>
"""
        self._send_html(self._wrap_page("New Product", body))

    def _handle_admin_product_edit_get(self, product_id: int) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to access this page.</p>"), 403)
            return
        p = app.product_dao.get_product(product_id)
        if not p:
            self._send_html(self._wrap_page("Not Found", "<p>Product not found.</p>"), 404)
            return
        body = f"""
<h1>Edit Product #{p.id}</h1>
<form method="post" action="/admin/product/{p.id}/edit">
  <label>Name: <input type="text" name="name" value="{html_escape(p.name)}" required></label><br>
  <label>Price: <input type="text" name="price" value="{p.price}" required></label><br>
  <label>Stock: <input type="number" name="stock" min="0" value="{p.stock}" required></label><br>
  <button type="submit">Update</button>
</form>
"""
        self._send_html(self._wrap_page(f"Edit Product {p.id}", body))

    def _handle_cart_get(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username:
            self._send_html(self._wrap_page("Cart", "<p>You must be logged in to view your cart.</p>"), 403)
            return
        items = app.view_cart()
        if not items:
            self._send_html(self._wrap_page("Cart", "<p>Your cart is empty.</p>"))
            return
        rows = []
        for it in items:
            p = app.product_dao.get_product(it.product_id)
            name = p.name if p else f"#{it.product_id}"
            rows.append(
                f"<tr><td>{it.product_id}</td><td>{html_escape(name)}</td><td>{it.qty}</td>"
                f"<td>{it.unit_price:.2f}</td><td>{it.unit_price * it.qty:.2f}</td>"
                f"<td><form method='post' action='/cart/remove' style='display:inline'>"
                f"<input type='hidden' name='product_id' value='{it.product_id}' />"
                f"<button type='submit'>Remove</button></form></td></tr>"
            )
        totals = app.compute_cart_totals()
        # Join rows into a single string prior to constructing the HTML to
        # avoid embedding a backslash within an f-string expression.
        rows_html = "\n".join(rows)
        body = f"""
<h1>Your Cart</h1>
<table>
  <tr><th>Product ID</th><th>Name</th><th>Qty</th><th>Unit Price</th><th>Total</th><th></th></tr>
  {rows_html}
</table>
<p>Subtotal: {totals.subtotal:.2f} &nbsp; Total: {totals.total:.2f}</p>
<form method='post' action='/cart/clear'>
  <button type='submit'>Clear Cart</button>
</form>
<p><a href='/checkout'>Proceed to Checkout</a></p>
"""
        self._send_html(self._wrap_page("Cart", body))

    def _handle_checkout_get(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username:
            self._send_html(self._wrap_page("Checkout", "<p>You must be logged in to checkout.</p>"), 403)
            return
        items = app.view_cart()
        if not items:
            self._send_html(self._wrap_page("Checkout", "<p>Your cart is empty.</p>"))
            return
        totals = app.compute_cart_totals()
        body = f"""
<h1>Checkout</h1>
<p>Subtotal: {totals.subtotal:.2f} &nbsp; Total: {totals.total:.2f}</p>
<form method='post' action='/checkout'>
  <label>Payment method:
    <select name='payment_method'>
      <option value='Card'>Card</option>
      <option value='Cash'>Cash</option>
      <option value='Crypto'>Crypto</option>
    </select>
  </label><br><br>
  <button type='submit'>Pay</button>
</form>
"""
        self._send_html(self._wrap_page("Checkout", body))

    # ----------------
    # POST handlers
    # ----------------
    def _handle_register_post(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        params = self._parse_post_data()
        username = params.get("username", "").strip()
        password = params.get("password", "").strip()
        if not username or not password:
            self._send_html(self._wrap_page("Register", "<p>Username and password are required.</p>"))
            return
        ok, msg = app.register(username, password)
        if ok:
            body = f"<p>{html_escape(msg)}</p><p><a href='/login'>Go to login</a></p>"
        else:
            body = f"<p>{html_escape(msg)}</p><p><a href='/register'>Try again</a></p>"
        self._send_html(self._wrap_page("Register", body))

    def _handle_login_post(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        params = self._parse_post_data()
        username = params.get("username", "").strip()
        password = params.get("password", "").strip()
        if not username or not password:
            self._send_html(self._wrap_page("Login", "<p>Username and password are required.</p>"))
            return
        if app.login(username, password):
            with _SESS_LOCK:
                self.session["username"] = username
            self._send_html(self._wrap_page("Login", f"<p>Welcome, {html_escape(username)}.</p><p><a href='/products'>Continue shopping</a></p>"))
        else:
            self._send_html(self._wrap_page("Login", "<p>Invalid credentials.</p><p><a href='/login'>Try again</a></p>"))

    def _handle_admin_new_product_post(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to perform this action.</p>"), 403)
            return
        params = self._parse_post_data()
        name = params.get("name", "").strip()
        price_raw = params.get("price", "").strip()
        stock_raw = params.get("stock", "").strip()
        if not name:
            self._send_html(self._wrap_page("Error", "<p>Name is required.</p><p><a href='/admin/product/new'>Back</a></p>"))
            return
        try:
            price = float(price_raw)
            stock = int(stock_raw)
        except ValueError:
            self._send_html(self._wrap_page("Error", "<p>Invalid price or stock.</p><p><a href='/admin/product/new'>Back</a></p>"))
            return
        try:
            pid = app.product_dao.add_product(name, price, stock)
            body = f"<p>Product #{pid} created.</p><p><a href='/admin/products'>Back to list</a></p>"
        except IntegrityError:
            body = "<p>A product with this name already exists.</p><p><a href='/admin/product/new'>Back</a></p>"
        self._send_html(self._wrap_page("New Product", body))

    def _handle_admin_product_edit_post(self, product_id: int) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to perform this action.</p>"), 403)
            return
        params = self._parse_post_data()
        name = params.get("name", "").strip()
        price_raw = params.get("price", "").strip()
        stock_raw = params.get("stock", "").strip()
        try:
            price = float(price_raw)
            stock = int(stock_raw)
        except ValueError:
            self._send_html(self._wrap_page("Error", f"<p>Invalid input values.</p><p><a href='/admin/product/{product_id}/edit'>Back</a></p>"))
            return
        p = app.product_dao.get_product(product_id)
        if not p:
            self._send_html(self._wrap_page("Error", "<p>Product not found.</p><p><a href='/admin/products'>Back</a></p>"), 404)
            return
        app.product_dao.update_name_price(product_id, name or p.name, price)
        app.product_dao.update_stock(product_id, stock)
        self._send_html(self._wrap_page("Edit Product", "<p>Product updated.</p><p><a href='/admin/products'>Back to list</a></p>"))

    def _handle_admin_product_delete_post(self, product_id: int) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to perform this action.</p>"), 403)
            return
        p = app.product_dao.get_product(product_id)
        if not p:
            self._send_html(self._wrap_page("Error", "<p>Product not found.</p><p><a href='/admin/products'>Back</a></p>"), 404)
            return
        try:
            app.product_dao.delete_product(product_id)
            body = "<p>Product deleted.</p><p><a href='/admin/products'>Back to list</a></p>"
        except IntegrityError:
            body = "<p>Cannot delete product because it is referenced by existing sales.</p><p><a href='/admin/products'>Back</a></p>"
        self._send_html(self._wrap_page("Delete Product", body))

    def _handle_cart_add_post(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        params = self._parse_post_data()
        try:
            product_id = int(params.get("product_id", "0"))
            qty = int(params.get("quantity", "0"))
        except ValueError:
            self._send_html(self._wrap_page("Error", "<p>Invalid product or quantity.</p><p><a href='/products'>Back to products</a></p>"))
            return
        if not username:
            self._send_html(self._wrap_page("Error", "<p>You must be logged in to add items to your cart.</p><p><a href='/login'>Login</a></p>"))
            return
        ok, msg = app.add_to_cart(product_id, qty)
        body = f"<p>{html_escape(msg)}</p><p><a href='/products'>Back to products</a> | <a href='/cart'>View cart</a></p>"
        self._send_html(self._wrap_page("Add to Cart", body))

    def _handle_cart_remove_post(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        params = self._parse_post_data()
        try:
            product_id = int(params.get("product_id", "0"))
        except ValueError:
            self._send_html(self._wrap_page("Error", "<p>Invalid product.</p><p><a href='/cart'>Back to cart</a></p>"))
            return
        app.remove_from_cart(product_id)
        self._send_html(self._wrap_page("Remove Item", "<p>Item removed.</p><p><a href='/cart'>Back to cart</a></p>"))

    def _handle_cart_clear_post(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        app.clear_cart()
        self._send_html(self._wrap_page("Clear Cart", "<p>Cart cleared.</p><p><a href='/products'>Continue shopping</a></p>"))

    def _handle_checkout_post(self) -> None:
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        params = self._parse_post_data()
        method = params.get("payment_method", "Card")
        if not username:
            self._send_html(self._wrap_page("Error", "<p>You must be logged in to checkout.</p><p><a href='/login'>Login</a></p>"), 403)
            return
        ok, res = app.checkout(method)
        if ok:
            # Escape the plain-text receipt for HTML display
            receipt_html = html_escape(res).replace("\n", "<br>")
            # Build a downloadable receipt: encode as URL-safe string
            encoded = urllib.parse.quote(res)
            download_link = (
                f"<a href='data:text/plain;charset=utf-8,{encoded}' download='receipt.txt'>Download receipt</a>"
            )
            # Print button triggers browser print dialog
            print_button = "<button onclick=\"window.print()\">Print receipt</button>"
            body = (
                f"<h1>Thank you for your purchase!</h1>"
                f"<p>{receipt_html}</p>"
                f"<p>{print_button} &nbsp; {download_link}</p>"
                f"<p><a href='/products'>Continue shopping</a></p>"
            )
            self._send_html(self._wrap_page("Receipt", body))
        else:
            self._send_html(
                self._wrap_page(
                    "Payment Failed",
                    f"<p>Payment failed: {html_escape(res)}</p><p><a href='/cart'>Back to cart</a></p>",
                )
            )

    # ------------------------------------------------------------------
    # Partner feed handler (Security scenario 2.1)
    # ------------------------------------------------------------------
    def _handle_partner_feed_get(self) -> None:
        """Handle GET requests to /partner/feed.

        This endpoint ingests partner product feeds on behalf of external
        resellers.  Access is controlled via an API key supplied either
        as a query parameter (``api_key``) or as an ``X-API-Key`` HTTP
        header.  If the key is not recognised, the request is rejected.

        Optional query parameters:

          * ``partner`` – logical partner name (ignored if the API key
            determines the partner).
          * ``source`` – file path or URL to the partner feed (CSV, JSON, XML).

        If ``source`` is omitted, a simple success message is returned.  If
        provided, the server attempts to ingest the feed immediately using
        ``RetailApp.ingest_partner_feed``.
        """
        # Extract the API key from query string or header
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        api_key = params.get("api_key", [None])[0] or self.headers.get("X-API-Key")
        if not api_key or api_key not in _PARTNER_API_KEYS:
            self._send_html(self._wrap_page("Unauthorized", "<p>Missing or invalid API key.</p>"), 401)
            return
        partner_name = _PARTNER_API_KEYS.get(api_key, "unknown")
        # Determine the feed source if provided
        feed_src = params.get("source", [None])[0]
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        if feed_src:
            try:
                inserted, updated = app.ingest_partner_feed(partner_name, feed_src)
                body = (
                    f"<p>Partner feed ingested for {html_escape(partner_name)}.</p>"
                    f"<p>Inserted {inserted}, updated {updated} products.</p>"
                )
            except Exception as ex:
                body = f"<p>Error ingesting feed: {html_escape(str(ex))}</p>"
                self._send_html(self._wrap_page("Partner Feed Error", body), 500)
                return
            self._send_html(self._wrap_page("Partner Feed", body))
            return
        # No source specified – simply confirm authentication
        body = f"<p>Authenticated partner request for {html_escape(partner_name)}.</p>"
        self._send_html(self._wrap_page("Partner Feed", body))

    # ------------------------------------------------------------------
    # Workload capture and replay handlers (Testability scenarios 6.1/6.2)
    # ------------------------------------------------------------------
    def _handle_workload_log_get(self) -> None:
        """Return the recorded request log as JSON inside a <pre> block."""
        import json
        with _REQUEST_LOG_LOCK:
            log_copy = list(_REQUEST_LOG)
        body = "<h1>Recorded Workload</h1><pre>" + html_escape(json.dumps(log_copy, indent=2)) + "</pre>"
        self._send_html(self._wrap_page("Workload Log", body))

    def _handle_workload_clear_get(self) -> None:
        """Clear the recorded workload log."""
        with _REQUEST_LOG_LOCK:
            _REQUEST_LOG.clear()
        body = "<p>Workload log cleared.</p>"
        self._send_html(self._wrap_page("Workload Cleared", body))

    def _handle_workload_replay_get(self) -> None:
        """Replay the recorded workload by invoking local business logic.

        For each recorded request, a corresponding call is made directly
        against the ``RetailApp`` instance held in the session.  Only a
        subset of endpoints are replayed: ``/products`` will call
        ``list_products`` and ``/cart`` will call ``view_cart``.  The
        results are summarised and displayed.  In a full system, this
        handler could reissue HTTP requests or drive the UI to reproduce
        real workloads.
        """
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        with _REQUEST_LOG_LOCK:
            log_copy = list(_REQUEST_LOG)
        summaries: list[str] = []
        for entry in log_copy:
            endpoint = entry.get("endpoint")
            method = entry.get("method")
            if endpoint == "/products" and method == "GET":
                products = app.list_products()
                summaries.append(f"/products -> {len(products)} products")
            elif endpoint == "/cart" and method == "GET":
                items = app.view_cart()
                summaries.append(f"/cart -> {len(items)} items in cart")
        if not summaries:
            summaries.append("No replayable requests recorded.")
        body = "<h1>Workload Replay</h1><pre>" + html_escape("\n".join(summaries)) + "</pre>"
        self._send_html(self._wrap_page("Workload Replay", body))

    # ------------------------------------------------------------------
    # Reseller order handler (Integrability scenario 5.1)
    # ------------------------------------------------------------------
    def _handle_reseller_order_post(self) -> None:
        """Handle POST requests to /reseller/order.

        External resellers can place orders through this endpoint.  The
        request body should contain a JSON object with the keys:

          * ``reseller`` – name of the reseller (adapter name registered
            in ``ResellerAPIGateway``).  If omitted, defaults to "default".
          * ``items`` – a list of order items.  Each item should be a
            dictionary with at minimum ``product_id`` and ``quantity``.

        The handler looks up the adapter via the current session's
        ``RetailApp.reseller_gateway`` and forwards the order.  On
        success a confirmation message is displayed.  If the reseller
        name is unknown or the payload cannot be parsed, a 400
        response is returned.

        Note: This simple implementation does not decrement stock or
        persist the order; it is intended to demonstrate how new
        reseller APIs can be integrated without changing core logic.
        """
        # Read the raw request body
        content_length = 0
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except Exception:
            pass
        raw_data = b""
        if content_length:
            try:
                raw_data = self.rfile.read(content_length)
            except Exception:
                raw_data = b""
        # Attempt to parse JSON payload
        data: dict[str, object] = {}
        if raw_data:
            try:
                data = json.loads(raw_data.decode("utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
        # Fallback to query string parameters if JSON was not provided
        if not data:
            # Parse x-www-form-urlencoded body
            try:
                length = content_length
                body = raw_data.decode("utf-8") if raw_data else ""
                params = urllib.parse.parse_qs(body)
                data = {k: v[0] for k, v in params.items() if v}
            except Exception:
                data = {}
        # Determine reseller name and items
        reseller_name = str(data.get("reseller", "default")).strip().lower()
        items = data.get("items")
        # If items is a JSON string, attempt to parse it
        if isinstance(items, str):
            try:
                items_parsed = json.loads(items)
                if isinstance(items_parsed, list):
                    items = items_parsed
            except Exception:
                pass
        # Validate items is a list
        if not isinstance(items, list):
            items = []
        # Build a generic order payload
        order = {
            "reseller": reseller_name,
            "items": items,
        }
        # Obtain the RetailApp from the session
        app: RetailApp = self.session.get("app")  # type: ignore[assignment]
        if not app:
            # Should not happen; fallback error
            self._send_html(self._wrap_page("Error", "<p>Internal session error.</p>"), 500)
            return
        # Attempt to place the order via the gateway
        try:
            app.reseller_gateway.place_order(reseller_name, order)
            body = f"<p>Order for reseller '{html_escape(reseller_name)}' has been accepted.</p>"
            self._send_html(self._wrap_page("Reseller Order", body), 200)
        except Exception as ex:
            # Unknown adapter or other failure
            body = f"<p>Failed to place reseller order: {html_escape(str(ex))}</p>"
            self._send_html(self._wrap_page("Reseller Order Error", body), 400)


    # -----------------------------------------------------------------
    # Orders and Returns (User-facing)
    # -----------------------------------------------------------------
    def _handle_orders_get(self) -> None:
        """Display the current user's order history with return options."""
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not getattr(app, "_current_user_id", None):
            self._send_html(self._wrap_page("Unauthorized", "<p>You must be logged in to view orders.</p>"), 403)
            return
        user_id = getattr(app, "_current_user_id", None)
        # Query the Sale table for this user
        try:
            from dao import get_request_connection
            conn = get_request_connection()
            rows = conn.execute(
                "SELECT id, timestamp, total, status FROM Sale WHERE user_id = ? ORDER BY id DESC;",
                (user_id,),
            ).fetchall()
        except Exception as e:
            self._send_html(self._wrap_page("Error", f"<p>Error fetching orders: {html_escape(str(e))}</p>"), 500)
            return
        # Build return lookup to determine existing requests
        try:
            existing = {r.sale_id: r for r in app.return_dao.list_returns(user_id)}
        except Exception:
            existing = {}
        rows_html = []
        for r in rows:
            sale_id, ts, total, status = r["id"], r["timestamp"], r["total"], r["status"]
            # Format timestamp (ISO) to something nicer
            ts_str = html_escape(ts)
            # Determine return action/status
            if sale_id in existing:
                rma = existing[sale_id]
                rma_status = rma.status
                return_html = f"{html_escape(rma_status)} (RMA {html_escape(rma.rma_number)})"
            elif status == "Completed":
                # Provide link to request return
                return_html = (
                    f"<form method='get' action='/return-request' style='display:inline'>"
                    f"<input type='hidden' name='sale_id' value='{sale_id}' />"
                    f"<button type='submit'>Request Return</button></form>"
                )
            else:
                return_html = "N/A"
            rows_html.append(
                f"<tr><td>{sale_id}</td><td>{ts_str}</td><td>{total:.2f}</td><td>{html_escape(status)}</td>"
                f"<td>{return_html}</td></tr>"
            )
        body = """
<h1>My Orders</h1>
<table>
  <tr><th>Sale ID</th><th>Timestamp</th><th>Total</th><th>Status</th><th>Return</th></tr>
  {} 
</table>
""".format("\n".join(rows_html))
        self._send_html(self._wrap_page("Orders", body))

    def _handle_return_request_get(self) -> None:
        """Show a form for the user to submit a return request for a sale."""
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not getattr(app, "_current_user_id", None):
            self._send_html(self._wrap_page("Unauthorized", "<p>You must be logged in to request a return.</p>"), 403)
            return
        # Parse sale_id from query string
        try:
            query = urllib.parse.parse_qs(self.path.partition("?")[2], keep_blank_values=True)
            sale_id_str = query.get("sale_id", [None])[0]
            sale_id = int(sale_id_str) if sale_id_str is not None else None
        except Exception:
            sale_id = None
        if not sale_id:
            self._send_html(self._wrap_page("Error", "<p>Missing or invalid sale ID.</p>"), 400)
            return
        # Show form to enter reason
        body = f"""
<h1>Request Return for Sale {sale_id}</h1>
<form method='post' action='/return-request'>
  <input type='hidden' name='sale_id' value='{sale_id}' />
  <label>Reason:<br><textarea name='reason' rows='4' cols='40' required></textarea></label><br>
  <button type='submit'>Submit Return Request</button>
</form>
"""
        self._send_html(self._wrap_page("Request Return", body))

    def _handle_returns_get(self) -> None:
        """Display the current user's return requests and their statuses."""
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not getattr(app, "_current_user_id", None):
            self._send_html(self._wrap_page("Unauthorized", "<p>You must be logged in to view returns.</p>"), 403)
            return
        user_id = getattr(app, "_current_user_id", None)
        try:
            requests = app.return_dao.list_returns(user_id)
        except Exception as e:
            self._send_html(self._wrap_page("Error", f"<p>Error fetching returns: {html_escape(str(e))}</p>"), 500)
            return
        rows_html = []
        for r in requests:
            # Format timestamps; handle None
            req_ts = html_escape(r.request_timestamp)
            res_ts = html_escape(r.resolution_timestamp) if r.resolution_timestamp else "-"
            refund_ref = html_escape(r.refund_reference) if r.refund_reference else "-"
            rows_html.append(
                f"<tr><td>{r.id}</td><td>{html_escape(r.rma_number)}</td><td>{r.sale_id}</td><td>{html_escape(r.reason)}</td>"
                f"<td>{html_escape(r.status)}</td><td>{req_ts}</td><td>{res_ts}</td><td>{refund_ref}</td></tr>"
            )
        body = """
<h1>My Return Requests</h1>
<table>
  <tr><th>ID</th><th>RMA Number</th><th>Sale ID</th><th>Reason</th><th>Status</th><th>Requested</th><th>Resolved</th><th>Refund Ref</th></tr>
  {} 
</table>
""".format("\n".join(rows_html))
        self._send_html(self._wrap_page("Returns", body))

    # -----------------------------------------------------------------
    # Returns (Admin-facing)
    # -----------------------------------------------------------------
    def _handle_admin_returns_get(self) -> None:
        """Display all return requests for admin processing."""
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to access this page.</p>"), 403)
            return
        try:
            requests = app.return_dao.list_returns()
        except Exception as e:
            self._send_html(self._wrap_page("Error", f"<p>Error fetching returns: {html_escape(str(e))}</p>"), 500)
            return
        rows_html = []
        for r in requests:
            req_ts = html_escape(r.request_timestamp)
            res_ts = html_escape(r.resolution_timestamp) if r.resolution_timestamp else "-"
            refund_ref = html_escape(r.refund_reference) if r.refund_reference else "-"
            actions = ""
            if r.status == "Pending":
                actions = (
                    f"<form method='post' action='/admin/returns/{r.id}/approve' style='display:inline'>"
                    f"<button type='submit'>Approve</button></form> "
                    f"<form method='post' action='/admin/returns/{r.id}/reject' style='display:inline'>"
                    f"<input type='text' name='reason' placeholder='Reason' required style='width:8rem' /> "
                    f"<button type='submit'>Reject</button></form>"
                )
            rows_html.append(
                f"<tr><td>{r.id}</td><td>{html_escape(r.rma_number)}</td><td>{r.sale_id}</td><td>{html_escape(r.reason)}</td>"
                f"<td>{html_escape(r.status)}</td><td>{req_ts}</td><td>{res_ts}</td><td>{refund_ref}</td><td>{actions}</td></tr>"
            )
        body = """
<h1>All Return Requests</h1>
<table>
  <tr><th>ID</th><th>RMA</th><th>Sale ID</th><th>Reason</th><th>Status</th><th>Requested</th><th>Resolved</th><th>Refund Ref</th><th>Actions</th></tr>
  {} 
</table>
""".format("\n".join(rows_html))
        self._send_html(self._wrap_page("Admin Returns", body))

    def _handle_admin_return_action_post(self, rma_id: int, approve: bool) -> None:
        """Handle admin approval or rejection of a return."""
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not app.current_user_is_admin(username):  # type: ignore[arg-type]
            self._send_html(self._wrap_page("Unauthorized", "<p>You do not have permission to perform this action.</p>"), 403)
            return
        # Parse POST data for rejection reason if needed
        reason = None
        if not approve:
            params = self._parse_post_data()
            reason = params.get("reason") or "Rejected"
        if approve:
            ok, msg = app.approve_return(rma_id)
        else:
            ok, msg = app.reject_return(rma_id, reason or "Rejected")
        status = "ok" if ok else "err"
        # After processing, redirect back to admin returns with flash message
        body = f"<p class='{status}'>{html_escape(msg)}</p><p><a href='/admin/returns'>Back to Returns</a></p>"
        self._send_html(self._wrap_page("Return Processing", body))

    # -----------------------------------------------------------------
    # Handle return request submission (POST)
    # -----------------------------------------------------------------
    def _handle_return_request_post(self) -> None:
        """Submit a return request for a sale."""
        app: RetailApp = self.session["app"]  # type: ignore[assignment]
        username = self.session.get("username")
        if not username or not getattr(app, "_current_user_id", None):
            self._send_html(self._wrap_page("Unauthorized", "<p>You must be logged in to submit a return request.</p>"), 403)
            return
        params = self._parse_post_data()
        sale_id_str = params.get("sale_id")
        reason = params.get("reason", "").strip()
        try:
            sale_id = int(sale_id_str) if sale_id_str else None
        except ValueError:
            sale_id = None
        if not sale_id or not reason:
            self._send_html(self._wrap_page("Error", "<p>Missing sale ID or reason.</p>"), 400)
            return
        ok, msg = app.request_return(sale_id, reason)
        status = "ok" if ok else "err"
        body = f"<p class='{status}'>{html_escape(msg)}</p><p><a href='/orders'>Back to Orders</a></p>"
        self._send_html(self._wrap_page("Return Requested", body))

    # -----------------------------------------------------------------
    # Simple metrics dashboard
    # -----------------------------------------------------------------
    def _handle_dashboard_get(self) -> None:
        """Display a simple dashboard summarizing key metrics."""
        # Generate Prometheus-style metrics text and embed in page
        try:
            metrics_text = generate_metrics_text().decode("utf-8")
        except Exception as e:
            metrics_text = f"Error generating metrics: {str(e)}"
        body = """
<h1>Metrics Dashboard</h1>
<p>This dashboard displays raw metrics for observability and monitoring purposes. Use a Prometheus-compatible tool to scrape <code>/metrics</code> endpoint.</p>
<pre style='background:#f7f7f7;padding:1rem;border:1px solid #ddd;overflow-x:auto'>{}</pre>
""".format(html_escape(metrics_text))
        self._send_html(self._wrap_page("Metrics Dashboard", body))


def run_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the threaded HTTP server and serve requests forever."""
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, RetailHTTPRequestHandler)
    print(f"Serving on http://{host}:{port} (Press CTRL+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.server_close()


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        port = 8000

    _warmup_db()
    
    run_server(host, port)


if __name__ == "__main__":
    main()
