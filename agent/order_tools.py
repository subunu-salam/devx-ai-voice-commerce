"""Order management tools for the drive-thru voice ordering agent."""

import logging
import os

import boto3
from strands import tool

try:
    from agent.order_state import OrderState
    from agent.ui_events import order_confirmed_event, order_update_event
    from agent.ui_sender import send_ui_event
except ModuleNotFoundError:
    from order_state import OrderState
    from ui_events import order_confirmed_event, order_update_event
    from ui_sender import send_ui_event

logger = logging.getLogger(__name__)

_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_menu_table = _dynamodb.Table(os.environ.get("MENU_TABLE_NAME", "DriveThruMenu"))
_orders_table = _dynamodb.Table(os.environ.get("ORDERS_TABLE_NAME", "DriveThruOrders"))
_order_state = OrderState()


def set_tables(menu_table, orders_table) -> None:
    global _menu_table, _orders_table
    _menu_table = menu_table
    _orders_table = orders_table


def set_order_state(state: OrderState) -> None:
    global _order_state
    _order_state = state


def get_order_state() -> OrderState:
    return _order_state


@tool(context=True)
def add_to_order(item_id: str, category_id: str, quantity: int = 1, tool_context=None) -> dict:
    """Adds a menu item to the current order.

    Args:
        item_id: The menu item identifier.
        category_id: The category the item belongs to.
        quantity: Number of items to add (must be >= 1).
    """
    logger.info("add_to_order: item_id=%s, category_id=%s, qty=%s", item_id, category_id, quantity)
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}

    response = _menu_table.get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    menu_item = response.get("Item")
    if not menu_item:
        logger.warning("add_to_order: item not found")
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}

    _order_state.add_item(item_id, menu_item.get("name", ""), quantity, int(menu_item.get("price", 0)))
    summary = _order_state.get_summary()
    ui_evt = order_update_event(summary)
    send_ui_event(ui_evt, tool_context)
    return summary


@tool(context=True)
def remove_from_order(item_id: str, quantity: int = 1, tool_context=None) -> dict:
    """Removes a menu item from the current order.

    Args:
        item_id: The menu item identifier.
        quantity: Number of items to remove (defaults to 1).
    """
    if not _order_state.remove_item(item_id, quantity):
        return {"error": f"Item '{item_id}' is not in the current order."}
    summary = _order_state.get_summary()
    ui_evt = order_update_event(summary)
    send_ui_event(ui_evt, tool_context)
    return summary


@tool(context=True)
def get_order_summary(tool_context=None) -> dict:
    """Returns the current order summary with all items, quantities, and total."""
    summary = _order_state.get_summary()
    ui_evt = order_update_event(summary)
    send_ui_event(ui_evt, tool_context)
    return summary


@tool(context=True)
def place_order(user_id: str, tool_context=None) -> dict:
    """Finalizes the order, persists to DynamoDB, and returns the order number.

    Args:
        user_id: The authenticated user's identifier.
    """
    if _order_state.is_empty():
        return {"error": "Cannot place an empty order."}
    order_record = _order_state.place_order(user_id)
    _orders_table.put_item(Item=order_record)
    _order_state.cancel()
    ui_evt = order_confirmed_event(order_record)
    send_ui_event(ui_evt, tool_context)
    return order_record


@tool(context=True)
def cancel_order(tool_context=None) -> dict:
    """Clears all items from the current order."""
    _order_state.cancel()
    summary = {"message": "Order cancelled.", **_order_state.get_summary()}
    ui_evt = order_update_event(_order_state.get_summary())
    send_ui_event(ui_evt, tool_context)
    return summary
