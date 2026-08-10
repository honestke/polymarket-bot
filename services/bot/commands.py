import calendar
from datetime import datetime, timezone

from shared import config, db, formatting, scoring, telegram_client

HELP_TEXT = (
    "*Commands*\n"
    "Use the menu buttons below, or these commands directly:\n\n"
    "/top - highest-ranked opportunities right now\n"
    "/trending - markets with significant recent activity\n"
    "/new - most recently discovered markets\n"
    "/ending - markets closest to resolution\n"
    "/live - recent activity that didn't warrant a push notification\n"
    "/categories - browse by category\n"
    "/saved - markets you've saved\n"
    "/watchlist - show your priority boosts\n"
    "/add <keyword or category> - boost matching markets in rankings/alerts\n"
    "/remove <keyword or category> - remove a boost\n"
    "/threshold <0-100> - set your personal push-notification cutoff\n"
    "/stats - basic system stats\n"
    "/help - this message\n\n"
    "This bot monitors the *entire* Polymarket platform by default. "
    "Boosts change how markets are prioritized in alerts and rankings — "
    "they never limit which markets get tracked.\n\n"
    "Only markets scoring above your threshold push an instant notification "
    "— everything else still gets logged, just check 📡 Live Updates for it."
)

WELCOME_TEXT = (
    "👋 *Welcome to your Polymarket Intelligence Bot*\n\n"
    "Use the buttons below to browse. Send /help anytime for the full command list."
)

# Persistent-menu button labels map to the same handlers as their slash
# command equivalents.
_MENU_LABELS = {
    "🏆 Best Opportunities": "_best_menu",
    "🔥 Trending": "_trending",
    "🆕 New Markets": "_new",
    "⏳ Ending Soon": "_ending_menu",
    "📡 Live Updates": "_live",
    "📂 Categories": "_categories",
    "⭐ Saved": "_saved",
    "📊 Stats": "_stats",
    "⚙️ Settings": "_settings",
    "❓ Help": "_help",
}


def handle(chat_id: int, text: str) -> None:
    if text in _MENU_LABELS:
        globals()[_MENU_LABELS[text]](chat_id)
        return

    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command == "/start":
        telegram_client.send_message(chat_id, WELCOME_TEXT, reply_markup=formatting.MAIN_MENU_KEYBOARD)
    elif command == "/help":
        _help(chat_id)
    elif command == "/top":
        _best_menu(chat_id)
    elif command == "/trending":
        _trending(chat_id)
    elif command == "/new":
        _new(chat_id)
    elif command == "/ending":
        _ending_menu(chat_id)
    elif command == "/live":
        _live(chat_id)
    elif command == "/categories":
        _categories(chat_id)
    elif command == "/saved":
        _saved(chat_id)
    elif command == "/watchlist":
        _watchlist(chat_id)
    elif command == "/add":
        _add(chat_id, arg)
    elif command == "/remove":
        _remove(chat_id, arg)
    elif command == "/threshold":
        _set_threshold(chat_id, arg)
    elif command == "/stats":
        _stats(chat_id)
    else:
        telegram_client.send_message(chat_id, "Unrecognized command. Try /help.")


def handle_callback(chat_id: int, callback_query_id: str, data: str) -> None:
    """Handles button presses: View Details / Save / category picks /
    Ending Soon buckets (relative + calendar month) / Best Opportunities
    time windows. 'Open Market' is a plain URL button, never reaches here."""
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
        _send_market_list(chat_id, db.get_markets_by_category(value, limit=10), "📂")

    elif action == "ending":
        telegram_client.answer_callback_query(callback_query_id)
        bucket = config.ENDING_SOON_BUCKETS.get(value)
        if not bucket:
            return
        min_days, max_days = bucket
        _send_market_list(chat_id, db.get_ending_in_range(min_days, max_days, limit=10), "⏳")

    elif action == "endingmonthmenu":
        telegram_client.answer_callback_query(callback_query_id)
        _send_month_picker(chat_id)

    elif action == "endingmonth":
        telegram_client.answer_callback_query(callback_query_id)
        try:
            year_str, month_str = value.split("-")
            year, month = int(year_str), int(month_str)
        except ValueError:
            return
        label = f"{calendar.month_name[month]} {year}"
        _send_market_list(
            chat_id, db.get_ending_in_calendar_month(year, month, limit=10), "📅",
            empty_msg=f"Nothing resolving in {label} yet.",
        )

    elif action == "best":
        telegram_client.answer_callback_query(callback_query_id)
        if value == "volume":
            _count_menu(chat_id, "volume", "💰 By Volume")
            return
        since_days = config.BEST_OPPORTUNITIES_WINDOWS.get(value)
        if since_days is None:
            return
        _send_market_list(chat_id, db.get_top_opportunities_since(since_days, limit=10), "🏆")

    elif action == "volume":
        telegram_client.answer_callback_query(callback_query_id)
        try:
            limit = int(value)
        except ValueError:
            limit = 10
        _send_market_list(chat_id, db.get_top_by_volume(limit=limit), "💰")

    elif action == "threshold":
        try:
            pct = float(value)
        except ValueError:
            telegram_client.answer_callback_query(callback_query_id, "Invalid value.")
            return
        db.set_push_threshold(chat_id, pct / 100)
        telegram_client.answer_callback_query(callback_query_id, f"Threshold set to {pct:.0f}/100")

    elif action == "addboost":
        _add_boost(chat_id, value)
        telegram_client.answer_callback_query(callback_query_id, f"Boosted: {value}")
        _settings(chat_id)  # resend so the button list reflects the change immediately

    elif action == "removeboost":
        _remove_boost(chat_id, value)
        telegram_client.answer_callback_query(callback_query_id, f"Removed: {value}")
        _settings(chat_id)

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
            [{"text": "💰 By Volume", "callback_data": "best:volume"}],
        ]
    }
    telegram_client.send_message(chat_id, "🏆 *Best Opportunities* — pick a window:", reply_markup=keyboard)


def _count_menu(chat_id: int, prefix: str, title: str) -> None:
    keyboard = {
        "inline_keyboard": [
            [{"text": "Top 5", "callback_data": f"{prefix}:5"}],
            [{"text": "Top 10", "callback_data": f"{prefix}:10"}],
            [{"text": "Top 20", "callback_data": f"{prefix}:20"}],
        ]
    }
    telegram_client.send_message(chat_id, f"{title} — how many?", reply_markup=keyboard)


def _trending(chat_id: int) -> None:
    _send_market_list(
        chat_id, db.get_trending(hours=6, limit=10), "🔥",
        empty_msg="Nothing trending in the last 6 hours.",
    )


def _new(chat_id: int) -> None:
    _send_market_list(chat_id, db.get_recent_markets(limit=10), "🆕")


def _help(chat_id: int) -> None:
    telegram_client.send_message(chat_id, HELP_TEXT, reply_markup=formatting.MAIN_MENU_KEYBOARD)


def _saved(chat_id: int) -> None:
    _send_market_list(chat_id, db.get_saved_markets(chat_id), "⭐", empty_msg="No saved markets yet — tap ⭐ Save on any market card.")


def _ending_menu(chat_id: int) -> None:
    keyboard = {
        "inline_keyboard": [
            [{"text": "🔴 <12 Hours", "callback_data": "ending:12h"}],
            [{"text": "🟠 <24 Hours", "callback_data": "ending:24h"}],
            [{"text": "🟡 <3 Days", "callback_data": "ending:3d"}],
            [{"text": "🟢 <1 Week", "callback_data": "ending:week"}],
            [{"text": "🔵 <1 Month", "callback_data": "ending:month"}],
            [{"text": "⚪ Longer Than 1 Month", "callback_data": "ending:longer"}],
            [{"text": "📅 Pick a Specific Month", "callback_data": "endingmonthmenu:"}],
        ]
    }
    telegram_client.send_message(chat_id, "⏳ *Ending Soon* — pick a window:", reply_markup=keyboard)


def _send_month_picker(chat_id: int) -> None:
    now = datetime.now(timezone.utc)
    buttons = []
    y, m = now.year, now.month
    for _ in range(6):
        buttons.append([{"text": f"{calendar.month_name[m]} {y}", "callback_data": f"endingmonth:{y}-{m}"}])
        m += 1
        if m > 12:
            m = 1
            y += 1
    telegram_client.send_message(chat_id, "📅 *Pick a month:*", reply_markup={"inline_keyboard": buttons})


def _live(chat_id: int) -> None:
    feed = db.get_live_feed(limit=15)
    if not feed:
        telegram_client.send_message(chat_id, "No recent activity logged yet.")
        return
    lines = ["📡 *Live Updates* — recent activity below your push threshold:\n"]
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
    boost_lines = "\n".join(f"- {b['keyword_or_category']}" for b in boosts) or "None set."
    result = db.get_client().table("markets").select("market_id", count="exact").execute()
    threshold = db.get_push_threshold(chat_id)
    text = (
        "⚙️ *Settings*\n\n"
        f"Tracking {result.count} active markets platform-wide.\n\n"
        f"*Your priority boosts:*\n{boost_lines}\n"
        "Tap ✕ below to remove one, or tap a category to add it — no typing needed. "
        "(A custom keyword still needs /add <word> since it can't be listed as a button.)\n\n"
        f"*Push threshold:* {int(threshold * 100)}/100\n"
        "Only markets scoring at or above this push an instant notification — "
        "everything else is still logged in 📡 Live Updates.\n"
        "Tap a preset below."
    )

    keyboard_rows = [
        [
            {"text": "20", "callback_data": "threshold:20"},
            {"text": "30", "callback_data": "threshold:30"},
            {"text": "40", "callback_data": "threshold:40"},
        ],
        [
            {"text": "50", "callback_data": "threshold:50"},
            {"text": "60", "callback_data": "threshold:60"},
            {"text": "70", "callback_data": "threshold:70"},
        ],
        [
            {"text": "80", "callback_data": "threshold:80"},
            {"text": "85 (default)", "callback_data": "threshold:85"},
            {"text": "95", "callback_data": "threshold:95"},
        ],
    ]

    # One "✕ remove" button per existing boost — truncated defensively so
    # callback_data can never exceed Telegram's 64-byte limit (same bug
    # class as the market_id/short_id issue fixed earlier).
    for b in boosts:
        term = b["keyword_or_category"]
        keyboard_rows.append([{"text": f"✕ Remove {term}", "callback_data": f"removeboost:{term[:45]}"}])

    # Add-by-category, two per row, only for categories not already boosted.
    existing_terms = {b["keyword_or_category"] for b in boosts}
    categories = [c for c in scoring.CATEGORY_KEYWORDS if c not in existing_terms]
    for i in range(0, len(categories), 2):
        row = [{"text": f"➕ {c}", "callback_data": f"addboost:{c}"} for c in categories[i:i + 2]]
        keyboard_rows.append(row)

    telegram_client.send_message(chat_id, text, reply_markup={"inline_keyboard": keyboard_rows})


def _set_threshold(chat_id: int, arg: str) -> None:
    if not arg:
        current = db.get_push_threshold(chat_id)
        telegram_client.send_message(
            chat_id,
            f"Current push threshold: {int(current * 100)}/100.\nUsage: /threshold <0-100>",
        )
        return
    try:
        value = float(arg)
    except ValueError:
        telegram_client.send_message(chat_id, "That doesn't look like a number. Usage: /threshold <0-100>")
        return
    if not (0 <= value <= 100):
        telegram_client.send_message(chat_id, "Enter a number between 0 and 100.")
        return
    db.set_push_threshold(chat_id, value / 100)
    telegram_client.send_message(
        chat_id,
        f"Push threshold set to {value:.0f}/100. Markets scoring at or above this will push instantly; "
        "everything else still logs to 📡 Live Updates.",
    )


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
    _add_boost(chat_id, term)
    telegram_client.send_message(chat_id, f"Added boost: {term}")


def _remove(chat_id: int, term: str) -> None:
    _remove_boost(chat_id, term)
    telegram_client.send_message(chat_id, f"Removed boost (if it existed): {term}")


def _add_boost(chat_id: int, term: str) -> None:
    db.get_client().table("priority_boosts").insert(
        {"chat_id": chat_id, "keyword_or_category": term, "weight": 1.5}
    ).execute()


def _remove_boost(chat_id: int, term: str) -> None:
    db.get_client().table("priority_boosts").delete().eq("chat_id", chat_id).eq(
        "keyword_or_category", term
    ).execute()


def _stats(chat_id: int) -> None:
    result = db.get_client().table("markets").select("market_id", count="exact").execute()
    telegram_client.send_message(chat_id, f"Tracking {result.count} active markets across the whole platform.")
