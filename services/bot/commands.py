from shared import db, formatting, telegram_client

HELP_TEXT = (
    "*Commands*\n"
    "/top - highest-ranked opportunities right now\n"
    "/new - most recently discovered markets\n"
    "/ending - markets closest to resolution\n"
    "/categories - browse by category\n"
    "/saved - markets you've saved\n"
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
        _send_market_list(chat_id, db.get_top_opportunities(limit=5), "🏆")
    elif command == "/new":
        _send_market_list(chat_id, db.get_recent_markets(limit=5), "🆕")
    elif command == "/ending":
        _send_market_list(chat_id, db.get_ending_soon(limit=5), "⏳")
    elif command == "/categories":
        _categories(chat_id)
    elif command == "/saved":
        _send_market_list(chat_id, db.get_saved_markets(chat_id), "⭐", empty_msg="No saved markets yet — tap ⭐ Save on any market card.")
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


def handle_callback(chat_id: int, callback_query_id: str, data: str) -> None:
    """Handles button presses (View Details / Save / category picks).
    'Open Market' is a plain URL button and never reaches here."""
    action, _, value = data.partition(":")

    if action == "details":
        market = db.get_market_by_short_id(value)
        if not market:
            telegram_client.answer_callback_query(callback_query_id, "Market not found.")
            return
        telegram_client.answer_callback_query(callback_query_id)
        text = formatting.format_market_card(market, icon="📈")
        keyboard = formatting.market_keyboard(market["short_id"], market.get("slug"))
        telegram_client.send_message(chat_id, text, reply_markup=keyboard)

    elif action == "save":
        market = db.get_market_by_short_id(value)
        if not market:
            telegram_client.answer_callback_query(callback_query_id, "Market not found.")
            return
        db.save_market(chat_id, market["market_id"])
        telegram_client.answer_callback_query(callback_query_id, "Saved ⭐")

    elif action == "category":
        telegram_client.answer_callback_query(callback_query_id)
        _send_market_list(chat_id, db.get_markets_by_category(value, limit=5), "📂")

    else:
        telegram_client.answer_callback_query(callback_query_id)


def _send_market_list(chat_id: int, markets: list[dict], icon: str, empty_msg: str = "Nothing to show yet.") -> None:
    if not markets:
        telegram_client.send_message(chat_id, empty_msg)
        return
    for market in markets:
        text = formatting.format_market_card(market, icon=icon)
        keyboard = formatting.market_keyboard(market["short_id"], market.get("slug"))
        telegram_client.send_message(chat_id, text, reply_markup=keyboard)


def _categories(chat_id: int) -> None:
    categories = db.get_categories()
    if not categories:
        telegram_client.send_message(chat_id, "No markets tracked yet.")
        return
    keyboard = {
        "inline_keyboard": [
            [{"text": f"{c['category']} ({c['count']})", "callback_data": f"category:{c['category']}"}]
            for c in categories[:10]
        ]
    }
    telegram_client.send_message(chat_id, "📂 *Browse by category*", reply_markup=keyboard)


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
