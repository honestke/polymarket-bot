-- Run this in the Supabase SQL editor after 001_init.sql.
-- Adds bookmarking support for the "⭐ Save" button on market cards.

create table if not exists saved_markets (
  chat_id bigint not null,
  market_id text not null references markets(market_id) on delete cascade,
  saved_at timestamptz not null default now(),
  primary key (chat_id, market_id)
);

alter table saved_markets enable row level security;
