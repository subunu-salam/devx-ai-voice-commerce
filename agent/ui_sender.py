# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Send UI_Events over WebSocket from tools (runs in worker threads)."""

import asyncio

try:
    from agent.call_context import current
except ImportError:
    from call_context import current


def set_websocket(ws, loop):
    call = current()
    call.ws, call.loop = ws, loop


def clear_websocket():
    call = current()
    call.ws = call.loop = None


def send_ui_event(ui_event: dict, tool_context=None):
    """Send a UI_Event as JSON over this call's WebSocket."""
    ws, loop = current().ws, current().loop

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
