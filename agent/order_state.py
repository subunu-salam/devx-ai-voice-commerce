"""In-memory order state management for drive-thru voice ordering agent."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class OrderLineItem:
    """A single line item in an order."""

    item_id: str
    name: str
    quantity: int
    unit_price: int  # cents
    special_instructions: str = ""


@dataclass
class OrderState:
    """Manages in-memory order state during a voice session.

    All prices are in cents (integers) to avoid floating-point issues.
    """

    items: dict[str, OrderLineItem] = field(default_factory=dict)

    def add_item(self, item_id: str, name: str, quantity: int, unit_price: int, special_instructions: str = "") -> None:
        """Add an item or increment its quantity if already present."""
        if quantity < 1:
            raise ValueError("Quantity must be >= 1")
        if item_id in self.items:
            self.items[item_id].quantity += quantity
            if special_instructions:
                self.items[item_id].special_instructions = special_instructions
        else:
            self.items[item_id] = OrderLineItem(
                item_id=item_id,
                name=name,
                quantity=quantity,
                unit_price=unit_price,
                special_instructions=special_instructions,
            )

    def remove_item(self, item_id: str, quantity: int = 1) -> bool:
        """Reduce an item's quantity or remove it entirely.

        Args:
            item_id: Unique menu item identifier.
            quantity: Number to remove (defaults to 1).

        Returns:
            True if the item was found, False otherwise.
        """
        if item_id not in self.items:
            return False
        line = self.items[item_id]
        line.quantity -= quantity
        if line.quantity <= 0:
            del self.items[item_id]
        return True

    def cancel(self) -> None:
        """Clear all items from the order."""
        self.items.clear()

    def get_total(self) -> int:
        """Return the total price in cents."""
        return sum(item.quantity * item.unit_price for item in self.items.values())

    def is_empty(self) -> bool:
        """Return True if the order has no items."""
        return len(self.items) == 0

    def get_summary(self) -> dict:
        """Return a summary dict with items list and total."""
        return {
            "items": [
                {
                    "itemId": item.item_id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "unitPrice": item.unit_price,
                    **({"specialInstructions": item.special_instructions} if item.special_instructions else {}),
                }
                for item in self.items.values()
            ],
            "total": self.get_total(),
        }

    def place_order(self, user_id: str) -> dict:
        """Generate a complete order record for persistence.

        Args:
            user_id: The authenticated user's identifier.

        Returns:
            Dict with orderId (UUID), userId, items, total, status, and createdAt.
        """
        return {
            "orderId": str(uuid.uuid4()),
            "userId": user_id,
            "items": [
                {
                    "itemId": item.item_id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "unitPrice": item.unit_price,
                }
                for item in self.items.values()
            ],
            "total": self.get_total(),
            "status": "confirmed",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
