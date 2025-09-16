"""
Command‑line interface for the minimal retail application.

This script wires the ``RetailApp`` class into an interactive CLI
loop.  It prompts the user for input, invokes methods on the
``RetailApp`` instance and prints results.  Separating the CLI from
the business logic keeps the latter testable and free from I/O code.
"""

import sys
from app import RetailApp


def interactive_cli() -> None:
    """Provide a simple command‑line interface to interact with the retail app."""
    app = RetailApp()

    def print_menu() -> None:
        print("\n-- Minimal Retail Application --")
        print("1. Register")
        print("2. Login")
        print("3. List Products")
        print("4. Add Product to Cart")
        print("5. View Cart")
        print("6. Checkout")
        print("7. Add New Product (Admin)*)")
        print("0. Exit")
        print("\n*) For demonstration purposes any logged‑in user can add products.")

    while True:
        print_menu()
        choice = input("Select an option: ").strip()
        if choice == "1":
            username = input("Username: ").strip()
            password = input("Password: ").strip()
            if app.register(username, password):
                print("Registration successful. You can now log in.")
            else:
                print("Username already exists. Please choose another.")
        elif choice == "2":
            username = input("Username: ").strip()
            password = input("Password: ").strip()
            if app.login(username, password):
                print(f"Welcome, {username}!")
            else:
                print("Invalid credentials.")
        elif choice == "3":
            products = app.list_products()
            if not products:
                print("No products available.")
            else:
                print("\nAvailable Products:")
                for p in products:
                    print(f"{p.id}. {p.name} - ${p.price:.2f} (Stock: {p.stock})")
        elif choice == "4":
            try:
                pid = int(input("Enter Product ID: "))
                qty = int(input("Enter quantity: "))
            except ValueError:
                print("Please enter valid numeric values.")
                continue
            success, msg = app.add_to_cart(pid, qty)
            print(msg)
        elif choice == "5":
            cart_items = app.view_cart()
            if not cart_items:
                print("Cart is empty.")
            else:
                print("\nCart Contents:")
                for product, qty, line_total in cart_items:
                    print(f"{product.name} x {qty} = ${line_total:.2f}")
        elif choice == "6":
            if app.current_user_id is None:
                print("Please log in first.")
                continue
            # Choose payment method
            print("Select payment method:")
            print("1. Cash")
            print("2. Card")
            pm_choice = input("Choice: ").strip()
            if pm_choice == "1":
                method = "Cash"
            elif pm_choice == "2":
                method = "Card"
            else:
                print("Invalid payment method.")
                continue
            success, receipt = app.checkout(method)
            if success:
                print("\nPurchase successful! Receipt:")
                print(receipt)
            else:
                print(f"Checkout failed: {receipt}")
        elif choice == "7":
            name = input("Product name: ").strip()
            try:
                price = float(input("Price: "))
                stock = int(input("Initial stock: "))
            except ValueError:
                print("Please enter valid numeric values for price and stock.")
                continue
            product_id = app.add_product(name, price, stock)
            print(f"Added product with ID {product_id}.")
        elif choice == "0":
            print("Exiting application.")
            break
        else:
            print("Invalid option. Please try again.")


if __name__ == "__main__":
    try:
        interactive_cli()
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting.")
        sys.exit(0)