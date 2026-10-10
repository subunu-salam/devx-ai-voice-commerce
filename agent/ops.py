"""VoiceBite operations: stock alerts, daily production and waste, POS sales, and loyalty administration.

Adds routes to the merchant console API (/admin/api/ops/...):

    Stock alerts      every stock item is measured against its par level. At or below the alert threshold
                      (20-30%, set in the console) it is "low", at half that it is "critical", at zero "out".
                      Crossing into one of those states writes an alert the console shows until it is acknowledged.
    Daily production  the kitchen records what it prepared (biryani, cutlets, snacks) and what was thrown away
                      (unsold, dropped, broken). The daily report sets that against what was actually sold
                      (voice orders plus POS sales) and shows the money lost: wasted portions and portions that
                      were made but neither sold nor logged as waste.
    POS sales         a till or POS system posts its daily item sales with an API key, or a manager pastes them in.
    Loyalty           members, points, referrals and manual adjustments (customers join from the ordering app,
                      see rewards.py).

Environment variables: none. Settings live in the console (Settings > Operations).
"""

import hmac
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field

try:
    from agent import admin_api as A
    from agent.shop_config import get_settings, put_config, _get_config, menu_table, orders_table
except ModuleNotFoundError:
    import admin_api as A
    from shop_config import get_settings, put_config, _get_config, menu_table, orders_table

logger = logging.getLogger(__name__)

DEFAULT_OPS = {
    "lowStockPct": 25,          # alert when stock is at or below this share of par (20-30% recommended)
    "criticalStockPct": 12,     # "critical" below this
    "posApiKey": "",            # a POS posts daily sales with this key in the X-POS-Key header
}
DEFAULT_LOYALTY = {
    "enabled": True,
    "pointsPerAed": 1,          # points earned for every AED 1 spent
    "filsPerPoint": 5,          # what one point is worth when redeemed (5 fils = AED 0.05)
    "welcomePoints": 50,        # given when a customer joins with a referral code
    "referrerPoints": 100,      # given to the referrer when their friend's first order is completed
    "minRedeem": 100,           # smallest number of points that can be redeemed at once
}
ITEM_WASTE_REASONS = ["unsold", "dropped", "broken", "burnt", "expired", "returned", "other"]

for name, caps in (("production", ("inventory.view", None)), ("pos_sales", ("inventory.view", None)),
                   ("alerts", ("inventory.view", None)), ("loyalty_moves", ("crm.view", None))):
    A.COLLECTIONS.setdefault(name, caps)

router = A.router


# ---------- settings ----------

def ops_config() -> dict:
    cfg = _get_config("OPS", DEFAULT_OPS)
    return {**DEFAULT_OPS, **cfg}


def loyalty_config() -> dict:
    cfg = _get_config("LOYALTY", DEFAULT_LOYALTY)
    out = {**DEFAULT_LOYALTY, **cfg}
    for k in ("pointsPerAed", "filsPerPoint", "welcomePoints", "referrerPoints", "minRedeem"):
        out[k] = int(float(out.get(k) or 0))
    out["enabled"] = bool(out.get("enabled"))
    return out


class OpsIn(BaseModel):
    lowStockPct: int = Field(default=25, ge=5, le=60)
    criticalStockPct: int = Field(default=12, ge=1, le=50)
    posApiKey: str = Field(default="", max_length=80)


@router.get("/ops/config")
def read_ops(user: dict = Depends(A.need("inventory.view"))):
    cfg = ops_config()
    if not A.can(user, "settings.manage"):
        cfg["posApiKey"] = "set" if cfg.get("posApiKey") else ""
    return cfg


@router.put("/ops/config")
def save_ops(body: OpsIn, user: dict = Depends(A.need("settings.manage"))):
    if body.criticalStockPct >= body.lowStockPct:
        raise HTTPException(400, "The critical level must be below the alert level.")
    if body.posApiKey and not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", body.posApiKey):
        raise HTTPException(400, "The POS key needs at least 16 letters, numbers, dashes or underscores.")
    put_config("OPS", body.model_dump())
    A.audit(user, "ops_settings_saved", "", f"alert {body.lowStockPct}% critical {body.criticalStockPct}%")
    return body.model_dump()


# ---------- stock levels and alerts ----------

def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def stock_level(item: dict, cfg: Optional[dict] = None) -> dict:
    """Where one stock item stands against its par level."""
    cfg = cfg or ops_config()
    on_hand, par = _num(item.get("onHand")), _num(item.get("parLevel"))
    low_pct, crit_pct = int(cfg["lowStockPct"]), int(cfg["criticalStockPct"])
    if par <= 0 and _num(item.get("reorderPoint")) > 0:      # older items only have a reorder point: treat it as the alert line
        par = _num(item.get("reorderPoint")) * 100 / low_pct
    pct = round(100 * on_hand / par) if par > 0 else None
    if on_hand <= 0 and (par > 0 or on_hand < 0):
        status = "out"
    elif pct is None:
        status = "untracked"
    elif pct <= crit_pct:
        status = "critical"
    elif pct <= low_pct:
        status = "low"
    else:
        status = "ok"
    short = max(0.0, par - on_hand) if par > 0 else 0.0
    return {"id": item.get("id"), "name": item.get("name", item.get("id")), "unit": item.get("unit", ""), "onHand": round(on_hand, 3),
            "par": round(par, 3), "pct": pct, "status": status, "shortfall": round(short, 3),
            "refillCost": round(short * _num(item.get("unitCost"))), "perishable": bool(item.get("perishable")),
            "unitCost": _num(item.get("unitCost")), "supplierId": item.get("supplierId", "")}


ALERTING = ("low", "critical", "out")


def check_alert(ingredient_id: str) -> None:
    """Called after every stock change: open an alert when an item drops into low/critical/out, close it when refilled."""
    try:
        item = A._record("ingredients", ingredient_id)
        if not item:
            return
        level = stock_level({**item, "id": ingredient_id})
        current = A._record("alerts", ingredient_id)
        if level["status"] in ALERTING:
            rank = ALERTING.index(level["status"])
            if not current or current.get("resolvedAt") or ALERTING.index(current.get("status", "low")) < rank:
                A._save("alerts", ingredient_id, {"status": level["status"], "pct": level["pct"], "name": level["name"], "onHand": level["onHand"],
                                                  "unit": level["unit"], "openedAt": A._now(), "resolvedAt": "", "ackBy": "", "ackAt": ""})
        elif current and not current.get("resolvedAt"):
            A._save("alerts", ingredient_id, {**current, "resolvedAt": A._now()})
    except Exception as e:   # alerts must never block a stock movement
        logger.warning("Could not check the stock alert for %s: %s", ingredient_id, e)


@router.get("/ops/stock")
def stock_overview(user: dict = Depends(A.need("inventory.view"))):
    cfg = ops_config()
    levels = [stock_level(i, cfg) for i in A._records("ingredients")]
    order = {"out": 0, "critical": 1, "low": 2, "ok": 3, "untracked": 4}
    levels.sort(key=lambda x: (order[x["status"]], x["pct"] if x["pct"] is not None else 999))
    alerts = [a for a in A._records("alerts") if not a.get("resolvedAt")]
    buy = [x for x in levels if x["shortfall"] > 0 and (x["perishable"] or x["status"] in ALERTING)]
    counts = defaultdict(int)
    for x in levels:
        counts[x["status"]] += 1
    return {"config": {k: cfg[k] for k in ("lowStockPct", "criticalStockPct")}, "items": levels, "alerts": alerts,
            "counts": dict(counts), "missingValue": sum(x["refillCost"] for x in levels if x["status"] in ALERTING),
            "purchaseList": buy, "purchaseValue": sum(x["refillCost"] for x in buy)}


@router.post("/ops/alerts/{ingredient_id}/ack")
def ack_alert(ingredient_id: str, user: dict = Depends(A.need("inventory.view"))):
    alert = A._record("alerts", ingredient_id)
    if not alert:
        raise HTTPException(404, "Alert not found.")
    A._save("alerts", ingredient_id, {**alert, "ackBy": user["user"], "ackAt": A._now()})
    return {"acknowledged": ingredient_id}


# ---------- menu items and portion cost ----------

def _menu_items() -> dict:
    items = {}
    for row in A._scan_all(menu_table):
        sk = str(row.get("SK", ""))
        if sk.startswith("ITEM#"):
            items[sk[5:]] = {"itemId": sk[5:], "name": row.get("name", sk[5:]), "price": int(_num(row.get("price"))),
                             "categoryId": str(row.get("PK", "")).replace("CATEGORY#", "")}
    return items


def portion_costs() -> dict:
    """Food cost of one portion of each menu item, from its recipe and current ingredient costs (fils)."""
    ingredients = {i["id"]: i for i in A._records("ingredients")}
    out = {}
    for recipe in A._records("recipes"):
        cost = 0.0
        for line in recipe.get("lines") or []:
            ing = ingredients.get(line.get("ingredientId"))
            if ing:
                yield_pct = _num(ing.get("yieldPct"), 100) or 100
                cost += _num(line.get("qty")) / (yield_pct / 100) * _num(ing.get("unitCost"))
        out[recipe["id"]] = round(cost)
    return out


def _offset() -> timedelta:
    raw = str(get_settings().get("utcOffset") or "+04:00")
    try:
        sign = -1 if raw.startswith("-") else 1
        h, m = raw.lstrip("+-").split(":")
        return sign * timedelta(hours=int(h), minutes=int(m))
    except ValueError:
        return timedelta(hours=4)


def local_day(iso: str = "") -> str:
    """The restaurant's calendar day for a UTC timestamp (or for now)."""
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00")) if iso else datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return (moment.astimezone(timezone.utc) + _offset()).date().isoformat()


def _day(value: str) -> str:
    if not value:
        return local_day()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(400, "Use a date like 2026-10-10.")
    return value


# ---------- daily production and prepared-item waste ----------

class ProductionIn(BaseModel):
    itemId: str = Field(min_length=1, max_length=64)
    qty: float = Field(gt=0, le=100_000)
    day: str = ""
    portionCost: Optional[int] = Field(default=None, ge=0, le=10_000_000)
    note: str = Field(default="", max_length=200)
    branchId: str = A.DEFAULT_LOCATION


@router.post("/ops/production")
def log_production(body: ProductionIn, user: dict = Depends(A.need("waste.log"))):
    day, items = _day(body.day), _menu_items()
    item = items.get(body.itemId)
    if not item:
        raise HTTPException(404, "That menu item does not exist.")
    cost = body.portionCost if body.portionCost is not None else portion_costs().get(body.itemId, 0)
    record = A._save("production", f"{day}#{A._new_id()}", {"day": day, "at": A._now(), "itemId": body.itemId, "name": item["name"], "qty": body.qty,
                                                            "portionCost": cost, "note": body.note, "by": user["user"], "branchId": body.branchId})
    A.audit(user, "production_logged", body.itemId, f"{body.qty:g} on {day}")
    return record


class ItemWasteIn(BaseModel):
    itemId: str = Field(min_length=1, max_length=64)
    qty: float = Field(gt=0, le=100_000)
    reason: str
    day: str = ""
    note: str = Field(default="", max_length=200)
    branchId: str = A.DEFAULT_LOCATION


@router.post("/ops/item-waste")
def log_item_waste(body: ItemWasteIn, user: dict = Depends(A.need("waste.log"))):
    if body.reason not in ITEM_WASTE_REASONS:
        raise HTTPException(400, "Reason must be one of: " + ", ".join(ITEM_WASTE_REASONS) + ".")
    day, items = _day(body.day), _menu_items()
    item = items.get(body.itemId)
    if not item:
        raise HTTPException(404, "That menu item does not exist.")
    made = [p for p in A._records("production") if p.get("day") == day and p.get("itemId") == body.itemId]
    unit = round(_num(made[-1].get("portionCost"))) if made else portion_costs().get(body.itemId, 0)
    record = A._save("waste", A._new_id(), {"at": A._now(), "day": day, "kind": "item", "itemId": body.itemId, "ingredientName": item["name"],
                                            "qty": body.qty, "unit": "portion", "cost": round(unit * body.qty), "reason": body.reason,
                                            "stage": "pre-consumer", "note": body.note, "orderId": "", "by": user["user"], "branchId": body.branchId})
    A.audit(user, "item_waste_logged", body.itemId, f"{body.qty:g} {body.reason}")
    return record


# ---------- POS sales ----------

class PosLine(BaseModel):
    itemId: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=80)
    qty: float = Field(ge=0, le=100_000)
    amount: int = Field(default=0, ge=0, le=100_000_000, description="Sales value in fils")


class PosIn(BaseModel):
    day: str = ""
    ref: str = Field(default="", max_length=40)
    branchId: str = A.DEFAULT_LOCATION
    sales: List[PosLine] = Field(min_length=1, max_length=500)


def _store_pos(body: PosIn, by: str) -> dict:
    day, items = _day(body.day), _menu_items()
    by_name = {v["name"].strip().lower(): k for k, v in items.items()}
    lines, unknown = [], []
    for line in body.sales:
        item_id = line.itemId if line.itemId in items else by_name.get(line.name.strip().lower(), "")
        if not item_id:
            unknown.append(line.itemId or line.name)
            continue
        lines.append({"itemId": item_id, "qty": line.qty, "amount": line.amount})
    ref = re.sub(r"[^A-Za-z0-9_-]", "", body.ref) or "import"
    A._save("pos_sales", f"{day}#{body.branchId}#{ref}", {"day": day, "at": A._now(), "lines": lines, "by": by, "branchId": body.branchId, "ref": ref})
    return {"day": day, "saved": len(lines), "unknown": unknown}


@router.post("/ops/pos/sales")
def pos_push(body: PosIn, x_pos_key: str = Header(default="")):
    """For the POS system itself: authenticated with the key set in the console."""
    key = str(ops_config().get("posApiKey") or "")
    if not key or not hmac.compare_digest(x_pos_key.encode(), key.encode()):
        raise HTTPException(401, "Wrong or missing POS key.")
    return _store_pos(body, "pos")


@router.post("/ops/pos/sales/manual")
def pos_manual(body: PosIn, user: dict = Depends(A.need("inventory.edit"))):
    result = _store_pos(body, user["user"])
    A.audit(user, "pos_sales_imported", result["day"], f"{result['saved']} lines")
    return result


# ---------- the daily report: produced vs sold vs wasted vs missing ----------

@router.get("/ops/daily")
def daily_report(day: str = "", location: Optional[str] = None, user: dict = Depends(A.need("inventory.view"))):
    day, scope = _day(day), A._scope(user, location)
    items, costs = _menu_items(), portion_costs()
    rows = defaultdict(lambda: {"produced": 0.0, "soldVoice": 0.0, "soldPos": 0.0, "wasted": 0.0, "sales": 0, "portionCost": 0, "reasons": defaultdict(float)})

    for p in A._records("production"):
        if p.get("day") == day and A._in_scope(p, scope):
            r = rows[p["itemId"]]
            r["produced"] += _num(p.get("qty"))
            r["portionCost"] = round(_num(p.get("portionCost"))) or r["portionCost"]
    for o in A._scan_all(orders_table):
        if o.get("status") == "cancelled" or not A._in_scope(o, scope) or local_day(o.get("createdAt", "")) != day:
            continue
        for it in o.get("items") or []:
            item_id = "custom-burger" if str(it.get("itemId", "")).startswith("custom-burger") else str(it.get("itemId", ""))
            q = _num(it.get("quantity"), 1)
            rows[item_id]["soldVoice"] += q
            rows[item_id]["sales"] += round(q * _num(it.get("unitPrice") if it.get("unitPrice") is not None else it.get("price")))
    for s in A._records("pos_sales"):
        if s.get("day") == day and A._in_scope(s, scope):
            for line in s.get("lines") or []:
                rows[line["itemId"]]["soldPos"] += _num(line.get("qty"))
                rows[line["itemId"]]["sales"] += round(_num(line.get("amount")))
    ingredient_waste = 0
    for w in A._records("waste"):
        if not A._in_scope(w, scope) or (w.get("day") or local_day(w.get("at", ""))) != day:
            continue
        if w.get("kind") == "item":
            r = rows[w["itemId"]]
            r["wasted"] += _num(w.get("qty"))
            r["reasons"][w.get("reason", "other")] += _num(w.get("qty"))
        else:
            ingredient_waste += round(_num(w.get("cost")))

    out, totals = [], defaultdict(float)
    for item_id, r in rows.items():
        unit = r["portionCost"] or costs.get(item_id, 0)
        sold = r["soldVoice"] + r["soldPos"]
        missing = max(0.0, r["produced"] - sold - r["wasted"]) if r["produced"] > 0 else 0.0
        oversold = max(0.0, sold + r["wasted"] - r["produced"]) if r["produced"] > 0 else 0.0
        row = {"itemId": item_id, "name": items.get(item_id, {}).get("name", item_id), "produced": r["produced"], "sold": sold,
               "soldVoice": r["soldVoice"], "soldPos": r["soldPos"], "wasted": r["wasted"], "missing": missing, "oversold": oversold,
               "portionCost": unit, "wasteCost": round(r["wasted"] * unit), "missingCost": round(missing * unit), "sales": r["sales"],
               "reasons": dict(r["reasons"]), "tracked": r["produced"] > 0}
        row["lostCost"] = row["wasteCost"] + row["missingCost"]
        out.append(row)
        for k in ("produced", "sold", "wasted", "missing", "wasteCost", "missingCost", "lostCost", "sales"):
            totals[k] += row[k]
    out.sort(key=lambda x: (-x["lostCost"], -x["sold"]))

    # Physical stock against what the orders say should have been used: losses that only a stock count reveals.
    ingredients = {i["id"]: i for i in A._records("ingredients")}
    count_loss = defaultdict(float)
    for m in A._records("stock_moves"):
        if m.get("type") == "count" and _num(m.get("qty")) < 0 and local_day(m.get("at", "")) == day and A._in_scope(m, scope):
            count_loss[m["ingredientId"]] += -_num(m.get("qty"))
    stock_gaps = sorted(({"ingredientId": k, "name": ingredients.get(k, {}).get("name", k), "qty": round(v, 3), "unit": ingredients.get(k, {}).get("unit", ""),
                          "cost": round(v * _num(ingredients.get(k, {}).get("unitCost")))} for k, v in count_loss.items()), key=lambda g: -g["cost"])
    totals["stockGapCost"] = sum(g["cost"] for g in stock_gaps)
    totals["ingredientWasteCost"] = ingredient_waste
    totals["totalLost"] = totals["lostCost"] + totals["stockGapCost"] + ingredient_waste
    return {"day": day, "items": out, "stockGaps": stock_gaps, "totals": {k: round(v, 2) for k, v in totals.items()},
            "reasons": ITEM_WASTE_REASONS, "menu": [{"itemId": k, "name": v["name"], "portionCost": costs.get(k, 0)} for k, v in sorted(items.items(), key=lambda kv: kv[1]["name"])]}


@router.get("/ops/trend")
def loss_trend(days: int = 14, location: Optional[str] = None, user: dict = Depends(A.need("inventory.view"))):
    """Money lost per day over the last few days (waste + unaccounted portions + stock-count gaps)."""
    days = max(1, min(days, 31))
    today = datetime.fromisoformat(local_day()).date()
    out = []
    for n in range(days - 1, -1, -1):
        d = (today - timedelta(days=n)).isoformat()
        rep = daily_report(day=d, location=location, user=user)
        t = rep["totals"]
        out.append({"day": d, "wasteCost": t.get("wasteCost", 0) + t.get("ingredientWasteCost", 0), "missingCost": t.get("missingCost", 0) + t.get("stockGapCost", 0)})
    return {"days": out}


# ---------- loyalty administration ----------

class LoyaltyIn(BaseModel):
    enabled: bool = True
    pointsPerAed: int = Field(default=1, ge=0, le=100)
    filsPerPoint: int = Field(default=5, ge=1, le=1000)
    welcomePoints: int = Field(default=50, ge=0, le=100_000)
    referrerPoints: int = Field(default=100, ge=0, le=100_000)
    minRedeem: int = Field(default=100, ge=1, le=1_000_000)


@router.put("/ops/loyalty/config")
def save_loyalty(body: LoyaltyIn, user: dict = Depends(A.need("settings.manage"))):
    put_config("LOYALTY", body.model_dump())
    A.audit(user, "loyalty_settings_saved")
    return body.model_dump()


def _public_member(c: dict) -> dict:
    return {k: c.get(k) for k in ("id", "phone", "name", "points", "referralCode", "referredBy", "joinedAt", "lifetimePoints", "marketingConsent") if k in c} | \
        {"member": bool(c.get("pinHash")), "locked": bool(c.get("lockUntil")) and str(c.get("lockUntil")) > A._now()}


@router.get("/ops/loyalty")
def loyalty_overview(user: dict = Depends(A.need("crm.view"))):
    cfg = loyalty_config()
    members = [_public_member(c) for c in A._records("customers") if c.get("pinHash") or c.get("points")]
    referrals = defaultdict(int)
    for m in members:
        if m.get("referredBy"):
            referrals[m["referredBy"]] += 1
    for m in members:
        m["referrals"] = referrals.get(m.get("referralCode", ""), 0)
        m["walletValue"] = int(m.get("points") or 0) * cfg["filsPerPoint"]
    members.sort(key=lambda m: -int(m.get("points") or 0))
    moves = sorted(A._records("loyalty_moves"), key=lambda r: r["id"], reverse=True)[:200]
    issued = sum(int(m.get("points") or 0) for m in moves if int(m.get("points") or 0) > 0)
    redeemed = -sum(int(m.get("points") or 0) for m in moves if m.get("kind") == "redeem")
    return {"config": cfg, "members": members, "moves": moves,
            "stats": {"members": len([m for m in members if m["member"]]), "outstandingPoints": sum(int(m.get("points") or 0) for m in members),
                      "outstandingValue": sum(m["walletValue"] for m in members), "issued": issued, "redeemed": redeemed,
                      "referred": sum(referrals.values())}}


class AdjustPointsIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    points: int = Field(ge=-1_000_000, le=1_000_000)
    note: str = Field(min_length=2, max_length=200)


@router.post("/ops/loyalty/adjust")
def adjust_points(body: AdjustPointsIn, user: dict = Depends(A.need("crm.edit"))):
    try:
        from agent import rewards
    except ModuleNotFoundError:
        import rewards
    phone = rewards.norm_phone(body.phone)
    if body.points == 0:
        raise HTTPException(400, "Enter a number of points other than zero.")
    balance = rewards.add_points(phone, body.points, "adjust", note=body.note, by=user["user"])
    A.audit(user, "points_adjusted", phone[-4:], f"{body.points:+d} {body.note}")
    return {"phone": phone, "points": balance}


class RedeemIn(BaseModel):
    phone: str = Field(min_length=6, max_length=20)
    points: int = Field(gt=0, le=1_000_000)
    orderId: str = Field(default="", max_length=40)


@router.post("/ops/loyalty/redeem")
def redeem_points(body: RedeemIn, user: dict = Depends(A.need("orders.status"))):
    """At the window: the customer pays part of the order with points. Returns the discount to apply."""
    try:
        from agent import rewards
    except ModuleNotFoundError:
        import rewards
    cfg = loyalty_config()
    if body.points < cfg["minRedeem"]:
        raise HTTPException(400, f"At least {cfg['minRedeem']} points can be redeemed at a time.")
    phone = rewards.norm_phone(body.phone)
    balance = rewards.add_points(phone, -body.points, "redeem", order_id=body.orderId, by=user["user"])
    discount = body.points * cfg["filsPerPoint"]
    A.audit(user, "points_redeemed", phone[-4:], f"{body.points} points = {discount} fils {body.orderId}")
    return {"phone": phone, "points": balance, "discount": discount}
