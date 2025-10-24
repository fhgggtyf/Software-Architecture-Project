"""Simple metrics library using only the Python standard library.

This module provides a minimal implementation of counters, gauges, and
histograms similar to Prometheus, but without any external dependencies.
Metrics are collected in global objects and can be exported in the
Prometheus text exposition format.  Use this module instead of a
third‑party metrics client when only the standard library is allowed.
"""

from collections import defaultdict
from threading import Lock
from typing import Dict, Iterable, List, Tuple


class Metric:
    """Base class for all metrics."""

    def __init__(self, name: str, description: str, label_names: Iterable[str]):
        self.name = name
        self.description = description
        self.label_names = list(label_names)
        # Protect metric updates in multi‑threaded contexts
        self._lock = Lock()
        # register metric in global registry
        _METRIC_REGISTRY.append(self)

    def _format_labels(self, label_values: Tuple[str, ...]) -> str:
        if not self.label_names:
            return ""
        pairs = [f'{name}="{value}"' for name, value in zip(self.label_names, label_values)]
        return "{" + ",".join(pairs) + "}"

    def to_prometheus(self) -> List[str]:
        """Return a list of strings in Prometheus exposition format."""
        raise NotImplementedError


class Counter(Metric):
    """Simple counter metric.  Call ``inc()`` to increment by 1.

    The ``inc`` method accepts keyword arguments matching the label
    names provided at construction time.  Example:

    ``COUNTER.inc(method="GET", status="200")``
    """

    def __init__(self, name: str, description: str, label_names: Iterable[str]):
        super().__init__(name, description, label_names)
        # Map from label tuple to integer count
        self._values: Dict[Tuple[str, ...], int] = defaultdict(int)

    def inc(self, **labels: str) -> None:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            self._values[label_tuple] += 1

    def to_prometheus(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} counter"]
        with self._lock:
            for label_values, value in self._values.items():
                label_str = self._format_labels(label_values)
                lines.append(f"{self.name}{label_str} {value}")
        return lines


class Gauge(Metric):
    """Gauge metric representing a single numeric value or labeled values.

    Use ``set()`` to assign a value.  Gauges may go up or down.
    """

    def __init__(self, name: str, description: str, label_names: Iterable[str]):
        super().__init__(name, description, label_names)
        self._values: Dict[Tuple[str, ...], float] = {}

    def set(self, value: float, **labels: str) -> None:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            self._values[label_tuple] = float(value)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        """Increment gauge by amount (default 1)."""
        label_tuple = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            self._values[label_tuple] = self._values.get(label_tuple, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        """Decrement gauge by amount (default 1)."""
        self.inc(-amount, **labels)

    def to_prometheus(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} gauge"]
        with self._lock:
            for label_values, value in self._values.items():
                label_str = self._format_labels(label_values)
                lines.append(f"{self.name}{label_str} {value}")
        return lines


class Histogram(Metric):
    """Histogram metric with configurable buckets.

    Buckets must be an ascending list of upper bounds (float).  Values
    greater than the largest bucket are counted in the ``+Inf`` bucket.
    ``observe(value, **labels)`` records a new observation.
    """

    def __init__(self, name: str, description: str, label_names: Iterable[str], buckets: Iterable[float]):
        super().__init__(name, description, label_names)
        # Ensure buckets sorted and copy to list
        self.buckets = sorted(float(b) for b in buckets)
        # Data structures per label tuple
        # counts[label_tuple][i] = count of observations <= buckets[i]
        self.counts: Dict[Tuple[str, ...], List[int]] = defaultdict(lambda: [0] * len(self.buckets))
        self.sums: Dict[Tuple[str, ...], float] = defaultdict(float)
        self.total_counts: Dict[Tuple[str, ...], int] = defaultdict(int)

    def observe(self, value: float, **labels: str) -> None:
        label_tuple = tuple(labels.get(k, "") for k in self.label_names)
        with self._lock:
            # update buckets
            for idx, b in enumerate(self.buckets):
                if value <= b:
                    self.counts[label_tuple][idx] += 1
            # always increment the +Inf bucket count by incrementing total count
            self.total_counts[label_tuple] += 1
            self.sums[label_tuple] += float(value)

    def to_prometheus(self) -> List[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} histogram"]
        with self._lock:
            for label_values in self.total_counts.keys():
                label_str = self._format_labels(label_values)
                cumulative = 0
                for idx, upper in enumerate(self.buckets):
                    cumulative += self.counts[label_values][idx]
                    # Build label string with 'le' appended; if no original labels, create braces.
                    # When label_str is non-empty, remove its trailing '}' and append the new le
                    # key-value, then close the brace separately.  This avoids nested braces in
                    # f-strings that would lead to a syntax error.
                    if label_str:
                        # Example: label_str = '{endpoint="/cart"}' -> '{endpoint="/cart",le="0.5"}'
                        bucket_labels = label_str[:-1] + f',le="{upper}"' + '}'
                    else:
                        bucket_labels = '{le="' + str(upper) + '"}'
                    lines.append(f"{self.name}_bucket{bucket_labels} {cumulative}")
                # +Inf bucket
                total = self.total_counts[label_values]
                if label_str:
                    inf_labels = label_str[:-1] + ',le="+Inf"}'
                else:
                    inf_labels = '{le="+Inf"}'
                lines.append(f"{self.name}_bucket{inf_labels} {total}")
                # sum and count
                lines.append(f"{self.name}_sum{label_str} {self.sums[label_values]}")
                lines.append(f"{self.name}_count{label_str} {total}")
        return lines


_METRIC_REGISTRY: List[Metric] = []


def generate_metrics_text() -> bytes:
    """Generate the text representation of all registered metrics."""
    lines: List[str] = []
    for metric in _METRIC_REGISTRY:
        lines.extend(metric.to_prometheus())
    return "\n".join(lines).encode("utf-8")


# -----------------------------------------------------------------------------
# Define global metrics used by the retail application.
# Labels should match the usage in the code (see app_web.py and app.py).
# -----------------------------------------------------------------------------

# Total number of HTTP requests received, labelled by endpoint, method, and HTTP status code
HTTP_REQUESTS_TOTAL = Counter(
    name="http_requests_total",
    description="Total number of HTTP requests",
    label_names=["endpoint", "method", "status"],
)

# Histogram of HTTP request latencies in seconds, labelled by endpoint.  The
# buckets are chosen to cover fast requests (<0.2s) up to slower ones.
HTTP_REQUEST_LATENCY_SECONDS = Histogram(
    name="http_request_latency_seconds",
    description="HTTP request latency in seconds",
    label_names=["endpoint"],
    buckets=[0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
)

# Histogram measuring the duration of the checkout operation in seconds, labelled by payment method
CHECKOUT_DURATION_SECONDS = Histogram(
    name="checkout_duration_seconds",
    description="Duration of checkout operations in seconds",
    label_names=["payment_method"],
    buckets=[0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0],
)

# Gauge indicating whether the payment service circuit breaker is open (1) or closed (0)
CIRCUIT_BREAKER_OPEN = Gauge(
    name="circuit_breaker_open",
    description="Payment circuit breaker state (1=open, 0=closed)",
    label_names=[],
)

# Counter for checkout errors, labelled by type
CHECKOUT_ERROR_TOTAL = Counter(
    name="checkout_error_total",
    description="Total number of checkout errors, labelled by type",
    label_names=["type"],
)