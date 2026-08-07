import httpx

from . import config


def _api_base() -> str:
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"


def send_message(chat_id, text: str, parse_mode: str = "Markdown") -> None:
    if not chat_id:
        return
    httpx.post(
        f"{_api_base()}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        timeout=10,
    )


def set_webhook(url: str) -> dict:
    resp = httpx.post(
        f"{_api_base()}/setWebhook",
        json={"url": url, "secret_token": config.TELEGRAM_WEBHOOK_SECRET},
        timeout=10,
    )
    return resp.json()
