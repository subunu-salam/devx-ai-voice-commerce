"""Helper to send UI_Events over WebSocket from tools.

Tools run in a sync context (possibly a different thread), so we use
the stored event loop reference and call_soon_threadsafe to schedule sends.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

# Set by the websocket handler before agent.run()
_event_loop: asyncio.AbstractEventLoop | None = None
_websocket = None


def set_websocket(ws, loop: asyncio.AbstractEventLoop) -> None:
    """Store the WebSocket and event loop for tools to use."""
    global _websocket, _event_loop
    _websocket = ws
    _event_loop = loop


def clear_websocket() -> None:
    """Clear the stored WebSocket reference."""
    global _websocket, _event_loop
    _websocket = None
    _event_loop = None


def send_ui_event(ui_event: dict, tool_context=None) -> None:
    """Send a UI_Event as a JSON text frame over the session WebSocket.

    Works from any thread by scheduling the send on the stored event loop.
    """
    ws = _websocket
    loop = _event_loop

    if ws is None or loop is None:
        return

    try:
        data = json.dumps(ui_event)

        async def _send():
            try:
                await ws.send_text(data)
            except Exception:
                pass

        loop.call_soon_threadsafe(asyncio.ensure_future, _send())
    except Exception as e:
        logger.error("send_ui_event: failed: %s", e)
