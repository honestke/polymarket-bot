-- Polymarket Intelligence Bot — V1 schema
-- Run this in the Supabase SQL editor once, on project creation.

create table if not exists markets (
  market_id text primary key,               -- Polymarket conditionId
  question text not null,
  slug text,
  category text,                             -- auto-categorized, for organization only — never filters monitoring
  status text not null default 'active',     -- active | resolved | paused
  created_on_polymarket_at timestamptz,      -- best-effort; Gamma API may not reliably expose this
  first_discovered_at timestamptz not null default now(),
  discovery_latency_seconds integer,         -- core mission KPI; null if creation timestamp unavailable
  end_date timestamptz,
  current_tier text,                         -- background | warm | active | hot | critical
  last_price_yes numeric,
  last_volume_24h numeric,
  last_liquidity numeric,
  last_polled_at timestamptz,
  risk_score numeric,
  confidence_score numeric,
  source_reliability_score numeric,
  opportunity_score numeric,                 -- heuristic "worth a look" ranking — NOT a probability/edge estimate in V1
  updated_at timestamptz not null default now()
);

create index if not exists idx_markets_status on markets(status);
create index if not exists idx_markets_tier on markets(current_tier);
create index if not exists idx_markets_opportunity on markets(opportunity_score desc);

-- Watchlist entries now only weight ranking/alert priority — they never
-- exclude a market from being monitored. Renamed from "watchlist" to make
-- that non-filtering role explicit in the schema itself.
create table if not exists priority_boosts (
  id bigserial primary key,
  chat_id bigint not null,
  keyword_or_category text not null,
  weight numeric not null default 1.5,       -- multiplies opportunity_score for matching markets
  created_at timestamptz not null default now()
);

-- Only written for Hot/Critical-tier markets, or when a market moves more
-- than the noise threshold — see shared/config.py. This keeps storage
-- bounded even while tracking every market on the platform.
create table if not exists price_snapshots (
  id bigserial primary key,
  market_id text references markets(market_id) on delete cascade,
  price_yes numeric,
  volume_24h numeric,
  captured_at timestamptz not null default now()
);
create index if not exists idx_snapshots_market_time on price_snapshots(market_id, captured_at desc);

create table if not exists alerts (
  id bigserial primary key,
  market_id text references markets(market_id) on delete cascade,
  chat_id bigint not null,
  alert_type text not null,                  -- new_market | price_move | volume_spike | tier_change | digest
  triggered_value numeric,
  payload jsonb,
  sent_at timestamptz not null default now()
);

create table if not exists alert_cooldowns (
  dedup_key text primary key,                -- market_id || ':' || alert_type
  last_sent_at timestamptz,
  last_alerted_value numeric,
  cooldown_until timestamptz
);

create table if not exists ai_analysis (
  id bigserial primary key,
  market_id text references markets(market_id) on delete cascade,
  trigger_alert_id bigint,
  model_used text,
  prompt_tokens integer,
  completion_tokens integer,
  summary_text text,
  generated_at timestamptz not null default now()
);

-- Version 3 — created now so the table exists when the learning loop is built later
create table if not exists resolutions (
  market_id text primary key references markets(market_id),
  resolved_outcome text,
  resolved_at timestamptz,
  final_ai_probability numeric,
  calibration_error numeric
);
