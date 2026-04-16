"""Send UI_Events over WebSocket from tools (runs in worker threads)."""

import asyncio
import json

_event_loop = None
_websocket = None


def set_websocket(ws, loop):
    global _websocket, _event_loop
    _websocket = ws
    _event_loop = loop
    print(f"[ui_sender] set_websocket: ws={ws is not None}, loop={loop is not None}")


def clear_websocket():
    global _websocket, _event_loop
    _websocket = None
    _event_loop = None


def send_ui_event(ui_event: dict, tool_context=None):
    """Send a UI_Event as JSON over the session WebSocket."""
    ws = _websocket
    loop = _event_loop

    if ws is None or loop is None:
        print(f"[ui_sender] SKIP: ws={ws is not None}, loop={loop is not None}")
        return

    try:
        print(f"[ui_sender] Sending: {ui_event.get('type', '?')}")

        async def _do_send():
            try:
                await ws.send_json(ui_event)
                print(f"[ui_sender] Sent OK: {ui_event.get('type', '?')}")
            except Exception as e:
                print(f"[ui_sender] send_json failed: {e}")

        loop.call_soon_threadsafe(asyncio.ensure_future, _do_send())
    except Exception as e:
        print(f"[ui_sender] schedule failed: {e}")
