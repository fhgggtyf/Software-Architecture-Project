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
from http import cookies
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional

from app import RetailApp

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

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        if self.set_cookie_header:
            self.set_cookie_header()
        self.end_headers()

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
            parts.append(f"<span>Hi, {html_escape(str(username))}</span>")
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
        self.sid, self.session, self.set_cookie_header = _get_or_create_session(self)

    def do_GET(self) -> None:
        self._begin_request()
        path, _, _ = self.path.partition("?")

        if path == "/" or path == "":
            self._redirect("/products")
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
        if path == "/checkout":
            self._handle_checkout_post()
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
        for p in products:
            row = (
                f"<tr><td>{p.id}</td><td>{html_escape(p.name)}</td><td>{p.price:.2f}</td><td>{p.stock}</td>"
                "<td>"
                f"<form method='post' action='/cart/add' style='display:inline'>"
                f"<input type='hidden' name='product_id' value='{p.id}' />"
                "<input type='number' name='quantity' min='1' value='1' style='width:4rem' />"
                "<button type='submit'>Add</button></form>"
                "</td></tr>"
            )
            rows.append(row)
        table_html = f"""
<h1>Products</h1>
<table>
  <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th>Add to Cart</th></tr>
  {'\n'.join(rows)}
</table>
"""
        username = self.session.get("username")
        admin_html = ""
        if username and app.current_user_is_admin(username):  # type: ignore[arg-type]
            admin_html = "<p><a href='/admin/product/new'>Add New Product</a></p>"
        self._send_html(self._wrap_page("Products", table_html + admin_html))

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
        table_html = f"""
<h1>Admin Products</h1>
<p><a href='/admin/product/new'>Add New Product</a></p>
<table>
  <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th></th><th></th></tr>
  {'\n'.join(rows)}
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
        body = f"""
<h1>Your Cart</h1>
<table>
  <tr><th>Product ID</th><th>Name</th><th>Qty</th><th>Unit Price</th><th>Total</th><th></th></tr>
  {'\n'.join(rows)}
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
            receipt_html = html_escape(res).replace("\n", "<br>")
            self._send_html(self._wrap_page("Receipt", f"<h1>Thank you for your purchase!</h1><p>{receipt_html}</p><p><a href='/products'>Continue shopping</a></p>"))
        else:
            self._send_html(self._wrap_page("Payment Failed", f"<p>Payment failed: {html_escape(res)}</p><p><a href='/cart'>Back to cart</a></p>"))


def run_server(host: str = "localhost", port: int = 8000) -> None:
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
    host = os.environ.get("HOST", "localhost")
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        port = 8000

    _warmup_db()
    
    run_server(host, port)


if __name__ == "__main__":
    main()
