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
            contains a mock transaction ID or failure code.
        """
        if self.always_approve:
            ref = f"PAY-{int(datetime.datetime.utcnow().timestamp()*1000)}"
            return True, ref
        else:
            success = random.choice([True, False])
            ref = f"PAY-{int(datetime.datetime.utcnow().timestamp()*1000)}"
            return success, ref