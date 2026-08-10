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
