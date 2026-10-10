"""Voice languages for the attendant: English, Arabic and Malayalam.

English runs on Amazon Nova Sonic exactly as before. Nova Sonic cannot speak Arabic or
Malayalam, so those two run on Google's Gemini Live, through the same voice agent, the
same tools and the same instructions.

Arabic and Malayalam switch on when a Gemini API key is set on the server:

    GOOGLE_API_KEY (or GEMINI_API_KEY)   a key from https://aistudio.google.com/apikey

Optional settings:

    GEMINI_VOICE_MODEL_ID   the Gemini Live model, default "gemini-3.8-live"
    GEMINI_VOICE            the voice, default "Kore" (GEMINI_VOICE_AR / GEMINI_VOICE_ML pick one per language)
    GEMINI_VAD_START, GEMINI_VAD_END, GEMINI_VAD_SILENCE_MS, GEMINI_VAD_PREFIX_MS   turn-taking (see _live_tuning)
    GEMINI_AFFECTIVE        "1" lets the voice match the customer's tone
    GEMINI_API_VERSION      default "v1beta"

Without a key only English is offered, and calls run exactly as they did before this file existed.

A customer changes language by asking the attendant (the switch_language tool in main.py) or by
tapping a language in the ordering app. Either way the app reconnects in the new language and the
order carries over: see issue_resume / take_resume below.
"""

import hmac
import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)

DEFAULT = "en"
MODEL_ID = os.getenv("GEMINI_VOICE_MODEL_ID", "gemini-3.8-live")
VOICE = os.getenv("GEMINI_VOICE", "Kore")
API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta")
RESUME_SECONDS = 30  # how long the app has to reconnect after a language switch and keep its order

LANGUAGES = {
    "en": {
        "name": "English",
        "aliases": ("en", "eng", "english", "inglizi", "الإنجليزية", "انجليزي", "إنجليزي", "ഇംഗ്ലീഷ്"),
        "resume": "Sure, let's carry on in English. What would you like?",
    },
    "ar": {
        "name": "Arabic",
        "aliases": ("ar", "ara", "arabic", "arabi", "العربية", "عربي", "عربى", "അറബിക്", "അറബി"),
        "greeting": "أهلاً بك في VoiceBite! كيف أقدر أساعدك؟",
        "resume": "تمام، نكمل بالعربية. ماذا تحب أن تطلب؟",
        "style": "Use clear, friendly spoken Arabic that customers across the UAE follow easily: "
                 "simple wording with a light Gulf touch, not stiff formal Arabic",
        "dirhams": "درهم",
    },
    "ml": {
        "name": "Malayalam",
        "aliases": ("ml", "mal", "malayalam", "malayalee", "മലയാളം", "المالايالامية", "مليالم", "ماليالام"),
        "greeting": "VoiceBite-ലേക്ക് സ്വാഗതം! എങ്ങനെ സഹായിക്കാം?",
        "resume": "ശരി, ഇനി മലയാളത്തിൽ തുടരാം. എന്താണ് വേണ്ടത്?",
        "style": "Use natural, everyday spoken Malayalam, not formal written style. Common English food words "
                 "(burger, fries, cola) stay as people in Kerala say them",
        "dirhams": "ദിർഹം",
    },
}


# ---------- which languages this server can speak ----------

def _api_key() -> str:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or ""


_model_class = None      # built on first use, so English calls never load Google's library
_library_missing = False


def _gemini_model_class():
    global _model_class
    if _model_class is None:
        from google.genai import types as genai_types
        from strands.experimental.bidi.models import BidiGeminiLiveModel

        class _GeminiAttendant(BidiGeminiLiveModel):
            """Gemini Live that waits for each tool result before it speaks again.

            The attendant must hear back from add_to_order or place_order before it confirms an item,
            a total or an order number, the same way the English attendant works.
            """

            def _format_tools_for_live_api(self, tool_specs):
                if not tool_specs:
                    return []
                return [genai_types.Tool(function_declarations=[
                    genai_types.FunctionDeclaration(
                        name=spec["name"],
                        description=spec["description"],
                        parameters_json_schema=spec["inputSchema"]["json"],
                        behavior=genai_types.Behavior.BLOCKING,
                    )
                    for spec in tool_specs
                ])]

        _model_class = _GeminiAttendant
    return _model_class


def _gemini_ready() -> bool:
    global _library_missing
    if not _api_key() or _library_missing:
        return False
    try:
        _gemini_model_class()
        return True
    except Exception as e:
        _library_missing = True
        logger.warning("A Gemini API key is set but Gemini Live could not be loaded, so only English is offered: %s", e)
        return False


def available() -> list:
    """Language codes this server can speak right now, English first."""
    return ["en", "ar", "ml"] if _gemini_ready() else ["en"]


def code_for(text) -> str:
    """Turn "ar", "Arabic" or "العربية" into a language code; "" if it is not one of ours."""
    wanted = str(text or "").strip().lower()
    for code, info in LANGUAGES.items():
        if wanted in info["aliases"]:
            return code
    return ""


def pick(requested) -> str:
    """The language a new call runs in: the one asked for if this server can speak it, otherwise English."""
    code = code_for(requested)
    return code if code in available() else DEFAULT


def name(code: str) -> str:
    return LANGUAGES.get(code, LANGUAGES[DEFAULT])["name"]


def _int_env(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.getenv(name, default))))
    except ValueError:
        return default


def _live_tuning() -> dict:
    """How Gemini Live decides the customer has started and finished speaking.

    The defaults suit a car at a drive-thru window: engine, indicator and road noise should not
    cut the attendant off mid-sentence (low start sensitivity), while a customer who stops talking
    gets an answer quickly (high end sensitivity, about half a second of silence).
    """
    tuning = {
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": False,
                "start_of_speech_sensitivity": os.getenv("GEMINI_VAD_START", "START_SENSITIVITY_LOW"),
                "end_of_speech_sensitivity": os.getenv("GEMINI_VAD_END", "END_SENSITIVITY_HIGH"),
                "prefix_padding_ms": _int_env("GEMINI_VAD_PREFIX_MS", 300, 0, 2000),
                "silence_duration_ms": _int_env("GEMINI_VAD_SILENCE_MS", 550, 200, 2000),
            },
        },
        # long calls stay inside the context window instead of ending abruptly
        "context_window_compression": {"sliding_window": {}},
    }
    if os.getenv("GEMINI_AFFECTIVE", "").lower() in ("1", "true", "yes"):
        tuning["enable_affective_dialog"] = True   # tone follows the customer's mood; switch off if the model rejects it
    return tuning


def make_model(lang: str):
    """The voice model for an Arabic or Malayalam call. English keeps its own model in main.py."""
    voice = os.getenv(f"GEMINI_VOICE_{lang.upper()}", VOICE)   # e.g. GEMINI_VOICE_ML=Aoede, GEMINI_VOICE_AR=Kore
    return _gemini_model_class()(
        model_id=MODEL_ID,
        provider_config={"audio": {"voice": voice}, "inference": _live_tuning()},
        client_config={"api_key": _api_key(), "http_options": {"api_version": API_VERSION}},
    )


def sends_pieces(lang: str) -> bool:
    """Gemini sends what was said a few words at a time; the app joins the pieces into one line."""
    return lang != DEFAULT


# ---------- what the attendant is told ----------

def first_line(lang: str, resumed: bool, english_greeting: str) -> str:
    """The attendant's opening words: the greeting, or a short "let's carry on" after a language switch."""
    info = LANGUAGES.get(lang, LANGUAGES[DEFAULT])
    if resumed:
        return info["resume"]
    return info.get("greeting") or english_greeting


def prompt_section(lang: str, resumed: bool = False, order_lines: list = None) -> str:
    """Extra instructions added to the attendant's prompt. Empty when English is the only language."""
    codes = available()
    if len(codes) < 2:
        return ""
    info = LANGUAGES.get(lang, LANGUAGES[DEFAULT])
    others = [c for c in codes if c != lang]
    other_names = " or ".join(LANGUAGES[c]["name"] for c in others)
    calls = " or ".join(f'switch_language(language="{c}")' for c in others)

    if lang == DEFAULT:
        lines = [
            "",
            "LANGUAGE: This call is in English, and you only speak English.",
            f'- If the customer asks to continue in {other_names} (for example "Arabic please" or "can you speak Malayalam?"), '
            f"call {calls} straight away. A colleague who speaks that language takes over the call with the order as it is, "
            "so say nothing after calling it",
            f"- Never try to speak {other_names} yourself, and never offer any other language",
        ]
    else:
        spoken = info["name"]
        lines = [
            "",
            f"LANGUAGE: This call is in {spoken}. RESPOND IN {spoken.upper()}. YOU MUST RESPOND UNMISTAKABLY IN {spoken.upper()}.",
            f"- Everything you say is in {spoken}, including the fixed phrases quoted in these instructions: "
            f"say their natural {spoken} equivalent, never the English wording",
            f"- {info['style']}",
            "- Reply in one or two short sentences, then stop and let the customer talk. Speak once per turn and never repeat yourself",
            "- When a tool is needed, call it first and speak after its result",
            f"- Tool results come back in English. When you do say a price or the total (only at checkout, or when asked), say it in {spoken}, "
            f"with exactly the same numbers and the word {info['dirhams']} for dirhams",
            f"- You may say menu item names the way {spoken} speakers naturally say them. The itemId and categoryId you pass "
            "to tools stay exactly as written in the menu",
            '- Tool arguments are always written in English letters: vehicle_number in Latin letters and the digits 0-9 '
            '(for example "D 12345"), and special_instructions in English so the kitchen can read them',
            '- Short typed messages from the ordering page arrive in English (for example "Hello", or "Please add one Cheeseburger '
            f'to my order"). Act on them and answer in {spoken}. They never mean the customer wants English',
            f"- If the customer asks to continue in {other_names}, or speaks whole sentences to you in one of them, "
            f"call {calls} straight away and say nothing after it. English food names inside a {spoken} sentence do not count",
        ]

    if resumed:
        so_far = "; ".join(order_lines or []) or "nothing yet"
        lines += [
            "",
            f"CONTINUED CALL: The customer was already talking to a colleague and asked to carry on in {info['name']}. "
            "Do not welcome them again and do not ask them to repeat anything.",
            f"Their order so far is already saved, so do not add these again: {so_far}.",
        ]
    return "\n".join(lines) + "\n"


def closed_note(lang: str) -> str:
    """Added to the "we are closed" instructions so the message is spoken in the caller's language."""
    return "" if lang == DEFAULT else f"\nSay it in {name(lang)}, not in English."


# ---------- carrying the order across a language switch ----------
# The server takes one call at a time and holds its order in memory. When the customer changes language the
# app reconnects, and a normal new call starts with an empty order. So a switch hands the app a one-use key:
# reconnecting with it inside RESUME_SECONDS keeps the order. Any other new call voids the key.

_resume = {"token": "", "until": 0.0}


def issue_resume() -> str:
    _resume.update(token=secrets.token_urlsafe(12), until=time.monotonic() + RESUME_SECONDS)
    return _resume["token"]


def take_resume(token) -> bool:
    """True if this new call is the same customer coming back after a language switch."""
    saved, until = _resume["token"], _resume["until"]
    _resume.update(token="", until=0.0)
    if not saved or not token or time.monotonic() > until:
        return False
    return hmac.compare_digest(saved.encode(), str(token).encode())
