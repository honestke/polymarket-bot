"""
Telegram command webhook — the one long-lived process in this system,
deployed as a Render free web service. Everything else (scan, digest)
runs as scheduled scripts with no persistent process at all.
"""
from fastapi import FastAPI, Header, HTTPException, Request

from services.bot import commands
from shared import config, telegram_client

app = FastAPI()

BOT_COMMANDS = [
    {"command": "top", "description": "Highest-ranked opportunities right now"},
    {"command": "trending", "description": "Markets with significant recent activity"},
    {"command": "new", "description": "Most recently discovered markets"},
    {"command": "ending", "description": "Markets closest to resolution"},
    {"command": "live", "description": "Recent activity below your push threshold"},
    {"command": "categories", "description": "Browse by category"},
    {"command": "saved", "description": "Markets you've saved"},
    {"command": "search", "description": "Search current markets: /search <term>"},
    {"command": "watchlist", "description": "Show your priority boosts"},
    {"command": "add", "description": "Boost matching markets: /add <keyword>"},
    {"command": "remove", "description": "Remove a boost: /remove <keyword>"},
    {"command": "threshold", "description": "Set push cutoff: /threshold <0-100>"},
    {"command": "stats", "description": "Basic system stats"},
    {"command": "help", "description": "Show all commands"},
]


@app.on_event("startup")
async def register_commands() -> None:
    """Runs automatically every time this service boots (including every
    deploy) — registers the command list with Telegram so it shows up in
    the native menu with no manual curl step required, ever.

    Wrapped defensively: this is a nice-to-have, and must never be able
    to prevent the webhook itself from coming up if Telegram is slow or
    unreachable during a cold start."""
    try:
        telegram_client.set_my_commands(BOT_COMMANDS)
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
        print(f"register_commands startup hook failed (non-fatal): {exc}")


@app.post("/webhook")
async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(default="")):
    if config.TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != config.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="invalid secret token")

    update = await request.json()

    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = cq.get("message", {}).get("chat", {}).get("id")
        if chat_id:
            commands.handle_callback(chat_id, cq["id"], cq.get("data", ""))
        return {"ok": True}

    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()

    # A reply to our own force_reply search prompt is search input, not a
    # command — Telegram's force_reply is the cleanest native way to get
    # free-text input without any custom session/state tracking.
    reply_to = message.get("reply_to_message", {})
    if chat_id and text and reply_to.get("text") == commands.SEARCH_PROMPT:
        commands.handle_search_reply(chat_id, text)
        return {"ok": True}

    if chat_id and text:
        commands.handle(chat_id, text)

    return {"ok": True}


@app.get("/")
async def health():
    return {"status": "ok"}
