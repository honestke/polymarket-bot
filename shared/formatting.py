"""
Shared formatting for how a market gets shown in Telegram — used by
scan.py (live alerts), digest.py (ranked digest), and bot/commands.py
(command responses), so every surface looks the same.
"""
from shared import scoring
import hashlib

# Legacy Telegram Markdown (not MarkdownV2) only treats these as special.
# Market questions are arbitrary text from Polymarket and can contain any
# of them — an unescaped one causes Telegram to reject the whole message
# with a 400 error, silently dropping the alert. Escape defensively.
_MARKDOWN_SPECIAL = ("_", "*", "`", "[")


def escape_markdown(text: str) -> str:
    text = text or ""
    for ch in _MARKDOWN_SPECIAL:
        text = text.replace(ch, f"\\{ch}")
    return text


def market_url(slug: str | None) -> str:
    """Deep link using the market's associated EVENT slug (see
    shared/polymarket_client.py normalize() — an earlier version used the
    market's own slug instead of the event's, which is a different value
    and was landing on blank/wrong pages). Still worth spot-checking a
    few real links, since this hasn't been verified against a live
    response from this environment."""
    if not slug:
        return "https://polymarket.com"
    return f"https://polymarket.com/event/{slug}"


def short_id(market_id: str) -> str:
    """Telegram's callback_data has a strict 64-byte limit. Polymarket's
    market_id is a 66-character 0x-prefixed hex string, which alone
    already exceeds that once combined with any prefix — every button
    press was silently failing before this existed. A 10-char hash is
    comfortably under the limit; collisions are a non-issue at this scale."""
    return hashlib.sha256(market_id.encode()).hexdigest()[:10]


def format_probability(price_yes: float | None) -> str:
    return f"{price_yes:.0%}" if price_yes is not None else "—"


def format_volume(volume: float | None) -> str:
    if volume is None:
        return "—"
    if volume >= 1_000_000:
        return f"${volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"${volume / 1_000:.0f}K"
    return f"${volume:.0f}"


def format_time_remaining(end_date_iso: str | None) -> str:
    days = scoring.time_remaining_days(end_date_iso)
    if days is None:
        return "Unknown"
    if days < 0:
        return "Ended"
    if days < 1:
        return f"{max(days * 24, 0):.0f} Hours"
    return f"{days:.0f} Days"


def risk_label(risk_score: float | None) -> str:
    if risk_score is None:
        return "Unknown"
    if risk_score < 0.33:
        return "Low"
    if risk_score < 0.66:
        return "Medium"
    return "High"


def opportunity_display(score: float | None) -> str:
    return f"{round(score * 100)}/100" if score is not None else "—"


def format_market_card(market: dict, icon: str = "🏆", highlight: str | None = None) -> str:
    """`market` is a row from the `markets` table (or an equivalent dict
    with the same keys) — works for scan.py's in-memory rows and for rows
    pulled back from Supabase alike."""
    title = escape_markdown(market.get("question") or "Unknown market")
    lines = [f"{icon} *{title}*", ""]
    if highlight:
        lines.append(f"_{escape_markdown(highlight)}_")
        lines.append("")
    group_size = market.get("group_size")
    if group_size and group_size > 1:
        lines.append(f"🔀 One of {group_size} candidates in this event")
        lines.append("")
    lines.extend([
        f"📊 Opportunity: {opportunity_display(market.get('opportunity_score'))}",
        f"📈 Market: {format_probability(market.get('last_price_yes'))}",
        f"⏳ Ends: {format_time_remaining(market.get('end_date'))}",
        f"💰 Volume: {format_volume(market.get('last_volume_24h'))}",
        f"⚠️ Risk: {risk_label(market.get('risk_score'))}",
    ])
    return "\n".join(lines)


def format_market_details(market: dict, ai_summary: dict | None, snapshots: list[dict]) -> str:
    """The actual 'more than the basic card' content for View Details:
    confidence/reliability scores that aren't on the base card, any AI
    summary that's been generated for this market, and recent price
    history if any snapshots exist. Markets that have never triggered a
    price/volume alert will have neither an AI summary nor snapshots —
    in that case this still adds the two score lines, just nothing more,
    since there genuinely isn't more data to show."""
    lines = [format_market_card(market, icon="📈"), ""]
    lines.append(f"🎯 Confidence: {opportunity_display(market.get('confidence_score'))}")
    lines.append(f"📚 Source reliability: {opportunity_display(market.get('source_reliability_score'))}")

    if ai_summary and ai_summary.get("summary_text"):
        lines.append("")
        lines.append(f"🤖 _{escape_markdown(ai_summary['summary_text'])}_")

    if snapshots:
        lines.append("")
        lines.append("📉 *Recent price history:*")
        for snap in snapshots:
            price = format_probability(snap.get("price_yes"))
            when = (snap.get("captured_at") or "")[:16].replace("T", " ")
            lines.append(f"  {when} — {price}")

    return "\n".join(lines)


def market_keyboard(market_row_short_id: str, slug: str | None, category: str | None = None) -> dict:
    """Inline keyboard for a market card. 'Open Market' is a plain URL
    button — it works with zero backend involvement, no webhook needed.
    'View Details' and 'Save' send a callback_query back to the bot,
    which only gets answered if the Telegram webhook (Render service) is
    deployed and running — see services/bot/app.py.

    Takes short_id (see short_id() above), NOT the raw market_id — the
    real market_id overflows Telegram's 64-byte callback_data limit.

    `category`, when given, adds a one-tap "Boost this category" row —
    lets someone add a watchlist boost directly from a card they're
    looking at, instead of only via Settings."""
    rows = [
        [{"text": "🔗 Open Market", "url": market_url(slug)}],
        [
            {"text": "📈 View Details", "callback_data": f"details:{market_row_short_id}"},
            {"text": "⭐ Save", "callback_data": f"save:{market_row_short_id}"},
        ],
    ]
    if category:
        rows.append([{"text": f"📌 Boost {category}", "callback_data": f"cardboost:{category}"}])
    return {"inline_keyboard": rows}


# Persistent reply keyboard shown after /start — stays visible under the
# text box until replaced. Button presses arrive as ordinary text
# messages with this exact label, routed in services/bot/commands.py.
MAIN_MENU_KEYBOARD = {
    "keyboard": [
        ["🏆 Best Opportunities", "💰 By Volume"],
        ["🔥 Trending", "🆕 New Markets"],
        ["⏳ Ending Soon", "📡 Live Updates"],
        ["📂 Categories", "⭐ Saved"],
        ["🔍 Search", "📊 Stats"],
        ["⚙️ Settings", "❓ Help"],
    ],
    "resize_keyboard": True,
}

_FEED_ICONS = {
    "price_move": "📈",
    "volume_spike": "🔥",
    "tier_change": "⏰",
    "new_market": "🆕",
}


def format_feed_line(alert_row: dict) -> str:
    """One compact line per event for /live — a scrollable feed, not a
    stack of full cards, since a feed is meant to be skimmed."""
    market = alert_row.get("markets") or {}
    icon = _FEED_ICONS.get(alert_row.get("alert_type"), "•")
    question = escape_markdown(market.get("question") or "Unknown market")
    score = opportunity_display(market.get("opportunity_score"))
    return f"{icon} {question} — score {score}"
