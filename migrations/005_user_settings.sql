-- Run this in the Supabase SQL editor after 004_alert_channel.sql.
-- Lets each chat customize their own push-notification cutoff instead of
-- the fixed 85/100 default in shared/config.py.

create table if not exists user_settings (
  chat_id bigint primary key,
  push_threshold numeric not null default 0.85,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table user_settings enable row level security;
NOTIFY pgrst, 'reload schema';
