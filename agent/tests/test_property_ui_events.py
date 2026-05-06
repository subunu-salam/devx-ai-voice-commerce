# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Property-based tests for UI_Event emission from order tools.

Property 17: Order tools emit order_update UI_Events
**Validates: Requirements 11.3**
"""

import boto3
from hypothesis import given, settings
from hypothesis import strategies as st
from moto import mock_aws

from agent import order_tools
from agent.order_state import OrderState


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

category_ids = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=15,
)

item_ids = st.text(
    alphabet=st.characters(whitelist_categories=("Ll",)),
    min_size=1,
    max_size=15,
)

names = st.text(min_size=1, max_size=40)
descriptions = st.text(min_size=0, max_size=100)
prices = st.integers(min_value=1, max_value=100_000)
image_urls = st.text(min_size=1, max_size=60)
quantities = st.integers(min_value=1, max_value=20)
user_ids = st.text(min_size=1, max_size=50)


@st.composite
def menu_item_data(draw: st.DrawFn):
    """Generate a single menu item with category info for seeding DynamoDB."""
    return {
        "category_id": draw(category_ids),
        "category_name": draw(names),
        "item_id": draw(item_ids),
        "name": draw(names),
        "description": draw(descriptions),
        "price": draw(prices),
        "imageUrl": draw(image_urls),
    }


@st.composite
def menu_items_list(draw: st.DrawFn):
    """Generate 1-5 distinct menu items (unique by item_id) sharing a category."""
    cat_id = draw(category_ids)
    cat_name = draw(names)
    items = draw(
        st.lists(
            st.fixed_dictionaries({
                "item_id": item_ids,
                "name": names,
                "description": descriptions,
                "price": prices,
                "imageUrl": image_urls,
            }),
            min_size=1,
            max_size=5,
            unique_by=lambda x: x["item_id"],
        )
    )
    return cat_id, cat_name, items


def _setup_tables_and_seed(menu_items: list[dict], cat_id: str, cat_name: str):
    """Create mocked DynamoDB tables and seed menu data. Returns (menu_table, orders_table)."""
    ddb = boto3.resource("dynamodb", region_name="us-east-1")

    menu_table = ddb.create_table(
        TableName="TestMenuUIEvents",
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    orders_table = ddb.create_table(
        TableName="TestOrdersUIEvents",
        KeySchema=[
            {"AttributeName": "orderId", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "orderId", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    for item in menu_items:
        menu_table.put_item(Item={
            "PK": f"CATEGORY#{cat_id}",
            "SK": f"ITEM#{item['item_id']}",
            "name": item["name"],
            "description": item["description"],
            "price": item["price"],
            "imageUrl": item["imageUrl"],
            "category": cat_name,
            "featured": False,
            "sortOrder": 1,
        })

    return menu_table, orders_table


# ---------------------------------------------------------------------------
# Property 17: Order tools emit order_update UI_Events
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(data=menu_items_list(), quantity=quantities)
def test_add_to_order_emits_order_update_ui_event(data, quantity: int) -> None:
    """add_to_order result includes a ui_event with type 'order_update' and matching payload.

    **Validates: Requirements 11.3**
    """
    cat_id, cat_name, items = data
    target = items[0]

    with mock_aws():
        menu_table, orders_table = _setup_tables_and_seed(items, cat_id, cat_name)
        order_tools.set_tables(menu_table, orders_table)
        order_tools.set_order_state(OrderState())

        result = order_tools.add_to_order(
            item_id=target["item_id"],
            category_id=cat_id,
            quantity=quantity,
        )

        # Must have ui_event key
        assert "ui_event" in result
        ui_event = result["ui_event"]

        # Type must be order_update
        assert ui_event["type"] == "order_update"

        # Payload must have items and total
        payload = ui_event["payload"]
        assert "items" in payload
        assert "total" in payload

        # Payload items should match the result items
        assert payload["items"] == result["items"]
        assert payload["total"] == result["total"]

        # Total should equal quantity * unit_price for the single item
        assert payload["total"] == quantity * target["price"]


@settings(max_examples=100, deadline=None)
@given(data=menu_items_list(), add_qty=st.integers(min_value=2, max_value=20))
def test_remove_from_order_emits_order_update_ui_event(data, add_qty: int) -> None:
    """remove_from_order result includes a ui_event with type 'order_update'.

    **Validates: Requirements 11.3**
    """
    cat_id, cat_name, items = data
    target = items[0]

    with mock_aws():
        menu_table, orders_table = _setup_tables_and_seed(items, cat_id, cat_name)
        order_tools.set_tables(menu_table, orders_table)
        order_tools.set_order_state(OrderState())

        # First add the item so we can remove it
        order_tools.add_to_order(
            item_id=target["item_id"],
            category_id=cat_id,
            quantity=add_qty,
        )

        result = order_tools.remove_from_order(
            item_id=target["item_id"],
            quantity=1,
        )

        assert "ui_event" in result
        ui_event = result["ui_event"]

        assert ui_event["type"] == "order_update"

        payload = ui_event["payload"]
        assert "items" in payload
        assert "total" in payload

        # Payload should match the result
        assert payload["items"] == result["items"]
        assert payload["total"] == result["total"]

        # After removing 1, quantity should be add_qty - 1
        assert payload["total"] == (add_qty - 1) * target["price"]


@settings(max_examples=100)
@given(data=menu_items_list(), quantity=quantities)
def test_cancel_order_emits_order_update_ui_event(data, quantity: int) -> None:
    """cancel_order result includes a ui_event with type 'order_update' with empty items and total 0.

    **Validates: Requirements 11.3**
    """
    cat_id, cat_name, items = data
    target = items[0]

    with mock_aws():
        menu_table, orders_table = _setup_tables_and_seed(items, cat_id, cat_name)
        order_tools.set_tables(menu_table, orders_table)
        order_tools.set_order_state(OrderState())

        # Add an item first
        order_tools.add_to_order(
            item_id=target["item_id"],
            category_id=cat_id,
            quantity=quantity,
        )

        result = order_tools.cancel_order()

        assert "ui_event" in result
        ui_event = result["ui_event"]

        assert ui_event["type"] == "order_update"

        payload = ui_event["payload"]
        assert payload["items"] == []
        assert payload["total"] == 0


@settings(max_examples=100)
@given(data=menu_items_list(), quantity=quantities, user_id=user_ids)
def test_place_order_emits_order_confirmed_ui_event(
    data, quantity: int, user_id: str
) -> None:
    """place_order result includes a ui_event with type 'order_confirmed' containing
    orderNumber, items, total, and timestamp.

    **Validates: Requirements 11.3**
    """
    cat_id, cat_name, items = data
    target = items[0]

    with mock_aws():
        menu_table, orders_table = _setup_tables_and_seed(items, cat_id, cat_name)
        order_tools.set_tables(menu_table, orders_table)
        order_tools.set_order_state(OrderState())

        # Add an item first
        order_tools.add_to_order(
            item_id=target["item_id"],
            category_id=cat_id,
            quantity=quantity,
        )

        result = order_tools.place_order(user_id=user_id)

        assert "ui_event" in result
        ui_event = result["ui_event"]

        # place_order emits order_confirmed, not order_update
        assert ui_event["type"] == "order_confirmed"

        payload = ui_event["payload"]
        assert "orderNumber" in payload
        assert "items" in payload
        assert "total" in payload
        assert "timestamp" in payload

        # orderNumber should be non-empty (UUID)
        assert len(payload["orderNumber"]) > 0

        # Total should match what was ordered
        assert payload["total"] == quantity * target["price"]

        # Items should contain the ordered item
        assert len(payload["items"]) >= 1

        # Timestamp should be non-empty
        assert len(payload["timestamp"]) > 0
