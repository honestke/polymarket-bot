"""
Periodic digest — runs hourly by default (.github/workflows/digest.yml).

This is how "highest-priority opportunities across all markets" reaches
you without becoming a firehose: instant Telegram pushes from scan.py are
reserved for genuinely notable events (new markets above the opportunity
threshold, price moves, volume spikes). Everything else — the full ranked
view across every tracked market — surfaces here instead.
"""
from shared import config, db, telegram_client


def run(limit: int = 10) -> None:
    top = db.get_top_opportunities(limit=limit)
    if not top:
        print("No markets tracked yet — has the scan job run?")
        return

    lines = ["📊 *Top opportunities right now*\n"]
    for i, m in enumerate(top, start=1):
        lines.append(
            f"{i}. {m['question']}\n"
            f"   {m['category']}  |  tier: {m['current_tier']}  |  "
            f"score: {m['opportunity_score']}  |  risk: {m['risk_score']}"
        )
    telegram_client.send_message(config.DEFAULT_CHAT_ID, "\n".join(lines))


if __name__ == "__main__":
    run()
