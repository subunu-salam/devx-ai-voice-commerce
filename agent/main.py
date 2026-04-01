"""Drive-thru voice ordering agent entry point for AgentCore Runtime.

Uses BedrockAgentCoreApp with a WebSocket handler that bridges incoming
audio/text frames to the Strands BidiAgent with Nova Sonic.
"""

import asyncio
import base64
import json
from collections.abc import Awaitable

from bedrock_agentcore.runtime import BedrockAgentCoreApp
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

SYSTEM_PROMPT = """\
You are a friendly and upbeat drive-thru attendant at a fast-food restaurant. \
Your job is to greet customers warmly, help them browse the menu, take their orders, \
and confirm everything before placing the order.

## Persona
- Speak in a casual, friendly tone — like a real drive-thru worker.
- Keep responses concise and conversational. Avoid long monologues.
- Greet the customer when the session starts: "Welcome! What can I get for you today?"
- Always confirm additions and removals verbally (e.g., "Got it, one cheeseburger added!").
- When reading back prices, format cents as dollars (e.g., 599 cents = "$5.99").

## Menu Browsing
- Use get_categories to list available menu categories when asked.
- Use get_items_by_category to show items in a specific category.
- Use get_item_details to describe a specific item in detail.
- Use get_recommendations when the customer asks for suggestions or what's popular.
- If a customer asks about an item or category that doesn't exist, suggest alternatives \
from the available menu.

## Order Management
- Use add_to_order to add items. Always include the correct item_id, category_id, and quantity.
- Use remove_from_order to remove items when requested.
- Use get_order_summary to read back the current order when the customer asks.
- Use place_order when the customer confirms they're done (e.g., "that's all", "place my order").
- Use cancel_order if the customer wants to start over or cancel entirely.

## Deictic Reference Resolution (UI_State)
- The frontend sends UI_State messages containing the customer's current visual context:
  - visibleCategory: the category currently shown on screen
  - selectedItem: the menu item the customer tapped or is looking at
  - orderItems: items currently in the order
  - orderTotal: current order total
- When the customer uses deictic references like "this one", "that", "add this", \
"how much is that?", or "tell me about this", use the UI_State to resolve which \
item or category they are referring to.
- If selectedItem is set, assume "this/that" refers to that item.
- If only visibleCategory is set, assume "these/this" refers to items in that category.

## Idle Timeout Handling
- If the customer has been silent for about 30 seconds, gently prompt them: \
"Still deciding? Take your time — just let me know when you're ready!"
- If there's still no response after about 60 seconds total, wrap up the session: \
"Looks like you might need a moment. Your order is saved if you'd like to come back. \
Have a great day!"

## Important Rules
- Never make up menu items. Only reference items returned by the menu tools.
- Always validate items exist before adding to the order.
- Keep the conversation flowing naturally — don't over-explain tool results.
- If something goes wrong (item not found, order error), apologize briefly and offer help.
"""

app = BedrockAgentCoreApp()


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
            stop_conversation,
        ],
        system_prompt=SYSTEM_PROMPT,
    )


class WebSocketAudioInput:
    """BidiInput that reads audio from a WebSocket connection.

    Implements the BidiInput protocol: callable that returns BidiInputEvent,
    with start() and stop() lifecycle methods.
    """

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
        """Read WebSocket messages and enqueue as BidiInputEvents."""
        from strands.experimental.bidi.agent.agent import BidiAudioInputEvent, BidiTextInputEvent

        try:
            while self._running:
                message = await self._ws.receive()
                msg_type = message.get("type", "")

                if msg_type == "websocket.disconnect":
                    break

                if "bytes" in message and message["bytes"]:
                    # Binary frame = audio from microphone
                    audio_b64 = base64.b64encode(message["bytes"]).decode("ascii")
                    event = BidiAudioInputEvent(
                        audio=audio_b64,
                        format="pcm",
                        sample_rate=16000,
                        channels=1,
                    )
                    await self._queue.put(event)

                elif "text" in message and message["text"]:
                    # Text frame = UI_State JSON (pass as text input for context)
                    text = message["text"]
                    try:
                        # Validate it's JSON but send as text input
                        json.loads(text)
                        event = BidiTextInputEvent(text=f"[UI_STATE] {text}", role="user")
                        await self._queue.put(event)
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass

    def __call__(self) -> Awaitable[BidiInputEvent]:
        return self._queue.get()


class WebSocketAudioOutput:
    """BidiOutput that sends audio/text back over a WebSocket connection.

    Implements the BidiOutput protocol: callable that receives BidiOutputEvent,
    with start() and stop() lifecycle methods.
    """

    def __init__(self, websocket):
        self._ws = websocket

    async def start(self, agent: BidiAgent) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def __call__(self, event: BidiOutputEvent) -> None:
        try:
            if isinstance(event, BidiAudioStreamEvent):
                # Send audio back as binary frame
                audio_bytes = base64.b64decode(event.audio)
                await self._ws.send_bytes(audio_bytes)
            elif hasattr(event, "get") and event.get("type") == "tool_use_stream":
                # Tool results may contain UI_Events — send as text frame
                result = event.get("result", {})
                if isinstance(result, dict) and "ui_event" in result:
                    await self._ws.send_text(json.dumps(result["ui_event"]))
        except Exception:
            pass


@app.websocket
async def websocket_handler(websocket, context):
    """Handle bidirectional audio/text streaming via WebSocket."""
    await websocket.accept()

    agent = create_agent()
    ws_input = WebSocketAudioInput(websocket)
    ws_output = WebSocketAudioOutput(websocket)

    try:
        await agent.run(
            inputs=[ws_input],
            outputs=[ws_output],
        )
    except Exception as e:
        print(f"Agent error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.entrypoint
def invoke(payload):
    """HTTP fallback for non-WebSocket invocations."""
    return {"message": "Use WebSocket endpoint at /ws for voice ordering."}


if __name__ == "__main__":
    app.run()
