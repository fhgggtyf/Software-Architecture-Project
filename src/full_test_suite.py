#!/usr/bin/env python3
"""
Comprehensive test harness for the Retail Store Application.

This script attempts to exercise the majority of quality‑attribute scenarios
described in the project documentation.  It launches the HTTP server
(`app_web.py`) on a high port and then runs a suite of test cases.  Each
test prints its name, what it is verifying, and the observed outcome.  After
all tests are complete, the server is stopped cleanly.

The tests included here cover the following categories:

* **Availability/Performance** – generates high concurrency load against
  the `/products` endpoint to approximate flash‑sale conditions and reports
  average and 95th percentile latencies.  This test can be tuned via the
  `NUM_REQUESTS` and `CONCURRENCY` constants.
* **Security** – attempts to interact with the system in ways that should
  be rejected, such as sending malicious inputs and calling non‑existent
  endpoints.  It checks that the server does not execute injected
  JavaScript and returns 404 for unknown partner endpoints.
* **Modifiability** – ingests partner feeds in both CSV and JSON formats
  using the adapter pattern.  A successful insert/update confirms the
  ability to extend to new feed formats without changing core logic.
* **Performance** – stresses the checkout process via direct calls to
  `RetailApp.checkout` with different payment methods.  It measures
  checkout duration and exercises the circuit breaker by forcing
  repeated failures.
* **Integrability** – calls the partner ingestion adapter directly with
  multiple formats and invalid data.  The system should gracefully skip
  invalid rows and upsert valid ones.
* **Testability** – fetches the `/metrics` endpoint after load tests and
  partner ingestions, ensuring that counters and histograms are exposed.
  It also tails the application log to verify that structured logging is
  configured and that events are recorded.
* **Usability** – performs a checkout using an unsupported payment method
  via the HTTP API and checks that the user receives a clear error
  response.

Not every scenario from the assignment can be fully automated in this
prototype (for example, database failover, adding new partner formats,
integration with real third‑party services or a sophisticated flash‑sale UI).
Where behaviour is not implemented in the reference application, the
corresponding test prints a warning so that you can extend the
application or the tests accordingly.  The expanded test suite below
adds additional test functions to exercise each of the quality
attribute scenarios described in the documentation.  These include
database failover recovery, partner feed authentication, support for
new partner feed formats, extensible payment methods, high‑load
performance, concurrent checkout behaviour, onboarding new resellers,
third‑party service integrations, replayable workloads for testability,
integration tests with external services, and flash‑sale usability.
"""

import os
import sys
import time
import threading
import tempfile
import urllib.request
import urllib.parse
import statistics
import subprocess

# Determine the directory where this script resides.  We assume the
# server (`app_web.py`) lives in the same directory, and the logs are
# stored one level up in a `logs` folder (as configured in
# logging_config.py).
HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = HERE
SERVER_SCRIPT = os.path.join(SRC_DIR, "src", "app_web.py") if os.path.exists(os.path.join(SRC_DIR, "src")) else os.path.join(SRC_DIR, "app_web.py")
LOG_FILE = os.path.join(os.path.dirname(SRC_DIR), "logs", "retail_app.log")

# Ensure the application modules can be imported (for partner
# ingestion) by adding SRC_DIR to sys.path if necessary.
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def start_server(port: int) -> tuple[subprocess.Popen, int]:
    """Launch the web server on the specified port.

    The server is started as a subprocess.  The function polls the
    server's root URL until it responds, indicating that the HTTP
    server is ready to accept connections.  If the server does not
    start within a timeout period, a RuntimeError is raised.

    Returns a tuple `(process, port)` for later termination.
    """
    proc = subprocess.Popen([
        sys.executable,
        SERVER_SCRIPT,
        str(port),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Wait up to 15 seconds for the server to start responding.
    for _ in range(30):
        try:
            urllib.request.urlopen(f"http://localhost:{port}", timeout=1)
            return proc, port
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Server did not start within timeout")


def stop_server(proc: subprocess.Popen) -> None:
    """Terminate the server process gracefully."""
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def http_get(url: str) -> tuple[int, bytes]:
    """Perform an HTTP GET request using urllib and return (status, body)."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.getcode(), resp.read()


def http_post(url: str, data: dict[str, str]) -> tuple[int, bytes]:
    """Perform an HTTP POST with URL‑encoded form data."""
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.getcode(), resp.read()


def run_load_test(base_url: str, num_requests: int = 100, concurrency: int = 10) -> tuple[list[float], int]:
    """
    Simulate concurrent GET requests to the `/products` endpoint.

    Parameters:
    - base_url: The root URL of the server (e.g. "http://localhost:9000").
    - num_requests: Total number of requests to perform.
    - concurrency: Number of worker threads to use.

    Returns a tuple `(durations, errors)` where `durations` is a list of
    request latencies (in seconds) and `errors` is the count of
    responses that were not HTTP 200 (or encountered exceptions).
    """
    durations: list[float] = []
    errors = 0
    lock = threading.Lock()

    def worker(count: int) -> None:
        nonlocal errors
        for _ in range(count):
            start = time.perf_counter()
            try:
                status, _ = http_get(f"{base_url}/products")
                if status != 200:
                    with lock:
                        errors += 1
            except Exception:
                with lock:
                    errors += 1
            end = time.perf_counter()
            with lock:
                durations.append(end - start)

    per_thread = max(1, num_requests // max(1, concurrency))
    threads = [threading.Thread(target=worker, args=(per_thread,)) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return durations, errors


def tail_log(path: str, lines: int = 10) -> list[str]:
    """Return the last `lines` lines from the given log file, if it exists."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.readlines()
    return [line.rstrip("\n") for line in content[-lines:]]


def fetch_metrics(base_url: str) -> str:
    """Retrieve the text from the `/metrics` endpoint as a string."""
    try:
        status, body = http_get(f"{base_url}/metrics")
    except Exception as exc:
        return f"(failed to fetch metrics: {exc})"
    if status != 200:
        return f"(metrics endpoint returned status {status})"
    return body.decode("utf-8", errors="replace")


def test_availability_performance(base_url: str) -> None:
    """Test system availability and performance under load."""
    print("\n[Availability/Performance] Flash‑sale load test")
    # Increase requests and concurrency to approximate flash sale
    NUM_REQUESTS = 200
    CONCURRENCY = 20
    durations, errors = run_load_test(base_url, num_requests=NUM_REQUESTS, concurrency=CONCURRENCY)
    print(f"  Sent {len(durations)} requests with {CONCURRENCY} workers; errors: {errors}")
    if durations:
        mean_latency = statistics.mean(durations)
        sorted_durations = sorted(durations)
        idx95 = max(0, int(0.95 * len(sorted_durations)) - 1)
        p95_latency = sorted_durations[idx95]
        print(f"  Average latency: {mean_latency:.3f}s, 95th percentile: {p95_latency:.3f}s")
    else:
        print("  No durations recorded – possible failure in load test.")
    # Fetch metrics to see histogram counts
    m = fetch_metrics(base_url)
    print("  Sample metrics:\n", "\n".join(m.splitlines()[:10]))
    # Show last few log entries for anomalies
    logs = tail_log(LOG_FILE, lines=5)
    if logs:
        print("  Recent logs:")
        for ln in logs:
            print("    ", ln)
    else:
        print("  (No log entries found for availability/performance test)")


def test_security(base_url: str) -> None:
    """Run basic security‑oriented tests."""
    print("\n[Security] Partner endpoint and malicious input tests")
    # Attempt to call a non‑existent partner feed endpoint over HTTP
    try:
        status, _ = http_get(f"{base_url}/partner/feed")
        if status == 404:
            print("  ✅ Unknown partner endpoint correctly returned 404")
        else:
            print(f"  ⚠️  Unexpected status from /partner/feed: {status}")
    except Exception as exc:
        print(f"  ⚠️  Error fetching /partner/feed: {exc}")
    # Attempt to register a user with malicious content and ensure it is escaped on listing
    malicious = "<script>alert('x')</script>"
    try:
        # Register and login with malicious username
        http_post(f"{base_url}/register", {"username": malicious, "password": "p"})
        http_post(f"{base_url}/login", {"username": malicious, "password": "p"})
        status, body = http_get(f"{base_url}/products")
        body_text = body.decode("utf-8", errors="replace")
        if malicious not in body_text:
            print("  ✅ Malicious HTML content is escaped/removed on product page")
        else:
            print("  ⚠️  Malicious HTML is rendered – input sanitization missing")
    except Exception as exc:
        print(f"  ⚠️  Error during malicious input test: {exc}")


def test_modifiability() -> None:
    """Test ingestion of partner feeds in different formats."""
    print("\n[Modifiability] Partner feed ingestion (CSV and JSON)")
    from partner_ingestion import ingest_partner_feed as ingest
    from dao import ProductDAO
    # Use a temporary ProductDAO pointing at the default DB
    product_dao = ProductDAO()
    # CSV feed
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tmp_csv:
        tmp_csv.write("name,price,stock\nCSVWidget,12.34,10\n")
        csv_path = tmp_csv.name
    try:
        ingest(csv_path, product_dao)
        print("  ✅ CSV partner feed ingested (adapter pattern)")
    except Exception as exc:
        print(f"  ⚠️  CSV ingestion failed: {exc}")
    finally:
        os.unlink(csv_path)
    # JSON feed
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp_jsn:
        tmp_jsn.write('[{"name": "JSONWidget", "price": 9.99, "stock": 5}]')
        jsn_path = tmp_jsn.name
    try:
        ingest(jsn_path, product_dao)
        print("  ✅ JSON partner feed ingested (adapter pattern)")
    except Exception as exc:
        print(f"  ⚠️  JSON ingestion failed: {exc}")
    finally:
        os.unlink(jsn_path)


def test_performance_checkout() -> None:
    """Stress the checkout process directly via the RetailApp API."""
    print("\n[Performance] Checkout process and circuit breaker")
    from app import RetailApp
    # Create an app instance and populate with products
    app = RetailApp()
    # Add a product to the cart
    products = app.product_dao.list_products()
    if not products:
        print("  ⚠️  No products available to test checkout performance")
        return
    pid = products[0].id
    app.user_dao.register_user("perfuser", "pass")
    app.login("perfuser", "pass")
    app.add_to_cart(pid, 1)
    # Perform multiple checkouts with an unsupported method to exercise retries and circuit breaker
    for i in range(5):
        start = time.perf_counter()
        ok, msg = app.checkout("unknown")
        duration = time.perf_counter() - start
        print(f"  Attempt {i+1}: ok={ok}, msg='{msg}', duration={duration:.3f}s")
    # After repeated failures the circuit breaker should open
    # Next checkout should fail fast
    start = time.perf_counter()
    ok, msg = app.checkout("card")  # card usually succeeds but circuit may be open
    duration = time.perf_counter() - start
    print(f"  After failures: ok={ok}, msg='{msg}', duration={duration:.3f}s")


def test_integrability() -> None:
    """Test the partner ingestion adapter with invalid data."""
    print("\n[Integrability] Handling invalid partner feeds")
    from partner_ingestion import ingest_partner_feed as ingest
    from dao import ProductDAO
    product_dao = ProductDAO()
    # Create a malformed CSV (missing name column)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tmp:
        tmp.write("price,stock\n5.0,3\n")
        path = tmp.name
    try:
        ingest(path, product_dao)
        print("  ✅ Malformed CSV ingested gracefully (no crash)")
    except Exception as exc:
        print(f"  ⚠️  Malformed CSV caused exception: {exc}")
    finally:
        os.unlink(path)


def test_testability(base_url: str) -> None:
    """Fetch metrics and logs to demonstrate testability."""
    print("\n[Testability] Metrics and logs availability")
    metrics_text = fetch_metrics(base_url)
    print("  /metrics endpoint output (first lines):")
    print("  --------------------------------------")
    for line in metrics_text.splitlines()[:15]:
        print("   ", line)
    # Tail logs
    logs = tail_log(LOG_FILE, lines=10)
    if logs:
        print("  Recent log entries (last 10):")
        for ln in logs:
            print("   ", ln)
    else:
        print("  (No log entries found)")


def test_usability(base_url: str) -> None:
    """Perform a checkout with an unsupported payment method and check feedback."""
    print("\n[Usability] Clear error feedback for failed orders")
    # We need at least one product; ensure DB has been initialised by visiting products page
    http_get(f"{base_url}/products")
    # Attempt checkout without login and with unknown payment method
    try:
        status, body = http_post(f"{base_url}/checkout", {"payment_method": "crypto"})
        if status in (400, 403):
            print(f"  ✅ Received expected error status ({status}) for unauthenticated/invalid payment")
        else:
            print(f"  ⚠️  Unexpected status from checkout: {status}")
        snippet = body[:200].decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)[:200]
        print("  Response preview:", snippet)
    except urllib.error.HTTPError as e:
        print(f"  ✅ HTTPError received as expected: {e.code}")
    except Exception as exc:
        print(f"  ⚠️  Error during usability test: {exc}")

def test_availability_db_failover() -> None:
    """Simulate database connection exhaustion and measure recovery.

    Scenario 1.2 from the quality scenarios calls for the system to
    gracefully recover when the database connection pool is exhausted.
    SQLite is an embedded database and does not have a connection pool in
    this prototype, but we can stress the DB by opening many
    connections concurrently.  The test records how many errors occur
    and how long the operation takes.  If the system exposes a
    read‑only fallback or queuing mechanism, it should be reflected
    here; otherwise a warning is printed.
    """
    print("\n[Availability] Database connection failure recovery test")
    try:
        from dao import get_request_connection
        import threading
        durations = []
        errors = 0
        lock = threading.Lock()

        def worker() -> None:
            nonlocal errors
            try:
                conn = get_request_connection()
                conn.execute("SELECT 1;")
            except Exception:
                with lock:
                    errors += 1

        # Launch a number of threads to open connections concurrently
        thread_count = 50
        threads = [threading.Thread(target=worker) for _ in range(thread_count)]
        start = time.perf_counter()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        duration = time.perf_counter() - start
        print(f"  Attempted {thread_count} concurrent DB ops; errors: {errors}, total time: {duration:.3f}s")
        if errors == 0:
            print("  ✅ DB handled concurrent connections without visible failure")
        else:
            print("  ⚠️  DB errors encountered; consider implementing connection pooling and failover")
    except Exception as exc:
        print(f"  ⚠️  DB failover test could not be executed: {exc}")


def test_partner_authentication(base_url: str) -> None:
    """Test partner feed authentication and authorization.

    Scenario 2.1 specifies that partner feed endpoints must validate
    credentials.  The reference implementation does not expose a
    /partner/feed endpoint at all (it returns 404).  If such an
    endpoint is added in the future it should require an API key or
    token.  This test attempts to call the endpoint with and without
    credentials and reports the observed status codes.
    """
    print("\n[Security] Partner feed authentication test")
    try:
        # Call the endpoint without any credentials
        try:
            status, _ = http_get(f"{base_url}/partner/feed")
            if status in (401, 403):
                print("  ✅ Unauthenticated access correctly blocked with", status)
            elif status == 404:
                print("  ⚠️  /partner/feed endpoint not implemented (returned 404)")
            else:
                print(f"  ⚠️  Unexpected status from /partner/feed without creds: {status}")
        except Exception as exc:
            print(f"  ⚠️  Error calling /partner/feed without credentials: {exc}")
        # Call the endpoint with a dummy API key in query string
        try:
            status, _ = http_get(f"{base_url}/partner/feed?api_key=dummy")
            if status == 200:
                print("  ✅ Authenticated partner feed returned 200 (dummy API key)")
            elif status in (401, 403):
                print("  ✅ Authenticated call correctly rejected with", status)
            elif status == 404:
                print("  ⚠️  /partner/feed endpoint not implemented (returned 404)")
            else:
                print(f"  ⚠️  Unexpected status from /partner/feed with API key: {status}")
        except Exception as exc:
            print(f"  ⚠️  Error calling /partner/feed with credentials: {exc}")
    except Exception as exc:
        print(f"  ⚠️  Partner authentication test failed: {exc}")


def test_new_partner_format_modifiability() -> None:
    """Test ingestion of a new partner feed format (XML).

    Scenario 3.1 requires that new partner formats can be added
    without major changes.  The current implementation supports CSV
    and JSON.  This test tries to ingest a simple XML feed.  If the
    ingestion succeeds, it indicates that an XML adapter has been
    implemented.  Otherwise, a clear message is printed.
    """
    print("\n[Modifiability] New partner format (XML) ingestion test")
    from dao import ProductDAO
    from partner_ingestion import ingest_partner_feed
    product_dao = ProductDAO()
    import tempfile
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as tmp_xml:
            tmp_xml.write("<products><product><name>XMLWidget</name><price>5.5</price><stock>10</stock></product></products>")
            xml_path = tmp_xml.name
        try:
            ingest_partner_feed(xml_path, product_dao)
            # If no exception, assume XML ingestion worked
            print("  ✅ XML partner feed ingested — adapter pattern extended")
        except ValueError as ve:
            print("  ⚠️  XML ingestion not supported (ValueError):", ve)
            print("     Please implement an XMLPartnerAdapter to satisfy scenario 3.1")
        except Exception as exc:
            print(f"  ⚠️  Error during XML ingestion: {exc}")
    finally:
        try:
            os.unlink(xml_path)  # type: ignore[name-defined]
        except Exception:
            pass


def test_payment_method_extension() -> None:
    """Test adding a new payment method via the strategy registry.

    Scenario 3.2 describes the need to add new payment methods (e.g.
    cryptocurrency or wallet payments) without affecting existing flows.
    The PaymentService exposes a register_strategy() method to
    accomplish this.  This test registers a fictitious 'applepay'
    strategy and verifies that it is accepted.
    """
    print("\n[Modifiability] Payment method extension test")
    from payment_service import PaymentService, PaymentStrategy
    class ApplePayStrategy(PaymentStrategy):
        def process(self, amount: float):
            return True, f"APPLE-{int(amount * 100)}"
    svc = PaymentService()
    svc.register_strategy("applepay", ApplePayStrategy())
    ok, ref = svc.process_payment(9.99, "applepay")
    if ok:
        print("  ✅ New payment method processed successfully; reference:", ref)
    else:
        print("  ⚠️  New payment method failed to process; reason:", ref)


def test_performance_high_load(base_url: str) -> None:
    """Test web service response times under higher load.

    Scenario 4.1 calls for bounded latency under heavy load (1k req/s).
    This test increases the number of requests and concurrency relative
    to the basic load test and reports average and 95th percentile
    latencies.  Thresholds are not enforced programmatically but can be
    compared against stated goals.
    """
    print("\n[Performance] High load latency test")
    NUM_REQ = 500
    CONC = 50
    durations, errors = run_load_test(base_url, num_requests=NUM_REQ, concurrency=CONC)
    print(f"  Sent {len(durations)} requests with {CONC} workers; errors: {errors}")
    if durations:
        mean = statistics.mean(durations)
        sd = sorted(durations)
        idx95 = max(0, int(0.95 * len(sd)) - 1)
        p95 = sd[idx95]
        print(f"  Average latency: {mean:.3f}s, 95th percentile: {p95:.3f}s")
        print("  (For scenario 4.1, compare p95 against target thresholds, e.g., <0.5s)")
    else:
        print("  ⚠️  No durations recorded — load test did not run correctly")


def test_concurrent_checkout_performance() -> None:
    """Stress checkout concurrently to measure throughput and circuit breaker.

    Scenario 4.2 describes 500 concurrent users performing checkout.
    We approximate this by launching multiple threads each attempting a
    checkout.  The test reports the number of successes and failures
    along with average durations.  It also exercises the circuit
    breaker behaviour in the business logic.
    """
    print("\n[Performance] Concurrent checkout performance test")
    from app import RetailApp
    import threading
    # Seed app with a product and user
    app = RetailApp()
    pid = app.product_dao.add_product("PerfWidget", 1.0, 50)
    username = "perfuser2"
    password = "pw"
    app.user_dao.register_user(username, password)
    app.login(username, password)
    # Add item to cart
    app.add_to_cart(pid, 1)
    successes = 0
    failures = 0
    durations: list[float] = []
    lock = threading.Lock()
    def do_checkout():
        nonlocal successes, failures
        start = time.perf_counter()
        ok, _ = app.checkout("card")
        dur = time.perf_counter() - start
        with lock:
            durations.append(dur)
            if ok:
                successes += 1
            else:
                failures += 1
    threads = [threading.Thread(target=do_checkout) for _ in range(20)]
    # Start all threads
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if durations:
        mean = statistics.mean(durations)
        p95 = sorted(durations)[max(0, int(0.95 * len(durations)) - 1)]
    else:
        mean = p95 = 0.0
    print(f"  Completed {len(durations)} concurrent checkouts; successes: {successes}, failures: {failures}")
    print(f"  Average checkout time: {mean:.3f}s, 95th percentile: {p95:.3f}s")
    print("  (If failures are high, tune circuit breaker thresholds or optimise DB transactions)")


def test_onboarding_new_reseller_integrability(base_url: str) -> None:
    """Exercise the reseller API gateway and HTTP endpoint.

    Scenario 5.1 requires that new reseller integrations can be onboarded
    without modifying business logic.  The application provides a
    ``ResellerAPIGateway`` with a default adapter and an HTTP endpoint
    ``/reseller/order``.  This test verifies both the direct Python
    interface and the HTTP interface by placing orders through the
    gateway and via the web API.  Successful calls should return
    ``True`` or HTTP 200, and unknown reseller names should fall back
    to the default adapter rather than raising exceptions.
    """
    print("\n[Integrability] Onboarding new reseller API test")
    # Test the direct gateway API
    try:
        from external_services import reseller_gateway
        order = {
            "sale_id": 123,
            "user_id": 1,
            "items": [
                {"product_id": 1, "quantity": 1, "unit_price": 1.0},
            ],
        }
        ok_def = reseller_gateway.place_order("default", order)
        ok_new = reseller_gateway.place_order("newreseller", order)
        if ok_def and ok_new:
            print("  ✅ Reseller gateway placed orders via default and fallback adapters")
        else:
            print("  ⚠️  Reseller gateway returned False for one or more orders")
    except Exception as exc:
        print(f"  ⚠️  Error placing orders via reseller gateway: {exc}")
    # Test the HTTP reseller order endpoint
    try:
        import json
        payload = json.dumps({
            "reseller": "default",
            "items": [
                {"product_id": 1, "quantity": 1, "unit_price": 1.0},
            ],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/reseller/order",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
        if status == 200 and "has been accepted" in body:
            print("  ✅ HTTP reseller order accepted (default)")
        else:
            print(f"  ⚠️  HTTP reseller order returned status {status}")
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  HTTP reseller order failed: {e.code}")
    except Exception as exc:
        print(f"  ⚠️  Error during HTTP reseller order test: {exc}")


def test_third_party_service_integration() -> None:
    """Test integration with inventory and shipping services.

    Scenario 5.2 covers integration with external inventory management
    and shipping services.  The application exposes simple stub
    services via ``external_services.inventory_service`` and
    ``external_services.shipping_service`` and calls them during
    checkout.  This test exercises those services directly and
    through the ``RetailApp.checkout`` method to ensure they return
    success and are invoked without errors.  If the services return
    False or raise exceptions, the test reports a warning.
    """
    print("\n[Integrability] Third‑party service integration test")
    try:
        from external_services import inventory_service, shipping_service
        ok_inv = inventory_service.update_inventory(1, [
            {"product_id": 1, "quantity": 1, "unit_price": 1.0},
        ])
        ok_ship = shipping_service.create_shipment(1, 1, [
            {"product_id": 1, "quantity": 1, "unit_price": 1.0},
        ])
        if ok_inv and ok_ship:
            print("  ✅ Inventory and shipping services responded successfully")
        else:
            print("  ⚠️  Inventory or shipping service returned failure")
    except Exception as exc:
        print(f"  ⚠️  Error calling external services: {exc}")
    try:
        from app import RetailApp
        # Reset the global circuit breaker state to avoid interference from prior tests
        RetailApp._record_payment_success()
        app = RetailApp()
        pid = app.product_dao.add_product("ExtServiceWidget", 1.0, 5)
        app.user_dao.register_user("extsvcuser", "pw")
        app.login("extsvcuser", "pw")
        app.add_to_cart(pid, 1)
        ok, msg = app.checkout("card")
        if ok:
            print("  ✅ Checkout succeeded with external services integrated")
        else:
            print(f"  ⚠️  Checkout failed: {msg}")
    except Exception as exc:
        print(f"  ⚠️  Error during checkout integration test: {exc}")


def test_testability_flash_sale_replay(base_url: str) -> None:
    """Test automated replay of flash-sale workloads (scenario 6.1)."""

    import urllib.request, urllib.error, json

    print("\n[Testability] Automated replay of flash sale workloads test")

    # --- Step 1: clear any existing logs
    try:
        urllib.request.urlopen(f"{base_url}/workload/clear")
    except Exception:
        pass

    # --- Step 2: perform a few requests that will be recorded ---
    try:
        urllib.request.urlopen(f"{base_url}/products").read()
        urllib.request.urlopen(f"{base_url}/products?flash=true").read()

        # simulate a small cart action to record /cart and /checkout
        req = urllib.request.Request(
            f"{base_url}/register", data=b"username=testuser&password=1234", method="POST"
        )
        urllib.request.urlopen(req)

        req = urllib.request.Request(
            f"{base_url}/login", data=b"username=testuser&password=1234", method="POST"
        )
        urllib.request.urlopen(req)

        urllib.request.urlopen(f"{base_url}/cart?add=1").read()
    except Exception as e:
        print(f"  ⚠️  Error while generating workload: {e}")

    # --- Step 3: fetch workload log ---
    try:
        log_resp = urllib.request.urlopen(f"{base_url}/workload/log")
        log_entries = log_resp.read().decode()
        print(f"  ✅ Recorded {len(log_entries.splitlines())} log entries")
    except Exception as e:
        print(f"  ⚠️  Failed to retrieve workload log: {e}")
        log_entries = ""

    # --- Step 4: replay workloads ---
    try:
        replay_resp = urllib.request.urlopen(f"{base_url}/workload/replay")
        result = replay_resp.read().decode()
        print("  ✅ Workload replay executed successfully")
        print("  Replay summary snippet:")
        print("  " + result[:200].replace("\n", " "))
    except urllib.error.HTTPError as e:
        print(f"  ⚠️  Replay HTTPError: {e}")
    except Exception as e:
        print(f"  ⚠️  Replay failed: {e}")



def test_testability_external_service_integration() -> None:
    """Test error handling when external services fail.

    Scenario 6.2 mandates that the system be testable in the face of
    failures from external integrations.  To simulate this, the test
    overrides the ``inventory_service`` and ``shipping_service`` on a
    ``RetailApp`` instance with stubs that return ``False``.  It then
    performs a checkout and verifies that the checkout fails with an
    appropriate error message.  A successful detection indicates that
    external service errors are propagated and handled gracefully.
    """
    print("\n[Testability] Integration testing with external services test")
    try:
        from app import RetailApp
        class FailingInventory:
            def update_inventory(self, sale_id: int, items):
                return False
        class FailingShipping:
            def create_shipment(self, sale_id: int, user_id: int, items):
                return False
        # Reset the circuit breaker to ensure the checkout path runs rather than being blocked
        RetailApp._record_payment_success()
        app = RetailApp()
        app.inventory_service = FailingInventory()
        app.shipping_service = FailingShipping()
        pid = app.product_dao.add_product("FailServiceWidget", 2.0, 5)
        app.user_dao.register_user("failuser", "pw")
        app.login("failuser", "pw")
        app.add_to_cart(pid, 1)
        ok, msg = app.checkout("card")
        if not ok and ("external" in msg.lower() or "failed" in msg.lower()):
            print("  ✅ External service failure detected and reported:", msg)
        else:
            print("  ⚠️  External service failure was not detected; result:", ok, msg)
    except Exception as exc:
        print(f"  ⚠️  Error during external service integration test: {exc}")


def test_flash_sale_pricing_and_ui(base_url: str) -> None:
    """Test flash sale pricing logic and verify UI elements.

    Scenario 7.2 demands both correct pricing during flash sales and an
    intuitive user interface with live countdown timers.  The business
    logic is exercised via ``RetailApp`` to ensure that the flash sale
    price is applied.  Then the ``/products`` page is retrieved over
    HTTP and inspected for the presence of countdown timers and the
    associated JavaScript.  Success requires both the price logic and
    UI elements to be in place.
    """
    print("\n[Usability] Flash sale pricing and interface test")
    from app import RetailApp
    from datetime import datetime, UTC, timedelta
    app = RetailApp()
    pid = app.product_dao.add_product("FlashItem", 10.0, 5)
    now = datetime.now(UTC)
    start = (now - timedelta(minutes=1)).isoformat()
    end = (now + timedelta(minutes=1)).isoformat()
    app.product_dao.upsert_product("FlashItem", 10.0, 5, 5.0, start, end)
    app.user_dao.register_user("flashuser", "pw")
    app.login("flashuser", "pw")
    ok, msg = app.add_to_cart(pid, 1)
    if not ok:
        print("  ⚠️  Could not add flash item to cart:", msg)
        return
    line = app.view_cart()[0]
    if abs(line.unit_price - 5.0) < 1e-6:
        print("  ✅ Flash sale price applied correctly (5.0)")
    else:
        print(f"  ⚠️  Flash sale price not applied; expected 5.0, got {line.unit_price}")
    try:
        status, body = http_get(f"{base_url}/products")
        page = body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)
        if ("flash-countdown" in page) and ("updateCountdown" in page):
            print("  ✅ Flash sale UI countdown elements detected on products page")
        else:
            print("  ⚠️  Flash sale UI countdown elements missing from products page")
    except Exception as exc:
        print(f"  ⚠️  Error fetching products page for UI test: {exc}")


# ------------------------------------------------------------------------------
# New tests for returns/refunds functionality
#
# The application now supports submitting return (RMA) requests for completed
# sales and approving or rejecting those requests.  These tests exercise the
# happy path (requesting and approving a return) as well as several failure
# cases, including duplicate requests, unauthenticated access and attempts to
# return another user's sale.  They also inspect the custom metrics exposed
# by the returns module to verify that counters are incremented appropriately.

def test_returns_flow() -> None:
    """Exercise the complete returns workflow: checkout, request return and approve.

    This test registers a user, performs a purchase, submits a return request
    for the completed sale and then approves it.  It prints intermediate
    results and surfaces any failures encountered.  After approval it
    inspects the RMA metrics to demonstrate that the counters and
    histograms have been updated.
    """
    print("\n[Returns] End‑to‑end return request and approval test")
    from app import RetailApp
    from metrics import RMA_REQUESTS_TOTAL, RMA_REFUNDS_TOTAL, RMA_PROCESSING_DURATION_SECONDS
    # Create a fresh application instance and seed with a product
    app = RetailApp()
    product_id = app.product_dao.add_product("ReturnWidget", 10.0, 3)
    # Register and login a user
    username = "returnuser"
    password = "pw"
    app.user_dao.register_user(username, password)
    app.login(username, password)
    # Add the product to the cart and perform checkout using a supported method
    app.add_to_cart(product_id, 1)
    ok, receipt = app.checkout("card")
    if not ok:
        print(f"  ⚠️  Checkout failed: {receipt}")
        return
    # Parse the sale ID from the first line of the receipt (format: 'Sale ID: <id>')
    try:
        first_line = receipt.split("\n", 1)[0]
        sale_id = int(first_line.split(":", 1)[1].strip())
    except Exception as parse_exc:
        print(f"  ⚠️  Could not determine sale ID from receipt: {parse_exc}")
        return
    # Submit a return request for the completed sale
    ok, msg = app.request_return(sale_id, "Changed my mind")
    if ok:
        print("  ✅ Return request submitted successfully")
    else:
        print(f"  ⚠️  Return request failed: {msg}")
        return
    # Retrieve the newly created return ID from the DAO
    returns_list = app.return_dao.list_returns(app._current_user_id)
    if not returns_list:
        print("  ⚠️  No return requests found after submission")
        return
    rma_id = returns_list[-1].id
    # Approve the return (simulate admin action)
    ok, msg2 = app.approve_return(rma_id)
    if ok:
        print("  ✅ Return approved and refund processed")
    else:
        print(f"  ⚠️  Return approval failed: {msg2}")
        return
    # Inspect RMA metrics values.  These structures are internal to the metrics
    # implementation; reading them directly demonstrates that counters and
    # histograms have been updated without relying on the HTTP /metrics endpoint.
    pending_count = RMA_REQUESTS_TOTAL._values.get(("Pending",), 0)
    approved_count = RMA_REQUESTS_TOTAL._values.get(("Approved",), 0)
    refund_count = RMA_REFUNDS_TOTAL._values.get(("card",), 0)
    total_obs = RMA_PROCESSING_DURATION_SECONDS.total_counts.get(tuple(), 0)
    print(f"  Metrics – pending: {pending_count}, approved: {approved_count}, refunds: {refund_count}, durations recorded: {total_obs}")


def test_returns_validation() -> None:
    """Verify that return requests enforce authentication, ownership and duplication rules.

    This test checks several negative scenarios: requesting a return when not
    logged in, attempting to return a sale belonging to another user,
    submitting a return for a sale that has already been refunded, and
    preventing duplicate return requests for the same sale.  Each case
    prints whether the expected validation behaviour is observed.
    """
    print("\n[Returns] Validation and rejection scenarios test")
    from app import RetailApp
    # Case 1: Not logged in
    app1 = RetailApp()
    ok, msg = app1.request_return(1, "No auth")
    if not ok and "logged in" in msg.lower():
        print("  ✅ Unauthenticated return request correctly rejected")
    else:
        print(f"  ⚠️  Unexpected result for unauthenticated request: ok={ok}, msg='{msg}'")
    # Case 2: User cannot return someone else's sale
    app2 = RetailApp()
    # Create two users and a product
    p_id = app2.product_dao.add_product("MultiUserWidget", 5.0, 2)
    app2.user_dao.register_user("userA", "pw")
    app2.user_dao.register_user("userB", "pw")
    # UserA logs in and completes a purchase
    app2.login("userA", "pw")
    app2.add_to_cart(p_id, 1)
    ok_checkout, receipt = app2.checkout("card")
    # Parse sale ID for reference
    sale_id = None
    if ok_checkout:
        try:
            sale_id = int(receipt.split("\n", 1)[0].split(":", 1)[1].strip())
        except Exception:
            sale_id = None
    # UserB attempts to request a return on UserA's sale
    app2.login("userB", "pw")
    ok_other, msg_other = app2.request_return(sale_id or 0, "Not my sale")
    if not ok_other and "only return your own" in msg_other.lower():
        print("  ✅ Return request for another user's sale correctly rejected")
    else:
        print(f"  ⚠️  Unexpected result for other-user return: ok={ok_other}, msg='{msg_other}'")
    # Case 3: Duplicate return requests are prevented
    app3 = RetailApp()
    pid = app3.product_dao.add_product("DupWidget", 3.0, 2)
    app3.user_dao.register_user("dupuser", "pw")
    app3.login("dupuser", "pw")
    app3.add_to_cart(pid, 1)
    ok_co, rec = app3.checkout("card")
    if not ok_co:
        print(f"  ⚠️  Checkout failed in duplicate test: {rec}")
        return
    try:
        sale_id_dup = int(rec.split("\n", 1)[0].split(":", 1)[1].strip())
    except Exception:
        sale_id_dup = 0
    # First return request
    ok_req1, msg1 = app3.request_return(sale_id_dup, "Reason1")
    # Duplicate request on same sale
    ok_req2, msg2 = app3.request_return(sale_id_dup, "Reason2")
    if ok_req1 and not ok_req2 and "already exists" in msg2.lower():
        print("  ✅ Duplicate return request prevented")
    else:
        print(f"  ⚠️  Unexpected duplicate return behaviour: first_ok={ok_req1}, second_ok={ok_req2}, msg2='{msg2}'")



def main() -> None:
    # Choose a high port to avoid conflicts with other services
    port = 8000
    print(f"Starting retail web server on port {port} ...")
    server_proc, _ = start_server(port)
    base_url = f"http://localhost:{port}"
    try:
        # # Availability & Performance
        # test_availability_performance(base_url)
        # # Security
        # test_security(base_url)
        # # Modifiability
        # test_modifiability()
        # # Performance (checkout)
        # test_performance_checkout()
        # # Integrability
        # test_integrability()
        # # Testability
        # test_testability(base_url)
        # # Usability
        # test_usability(base_url)
        # # Additional scenario tests
        # # Availability – database failover recovery
        # test_availability_db_failover()
        # # Security – partner feed authentication
        # test_partner_authentication(base_url)
        # # Modifiability – new partner format and payment extension
        # test_new_partner_format_modifiability()
        # test_payment_method_extension()
        # # Performance – high load and concurrent checkout
        # test_performance_high_load(base_url)
        # test_concurrent_checkout_performance()
        # # Integrability – new reseller and third‑party service
        # test_onboarding_new_reseller_integrability(base_url)
        # test_third_party_service_integration()
        # # Testability – flash sale replay and external service integration
        # test_testability_flash_sale_replay(base_url)
        # test_testability_external_service_integration()
        # # Usability – flash sale pricing and UI
        # test_flash_sale_pricing_and_ui(base_url)
        # Returns/RMA tests for new functionality
        test_returns_flow()
        test_returns_validation()
    finally:
        print("\nStopping server ...")
        stop_server(server_proc)


if __name__ == "__main__":
    main()