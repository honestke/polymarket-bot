import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import formatting


def test_escape_markdown_neutralizes_special_chars():
    assert formatting.escape_markdown("Will GPT-4_5 beat *everyone*?") == "Will GPT-4\\_5 beat \\*everyone\\*?"


def test_market_url_uses_slug():
    assert formatting.market_url("will-x-happen") == "https://polymarket.com/event/will-x-happen"


def test_market_url_falls_back_without_slug():
    assert formatting.market_url(None) == "https://polymarket.com"


def test_format_volume_buckets():
    assert formatting.format_volume(1_200_000) == "$1.2M"
    assert formatting.format_volume(15_000) == "$15K"
    assert formatting.format_volume(500) == "$500"
    assert formatting.format_volume(None) == "—"


def test_risk_label_buckets():
    assert formatting.risk_label(0.1) == "Low"
    assert formatting.risk_label(0.5) == "Medium"
    assert formatting.risk_label(0.9) == "High"
    assert formatting.risk_label(None) == "Unknown"


def test_opportunity_display_scales_to_100():
    assert formatting.opportunity_display(0.65) == "65/100"
    assert formatting.opportunity_display(None) == "—"


def test_format_market_card_includes_all_fields():
    market = {
        "question": "Will OpenAI release GPT-6 before Dec. 31?",
        "opportunity_score": 0.94,
        "last_price_yes": 0.68,
        "end_date": None,
        "last_volume_24h": 1_200_000,
        "risk_score": 0.1,
    }
    card = formatting.format_market_card(market, icon="🏆")
    assert "94/100" in card
    assert "68%" in card
    assert "$1.2M" in card
    assert "Low" in card


def test_short_id_is_deterministic():
    market_id = "0x" + "a" * 64  # Polymarket's real format: 0x + 64 hex chars
    assert formatting.short_id(market_id) == formatting.short_id(market_id)


def test_market_keyboard_callback_data_fits_telegram_limit():
    """The actual bug: Telegram silently rejects any message whose
    callback_data exceeds 64 bytes. Polymarket's market_id (66 chars) blew
    past that on its own — every button on every card failed to send
    until short_id existed. This test exists so that regression can never
    be silent again."""
    market_id = "0x" + "f" * 64
    sid = formatting.short_id(market_id)
    keyboard = formatting.market_keyboard(sid, "some-slug")
    for row in keyboard["inline_keyboard"]:
        for button in row:
            if "callback_data" in button:
                assert len(button["callback_data"].encode("utf-8")) <= 64


def test_format_feed_line_includes_score_and_icon():
    row = {
        "alert_type": "volume_spike",
        "markets": {"question": "Will X happen?", "opportunity_score": 0.32},
    }
    line = formatting.format_feed_line(row)
    assert "🔥" in line
    assert "32/100" in line
    assert "Will X happen?" in line
