"""VoiceBite AI insights: production forecasts with a confidence score, gap alerts and leakage analysis.

Routes on the console API (/admin/api/insights/...):

    GET  /insights/forecast?day=      what to make of each item, with a confidence %, the last quantity logged
                                      (auto-replay) and live gap alerts for the day
    POST /insights/production/bulk    log several batches at once (the pre-filled daily log)
    GET  /insights/overview?days=7    the AI insights dashboard: forecast vs made vs sold, overproduction that
                                      could have been avoided, solved vs unsolved orders, waste, leakage points

How the forecast works (deliberately simple, so a manager can follow it):
    demand = average sold per day over the last 7 days
           x this weekday's pattern over the last 4 weeks (e.g. Fridays sell 1.5x an average day)
           x the trend (last 7 days vs the 7 before, half applied, capped at +/-15%)
    suggestion = demand + a small buffer (5%), rounded up
    confidence = how close the model would have been on each of the last 14 days, had it been used:
                 100% - average |forecast demand - sold| / the larger of the two. "Expected 200, sold 170" is an 85% day.
                 (The 5% buffer on top of the demand is deliberate and not counted as error.)
Days with no sales data are skipped. Fewer than 7 days of history marks the item as "learning".
"""

import logging
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

try:
    from agent import admin_api as A
    from agent import ops
    from agent.shop_config import get_settings
except ModuleNotFoundError:
    import admin_api as A
    import ops
    from shop_config import get_settings

logger = logging.getLogger(__name__)
router = A.router

BUFFER, TREND_CAP = 0.05, 0.15
BACKTEST_DAYS, HISTORY_DAYS = 14, 42
OVER_MAKE = 1.15        # made more than 15% over the suggestion: overproduction alert
SLOW_PACE = 0.6         # sold under 60% of what the forecast expects by now: slow-sales alert


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _history(data: dict) -> dict:
    """Units sold per item per day (voice orders + POS), from data already loaded by ops._load."""
    sold = defaultdict(lambda: defaultdict(float))
    for o in data["orders"]:
        day = o.get("_day") or ops.local_day(o.get("createdAt", ""))
        o["_day"] = day
        for it in o.get("items") or []:
            item_id = "custom-burger" if str(it.get("itemId", "")).startswith("custom-burger") else str(it.get("itemId", ""))
            sold[item_id][day] += _num(it.get("quantity"), 1)
    for x in data["pos"]:
        for line in x.get("lines") or []:
            sold[line["itemId"]][x.get("day")] += _num(line.get("qty"))
    made = defaultdict(lambda: defaultdict(float))
    for p in data["production"]:
        made[p["itemId"]][p.get("day")] += _num(p.get("qty"))
    return {"sold": sold, "made": made}


def _days_before(target: date, n: int) -> List[str]:
    return [(target - timedelta(days=k)).isoformat() for k in range(1, n + 1)]


def predict(sold_by_day: dict, target: date, first_day: Optional[str]) -> Optional[dict]:
    """Demand for one item on `target`, using only days before it. None when there is nothing to go on.

    level   = average sold per day over the last 7 days
    weekday = how this weekday compares with an average day over the last 4 weeks (Fridays might be 1.5x)
    trend   = last 7 days vs the 7 before, half applied and capped, so one odd week does not swing it
    demand  = level x weekday x trend
    """
    def days(start: int, end: int) -> List[str]:
        return [d for d in [(target - timedelta(days=k)).isoformat() for k in range(start, end + 1)] if not first_day or d >= first_day]
    recent = days(1, 7)
    if not recent:
        return None
    level = sum(sold_by_day.get(d, 0) for d in recent) / len(recent)
    window = days(1, 28)
    same = [d for d in window if date.fromisoformat(d).weekday() == target.weekday()]
    overall = sum(sold_by_day.get(d, 0) for d in window) / len(window)
    weekday = 1.0
    if same and overall > 0:
        raw = (sum(sold_by_day.get(d, 0) for d in same) / len(same)) / overall
        weekday = 1 + (raw - 1) * min(1.0, len(same) / 3)        # trust the pattern once a few weeks are in
        # the 7-day level already contains one of this weekday; take its share out before applying the factor
        level = level * 7 / (6 + weekday) if len(recent) == 7 else level
    prev = days(8, 14)
    trend = 1.0
    if prev:
        prev_avg = sum(sold_by_day.get(d, 0) for d in prev) / len(prev)
        if prev_avg > 0:
            trend = max(1 - TREND_CAP, min(1 + TREND_CAP, (sum(sold_by_day.get(d, 0) for d in recent) / len(recent)) / prev_avg))
    demand = level * weekday * (1 + (trend - 1) / 2)
    if demand <= 0:
        return {"demand": 0.0, "suggested": 0, "trend": trend, "weekday": weekday}
    return {"demand": demand, "suggested": int(math.ceil(demand * (1 + BUFFER))), "trend": trend, "weekday": round(weekday, 2)}


def confidence(sold_by_day: dict, today: date, first_day: Optional[str]) -> dict:
    """Backtest: what the model would have suggested on each recent day vs what was really sold."""
    scores, days = [], []
    for k in range(1, BACKTEST_DAYS + 1):
        d = today - timedelta(days=k)
        if first_day and d.isoformat() < first_day:
            break
        p = predict(sold_by_day, d, first_day)
        actual = sold_by_day.get(d.isoformat(), 0)
        if not p or (p["suggested"] == 0 and actual == 0):
            continue
        accuracy = max(0.0, 1 - abs(p["demand"] - actual) / max(p["demand"], actual, 1))   # the buffer is deliberate, not an error
        scores.append(accuracy)
        days.append({"day": d.isoformat(), "suggested": p["suggested"], "sold": actual, "accuracy": round(100 * accuracy)})
    pct = round(100 * sum(scores) / len(scores)) if scores else None
    return {"pct": pct, "days": list(reversed(days)), "samples": len(scores)}


def _tier(pct: Optional[int], samples: int) -> str:
    if pct is None or samples < 7:
        return "learning"
    return "high" if pct >= 95 else "good" if pct >= 85 else "low"


def _open_fraction() -> float:
    """How much of today's trading day has passed, from the opening hours in settings (10:00-23:00 if unset)."""
    s = get_settings()
    try:
        oh, om = map(int, str(s.get("openTime") or "10:00").split(":"))
        ch, cm = map(int, str(s.get("closeTime") or "23:00").split(":"))
    except ValueError:
        oh, om, ch, cm = 10, 0, 23, 0
    now = datetime.now(timezone.utc) + ops._offset()
    start, end, cur = oh * 60 + om, ch * 60 + cm, now.hour * 60 + now.minute
    if end <= start:
        end += 24 * 60
        if cur < start:
            cur += 24 * 60
    return max(0.0, min(1.0, (cur - start) / max(1, end - start)))


def forecast_for(day: str, data: dict) -> dict:
    hist = _history(data)
    target, today = date.fromisoformat(day), date.fromisoformat(ops.local_day())
    menu, costs = data["items"], data["costs"]
    all_days = sorted({d for s in hist["sold"].values() for d in s} | {d for m in hist["made"].values() for d in m})
    first_day = all_days[0] if all_days else None
    # items worth forecasting: anything the kitchen batches, plus anything sold in the last 6 weeks
    since = (target - timedelta(days=HISTORY_DAYS)).isoformat()
    candidates = {i for i, m in hist["made"].items() if any(d >= since for d in m)} | \
                 {i for i, s in hist["sold"].items() if any(d >= since and q > 0 for d, q in s.items())}
    last_logged = {}
    for p in sorted(data["production"], key=lambda p: (p.get("day", ""), p.get("at", ""))):
        if p.get("day", "") < day or p.get("day") == day:
            last_logged[p["itemId"]] = {"qty": _num(p.get("qty")), "day": p.get("day")}
    fraction = _open_fraction() if target == today else (1.0 if target < today else 0.0)
    rows, alerts = [], []
    for item_id in candidates:
        if item_id not in menu:
            continue
        sold = hist["sold"].get(item_id, {})
        p = predict(sold, target, first_day)
        conf = confidence(sold, min(target, today), first_day)
        made_today = hist["made"].get(item_id, {}).get(day, 0)
        sold_today = sold.get(day, 0)
        batch = item_id in hist["made"]
        row = {"itemId": item_id, "name": menu[item_id]["name"], "batch": batch, "suggested": p["suggested"] if p else None,
               "demand": round(p["demand"], 1) if p else None, "trend": round((p["trend"] - 1) * 100) if p else 0,
               "confidence": conf["pct"], "tier": _tier(conf["pct"], conf["samples"]), "backtest": conf["days"],
               "last": last_logged.get(item_id), "made": made_today, "sold": sold_today, "portionCost": costs.get(item_id, 0),
               "price": menu[item_id]["price"]}
        # gap analysis: the AI suggestion against what was made and what is selling
        if p and batch and made_today and p["suggested"] and made_today > p["suggested"] * OVER_MAKE:
            extra = made_today - p["suggested"]
            alerts.append({"kind": "overproduction", "itemId": item_id, "name": row["name"], "severity": "warn",
                           "text": f"{row['name']}: {made_today:g} made, the forecast was {p['suggested']}. About {extra:g} may go unsold.",
                           "value": round(extra * row["portionCost"])})
        if p and p["suggested"] and fraction >= 0.35 and target == today:
            expected = p["demand"] * fraction
            if expected >= 3 and sold_today < expected * SLOW_PACE:
                alerts.append({"kind": "slow", "itemId": item_id, "name": row["name"], "severity": "info",
                               "text": f"{row['name']} is selling slower than forecast: {sold_today:g} sold, about {expected:.0f} expected by now.",
                               "value": 0})
            elif made_today and sold_today >= made_today * 0.9 and fraction < 0.85:
                alerts.append({"kind": "sellout", "itemId": item_id, "name": row["name"], "severity": "bad",
                               "text": f"{row['name']} may sell out: {sold_today:g} of {made_today:g} sold with {round(100 * (1 - fraction))}% of the day left.",
                               "value": 0})
        if target < today and p and p["suggested"] and made_today:
            gap = abs(sold_today - p["suggested"]) / max(p["suggested"], 1)
            if gap > 0.25:
                alerts.append({"kind": "deviation", "itemId": item_id, "name": row["name"], "severity": "info",
                               "text": f"{row['name']}: forecast {p['suggested']}, sold {sold_today:g}. The model will take this into account.", "value": 0})
        rows.append(row)
    rows.sort(key=lambda r: (not r["batch"], -(r["suggested"] or 0)))
    batch_rows = [r for r in rows if r["batch"] and r["confidence"] is not None]
    overall = round(sum(r["confidence"] for r in batch_rows) / len(batch_rows)) if batch_rows else None
    return {"day": day, "items": rows, "alerts": alerts, "confidence": overall, "dayProgress": round(100 * fraction),
            "model": {"buffer": BUFFER, "backtestDays": BACKTEST_DAYS, "trendCap": TREND_CAP}}


@router.get("/insights/forecast")
def forecast(day: str = "", location: Optional[str] = None, user: dict = Depends(A.need("inventory.view"))):
    return forecast_for(ops._day(day), ops._load(A._scope(user, location)))


class BulkLine(BaseModel):
    itemId: str = Field(min_length=1, max_length=64)
    qty: float = Field(gt=0, le=100_000)


class BulkIn(BaseModel):
    day: str = ""
    lines: List[BulkLine] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=200)
    branchId: str = A.DEFAULT_LOCATION


@router.post("/insights/production/bulk")
def log_bulk(body: BulkIn, user: dict = Depends(A.need("waste.log"))):
    saved = [ops.log_production(ops.ProductionIn(itemId=l.itemId, qty=l.qty, day=body.day, note=body.note or "Daily log", branchId=body.branchId), user=user)
             for l in body.lines]
    return {"saved": len(saved)}


def _leakage(data: dict, days: List[str]) -> list:
    """Per stock item over the period: what was bought, what recipes say sales used, logged waste,
    and losses only stock counts and adjustments reveal (the leakage points)."""
    ings = data["ingredients"]
    period = set(days)
    out = defaultdict(lambda: {"bought": 0.0, "used": 0.0, "wasted": 0.0, "unexplained": 0.0})
    for m in A._records("stock_moves"):
        if ops.local_day(m.get("at", "")) not in period or not A._in_scope(m, data["scope"]):
            continue
        q, kind, row = _num(m.get("qty")), m.get("type"), out[m.get("ingredientId")]
        if kind == "purchase" and q > 0 and m.get("ref") != "sample":
            row["bought"] += q
        elif kind == "consumption":
            row["used"] += -q
        elif kind == "waste":
            row["wasted"] += -q
        elif kind in ("count", "adjustment") and q < 0:
            row["unexplained"] += -q
    rows = []
    for iid, r in out.items():
        ing = ings.get(iid)
        if not ing:
            continue
        cost = _num(ing.get("unitCost"))
        lost = (r["wasted"] + r["unexplained"]) * cost
        rows.append({"ingredientId": iid, "name": ing.get("name", iid), "unit": ing.get("unit", ""), **{k: round(v, 3) for k, v in r.items()},
                     "spend": round(r["bought"] * cost), "lostValue": round(lost), "unexplainedValue": round(r["unexplained"] * cost)})
    rows.sort(key=lambda r: -r["lostValue"])
    return rows


@router.get("/insights/overview")
def overview(days: int = 7, location: Optional[str] = None, user: dict = Depends(A.need("inventory.view"))):
    days = max(3, min(days, 28))
    scope = A._scope(user, location)
    data = ops._load(scope)
    today = date.fromisoformat(ops.local_day())
    period = [(today - timedelta(days=k)).isoformat() for k in range(days - 1, -1, -1)]
    hist = _history(data)
    all_days = sorted({d for s in hist["sold"].values() for d in s} | {d for m in hist["made"].values() for d in m})
    first_day = all_days[0] if all_days else None
    costs, menu = data["costs"], data["items"]

    # forecast vs made vs sold, per day, for batch items
    per_day, avoidable, accuracy = [], 0, []
    for d in period:
        target = date.fromisoformat(d)
        sug = made = sold = 0.0
        for item_id, m in hist["made"].items():
            if item_id not in menu or d not in m:
                continue
            p = predict(hist["sold"].get(item_id, {}), target, first_day)
            s_item = hist["sold"].get(item_id, {}).get(d, 0)
            sug += p["suggested"] if p else m[d]
            made += m[d]
            sold += s_item
            if p and d < today.isoformat():
                over = max(0.0, m[d] - max(p["suggested"], s_item))
                avoidable += over * costs.get(item_id, 0)
                if p["demand"] or s_item:
                    accuracy.append(max(0.0, 1 - abs(p["demand"] - s_item) / max(p["demand"], s_item, 1)))
        per_day.append({"day": d, "suggested": round(sug), "made": round(made), "sold": round(sold)})

    # money lost per day from the existing daily report
    reports = {d: ops._compute(d, data) for d in period}
    for row in per_day:
        t = reports[row["day"]]["totals"]
        row["wasteCost"] = round(t.get("wasteCost", 0) + t.get("ingredientWasteCost", 0))
        row["missingCost"] = round(t.get("missingCost", 0) + t.get("stockGapCost", 0))

    # solved vs unsolved orders (today) and waste in one panel
    orders_today = [o for o in A._scan_all(ops.orders_table) if A._in_scope(o, scope) and ops.local_day(o.get("createdAt", "")) == today.isoformat()]
    solved = [o for o in orders_today if o.get("status") == "completed"]
    cancelled = [o for o in orders_today if o.get("status") == "cancelled"]
    open_ = [o for o in orders_today if o.get("status") not in ("completed", "cancelled")]
    sla = int(_num(get_settings().get("prepSlaMinutes"), 8))
    now = datetime.now(timezone.utc)
    late = []
    for o in open_:
        try:
            age = (now - datetime.fromisoformat(str(o.get("createdAt")).replace("Z", "+00:00"))).total_seconds() / 60
        except ValueError:
            age = 0
        if age > sla:
            late.append({"orderId": o.get("orderId"), "minutes": round(age), "status": o.get("status")})
    forecast_today = forecast_for(today.isoformat(), data)
    waste_by_reason = defaultdict(float)
    for w in data["waste"]:
        if (w.get("day") or ops.local_day(w.get("at", ""))) in set(period):
            waste_by_reason[w.get("reason", "other")] += _num(w.get("cost"))
    leak = _leakage(data, period)

    overall = round(100 * sum(accuracy) / len(accuracy)) if accuracy else forecast_today["confidence"]
    totals = {k: sum(r[k] for r in per_day) for k in ("suggested", "made", "sold", "wasteCost", "missingCost")}
    return {"days": days, "perDay": per_day, "totals": totals, "confidence": overall, "tier": _tier(overall, len(accuracy) or 7),
            "avoidableCost": round(avoidable), "forecastToday": forecast_today,
            "orders": {"solved": len(solved), "open": len(open_), "cancelled": len(cancelled), "late": late,
                       "revenue": sum(int(_num(o.get("total"))) for o in solved)},
            "wasteByReason": dict(waste_by_reason), "leakage": leak[:8],
            "leakTotal": sum(r["lostValue"] for r in leak), "spendTotal": sum(r["spend"] for r in leak)}
