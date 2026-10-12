"""One object per voice call: everything that belongs to the customer on this call, and nothing else.

A merchant runs several lanes (kiosks) on one server. Each WebSocket gets its own Call holding its screen state,
its socket, its order, who the customer is, what they said and the call record. Nothing about a customer lives in
a shared variable, so two cars ordering at the same moment never see each other's order, and when a call ends its
Call is simply dropped: the next customer starts from nothing. What must be kept (customers, orders, points) is
written to the database the moment it is captured, never held here.

The Call travels with the asyncio task that serves the WebSocket (a ContextVar), which is copied into every task
and worker thread the voice agent starts for that call, so tool functions find their own call without being
told. Outside a call (tests, admin requests) a default Call is used, which keeps the old single-line behaviour.
"""

import contextvars
import logging
import secrets
import threading

try:
    from agent.order_state import OrderState
except ImportError:
    from order_state import OrderState

logger = logging.getLogger(__name__)


def blank_ui() -> dict:
    return {
        "categories": [], "menuItems": {}, "highlightedCategory": None, "highlightedItem": None,
        "orderItems": [], "orderTotal": 0, "orderConfirmed": False, "orderNumber": None,
        "burgerBuilder": None, "shownItems": [],
    }


class Call:
    def __init__(self, lane: str = ""):
        self.id = secrets.token_hex(6)
        self.lane = lane                       # which kiosk / device, for logs and the call record
        self.ui = blank_ui()                   # what this customer's screen shows
        self.ws = None                         # this call's WebSocket and event loop
        self.loop = None
        self.order = OrderState()              # items not yet placed
        self.customer: dict = {}               # the Rewards member on this call, if any (phone, name, ...)
        self.heard: list = []                  # what the customer said or tapped (vehicle plate check)
        self.heard_any = False                 # True once any customer line reached us
        self.record = None                     # call record for insights (shop_config)
        self.looking_at = {"visibleCategory": None, "selectedItem": None}
        self.lang = "en"
        self.kiosk = False                     # a shared kiosk: sign-ins only last for this visit

    def carry_over_from(self, old: "Call") -> None:
        """A language switch reconnects: the same customer, same order, same identity."""
        self.order, self.customer, self.heard, self.heard_any = old.order, old.customer, old.heard, old.heard_any


_current: contextvars.ContextVar = contextvars.ContextVar("voicebite_call", default=None)
_default = Call("default")
_live: dict = {}
_lock = threading.Lock()


def begin(lane: str = "") -> Call:
    """Start a fresh Call for the WebSocket being served by the current task."""
    call = Call(lane)
    _current.set(call)
    with _lock:
        _live[call.id] = call
    return call


def end(call: Call) -> None:
    """Forget the call. Its customer, order and screen go with it."""
    with _lock:
        _live.pop(call.id, None)
    call.ws = call.loop = None


def current() -> Call:
    call = _current.get()
    if call is not None:
        return call
    with _lock:
        live = list(_live.values())
    if len(live) == 1:
        return live[0]            # the voice library ran a tool outside the call's context: only one call, so it is this one
    if live:
        logger.error("A tool ran outside its call while %s calls are live; using a blank call", len(live))
    return _default


def live_lanes() -> dict:
    """Kiosk lane -> number of customers on a call there right now."""
    out: dict = {}
    with _lock:
        for call in _live.values():
            if call.lane:
                out[call.lane] = out.get(call.lane, 0) + 1
    return out


def live_calls() -> int:
    with _lock:
        return len(_live)
