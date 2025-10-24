# Retail Store Application – Software Architecture Project

This repository contains an enhanced retail application used to explore software architecture patterns and quality attributes. While the original checkpoint showcased a simple two‑tier system, the updated version demonstrates how to build a more feature‑rich system using only Python’s standard library. It now supports concurrency, external integrations, partner feed ingestion, extensible payment methods, circuit breaking, retry logic, metrics, logging and real‑time flash sales. Data continues to be stored locally in SQLite, and the persistence layer is abstracted via Data Access Objects (DAOs).

## Team Members

This project was completed by the following team members:  
- Kwabena Sekyi-Djan  
- Jiacheng Xia

## Project Structure

```text
.
├── db/                          # Database schema and persisted data
│   ├── init.sql                # Schema definition; applied automatically on first run
│   └── retail.db               # SQLite database (auto-generated; ignored by version control)
├── docs/                        # Documentation and diagrams
│   ├── UMLS/                   # UML diagrams for the 4+1 views
│   ├── ADR/                    # Architecture Decision Records (see below)
│   └── QUALITY_SCENARIO_CATALOG.md  # Quality attribute scenarios and mapped tactics
├── logs/                        # JSON‑formatted rotating log files (created at runtime)
├── src/
│   ├── app.py                  # Business logic: registration, cart, checkout, circuit breaker, retry/backoff, flash sales
│   ├── app_web.py              # Multi‑user HTTP server (ThreadingHTTPServer) with per‑session cookies and endpoints
│   ├── dao.py                  # Data access objects with connection pooling, optimistic locking and schema versioning
│   ├── external_services.py    # Stubs for inventory, shipping and reseller API integrations (gateway + adapters)
│   ├── logging_config.py       # JSON logging configuration and rotating file handler
│   ├── metrics.py              # Minimal metrics library (counters, gauges, histograms) and global metrics
│   ├── partner_ingestion.py    # Adapter pattern for partner feed ingestion (CSV, JSON, XML)
│   ├── payment_service.py      # Strategy‑driven payment service with retry logic, circuit breaker and refund API
│   └── full_test_suite.py      # Comprehensive test harness covering quality scenarios
├── tests/                      # Unit tests for core business logic and DAO interactions
│   └── test_retail_app.py
├── .gitignore
└── README.md                  # Project documentation (this file)

```

## Key Modules

### app.py – Implements the core retail workflows (user registration, login, cart management and checkout). This module now includes:

- A circuit breaker to protect the payment service; if too many payment failures occur within a short period, further attempts are short‑circuited until the cooldown expires.

- Retry logic with exponential backoff and jitter when contacting the payment gateway, ensuring transient failures are retried but not indefinitely.

- Atomic transactions with compensating rollback: all database operations (sale record, stock updates, payment record) occur within a transaction; if anything fails afterwards, the payment is refunded.

- External service integrations: after a successful sale, the app updates a mock inventory service, creates a mock shipment via a shipping service, and optionally notifies resellers via a gateway and adapters.

- Partner feed ingestion: products from external partners can be imported and scheduled for periodic refresh using adapters and scheduled threads.

### app_web.py – Wraps the business logic in a multi‑user HTTP server. It uses ThreadingHTTPServer to handle concurrent requests and cookie‑based sessions so multiple users can browse and purchase independently. Additional endpoints include:

- /partner/feed – Ingest partner product feeds authenticated via API key (security scenario 2.1). Provide an API key via the X‑API‑Key header or api_key query parameter and a source URL or file path to ingest.

- /workload/log, /workload/clear, /workload/replay – Capture and replay workloads for testability scenarios (6.1/6.2).

- /metrics – Expose runtime metrics in Prometheus exposition format.

- Standard pages such as /products, /cart, /checkout, /login and /register (HTML forms).

### dao.py – Provides per‑thread connection pooling to the SQLite database using thread‑local storage. Each connection automatically applies the schema via init.sql on first use and enforces foreign‑key integrity. Updates to stock levels use optimistic locking to prevent overselling under concurrent access. The module also supports schema versioning via PRAGMA user_version to ensure migrations can be applied incrementally.

### external_services.py – Defines stubbed inventory, shipping and reseller API services. Each service logs calls and returns success for demonstration. A reseller API gateway acts as a registry and facade for adapter instances; adapters can be registered dynamically to support new resellers.

### partner_ingestion.py – Implements the adapter pattern for parsing partner feeds. CSV, JSON and XML formats are supported out of the box. Parsed products are validated and upserted into the local catalogue. Developers can add new adapters by subclassing PartnerAdapter.

### payment_service.py – Implements a strategy‑based payment service with pluggable payment methods (card, cash, crypto). Each method defines its own success/failure logic (e.g., card payments have a configurable success rate, cash is currently unsupported, crypto always succeeds). The service integrates retry logic, a circuit breaker and a refund API for compensating transactions.

### metrics.py and logging_config.py – Provide instrumentation and structured logging. Metrics are collected via counters, gauges and histograms, and can be scraped at /metrics. Logging is JSON‑formatted with timestamps, levels and optional request/user context; logs are written to rotating files under logs/.

### full_test_suite.py – A script that launches the server and exercises many of the quality attribute scenarios (high‑load performance, security, modifiability, integrability, testability, usability). It generates concurrent load, ingests partner feeds, measures latencies, checks circuit breaker behaviour and produces a summary of metrics and logs.

## Prerequisites

- Python 3.11+ is recommended (the code relies on datetime.UTC and other recent standard library features).

- A POSIX shell to run commands (Windows users can adapt commands accordingly).

- No external dependencies are required; all functionality is built using Python’s standard library. A .venv folder is included for convenience but is not strictly necessary.

## Setup Instructions

### Clone the repository and navigate into the project folder:

```text

git clone https://github.com/fhgggtyf/Software-Architecture-Project.git
cd Software-Architecture-Project

```

### Create and activate a virtual environment. This isolates dependencies from your system Python:

```text

python3 -m venv .venv
source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`

```

### Database Setup

The application uses an SQLite database stored in db/retail.db. A schema definition is provided in db/init.sql. You do not need to run this manually—the DAO layer will automatically run the script on first connection and create the tables if they do not already exist. If you prefer to initialise the database manually (for example via the SQLite CLI), run:

```text

sqlite3 db/retail.db < db/init.sql

```

You can override the default database path by setting the RETAIL_DB_PATH environment variable before starting the server.

Note that it’s ignored by .gitignore and should not be committed.

### Running the Application

Start the minimal HTTP server from the project root. By default it listens on localhost:8000 but you can change the host and port via environment variables:

```text

# start the server on http://localhost:8000
python ./src/app_web.py

# or specify a different host/port
HOST=0.0.0.0 PORT=8080 python ./src/app_web.py

```

#### Purchase Flow and Payment Methods

When a user checks out, the application performs the following steps:

- Validate stock: Ensure each product in the cart still exists and has sufficient quantity.

- Compute totals: Sum item subtotals (accounting for flash sale pricing when active).

- Circuit breaker check: Before contacting the payment gateway, the circuit breaker is consulted to see if too many recent failures have occurred.

- Process payment: Payments are processed via the PaymentService, which uses a strategy pattern to support multiple methods (card, cash, crypto by default). Each strategy can be configured or extended:

- - Card – Simulated credit‑card payments succeed based on a success rate (default 50%).

- - Cash – Currently unsupported; always fails.

- - Crypto – Always succeeds for demonstration.

- - Custom – Register additional strategies via PaymentService.register_strategy().

- Retry and backoff: If a payment fails, the service retries up to three times with exponential backoff and random jitter. Repeated failures will trip the circuit breaker.

- Persist sale: If payment succeeds, the sale, sale items and payment record are inserted in a single transaction. Stock levels are decremented using optimistic locking.

- External services: The app updates an inventory service, creates a shipment via the shipping service and optionally sends the order to resellers via the API gateway.

- Clear the cart: On the main thread, the cart is cleared after a successful checkout. Concurrent checkouts running in other threads use snapshot copies to avoid race conditions.

- Receipt: A text receipt summarising the sale, totals, payment method and reference is returned to the user.

If any step after payment fails (e.g., a database or external service error), the application refunds the payment and rolls back the transaction to maintain consistency.

## Running the Tests

This project includes a suite of unit tests covering both the business logic and the database integration. To run the tests, execute from the project root:

```text

python -m unittest discover -s tests -p "test_*.py" -v

```

The tests use a temporary SQLite database (RETAIL_DB_PATH is set to a temporary file) so they will not interfere with your development database. They verify registration/login, cart behaviour, checkout success/failure, stock decrementation, payment persistence, and foreign‑key integrity.

Full test suite (src/full_test_suite.py) exercises many of the quality attribute scenarios. It launches a server on a high port, generates concurrent load, ingests partner feeds, measures latencies, triggers circuit breaker behaviour and inspects metrics and logs. Execute it with:

```text

python src/full_test_suite.py

```

## Documentation

Quality Scenario Catalog (docs/QUALITY_SCENARIO_CATALOG.md) describes the fourteen quality attribute scenarios and maps them to architectural tactics and code references.

Architecture Decision Records (ADRs) (docs/ADR/) capture key design choices. The README.md in that folder indexes decisions such as circuit breaker, retry logic, strategy pattern, adapter pattern, optimistic locking, session management, atomic transactions, input validation, schema versioning, flash sale logic, progressive error handling, connection pooling and plugin architecture.

UML diagrams (docs/UML/) illustrate the 4+1 views of the system (logical, process, deployment, implementation and use case).

A consolidated PDF including UML diagrams, ADRs, and the demo video link is included in the docs/ folder.

## Additional Notes

The application uses only the Python standard library. The .venv included in the repository is optional and contains pip packages for development convenience but is not required for runtime.

Partner feed ingestion uses the adapter pattern to support new formats. Developers can implement additional PartnerAdapter subclasses to parse bespoke feeds and register them via partner_ingestion.select_adapter().

Payment service extensibility is achieved via the strategy pattern. You can register new strategies (e.g., mobile wallets, buy‑now‑pay‑later) using PaymentService.register_strategy().

External integrations are stubbed for demonstration. Replace InventoryService, ShippingService and ResellerAPIGateway with real SDKs or HTTP clients for production use.

Logging & metrics are disabled by default in the unit tests but can be enabled during integration tests to verify structured logs and collected metrics.

While the spec mentions pytest, this repository relies on Python’s built‑in unittest to remain dependency‑free.