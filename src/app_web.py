# src/app_web.py
from __future__ import annotations

import os
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, g, abort
)

from app import RetailApp

def db_path_from_here() -> str:
    """Resolve ../db/retail.db relative to this file (src/)."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(base_dir, "..", "db", "retail.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", "dev-secret")
app.config["DB_PATH"] = db_path_from_here()

# Single instance of business logic
retail = RetailApp()

# Close per-request DB on teardown
@app.teardown_appcontext
def close_db(exc):
    db = getattr(g, "_retail_db_conn", None)
    if db is not None:
        db.close()

# --- Helpers ---
def current_user() -> str | None:
    return session.get("username")

def require_login():
    """Redirect to login if not authenticated."""
    if not current_user():
        return redirect(url_for("login"))

# --- Context processor to inject admin flag ---
@app.context_processor
def inject_is_admin():
    """
    Inject a boolean 'is_admin' into all templates based on the logged-in user.
    If an error occurs (e.g. missing column), returns False.
    """
    u = current_user()
    try:
        return {"is_admin": (retail.current_user_is_admin(u) if u else False)}
    except Exception:
        return {"is_admin": False}

# --- Authentication routes ---
@app.get("/register")
def register():
    return render_template("register.html")

@app.post("/register")
def register_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("register"))
    ok, msg = retail.register(username, password)
    if not ok:
        flash(msg, "error")
        return redirect(url_for("register"))
    flash("Registered. Please log in.", "success")
    return redirect(url_for("login"))

@app.get("/login")
def login():
    return render_template("login.html")

@app.post("/login")
def login_post():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("login"))
    if retail.login(username, password):
        session["username"] = username
        # Cache admin flag in session for convenience (optional)
        session["is_admin"] = retail.current_user_is_admin(username)
        flash(f"Welcome, {username}.", "success")
        return redirect(url_for("products"))
    flash("Invalid credentials.", "error")
    return redirect(url_for("login"))

@app.get("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))

# --- Admin UI ---
@app.get("/admin/products")
def admin_products():
    if not current_user():
        return require_login()
    if not retail.current_user_is_admin(current_user()):
        return abort(403)
    products = retail.list_products()
    return render_template("admin_products.html", products=products)

@app.get("/admin/product/<int:product_id>/edit")
def admin_edit_product(product_id: int):
    if not current_user():
        return require_login()
    if not retail.current_user_is_admin(current_user()):
        return abort(403)
    p = retail.product_dao.get_product(product_id)
    if not p:
        flash("Product not found.", "error")
        return redirect(url_for("admin_products"))
    return render_template("admin_edit_product.html", product=p)

@app.post("/admin/product/<int:product_id>/edit")
def admin_edit_product_post(product_id: int):
    if not current_user():
        return require_login()
    if not retail.current_user_is_admin(current_user()):
        return abort(403)
    try:
        new_name = (request.form.get("name") or "").strip()
        new_price = float(request.form.get("price") or "0")
        new_stock = int(request.form.get("stock") or "0")
    except (TypeError, ValueError):
        flash("Invalid input values.", "error")
        return redirect(url_for("admin_edit_product", product_id=product_id))
    p = retail.product_dao.get_product(product_id)
    if not p:
        flash("Product not found.", "error")
        return redirect(url_for("admin_products"))
    # Apply updates
    retail.product_dao.update_name_price(product_id, new_name or p.name, new_price)
    retail.product_dao.update_stock(product_id, new_stock)
    flash("Product updated.", "success")
    return redirect(url_for("admin_products"))

@app.get("/admin/product/new")
def admin_new_product():
    """Show form to create a new product (admin only)."""
    if not current_user():
        return require_login()
    if not retail.current_user_is_admin(current_user()):
        return abort(403)
    return render_template("admin_new_product.html")

from sqlite3 import IntegrityError

@app.post("/admin/product/new")
def admin_new_product_post():
    if not current_user():
        return require_login()
    if not retail.current_user_is_admin(current_user()):
        return abort(403)

    name = (request.form.get("name") or "").strip()
    price_raw = (request.form.get("price") or "").strip()
    stock_raw = (request.form.get("stock") or "").strip()

    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin_new_product"))
    try:
        price = float(price_raw)
        stock = int(stock_raw)
    except ValueError:
        flash("Price must be a number and stock must be an integer.", "error")
        return redirect(url_for("admin_new_product"))

    try:
        pid = retail.product_dao.add_product(name=name, price=price, stock=stock)
    except IntegrityError:
        flash("A product with this name already exists.", "error")
        return redirect(url_for("admin_new_product"))

    flash(f"Product #{pid} created.", "success")
    return redirect(url_for("admin_products"))

# --- Delete product route ---
@app.post("/admin/product/<int:product_id>/delete")
def admin_delete_product(product_id: int):
    """Remove a product permanently (admin only)."""
    # Must be logged in and have admin privileges
    if not current_user():
        return require_login()
    if not retail.current_user_is_admin(current_user()):
        return abort(403)
    # Verify the product exists
    product = retail.product_dao.get_product(product_id)
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("admin_products"))
    try:
        # Attempt deletion
        retail.product_dao.delete_product(product_id)
        flash("Product deleted.", "success")
    except IntegrityError:
        # Foreign key violation: there are existing sales referencing this product
        flash(
            "Cannot delete product because it is referenced by existing sales.",
            "error",
        )
    return redirect(url_for("admin_products"))


# --- Catalogue & cart routes ---
@app.get("/")
def home():
    return redirect(url_for("products"))

@app.get("/products")
def products():
    if not current_user():
        return require_login()
    catalog = retail.list_products()
    return render_template("products.html", products=catalog)

@app.post("/cart/add")
def cart_add():
    if not current_user():
        return require_login()
    try:
        product_id = int(request.form.get("product_id"))
        qty = int(request.form.get("quantity"))
    except (TypeError, ValueError):
        flash("Invalid product/quantity.", "error")
        return redirect(url_for("products"))
    ok, msg = retail.add_to_cart(product_id, qty)
    if ok:
        flash(msg, "success")
        return redirect(url_for("cart"))
    if msg.startswith("Only "):
        # Parse available quantity from message
        try:
            available = int(msg.split()[1])
        except Exception:
            available = 0
        product = retail.product_dao.get_product(product_id)
        return render_template(
            "stock_choice.html",
            product=product,
            requested_qty=qty,
            available=available,
        )
    flash(msg, "error")
    return redirect(url_for("products"))

@app.post("/cart/stock_choice")
def cart_stock_choice():
    """Handle user choices for insufficient stock."""
    if not current_user():
        return require_login()
    product_id = int(request.form.get("product_id"))
    requested_qty = int(request.form.get("requested_qty"))
    available = int(request.form.get("available"))
    choice = request.form.get("choice")  # reduce/remove/cancel

    if choice == "reduce":
        if available > 0:
            retail.remove_from_cart(product_id)
            ok, msg = retail.add_to_cart(product_id, available)
            flash(msg if ok else "Unable to adjust quantity.", "info")
        else:
            retail.remove_from_cart(product_id)
            flash("No stock available; item removed.", "info")
        return redirect(url_for("cart"))

    elif choice == "remove":
        retail.remove_from_cart(product_id)
        flash("Item removed from cart.", "info")
        return redirect(url_for("cart"))

    elif choice == "cancel":
        retail.clear_cart()
        flash("Sale cancelled; cart cleared.", "warning")
        return redirect(url_for("products"))

    flash("Unknown choice.", "error")
    return redirect(url_for("products"))

@app.get("/cart")
def cart():
    if not current_user():
        return require_login()

    raw_items = retail.view_cart()  # list[CartLine]
    enriched = []
    for it in raw_items:
        p = retail.product_dao.get_product(it.product_id)
        enriched.append({
            "product_id": it.product_id,
            "name": p.name if p else f"#{it.product_id}",
            "qty": it.qty,
            "unit_price": it.unit_price,
            "line_total": it.unit_price * it.qty,
        })

    totals = retail.compute_cart_totals()
    return render_template("cart.html", items=enriched, totals=totals)

@app.post("/cart/remove")
def cart_remove():
    if not current_user():
        return require_login()
    product_id = int(request.form.get("product_id"))
    retail.remove_from_cart(product_id)
    flash("Item removed.", "info")
    return redirect(url_for("cart"))


@app.post("/cart/clear")
def cart_clear():
    if not current_user():
        return require_login()
    retail.clear_cart()
    flash("Cart cleared.", "info")
    return redirect(url_for("cart"))


# ---------------------------- Checkout / Payment ----------------------------
@app.get("/checkout")
def checkout():
    if not current_user():
        return require_login()
    items = retail.view_cart()
    if not items:
        flash("Cart is empty.", "error")
        return redirect(url_for("products"))
    totals = retail.compute_cart_totals()
    return render_template("checkout.html", totals=totals)


@app.post("/checkout")
def checkout_post():
    if not current_user():
        return require_login()
    method = request.form.get("payment_method", "Card")
    ok, res = retail.checkout(method)
    if not ok:
        # Payment failed; show reason and give retry / cancel options
        return render_template("payment_failed.html", reason=res)
    # Success -> render receipt text
    return render_template("receipt.html", text_receipt=res)


if __name__ == "__main__":
    # Run:  FLASK_DEBUG=1 python src/app_web.py
    # If port 5000 is taken by Control Center on macOS, try -p 5001
    app.run(host="0.0.0.0", port=5000, debug=True)
