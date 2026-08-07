from shared import db, telegram_client

HELP_TEXT = (
    "*Commands*\n"
    "/top - highest-ranked opportunities right now\n"
    "/watchlist - show your priority boosts\n"
    "/add <keyword or category> - boost matching markets in rankings/alerts\n"
    "/remove <keyword or category> - remove a boost\n"
    "/stats - basic system stats\n"
    "/help - this message\n\n"
    "This bot monitors the *entire* Polymarket platform by default. "
    "Boosts change how markets are prioritized in alerts and rankings — "
    "they never limit which markets get tracked."
)


def handle(chat_id: int, text: str) -> None:
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command in ("/start", "/help"):
        telegram_client.send_message(chat_id, HELP_TEXT)
    elif command == "/top":
        _top(chat_id)
    elif command == "/watchlist":
        _watchlist(chat_id)
    elif command == "/add":
        _add(chat_id, arg)
    elif command == "/remove":
        _remove(chat_id, arg)
    elif command == "/stats":
        _stats(chat_id)
    else:
        telegram_client.send_message(chat_id, "Unrecognized command. Try /help.")


def _top(chat_id: int) -> None:
    top = db.get_top_opportunities(limit=10)
    if not top:
        telegram_client.send_message(chat_id, "No markets tracked yet — the scan job may not have run.")
        return
    lines = [f"{i}. {m['question']} (score {m['opportunity_score']})" for i, m in enumerate(top, 1)]
    telegram_client.send_message(chat_id, "\n".join(lines))


def _watchlist(chat_id: int) -> None:
    boosts = [b for b in db.get_priority_boosts() if b["chat_id"] == chat_id]
    if not boosts:
        telegram_client.send_message(chat_id, "No boosts set. Use /add <keyword or category>.")
        return
    lines = [f"- {b['keyword_or_category']} (weight {b['weight']})" for b in boosts]
    telegram_client.send_message(chat_id, "\n".join(lines))


def _add(chat_id: int, term: str) -> None:
    if not term:
        telegram_client.send_message(chat_id, "Usage: /add <keyword or category>")
        return
    db.get_client().table("priority_boosts").insert(
        {"chat_id": chat_id, "keyword_or_category": term, "weight": 1.5}
    ).execute()
    telegram_client.send_message(chat_id, f"Added boost: {term}")


def _remove(chat_id: int, term: str) -> None:
    db.get_client().table("priority_boosts").delete().eq("chat_id", chat_id).eq(
        "keyword_or_category", term
    ).execute()
    telegram_client.send_message(chat_id, f"Removed boost (if it existed): {term}")


def _stats(chat_id: int) -> None:
    result = db.get_client().table("markets").select("market_id", count="exact").execute()
    telegram_client.send_message(chat_id, f"Tracking {result.count} active markets across the whole platform.")
