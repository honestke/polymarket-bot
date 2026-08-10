"""
Periodic digest — runs hourly by default (.github/workflows/digest.yml).

Sends the top-ranked markets as individual rich cards (same format as the
live alerts), each with its own "Open Market" / "View Details" / "Save"
buttons — not one consolidated block of text. That means N messages per
digest run instead of 1, so `limit` is intentionally conservative.
"""
from shared import config, db, formatting, telegram_client

DEFAULT_LIMIT = 5


def run(limit: int = DEFAULT_LIMIT) -> None:
    top = db.get_top_opportunities(limit=limit)
    if not top:
        print("No markets tracked yet — has the scan job run?")
        return

    telegram_client.send_message(config.DEFAULT_CHAT_ID, f"📊 *Top {len(top)} opportunities right now*")
    for market in top:
        text = formatting.format_market_card(market, icon="🏆")
        keyboard = formatting.market_keyboard(market["short_id"], market.get("slug"), market.get("category"))
        telegram_client.send_message(config.DEFAULT_CHAT_ID, text, reply_markup=keyboard)


if __name__ == "__main__":
    run()
