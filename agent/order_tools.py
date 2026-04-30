"""Order management tools for the drive-thru voice ordering agent."""

import logging
import os

import boto3
from strands import tool

try:
    from agent.order_state import OrderState
except ModuleNotFoundError:
    from order_state import OrderState

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


@tool
def add_to_order(item_id: str, category_id: str, quantity: int = 1, special_instructions: str = "") -> dict:
    """Adds a menu item to the current order.

    Args:
        item_id: The menu item identifier.
        category_id: The category the item belongs to.
        quantity: Number of items to add (must be >= 1).
        special_instructions: Customer notes like "no pickles" or "extra sauce".
    """
    logger.info("add_to_order: %s %s qty=%s notes=%s", item_id, category_id, quantity, special_instructions)
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}
    response = _menu_table.get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    menu_item = response.get("Item")
    if not menu_item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}
    _order_state.add_item(item_id, menu_item.get("name", ""), quantity, int(menu_item.get("price", 0)), special_instructions)
    summary = _order_state.get_summary()
    return summary


@tool
def remove_from_order(item_id: str, quantity: int = 1) -> dict:
    """Removes a menu item from the current order."""
    if not _order_state.remove_item(item_id, quantity):
        return {"error": f"Item '{item_id}' is not in the current order."}
    summary = _order_state.get_summary()
    return summary


@tool
def get_order_summary(tool_context=None) -> dict:
    """Returns the current order summary."""
    summary = _order_state.get_summary()
    return summary


@tool
def place_order(user_id: str) -> dict:
    """Finalizes the order, persists to DynamoDB, returns order number."""
    if _order_state.is_empty():
        return {"error": "Cannot place an empty order."}
    order_record = _order_state.place_order(user_id)
    _orders_table.put_item(Item=order_record)
    logger.info(
        "ORDER_PLACED: orderId=%s userId=%s total=%s itemCount=%s",
        order_record["orderId"],
        order_record["userId"],
        order_record["total"],
        len(order_record["items"]),
    )
    _order_state.cancel()
    return order_record


@tool
def cancel_order(tool_context=None) -> dict:
    """Clears all items from the current order."""
    logger.info("ORDER_CANCELLED: itemCount=%s", len(_order_state.items))
    _order_state.cancel()
    summary = {"message": "Order cancelled.", **_order_state.get_summary()}
    return summary
