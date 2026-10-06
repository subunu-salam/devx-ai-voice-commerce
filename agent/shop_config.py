"""Shared settings, burger pricing and call records, used by both the voice agent and the admin API.

Settings live in the menu table under PK="CONFIG", so no extra table is needed for them.
Call records go to a separate table that is created automatically on first start.
"""

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

logger = logging.getLogger(__name__)

_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_db = boto3.resource("dynamodb", region_name=_REGION)
menu_table = _db.Table(os.environ.get("MENU_TABLE_NAME", "DriveThruMenu"))
orders_table = _db.Table(os.environ.get("ORDERS_TABLE_NAME", "DriveThruOrders"))
SESSIONS_TABLE_NAME = os.environ.get("SESSIONS_TABLE_NAME", "DriveThruSessions")
sessions_table = _db.Table(SESSIONS_TABLE_NAME)

CONFIG_PK = "CONFIG"
VOICES = ["tiffany", "matthew", "amy"]
DEFAULT_LOCATION = "main"

DEFAULT_SETTINGS = {
    "greeting": "Welcome to VoiceBite! How can I help you?",
    "voice": "tiffany",
    "upsell": "Suggest combos naturally.",
    "hoursEnabled": False,
    "openTime": "09:00",
    "closeTime": "22:00",
    "utcOffset": "+04:00",
    "closedMessage": "Sorry, we're closed right now. Please come back during opening hours.",
    "accessCode": "",
    "costPer1kInput": "0",
    "costPer1kOutput": "0",
    # Business details used on receipts and in the console
    "legalName": "",
    "trn": "",
    "address": "",
    "currency": "AED",
    "vatRate": "5",
    "pricesIncludeVat": True,
    "prepSlaMinutes": 8,
    # Where the restaurant is, so the ordering app can work out how far away a customer is. Empty = not set.
    "storeLat": "",
    "storeLng": "",
}

DEFAULT_BURGER = {
    "basePrice": 899,
    "toppings": {
        "american cheese": 100, "cheddar cheese": 100, "pepper jack cheese": 100, "swiss cheese": 100,
        "bacon": 150, "avocado": 150, "fried egg": 150,
        "lettuce": 0, "tomato": 0, "onion": 0, "pickles": 0, "jalapeños": 0, "mushrooms": 0,
    },
    "sauces": {"ketchup": 0, "mustard": 0, "mayo": 0, "bbq sauce": 0, "chipotle mayo": 0, "special sauce": 0},
}


def plain(obj):
    """Turn DynamoDB Decimals into ordinary numbers so results are valid JSON."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [plain(v) for v in obj]
    return obj


# ---------- settings ----------

_cache: dict = {}
_CACHE_SECONDS = 15


def _get_config(sk: str, default: dict) -> dict:
    hit = _cache.get(sk)
    if hit and hit[0] > time.monotonic():
        return dict(hit[1])
    value = dict(default)
    try:
        item = menu_table.get_item(Key={"PK": CONFIG_PK, "SK": sk}).get("Item")
        if item:
            value.update({k: v for k, v in plain(item).items() if k not in ("PK", "SK")})
    except Exception as e:  # the agent must keep working even if settings can't be read
        logger.warning("Could not read %s settings, using defaults: %s", sk, e)
    _cache[sk] = (time.monotonic() + _CACHE_SECONDS, value)
    return dict(value)


def put_config(sk: str, value: dict) -> None:
    menu_table.put_item(Item={"PK": CONFIG_PK, "SK": sk, **value})
    _cache.pop(sk, None)


def get_settings() -> dict:
    return _get_config("SETTINGS", DEFAULT_SETTINGS)


def get_burger_config() -> dict:
    return _get_config("BURGER", DEFAULT_BURGER)


def is_open_now(settings: dict) -> bool:
    """True unless opening hours are switched on and the local time is outside them."""
    if not settings.get("hoursEnabled"):
        return True
    try:
        offset = str(settings.get("utcOffset", "+00:00"))
        sign = -1 if offset.startswith("-") else 1
        hours, minutes = offset.lstrip("+-").split(":")
        now = datetime.now(timezone.utc) + sign * timedelta(hours=int(hours), minutes=int(minutes))
        current, opens, closes = now.strftime("%H:%M"), settings["openTime"], settings["closeTime"]
        if opens <= closes:
            return opens <= current < closes
        return current >= opens or current < closes  # hours that run past midnight
    except Exception as e:
        logger.warning("Could not work out opening hours, treating as open: %s", e)
        return True


# ---------- call records ----------

def ensure_sessions_table() -> None:
    try:
        _db.create_table(
            TableName=SESSIONS_TABLE_NAME,
            KeySchema=[{"AttributeName": "sessionId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sessionId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        logger.info("Created table %s", SESSIONS_TABLE_NAME)
    except _db.meta.client.exceptions.ResourceInUseException:
        pass
    except Exception as e:
        logger.warning("Could not create %s; call insights will be empty: %s", SESSIONS_TABLE_NAME, e)


_session = None  # the agent handles one call at a time, like its order state


def start_session(location_id: str) -> None:
    global _session
    _session = {
        "sessionId": uuid.uuid4().hex[:12],
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "t0": time.time(),
        "locationId": location_id or DEFAULT_LOCATION,
        "viewed": [], "added": [],
        "orderPlaced": False, "orderId": "", "orderTotal": 0,
        "inputTokens": 0, "outputTokens": 0,
    }


def current_location() -> str:
    return _session["locationId"] if _session else DEFAULT_LOCATION


def note_viewed(item_id: str) -> None:
    if _session and item_id and item_id not in _session["viewed"]:
        _session["viewed"].append(item_id)


def note_added(item_id: str) -> None:
    if _session and item_id and item_id not in _session["added"]:
        _session["added"].append(item_id)


def note_order(order_id: str, total: int) -> None:
    if _session:
        _session.update(orderPlaced=True, orderId=str(order_id), orderTotal=int(total or 0))


def note_usage(input_tokens, output_tokens) -> None:
    """The voice model reports running totals, so keep the highest figure seen."""
    if _session:
        _session["inputTokens"] = max(_session["inputTokens"], int(input_tokens or 0))
        _session["outputTokens"] = max(_session["outputTokens"], int(output_tokens or 0))


def end_session(error: str = "") -> None:
    global _session
    record, _session = _session, None
    if not record:
        return
    started = record.pop("t0")
    record["endedAt"] = datetime.now(timezone.utc).isoformat()
    record["durationSec"] = int(time.time() - started)
    if error:
        record["error"] = error[:300]
    try:
        sessions_table.put_item(Item=record)
    except Exception as e:
        logger.warning("Could not save call record: %s", e)
