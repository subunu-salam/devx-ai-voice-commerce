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
        get_categories, get_item_details, get_items_by_category, get_recommendations,
    )
    from agent.order_tools import (
        add_to_order, cancel_order, get_order_summary, place_order, remove_from_order,
    )
    from agent.ui_state_manager import set_websocket, clear_websocket, set_ui_state, get_ui_state, reset_ui_state
except ModuleNotFoundError:
    from menu_tools import (
        get_categories, get_item_details, get_items_by_category, get_recommendations,
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
    item_detail: dict = None,
    order_items: list = None,
    order_total: int = None,
    order_confirmed: bool = None,
    order_number: str = None,
) -> dict:
    """Update the customer's screen. Call this after any action that should change the display.

    Only include the fields you want to change — others keep their current value.

    Args:
        highlighted_category: Category ID to highlight/scroll to (e.g. "burgers"). Set to "" to clear.
        highlighted_item: Item ID to highlight (e.g. "classic-burger"). Set to "" to clear.
        item_detail: Full item details to show in a detail modal. Set to None to close the modal.
            Example: {"itemId": "classic-burger", "categoryId": "burgers", "name": "Classic Burger",
                      "description": "...", "price": 799, "imageUrl": "images/classic-burger.svg",
                      "category": "Burgers"}
        order_items: Full list of items in the order. Each item:
            {"itemId": "...", "name": "...", "quantity": 1, "unitPrice": 799, "specialInstructions": "..."}
        order_total: Total price in cents.
        order_confirmed: Set to true when order is placed.
        order_number: The order number (set when order is confirmed).

    Returns:
        The current UI state after the update.
    """
    current = get_ui_state()

    if highlighted_category is not None:
        current["highlightedCategory"] = highlighted_category or None
    if highlighted_item is not None:
        current["highlightedItem"] = highlighted_item or None
    if item_detail is not None:
        current["itemDetail"] = item_detail if item_detail else None
    elif item_detail == {}:
        current["itemDetail"] = None
    if order_items is not None:
        current["orderItems"] = order_items
    if order_total is not None:
        current["orderTotal"] = order_total
    if order_confirmed is not None:
        current["orderConfirmed"] = order_confirmed
    if order_number is not None:
        current["orderNumber"] = order_number

    # If the agent is updating category, order, or other fields but didn't
    # explicitly set item_detail, auto-close the modal. The agent opens modals
    # explicitly but cleanup happens automatically.
    explicitly_set_detail = item_detail is not None
    if not explicitly_set_detail and (highlighted_category is not None or order_items is not None or order_confirmed is not None):
        current["itemDetail"] = None

    set_ui_state(current)
    # Return a minimal confirmation — don't send the full state back to Nova Sonic
    # (large tool results can cause stream errors)
    return {"status": "updated"}


SYSTEM_PROMPT = """\
You are a friendly drive-thru attendant. Greet customers, help them browse the menu, \
take orders, and confirm before placing.

## Rules
- Casual, friendly tone. Keep it concise.
- Greet with: "Welcome! What can I get for you today?"
- Confirm additions/removals verbally. Format prices as dollars (599 = "$5.99").
- Never make up menu items — only use what the tools return.
- NEVER mention the screen, display, or UI updates in your speech. \
Just update the screen silently and talk about the food naturally. \
Don't say "I've updated your screen" or "let me show you" or "I'm pulling that up". \
The customer can see the screen — just describe the food.

## Screen Control
You have FULL control of the customer's screen via the update_ui tool. \
The screen should ALWAYS reflect what you're talking about. Be proactive:

WHEN YOU MENTION AN ITEM BY NAME → you MUST call get_item_details first to get the full \
item data, then IMMEDIATELY call update_ui with item_detail set to the full item object \
from get_item_details. Every single time. No exceptions. If you describe an item without \
opening its detail modal, the customer cannot see what you're talking about.

WHEN YOU MENTION A CATEGORY → immediately call update_ui(highlighted_category=...) \
to scroll the menu there.

WHEN YOU LIST ITEMS IN A CATEGORY → call update_ui(highlighted_category=...) so the \
customer can see what you're describing.

WHEN YOU ADD/REMOVE/CHANGE THE ORDER → call update_ui with the updated order_items \
and order_total.

WHEN THE TOPIC CHANGES → the item detail modal closes automatically.

Examples:
- "We have burgers, chicken, sides..." → update_ui(highlighted_category="burgers")
- "The classic burger is a quarter-pound..." → get_item_details + update_ui(item_detail={...})
- "Got it, one cheeseburger added!" → update_ui(order_items=[...], order_total=..., item_detail={})
- "Let me show you our drinks" → update_ui(highlighted_category="drinks", item_detail={})
- Customer: "what about sides?" → update_ui(highlighted_category="sides", item_detail={})

IMPORTANT: Always use get_item_details before showing item details — never make up item data.

## Tools
Menu tools: get_categories, get_items_by_category, get_item_details, get_recommendations
Order tools: add_to_order, remove_from_order, get_order_summary, place_order, cancel_order
UI tool: update_ui (call after every action)

## Special Instructions
When the customer says "no pickles", "extra sauce", etc., pass these as \
special_instructions in add_to_order, then update_ui with the new order state.

## Deictic References
When the customer says "this one", "that", "add this", use get_ui_context to see \
what they're looking at.

## Idle Timeout
- 30s silence: "Still deciding? Take your time!"
- 60s silence: wrap up the session.
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
            get_categories, get_items_by_category, get_item_details, get_recommendations,
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
