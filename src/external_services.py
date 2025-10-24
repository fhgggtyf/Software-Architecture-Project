"""
Mock external service integrations for inventory management, shipping and
reseller APIs.

To satisfy the integrability scenarios, this module defines simple
interfaces for interacting with third‑party systems.  In a real system
these classes would make HTTP calls or use SDKs to integrate with
external services.  Here they are implemented as no‑ops or stubs to
demonstrate the intended usage.
"""

from __future__ import annotations

from typing import List, Dict, Any


class InventoryService:
    """Simulate an external inventory management service.

    In a real deployment this class would update the merchant's stock
    levels in an enterprise resource planning (ERP) system or other
    warehouse management system.  The ``update_inventory`` method is
    called after a sale has been recorded in the local database.

    This mock implementation logs each call and introduces a tiny delay
    to better simulate network latency.  Returning True indicates
    success.  Tests looking for evidence of external integration can
    examine stdout for these messages.
    """

    def update_inventory(self, sale_id: int, items: List[Any]) -> bool:
        # Log the invocation for testing purposes.  Printing to stdout
        # provides a visible side effect without requiring external
        # libraries.  In a real integration this would be an HTTP call.
        try:
            import time
            import random
            print(f"[InventoryService] updating inventory for sale {sale_id} ({len(items)} items)")
            # Sleep for a few tens of milliseconds to simulate latency
            time.sleep(0.05 + random.random() * 0.05)
        except Exception:
            # If printing or sleeping fails (should not happen), continue
            pass
        return True


class ShippingService:
    """Simulate an external shipping/carrier service.

    After a successful sale and payment, orders often need to be
    dispatched via a courier.  The ``create_shipment`` method would
    normally call the shipping provider's API to generate a tracking
    number and schedule pickup.  Here we log the call, generate a
    pseudo tracking number and introduce a tiny delay.  Returning True
    indicates that shipment creation succeeded.
    """

    def create_shipment(self, sale_id: int, user_id: int, items: List[Any]) -> bool:
        try:
            import time
            import random
            tracking_number = f"SHIP-{int(time.time() * 1000)}"
            print(f"[ShippingService] creating shipment for sale {sale_id} user {user_id}")
            # Sleep briefly to simulate network latency
            time.sleep(0.05 + random.random() * 0.05)
            print(f"[ShippingService] tracking number: {tracking_number}")
        except Exception:
            pass
        return True


class ResellerAPIAdapter:
    """Base class for reseller adapters.

    New resellers can be integrated by implementing this interface and
    registering an instance with the ``ResellerAPIGateway``.  Each
    adapter should translate the generic order format into the
    reseller's proprietary API calls.
    """

    def place_order(self, order: Dict[str, Any]) -> bool:
        raise NotImplementedError


class GenericResellerAdapter(ResellerAPIAdapter):
    """A trivial adapter that always succeeds.

    This adapter can be used as a stand‑in for a real reseller API.  It
    simply returns True for any order placed.  You can extend this
    class to simulate failures or more complex behaviour.
    """

    def place_order(self, order: Dict[str, Any]) -> bool:
        # Accept all orders unconditionally
        return True


class ResellerAPIGateway:
    """A registry and facade for reseller API adapters.

    Clients interact with this gateway rather than individual reseller
    adapters.  Adapters can be registered by name and are looked up
    dynamically when placing orders.  This decouples business logic
    from the specifics of each reseller's API.
    """

    def __init__(self) -> None:
        self.adapters: Dict[str, ResellerAPIAdapter] = {}

    def register_adapter(self, name: str, adapter: ResellerAPIAdapter) -> None:
        self.adapters[name.strip().lower()] = adapter

    def place_order(self, name: str, order: Dict[str, Any]) -> bool:
        """Place an order through the named reseller adapter.

        If no adapter is registered for the given name, this method
        falls back to the "default" adapter if available.  It also
        logs the adapter selection for test visibility.

        Args:
            name: Reseller adapter name.  Case-insensitive.
            order: Order payload passed to the adapter.

        Returns:
            True if the adapter processed the order successfully.

        Raises:
            ValueError: If neither the named adapter nor a default
                adapter exists.
        """
        key = name.strip().lower()
        adapter = self.adapters.get(key) or self.adapters.get("default")
        if not adapter:
            raise ValueError(f"No adapter registered for reseller '{name}' and no default adapter present")
        try:
            print(f"[ResellerAPIGateway] Using adapter '{key or 'default'}' for order {order}")
        except Exception:
            pass
        return adapter.place_order(order)


# Expose default instances for convenience
inventory_service = InventoryService()
shipping_service = ShippingService()
reseller_gateway = ResellerAPIGateway()

# Register a default generic reseller adapter.  This enables calls to
# ``reseller_gateway.place_order("default", order)`` to succeed without
# requiring additional configuration.  Integrators can register their own
# adapters for specific resellers by calling ``reseller_gateway.register_adapter``.
reseller_gateway.register_adapter("default", GenericResellerAdapter())