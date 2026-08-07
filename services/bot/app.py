"""
Telegram command webhook — the one long-lived process in this system,
deployed as a Render free web service. Everything else (scan, digest)
runs as scheduled scripts with no persistent process at all.
"""
from fastapi import FastAPI, Header, HTTPException, Request

from services.bot import commands
from shared import config

app = FastAPI()


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

    if chat_id and text:
        commands.handle(chat_id, text)

    return {"ok": True}


@app.get("/")
async def health():
    return {"status": "ok"}
