import json
import os
import boto3
from decimal import Decimal


def handler(event, context):
    if event.get("RequestType") == "Delete":
        return {"PhysicalResourceId": "seed-menu-data"}

    table_name = os.environ["TABLE_NAME"]

    # Load menu data from bundled JSON file
    data_path = os.path.join(os.path.dirname(__file__), "menu_items.json")
    with open(data_path) as f:
        menu_data = json.load(f, parse_float=Decimal, parse_int=Decimal)

    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(table_name)

    with table.batch_writer() as batch:
        for item in menu_data:
            batch.put_item(Item=item)

    return {
        "PhysicalResourceId": "seed-menu-data",
        "Data": {"ItemCount": str(len(menu_data))},
    }
