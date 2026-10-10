"""VoiceBite Rewards: customer sign-up with a mobile number and a 4-digit PIN, a points wallet and referrals.

Public routes for the ordering app (/rewards/...):

    POST /rewards/join     {phone, pin, name?, referralCode?}   create the account (or set a PIN on a known customer)
    POST /rewards/login    {phone, pin}                         sign in; 5 wrong PINs lock the account for 15 minutes
    GET  /rewards/me       Authorization: Bearer <member token> points, wallet value, referral code, recent orders
    POST /rewards/claim    {orderId, token}                     link an order placed by voice to the member (uses the
                                                               order's private tracking key, so only the customer can)

Points are earned when the kitchen marks a linked order "completed" (award_for_order, called by the console).
A friend who joins with a member's referral code gets welcome points; the member who referred them gets the
referral reward when that friend's first order is completed.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

try:
    from agent import admin_api as A
    from agent import ops
    from agent.shop_config import orders_table
except ModuleNotFoundError:
    import admin_api as A
    import ops
    from shop_config import orders_table

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rewards")
TOKEN_DAYS = 30
MAX_TRIES, LOCK_MINUTES = 5, 15
WEAK_PINS = {"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999", "1234", "4321", "1212", "0123"}
PRIVATE = ("pinHash", "pinSalt", "failedPins", "lockUntil")


# ---------- phone numbers, PINs and member tokens ----------

def norm_phone(raw: str) -> str:
    """One form per number so the same customer is always found: UAE mobiles become +9715XXXXXXXX."""
    digits = re.sub(r"[^\d+]", "", str(raw or ""))
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if re.fullmatch(r"05\d{8}", digits):
        digits = "+971" + digits[1:]
    elif re.fullmatch(r"5\d{8}", digits):
        digits = "+971" + digits
    elif re.fullmatch(r"9715\d{8}", digits):
        digits = "+" + digits
    if not re.fullmatch(r"\+?\d{7,15}", digits):
        raise HTTPException(400, "Enter a valid mobile number.")
    return digits


def _pin_hash(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000).hex()


def _secret() -> bytes:
    base = A.ADMIN_PASSWORD or os.environ.get("REWARDS_SECRET", "")
    if not base:
        raise HTTPException(503, "Rewards are not set up on the server yet.")
    return hashlib.sha256(("rewards|" + base).encode()).digest()


def _token(phone: str) -> str:
    expires = int(time.time()) + TOKEN_DAYS * 86400
    sig = hmac.new(_secret(), f"{expires}|{phone}".encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{phone}.{sig}"


def _member_from(authorization: str) -> str:
    parts = (authorization[7:].strip() if authorization.startswith("Bearer ") else "").split(".")
    if len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) < time.time():
        raise HTTPException(401, "Sign in again.")
    expected = hmac.new(_secret(), f"{parts[0]}|{parts[1]}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(parts[2], expected):
        raise HTTPException(401, "Sign in again.")
    return parts[1]


def _new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I to misread
    taken = {c.get("referralCode") for c in A._records("customers")}
    while True:
        code = "VB" + "".join(secrets.choice(alphabet) for _ in range(5))
        if code not in taken:
            return code


# ---------- the points ledger ----------

def add_points(phone: str, points: int, kind: str, order_id: str = "", note: str = "", by: str = "system") -> int:
    """Every change to a wallet is one ledger line plus an atomic change to the balance. Returns the new balance."""
    customer = A._record("customers", phone)
    if not customer:
        raise HTTPException(404, "No customer with that number.")
    if points < 0 and int(customer.get("points") or 0) + points < 0:
        raise HTTPException(400, f"Only {int(customer.get('points') or 0)} points are available.")
    expression, values = "ADD points :p", {":p": points}
    if points > 0:
        expression += ", lifetimePoints :p"
    result = A.data_table.update_item(Key={"c": "customers", "id": phone}, UpdateExpression=expression,
                                      ExpressionAttributeValues=values, ReturnValues="UPDATED_NEW")
    A._save("loyalty_moves", A._new_id(), {"at": A._now(), "phone": phone, "points": points, "kind": kind, "orderId": order_id,
                                           "note": note[:200], "by": by})
    return int(result.get("Attributes", {}).get("points", 0))


def award_for_order(order: dict) -> int:
    """Points for a completed order linked to a member; once per order. Also pays a pending referral reward."""
    cfg = ops.loyalty_config()
    phone = str(order.get("customerPhone") or "")
    if not cfg["enabled"] or not phone or order.get("pointsAwarded") or order.get("status") == "cancelled":
        return 0
    customer = A._record("customers", phone)
    if not customer or not customer.get("pinHash"):
        return 0                                     # only members who joined Rewards collect points
    paid = max(0, int(order.get("total") or 0) - int(order.get("refundedTotal") or 0))
    points = paid // 100 * cfg["pointsPerAed"]
    order_id = str(order.get("orderId", ""))
    A._set_order(order_id, pointsAwarded=points)
    if points:
        add_points(phone, points, "earn", order_id=order_id)
    referrer = customer.get("referredBy")
    if referrer and not customer.get("referralPaid") and cfg["referrerPoints"]:
        friend = next((c for c in A._records("customers") if c.get("referralCode") == referrer), None)
        if friend and friend["id"] != phone:
            add_points(friend["id"], cfg["referrerPoints"], "referral", order_id=order_id, note=f"Friend {phone[-4:]} placed their first order")
        A._save("customers", phone, {**A._record("customers", phone), "referralPaid": True})
    return points


# ---------- routes ----------

class JoinIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    pin: str
    name: str = Field(default="", max_length=60)
    referralCode: str = Field(default="", max_length=12)
    marketingConsent: bool = False


class LoginIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    pin: str


class ClaimIn(BaseModel):
    orderId: str = Field(min_length=1, max_length=40)
    token: str = Field(min_length=8, max_length=64)


def _check_pin_format(pin: str) -> None:
    if not re.fullmatch(r"\d{4}", pin or ""):
        raise HTTPException(400, "The PIN is 4 digits.")


def _view(phone: str) -> dict:
    cfg = ops.loyalty_config()
    c = A._record("customers", phone) or {}
    orders = [o for o in A._scan_all(orders_table) if str(o.get("customerPhone") or "") == phone]
    orders.sort(key=lambda o: str(o.get("createdAt", "")), reverse=True)
    moves = sorted((m for m in A._records("loyalty_moves") if m.get("phone") == phone), key=lambda m: m["id"], reverse=True)[:15]
    friends = len([x for x in A._records("customers") if c.get("referralCode") and x.get("referredBy") == c.get("referralCode")])
    points = int(c.get("points") or 0)
    return {"phone": phone, "name": c.get("name", ""), "points": points, "walletValue": points * cfg["filsPerPoint"],
            "referralCode": c.get("referralCode", ""), "friendsJoined": friends,
            "program": {k: cfg[k] for k in ("enabled", "pointsPerAed", "filsPerPoint", "welcomePoints", "referrerPoints", "minRedeem")},
            "orders": [{"orderId": o.get("orderId"), "createdAt": o.get("createdAt"), "total": int(o.get("total") or 0), "status": o.get("status"),
                        "points": int(o.get("pointsAwarded") or 0), "items": [f"{int(i.get('quantity') or 1)} x {i.get('name', '')}" for i in (o.get("items") or [])]}
                       for o in orders[:10]],
            "history": [{k: m.get(k) for k in ("at", "points", "kind", "orderId", "note")} for m in moves]}


@router.post("/join")
def join(body: JoinIn):
    _check_pin_format(body.pin)
    if body.pin in WEAK_PINS:
        raise HTTPException(400, "Choose a less obvious PIN than that.")
    phone = norm_phone(body.phone)
    existing = A._record("customers", phone) or {}
    if existing.get("pinHash"):
        raise HTTPException(409, "This number already has an account. Sign in with your PIN.")
    cfg = ops.loyalty_config()
    ref = body.referralCode.strip().upper()
    referrer = next((c for c in A._records("customers") if ref and c.get("referralCode") == ref), None) if ref else None
    if ref and not referrer:
        raise HTTPException(400, "That referral code was not found.")
    salt = secrets.token_hex(8)
    record = {**existing, "phone": phone, "pinSalt": salt, "pinHash": _pin_hash(body.pin, salt), "referralCode": existing.get("referralCode") or _new_code(),
              "joinedAt": A._now(), "points": int(existing.get("points") or 0), "lifetimePoints": int(existing.get("lifetimePoints") or 0),
              "createdAt": existing.get("createdAt") or A._now(), "source": existing.get("source") or "app"}
    if body.name.strip():
        record["name"] = body.name.strip()
    if body.marketingConsent:
        record.update(marketingConsent=True, consentAt=A._now())
    if referrer:
        record["referredBy"] = ref
    A._save("customers", phone, record)
    if referrer and cfg["enabled"] and cfg["welcomePoints"]:
        add_points(phone, cfg["welcomePoints"], "welcome", note=f"Joined with code {ref}")
    A.audit({"user": "customer", "role": "customer"}, "rewards_joined", phone[-4:].rjust(len(phone), "*"), ref)
    return {"token": _token(phone), **_view(phone)}


@router.post("/login")
def login(body: LoginIn):
    _check_pin_format(body.pin)
    phone = norm_phone(body.phone)
    c = A._record("customers", phone)
    if not c or not c.get("pinHash"):
        time.sleep(0.5)
        raise HTTPException(401, "Wrong number or PIN.")
    if str(c.get("lockUntil") or "") > A._now():
        raise HTTPException(429, "Too many wrong PINs. Try again in a few minutes.")
    if not hmac.compare_digest(_pin_hash(body.pin, str(c.get("pinSalt", ""))), str(c["pinHash"])):
        tries = int(c.get("failedPins") or 0) + 1
        update = {"failedPins": 0 if tries >= MAX_TRIES else tries,
                  "lockUntil": (datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)).isoformat() if tries >= MAX_TRIES else ""}
        A._save("customers", phone, {**c, **update})
        time.sleep(0.5)
        raise HTTPException(401, "Wrong number or PIN." + (f" {MAX_TRIES - tries} tries left." if tries < MAX_TRIES else " The account is locked for 15 minutes."))
    if c.get("failedPins") or c.get("lockUntil"):
        A._save("customers", phone, {**c, "failedPins": 0, "lockUntil": ""})
    return {"token": _token(phone), **_view(phone)}


@router.get("/me")
def me(authorization: str = Header(default="")):
    return _view(_member_from(authorization))


@router.post("/claim")
def claim(body: ClaimIn, authorization: str = Header(default="")):
    """Link an order the member just placed by voice to their account, so it earns points."""
    phone = _member_from(authorization)
    item = orders_table.get_item(Key={"orderId": body.orderId}).get("Item")
    saved = str((item or {}).get("trackToken") or "")
    if not saved or not hmac.compare_digest(saved.encode(), body.token.encode()):
        raise HTTPException(404, "Order not found.")
    order = A.plain(item)
    if order.get("customerPhone") and order["customerPhone"] != phone:
        raise HTTPException(409, "This order is already linked to another customer.")
    if not order.get("customerPhone"):
        c = A._record("customers", phone) or {}
        A._set_order(body.orderId, customerPhone=phone, customerName=c.get("name", ""))
        order["customerPhone"] = phone
    earned = award_for_order(order) if order.get("status") == "completed" else 0
    return {"linked": body.orderId, "pointsNow": earned, **_view(phone)}


def setup_rewards(app) -> None:
    app.include_router(router)
