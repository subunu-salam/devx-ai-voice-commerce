"""Drive-thru voice ordering agent for AgentCore Runtime.

The agent has full control of the frontend UI state via a single update_ui tool.
Every visual change goes through update_ui — the frontend just renders what it receives.
"""

import os
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.tools import stop_conversation
from strands import tool

try:
    from agent.menu_tools import (
        get_categories, get_items_by_category, get_recommendations,
    )
    from agent.order_tools import (
        add_to_order, cancel_order, get_order_summary, place_order, remove_from_order,
    )
    from agent.ui_state_manager import set_websocket, clear_websocket, set_ui_state, get_ui_state, reset_ui_state
except ModuleNotFoundError:
    from menu_tools import (
        get_categories, get_items_by_category, get_recommendations,
    )
    from order_tools import (
        add_to_order, cancel_order, get_order_summary, place_order, remove_from_order,
    )
    from ui_state_manager import set_websocket, clear_websocket, set_ui_state, get_ui_state, reset_ui_state

BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")

# Shared UI_State from frontend (what the customer is looking at)
_current_frontend_state: dict = {
    "visibleCategory": None,
    "selectedItem": None,
}


@tool
def get_ui_context() -> dict:
    """Returns what the customer is currently looking at on screen."""
    return dict(_current_frontend_state)


@tool
def update_ui(
    highlighted_category: str = None,
    highlighted_item: str = None,
    order_items: list = None,
    order_total: int = None,
    order_confirmed: bool = None,
    order_number: str = None,
) -> dict:
    """Update the customer's screen. Call this after any action that should change the display.

    Only include the fields you want to change — others keep their current value.

    Args:
        highlighted_category: Category ID to highlight/scroll to (e.g. "burgers"). Set to "" to clear.
        highlighted_item: Item ID to highlight and show details for (e.g. "classic-burger"). Set to "" to clear.
        order_items: Full list of items in the order. Each item:
            {"itemId": "...", "name": "...", "quantity": 1, "unitPrice": 799, "specialInstructions": "..."}
        order_total: Total price in cents.
        order_confirmed: Set to true when order is placed.
        order_number: The order number (set when order is confirmed).

    Returns:
        Confirmation that the update was sent.
    """
    current = get_ui_state()

    if highlighted_category is not None:
        current["highlightedCategory"] = highlighted_category or None
    if highlighted_item is not None:
        current["highlightedItem"] = highlighted_item or None
    if order_items is not None:
        current["orderItems"] = order_items
    if order_total is not None:
        current["orderTotal"] = order_total
    if order_confirmed is not None:
        current["orderConfirmed"] = order_confirmed
    if order_number is not None:
        current["orderNumber"] = order_number

    # Auto-clear highlighted item when navigating to a category or updating order
    if highlighted_item is None and (highlighted_category is not None or order_items is not None or order_confirmed is not None):
        current["highlightedItem"] = None

    set_ui_state(current)
    return {"status": "updated"}


SYSTEM_PROMPT = """\
You are a warm, enthusiastic drive-thru attendant who genuinely loves helping \
customers find the perfect meal. You're knowledgeable about every item on the menu \
and love making personalized suggestions.

## Your Personality
- Warm and welcoming — make every customer feel like a regular
- Enthusiastic about the food — you've tried everything and have favorites
- Helpful and proactive — suggest combos, sides, and drinks without being pushy
- Patient — never rush the customer, let them browse at their pace
- Conversational — ask follow-up questions like "Are you in the mood for something \
hearty or something lighter?" or "Want to add fries and a drink with that?"

## Greeting
Start with a warm welcome and offer to help: \
"Hey there, welcome! Hungry? I can walk you through our menu or you can just tell me \
what you're craving and I'll get it started for you!"

## How to Help
- If the customer seems unsure, ask what they're in the mood for and suggest categories
- When describing items, mention what makes them special — "The bacon burger is a \
customer favorite, it's got crispy bacon and this amazing BBQ sauce"
- After adding an item, naturally suggest complementary items — "Great choice! Want \
some fries or onion rings on the side?"
- When the order seems complete, gently confirm — "Anything else, or should I get \
this order in for you?"
- Format prices as dollars (599 = "$5.99")
- Never make up menu items — only use what the tools return

## Speech Rules
- NEVER mention the screen, display, or UI updates in your speech
- Don't say "I've updated your screen" or "let me show you" or "I'm pulling that up"
- The customer can see the screen — just talk about the food naturally

## Screen Control
You control the customer's screen via update_ui. Keep it in sync with the conversation:

WHEN YOU MENTION AN ITEM → call update_ui(highlighted_item="classic-burger") to show \
its details on screen. The frontend looks up the item data automatically.

WHEN YOU MENTION A CATEGORY → call update_ui(highlighted_category=...) to scroll there.

WHEN THE ORDER CHANGES → call update_ui(order_items=[...], order_total=...).

The item detail modal closes automatically when you update categories or order.

## Tools
Menu: get_categories, get_items_by_category, get_recommendations
Order: add_to_order, remove_from_order, get_order_summary, place_order, cancel_order
Screen: update_ui
Context: get_ui_context (use when customer says "this one", "that", etc.)

## Special Instructions
When the customer says "no pickles", "extra sauce", "well done", etc., pass these as \
special_instructions in add_to_order. Confirm them back naturally — \
"Cheeseburger, no pickles, extra ketchup — you got it!"
"""

sonic_model = BidiNovaSonicModel(
    model_id="amazon.nova-sonic-v1:0",
    provider_config={
        "audio": {"voice": "tiffany", "input_rate": 16000, "output_rate": 16000, "channels": 1, "format": "pcm"},
        "inference": {},
    },
    client_config={"region": BEDROCK_REGION},
)

app = FastAPI()


@app.get("/ping")
async def ping():
    return {"status": "Healthy", "time_of_last_update": int(datetime.now().timestamp())}


@app.websocket("/ws")
async def voice_chat(websocket: WebSocket) -> None:
    agent = BidiAgent(
        model=sonic_model,
        tools=[
            get_categories, get_items_by_category, get_recommendations,
            add_to_order, remove_from_order, get_order_summary, place_order, cancel_order,
            update_ui, get_ui_context, stop_conversation,
        ],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        await websocket.accept()
        import asyncio
        set_websocket(websocket, asyncio.get_running_loop())
        reset_ui_state()

        async def safe_send_json(data):
            """Send JSON, skip non-serializable events."""
            try:
                await websocket.send_json(data)
            except (TypeError, ValueError):
                # Skip events that can't be serialized (e.g. BidiModelTimeoutError)
                try:
                    import json as _json
                    await websocket.send_text(_json.dumps(data, default=str))
                except Exception:
                    pass

        await agent.run(
            inputs=[websocket.receive_json],
            outputs=[safe_send_json],
        )
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        clear_websocket()
        try:
            await websocket.close()
            await agent.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0" if os.getenv("CONTAINER_ENV") else "127.0.0.1"
    uvicorn.run(app, host=host, port=8080)
