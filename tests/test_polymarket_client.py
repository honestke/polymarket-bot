import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.polymarket_client import _parse_json_field, normalize


def test_parse_json_field_handles_stringified_array():
    assert _parse_json_field('["0.62", "0.38"]') == ["0.62", "0.38"]


def test_parse_json_field_handles_real_array():
    assert _parse_json_field(["0.62", "0.38"]) == ["0.62", "0.38"]


def test_parse_json_field_handles_garbage():
    assert _parse_json_field("not json") == []
    assert _parse_json_field(None) == []


def test_normalize_extracts_price_from_stringified_outcome_prices():
    """The actual bug: Gamma returns outcomePrices as a JSON string, not
    an array. Indexing into the raw string grabbed '[' instead of a price
    and silently produced None — this is why every card showed a blank
    'Market: —' instead of a real percentage."""
    raw = {
        "conditionId": "0x123",
        "question": "Will X happen?",
        "outcomePrices": '["0.62", "0.38"]',
        "tags": '["Politics", "Elections"]',
    }
    result = normalize(raw)
    assert result["price_yes"] == 0.62
    assert result["tags"] == ["Politics", "Elections"]


def test_fetch_all_active_markets_dedupes_across_both_passes(monkeypatch):
    """The two-pass fetch (high-volume-first + low-volume-first) can
    return the same market in both passes if the platform has fewer than
    ~4,200 active markets. Must not produce duplicates downstream —
    duplicate market_id in the same DB batch previously crashed the
    entire scan (see the ON CONFLICT bug fixed earlier)."""
    import shared.polymarket_client as pmc

    call_count = {"n": 0}

    def fake_fetch_sorted(ascending: bool):
        call_count["n"] += 1
        # Overlapping market_id on purpose, to verify dedup.
        if ascending:
            return [{"market_id": "0xAAA", "question": "A"}, {"market_id": "0xCCC", "question": "C"}]
        return [{"market_id": "0xAAA", "question": "A"}, {"market_id": "0xBBB", "question": "B"}]

    monkeypatch.setattr(pmc, "_fetch_sorted", fake_fetch_sorted)
    result = pmc.fetch_all_active_markets()

    assert call_count["n"] == 2  # both directions actually got called
    ids = {m["market_id"] for m in result}
    assert ids == {"0xAAA", "0xBBB", "0xCCC"}
    assert len(result) == 3  # not 4 — 0xAAA deduplicated


def test_normalize_extracts_group_size_from_nested_event_markets():
    raw = {
        "conditionId": "0xHarryKane",
        "question": "Will Harry Kane win the 2026 Ballon d'Or?",
        "outcomePrices": '["0.58", "0.42"]',
        "events": [{"slug": "ballon-dor-winner-2026", "markets": [{}] * 23}],
    }
    result = normalize(raw)
    assert result["group_size"] == 23


def test_normalize_group_size_none_when_not_determinable():
    raw = {
        "conditionId": "0xStandalone",
        "question": "Will it rain tomorrow?",
        "outcomePrices": '["0.30", "0.70"]',
        "events": [{"slug": "will-it-rain"}],  # no nested "markets" list
    }
    result = normalize(raw)
    assert result["group_size"] is None
