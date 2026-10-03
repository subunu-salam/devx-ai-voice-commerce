"""VoiceBite merchant console API.

Sign-in with roles, orders and kitchen status, payments at the window, refunds and voids,
menu, burger pricing, inventory with recipes (BOM) and a stock ledger, waste, purchasing,
assets, customers, coupons, campaigns, analytics, branches, team and an audit log.

Environment variables:
    ADMIN_PASSWORD   required; password of the built-in merchant admin account "admin"
    ADMIN_ORIGINS    optional; comma-separated sites allowed to call this API
    DATA_TABLE_NAME  optional; table for console records (created automatically)
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from agent.shop_config import (
        CONFIG_PK, DEFAULT_LOCATION, VOICES, ensure_sessions_table, get_burger_config, get_settings,
        menu_table, orders_table, plain, put_config, sessions_table,
    )
except ModuleNotFoundError:
    from shop_config import (
        CONFIG_PK, DEFAULT_LOCATION, VOICES, ensure_sessions_table, get_burger_config, get_settings,
        menu_table, orders_table, plain, put_config, sessions_table,
    )

logger = logging.getLogger(__name__)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
DEFAULT_ORIGINS = "https://devx-ai-voice-commerce-1.onrender.com"
TOKEN_HOURS = 12
STATUSES = ["received", "preparing", "ready", "completed", "cancelled"]
ALL = "all"
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_OFFSET = re.compile(r"^[+-](0\d|1[0-4]):[0-5]\d$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")

_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_db = boto3.resource("dynamodb", region_name=_REGION)
DATA_TABLE_NAME = os.environ.get("DATA_TABLE_NAME", "VoiceBiteData")
data_table = _db.Table(DATA_TABLE_NAME)

# ---------- roles (PRD 5.9) ----------
_EVERYTHING = {
    "orders.view", "orders.status", "orders.refund", "menu.edit", "inventory.view", "inventory.edit", "waste.log",
    "assets.edit", "purchasing.edit", "purchasing.approve", "crm.view", "crm.edit", "analytics.view",
    "team.manage", "settings.manage", "audit.view",
}
ROLE_CAPS = {
    "platform_admin": _EVERYTHING,
    "merchant_admin": _EVERYTHING,
    "store_manager": _EVERYTHING - {"team.manage", "settings.manage"},
    "cashier": {"orders.view", "orders.status", "waste.log", "crm.view"},
    "kitchen": {"orders.view", "orders.status", "waste.log", "inventory.view"},
    "inventory": {"orders.view", "inventory.view", "inventory.edit", "waste.log", "assets.edit", "purchasing.edit"},
    "analyst": {"orders.view", "inventory.view", "crm.view", "analytics.view", "audit.view"},
}
_OLD_ROLES = {"owner": "merchant_admin", "manager": "store_manager", "staff": "cashier"}

# Console record types: (capability to read, capability to write; None = written only by the actions further down)
COLLECTIONS = {
    "ingredients": ("inventory.view", "inventory.edit"),
    "recipes": ("inventory.view", "inventory.edit"),
    "suppliers": ("inventory.view", "purchasing.edit"),
    "purchase_orders": ("inventory.view", "purchasing.edit"),
    "assets": ("inventory.view", "assets.edit"),
    "customers": ("crm.view", "crm.edit"),
    "coupons": ("crm.view", "crm.edit"),
    "campaigns": ("crm.view", "crm.edit"),
    "stock_moves": ("inventory.view", None),
    "waste": ("inventory.view", None),
    "asset_moves": ("inventory.view", None),
    "refunds": ("orders.view", None),
    "audit": ("audit.view", None),
}
WASTE_REASONS = ["trimming", "overproduction", "burnt", "dropped", "expired", "damaged", "cancelled order", "unclaimed pickup", "other"]
MOVE_TYPES = ["purchase", "adjustment", "count", "transfer", "return"]


# ---------- helpers ----------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


def _to_db(obj):
    """The database rejects Python floats, so numbers go in as Decimals."""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 6)))
    if isinstance(obj, dict):
        return {str(k): _to_db(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_db(v) for v in obj]
    return obj


def _scan_all(table) -> list:
    rows, kwargs = [], {}
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return plain(rows)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _query(pk: str, sk_prefix: str) -> list:
    rows, kwargs = [], {"KeyConditionExpression": Key("PK").eq(pk) & Key("SK").begins_with(sk_prefix)}
    while True:
        page = menu_table.query(**kwargs)
        rows.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return plain(rows)
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _records(collection: str) -> list:
    rows, kwargs = [], {"KeyConditionExpression": Key("c").eq(collection)}
    while True:
        page = data_table.query(**kwargs)
        rows.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    rows = plain(rows)
    for row in rows:
        row.pop("c", None)
    return rows


def _record(collection: str, record_id: str) -> Optional[dict]:
    item = data_table.get_item(Key={"c": collection, "id": record_id}).get("Item")
    return plain(item) if item else None


def _save(collection: str, record_id: str, record: dict) -> dict:
    item = {k: v for k, v in record.items() if k not in ("c", "id")}
    data_table.put_item(Item=_to_db({**item, "c": collection, "id": record_id}))
    return {**item, "id": record_id}


def _slug(value: str, what: str) -> str:
    if not _SLUG.match(value):
        raise HTTPException(400, f"{what} must be lowercase letters, numbers and dashes, up to 40 characters.")
    return value


def _locations() -> list:
    found = {row["SK"][9:]: row.get("name", "") for row in _query(CONFIG_PK, "LOCATION#")}
    found.setdefault(DEFAULT_LOCATION, "Main branch")
    return [{"locationId": k, "name": v} for k, v in sorted(found.items(), key=lambda kv: (kv[0] != DEFAULT_LOCATION, kv[1].lower()))]


def ensure_data_table() -> None:
    try:
        _db.create_table(
            TableName=DATA_TABLE_NAME,
            KeySchema=[{"AttributeName": "c", "KeyType": "HASH"}, {"AttributeName": "id", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "c", "AttributeType": "S"}, {"AttributeName": "id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        logger.info("Created table %s", DATA_TABLE_NAME)
    except _db.meta.client.exceptions.ResourceInUseException:
        pass
    except Exception as e:
        logger.warning("Could not create %s; console records will not save: %s", DATA_TABLE_NAME, e)


def audit(user: dict, action: str, target: str = "", detail: str = "") -> None:
    """Append-only trail of who did what. There is no endpoint to edit or delete these."""
    try:
        data_table.put_item(Item={"c": "audit", "id": _new_id(), "at": _now(), "user": user.get("user", "?"),
                                  "role": user.get("role", "?"), "action": action, "target": str(target)[:120], "detail": str(detail)[:300]})
    except Exception as e:
        logger.warning("Could not write audit event %s: %s", action, e)


# ---------- sign-in ----------

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def _sign(expires: int, user: str, role: str, location: str) -> str:
    return hmac.new(ADMIN_PASSWORD.encode(), f"{expires}|{user}|{role}|{location}".encode(), hashlib.sha256).hexdigest()


def _token(user: str, role: str, location: str) -> str:
    expires = int(time.time()) + TOKEN_HOURS * 3600
    return f"{expires}.{user}.{role}.{location}.{_sign(expires, user, role, location)}"


def current_user(authorization: str = Header(default="")) -> dict:
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "The console is locked. Set ADMIN_PASSWORD on the server.")
    parts = (authorization[7:].strip() if authorization.startswith("Bearer ") else "").split(".")
    if len(parts) != 5 or not parts[0].isdigit() or int(parts[0]) < time.time() \
            or parts[2] not in ROLE_CAPS or not hmac.compare_digest(parts[4], _sign(int(parts[0]), parts[1], parts[2], parts[3])):
        raise HTTPException(401, "Sign in again.")
    return {"user": parts[1], "role": parts[2], "location": parts[3]}


def can(user: dict, capability: str) -> bool:
    return capability in ROLE_CAPS.get(user["role"], set())


def need(capability: str):
    def check(user: dict = Depends(current_user)) -> dict:
        if not can(user, capability):
            raise HTTPException(403, "Your role does not allow this. Ask a manager.")
        return user
    return check


def _scope(user: dict, requested: Optional[str]) -> str:
    return user["location"] if user["location"] != ALL else (requested or ALL)


def _in_scope(row: dict, location: str) -> bool:
    return location == ALL or (row.get("locationId") or row.get("branchId") or DEFAULT_LOCATION) == location


router = APIRouter(prefix="/admin/api")


class LoginIn(BaseModel):
    username: str = "admin"
    password: str


@router.post("/login")
def login(body: LoginIn):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "The console is locked. Set ADMIN_PASSWORD on the server.")
    username = body.username.strip().lower() or "admin"
    role = location = None
    if username == "admin":
        if hmac.compare_digest(body.password.encode(), ADMIN_PASSWORD.encode()):
            role, location = "merchant_admin", ALL
    elif _SLUG.match(username):
        staff = menu_table.get_item(Key={"PK": CONFIG_PK, "SK": f"STAFF#{username}"}).get("Item")
        if staff and hmac.compare_digest(_hash(body.password, str(staff.get("salt", ""))), str(staff.get("hash", ""))):
            role = str(staff.get("role", "cashier"))
            role, location = _OLD_ROLES.get(role, role), str(staff.get("location", ALL))
    if role not in ROLE_CAPS:
        time.sleep(1)  # slows down password guessing
        raise HTTPException(401, "Wrong username or password.")
    user = {"user": username, "role": role, "location": location}
    audit(user, "sign_in")
    return {"token": _token(username, role, location), **user}


def _business(settings: dict) -> dict:
    keys = ("legalName", "trn", "address", "currency", "vatRate", "pricesIncludeVat", "prepSlaMinutes")
    return {k: settings.get(k) for k in keys}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return {**user, "caps": sorted(ROLE_CAPS[user["role"]]), "locations": _locations(), "statuses": STATUSES, "voices": VOICES,
            "roles": list(ROLE_CAPS), "wasteReasons": WASTE_REASONS, "moveTypes": MOVE_TYPES, "business": _business(get_settings())}


# ---------- orders, kitchen, payment, refunds ----------

class StatusIn(BaseModel):
    status: str


class PaymentIn(BaseModel):
    method: str


class CustomerIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    name: str = Field(default="", max_length=80)
    marketingConsent: bool = False


class RefundIn(BaseModel):
    kind: str = "refund"
    amount: int = Field(default=0, ge=0, le=10_000_000)
    reason: str = Field(min_length=3, max_length=200)


def _order(order_id: str, user: dict) -> dict:
    item = orders_table.get_item(Key={"orderId": order_id}).get("Item")
    order = plain(item) if item else None
    if not order or not _in_scope(order, _scope(user, None)):
        raise HTTPException(404, "Order not found.")
    return order


def _set_order(order_id: str, **fields) -> None:
    names = {f"#f{n}": k for n, k in enumerate(fields)}
    values = {f":v{n}": _to_db(v) for n, v in enumerate(fields.values())}
    orders_table.update_item(Key={"orderId": order_id}, UpdateExpression="SET " + ", ".join(f"#f{n} = :v{n}" for n in range(len(fields))),
                             ExpressionAttributeNames=names, ExpressionAttributeValues=values)


@router.get("/orders")
def list_orders(location: Optional[str] = None, user: dict = Depends(need("orders.view"))):
    scope = _scope(user, location)
    rows = [r for r in _scan_all(orders_table) if _in_scope(r, scope)]
    for row in rows:
        row.setdefault("status", "received")
        row.setdefault("locationId", DEFAULT_LOCATION)
        row.setdefault("paymentStatus", "unpaid")
    rows.sort(key=lambda r: str(r.get("createdAt", "")), reverse=True)
    return {"orders": rows[:300]}


@router.patch("/orders/{order_id}")
def set_order_status(order_id: str, body: StatusIn, user: dict = Depends(need("orders.status"))):
    if body.status not in STATUSES:
        raise HTTPException(400, "Status must be one of: " + ", ".join(STATUSES) + ".")
    order = _order(order_id, user)
    fields = {"status": body.status, "statusUpdatedAt": _now(), "statusUpdatedBy": user["user"]}
    stamp = {"preparing": "preparingAt", "ready": "readyAt", "completed": "completedAt"}.get(body.status)
    if stamp and not order.get(stamp):
        fields[stamp] = _now()
    deducted = 0
    if body.status == "completed" and not order.get("stockDeducted"):
        deducted = _deduct_stock(order, user)   # recipe-based stock deduction, once per order
        fields["stockDeducted"] = True
    _set_order(order_id, **fields)
    audit(user, "order_status", order_id, body.status)
    return {"orderId": order_id, "status": body.status, "stockMoves": deducted}


@router.post("/orders/{order_id}/payment")
def take_payment(order_id: str, body: PaymentIn, user: dict = Depends(need("orders.status"))):
    if body.method not in ("cash", "card"):
        raise HTTPException(400, "Payment method must be cash or card.")
    order = _order(order_id, user)
    if order.get("paymentStatus") in ("captured", "refunded", "voided"):
        raise HTTPException(400, "This order's payment is already settled.")   # guards against charging twice
    _set_order(order_id, paymentStatus="captured", paymentMethod=body.method, paidAt=_now(), paidBy=user["user"])
    audit(user, "payment_taken", order_id, f"{body.method} {order.get('total', 0)}")
    return {"orderId": order_id, "paymentStatus": "captured"}


@router.post("/orders/{order_id}/customer")
def attach_customer(order_id: str, body: CustomerIn, user: dict = Depends(need("orders.status"))):
    phone = re.sub(r"[^\d+]", "", body.phone)
    if len(phone) < 6:
        raise HTTPException(400, "Enter a phone number.")
    _order(order_id, user)
    _set_order(order_id, customerPhone=phone, customerName=body.name)
    existing = _record("customers", phone) or {"createdAt": _now()}
    existing.update({"phone": phone, "marketingConsent": body.marketingConsent, "consentAt": _now() if body.marketingConsent else existing.get("consentAt", "")})
    if body.name:
        existing["name"] = body.name
    _save("customers", phone, existing)
    audit(user, "customer_attached", order_id, phone[-4:].rjust(len(phone), "*"))
    return {"orderId": order_id, "customerPhone": phone}


@router.post("/orders/{order_id}/refund")
def refund_order(order_id: str, body: RefundIn, user: dict = Depends(need("orders.refund"))):
    order = _order(order_id, user)
    total, already = int(order.get("total") or 0), int(order.get("refundedTotal") or 0)
    if body.kind == "void":
        if order.get("paymentStatus") == "captured":
            raise HTTPException(400, "This order has been paid. Refund it instead of voiding it.")
        _set_order(order_id, status="cancelled", paymentStatus="voided", statusUpdatedAt=_now(), statusUpdatedBy=user["user"])
        amount = 0
    elif body.kind == "refund":
        if order.get("paymentStatus") not in ("captured", "partially_refunded"):
            raise HTTPException(400, "Only paid orders can be refunded. Void this order instead.")
        amount = body.amount or (total - already)
        if amount <= 0 or amount > total - already:
            raise HTTPException(400, "The refund is more than what is left on this order.")
        _set_order(order_id, refundedTotal=already + amount, paymentStatus="refunded" if already + amount >= total else "partially_refunded")
    else:
        raise HTTPException(400, "Choose refund or void.")
    _save("refunds", _new_id(), {"orderId": order_id, "kind": body.kind, "amount": amount, "reason": body.reason, "by": user["user"], "at": _now(),
                                 "locationId": order.get("locationId", DEFAULT_LOCATION)})
    audit(user, "order_" + body.kind, order_id, f"{amount} {body.reason}")
    return {"orderId": order_id, "kind": body.kind, "amount": amount}


# ---------- inventory: stock ledger, recipes, waste, purchasing ----------

def _move(user: dict, ingredient_id: str, qty: float, kind: str, ref: str = "", note: str = "", branch: str = DEFAULT_LOCATION, cost: Optional[int] = None) -> None:
    """Every stock change is one ledger line plus an atomic change to the quantity on hand."""
    try:
        data_table.update_item(Key={"c": "ingredients", "id": ingredient_id}, UpdateExpression="ADD onHand :q",
                               ExpressionAttributeValues={":q": Decimal(str(round(qty, 4)))}, ConditionExpression="attribute_exists(#i)",
                               ExpressionAttributeNames={"#i": "id"})
    except _db.meta.client.exceptions.ConditionalCheckFailedException:
        raise HTTPException(404, f"Ingredient '{ingredient_id}' does not exist.")
    line = {"at": _now(), "ingredientId": ingredient_id, "qty": round(qty, 4), "type": kind, "ref": ref, "note": note[:200], "by": user["user"], "branchId": branch}
    if cost is not None:
        line["cost"] = cost
    _save("stock_moves", _new_id(), line)


def _deduct_stock(order: dict, user: dict) -> int:
    recipes = {r["id"]: r for r in _records("recipes")}
    ingredients = {i["id"]: i for i in _records("ingredients")}
    moves = 0
    for item in order.get("items") or []:
        item_id = str(item.get("itemId", ""))
        recipe = recipes.get(item_id) or (recipes.get("custom-burger") if item_id.startswith("custom-burger") else None)
        for line in (recipe or {}).get("lines") or []:
            ingredient = ingredients.get(line.get("ingredientId"))
            if not ingredient:
                continue
            yield_pct = float(ingredient.get("yieldPct") or 100) or 100
            qty = float(line.get("qty") or 0) * int(item.get("quantity") or 1) / (yield_pct / 100)
            if qty > 0:
                _move(user, ingredient["id"], -qty, "consumption", ref=str(order.get("orderId", "")), branch=order.get("locationId", DEFAULT_LOCATION))
                moves += 1
    return moves


class AdjustIn(BaseModel):
    ingredientId: str
    qty: float = Field(ge=-1_000_000, le=1_000_000)
    type: str = "adjustment"
    note: str = Field(default="", max_length=200)
    branchId: str = DEFAULT_LOCATION


@router.post("/inventory/adjust")
def adjust_stock(body: AdjustIn, user: dict = Depends(need("inventory.edit"))):
    if body.type not in MOVE_TYPES:
        raise HTTPException(400, "Type must be one of: " + ", ".join(MOVE_TYPES) + ".")
    qty = body.qty
    if body.type == "count":   # a count states what is on the shelf; the ledger records the difference
        ingredient = _record("ingredients", body.ingredientId)
        if not ingredient:
            raise HTTPException(404, "Ingredient not found.")
        qty = body.qty - float(ingredient.get("onHand") or 0)
    if qty == 0:
        return {"ingredientId": body.ingredientId, "change": 0}
    _move(user, body.ingredientId, qty, body.type, note=body.note, branch=body.branchId)
    audit(user, "stock_" + body.type, body.ingredientId, f"{qty:+g} {body.note}")
    return {"ingredientId": body.ingredientId, "change": qty}


class WasteIn(BaseModel):
    ingredientId: str
    qty: float = Field(gt=0, le=1_000_000)
    reason: str
    stage: str = "pre-consumer"
    note: str = Field(default="", max_length=200)
    orderId: str = Field(default="", max_length=40)
    branchId: str = DEFAULT_LOCATION


@router.post("/waste")
def log_waste(body: WasteIn, user: dict = Depends(need("waste.log"))):
    if body.reason not in WASTE_REASONS:
        raise HTTPException(400, "Reason must be one of: " + ", ".join(WASTE_REASONS) + ".")
    if body.stage not in ("pre-consumer", "post-consumer"):
        raise HTTPException(400, "Stage must be pre-consumer or post-consumer.")
    ingredient = _record("ingredients", body.ingredientId)
    if not ingredient:
        raise HTTPException(404, "Ingredient not found.")
    cost = round(body.qty * float(ingredient.get("unitCost") or 0))
    _move(user, body.ingredientId, -body.qty, "waste", ref=body.orderId, note=body.reason, branch=body.branchId, cost=cost)
    record = _save("waste", _new_id(), {"at": _now(), "ingredientId": body.ingredientId, "ingredientName": ingredient.get("name", ""), "qty": body.qty,
                                        "unit": ingredient.get("unit", ""), "cost": cost, "reason": body.reason, "stage": body.stage, "note": body.note,
                                        "orderId": body.orderId, "by": user["user"], "branchId": body.branchId})
    audit(user, "waste_logged", body.ingredientId, f"{body.qty:g} {ingredient.get('unit', '')} {body.reason}")
    return record


class ReceiveLine(BaseModel):
    ingredientId: str
    qtyReceived: float = Field(ge=0, le=1_000_000)
    unitCost: int = Field(ge=0, le=10_000_000)


class ReceiveIn(BaseModel):
    lines: List[ReceiveLine]


@router.post("/purchase-orders/{po_id}/approve")
def approve_po(po_id: str, user: dict = Depends(need("purchasing.approve"))):
    po = _record("purchase_orders", po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found.")
    if po.get("status") != "draft":
        raise HTTPException(400, "Only draft purchase orders can be approved.")
    po.update(status="approved", approvedBy=user["user"], approvedAt=_now())
    _save("purchase_orders", po_id, po)
    audit(user, "po_approved", po_id)
    return po


@router.post("/purchase-orders/{po_id}/receive")
def receive_po(po_id: str, body: ReceiveIn, user: dict = Depends(need("purchasing.edit"))):
    po = _record("purchase_orders", po_id)
    if not po:
        raise HTTPException(404, "Purchase order not found.")
    if po.get("status") != "approved":
        raise HTTPException(400, "Approve this purchase order before receiving goods against it.")
    ordered = {l.get("ingredientId"): l for l in po.get("lines") or []}
    received = []
    for line in body.lines:
        ingredient = _record("ingredients", line.ingredientId)
        if not ingredient:
            raise HTTPException(404, f"Ingredient '{line.ingredientId}' does not exist.")
        if line.qtyReceived > 0:
            _move(user, line.ingredientId, line.qtyReceived, "purchase", ref=po_id, branch=po.get("branchId", DEFAULT_LOCATION), cost=round(line.qtyReceived * line.unitCost))
        history = (ingredient.get("priceHistory") or [])[-11:] + [{"at": _now(), "unitCost": line.unitCost, "supplierId": po.get("supplierId", "")}]
        data_table.update_item(Key={"c": "ingredients", "id": line.ingredientId}, UpdateExpression="SET unitCost = :c, priceHistory = :h",
                               ExpressionAttributeValues={":c": line.unitCost, ":h": _to_db(history)})
        want = ordered.get(line.ingredientId, {})
        received.append({"ingredientId": line.ingredientId, "qtyOrdered": want.get("qty", 0), "qtyReceived": line.qtyReceived,
                         "unitCostOrdered": want.get("unitCost", 0), "unitCost": line.unitCost})
    po.update(status="received", received=received, receivedBy=user["user"], receivedAt=_now())
    _save("purchase_orders", po_id, po)
    audit(user, "po_received", po_id, f"{len(received)} lines")
    return po


class AssetMoveIn(BaseModel):
    action: str
    holder: str = Field(default="", max_length=80)
    dueAt: str = Field(default="", max_length=40)
    condition: str = Field(default="good", max_length=40)
    note: str = Field(default="", max_length=200)


@router.post("/assets/{asset_id}/move")
def move_asset(asset_id: str, body: AssetMoveIn, user: dict = Depends(need("assets.edit"))):
    asset = _record("assets", asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found.")
    if body.action == "checkout":
        if not body.holder:
            raise HTTPException(400, "Say who is taking the asset.")
        asset.update(status="out", holder=body.holder, dueAt=body.dueAt, outAt=_now())
    elif body.action == "checkin":
        asset.update(status="lost" if body.condition == "lost" else "maintenance" if body.condition == "damaged" else "in", holder="", dueAt="", condition=body.condition)
    else:
        raise HTTPException(400, "Action must be checkout or checkin.")
    _save("assets", asset_id, asset)
    _save("asset_moves", _new_id(), {"at": _now(), "assetId": asset_id, "action": body.action, "holder": body.holder, "dueAt": body.dueAt,
                                     "condition": body.condition, "note": body.note, "by": user["user"]})
    audit(user, "asset_" + body.action, asset_id, body.holder or body.condition)
    return asset


# ---------- console records (ingredients, recipes, suppliers, purchase orders, assets, customers, coupons, campaigns) ----------

def _collection(name: str, user: dict, write: bool) -> None:
    spec = COLLECTIONS.get(name)
    if not spec:
        raise HTTPException(404, "Unknown record type.")
    capability = spec[1] if write else spec[0]
    if capability is None:
        raise HTTPException(405, "These records are created by their own actions and cannot be edited directly.")
    if not can(user, capability):
        raise HTTPException(403, "Your role does not allow this. Ask a manager.")


@router.get("/data/{collection}")
def list_records(collection: str, user: dict = Depends(current_user)):
    _collection(collection, user, write=False)
    rows = _records(collection)
    if collection in ("stock_moves", "waste", "asset_moves", "refunds", "audit"):
        rows = sorted(rows, key=lambda r: r["id"], reverse=True)[:500]
    return {"records": rows}


@router.put("/data/{collection}/{record_id}")
def save_record(collection: str, record_id: str, body: Dict[str, Any], user: dict = Depends(current_user)):
    _collection(collection, user, write=True)
    if not _ID.match(record_id):
        raise HTTPException(400, "The ID can use letters, numbers, dots and dashes, up to 64 characters.")
    if len(str(body)) > 20_000:
        raise HTTPException(400, "This record is too large.")
    existing = _record(collection, record_id) or {}
    record = {**body, "updatedAt": _now(), "updatedBy": user["user"], "createdAt": existing.get("createdAt") or _now()}
    if collection == "ingredients":       # quantity and price history only change through the stock ledger
        record["onHand"] = existing.get("onHand", 0)
        record["priceHistory"] = existing.get("priceHistory", [])
    if collection == "purchase_orders":   # approval and receiving have their own actions and permission
        record["status"] = existing.get("status", "draft")
        if existing.get("status") in ("approved", "received"):
            raise HTTPException(400, "This purchase order is already approved and can no longer be edited.")
    saved = _save(collection, record_id, record)
    audit(user, "saved_" + collection, record_id)
    return saved


@router.delete("/data/{collection}/{record_id}")
def delete_record(collection: str, record_id: str, user: dict = Depends(current_user)):
    _collection(collection, user, write=True)
    data_table.delete_item(Key={"c": collection, "id": record_id})
    audit(user, "deleted_" + collection, record_id)
    return {"deleted": record_id}


# ---------- menu ----------

class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    sortOrder: int = 0


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    price: int = Field(ge=0, le=1_000_000, description="Price in fils")
    featured: bool = False
    available: bool = True
    sortOrder: int = 0
    imageUrl: str = Field(default="", max_length=300)
    station: str = Field(default="", max_length=30)


@router.get("/menu")
def get_menu(user: dict = Depends(need("orders.view"))):
    categories, items = [], []
    for row in _scan_all(menu_table):
        pk, sk = str(row.get("PK", "")), str(row.get("SK", ""))
        if not pk.startswith("CATEGORY#"):
            continue
        category_id = pk[9:]
        if sk == "METADATA":
            categories.append({"categoryId": category_id, "name": row.get("name", ""), "sortOrder": row.get("sortOrder", 0)})
        elif sk.startswith("ITEM#"):
            items.append({
                "categoryId": category_id, "itemId": sk[5:], "name": row.get("name", ""),
                "description": row.get("description", ""), "price": row.get("price", 0),
                "featured": bool(row.get("featured", False)), "available": row.get("available") is not False,
                "sortOrder": row.get("sortOrder", 0), "imageUrl": row.get("imageUrl", ""), "station": row.get("station", ""),
            })
    categories.sort(key=lambda c: c["sortOrder"])
    items.sort(key=lambda i: (i["categoryId"], i["sortOrder"]))
    return {"categories": categories, "items": items}


@router.put("/menu/categories/{category_id}")
def save_category(category_id: str, body: CategoryIn, user: dict = Depends(need("menu.edit"))):
    _slug(category_id, "Category ID")
    menu_table.put_item(Item={"PK": f"CATEGORY#{category_id}", "SK": "METADATA", "name": body.name, "sortOrder": body.sortOrder})
    for item in _query(f"CATEGORY#{category_id}", "ITEM#"):
        if item.get("category") != body.name:
            menu_table.update_item(Key={"PK": item["PK"], "SK": item["SK"]}, UpdateExpression="SET #c = :c",
                                   ExpressionAttributeNames={"#c": "category"}, ExpressionAttributeValues={":c": body.name})
    audit(user, "menu_category_saved", category_id)
    return {"categoryId": category_id}


@router.delete("/menu/categories/{category_id}")
def delete_category(category_id: str, user: dict = Depends(need("menu.edit"))):
    _slug(category_id, "Category ID")
    with menu_table.batch_writer() as batch:
        for item in _query(f"CATEGORY#{category_id}", "ITEM#"):
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        batch.delete_item(Key={"PK": f"CATEGORY#{category_id}", "SK": "METADATA"})
    audit(user, "menu_category_deleted", category_id)
    return {"deleted": category_id}


@router.put("/menu/items/{category_id}/{item_id}")
def save_item(category_id: str, item_id: str, body: ItemIn, user: dict = Depends(need("menu.edit"))):
    _slug(category_id, "Category ID")
    _slug(item_id, "Item ID")
    category = menu_table.get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": "METADATA"}).get("Item")
    if not category:
        raise HTTPException(404, "That category does not exist.")
    menu_table.put_item(Item={
        "PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}", "name": body.name, "description": body.description,
        "price": body.price, "featured": body.featured, "available": body.available, "sortOrder": body.sortOrder,
        "imageUrl": body.imageUrl, "station": body.station, "category": str(category.get("name", "")),
    })
    audit(user, "menu_item_saved", item_id, f"price {body.price} available {body.available}")
    return {"categoryId": category_id, "itemId": item_id}


@router.delete("/menu/items/{category_id}/{item_id}")
def delete_item(category_id: str, item_id: str, user: dict = Depends(need("menu.edit"))):
    _slug(category_id, "Category ID")
    menu_table.delete_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    audit(user, "menu_item_deleted", item_id)
    return {"deleted": item_id}


class BurgerIn(BaseModel):
    basePrice: int = Field(ge=0, le=100_000)
    toppings: Dict[str, int]
    sauces: Dict[str, int]


def _clean_prices(prices: Dict[str, int], what: str) -> dict:
    if len(prices) > 40:
        raise HTTPException(400, f"Keep {what} to 40 or fewer.")
    clean = {}
    for name, price in prices.items():
        name = re.sub(r"\s+", " ", name).strip().lower()
        if not name or len(name) > 40 or not 0 <= price <= 100_000:
            raise HTTPException(400, f"Each of the {what} needs a name of up to 40 characters and a price of zero or more.")
        clean[name] = price
    return clean


@router.get("/burger", dependencies=[Depends(need("orders.view"))])
def get_burger():
    return get_burger_config()


@router.put("/burger")
def save_burger(body: BurgerIn, user: dict = Depends(need("menu.edit"))):
    value = {"basePrice": body.basePrice, "toppings": _clean_prices(body.toppings, "toppings"), "sauces": _clean_prices(body.sauces, "sauces")}
    put_config("BURGER", value)
    audit(user, "burger_prices_saved")
    return value


# ---------- settings ----------

class SettingsIn(BaseModel):
    greeting: str = Field(min_length=1, max_length=200)
    voice: str
    upsell: str = Field(default="", max_length=300)
    hoursEnabled: bool = False
    openTime: str
    closeTime: str
    utcOffset: str
    closedMessage: str = Field(min_length=1, max_length=200)
    accessCode: str = Field(default="", max_length=40)
    costPer1kInput: float = Field(default=0, ge=0, le=1000)
    costPer1kOutput: float = Field(default=0, ge=0, le=1000)
    legalName: str = Field(default="", max_length=120)
    trn: str = Field(default="", max_length=20)
    address: str = Field(default="", max_length=200)
    currency: str = Field(default="AED", max_length=3)
    vatRate: float = Field(default=5, ge=0, le=100)
    pricesIncludeVat: bool = True
    prepSlaMinutes: int = Field(default=8, ge=1, le=240)


@router.get("/settings", dependencies=[Depends(need("settings.manage"))])
def read_settings():
    return get_settings()


@router.put("/settings")
def save_settings(body: SettingsIn, user: dict = Depends(need("settings.manage"))):
    if body.voice not in VOICES:
        raise HTTPException(400, "Voice must be one of: " + ", ".join(VOICES) + ".")
    if not _TIME.match(body.openTime) or not _TIME.match(body.closeTime):
        raise HTTPException(400, "Opening and closing times must look like 09:00.")
    if not _OFFSET.match(body.utcOffset):
        raise HTTPException(400, "Time zone offset must look like +04:00.")
    if body.accessCode and not re.fullmatch(r"[A-Za-z0-9-]+", body.accessCode):
        raise HTTPException(400, "The access code can use letters, numbers and dashes only.")
    if body.trn and not re.fullmatch(r"\d{15}", body.trn):
        raise HTTPException(400, "A UAE tax registration number has 15 digits.")
    value = body.model_dump()
    for key in ("costPer1kInput", "costPer1kOutput", "vatRate"):   # stored as text: the database rejects Python floats
        value[key] = repr(value[key])
    put_config("SETTINGS", value)
    audit(user, "settings_saved")
    return value


# ---------- analytics ----------

@router.get("/dashboard")
def dashboard(location: Optional[str] = None, days: int = 14, user: dict = Depends(need("analytics.view"))):
    days = max(1, min(days, 90))
    scope = _scope(user, location)
    orders = [o for o in _scan_all(orders_table) if _in_scope(o, scope) and o.get("status") != "cancelled"]
    today = datetime.now(timezone.utc).date()
    window = [(today - timedelta(days=n)).isoformat() for n in range(days - 1, -1, -1)]
    per_day = {d: {"date": d, "orders": 0, "revenue": 0} for d in window}
    top = defaultdict(lambda: {"quantity": 0, "revenue": 0})
    methods = defaultdict(int)
    count = revenue = refunded = 0
    prep = []
    for order in orders:
        day = str(order.get("createdAt", ""))[:10]
        if not _DAY.match(day) or day not in per_day:
            continue
        total = int(order.get("total") or 0)
        count += 1
        revenue += total
        refunded += int(order.get("refundedTotal") or 0)
        methods[str(order.get("paymentMethod") or "unpaid")] += total
        per_day[day]["orders"] += 1
        per_day[day]["revenue"] += total
        try:
            if order.get("readyAt"):
                prep.append((datetime.fromisoformat(order["readyAt"]) - datetime.fromisoformat(str(order["createdAt"]).replace("Z", "+00:00"))).total_seconds())
        except (ValueError, TypeError):
            pass
        for item in order.get("items") or []:
            qty = int(item.get("quantity") or 1)
            entry = top[str(item.get("name", "Unknown"))]
            entry["quantity"] += qty
            entry["revenue"] += qty * int(item.get("unitPrice") or item.get("price") or 0)
    top_items = sorted(({"name": n, **v} for n, v in top.items()), key=lambda i: -i["quantity"])[:10]
    return {"days": list(per_day.values()), "orders": count, "revenue": revenue, "refunded": refunded,
            "averageOrder": round(revenue / count) if count else 0, "topItems": top_items, "windowDays": days,
            "byPayment": dict(methods), "averagePrepSeconds": round(sum(prep) / len(prep)) if prep else 0}


@router.get("/insights")
def insights(location: Optional[str] = None, days: int = 14, user: dict = Depends(need("analytics.view"))):
    days = max(1, min(days, 90))
    scope = _scope(user, location)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    calls = [c for c in _scan_all(sessions_table) if _in_scope(c, scope) and str(c.get("startedAt", "")) >= since]
    calls.sort(key=lambda c: str(c.get("startedAt", "")), reverse=True)
    names = {}
    for row in _scan_all(menu_table):
        if str(row.get("SK", "")).startswith("ITEM#"):
            names[row["SK"][5:]] = row.get("name", "")
    ordered = [c for c in calls if c.get("orderPlaced")]
    abandoned = [c for c in calls if not c.get("orderPlaced") and c.get("added")]
    skipped = defaultdict(int)
    for call in calls:
        for item_id in set(call.get("viewed") or []) - set(call.get("added") or []):
            skipped[item_id] += 1
    settings = get_settings()
    tokens_in = sum(int(c.get("inputTokens") or 0) for c in calls)
    tokens_out = sum(int(c.get("outputTokens") or 0) for c in calls)
    try:
        rate_in, rate_out = float(settings.get("costPer1kInput") or 0), float(settings.get("costPer1kOutput") or 0)
    except (TypeError, ValueError):
        rate_in = rate_out = 0.0
    cost = tokens_in / 1000 * rate_in + tokens_out / 1000 * rate_out
    seconds = sum(int(c.get("durationSec") or 0) for c in calls)
    return {
        "windowDays": days, "calls": len(calls), "withOrder": len(ordered), "abandoned": len(abandoned),
        "browsedOnly": len(calls) - len(ordered) - len(abandoned), "failed": len([c for c in calls if c.get("error")]),
        "conversion": round(100 * len(ordered) / len(calls)) if calls else 0,
        "averageSeconds": round(seconds / len(calls)) if calls else 0,
        "notOrdered": sorted(({"itemId": k, "name": names.get(k, k), "calls": v} for k, v in skipped.items()), key=lambda i: -i["calls"])[:10],
        "usage": {"minutes": round(seconds / 60, 1), "inputTokens": tokens_in, "outputTokens": tokens_out, "ratesSet": rate_in > 0 or rate_out > 0,
                  "estimatedCost": round(cost, 4), "costPerOrder": round(cost / len(ordered), 4) if ordered and cost else 0},
        "recent": [{k: c.get(k) for k in ("sessionId", "startedAt", "durationSec", "locationId", "orderPlaced", "orderId", "orderTotal", "error")} for c in calls[:25]],
    }


# ---------- branches and team ----------

class LocationIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.put("/locations/{location_id}")
def save_location(location_id: str, body: LocationIn, user: dict = Depends(need("settings.manage"))):
    _slug(location_id, "Branch ID")
    if location_id == ALL:
        raise HTTPException(400, "Choose a different branch ID.")
    menu_table.put_item(Item={"PK": CONFIG_PK, "SK": f"LOCATION#{location_id}", "name": body.name})
    audit(user, "branch_saved", location_id)
    return {"locations": _locations()}


@router.delete("/locations/{location_id}")
def delete_location(location_id: str, user: dict = Depends(need("settings.manage"))):
    if location_id == DEFAULT_LOCATION:
        raise HTTPException(400, "The main branch can be renamed but not deleted.")
    menu_table.delete_item(Key={"PK": CONFIG_PK, "SK": f"LOCATION#{location_id}"})
    audit(user, "branch_deleted", location_id)
    return {"locations": _locations()}


class StaffIn(BaseModel):
    role: str
    location: str = ALL
    password: Optional[str] = Field(default=None, min_length=6, max_length=100)


@router.get("/staff", dependencies=[Depends(need("team.manage"))])
def list_staff():
    return {"staff": [{"username": r["SK"][6:], "role": _OLD_ROLES.get(r.get("role", "cashier"), r.get("role", "cashier")), "location": r.get("location", ALL)}
                      for r in _query(CONFIG_PK, "STAFF#")]}


@router.put("/staff/{username}")
def save_staff(username: str, body: StaffIn, user: dict = Depends(need("team.manage"))):
    _slug(username, "Username")
    if username == "admin":
        raise HTTPException(400, "The admin account is managed with ADMIN_PASSWORD on the server.")
    if body.role not in ROLE_CAPS:
        raise HTTPException(400, "Unknown role.")
    if body.role == "platform_admin" and user["role"] != "platform_admin":
        raise HTTPException(403, "Only a platform admin can create another platform admin.")
    if body.location != ALL and body.location not in {l["locationId"] for l in _locations()}:
        raise HTTPException(400, "That branch does not exist.")
    key = {"PK": CONFIG_PK, "SK": f"STAFF#{username}"}
    existing = menu_table.get_item(Key=key).get("Item")
    if not existing and not body.password:
        raise HTTPException(400, "A new account needs a password or PIN of at least 6 characters.")
    item = {**key, "role": body.role, "location": body.location}
    if body.password:
        item["salt"] = secrets.token_hex(8)
        item["hash"] = _hash(body.password, item["salt"])
    else:
        item["salt"], item["hash"] = existing["salt"], existing["hash"]
    menu_table.put_item(Item=item)
    audit(user, "staff_saved", username, f"{body.role} {body.location}")
    return {"username": username}


@router.delete("/staff/{username}")
def delete_staff(username: str, user: dict = Depends(need("team.manage"))):
    _slug(username, "Username")
    menu_table.delete_item(Key={"PK": CONFIG_PK, "SK": f"STAFF#{username}"})
    audit(user, "staff_removed", username)
    return {"deleted": username}


# ---------- wiring ----------

def setup_admin(app) -> None:
    origins = [o.strip() for o in os.environ.get("ADMIN_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    ensure_sessions_table()
    ensure_data_table()
