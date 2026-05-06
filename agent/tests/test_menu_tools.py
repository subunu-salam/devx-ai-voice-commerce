# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for menu_tools using moto to mock DynamoDB."""

import boto3
import pytest
from moto import mock_aws

from agent import menu_tools


@pytest.fixture
def dynamodb_table():
    """Create a mocked DynamoDB DriveThruMenu table with sample data."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
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

        # Seed category metadata
        table.put_item(Item={
            "PK": "CATEGORY#burgers", "SK": "METADATA",
            "name": "Burgers", "sortOrder": 1,
        })
        table.put_item(Item={
            "PK": "CATEGORY#drinks", "SK": "METADATA",
            "name": "Drinks", "sortOrder": 2,
        })

        # Seed menu items
        table.put_item(Item={
            "PK": "CATEGORY#burgers", "SK": "ITEM#classic",
            "name": "Classic Burger", "description": "A classic beef burger",
            "price": 899, "imageUrl": "images/classic.jpg",
            "category": "Burgers", "featured": True, "sortOrder": 1,
        })
        table.put_item(Item={
            "PK": "CATEGORY#burgers", "SK": "ITEM#cheese",
            "name": "Cheeseburger", "description": "Burger with cheese",
            "price": 999, "imageUrl": "images/cheese.jpg",
            "category": "Burgers", "featured": False, "sortOrder": 2,
        })
        table.put_item(Item={
            "PK": "CATEGORY#drinks", "SK": "ITEM#cola",
            "name": "Cola", "description": "Refreshing cola",
            "price": 299, "imageUrl": "images/cola.jpg",
            "category": "Drinks", "featured": True, "sortOrder": 1,
        })

        # Inject the mocked table
        menu_tools.set_table(table)
        yield table


class TestGetCategories:
    def test_returns_all_categories(self, dynamodb_table):
        result = menu_tools.get_categories()
        cats = result["categories"]
        assert len(cats) == 2
        names = {c["name"] for c in cats}
        assert names == {"Burgers", "Drinks"}

    def test_categories_sorted_by_sort_order(self, dynamodb_table):
        result = menu_tools.get_categories()
        cats = result["categories"]
        assert cats[0]["name"] == "Burgers"
        assert cats[1]["name"] == "Drinks"

    def test_category_ids_extracted(self, dynamodb_table):
        result = menu_tools.get_categories()
        ids = {c["categoryId"] for c in cats} if (cats := result["categories"]) else set()
        assert "burgers" in ids
        assert "drinks" in ids


class TestGetItemsByCategory:
    def test_returns_items_for_category(self, dynamodb_table):
        result = menu_tools.get_items_by_category(category_id="burgers")
        items = result["items"]
        assert len(items) == 2
        assert all(i["category"] == "Burgers" for i in items)

    def test_returns_empty_for_nonexistent_category(self, dynamodb_table):
        result = menu_tools.get_items_by_category(category_id="desserts")
        assert result["items"] == []

    def test_items_sorted_by_sort_order(self, dynamodb_table):
        result = menu_tools.get_items_by_category(category_id="burgers")
        items = result["items"]
        assert items[0]["name"] == "Classic Burger"
        assert items[1]["name"] == "Cheeseburger"


class TestGetItemDetails:
    def test_returns_item_details(self, dynamodb_table):
        result = menu_tools.get_item_details(item_id="classic", category_id="burgers")
        assert result["name"] == "Classic Burger"
        assert result["price"] == 899
        assert result["description"] == "A classic beef burger"
        assert result["imageUrl"] == "images/classic.jpg"

    def test_returns_error_for_nonexistent_item(self, dynamodb_table):
        result = menu_tools.get_item_details(item_id="nonexistent", category_id="burgers")
        assert "error" in result


class TestGetRecommendations:
    def test_returns_only_featured_items(self, dynamodb_table):
        result = menu_tools.get_recommendations()
        items = result["items"]
        assert len(items) == 2
        assert all(i["featured"] is True for i in items)
        names = {i["name"] for i in items}
        assert "Classic Burger" in names
        assert "Cola" in names

    def test_excludes_non_featured_items(self, dynamodb_table):
        result = menu_tools.get_recommendations()
        names = {i["name"] for i in result["items"]}
        assert "Cheeseburger" not in names
