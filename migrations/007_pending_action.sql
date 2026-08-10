-- Run this in the Supabase SQL editor after 006_group_size.sql.
--
-- Fixes Search: the previous implementation relied on Telegram correctly
-- threading the user's reply back to the prompt message
-- (reply_to_message matching), which isn't reliable across all Telegram
-- clients. pending_action tracks "this chat is waiting for search input"
-- directly, so any next message is captured correctly regardless of
-- reply-threading behavior.

alter table user_settings add column if not exists pending_action text;
NOTIFY pgrst, 'reload schema';
