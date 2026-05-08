# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Menu browsing tools for the drive-thru voice ordering agent."""

import os

import boto3
from strands import tool

_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_table = _dynamodb.Table(os.environ.get("MENU_TABLE_NAME", "DriveThruMenu"))


def set_table(table) -> None:
    global _table
    _table = table


def get_table():
    return _table


@tool
def get_categories(tool_context=None) -> dict:
    """Returns all menu categories."""
    response = get_table().scan(
        FilterExpression="SK = :sk",
        ExpressionAttributeValues={":sk": "METADATA"},
    )
    categories = []
    for item in response.get("Items", []):
        pk = item.get("PK", "")
        category_id = pk.replace("CATEGORY#", "") if pk.startswith("CATEGORY#") else pk
        categories.append({
            "categoryId": category_id,
            "name": str(item.get("name", "")),
            "sortOrder": int(item.get("sortOrder", 0)),
        })
    categories.sort(key=lambda c: c["sortOrder"])
    result = {"categories": categories}
    return result


@tool
def get_items_by_category(category_id: str) -> dict:
    """Returns all menu items in a given category."""
    response = get_table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={":pk": f"CATEGORY#{category_id}", ":sk_prefix": "ITEM#"},
    )
    items = []
    for item in response.get("Items", []):
        sk = item.get("SK", "")
        item_id = sk.replace("ITEM#", "") if sk.startswith("ITEM#") else sk
        items.append({
            "itemId": item_id,
            "name": str(item.get("name", "")),
            "description": str(item.get("description", "")),
            "price": int(item.get("price", 0)),
            "imageUrl": str(item.get("imageUrl", "")),
            "category": str(item.get("category", "")),
            "featured": bool(item.get("featured", False)),
            "sortOrder": int(item.get("sortOrder", 0)),
        })
    items.sort(key=lambda i: i["sortOrder"])
    result = {"items": items}
    return result


@tool
def get_item_details(item_id: str, category_id: str) -> dict:
    """Returns full details for a specific menu item."""
    response = get_table().get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    item = response.get("Item")
    if not item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}
    result = {
        "itemId": item_id,
        "categoryId": category_id,
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "price": int(item.get("price", 0)),
        "imageUrl": item.get("imageUrl", ""),
        "category": item.get("category", ""),
        "featured": bool(item.get("featured", False)),
        "sortOrder": int(item.get("sortOrder", 0)),
    }
    return result


@tool
def get_recommendations(tool_context=None) -> dict:
    """Returns a list of featured/popular menu items."""
    response = get_table().scan(
        FilterExpression="featured = :f AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={":f": True, ":sk_prefix": "ITEM#"},
    )
    items = []
    for item in response.get("Items", []):
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        category_id = pk.replace("CATEGORY#", "") if pk.startswith("CATEGORY#") else pk
        item_id = sk.replace("ITEM#", "") if sk.startswith("ITEM#") else sk
        items.append({
            "itemId": item_id, "categoryId": category_id,
            "name": str(item.get("name", "")), "description": str(item.get("description", "")),
            "price": int(item.get("price", 0)), "imageUrl": str(item.get("imageUrl", "")),
            "category": str(item.get("category", "")), "featured": True,
            "sortOrder": int(item.get("sortOrder", 0)),
        })
    items.sort(key=lambda i: i["sortOrder"])
    return {"items": items}
