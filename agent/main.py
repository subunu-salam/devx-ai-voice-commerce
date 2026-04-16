"""Drive-thru voice ordering agent for AgentCore Runtime.

Uses FastAPI + Strands BidiAgent with native WebSocket JSON protocol.
All audio is base64-encoded inside JSON events — no raw binary frames.
Strands handles event routing, interruptions, and tool execution natively.
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
except ModuleNotFoundError:
    from menu_tools import (
        get_categories, get_item_details, get_items_by_category, get_recommendations,
    )
    from order_tools import (
        add_to_order, cancel_order, get_order_summary, place_order, remove_from_order,
    )

BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-east-1")

# Shared UI_State updated silently from frontend
_current_ui_state: dict = {
    "visibleCategory": None,
    "selectedItem": None,
    "orderItems": [],
    "orderTotal": 0,
}


@tool
def get_ui_context() -> dict:
    """Returns what the customer is currently looking at on screen.
    Use when the customer says "this one", "that", "add this", etc.
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

# Configure Nova Sonic model
sonic_model = BidiNovaSonicModel(
    model_id="amazon.nova-sonic-v1:0",
    provider_config={
        "audio": {
            "voice": "tiffany",
            "input_rate": 16000,
            "output_rate": 16000,
            "channels": 1,
            "format": "pcm",
        },
        "inference": {},
    },
    client_config={"region": BEDROCK_REGION},
)

app = FastAPI()


@app.get("/ping")
async def ping():
    """Health check endpoint for AgentCore Runtime."""
    return {"status": "Healthy", "time_of_last_update": int(datetime.now().timestamp())}


@app.websocket("/ws")
async def voice_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for bidirectional voice streaming.

    Strands BidiAgent handles all event routing natively:
    - websocket.receive_json reads typed events from the client
    - websocket.send_json sends typed events back to the client
    - Audio is base64-encoded inside JSON events
    - Interruptions (barge-in) are handled automatically
    """
    agent = BidiAgent(
        model=sonic_model,
        tools=[
            get_categories, get_items_by_category, get_item_details, get_recommendations,
            add_to_order, remove_from_order, get_order_summary, place_order, cancel_order,
            get_ui_context, stop_conversation,
        ],
        system_prompt=SYSTEM_PROMPT,
    )

    try:
        await websocket.accept()

        # Store websocket + event loop so tools can send UI_Events directly
        try:
            from agent.ui_sender import set_websocket, clear_websocket
        except ModuleNotFoundError:
            from ui_sender import set_websocket, clear_websocket

        import asyncio
        set_websocket(websocket, asyncio.get_running_loop())

        await agent.run(
            inputs=[websocket.receive_json],
            outputs=[websocket.send_json],
        )
    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"Error in voice chat: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            clear_websocket()
        except Exception:
            pass
        try:
            await websocket.close()
            await agent.stop()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    host = "0.0.0.0" if os.getenv("CONTAINER_ENV") else "127.0.0.1"
    uvicorn.run(app, host=host, port=8080)
