import httpx

from . import config


def _api_base() -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def send_message(chat_id, text: str, parse_mode: str = "Markdown", reply_markup: dict | None = None) -> None:
    if not chat_id:
        return
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    resp = httpx.post(f"{_api_base()}/sendMessage", json=payload, timeout=10)
    if resp.status_code >= 400:
        # Telegram's API doesn't raise on the transport level for a
        # rejected message (bad Markdown, oversized callback_data, etc.)
        # — without this check, failures like that are completely
        # invisible: the script "succeeds" while messages silently never
        # arrive. Printed, not raised, so one bad card doesn't kill the
        # rest of a batch (digest, scan alerts).
        print(f"Telegram sendMessage failed ({resp.status_code}): {resp.text[:300]}")


def answer_callback_query(callback_query_id: str, text: str | None = None) -> None:
    """Must be called for every button press (callback_query) received,
    even with no text — otherwise Telegram shows a loading spinner on the
    button until it times out."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    httpx.post(f"{_api_base()}/answerCallbackQuery", json=payload, timeout=10)


def set_webhook(url: str) -> dict:
    resp = httpx.post(
        f"{_api_base()}/setWebhook",
        json={"url": url, "secret_token": config.TELEGRAM_WEBHOOK_SECRET},
        timeout=10,
    )
    return resp.json()


def set_my_commands(commands: list[dict]) -> None:
    """Registers the bot's command list with Telegram so it shows up in
    the native menu (the icon next to the message box, or typing '/'
    autocompletes with descriptions) — without this, a new user has to
    already know to type /start with no prompt at all.

    Called from a FastAPI startup event (services/bot/app.py) — a network
    hiccup here must never be allowed to crash app startup and take the
    whole webhook down with it, so this swallows and logs rather than
    raising."""
    try:
        httpx.post(f"{_api_base()}/setMyCommands", json={"commands": commands}, timeout=10)
    except httpx.HTTPError as exc:
        print(f"set_my_commands failed (non-fatal, app will still start): {exc}")
