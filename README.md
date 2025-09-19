# Retail Store Application – Software Architecture Project

This repository contains a **minimal retail application** built as part of a software architecture course. The goal of this checkpoint is to demonstrate how to structure a **two-tier system** (client + database) using **Python’s standard library only**. It provides a simple web interface for managing a product catalogue, registering/logging in users, adding items to a cart, and checking out. All data is stored locally in an SQLite database and the persistence layer is abstracted via Data Access Objects (DAOs).

## Team Members
Replace these with your actual names (two teammates required):
- Team Member 1: **Kwabena Sekyi-Djan**
- Team Member 2: **Jiacheng Xia**

## Project Structure
.
├── db/
│ ├── init.sql # SQL script defining the database schema
│ └── retail.db # SQLite database file (auto-generated at runtime; not tracked)
├── docs/
│ ├── UML/ # UML diagrams for the 4+1 views model
│ └── ADR/ # Architecture Decision Records
├── src/
│ ├── app.py # Business logic: registration, cart, checkout
│ ├── app_web.py # Minimal HTTP server using stdlib http.server
│ ├── dao.py # DAOs for User, Product, Sale, SaleItem, Payment
│ └── payment_service.py# Mock payment service (Card=approve, Cash=fail)
├── tests/
│ └── test_retail_app.py# Unit tests (business logic + DB integration)
├── .gitignore
└── README.md

markdown
Copy code

> **Note:** `db/retail.db` is generated at runtime and should be ignored by Git (see `.gitignore`).

## Prerequisites
- **Python 3.10+**
- Ability to create a virtual environment with **venv** (bundled with Python)
- **No external dependencies required** (pure stdlib)
- Optional: `sqlite3` **CLI** if you want to run `init.sql` manually. (The Python **`sqlite3` module** is included with Python; the **CLI** may not be installed on all systems.)

## Setup
```bash
# clone & enter project
git clone https://github.com/fhgggtyf/Software-Architecture-Project.git
cd Software-Architecture-Project

# create & activate virtual environment
python3 -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows (PowerShell)
# .venv\Scripts\Activate.ps1
Database Setup
The app uses SQLite at db/retail.db. The schema is defined in db/init.sql.

Automatic: You do not need to run anything manually. On the first DB connection, the DAO layer executes db/init.sql and creates tables if they don’t exist.

Manual (optional): If you have the SQLite CLI:

bash
Copy code
sqlite3 db/retail.db < db/init.sql
Override DB location: Set RETAIL_DB_PATH before running:

bash
Copy code
RETAIL_DB_PATH=/absolute/path/to/retail.db python src/app_web.py
Running the Application
Start the minimal HTTP server from the project root:

bash
Copy code
# default: http://localhost:8000
python src/app_web.py

# or specify a different host/port
HOST=0.0.0.0 PORT=8080 python src/app_web.py
Open your browser to the server URL. You can then:

Register a user and log in

Browse products, add to cart

Checkout with a payment method

On checkout the app will:

Validate product IDs and stock levels

Compute subtotals and totals

Process payment via the mock PaymentService (Card always succeeds; Cash always fails)

Persist the sale, items, and payment details atomically

Decrement stock levels

Display a simple receipt

All data persists across restarts in db/retail.db.

Running Tests
This project uses Python’s built-in unittest (no pytest required):

bash
Copy code
python -m unittest discover -s tests -p "test_*.py" -v
The tests use a temporary SQLite file (by setting RETAIL_DB_PATH) so they won’t interfere with your development database. They verify:

Registration/login, cart behaviour, totals

Checkout success (Card) and failure (Cash)

Stock decrementation

Payment persistence

Foreign-key integrity

Documentation
UML (4+1 views): see docs/UML/ (logical/class, process/sequence, deployment, implementation, use-case)

ADRs: see docs/ADR/ (e.g., DB choice, DAO pattern, mock payment approach)

Consolidated PDF: include a single PDF in docs/ with the UML diagrams, ADRs, and a link to the demo video (per checkpoint deliverables).

Notes
The mock payment service is intentionally simple so you can demonstrate both success and failure flows.

The test suite sticks to stdlib unittest to remain dependency-free.