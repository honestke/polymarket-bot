"""
V1 AI summarization — called only from scan.py, and only after a
price_move or volume_spike alert has already fired (see
shared/alert_engine.py). Never runs on a routine poll, and never runs
per-market just because a market exists — see the AI cost optimization
section of the architecture doc.

Uses only the structured market-data delta as context; no external
research yet (that's V2), so this produces a plain description of what
happened, not a probability estimate or trade recommendation.
"""
from anthropic import Anthropic

from shared import config, db, telegram_client

MODEL = "claude-haiku-4-5-20251001"

_client = Anthropic(api_key=config.ANTHROPIC_API_KEY) if config.ANTHROPIC_API_KEY else None


def summarize_market(market_id: str, question: str, prev_price: float | None,
                      new_price: float | None, tier: str) -> None:
    if _client is None:
        return  # AI summaries are optional — scan.py works without a key configured

    prompt = (
        f"Market: {question}\n"
        f"Price moved from {prev_price} to {new_price} (tier: {tier}).\n\n"
        "In 1-2 plain sentences, describe what happened. Do not speculate "
        "about why it happened, and do not give a probability estimate or "
        "a trade recommendation — just describe the observed change."
    )

    response = _client.messages.create(
        model=MODEL,
        max_tokens=120,
        messages=[{"role": "user", "content": prompt}],
    )
    summary_text = "".join(block.text for block in response.content if block.type == "text")

    db.insert_ai_analysis({
        "market_id": market_id,
        "model_used": MODEL,
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
        "summary_text": summary_text,
    })

    telegram_client.send_message(config.DEFAULT_CHAT_ID, f"🤖 {summary_text}")
