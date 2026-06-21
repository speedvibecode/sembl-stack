create table if not exists public.feedback_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 3 and 120),
  body text not null check (char_length(body) between 10 and 2000),
  status text not null default 'open' check (status in ('open', 'planned', 'closed')),
  priority text not null default 'medium' check (priority in ('low', 'medium', 'high')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists feedback_items_user_created_idx
  on public.feedback_items (user_id, created_at desc);

alter table public.feedback_items enable row level security;

revoke all on public.feedback_items from anon;
revoke delete on public.feedback_items from authenticated;
grant usage on schema public to authenticated;
grant select, insert, update on public.feedback_items to authenticated;

drop policy if exists "feedback_items_select_own" on public.feedback_items;
create policy "feedback_items_select_own"
  on public.feedback_items
  for select
  to authenticated
  using ((select auth.uid()) = user_id);

drop policy if exists "feedback_items_insert_own" on public.feedback_items;
create policy "feedback_items_insert_own"
  on public.feedback_items
  for insert
  to authenticated
  with check ((select auth.uid()) = user_id);

drop policy if exists "feedback_items_update_own" on public.feedback_items;
create policy "feedback_items_update_own"
  on public.feedback_items
  for update
  to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
