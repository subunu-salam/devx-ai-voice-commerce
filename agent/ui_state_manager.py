# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""UI state for the call in progress, sent to that call's screen over its own WebSocket.

Each call (lane) has its own state in call_context.Call, so two kiosks never see each other's screen.
"""

import asyncio
import json as _json
from decimal import Decimal

try:
    from agent.call_context import current, blank_ui
except ImportError:
    from call_context import current, blank_ui


def set_websocket(ws, loop):
    call = current()
    call.ws, call.loop = ws, loop


def clear_websocket():
    call = current()
    call.ws = call.loop = None


def get_ui_state():
    """Return a copy of this call's UI state."""
    return dict(current().ui)


def set_ui_state(new_state: dict):
    """Update this call's UI state and send it to its screen."""
    call = current()
    call.ui.update(new_state)
    _send_to_frontend(call)


def _serialize(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == int(obj) else float(obj)
    return str(obj)


def _send_to_frontend(call):
    ws, loop = call.ws, call.loop
    if ws is None or loop is None:
        return
    message = {"type": "ui_state_update", "state": dict(call.ui)}

    async def _do_send():
        try:
            await ws.send_text(_json.dumps(message, default=_serialize))
        except Exception as e:
            print(f"[ui_state] send failed: {e}")

    try:
        loop.call_soon_threadsafe(asyncio.ensure_future, _do_send())
    except Exception as e:
        print(f"[ui_state] schedule failed: {e}")


def reset_ui_state():
    """Reset this call's UI state to defaults."""
    current().ui = blank_ui()
