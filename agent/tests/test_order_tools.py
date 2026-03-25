"""Unit tests for order_tools using moto to mock DynamoDB."""

import boto3
import pytest
from moto import mock_aws

from agent import order_tools
from agent.order_state import OrderState


@pytest.fixture
def dynamodb_tables():
    """Create mocked DynamoDB menu and orders tables with sample data."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")

        menu_table = ddb.create_table(
            TableName="DriveThruMenu",
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
            TableName="DriveThruOrders",
            KeySchema=[
                {"AttributeName": "orderId", "KeyType": "HASH"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "orderId", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Seed menu items
        menu_table.put_item(Item={
            "PK": "CATEGORY#burgers", "SK": "ITEM#classic",
            "name": "Classic Burger", "description": "A classic beef burger",
            "price": 899, "imageUrl": "images/classic.jpg",
            "category": "Burgers", "featured": True, "sortOrder": 1,
        })
        menu_table.put_item(Item={
            "PK": "CATEGORY#drinks", "SK": "ITEM#cola",
            "name": "Cola", "description": "Refreshing cola",
            "price": 299, "imageUrl": "images/cola.jpg",
            "category": "Drinks", "featured": True, "sortOrder": 1,
        })

        # Inject mocked tables and fresh order state
        order_tools.set_tables(menu_table, orders_table)
        order_tools.set_order_state(OrderState())
        yield menu_table, orders_table


class TestAddToOrder:
    def test_add_valid_item(self, dynamodb_tables):
        result = order_tools.add_to_order(
            item_id="classic", category_id="burgers", quantity=1
        )
        assert "error" not in result
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Classic Burger"
        assert result["total"] == 899

    def test_add_with_quantity(self, dynamodb_tables):
        result = order_tools.add_to_order(
            item_id="classic", category_id="burgers", quantity=3
        )
        assert result["items"][0]["quantity"] == 3
        assert result["total"] == 899 * 3

    def test_add_increments_existing(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        result = order_tools.add_to_order(
            item_id="classic", category_id="burgers", quantity=2
        )
        assert result["items"][0]["quantity"] == 3

    def test_add_invalid_item(self, dynamodb_tables):
        result = order_tools.add_to_order(
            item_id="nonexistent", category_id="burgers", quantity=1
        )
        assert "error" in result

    def test_add_zero_quantity(self, dynamodb_tables):
        result = order_tools.add_to_order(
            item_id="classic", category_id="burgers", quantity=0
        )
        assert "error" in result

    def test_add_negative_quantity(self, dynamodb_tables):
        result = order_tools.add_to_order(
            item_id="classic", category_id="burgers", quantity=-1
        )
        assert "error" in result


class TestRemoveFromOrder:
    def test_remove_existing_item(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=2)
        result = order_tools.remove_from_order(item_id="classic", quantity=1)
        assert "error" not in result
        assert result["items"][0]["quantity"] == 1

    def test_remove_reduces_to_zero_removes_item(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        result = order_tools.remove_from_order(item_id="classic", quantity=1)
        assert result["items"] == []
        assert result["total"] == 0

    def test_remove_nonexistent_item(self, dynamodb_tables):
        result = order_tools.remove_from_order(item_id="classic", quantity=1)
        assert "error" in result


class TestGetOrderSummary:
    def test_empty_order(self, dynamodb_tables):
        result = order_tools.get_order_summary()
        assert result["items"] == []
        assert result["total"] == 0

    def test_with_items(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        order_tools.add_to_order(item_id="cola", category_id="drinks", quantity=2)
        result = order_tools.get_order_summary()
        assert len(result["items"]) == 2
        assert result["total"] == 899 + 299 * 2


class TestPlaceOrder:
    def test_place_order_persists(self, dynamodb_tables):
        menu_table, orders_table = dynamodb_tables
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        result = order_tools.place_order(user_id="user-123")
        assert "orderId" in result
        assert result["userId"] == "user-123"
        assert result["status"] == "confirmed"
        assert result["total"] == 899
        # Verify persisted in DynamoDB
        db_item = orders_table.get_item(Key={"orderId": result["orderId"]})
        assert "Item" in db_item

    def test_place_empty_order_fails(self, dynamodb_tables):
        result = order_tools.place_order(user_id="user-123")
        assert "error" in result

    def test_place_order_clears_state(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=1)
        order_tools.place_order(user_id="user-123")
        summary = order_tools.get_order_summary()
        assert summary["items"] == []
        assert summary["total"] == 0


class TestCancelOrder:
    def test_cancel_clears_items(self, dynamodb_tables):
        order_tools.add_to_order(item_id="classic", category_id="burgers", quantity=2)
        result = order_tools.cancel_order()
        assert result["message"] == "Order cancelled."
        assert result["items"] == []
        assert result["total"] == 0

    def test_cancel_empty_order(self, dynamodb_tables):
        result = order_tools.cancel_order()
        assert result["message"] == "Order cancelled."
        assert result["items"] == []
