# payment_service.py
"""
Payment service simulation used by the minimal retail app.

- Strategy-based processing (card/cash/crypto).
- Retries with exponential backoff + jitter for transient failures.
- Simple circuit breaker (threshold + cooldown).
- Refund API for compensating rollback.
- Breaker status API for surfacing health in the UI/metrics.
"""

from __future__ import annotations

import random
import time
from typing import Tuple, Optional, Dict
from datetime import datetime, UTC, timedelta


# ---------- Strategy interfaces ----------

class PaymentStrategy:
    """Abstract base for payment strategies."""
    def process(self, amount: float) -> Tuple[bool, str]:  # (approved, ref_or_reason)
        raise NotImplementedError


class CardPaymentStrategy(PaymentStrategy):
    """Simulate a credit card payment that usually succeeds."""
    def __init__(self, success_rate: float = 0.5) -> None:
        self.success_rate = success_rate

    def process(self, amount: float) -> Tuple[bool, str]:
        # Randomized success to exercise retry/CB logic
        ok = random.random() < self.success_rate
        ref = f"TXN-{int(datetime.now(UTC).timestamp() * 1000)}"
        return (ok, ref if ok else "Card authorization failed")


class CashPaymentStrategy(PaymentStrategy):
    """Simulate a cash payment that fails (unsupported)."""
    def process(self, amount: float) -> Tuple[bool, str]:
        return False, "Cash payments are currently not accepted"


class CryptoPaymentStrategy(PaymentStrategy):
    """Simulate a cryptocurrency payment that succeeds."""
    def process(self, amount: float) -> Tuple[bool, str]:
        ref = f"CRYPTO-{int(datetime.now(UTC).timestamp() * 1000)}"
        return True, ref


# ---------- Payment service with retry + CB + refund ----------

class PaymentService:
    """
    Strategy-driven payment service with:
      - Retries (exponential backoff + jitter)
      - Circuit breaker (failure threshold + cooldown)
      - Refund endpoint for compensating rollback

    NOTE: This is *mock* code — no real gateways are called.
    """

    def __init__(
        self,
        always_approve: bool = False,
        failure_threshold: int = 3,
        cooldown_seconds: int = 30,
        max_attempts: int = 3,
        backoff_base: float = 0.25,   # seconds
        backoff_max: float = 2.0,     # cap per attempt
        backoff_jitter: float = 0.10  # +/- jitter seconds
    ) -> None:
        # Strategy registry
        self.strategies: dict[str, PaymentStrategy] = {}
        self.register_strategy("card", CardPaymentStrategy())
        self.register_strategy("cash", CashPaymentStrategy())
        self.register_strategy("crypto", CryptoPaymentStrategy())

        # Fallback for unknown methods
        self.always_approve = always_approve

        # Circuit breaker state
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failure_count = 0
        self._circuit_open_until: Optional[datetime] = None

        # Retry/backoff tuning
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.backoff_jitter = backoff_jitter

    # ----- strategy registry -----
    def register_strategy(self, method: str, strategy: PaymentStrategy) -> None:
        self.strategies[method.strip().lower()] = strategy

    # ----- circuit breaker helpers -----
    def _is_circuit_open(self) -> bool:
        if self._circuit_open_until is None:
            return False
        now = datetime.now(UTC)
        if now >= self._circuit_open_until:
            # cooldown elapsed -> close breaker
            self._circuit_open_until = None
            self._failure_count = 0
            return False
        return True

    def _trip_breaker(self) -> None:
        self._circuit_open_until = datetime.now(UTC) + timedelta(seconds=self.cooldown_seconds)

    def breaker_state(self) -> Dict[str, object]:
        """Expose breaker state for dashboards/logging."""
        return {
            "is_open": self._is_circuit_open(),
            "failure_count": self._failure_count,
            "open_until": self._circuit_open_until.isoformat() if self._circuit_open_until else None,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }

    # ----- backoff helper -----
    def _backoff_sleep(self, attempt_index: int) -> None:
        # attempt_index is 0-based; delay grows 0.25, 0.5, 1.0, ... up to cap
        delay = min(self.backoff_base * (2 ** attempt_index), self.backoff_max)
        # add small +/- jitter
        jitter = (random.random() * 2 - 1) * self.backoff_jitter
        time.sleep(max(0.0, delay + jitter))

    # ----- main APIs -----
    def process_payment(self, amount: float, method: str) -> Tuple[bool, str]:
        """Attempt a payment with retries and CB."""
        # Circuit open? Hard-fail fast.
        if self._is_circuit_open():
            return False, "Payment service unavailable (circuit breaker open)"

        method_lower = method.strip().lower()
        strategy = self.strategies.get(method_lower)

        last_ref_or_reason = "Unknown error"
        for attempt in range(self.max_attempts):
            if strategy:
                approved, ref_or_reason = strategy.process(amount)
            else:
                # Unknown method: configurable fallback
                ref_or_reason = f"TXN-{int(datetime.now(UTC).timestamp() * 1000)}"
                approved = True if self.always_approve else random.choice([True, False])

            if approved:
                self._failure_count = 0
                return True, ref_or_reason

            # failure
            last_ref_or_reason = ref_or_reason
            self._failure_count += 1

            # trip breaker once threshold reached
            if self._failure_count >= self.failure_threshold:
                self._trip_breaker()
                return False, last_ref_or_reason

            # retry (if more attempts left)
            if attempt < self.max_attempts - 1:
                self._backoff_sleep(attempt)

        return False, last_ref_or_reason

    def refund_payment(self, reference: str, amount: float) -> Tuple[bool, str]:
        """
        Mock refund used for compensating rollback (e.g., DB commit fails
        *after* payment approval). Always succeeds here.
        """
        # In real life: call gateway refund endpoint; idempotently handle repeats.
        return True, f"REFUND-{reference}"
