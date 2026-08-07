import os

from dotenv import load_dotenv

load_dotenv()

# --- Required ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# --- Optional ---
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
DEFAULT_CHAT_ID = os.environ.get("DEFAULT_CHAT_ID")  # fallback alert recipient
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")  # AI summaries are skipped if unset
GAMMA_API_BASE = os.environ.get("GAMMA_API_BASE", "https://gamma-api.polymarket.com")

# --- Tiering (days remaining -> tier) ---
TIER_THRESHOLDS_DAYS = {
    "critical": 1,
    "hot": 3,
    "active": 7,
    "warm": 14,
    # anything beyond 14 days is "background"
}

# --- Alert thresholds — starting defaults, tune after a week or two of real data ---
PRICE_MOVE_THRESHOLD_POINTS = 8.0        # alert if |Δ price| >= this many percentage points
VOLUME_SPIKE_MULTIPLIER = 3.0            # alert if interval volume >= this x trailing avg
SNAPSHOT_NOISE_THRESHOLD_POINTS = 1.5    # persist a price_snapshot for non-hot/critical tiers only above this delta

# Raw opportunity_score (0-1) cutoff for pushing an instant alert on a
# brand-new market. This is a fixed cutoff, not a true percentile — a
# percentile-based cutoff needs a rolling score distribution, which is a
# reasonable v1.1 upgrade once you have real data to compute one from.
NEW_MARKET_ALERT_THRESHOLD = 0.7

ALERT_COOLDOWN_MINUTES = {
    "critical": 15,
    "hot": 30,
    "active": 45,
    "warm": 60,
    "background": 120,
}
