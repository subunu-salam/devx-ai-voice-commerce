"""Menu browsing tools for the drive-thru voice ordering agent.

Each tool queries the DynamoDB DriveThruMenu table using PK/SK access patterns.
The module-level `_table` variable can be overridden for testing.
"""

import boto3
from strands import tool

from agent.ui_events import browse_category_event, highlight_category_event, highlight_item_event

# Module-level DynamoDB table resource — injectable for testing.
_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table("DriveThruMenu")


def set_table(table) -> None:
    """Override the DynamoDB table resource (used in tests)."""
    global _table
    _table = table


def get_table():
    """Return the current DynamoDB table resource."""
    return _table


@tool
def get_categories() -> dict:
    """Returns all menu categories.

    Scans the DriveThruMenu table for items where SK = 'METADATA',
    which represent category metadata records.

    Returns:
        dict with 'categories' list, each containing categoryId and name.
    """
    response = get_table().scan(
        FilterExpression="SK = :sk",
        ExpressionAttributeValues={":sk": "METADATA"},
    )
    categories = []
    for item in response.get("Items", []):
        # PK is "CATEGORY#<categoryId>"
        pk = item.get("PK", "")
        category_id = pk.replace("CATEGORY#", "") if pk.startswith("CATEGORY#") else pk
        categories.append({
            "categoryId": category_id,
            "name": item.get("name", ""),
            "sortOrder": item.get("sortOrder", 0),
        })
    categories.sort(key=lambda c: c["sortOrder"])
    result = {"categories": categories}
    if categories:
        first = categories[0]
        result["ui_event"] = highlight_category_event(first["categoryId"], first["name"])
    return result


@tool
def get_items_by_category(category_id: str) -> dict:
    """Returns all menu items in a given category.

    Queries PK = 'CATEGORY#<category_id>' where SK begins with 'ITEM#'.

    Args:
        category_id: The category identifier (e.g. 'burgers').

    Returns:
        dict with 'items' list, each containing itemId, name, description,
        price, imageUrl, category, featured, and sortOrder.
    """
    response = get_table().query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={
            ":pk": f"CATEGORY#{category_id}",
            ":sk_prefix": "ITEM#",
        },
    )
    items = []
    for item in response.get("Items", []):
        sk = item.get("SK", "")
        item_id = sk.replace("ITEM#", "") if sk.startswith("ITEM#") else sk
        items.append({
            "itemId": item_id,
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "price": item.get("price", 0),
            "imageUrl": item.get("imageUrl", ""),
            "category": item.get("category", ""),
            "featured": item.get("featured", False),
            "sortOrder": item.get("sortOrder", 0),
        })
    items.sort(key=lambda i: i["sortOrder"])
    result = {"items": items}
    result["ui_event"] = browse_category_event(category_id, items[0]["category"] if items else category_id)
    return result


@tool
def get_item_details(item_id: str, category_id: str) -> dict:
    """Returns full details for a specific menu item.

    Uses GetItem with PK = 'CATEGORY#<category_id>', SK = 'ITEM#<item_id>'.

    Args:
        item_id: The item identifier.
        category_id: The category the item belongs to.

    Returns:
        dict with item details or an error if not found.
    """
    response = get_table().get_item(
        Key={
            "PK": f"CATEGORY#{category_id}",
            "SK": f"ITEM#{item_id}",
        }
    )
    item = response.get("Item")
    if not item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}
    result = {
        "itemId": item_id,
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "price": item.get("price", 0),
        "imageUrl": item.get("imageUrl", ""),
        "category": item.get("category", ""),
        "featured": item.get("featured", False),
        "sortOrder": item.get("sortOrder", 0),
    }
    result["ui_event"] = highlight_item_event(item_id, result["name"])
    return result


@tool
def get_recommendations() -> dict:
    """Returns a list of featured/popular menu items.

    Scans the DriveThruMenu table for items where featured = true
    and SK begins with 'ITEM#' (excludes METADATA records).

    Returns:
        dict with 'items' list of featured menu items.
    """
    response = get_table().scan(
        FilterExpression="featured = :f AND begins_with(SK, :sk_prefix)",
        ExpressionAttributeValues={
            ":f": True,
            ":sk_prefix": "ITEM#",
        },
    )
    items = []
    for item in response.get("Items", []):
        pk = item.get("PK", "")
        sk = item.get("SK", "")
        category_id = pk.replace("CATEGORY#", "") if pk.startswith("CATEGORY#") else pk
        item_id = sk.replace("ITEM#", "") if sk.startswith("ITEM#") else sk
        items.append({
            "itemId": item_id,
            "categoryId": category_id,
            "name": item.get("name", ""),
            "description": item.get("description", ""),
            "price": item.get("price", 0),
            "imageUrl": item.get("imageUrl", ""),
            "category": item.get("category", ""),
            "featured": True,
            "sortOrder": item.get("sortOrder", 0),
        })
    items.sort(key=lambda i: i["sortOrder"])
    return {"items": items}
