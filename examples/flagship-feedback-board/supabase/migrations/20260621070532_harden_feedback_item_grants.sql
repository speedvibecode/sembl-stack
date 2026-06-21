revoke all on public.feedback_items from anon;
revoke delete on public.feedback_items from authenticated;
grant usage on schema public to authenticated;
grant select, insert, update on public.feedback_items to authenticated;
