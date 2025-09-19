"""
Payment service simulation used by the minimal retail app.

This module defines a ``PaymentService`` class that mimics the
behaviour of a payment gateway.  It exposes a ``process_payment``
method returning an approval flag and a reference string.  The
implementation here never integrates with real financial systems; it
simply returns success for demonstration purposes.  This decouples
payment processing from the rest of the application and makes it easy
to swap in a real implementation if desired.
"""

import datetime
import random
from typing import Tuple
from datetime import datetime, UTC

class PaymentService:
    """Simplified payment service that simulates approval or rejection."""

    def __init__(self, always_approve: bool = True) -> None:
        """Initialize the service.

        :param always_approve: When true, all payments will succeed.
            When false, the service will randomly approve or decline
            payments to test alternate flows.
        """
        self.always_approve = always_approve

    def process_payment(self, amount: float, method: str) -> Tuple[bool, str]:
        """Simulate payment processing.

        :param amount: The amount to charge.
        :param method: Payment method chosen by the user, e.g. 'Cash' or 'Card'.
        :returns: Tuple of (approved, reference).  ``approved`` is True
            if the payment succeeds, False otherwise.  ``reference``
            contains a mock transaction ID or a reason for decline.

        The default behaviour is governed by the ``always_approve`` flag.  In
        this assignment implementation we override that behaviour to
        satisfy the requirement that cash payments always fail and card
        payments always succeed.  Additional or unknown payment
        methods fall back to the behaviour specified by ``always_approve``.
        """
        # Normalise method to lower case for comparison
        method_lower = method.strip().lower()
        # Special handling for assignment requirements
        if method_lower == "cash":
            # Always fail cash payments
            return False, "Cash payments are currently not accepted"
        if method_lower == "card":
            # Always succeed card payments
            ref = f"TXN-{int(datetime.now(UTC).timestamp() * 1000)}"
            return True, ref
        # For other methods, defer to the always_approve flag
        if self.always_approve:
            ref = f"TXN-{int(datetime.now(UTC).timestamp() * 1000)}"
            return True, ref
        else:
            success = random.choice([True, False])
            ref = f"TXN-{int(datetime.now(UTC).timestamp() * 1000)}"
            return success, ref