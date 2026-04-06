"""Drive-thru voice ordering agent entry point for AgentCore Runtime.

Tools send UI_Events directly over WebSocket. The agent just calls tools
and responds verbally — screen updates happen automatically.
"""

import asyncio
import base64
import json
from collections.abc import Awaitable

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import tool
from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.agent.agent import BidiInputEvent, BidiOutputEvent
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.tools import stop_conversation
from strands.experimental.bidi.types.events import BidiAudioStreamEvent

try:
    from agent.menu_tools import (
        get_categories, get_item_details, get_items_by_category, get_recommendations,
    )
    from agent.order_tools import (
        add_to_order, cancel_order, get_order_summary, place_order, remove_from_order,
    )
except ModuleNotFoundError:
    from menu_tools import (
        get_categories, get_item_details, get_items_by_category, get_recommendations,
    )
    from order_tools import (
        add_to_order, cancel_order, get_order_summary, place_order, remove_from_order,
    )

# Shared UI_State updated silently from frontend WebSocket text frames.
_current_ui_state: dict = {
    "visibleCategory": None,
    "selectedItem": None,
    "orderItems": [],
    "orderTotal": 0,
}

app = BedrockAgentCoreApp()


@tool
def get_ui_context() -> dict:
    """Returns what the customer is currently looking at on screen.

    Use when the customer says "this one", "that", "add this", etc.
    to resolve which item or category they mean.

    Returns:
        dict with visibleCategory, selectedItem, orderItems, orderTotal.
    """
    return _current_ui_state.copy()


SYSTEM_PROMPT = """\
You are a friendly drive-thru attendant. Greet customers, help them browse the menu, \
take orders, and confirm before placing.

## Rules
- Casual, friendly tone. Keep it concise.
- Greet with: "Welcome! What can I get for you today?"
- Confirm additions/removals verbally. Format prices as dollars (599 = "$5.99").
- Never make up menu items — only use what the tools return.
- The customer's screen updates automatically when you use tools. \
Do NOT mention screen updates or try to update the screen yourself.

## Tools
You have menu tools (get_categories, get_items_by_category, get_item_details, \
get_recommendations) and order tools (add_to_order, remove_from_order, \
get_order_summary, place_order, cancel_order).

Just call the tool and respond verbally — the screen handles itself.

## Deictic References
When the customer says "this one", "that", "add this", use get_ui_context to see \
what they're looking at, then use the appropriate tool.

## Idle Timeout
- 30s silence: "Still deciding? Take your time!"
- 60s silence: wrap up the session.
"""


def create_model() -> BidiNovaSonicModel:
    return BidiNovaSonicModel(
        model_id="amazon.nova-sonic-v1:0",
        provider_config={"audio": {"voice": "tiffany"}},
        client_config={"region": "us-east-1"},
    )


def create_agent() -> BidiAgent:
    return BidiAgent(
        model=create_model(),
        tools=[
            get_categories, get_items_by_category, get_item_details, get_recommendations,
            add_to_order, remove_from_order, get_order_summary, place_order, cancel_order,
            get_ui_context,
            stop_conversation,
        ],
        system_prompt=SYSTEM_PROMPT,
    )


class WebSocketAudioInput:
    """BidiInput: reads audio from WebSocket, stores UI_State silently."""

    def __init__(self, websocket):
        self._ws = websocket
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._reader_task = None

    async def start(self, agent: BidiAgent) -> None:
        self._running = True
        self._reader_task = asyncio.create_task(self._read_loop())

    async def stop(self) -> None:
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

    async def _read_loop(self):
        from strands.experimental.bidi.agent.agent import BidiAudioInputEvent
        global _current_ui_state
        try:
            while self._running:
                message = await self._ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if "bytes" in message and message["bytes"]:
                    audio_b64 = base64.b64encode(message["bytes"]).decode("ascii")
                    await self._queue.put(BidiAudioInputEvent(
                        audio=audio_b64, format="pcm", sample_rate=16000, channels=1,
                    ))
                elif "text" in message and message["text"]:
                    try:
                        data = json.loads(message["text"])
                        if isinstance(data, dict) and "visibleCategory" in data:
                            _current_ui_state.update(data)
                    except (json.JSONDecodeError, TypeError):
                        pass
        except Exception:
            pass

    def __call__(self) -> Awaitable[BidiInputEvent]:
        return self._queue.get()


class WebSocketAudioOutput:
    """BidiOutput: sends audio back over WebSocket."""

    def __init__(self, websocket):
        self._ws = websocket

    async def start(self, agent: BidiAgent) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def __call__(self, event: BidiOutputEvent) -> None:
        try:
            if isinstance(event, BidiAudioStreamEvent):
                await self._ws.send_bytes(base64.b64decode(event.audio))
        except Exception:
            pass


@app.websocket
async def websocket_handler(websocket, context):
    await websocket.accept()

    # Store websocket + event loop so tools can send UI_Events from any thread
    try:
        from agent.ui_sender import set_websocket, clear_websocket
    except ModuleNotFoundError:
        from ui_sender import set_websocket, clear_websocket

    loop = asyncio.get_running_loop()
    set_websocket(websocket, loop)

    agent = create_agent()
    try:
        await agent.run(
            inputs=[WebSocketAudioInput(websocket)],
            outputs=[WebSocketAudioOutput(websocket)],
            invocation_state={"websocket": websocket},
        )
    except Exception as e:
        print(f"Agent error: {e}")
    finally:
        clear_websocket()
        try:
            await websocket.close()
        except Exception:
            pass


@app.entrypoint
def invoke(payload):
    return {"message": "Use WebSocket endpoint at /ws for voice ordering."}


if __name__ == "__main__":
    app.run()
