"""
Simple HTTP server for the retail application.

This module provides a minimal web interface built entirely on
Python's standard library.  It replaces the original Flask-based
implementation but preserves the same URL structure and
functionality where practical.  No external dependencies are
required.

The server exposes routes for user registration, login and logout,
browsing the product catalogue, managing a shopping cart, checking
out with a mock payment service, and basic admin operations for
products.  Because there is no session management library, a
single global session is used: only one user can be logged in at
a time, and the cart is shared across all requests.

Run the server with:

```
python src/app_web.py
```

It will listen on ``localhost:8000`` by default.  Use CTRL+C to stop
the server.

This file must remain at the same location to preserve the project
structure, even though the implementation has changed.
"""

from __future__ import annotations

import html
import os
import socketserver
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Tuple, Optional

from app import RetailApp

try:
    from sqlite3 import IntegrityError
except ImportError:
    IntegrityError = Exception  # fallback, should not happen


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

# Single instance of the business logic.  This encapsulates all
# operations on users, products, sales and payments.  Its `_cart` and
# `_current_user_id` attributes are used to simulate per-user state.
retail = RetailApp()

# Name of the currently logged in user, or None.  Only one user may
# be logged in at a time.  This mirrors the `_current_user_id` stored
# on the RetailApp instance.
current_username: Optional[str] = None


def db_path_from_here() -> str:
    """
    Resolve ``../db/retail.db`` relative to this file (``src/``).

    This helper is retained for compatibility with the original
    implementation.  The returned path can be used to set the
    ``RETAIL_DB_PATH`` environment variable before starting the
    server.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_dir, "..", "db", "retail.db"))


def html_escape(s: str) -> str:
    """Escape text for inclusion in HTML."""
    return html.escape(s, quote=True)


class RetailHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler implementing the retail web interface."""

    def _send_html(self, content: str, status: int = 200) -> None:
        """Send an HTML response with the given status code."""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def _render_nav(self) -> str:
        """Return HTML for the top navigation bar."""
        global current_username
        parts = [
            '<nav>',
            '<a href="/products">Products</a>',
            '<a href="/cart">Cart</a>',
        ]
        if current_username:
            # Show admin link if the current user has admin rights
            is_admin = retail.current_user_is_admin(current_username)
            if is_admin:
                parts.append('<a href="/admin/products">Admin</a>')
            parts.append(f'<span>Hi, {html_escape(current_username)}</span>')
            parts.append('<a href="/logout">Logout</a>')
        else:
            parts.append('<a href="/login">Login</a>')
            parts.append('<a href="/register">Register</a>')
        parts.append('</nav>')
        return ''.join(parts)

    def _wrap_page(self, title: str, body: str) -> str:
        """Wrap the given body HTML in a complete document with a nav bar."""
        return f"""
<!doctype html>
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
    </style>
</head>
<body>
{self._render_nav()}
<main>
{body}
</main>
</body>
</html>
"""

    def _parse_post_data(self) -> Dict[str, str]:
        """Parse and return form data from a POST request."""
        length = int(self.headers.get("Content-Length", 0))
        data = self.rfile.read(length).decode("utf-8")
        params = urllib.parse.parse_qs(data, keep_blank_values=True)
        # Convert single-element lists to values
        return {k: v[0] for k, v in params.items()}

    # ---------------------------------------------------------------------
    # Route handlers
    # ---------------------------------------------------------------------
    def do_GET(self) -> None:
        global current_username
        path, _, query_string = self.path.partition('?')
        # Route dispatch
        if path == '/' or path == '':
            # Redirect to /products
            self.send_response(302)
            self.send_header('Location', '/products')
            self.end_headers()
            return
        if path == '/register':
            self._handle_register_get()
            return
        if path == '/login':
            self._handle_login_get()
            return
        if path == '/logout':
            self._handle_logout_get()
            return
        if path == '/products':
            self._handle_products_get()
            return
        if path.startswith('/admin/product/') and path.endswith('/edit'):
            # e.g. /admin/product/3/edit
            parts = path.strip('/').split('/')
            if len(parts) == 4:
                _, _, pid_str, _ = parts
                try:
                    pid = int(pid_str)
                except ValueError:
                    self._send_html(self._wrap_page("Error", "Invalid product ID."), 404)
                    return
                self._handle_admin_product_edit_get(pid)
                return
        if path == '/admin/products':
            self._handle_admin_products_get()
            return
        if path == '/admin/product/new':
            self._handle_admin_new_product_get()
            return
        if path == '/cart':
            self._handle_cart_get()
            return
        if path == '/checkout':
            self._handle_checkout_get()
            return
        # Unknown path
        self._send_html(self._wrap_page("404 Not Found", "<p>Page not found.</p>"), 404)

    def do_POST(self) -> None:
        global current_username
        path = self.path
        # Dispatch based on path
        if path == '/register':
            self._handle_register_post()
            return
        if path == '/login':
            self._handle_login_post()
            return
        if path == '/admin/product/new':
            self._handle_admin_new_product_post()
            return
        if path.startswith('/admin/product/') and path.endswith('/edit'):
            parts = path.strip('/').split('/')
            if len(parts) == 4:
                _, _, pid_str, _ = parts
                try:
                    pid = int(pid_str)
                except ValueError:
                    self._send_html(self._wrap_page("Error", "Invalid product ID."), 404)
                    return
                self._handle_admin_product_edit_post(pid)
                return
        if path.startswith('/admin/product/') and path.endswith('/delete'):
            parts = path.strip('/').split('/')
            if len(parts) == 4:
                _, _, pid_str, _ = parts
                try:
                    pid = int(pid_str)
                except ValueError:
                    self._send_html(self._wrap_page("Error", "Invalid product ID."), 404)
                    return
                self._handle_admin_product_delete_post(pid)
                return
        if path == '/cart/add':
            self._handle_cart_add_post()
            return
        if path == '/cart/remove':
            self._handle_cart_remove_post()
            return
        if path == '/cart/clear':
            self._handle_cart_clear_post()
            return
        if path == '/checkout':
            self._handle_checkout_post()
            return
        # Unknown POST path
        self._send_html(self._wrap_page("404 Not Found", "<p>Page not found.</p>"), 404)

    # ---------------------------------------------------------------------
    # GET handlers
    # ---------------------------------------------------------------------
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
        global current_username
        if current_username:
            # Clear cart and log out in the RetailApp
            retail.clear_cart()
            retail._current_user_id = None
            current_username = None
        body = "<p>You have been logged out.</p>\n<p><a href=\"/products\">Continue shopping</a>.</p>"
        self._send_html(self._wrap_page("Logged Out", body))

    def _handle_products_get(self) -> None:
        # Show catalogue with add-to-cart forms
        products = retail.list_products()
        rows = []
        for p in products:
            # Each product row with a form to add to cart
            row = f"<tr><td>{p.id}</td><td>{html_escape(p.name)}</td><td>{p.price:.2f}</td><td>{p.stock}</td>"
            row += "<td>"
            row += f"<form method='post' action='/cart/add' style='display:inline'>"
            row += f"<input type='hidden' name='product_id' value='{p.id}' />"
            row += "<input type='number' name='quantity' min='1' value='1' style='width:4rem' />"
            row += "<button type='submit'>Add</button></form>"
            row += "</td></tr>"
            rows.append(row)
        table_html = """
<h1>Products</h1>
<table>
    <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th>Add to Cart</th></tr>
    {rows}
</table>
""".format(rows="\n".join(rows))
        # Admin controls
        admin_html = ""
        if current_username and retail.current_user_is_admin(current_username):
            admin_html = "<p><a href='/admin/product/new'>Add New Product</a></p>"
        body = table_html + admin_html
        self._send_html(self._wrap_page("Products", body))

    def _handle_admin_products_get(self) -> None:
        global current_username
        # Only allow access if current user is admin
        if not current_username or not retail.current_user_is_admin(current_username):
            body = "<p>You do not have permission to access this page.</p>"
            self._send_html(self._wrap_page("Unauthorized", body), 403)
            return
        products = retail.list_products()
        rows = []
        for p in products:
            row = (
                f"<tr><td>{p.id}</td><td>{html_escape(p.name)}</td><td>{p.price:.2f}</td><td>{p.stock}</td>"
                f"<td><a href='/admin/product/{p.id}/edit'>Edit</a></td>"
                f"<td><form method='post' action='/admin/product/{p.id}/delete' style='display:inline'>"
                f"<button type='submit'>Delete</button></form></td>"
                "</tr>"
            )
            rows.append(row)
        table_html = """
<h1>Admin Products</h1>
<p><a href='/admin/product/new'>Add New Product</a></p>
<table>
    <tr><th>ID</th><th>Name</th><th>Price</th><th>Stock</th><th></th><th></th></tr>
    {rows}
</table>
""".format(rows="\n".join(rows))
        self._send_html(self._wrap_page("Admin Products", table_html))

    def _handle_admin_new_product_get(self) -> None:
        global current_username
        if not current_username or not retail.current_user_is_admin(current_username):
            body = "<p>You do not have permission to access this page.</p>"
            self._send_html(self._wrap_page("Unauthorized", body), 403)
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
        global current_username
        if not current_username or not retail.current_user_is_admin(current_username):
            body = "<p>You do not have permission to access this page.</p>"
            self._send_html(self._wrap_page("Unauthorized", body), 403)
            return
        p = retail.product_dao.get_product(product_id)
        if not p:
            body = "<p>Product not found.</p>"
            self._send_html(self._wrap_page("Not Found", body), 404)
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
        # Show items in the cart
        items = retail.view_cart()
        if not current_username:
            body = "<p>You must be logged in to view your cart.</p>"
            self._send_html(self._wrap_page("Cart", body), 403)
            return
        if not items:
            body = "<p>Your cart is empty.</p>"
            self._send_html(self._wrap_page("Cart", body))
            return
        rows = []
        for it in items:
            p = retail.product_dao.get_product(it.product_id)
            name = p.name if p else f"#{it.product_id}"
            row = (
                f"<tr><td>{it.product_id}</td><td>{html_escape(name)}</td><td>{it.qty}</td>"
                f"<td>{it.unit_price:.2f}</td><td>{it.unit_price * it.qty:.2f}</td>"
                f"<td><form method='post' action='/cart/remove' style='display:inline'>"
                f"<input type='hidden' name='product_id' value='{it.product_id}' />"
                f"<button type='submit'>Remove</button></form></td>"
                "</tr>"
            )
            rows.append(row)
        totals = retail.compute_cart_totals()
        body = f"""
<h1>Your Cart</h1>
<table>
    <tr><th>Product ID</th><th>Name</th><th>Qty</th><th>Unit Price</th><th>Total</th><th></th></tr>
    {rows}
</table>
<p>Subtotal: {totals.subtotal:.2f} &nbsp; Total: {totals.total:.2f}</p>
<form method='post' action='/cart/clear'>
    <button type='submit'>Clear Cart</button>
</form>
<p><a href='/checkout'>Proceed to Checkout</a></p>
""".format(rows="\n".join(rows))
        self._send_html(self._wrap_page("Cart", body))

    def _handle_checkout_get(self) -> None:
        if not current_username:
            body = "<p>You must be logged in to checkout.</p>"
            self._send_html(self._wrap_page("Checkout", body), 403)
            return
        items = retail.view_cart()
        if not items:
            body = "<p>Your cart is empty.</p>"
            self._send_html(self._wrap_page("Checkout", body))
            return
        totals = retail.compute_cart_totals()
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

    # ---------------------------------------------------------------------
    # POST handlers
    # ---------------------------------------------------------------------
    def _handle_register_post(self) -> None:
        params = self._parse_post_data()
        username = params.get('username', '').strip()
        password = params.get('password', '').strip()
        if not username or not password:
            body = "<p>Username and password are required.</p>"
            self._send_html(self._wrap_page("Register", body))
            return
        ok, msg = retail.register(username, password)
        body = f"<p>{html_escape(msg)}</p><p><a href='/login'>Go to login</a></p>" if ok else f"<p>{html_escape(msg)}</p><p><a href='/register'>Try again</a></p>"
        self._send_html(self._wrap_page("Register", body))

    def _handle_login_post(self) -> None:
        global current_username
        params = self._parse_post_data()
        username = params.get('username', '').strip()
        password = params.get('password', '').strip()
        if not username or not password:
            body = "<p>Username and password are required.</p>"
            self._send_html(self._wrap_page("Login", body))
            return
        if retail.login(username, password):
            current_username = username
            body = f"<p>Welcome, {html_escape(username)}.</p><p><a href='/products'>Continue shopping</a></p>"
            self._send_html(self._wrap_page("Login", body))
        else:
            body = "<p>Invalid credentials.</p><p><a href='/login'>Try again</a></p>"
            self._send_html(self._wrap_page("Login", body))

    def _handle_admin_new_product_post(self) -> None:
        global current_username
        if not current_username or not retail.current_user_is_admin(current_username):
            body = "<p>You do not have permission to perform this action.</p>"
            self._send_html(self._wrap_page("Unauthorized", body), 403)
            return
        params = self._parse_post_data()
        name = params.get('name', '').strip()
        price_raw = params.get('price', '').strip()
        stock_raw = params.get('stock', '').strip()
        if not name:
            body = "<p>Name is required.</p><p><a href='/admin/product/new'>Back</a></p>"
            self._send_html(self._wrap_page("Error", body))
            return
        try:
            price = float(price_raw)
            stock = int(stock_raw)
        except ValueError:
            body = "<p>Invalid price or stock.</p><p><a href='/admin/product/new'>Back</a></p>"
            self._send_html(self._wrap_page("Error", body))
            return
        try:
            pid = retail.product_dao.add_product(name, price, stock)
            body = f"<p>Product #{pid} created.</p><p><a href='/admin/products'>Back to list</a></p>"
        except IntegrityError:
            body = "<p>A product with this name already exists.</p><p><a href='/admin/product/new'>Back</a></p>"
        self._send_html(self._wrap_page("New Product", body))

    def _handle_admin_product_edit_post(self, product_id: int) -> None:
        global current_username
        if not current_username or not retail.current_user_is_admin(current_username):
            body = "<p>You do not have permission to perform this action.</p>"
            self._send_html(self._wrap_page("Unauthorized", body), 403)
            return
        params = self._parse_post_data()
        name = params.get('name', '').strip()
        price_raw = params.get('price', '').strip()
        stock_raw = params.get('stock', '').strip()
        try:
            price = float(price_raw)
            stock = int(stock_raw)
        except ValueError:
            body = f"<p>Invalid input values.</p><p><a href='/admin/product/{product_id}/edit'>Back</a></p>"
            self._send_html(self._wrap_page("Error", body))
            return
        p = retail.product_dao.get_product(product_id)
        if not p:
            body = "<p>Product not found.</p><p><a href='/admin/products'>Back</a></p>"
            self._send_html(self._wrap_page("Error", body), 404)
            return
        retail.product_dao.update_name_price(product_id, name or p.name, price)
        retail.product_dao.update_stock(product_id, stock)
        body = f"<p>Product updated.</p><p><a href='/admin/products'>Back to list</a></p>"
        self._send_html(self._wrap_page("Edit Product", body))

    def _handle_admin_product_delete_post(self, product_id: int) -> None:
        global current_username
        if not current_username or not retail.current_user_is_admin(current_username):
            body = "<p>You do not have permission to perform this action.</p>"
            self._send_html(self._wrap_page("Unauthorized", body), 403)
            return
        p = retail.product_dao.get_product(product_id)
        if not p:
            body = "<p>Product not found.</p><p><a href='/admin/products'>Back</a></p>"
            self._send_html(self._wrap_page("Error", body), 404)
            return
        try:
            retail.product_dao.delete_product(product_id)
            body = "<p>Product deleted.</p><p><a href='/admin/products'>Back to list</a></p>"
        except IntegrityError:
            body = "<p>Cannot delete product because it is referenced by existing sales.</p><p><a href='/admin/products'>Back</a></p>"
        self._send_html(self._wrap_page("Delete Product", body))

    def _handle_cart_add_post(self) -> None:
        global current_username
        params = self._parse_post_data()
        try:
            product_id = int(params.get('product_id', '0'))
            qty = int(params.get('quantity', '0'))
        except ValueError:
            body = "<p>Invalid product or quantity.</p><p><a href='/products'>Back to products</a></p>"
            self._send_html(self._wrap_page("Error", body))
            return
        if not current_username:
            body = "<p>You must be logged in to add items to your cart.</p><p><a href='/login'>Login</a></p>"
            self._send_html(self._wrap_page("Error", body))
            return
        ok, msg = retail.add_to_cart(product_id, qty)
        body = f"<p>{html_escape(msg)}</p><p><a href='/products'>Back to products</a> | <a href='/cart'>View cart</a></p>"
        self._send_html(self._wrap_page("Add to Cart", body))

    def _handle_cart_remove_post(self) -> None:
        params = self._parse_post_data()
        try:
            product_id = int(params.get('product_id', '0'))
        except ValueError:
            body = "<p>Invalid product.</p><p><a href='/cart'>Back to cart</a></p>"
            self._send_html(self._wrap_page("Error", body))
            return
        retail.remove_from_cart(product_id)
        body = "<p>Item removed.</p><p><a href='/cart'>Back to cart</a></p>"
        self._send_html(self._wrap_page("Remove Item", body))

    def _handle_cart_clear_post(self) -> None:
        retail.clear_cart()
        body = "<p>Cart cleared.</p><p><a href='/products'>Continue shopping</a></p>"
        self._send_html(self._wrap_page("Clear Cart", body))

    def _handle_checkout_post(self) -> None:
        global current_username
        params = self._parse_post_data()
        method = params.get('payment_method', 'Card')
        if not current_username:
            body = "<p>You must be logged in to checkout.</p><p><a href='/login'>Login</a></p>"
            self._send_html(self._wrap_page("Error", body), 403)
            return
        ok, res = retail.checkout(method)
        if ok:
            # Show receipt and clear cart
            receipt_html = html_escape(res).replace('\n', '<br>')
            body = f"<h1>Thank you for your purchase!</h1><p>{receipt_html}</p><p><a href='/products'>Continue shopping</a></p>"
            self._send_html(self._wrap_page("Receipt", body))
        else:
            body = f"<p>Payment failed: {html_escape(res)}</p><p><a href='/cart'>Back to cart</a></p>"
            self._send_html(self._wrap_page("Payment Failed", body))


def run_server(host: str = "localhost", port: int = 8000) -> None:
    """Start the HTTP server and serve requests forever."""
    server_address = (host, port)
    httpd = HTTPServer(server_address, RetailHTTPRequestHandler)
    print(f"Serving on http://{host}:{port} (Press CTRL+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        httpd.server_close()


def main() -> None:
    """Entry point when running this module as a script."""
    # Optionally honour the PORT environment variable
    host = os.environ.get("HOST", "localhost")
    port_str = os.environ.get("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000
    run_server(host, port)


if __name__ == "__main__":
    main()