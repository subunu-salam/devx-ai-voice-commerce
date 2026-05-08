# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Centralized UI state manager for the agent.

Maintains the current UI state and sends it to the frontend via WebSocket.
The agent calls update_ui() to set the full frontend display state.
"""

import asyncio
import json

# Current UI state — the single source of truth for what the frontend shows
_ui_state = {
    "categories": [],
    "menuItems": {},
    "highlightedCategory": None,
    "highlightedItem": None,
    "orderItems": [],
    "orderTotal": 0,
    "orderConfirmed": False,
    "orderNumber": None,
    "burgerBuilder": None,
}

_event_loop = None
_websocket = None


def set_websocket(ws, loop):
    global _websocket, _event_loop
    _websocket = ws
    _event_loop = loop


def clear_websocket():
    global _websocket, _event_loop
    _websocket = None
    _event_loop = None


def get_ui_state():
    """Return a copy of the current UI state."""
    return dict(_ui_state)


def set_ui_state(new_state: dict):
    """Update the UI state and send it to the frontend."""
    global _ui_state
    _ui_state.update(new_state)
    _send_to_frontend()


def _send_to_frontend():
    """Send the current UI state to the frontend via WebSocket."""
    ws = _websocket
    loop = _event_loop
    if ws is None or loop is None:
        return

    # Use a copy to avoid mutation during serialization
    state_copy = {k: v for k, v in _ui_state.items()}
    message = {"type": "ui_state_update", "state": state_copy}

    async def _do_send():
        try:
            # Use send_text with manual JSON to avoid conflicts with Starlette's send_json
            import json as _json
            await ws.send_text(_json.dumps(message, default=str))
        except Exception as e:
            print(f"[ui_state] send failed: {e}")

    try:
        loop.call_soon_threadsafe(asyncio.ensure_future, _do_send())
    except Exception as e:
        print(f"[ui_state] schedule failed: {e}")


def reset_ui_state():
    """Reset UI state to defaults."""
    global _ui_state
    _ui_state = {
        "categories": [],
        "menuItems": {},
        "highlightedCategory": None,
        "highlightedItem": None,
        "orderItems": [],
        "orderTotal": 0,
        "orderConfirmed": False,
        "orderNumber": None,
        "burgerBuilder": None,
    }
