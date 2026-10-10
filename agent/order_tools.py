# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Order management tools for the VoiceBite voice ordering agent."""

import json
import logging
import os
import re
import secrets
from decimal import Decimal

import boto3
from strands import tool

try:
    from agent.order_state import OrderState
    from agent.ui_state_manager import set_ui_state, get_ui_state
except ModuleNotFoundError:
    from order_state import OrderState
    from ui_state_manager import set_ui_state, get_ui_state

CURRENCY = "AED"  # shown and spoken as UAE dirhams
_SAUCES = ("ketchup", "mustard", "mayo", "bbq sauce", "chipotle mayo", "special sauce")


def _load_shop_config():
    """Use the admin panel's settings module if it has been added to the project."""
    import importlib
    for module in ("agent.shop_config", "shop_config"):
        try:
            return importlib.import_module(module)
        except ModuleNotFoundError:
            continue
    return None


_shop = _load_shop_config()
if _shop:
    get_burger_config, current_location = _shop.get_burger_config, _shop.current_location
    note_added, note_order = _shop.note_added, _shop.note_order
else:
    # No admin panel installed: burger prices come from the constants further down this file.
    def get_burger_config() -> dict:
        extras = {k: v for k, v in _TOPPING_PRICES.items() if k not in ("beef patty", "chicken patty")}
        return {
            "basePrice": _CUSTOM_BURGER_BASE_PRICE,
            "toppings": {k: v for k, v in extras.items() if k not in _SAUCES},
            "sauces": {k: v for k, v in extras.items() if k in _SAUCES},
        }

    def current_location() -> str:
        return "main"

    def note_added(item_id: str) -> None:
        pass

    def note_order(order_id: str, total: int) -> None:
        pass

logger = logging.getLogger(__name__)


# VOICE_PRICE_MODE: "checkout" (default) keeps prices out of the conversation until the order summary, so choosing is
# quick; the prices stay visible on the customer's screen. "always" also says the item price and running total each time.
PRICE_MODE = os.getenv("VOICE_PRICE_MODE", "checkout").strip().lower()
_MID_ORDER_PRICES = ("itemPriceText", "total", "totalText", "price", "priceText")


def _while_choosing(result: dict) -> dict:
    """Results of add/remove while the customer is still choosing: no prices to read out in checkout mode."""
    if PRICE_MODE == "always":
        return result
    quiet = {k: v for k, v in result.items() if k not in _MID_ORDER_PRICES}
    quiet["say"] = "Confirm in a few words without any price, e.g. 'Done, one Cheeseburger. Anything else?'. The total is said only at checkout."
    return quiet


def _spoken(amount: int) -> str:
    """The amount exactly as the attendant should say it, so speech and screen always match."""
    return f"{int(amount) / 100:.2f} dirhams"


def _show_order_on_screen() -> dict:
    """Push the real order and its total to the customer's screen; returns the summary."""
    summary = _order_state.get_summary()
    try:
        current = get_ui_state()
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        set_ui_state(current)
    except Exception as e:
        logger.warning("could not update the screen: %s", e)
    return summary


def _sanitize_result(result: dict) -> dict:
    """Ensure tool result is JSON-serializable with only basic Python types."""
    def _convert(obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        if isinstance(obj, dict):
            return {str(k): _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(i) for i in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        return str(obj)

    sanitized = _convert(result)
    try:
        json.dumps(sanitized)
    except (TypeError, ValueError) as e:
        logger.error("Tool result not JSON-serializable: %s | result: %s", e, sanitized)
        return {"status": "ok"}
    return sanitized

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
    """Adds a menu item to the current order and updates the customer's screen.

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
    if menu_item.get("available") is False:
        return {"error": f"'{menu_item.get('name', item_id)}' is sold out right now. Apologise and offer something else."}
    _order_state.add_item(item_id, menu_item.get("name", ""), quantity, int(menu_item.get("price", 0)), special_instructions)
    note_added(item_id)
    summary = _order_state.get_summary()

    # Auto-update the UI: refresh the order display (don't highlight — that opens the modal)
    try:
        current = get_ui_state()
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        set_ui_state(current)
    except Exception as e:
        logger.warning("add_to_order: failed to auto-update UI: %s", e)

    # Return minimal confirmation to keep tool result small for Nova Sonic
    return _sanitize_result(_while_choosing({
        "status": "added",
        "item": str(menu_item.get("name", "")),
        "quantity": quantity,
        "itemPriceText": _spoken(int(menu_item.get("price", 0))),
        "total": summary["total"],
        "totalText": _spoken(summary["total"]),
    }))


@tool
def remove_from_order(item_id: str, quantity: int = 1) -> dict:
    """Removes a menu item from the current order."""
    if not _order_state.remove_item(item_id, quantity):
        return {"error": f"Item '{item_id}' is not in the current order."}
    summary = _show_order_on_screen()
    return _sanitize_result(_while_choosing({"status": "removed", "item": item_id, "total": summary["total"], "totalText": _spoken(summary["total"]), "itemCount": len(summary["items"])}))


@tool
def get_order_summary(tool_context=None) -> dict:
    """Returns the current order summary."""
    summary = _show_order_on_screen()
    items_brief = [f"{i['name']} x{i['quantity']}" for i in summary["items"]]
    return _sanitize_result({"items": items_brief, "total": summary["total"], "totalText": _spoken(summary["total"])})


@tool
def place_order(vehicle_number: str = "", user_id: str = "guest") -> dict:
    """Finalizes the order, persists to DynamoDB, returns order number.

    Ask the customer for their vehicle plate number as the LAST question, then call this.

    Args:
        vehicle_number: The customer's vehicle plate number, e.g. "D 12345". Required: staff use it to bring the order to the right car.
        user_id: The customer identifier. Defaults to "guest".
    """
    if _order_state.is_empty():
        return {"error": "Cannot place an empty order."}
    vehicle = re.sub(r"[^A-Za-z0-9 ]", " ", str(vehicle_number or "")).upper()
    vehicle = re.sub(r"\s+", " ", vehicle).strip()[:20]
    if len(vehicle.replace(" ", "")) < 2:
        return {"error": "The vehicle plate number is missing. Ask the customer for their vehicle plate number, then call place_order again with vehicle_number."}
    order_record = _order_state.place_order(user_id)
    order_record["vehicleNumber"] = vehicle          # staff serve the order to this car
    order_record["locationId"] = current_location()  # which store took the order
    order_record["status"] = "received"              # first step on the kitchen display
    order_record["trackToken"] = secrets.token_urlsafe(16)  # lets this customer's phone, and nobody else, follow the order
    _orders_table.put_item(Item=order_record)
    note_order(order_record["orderId"], order_record["total"])
    logger.info(
        "ORDER_PLACED: orderId=%s userId=%s total=%s itemCount=%s",
        order_record["orderId"],
        order_record["userId"],
        order_record["total"],
        len(order_record["items"]),
    )
    _order_state.cancel()

    # Update UI to show order confirmation page
    try:
        current = get_ui_state()
        current["orderConfirmed"] = True
        current["orderNumber"] = order_record["orderId"]
        current["orderTotal"] = order_record["total"]
        current["vehicleNumber"] = vehicle
        current["trackToken"] = order_record["trackToken"]
        current["shownItems"] = []
        current["burgerBuilder"] = None
        current["highlightedItem"] = None
        current["highlightedCategory"] = None
        set_ui_state(current)
    except Exception as e:
        logger.warning("place_order: failed to update UI: %s", e)

    return _sanitize_result({"status": "confirmed", "orderId": order_record["orderId"], "vehicleNumber": vehicle,
                             "total": order_record["total"], "totalText": _spoken(order_record["total"])})


@tool
def cancel_order(tool_context=None) -> dict:
    """Clears all items from the current order."""
    logger.info("ORDER_CANCELLED: itemCount=%s", len(_order_state.items))
    _order_state.cancel()
    _show_order_on_screen()
    return _sanitize_result({"status": "cancelled"})


# --- Custom Burger Builder ---
# Prices are edited in the admin panel and read from shop_config.get_burger_config().
# The constants below are only the starting defaults, kept for reference and tests.

_CUSTOM_BURGER_BASE_PRICE = 899  # AED 8.99 for patty + bun
_TOPPING_PRICES = {
    # Patty options (included in base)
    "beef patty": 0,
    "chicken patty": 0,
    # Cheese (+1.00)
    "american cheese": 100,
    "cheddar cheese": 100,
    "pepper jack cheese": 100,
    "swiss cheese": 100,
    # Premium toppings (+1.50)
    "bacon": 150,
    "avocado": 150,
    "fried egg": 150,
    # Free toppings
    "lettuce": 0,
    "tomato": 0,
    "onion": 0,
    "pickles": 0,
    "jalapeños": 0,
    "mushrooms": 0,
    # Sauces (free)
    "ketchup": 0,
    "mustard": 0,
    "mayo": 0,
    "bbq sauce": 0,
    "chipotle mayo": 0,
    "special sauce": 0,
}


@tool
def build_custom_burger(patty: str, toppings: list, sauces: list = None, quantity: int = 1) -> dict:
    """Build a custom burger with chosen patty, toppings, and sauces. Adds it to the order.

    Args:
        patty: The patty type — "beef patty" or "chicken patty".
        toppings: List of toppings, using the names in the BUILD YOUR OWN BURGER section of your instructions.
        sauces: List of sauces, using the names in your instructions. Defaults to none.
        quantity: Number of custom burgers (default 1).

    Returns:
        Summary with the custom burger details, price breakdown, and updated order.
    """
    if sauces is None:
        sauces = []
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}

    config = get_burger_config()
    base_price = int(config.get("basePrice", _CUSTOM_BURGER_BASE_PRICE))
    topping_prices = {str(k).lower(): int(v) for k, v in (config.get("toppings") or {}).items()}
    sauce_prices = {str(k).lower(): int(v) for k, v in (config.get("sauces") or {}).items()}

    # Validate patty
    patty = patty.lower().strip()
    if patty not in ("beef patty", "chicken patty"):
        return {"error": f"Invalid patty '{patty}'. Choose 'beef patty' or 'chicken patty'."}

    # Calculate price
    total_price = base_price
    selected_toppings = []
    price_breakdown = [{"item": f"Custom burger ({patty})", "price": base_price}]

    for topping in toppings:
        topping = topping.lower().strip()
        if topping not in topping_prices:
            return {"error": f"Unknown topping '{topping}'. Available: {', '.join(sorted(topping_prices))}"}
        price = topping_prices[topping]
        total_price += price
        selected_toppings.append(topping)
        if price > 0:
            price_breakdown.append({"item": f"+ {topping}", "price": price})

    selected_sauces = []
    for sauce in sauces:
        sauce = sauce.lower().strip()
        if sauce not in sauce_prices:
            return {"error": f"Unknown sauce '{sauce}'. Available: {', '.join(sorted(sauce_prices))}"}
        price = sauce_prices[sauce]
        total_price += price
        selected_sauces.append(sauce)
        if price > 0:
            price_breakdown.append({"item": f"+ {sauce}", "price": price})

    # Build description for the order
    parts = [patty]
    if selected_toppings:
        parts.extend(selected_toppings)
    if selected_sauces:
        parts.extend(selected_sauces)
    description = ", ".join(parts)

    # Use a unique item ID for each custom burger configuration
    import hashlib
    config_hash = hashlib.md5(description.encode()).hexdigest()[:6]
    item_id = f"custom-burger-{config_hash}"
    name = "Custom Burger"

    logger.info("build_custom_burger: %s toppings=%s sauces=%s price=%s", patty, selected_toppings, selected_sauces, total_price)

    _order_state.add_item(item_id, name, quantity, total_price, description)
    note_added("custom-burger")
    summary = _order_state.get_summary()

    # Auto-update the UI: close burger builder, update order
    try:
        current = get_ui_state()
        current["burgerBuilder"] = None
        current["highlightedItem"] = None
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        set_ui_state(current)
    except Exception as e:
        logger.warning("build_custom_burger: failed to auto-update UI: %s", e)

    return _sanitize_result(_while_choosing({
        "status": "added",
        "item": "Custom Burger",
        "patty": patty,
        "toppings": selected_toppings,
        "sauces": selected_sauces,
        "price": f"{CURRENCY} {total_price / 100:.2f}",
        "priceText": _spoken(total_price),
        "total": summary["total"],
        "totalText": _spoken(summary["total"]),
    }))
