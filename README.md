Software Architecture Project
=============================

This repository contains a small **retail store** application built with
Python 3.10+.  It demonstrates how to build a functional web
application without relying on any third‑party frameworks.  A minimal
HTTP server built on Python's standard library exposes pages for
registering, logging in, browsing the product catalogue, managing a
shopping cart and checking out.  The business logic is encapsulated
in `src/app.py`, and data is persisted using a minimal Data Access
Object (DAO) layer backed by SQLite.

The intent of this refactored version is to demonstrate how to build a
complete but minimal application using only *native* toolchains:

* **Python 3.10+** – the code uses modern language features such as the
  dataclass decorator and the union operator (`|`) for type annotations.
* **Built‑in virtual environments** – no external dependency managers like
  Poetry or Pipenv are used.  A `venv` is sufficient.
* **pytest** – used as the test runner for this project.  The tests live under
  `tests/` and can be run directly after installing the dependencies listed in
  `requirements.txt`.
* **SQLite** – the default and only supported database in this repository.  It
  is bundled with Python, so no additional drivers are required.  The DAO
  layer could be extended to support other backends (for example,
  PostgreSQL via `psycopg`) if those packages are installed, but such support
  is outside the scope of this refactoring.

Getting Started
---------------

1. **Clone the repository** and navigate into the project folder:

   ```bash
   git clone <repo-url>
   cd Software-Architecture-Project
   ```

2. **Create a virtual environment** and activate it.  This isolates the
   project's dependencies from your system Python.  On Unix or macOS:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

   On Windows:

   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **Install the dependencies** using `pip`.  The `requirements.txt`
   lists pytest for running the test suite:

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

4. **Initialize the database**.  The SQLite database will be created
   automatically when the app is first run.  It lives in `db/retail.db` by
   default.  You can override the path by exporting the `RETAIL_DB_PATH`
   environment variable.

5. **Run the web server**.  The application includes a minimal HTTP
   server built entirely on Python's standard library.  To start the
   server, run the entry point directly.  By default it listens on
   `localhost:8000`, but you can override the host and port with the
   `HOST` and `PORT` environment variables:

   ```bash
   # start the server on http://localhost:8000
   python src/app_web.py

   # or specify a different host/port
   HOST=0.0.0.0 PORT=8080 python src/app_web.py
   ```

   Once running, open your browser and navigate to the server URL to
   register, log in, browse products, manage the cart and check out.

6. **Run the tests**.  The test suite uses pytest and can be invoked from
   the project root.  The tests automatically create and tear down temporary
   SQLite databases, so they will not interfere with your development data:

   ```bash
   pytest
   ```

Project Structure
-----------------

```
Software-Architecture-Project/
├── README.md          – this file
├── requirements.txt   – Python dependencies
├── db/
│   └── retail.db      – SQLite database file (created on demand)
├── docs/              – optional documentation folder
├── src/
│   ├── app.py         – business logic
│   ├── app_web.py     – minimal HTTP server (no external dependencies)
│   ├── dao.py         – data access layer (SQLite implementation)
│   ├── payment_service.py – mock payment gateway
│   └── templates/     – HTML templates for the UI
└── tests/
    └── test_retail_app.py – pytest tests exercising the core functionality
```

Extending the Data Layer
------------------------

At present the DAO layer in `src/dao.py` uses Python's built‑in
`sqlite3` module to access the `db/retail.db` file.  To support an alternative database backend such as
PostgreSQL you could:

1. Install a suitable driver (e.g. `psycopg` for PostgreSQL).
2. Modify the `_new_connection` helper in `dao.py` to detect an
   environment variable (for example, `DB_TYPE=postgres`) and create a
   connection accordingly.
3. Update the SQL statements in the DAO methods to use parameter
   placeholders appropriate for the driver (SQLite uses `?`, whereas
   PostgreSQL uses `%s`).

Such work would require additional dependencies and testing and is left
as an exercise.  The current implementation fully satisfies the
requirement to use a built‑in database engine.