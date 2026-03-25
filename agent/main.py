"""Drive-thru voice ordering agent entry point.

Creates and configures a Strands BidiAgent with BidiNovaSonicModel (Nova Sonic)
for real-time bidirectional voice ordering. Registers all menu and order tools,
and configures a drive-thru attendant persona with idle timeout handling and
UI_State-aware deictic reference resolution.

This module is the main entry point deployed to AgentCore Runtime.
"""

import asyncio

from strands.experimental.bidi import BidiAgent
from strands.experimental.bidi.io import BidiAudioIO, BidiTextIO
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.tools import stop_conversation

from agent.menu_tools import (
    get_categories,
    get_item_details,
    get_items_by_category,
    get_recommendations,
)
from agent.order_tools import (
    add_to_order,
    cancel_order,
    get_order_summary,
    place_order,
    remove_from_order,
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


def create_model() -> BidiNovaSonicModel:
    """Create and return a configured BidiNovaSonicModel instance."""
    return BidiNovaSonicModel(
        model_id="amazon.nova-sonic-v1:0",
        provider_config={
            "audio": {
                "voice": "tiffany",
            },
        },
        client_config={"region": "us-east-1"},
    )


def create_agent() -> BidiAgent:
    """Create and return a configured BidiAgent with all tools registered.

    Returns:
        BidiAgent configured with Nova Sonic model, drive-thru system prompt,
        and all 9 menu/order tools plus stop_conversation.
    """
    model = create_model()

    tools = [
        # Menu tools
        get_categories,
        get_items_by_category,
        get_item_details,
        get_recommendations,
        # Order tools
        add_to_order,
        remove_from_order,
        get_order_summary,
        place_order,
        cancel_order,
        # Session control
        stop_conversation,
    ]

    return BidiAgent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )


async def run_agent() -> None:
    """Create the agent and run it with audio and text I/O."""
    agent = create_agent()

    audio_io = BidiAudioIO()
    text_io = BidiTextIO()
    await agent.run(
        inputs=[audio_io.input()],
        outputs=[audio_io.output(), text_io.output()],
    )


if __name__ == "__main__":
    asyncio.run(run_agent())
