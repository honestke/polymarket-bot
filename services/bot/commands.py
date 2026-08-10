from shared import config, db, formatting, telegram_client

HELP_TEXT = (
    "*Commands*\n"
    "Use the menu buttons below, or these commands directly:\n\n"
    "/top - highest-ranked opportunities right now\n"
    "/new - most recently discovered markets\n"
    "/ending - markets closest to resolution\n"
    "/live - recent activity that didn't warrant a push notification\n"
    "/categories - browse by category\n"
    "/saved - markets you've saved\n"
    "/watchlist - show your priority boosts\n"
    "/add <keyword or category> - boost matching markets in rankings/alerts\n"
    "/remove <keyword or category> - remove a boost\n"
    "/stats - basic system stats\n"
    "/help - this message\n\n"
    "This bot monitors the *entire* Polymarket platform by default. "
    "Boosts change how markets are prioritized in alerts and rankings — "
    "they never limit which markets get tracked.\n\n"
    "Only the highest-scoring events push an instant notification — "
    "everything else still gets logged, just check 📡 Live Updates for it."
)

# Persistent-menu button labels map to the same handlers as their slash
# command equivalents.
_MENU_LABELS = {
    "🏆 Best Opportunities": "_best_menu",
    "🆕 New Markets": "_new",
    "⏳ Ending Soon": "_ending_menu",
    "📡 Live Updates": "_live",
    "📂 Categories": "_categories",
    "⚙️ Settings": "_settings",
}


def handle(chat_id: int, text: str) -> None:
    if text in _MENU_LABELS:
        globals()[_MENU_LABELS[text]](chat_id)
        return

    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command == "/start":
        telegram_client.send_message(chat_id, HELP_TEXT, reply_markup=formatting.MAIN_MENU_KEYBOARD)
    elif command == "/help":
        telegram_client.send_message(chat_id, HELP_TEXT)
    elif command == "/top":
        _best_menu(chat_id)
    elif command == "/new":
        _new(chat_id)
    elif command == "/ending":
        _ending_menu(chat_id)
    elif command == "/live":
        _live(chat_id)
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
    """Handles button presses: View Details / Save / category picks /
    Ending Soon time buckets / Best Opportunities time windows.
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

    elif action == "ending":
        telegram_client.answer_callback_query(callback_query_id)
        bucket = config.ENDING_SOON_BUCKETS.get(value)
        if not bucket:
            return
        min_days, max_days = bucket
        _send_market_list(chat_id, db.get_ending_in_range(min_days, max_days, limit=5), "⏳")

    elif action == "best":
        telegram_client.answer_callback_query(callback_query_id)
        since_days = config.BEST_OPPORTUNITIES_WINDOWS.get(value)
        if since_days is None:
            return
        _send_market_list(chat_id, db.get_top_opportunities_since(since_days, limit=5), "🏆")

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


def _best_menu(chat_id: int) -> None:
    keyboard = {
        "inline_keyboard": [
            [{"text": "🔥 Today", "callback_data": "best:today"}],
            [{"text": "📅 This Week", "callback_data": "best:week"}],
            [{"text": "🗓️ This Month", "callback_data": "best:month"}],
        ]
    }
    telegram_client.send_message(chat_id, "🏆 *Best Opportunities* — pick a window:", reply_markup=keyboard)


def _new(chat_id: int) -> None:
    _send_market_list(chat_id, db.get_recent_markets(limit=5), "🆕")


def _ending_menu(chat_id: int) -> None:
    keyboard = {
        "inline_keyboard": [
            [{"text": "🔴 Within 24 Hours", "callback_data": "ending:24h"}],
            [{"text": "🟠 Within 7 Days", "callback_data": "ending:7d"}],
            [{"text": "🟡 Within 2 Weeks", "callback_data": "ending:2w"}],
            [{"text": "🟢 Within 1 Month", "callback_data": "ending:1m"}],
            [{"text": "🔵 Longer Than 1 Month", "callback_data": "ending:longer"}],
        ]
    }
    telegram_client.send_message(chat_id, "⏳ *Ending Soon* — pick a window:", reply_markup=keyboard)


def _live(chat_id: int) -> None:
    feed = db.get_live_feed(limit=15)
    if not feed:
        telegram_client.send_message(chat_id, "No recent activity logged yet.")
        return
    lines = ["📡 *Live Updates* — recent activity below the push threshold:\n"]
    lines.extend(formatting.format_feed_line(row) for row in feed)
    telegram_client.send_message(chat_id, "\n".join(lines))


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


def _settings(chat_id: int) -> None:
    boosts = [b for b in db.get_priority_boosts() if b["chat_id"] == chat_id]
    boost_lines = "\n".join(f"- {b['keyword_or_category']} (weight {b['weight']})" for b in boosts) or "None set."
    result = db.get_client().table("markets").select("market_id", count="exact").execute()
    text = (
        "⚙️ *Settings*\n\n"
        f"Tracking {result.count} active markets platform-wide.\n\n"
        f"*Your priority boosts:*\n{boost_lines}\n\n"
        "/add <keyword or category> — boost matching markets\n"
        "/remove <keyword or category> — remove a boost\n\n"
        f"Push notifications fire only for markets scoring "
        f"{int(config.PUSH_OPPORTUNITY_THRESHOLD * 100)}/100 or higher — "
        "everything else is still logged in 📡 Live Updates."
    )
    telegram_client.send_message(chat_id, text)


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
