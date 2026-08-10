-- Run this in the Supabase SQL editor after 003_short_id.sql.
--
-- Splits alerts into two channels: 'push' (sent to Telegram immediately)
-- and 'feed' (logged for the /live command, never pushed). Previously
-- every threshold crossing was pushed regardless of how low-value the
-- market was — this is what caused low-scoring markets with routine
-- volume blips to spam instant notifications.

alter table alerts add column if not exists channel text not null default 'feed';
create index if not exists idx_alerts_channel_time on alerts(channel, sent_at desc);
