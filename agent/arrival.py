"""Customer arrival updates and order tracking.

After an order is placed, the ordering app can tell the kitchen how close the customer is:
"on the way" with a distance and minutes, "5 minutes away", or "I'm here". The kitchen display
shows it on the order ticket so staff can time the food and bring it out to the right car.

These routes are public (customers are not signed in), so each order carries a private
tracking key, created when the order is placed. Only the phone that placed the order has it.
"""

import hmac
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from agent import order_tools
except ImportError:
    import order_tools

logger = logging.getLogger(__name__)

ARRIVAL_STATES = ["on_the_way", "arriving", "arrived"]   # "arriving" = about five minutes away
_CLOSED = ("completed", "cancelled")
KITCHEN_STEPS = ["received", "preparing", "ready", "completed"]

router = APIRouter(prefix="/orders")


class ArrivalIn(BaseModel):
    token: str = Field(min_length=8, max_length=64)
    state: str
    etaMinutes: Optional[int] = Field(default=None, ge=0, le=600)
    distanceM: Optional[int] = Field(default=None, ge=0, le=2_000_000)
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    source: str = Field(default="button", max_length=10)   # "button" (tapped) or "gps" (worked out from location)


def _settings() -> dict:
    try:
        return order_tools._shop.get_settings() if order_tools._shop else {}
    except Exception as e:
        logger.warning("Could not read settings: %s", e)
        return {}


def _store() -> Optional[dict]:
    """The restaurant's coordinates from the console settings, or None if they have not been entered."""
    settings = _settings()
    try:
        return {"lat": float(settings["storeLat"]), "lng": float(settings["storeLng"])}
    except (KeyError, TypeError, ValueError):
        return None


def _find(order_id: str, token: str) -> dict:
    item = order_tools._orders_table.get_item(Key={"orderId": order_id}).get("Item")
    saved = str((item or {}).get("trackToken") or "")
    # One answer for "no such order" and "wrong key", so order numbers cannot be probed.
    if not saved or not hmac.compare_digest(saved.encode(), str(token).encode()):
        raise HTTPException(404, "Order not found.")
    return item


def _status(order: dict) -> str:
    status = str(order.get("status") or "received")
    return status if status in KITCHEN_STEPS or status == "cancelled" else "received"


def _view(order: dict) -> dict:
    eta, dist = order.get("etaMinutes"), order.get("distanceM")
    return {
        "orderId": order["orderId"], "status": _status(order),
        "arrivalState": order.get("arrivalState") or "",
        "etaMinutes": int(eta) if eta is not None else None,
        "distanceM": int(dist) if dist is not None else None,
        "store": _store(),
    }


@router.get("/{order_id}/track")
def track(order_id: str, token: str = ""):
    """What the customer's phone needs to follow its order: kitchen status and where the restaurant is."""
    return _view(_find(order_id, token))


@router.post("/{order_id}/arrival")
def arrival(order_id: str, body: ArrivalIn):
    if body.state not in ARRIVAL_STATES:
        raise HTTPException(400, "State must be one of: " + ", ".join(ARRIVAL_STATES) + ".")
    order = _find(order_id, body.token)
    if _status(order) in _CLOSED:
        raise HTTPException(409, "This order is already closed.")

    # Never go backwards: a GPS wobble must not turn "I'm here" back into "on the way".
    previous = str(order.get("arrivalState") or "")
    state = body.state
    if previous in ARRIVAL_STATES and ARRIVAL_STATES.index(previous) > ARRIVAL_STATES.index(state):
        state = previous

    now = datetime.now(timezone.utc).isoformat()
    fields = {"arrivalState": state, "arrivalUpdatedAt": now, "arrivalSource": "gps" if body.source == "gps" else "button"}
    if state == "arrived":
        fields.update(etaMinutes=0, distanceM=0)
        if previous != "arrived":
            fields["arrivedAt"] = now
    else:
        if body.etaMinutes is not None:
            fields["etaMinutes"] = body.etaMinutes
        elif state == "arriving" and previous != "arriving":
            fields["etaMinutes"] = 5
        if body.distanceM is not None:
            fields["distanceM"] = body.distanceM
    if body.lat is not None and body.lng is not None:
        # Rounded to about 10 metres; the database does not take Python floats.
        fields["customerLat"] = Decimal(str(round(body.lat, 4)))
        fields["customerLng"] = Decimal(str(round(body.lng, 4)))

    names = {f"#f{n}": key for n, key in enumerate(fields)}
    values = {f":v{n}": value for n, value in enumerate(fields.values())}
    order_tools._orders_table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET " + ", ".join(f"#f{n} = :v{n}" for n in range(len(fields))),
        ExpressionAttributeNames=names, ExpressionAttributeValues=values,
    )
    logger.info("ARRIVAL: orderId=%s state=%s eta=%s distance=%s source=%s", order_id, state,
                fields.get("etaMinutes"), fields.get("distanceM"), fields["arrivalSource"])
    return _view({**order, **fields})


def setup_arrival(app, cors: bool = False) -> None:
    """Add the tracking routes. `cors=True` when the admin panel (which normally sets up CORS) is not installed."""
    if cors:
        from fastapi.middleware.cors import CORSMiddleware
        origins = [o.strip() for o in os.environ.get("ADMIN_ORIGINS", "*").split(",") if o.strip()]
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
