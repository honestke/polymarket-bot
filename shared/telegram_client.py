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
    httpx.post(f"{_api_base()}/sendMessage", json=payload, timeout=10)


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
