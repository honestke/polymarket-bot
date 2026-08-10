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
    {"command": "watchlist", "description": "Alias for Settings, where boosts now live"},
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
            _safe_dispatch(chat_id, lambda: commands.handle_callback(chat_id, cq["id"], cq.get("data", "")))
        return {"ok": True}

    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()

    if chat_id and text:
        # Check for a pending free-text capture (e.g. Search) before
        # treating the message as a command/menu tap. Tracked in the DB
        # per chat_id — reliable across every Telegram client, unlike
        # depending on reply_to_message threading (the earlier approach,
        # which wasn't consistently triggering).
        #
        # Wrapped defensively: Supabase has occasionally returned a
        # transient Cloudflare-layer error (HTML instead of JSON) rather
        # than a normal response — confirmed as an external
        # infrastructure issue, not a bug in this query. A single hiccup
        # here must not take down the whole command (fail safe: treat it
        # as "no pending action" and let normal command handling proceed,
        # rather than erroring out with no reply at all).
        try:
            pending = commands.get_and_clear_pending_action(chat_id)
        except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
            print(f"get_and_clear_pending_action failed (non-fatal, treating as no pending action): {exc}")
            pending = None

        if pending == "search":
            _safe_dispatch(chat_id, lambda: commands.handle_search_reply(chat_id, text))
        else:
            _safe_dispatch(chat_id, lambda: commands.handle(chat_id, text))

    return {"ok": True}


def _safe_dispatch(chat_id, fn) -> None:
    """Runs a command handler and, if it raises (e.g. a transient
    Supabase/Cloudflare hiccup — confirmed as a real external issue, not
    a bug in the query logic), tells the user to retry instead of
    leaving them with total silence. This is what "Settings"/"Saved"/
    "Categories" taps looked like before this existed: sent, then
    nothing back at all, with no indication anything went wrong."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — deliberately broad, see docstring
        print(f"Command handler failed: {exc}")
        try:
            telegram_client.send_message(
                chat_id, "⚠️ Something went wrong on that request — please try again in a moment."
            )
        except Exception:  # noqa: BLE001 — never let the error-reporting path itself crash the webhook
            pass


@app.get("/")
async def health():
    return {"status": "ok"}
