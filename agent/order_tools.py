"""Order management tools for the drive-thru voice ordering agent.

Each tool updates in-memory OrderState and returns the updated order state.
place_order persists the order to DynamoDB.
Module-level variables can be overridden for testing via set_tables/set_order_state.
"""

import os

import boto3
from strands import tool

try:
    from agent.order_state import OrderState
    from agent.ui_events import order_confirmed_event, order_update_event
except ModuleNotFoundError:
    from order_state import OrderState
    from ui_events import order_confirmed_event, order_update_event

# Module-level state — injectable for testing.
_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_menu_table = _dynamodb.Table(os.environ.get("MENU_TABLE_NAME", "DriveThruMenu"))
_orders_table = _dynamodb.Table(os.environ.get("ORDERS_TABLE_NAME", "DriveThruOrders"))
_order_state = OrderState()


def set_tables(menu_table, orders_table) -> None:
    """Override DynamoDB table resources (used in tests)."""
    global _menu_table, _orders_table
    _menu_table = menu_table
    _orders_table = orders_table


def set_order_state(state: OrderState) -> None:
    """Override the in-memory order state (used in tests)."""
    global _order_state
    _order_state = state


def get_order_state() -> OrderState:
    """Return the current order state."""
    return _order_state


@tool
def add_to_order(item_id: str, category_id: str, quantity: int = 1) -> dict:
    """Adds a menu item to the current order.

    Validates the item exists in the menu table and that quantity >= 1,
    then adds it to the in-memory order state.

    Args:
        item_id: The menu item identifier.
        category_id: The category the item belongs to.
        quantity: Number of items to add (must be >= 1).

    Returns:
        dict with updated order summary, or error details.
    """
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}

    # Validate item exists in menu table
    response = _menu_table.get_item(
        Key={
            "PK": f"CATEGORY#{category_id}",
            "SK": f"ITEM#{item_id}",
        }
    )
    menu_item = response.get("Item")
    if not menu_item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}

    name = menu_item.get("name", "")
    unit_price = int(menu_item.get("price", 0))

    _order_state.add_item(item_id, name, quantity, unit_price)
    summary = _order_state.get_summary()
    summary["ui_event"] = order_update_event(summary)
    return summary


@tool
def remove_from_order(item_id: str, quantity: int = 1) -> dict:
    """Removes a menu item from the current order.

    Reduces the item quantity or removes it entirely if quantity reaches zero.

    Args:
        item_id: The menu item identifier.
        quantity: Number of items to remove (defaults to 1).

    Returns:
        dict with updated order summary, or error if item not in order.
    """
    removed = _order_state.remove_item(item_id, quantity)
    if not removed:
        return {"error": f"Item '{item_id}' is not in the current order."}
    summary = _order_state.get_summary()
    summary["ui_event"] = order_update_event(summary)
    return summary


@tool
def get_order_summary() -> dict:
    """Returns the current order summary with all items, quantities, and total.

    Returns:
        dict with items list and total price in cents.
    """
    summary = _order_state.get_summary()
    summary["ui_event"] = order_update_event(summary)
    return summary


@tool
def place_order(user_id: str) -> dict:
    """Finalizes the order, persists to DynamoDB, and returns the order number.

    Generates a UUID order number, writes the complete order record to the
    DynamoDB orders table, and clears the in-memory order state.

    Args:
        user_id: The authenticated user's identifier.

    Returns:
        dict with the complete order record including orderId, or error if empty.
    """
    if _order_state.is_empty():
        return {"error": "Cannot place an empty order."}

    order_record = _order_state.place_order(user_id)

    # Persist to DynamoDB
    _orders_table.put_item(Item=order_record)

    # Clear in-memory state after successful persistence
    _order_state.cancel()

    order_record["ui_event"] = order_confirmed_event(order_record)
    return order_record


@tool
def cancel_order() -> dict:
    """Clears all items from the current order.

    Returns:
        dict confirming cancellation with empty order summary.
    """
    _order_state.cancel()
    summary = {"message": "Order cancelled.", **_order_state.get_summary()}
    summary["ui_event"] = order_update_event(_order_state.get_summary())
    return summary
