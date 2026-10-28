# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Order management tools for the VoiceBite voice ordering agent."""

import json
import logging
import os
import re
import secrets
from decimal import Decimal

import boto3
from strands import tool

try:
    from agent.order_state import OrderState
    from agent.ui_state_manager import set_ui_state, get_ui_state
    from agent.call_context import current as _call
except ModuleNotFoundError:
    from order_state import OrderState
    from ui_state_manager import set_ui_state, get_ui_state
    from call_context import current as _call

CURRENCY = "AED"  # shown and spoken as UAE dirhams
_SAUCES = ("ketchup", "mustard", "mayo", "bbq sauce", "chipotle mayo", "special sauce")


def _load_shop_config():
    """Use the admin panel's settings module if it has been added to the project."""
    import importlib
    for module in ("agent.shop_config", "shop_config"):
        try:
            return importlib.import_module(module)
        except ModuleNotFoundError:
            continue
    return None


_shop = _load_shop_config()
if _shop:
    get_burger_config, current_location = _shop.get_burger_config, _shop.current_location
    note_added, note_order = _shop.note_added, _shop.note_order
else:
    # No admin panel installed: burger prices come from the constants further down this file.
    def get_burger_config() -> dict:
        extras = {k: v for k, v in _TOPPING_PRICES.items() if k not in ("beef patty", "chicken patty")}
        return {
            "basePrice": _CUSTOM_BURGER_BASE_PRICE,
            "toppings": {k: v for k, v in extras.items() if k not in _SAUCES},
            "sauces": {k: v for k, v in extras.items() if k in _SAUCES},
        }

    def current_location() -> str:
        return "main"

    def note_added(item_id: str) -> None:
        pass

    def note_order(order_id: str, total: int) -> None:
        pass

logger = logging.getLogger(__name__)


# VOICE_PRICE_MODE: "checkout" (default) keeps prices out of the conversation until the order summary, so choosing is
# quick; the prices stay visible on the customer's screen. "always" also says the item price and running total each time.
PRICE_MODE = os.getenv("VOICE_PRICE_MODE", "checkout").strip().lower()
_MID_ORDER_PRICES = ("itemPriceText", "total", "totalText", "price", "priceText")


def _who_first(result: dict) -> dict:
    """Until we know who is ordering, every tool result reminds the attendant to settle it (the drive-through flow)."""
    call = _call()
    if _identity_open() and not getattr(call, "who_reminded", False) and not getattr(call, "who_answer", ""):   # remind once, not on every item
        call.who_reminded = True
        result["first"] = (f'They have not said who is ordering yet. After confirming the item, ask once: "{_WHO_Q}" '
                           "Do not repeat this question again until they answer; carry on with the order meanwhile.")
    call = _call()
    if call.step in ("plate", "plate_ok", "pay", "review"):   # the order changed during checkout: checkout starts again
        call.step, call.plate, call.pay = "order", "", ""
        _flow_screen(2)
        result["checkout"] = "The order changed, so checkout starts again: when they are done, call checkout."
    return result


def _while_choosing(result: dict) -> dict:
    """Results of add/remove while the customer is still choosing: no prices to read out in checkout mode."""
    result = _who_first(result)
    if PRICE_MODE == "always":
        return result
    quiet = {k: v for k, v in result.items() if k not in _MID_ORDER_PRICES}
    quiet["say"] = "Confirm in a few words without any price, e.g. 'Done, one Cheeseburger. Anything else?'. The total is said only at checkout."
    return quiet


def _spoken(amount: int) -> str:
    """The amount exactly as the attendant should say it, so speech and screen always match."""
    return f"{int(amount) / 100:.2f} dirhams"


def _show_order_on_screen() -> dict:
    """Push the real order and its total to the customer's screen; returns the summary."""
    summary = get_order_state().get_summary()
    try:
        current = get_ui_state()
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        set_ui_state(current)
    except Exception as e:
        logger.warning("could not update the screen: %s", e)
    return summary


def _sanitize_result(result: dict) -> dict:
    """Ensure tool result is JSON-serializable with only basic Python types."""
    def _convert(obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj == int(obj) else float(obj)
        if isinstance(obj, dict):
            return {str(k): _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(i) for i in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        return str(obj)

    sanitized = _convert(result)
    try:
        json.dumps(sanitized)
    except (TypeError, ValueError) as e:
        logger.error("Tool result not JSON-serializable: %s | result: %s", e, sanitized)
        return {"status": "ok"}
    return sanitized

_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
_dynamodb = boto3.resource("dynamodb", region_name=_REGION)
_menu_table = _dynamodb.Table(os.environ.get("MENU_TABLE_NAME", "DriveThruMenu"))
_orders_table = _dynamodb.Table(os.environ.get("ORDERS_TABLE_NAME", "DriveThruOrders"))

# Who is on this call, when the app says (a signed-in Rewards member) or they join by voice.
# main.py sets it at the start of each call; after_order (also set by main.py) saves their car and payment choice.
PAYMENT_METHODS = {"cash": "cash", "card": "card", "link": "link", "payment link": "link", "online": "link", "online link": "link"}
after_order = None
rewards_on = False   # main.py turns this on when VoiceBite Rewards is set up

# What the customer has said or tapped during this order. The plate passed to place_order must be one the
# customer actually gave (spoken or tapped), so the attendant can never fill it in from memory or an example.
_NUM_WORDS = {"zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3", "four": "4", "for": "4", "five": "5",
              "six": "6", "seven": "7", "eight": "8", "ate": "8", "nine": "9"}


def customer() -> dict:
    """The Rewards member (or declined flag) for the call in progress. Empty for a guest."""
    return _call().customer


def set_call_customer(info: dict) -> None:
    _call().customer = dict(info or {})


def reset_heard() -> None:
    call = _call()
    call.heard, call.heard_any = [], False


def note_heard(text: str) -> None:
    """main.py passes every line the customer speaks or taps."""
    t = str(text or "").strip()
    if t:
        call = _call()
        call.heard.append(t[:300])
        call.heard_any = True
        del call.heard[:-40]


def _digits_spoken(text: str) -> str:
    """'D one two double three' -> 'D 1 2 33': spoken digits as numerals, Arabic-Indic digits too."""
    t = str(text).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")).lower()
    t = re.sub(r"\b(double|triple)\s+(\w+)", lambda m: (_NUM_WORDS.get(m.group(2), m.group(2)) + " ") * (2 if m.group(1) == "double" else 3), t)
    return " ".join(_NUM_WORDS.get(w, w) for w in re.findall(r"[a-z]+|\d+|[^\sa-z\d]+", t))


def _plate_from_customer(vehicle: str, lines=None) -> bool:
    """True when the customer said or tapped this plate's number (in `lines`, default the whole call). Never a remembered plate."""
    call = _call()
    if not call.heard_any:
        return True   # no transcript reaches us (text-only test calls): nothing to check against
    said = re.sub(r"\D", "", "".join(_digits_spoken(h) for h in (call.heard if lines is None else lines)))
    digits = re.sub(r"\D", "", vehicle)
    return bool(digits) and digits in said


# ---------- the drive-through flow, enforced here rather than left to the voice model ----------
# 1 who is ordering -> 2 the order -> 3 vehicle plate (+ confirm) -> 4 payment -> 5 review and place.
# Each step tool only moves on when the customer has actually answered the question it asked (spoken or tapped),
# and tells the attendant the exact next sentence. The attendant cannot skip a step or answer for the customer.

_WHO_Q = "Are you a VoiceBite Rewards member, or is this your first order with us?"
_WHO_OPTIONS = ["I'm a member", "First order"]
_DETAILS_Q = "Welcome! Could I have your name and mobile number? We'll use it to reach you when you arrive."
_MEMBER_Q = "Great! What's your mobile number and 4-digit PIN? You can type them on your screen."
_NUMBER_Q = "Could you say your mobile number again, one digit at a time? You can also type it on your screen."


def _said_something() -> bool:
    """The customer answered the current question at all. Speech-to-text often splits or drops digits, so the exact
    number is never checked against it: the customer confirms what we read back instead."""
    call = _call()
    return (not call.heard_any) or bool(_since())


def _grouped(digits: str) -> str:
    """'0508989797' -> '0 5 0, 8 9 8, 9 7 9 7': how a number is read back."""
    d = re.sub(r"\D", "", digits)
    parts = [d[:3], d[3:6], d[6:]] if len(d) > 6 else [d]
    return ", ".join(" ".join(p) for p in parts if p)
_GUEST = re.compile(r"\b(guest|no thanks|no thank you|not now|skip|without|don'?t want|continue)\b|لا شكر|ضيف|بدون|വേണ്ട|ഗസ്റ്റ്", re.I)
_YES = re.compile(r"\b(yes|yeah|yep|yup|correct|that's right|that is right|right|sure|ok|okay|go ahead|place( it| the order| order)?|confirm|perfect|exactly)\b"
                  r"|نعم|أيوه|ايوه|صحيح|تمام|أكد|اطلب|അതെ|ശരി|ഓക്കെ", re.I)
_NO = re.compile(r"\b(no|nope|wrong|not right|change|incorrect)\b|لا|خطأ|غير|അല്ല|മാറ്റ", re.I)
_PAY_WORDS = {"cash": re.compile(r"\bcash\b|كاش|نقد|ക്യാഷ്|പണം", re.I),
              "card": re.compile(r"\bcard\b|credit|debit|visa|master|بطاقة|كارت|കാർഡ്", re.I),
              "link": re.compile(r"\blink\b|online|apple ?pay|رابط|اونلاين|ലിങ്ക്", re.I)}
PAY_LABEL = {"cash": "Cash", "card": "Card", "link": "Payment link"}
FLOW_STEPS = ["Your details", "Your order", "Car", "Payment", "Confirm"]


def _identity_open() -> bool:
    """Every order needs the customer's mobile number: the restaurant calls it on arrival, and it is their CRM record."""
    return rewards_on and not customer().get("phone")


def _since() -> list:
    """What the customer has said or tapped since the current question was asked."""
    call = _call()
    return call.heard[call.mark:]


def _answered(pattern) -> bool:
    call = _call()
    return (not call.heard_any) or any(pattern.search(h) for h in _since())


def _flow_screen(step_no: int, choices=None) -> None:
    current = get_ui_state()
    current.update(flowStep=step_no, flowSteps=FLOW_STEPS, choices=choices)
    set_ui_state(current)


def _ask(step: str, step_no: int, question: str, options=None, typing: str = "") -> dict:
    """Move to `step`, put the question (tap answers, or a box to type into) on screen, and tell the attendant to ask it and wait."""
    call = _call()
    call.step, call.mark = step, len(call.heard)
    call.who_open = question == _WHO_Q
    box = {"question": question, "options": options or []}
    if typing:
        box["input"] = typing   # "tel" or "text": the customer can type the answer instead of saying it
    _flow_screen(step_no, box if (options or typing) else None)
    return {"next": f'Say exactly: "{question}" Then stop and wait for the customer to answer. Do not call another checkout tool until they do.'}


def flow_begin() -> None:
    """Start of a call (main.py): members go straight to ordering, everyone else is asked who is ordering."""
    call = _call()
    call.plate = call.pay = ""
    if _identity_open():
        _ask("identify", 1, _WHO_Q, _WHO_OPTIONS)
    else:
        call.step = "order"
        _flow_screen(2)


def greeting_question() -> str:
    """Added to the attendant's first sentence when the customer is not identified yet."""
    return _WHO_Q if _identity_open() else ""


def identity_done(name: str = "") -> dict:
    """Called once the customer has signed in, joined or chosen to continue as a guest."""
    call = _call()
    call.step, call.who_open = "order", False
    call.mark = len(call.heard)
    _flow_screen(2)
    hello = f"Thanks, {name}. " if name else "Thanks. "
    if get_order_state().is_empty():
        return {"next": f'Say: "{hello}What would you like to order today?"'}
    return {"next": f'Say: "{hello}Anything else, or is that everything?"'}


def _spell(plate: str) -> str:
    return " ".join(plate.replace(" ", ""))


@tool
def sign_in_rewards(mobile_number: str, pin: str) -> dict:
    """Sign in an existing VoiceBite Rewards member by voice, so this order earns their points and fruit.

    Args:
        mobile_number: Their mobile number, digits as spoken, e.g. "0501234567".
        pin: Their 4-digit PIN. Never say it back out loud.
    """
    if not rewards_on:
        return {"error": "Rewards are not available. Carry on with the order."}
    if customer().get("phone"):
        return {"status": "already signed in", "name": customer().get("name", "")}
    from rewards import voice_login   # loaded only when Rewards is on
    result = voice_login(mobile_number, pin, short=_call().kiosk)
    if result.get("error"):
        return {"error": result["error"] + " Ask for the number and PIN again, or offer to join or continue as a guest. Never repeat the PIN."}
    set_call_customer({k: result.get(k, "") for k in ("phone", "name", "lastVehicle", "lastPayment", "member")})
    current = get_ui_state(); current.update(memberToken=result["token"], customerName=result.get("name", "")); set_ui_state(current)
    return {"status": "signed in", **identity_done(result.get("name", ""))}


@tool
def quick_details(name: str, mobile_number: str) -> dict:
    """A first-time customer said (or typed) their name and mobile number. Reads the number back for them to confirm.

    Args:
        name: Their first name, as they said it.
        mobile_number: Their mobile number, all the digits they gave, e.g. "0501234567".
    """
    if not rewards_on:
        return {"error": "Not available. Carry on with the order."}
    if customer().get("phone"):
        return {"status": "already known", "name": customer().get("name", "")}
    if not _said_something():
        return {"error": "Wait for the customer to say their name and mobile number."}
    digits = re.sub(r"\D", "", _digits_spoken(mobile_number))
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:60]
    if not name:
        return {"error": "Ask for their first name too.", **_ask("identify", 1, "And your first name, please?", None, "text")}
    if not 7 <= len(digits) <= 15:
        return {"status": "number unclear", **_ask("identify", 1, _NUMBER_Q, None, "tel")}
    call = _call()
    call.pending = {"name": name, "phone": digits}
    return {"status": "read back", **_ask("identify_ok", 1, f"Thanks, {name}. I have {_grouped(digits)}. Is that right?", [digits, "Change number"], "tel")}


@tool
def confirm_details(is_correct: bool) -> dict:
    """The customer answered whether the mobile number you read back is right.

    Args:
        is_correct: true if they said yes / tapped the number, false if it is wrong.
    """
    call = _call()
    pending = getattr(call, "pending", None)
    if call.step != "identify_ok" or not pending:
        return {"error": "No number to confirm. Ask for their name and mobile number first."}
    tapped = any(re.sub(r"\D", "", h) == pending["phone"] for h in _since())
    said_no = call.heard_any and not tapped and any(_NO.search(h) for h in _since())
    if not is_correct or said_no:
        call.pending = {"name": pending["name"], "phone": ""}
        return {"status": "change", **_ask("identify", 1, _NUMBER_Q, None, "tel")}
    if not (tapped or _answered(_YES)):
        return {"error": "The customer has not confirmed the number yet. Wait for their answer."}
    from rewards import voice_quick   # loaded only when Rewards is on
    result = voice_quick(pending["name"], pending["phone"])
    if result.get("error"):
        if "PIN" in result["error"]:
            return {"error": "This number already has a Rewards account.", **_ask("identify", 1, "That number has a VoiceBite Rewards account. What's your 4-digit PIN?", None, "tel")}
        return {"error": result["error"], **_ask("identify", 1, _NUMBER_Q, None, "tel")}
    call.pending = None
    set_call_customer({k: result.get(k, "") for k in ("phone", "name", "lastVehicle", "lastPayment", "member")})
    current = get_ui_state(); current.update(customerToken=result["token"], customerName=result.get("name", ""), customerPhone=result.get("phone", "")); set_ui_state(current)
    return {"status": "saved", **identity_done(result.get("name", ""))}


@tool
def skip_rewards() -> dict:
    """The customer says it is their FIRST ORDER, that they are new, not a member, or do not want to sign in.

    Call it straight away when they answer "member or first order?" with first order, in any language
    ("first time", "أول مرة", "ആദ്യമായി"...). It asks for their name and mobile number. Never ask "member or first order?" again after this.
    """
    _call().who_answer = "first"
    return {"status": "first order", **_ask("identify", 1, _DETAILS_Q, None, "tel")}


@tool
def i_am_member() -> dict:
    """The customer says they ARE a VoiceBite Rewards member (in any language). Asks for their mobile number and PIN.

    Then call sign_in_rewards with what they say. Never ask "member or first order?" again after this.
    """
    _call().who_answer = "member"
    return {"status": "member", **_ask("identify", 1, _MEMBER_Q, None, "tel")}


# The answer to "member or first order?" in English, Arabic or Malayalam (spoken, typed or tapped).
_FIRST = re.compile(r"\b(first[\s-]*(time|order|visit)|new (customer|here|user)|not a member|no[t]? member|never ordered|i'?m new|am new)\b"
                    r"|أول\s*(مرة|طلب)|اول\s*(مرة|مره|طلب)|لست عضو|مش عضو|ما\s*عندي\s*حساب|جديد"
                    r"|ആദ്യ|പുതിയ|മെമ്പർ അല്ല|അംഗമല്ല|അംഗം അല്ല|മെമ്പറല്ല", re.I)
_MEMBER = re.compile(r"\b((i'?m|i am|yes,? i'?m) (a |already a )?(rewards )?member|already (a )?member|member already|sign me in|log ?in)\b"
                     r"|أنا عضو|انا عضو|عضو في|عندي حساب"
                     r"|മെമ്പർ ആണ്|മെമ്പറാണ്|അംഗമാണ്|ഞാൻ മെമ്പർ", re.I)


def who_answer_in(text: str) -> str:
    """"first" or "member" when `text` answers the open "member or first order?" question; "" otherwise."""
    call = _call()
    if not rewards_on or not getattr(call, "who_open", False) or not _identity_open():
        return ""
    t = str(text or "")
    if _FIRST.search(t):
        return "first"
    if _MEMBER.search(t):
        return "member"
    return ""


def settle_who(answer: str) -> str:
    """The customer answered "member or first order?". Moves the flow on (screen included) without waiting for the
    voice model, and returns a note for the attendant so it never asks the same question again."""
    call = _call()
    call.who_answer = answer
    if answer == "first":
        _ask("identify", 1, _DETAILS_Q, None, "tel")
        call.mark = max(0, call.mark - 1)   # the answer itself may already hold the name and number
        return ("(The customer has answered: this is their FIRST ORDER. Do NOT ask whether they are a member again. "
                "Now ask for their first name and mobile number, in the call's language.)")
    _ask("identify", 1, _MEMBER_Q, None, "tel")
    call.mark = max(0, call.mark - 1)
    return ("(The customer has answered: they ARE a VoiceBite Rewards member. Do NOT ask whether they are a member again. "
            "Now ask for their mobile number and 4-digit PIN, then call sign_in_rewards.)")


@tool
def checkout() -> dict:
    """The customer says that is everything / wants to place the order. Starts checkout: reads back the order and asks for the car."""
    call = _call()
    if get_order_state().is_empty():
        return {"error": "The order is empty. Ask what they would like."}
    if _identity_open():
        if getattr(call, "who_answer", "") == "first":
            return {"error": "We still need their name and mobile number.", **_ask("identify", 1, _DETAILS_Q, None, "tel")}
        if getattr(call, "who_answer", "") == "member":
            return {"error": "We still need their member sign-in.", **_ask("identify", 1, _MEMBER_Q, None, "tel")}
        return {"error": "Who is ordering is not settled yet.", **_ask("identify", 1, _WHO_Q, _WHO_OPTIONS)}
    summary = _show_order_on_screen()
    said = ", ".join(f"{i['quantity']} {i['name']}" for i in summary["items"])
    call.plate = call.pay = ""
    return {"status": "checkout", **_ask("plate", 3, f"That's {said}, {_spoken(summary['total'])}. What's your vehicle plate number?", None, "text")}


@tool
def set_vehicle(plate_number: str) -> dict:
    """Record the vehicle plate number the customer just said, then ask them to confirm it.

    Args:
        plate_number: The plate exactly as the customer said it, letters and digits, e.g. "D 12345".
    """
    call = _call()
    if call.step not in ("plate", "plate_ok"):
        return {"error": "Not at the car step. If they are done ordering, call checkout first."}
    vehicle = re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 ]", " ", str(plate_number or "")).upper()).strip()[:20]
    if not re.search(r"\d", vehicle):
        return {"error": "A plate needs its number.", **_ask("plate", 3, "Sorry, I didn't catch that. What's your vehicle plate number? You can also type it on your screen.", None, "text")}
    if not _said_something():
        return {"error": "Wait for the customer to say their plate number. Never guess or reuse a plate."}
    call.plate = vehicle
    return {"status": "heard", **_ask("plate_ok", 3, f"I have {_spell(vehicle)}. Is that right?", [vehicle, "Change plate"])}


@tool
def confirm_vehicle(is_correct: bool) -> dict:
    """The customer answered whether the plate you read back is right.

    Args:
        is_correct: true if they said yes / tapped the plate, false if they want to change it.
    """
    call = _call()
    if call.step != "plate_ok" or not call.plate:
        return {"error": "No plate to confirm. Ask for the plate number first."}
    tapped = any(h.replace(" ", "").upper() == call.plate.replace(" ", "") for h in _since())
    said_no = call.heard_any and not tapped and any(_NO.search(h) for h in _since())
    if is_correct and said_no:
        return {"error": "They said the plate is not right. Call confirm_vehicle with is_correct false."}
    if is_correct:
        if not (tapped or _answered(_YES)):
            return {"error": "The customer has not confirmed the plate yet. Wait for their answer."}
        last = customer().get("lastPayment", "")
        options = [PAY_LABEL[last]] + [PAY_LABEL[m] for m in PAY_LABEL if m != last] if last in PAY_LABEL else list(PAY_LABEL.values())
        q = f"How would you like to pay? {PAY_LABEL[last]} like last time, or something else?" if last in PAY_LABEL else "How would you like to pay: cash, card or a payment link?"
        return {"status": "plate confirmed", **_ask("pay", 4, q, options)}
    call.plate = ""
    return {"status": "change", **_ask("plate", 3, "Sorry about that. What's your vehicle plate number? You can also type it on your screen.", None, "text")}


@tool
def set_payment(method: str) -> dict:
    """Record how the customer said they will pay, then read back the whole order for a final yes.

    Args:
        method: "cash", "card" or "link", exactly as the customer chose.
    """
    call = _call()
    if call.step != "pay":
        return {"error": "Not at the payment step yet. Follow the steps: checkout, set_vehicle, confirm_vehicle, then payment."}
    m = PAYMENT_METHODS.get(str(method or "").strip().lower(), "")
    if not m:
        return {"error": "Ask: cash, card or a payment link?"}
    if call.heard_any and not any(_PAY_WORDS[m].search(h) or h.strip().lower() == PAY_LABEL[m].lower() for h in _since()):
        return {"error": f"The customer has not chosen {PAY_LABEL[m].lower()}. Wait for them to say or tap how they will pay. Never choose for them."}
    call.pay = m
    summary = _show_order_on_screen()
    said = ", ".join(f"{i['quantity']} {i['name']}" for i in summary["items"])
    return {"status": "payment chosen", **_ask("review", 5, f"So that's {said}, {_spoken(summary['total'])}, for car {_spell(call.plate)}, paying by {PAY_LABEL[m].lower()}. Shall I place the order?",
                                               ["Place order", "Change something"])}


def set_tables(menu_table, orders_table) -> None:
    global _menu_table, _orders_table
    _menu_table = menu_table
    _orders_table = orders_table


def set_order_state(state: OrderState) -> None:
    _call().order = state


def get_order_state() -> OrderState:
    """The unplaced order of the call in progress."""
    return _call().order


@tool
def add_to_order(item_id: str, category_id: str, quantity: int = 1, special_instructions: str = "") -> dict:
    """Adds a menu item to the current order and updates the customer's screen.

    Args:
        item_id: The menu item identifier.
        category_id: The category the item belongs to.
        quantity: Number of items to add (must be >= 1).
        special_instructions: Customer notes like "no pickles" or "extra sauce".
    """
    logger.info("add_to_order: %s %s qty=%s notes=%s", item_id, category_id, quantity, special_instructions)
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}
    response = _menu_table.get_item(Key={"PK": f"CATEGORY#{category_id}", "SK": f"ITEM#{item_id}"})
    menu_item = response.get("Item")
    if not menu_item:
        return {"error": f"Item '{item_id}' not found in category '{category_id}'."}
    if menu_item.get("available") is False:
        return {"error": f"'{menu_item.get('name', item_id)}' is sold out right now. Apologise and offer something else."}
    get_order_state().add_item(item_id, menu_item.get("name", ""), quantity, int(menu_item.get("price", 0)), special_instructions)
    note_added(item_id)
    summary = get_order_state().get_summary()

    # Auto-update the UI: refresh the order display (don't highlight — that opens the modal)
    try:
        current = get_ui_state()
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        set_ui_state(current)
    except Exception as e:
        logger.warning("add_to_order: failed to auto-update UI: %s", e)

    # Return minimal confirmation to keep tool result small for Nova Sonic
    return _sanitize_result(_while_choosing({
        "status": "added",
        "item": str(menu_item.get("name", "")),
        "quantity": quantity,
        "itemPriceText": _spoken(int(menu_item.get("price", 0))),
        "total": summary["total"],
        "totalText": _spoken(summary["total"]),
    }))


@tool
def remove_from_order(item_id: str, quantity: int = 1) -> dict:
    """Removes a menu item from the current order."""
    if not get_order_state().remove_item(item_id, quantity):
        return {"error": f"Item '{item_id}' is not in the current order."}
    summary = _show_order_on_screen()
    return _sanitize_result(_while_choosing({"status": "removed", "item": item_id, "total": summary["total"], "totalText": _spoken(summary["total"]), "itemCount": len(summary["items"])}))


@tool
def get_order_summary(tool_context=None) -> dict:
    """Returns the current order summary."""
    summary = _show_order_on_screen()
    items_brief = [f"{i['name']} x{i['quantity']}" for i in summary["items"]]
    said = ", ".join(f"{i['quantity']} {i['name']}" for i in summary["items"])
    return _sanitize_result({"items": items_brief, "total": summary["total"], "totalText": _spoken(summary["total"]),
                             "say": f"Read back exactly: \"{said}. Your total is {_spoken(summary['total'])}.\" Never work out a total yourself."})


@tool
def place_order(vehicle_number: str = "", payment_method: str = "", user_id: str = "guest") -> dict:
    """Places the order once the customer has said yes to the final read-back (after set_payment).

    The plate and payment are the ones the customer gave in the earlier steps; the arguments are ignored.

    Args:
        vehicle_number: The plate number exactly as the customer said or tapped it IN THIS CALL. Required for every
            order, even for a known customer: they may be in a different car today. Never guess or reuse a plate.
        payment_method: "cash", "card" or "link" (a payment link sent to their phone), as the customer chose.
        user_id: The customer identifier. Defaults to "guest".
    """
    if get_order_state().is_empty():
        return {"error": "Cannot place an empty order."}
    call = _call()
    if call.step != "review" or not call.plate or not call.pay:
        where = {"identify": "who is ordering", "order": "the order (call checkout when they are done)", "plate": "the vehicle plate",
                 "plate_ok": "confirming the plate", "pay": "the payment method"}.get(call.step, "checkout")
        return {"error": f"Not ready: still at {where}. Follow the steps and wait for the customer's answer at each one."}
    if call.heard_any and any(_NO.search(h) and not _YES.search(h) for h in _since()):
        return {"error": "They want to change something. Ask what they would like to change."}
    if not _answered(_YES):
        return {"error": "The customer has not said yes to placing the order. Wait for their answer."}
    vehicle, method = call.plate, call.pay   # what the customer gave and confirmed, never the model's arguments
    order_record = get_order_state().place_order(user_id)
    order_record["vehicleNumber"] = vehicle          # staff serve the order to this car
    order_record["paymentPreference"] = method       # shown to the window; the payment itself is taken there
    if customer().get("phone"):
        order_record["customerPhone"] = customer()["phone"]
        order_record["customerName"] = customer().get("name", "")
    order_record["locationId"] = current_location()  # which store took the order
    order_record["status"] = "received"              # first step on the kitchen display
    order_record["trackToken"] = secrets.token_urlsafe(16)  # lets this customer's phone, and nobody else, follow the order
    _orders_table.put_item(Item=order_record)
    note_order(order_record["orderId"], order_record["total"])
    if after_order:
        try:
            after_order(order_record)   # remembers this customer's car and payment method for next time
        except Exception as e:
            logger.warning("place_order: could not remember the customer's choices: %s", e)
    logger.info(
        "ORDER_PLACED: orderId=%s userId=%s total=%s itemCount=%s",
        order_record["orderId"],
        order_record["userId"],
        order_record["total"],
        len(order_record["items"]),
    )
    get_order_state().cancel()
    call.heard, call.mark, call.plate, call.pay, call.step = [], 0, "", "", "done"   # a second order asks for the car again

    # Update UI to show order confirmation page
    try:
        current = get_ui_state()
        current["orderConfirmed"] = True
        current["orderNumber"] = order_record["orderId"]
        current["orderTotal"] = order_record["total"]
        current["vehicleNumber"] = vehicle
        current["paymentPreference"] = method
        current["choices"] = None
        current["trackToken"] = order_record["trackToken"]
        current["shownItems"] = []
        current["burgerBuilder"] = None
        current["highlightedItem"] = None
        _call().burger = None
        current["highlightedCategory"] = None
        set_ui_state(current)
    except Exception as e:
        logger.warning("place_order: failed to update UI: %s", e)

    return _sanitize_result({"status": "confirmed", "orderId": order_record["orderId"], "vehicleNumber": vehicle, "paymentMethod": method,
                             "total": order_record["total"], "totalText": _spoken(order_record["total"]),
                             "say": f"Say exactly: \"Your order number is {order_record['orderId']}, for car {vehicle}. The total is {_spoken(order_record['total'])}. Please drive to the window.\""})


@tool
def cancel_order(tool_context=None) -> dict:
    """Clears all items from the current order."""
    logger.info("ORDER_CANCELLED: itemCount=%s", len(get_order_state().items))
    get_order_state().cancel()
    _show_order_on_screen()
    call = _call()
    if call.step not in ("identify",):
        call.step, call.plate, call.pay = "order", "", ""
        _flow_screen(2)
    return _sanitize_result({"status": "cancelled"})


# --- Custom Burger Builder ---
# Prices are edited in the admin panel and read from shop_config.get_burger_config().
# The constants below are only the starting defaults, kept for reference and tests.

_CUSTOM_BURGER_BASE_PRICE = 899  # AED 8.99 for patty + bun
_TOPPING_PRICES = {
    # Patty options (included in base)
    "beef patty": 0,
    "chicken patty": 0,
    # Cheese (+1.00)
    "american cheese": 100,
    "cheddar cheese": 100,
    "pepper jack cheese": 100,
    "swiss cheese": 100,
    # Premium toppings (+1.50)
    "bacon": 150,
    "avocado": 150,
    "fried egg": 150,
    # Free toppings
    "lettuce": 0,
    "tomato": 0,
    "onion": 0,
    "pickles": 0,
    "jalapeños": 0,
    "mushrooms": 0,
    # Sauces (free)
    "ketchup": 0,
    "mustard": 0,
    "mayo": 0,
    "bbq sauce": 0,
    "chipotle mayo": 0,
    "special sauce": 0,
}


@tool
def build_custom_burger(patty: str, toppings: list, sauces: list = None, quantity: int = 1, bun: str = "") -> dict:
    """Build a custom burger with chosen patty, toppings, and sauces. Adds it to the order.

    Args:
        patty: The patty type — "beef patty" or "chicken patty".
        toppings: List of toppings, using the names in the BUILD YOUR OWN BURGER section of your instructions.
        sauces: List of sauces, using the names in your instructions. Defaults to none.
        quantity: Number of custom burgers (default 1).
        bun: Optional bun: "brioche", "sesame", "potato" or "parmesan".

    Returns:
        Summary with the custom burger details, price breakdown, and updated order.
    """
    if sauces is None:
        sauces = []
    if quantity < 1:
        return {"error": "Quantity must be at least 1."}

    config = get_burger_config()
    base_price = int(config.get("basePrice", _CUSTOM_BURGER_BASE_PRICE))
    topping_prices = {str(k).lower(): int(v) for k, v in (config.get("toppings") or {}).items()}
    sauce_prices = {str(k).lower(): int(v) for k, v in (config.get("sauces") or {}).items()}

    # Validate patty
    patty = patty.lower().strip()
    if patty not in ("beef patty", "chicken patty"):
        return {"error": f"Invalid patty '{patty}'. Choose 'beef patty' or 'chicken patty'."}

    # Calculate price
    total_price = base_price
    selected_toppings = []
    price_breakdown = [{"item": f"Custom burger ({patty})", "price": base_price}]

    for topping in toppings:
        topping = topping.lower().strip()
        if topping not in topping_prices:
            return {"error": f"Unknown topping '{topping}'. Available: {', '.join(sorted(topping_prices))}"}
        price = topping_prices[topping]
        total_price += price
        selected_toppings.append(topping)
        if price > 0:
            price_breakdown.append({"item": f"+ {topping}", "price": price})

    selected_sauces = []
    for sauce in sauces:
        sauce = sauce.lower().strip()
        if sauce not in sauce_prices:
            return {"error": f"Unknown sauce '{sauce}'. Available: {', '.join(sorted(sauce_prices))}"}
        price = sauce_prices[sauce]
        total_price += price
        selected_sauces.append(sauce)
        if price > 0:
            price_breakdown.append({"item": f"+ {sauce}", "price": price})

    # Build description for the order
    bun = str(bun or "").strip().lower()
    parts = ([f"{bun} bun"] if bun in BUNS else []) + [patty]
    if selected_toppings:
        parts.extend(selected_toppings)
    if selected_sauces:
        parts.extend(selected_sauces)
    description = ", ".join(parts)

    # Use a unique item ID for each custom burger configuration
    import hashlib
    config_hash = hashlib.md5(description.encode()).hexdigest()[:6]
    item_id = f"custom-burger-{config_hash}"
    name = "Custom Burger"

    logger.info("build_custom_burger: %s toppings=%s sauces=%s price=%s", patty, selected_toppings, selected_sauces, total_price)

    get_order_state().add_item(item_id, name, quantity, total_price, description)
    note_added("custom-burger")
    summary = get_order_state().get_summary()

    # Auto-update the UI: close burger builder, update order
    try:
        _call().burger = None
        current = get_ui_state()
        current["burgerBuilder"] = {"active": False, "added": True}   # the app flies the burger into the order and closes the builder
        current["highlightedItem"] = None
        current["orderItems"] = summary["items"]
        current["orderTotal"] = summary["total"]
        set_ui_state(current)
    except Exception as e:
        logger.warning("build_custom_burger: failed to auto-update UI: %s", e)

    return _sanitize_result(_while_choosing({
        "status": "added",
        "item": "Custom Burger",
        "patty": patty,
        "toppings": selected_toppings,
        "sauces": selected_sauces,
        "price": f"{CURRENCY} {total_price / 100:.2f}",
        "priceText": _spoken(total_price),
        "total": summary["total"],
        "totalText": _spoken(summary["total"]),
    }))


# ---------- building a burger by voice: every ingredient the customer names lands on the burger on their screen ----------

BUNS = ("brioche", "sesame", "potato", "parmesan")
_MAX_LAYER = 3   # same as the app: at most three of one layer
_SAYS = {   # what customers say -> the name in the burger config
    "beef": "beef patty", "chicken": "chicken patty", "american": "american cheese", "cheddar": "cheddar cheese",
    "pepper jack": "pepper jack cheese", "pepperjack": "pepper jack cheese", "swiss": "swiss cheese", "cheese": "american cheese",
    "egg": "fried egg", "eggs": "fried egg", "jalapeno": "jalapeños", "jalapenos": "jalapeños", "jalapeño": "jalapeños",
    "pickle": "pickles", "mushroom": "mushrooms", "onions": "onion", "tomatoes": "tomato", "bbq": "bbq sauce",
    "barbecue": "bbq sauce", "barbecue sauce": "bbq sauce", "chipotle": "chipotle mayo", "special": "special sauce",
    "mayonnaise": "mayo", "avocados": "avocado", "lettuces": "lettuce",
}


def _ingredient(name: str, known: dict) -> str:
    k = re.sub(r"\s+", " ", str(name or "").strip().lower())
    k = _SAYS.get(k, k)
    if k in known:
        return k
    for opt in known:   # "a slice of cheddar", "extra bacon"
        if re.search(r"\b" + re.escape(opt) + r"\b", k) or re.search(r"\b" + re.escape(k) + r"\b", opt):
            return opt
    return ""


def _builder_screen(b: dict, added=(), removed=()) -> None:
    current = get_ui_state()
    current["burgerBuilder"] = {"active": True, "voice": True, "bun": b["bun"], "patty": b["patty"],
                                "toppings": list(b["toppings"]), "sauces": list(b["sauces"]), "price": b["price"],
                                "just": list(added), "removed": list(removed), "seq": b["seq"]}
    set_ui_state(current)


@tool
def burger_builder(add: list = None, remove: list = None, patty: str = "", bun: str = "", close: bool = False) -> dict:
    """The live Build Your Own Burger on the customer's screen. Each ingredient you add drops onto the burger as they watch.

    Call it with no arguments as soon as the customer wants to build their own burger: the builder opens (beef patty on
    a brioche bun to start). Then call it EVERY time they name ingredients, straight away, before you speak.

    Args:
        add: Toppings and sauces they just asked for, in English, e.g. ["bacon", "cheddar cheese", "bbq sauce"].
            Say "two bacon" as ["bacon", "bacon"].
        remove: Toppings or sauces to take off, e.g. ["onion"].
        patty: "beef patty" or "chicken patty" if they choose or change it.
        bun: "brioche", "sesame", "potato" or "parmesan" if they choose it.
        close: true only if they no longer want a custom burger.

    Returns:
        What is on the burger now. When they say it is done, recap it in a few words (no prices), ask for a yes, then
        call build_custom_burger with exactly these patty, toppings, sauces and bun.
    """
    call = _call()
    if close:
        call.burger = None
        current = get_ui_state(); current["burgerBuilder"] = None; set_ui_state(current)
        return {"status": "closed", "next": "Carry on with the order."}
    config = get_burger_config()
    base = int(config.get("basePrice", _CUSTOM_BURGER_BASE_PRICE))
    tops = {str(k).lower(): int(v) for k, v in (config.get("toppings") or {}).items()}
    sauces = {str(k).lower(): int(v) for k, v in (config.get("sauces") or {}).items()}
    b = call.burger or {"bun": "brioche", "patty": "beef patty", "toppings": [], "sauces": [], "price": base, "seq": 0}
    opened = call.burger is None
    added, removed, unknown = [], [], []
    p = _ingredient(patty, {"beef patty": 0, "chicken patty": 0}) if patty else ""
    if p:
        b["patty"] = p
        added.append(p)
    if str(bun or "").strip().lower() in BUNS:
        b["bun"] = str(bun).strip().lower()
    for raw in (add or []):
        k = _ingredient(raw, {**tops, **sauces})
        if not k:
            if _ingredient(raw, {"beef patty": 0, "chicken patty": 0}):
                b["patty"] = _ingredient(raw, {"beef patty": 0, "chicken patty": 0}); added.append(b["patty"])
            elif str(raw).strip().lower() in BUNS:
                b["bun"] = str(raw).strip().lower()
            else:
                unknown.append(str(raw))
            continue
        layer = "sauces" if k in sauces and k not in tops else "toppings"
        if b[layer].count(k) >= _MAX_LAYER:
            continue
        b[layer].append(k)
        added.append(k)
    for raw in (remove or []):
        k = _ingredient(raw, {**tops, **sauces})
        for layer in ("toppings", "sauces"):
            if k and k in b[layer]:
                b[layer].remove(k)
                removed.append(k)
                break
    b["price"] = base + sum(tops.get(k, 0) for k in b["toppings"]) + sum(sauces.get(k, 0) for k in b["sauces"])
    b["seq"] += 1
    call.burger = b
    _builder_screen(b, added, removed)
    result = {"status": "opened" if opened else "updated", "bun": b["bun"], "patty": b["patty"],
              "toppings": b["toppings"], "sauces": b["sauces"]}
    if unknown:
        result["not_available"] = unknown
        result["options"] = sorted(tops) + sorted(sauces)
    if opened and not added:
        result["next"] = ("The builder is open with a beef patty on a brioche bun. In one short sentence, invite them to "
                          "say what goes on it (for example cheese, bacon, a sauce). No prices.")
    else:
        result["next"] = ("React in a few lively words, e.g. 'Bacon's on! What else?'. No prices. "
                          + ("Some of that is not available: say so briefly. " if unknown else "")
                          + "When they say that's it, recap it and ask for a yes before build_custom_burger.")
    return result
