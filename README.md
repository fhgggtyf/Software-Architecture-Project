# Retail Store Application – Software Architecture Project

This repository contains a minimal retail application built as part of a software architecture course. The goal of this project checkpoint is to demonstrate how to structure a two-tier system (client + database) using Python’s standard library only. It provides a simple web interface for managing a product catalogue, registering/logging in users, adding items to a cart, and checking out. All data is stored locally in an SQLite database, and the persistence layer is abstracted via Data Access Objects (DAOs).

## Team Members

This project was completed by the following team members:  
- Kwabena Sekyi-Djan  
- Jiacheng Xia

## Project Structure

```text
.  
├── db/  
│   ├── init.sql          # SQL script defining the database schema  
│   └── retail.db         # SQLite database file (auto-generated at runtime; should be ignored via version control)  
├── docs/  
│   ├── UML/              # UML diagrams for the 4+1 views model  
│   └── ADR/              # Architecture Decision Records  
├── src/  
│   ├── app.py            # Business logic for registration, cart management, and checkout  
│   ├── app_web.py        # Minimal HTTP server using Python’s built-in http.server module  
│   ├── dao.py            # Data Access Objects for User, Product, Sale, SaleItem, and Payment  
│   └── payment_service.py # Mock payment gateway  
├── tests/                # Unit tests (business logic and DB integration)  
│   └── test_retail_app.py # Test cases for the application  
├── .gitignore            # Ignore patterns for Git (includes db/retail.db)  
└── README.md             # Project documentation (this file)  

```

## Prerequisites
- Python 3.10+ installed on your machine.
- Ability to create a virtual environment with venv (built into Python).
- SQLite (comes with Python’s standard library; no separate installation needed).

## Setup Instructions

- Clone the repository and navigate into the project folder:

```text

git clone https://github.com/fhgggtyf/Software-Architecture-Project.git
cd Software-Architecture-Project

```

- Create and activate a virtual environment. This isolates dependencies from your system Python:

```text

python3 -m venv .venv
source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`

```

- Database Setup

The application uses an SQLite database stored in db/retail.db. A schema definition is provided in db/init.sql. You do not need to run this manually—the DAO layer will automatically run the script on first connection and create the tables if they do not already exist. If you prefer to initialise the database manually (for example via the SQLite CLI), run:

```text

sqlite3 db/retail.db < db/init.sql

```

You can override the default database path by setting the RETAIL_DB_PATH environment variable before starting the server.

- Running the Application

Start the minimal HTTP server from the project root. By default it listens on localhost:8000 but you can change the host and port via environment variables:

```text

# start the server on http://localhost:8000
python ./src/app_web.py

# or specify a different host/port
HOST=0.0.0.0 PORT=8080 python ./src/app_web.py

```

Open your browser and navigate to the server URL. You can then register a user, log in, browse products, add items to your cart, and check out. Upon checkout the application will:

- Validate product IDs and stock levels.

Compute subtotals and totals.

Process a payment via the mock PaymentService (Card always succeeds; Cash always fails).

Persist the sale, sale items and payment details atomically.

Decrement stock levels.

Display a simple receipt.

All data persists across restarts because it is stored in db/retail.db.

Running the Tests

This project includes a suite of unit tests covering both the business logic and the database integration. To run the tests, execute from the project root:

python -m unittest discover -s tests -p "test_*.py" -v


The tests use a temporary SQLite database (RETAIL_DB_PATH is set to a temporary file) so they will not interfere with your development database. They verify registration/login, cart behaviour, checkout success/failure, stock decrementation, payment persistence, and foreign‑key integrity.

Documentation

UML diagrams for the 4+1 views (logical, process, deployment, implementation and use‑case) are located under docs/UML/.

Architectural Decision Records (ADRs) documenting key decisions (e.g., database choice, DAO pattern, mock payment service) reside in docs/ADR/.

A consolidated PDF containing the diagrams, ADRs and a link to the demonstration is placed in the docs folder.

Additional Notes

The mock payment service is intentionally simple; it always approves card payments and rejects cash payments to allow you to demonstrate success and failure flows.

The test suite uses Python’s built‑in unittest rather than pytest to remain dependency‑free.