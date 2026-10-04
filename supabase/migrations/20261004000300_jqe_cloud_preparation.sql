-- Preparation only: no runtime publisher or dashboard fallback is activated.
-- Owner identity comes from auth.users; never expose service_role to a browser.
create table if not exists public.jqe_monitor_snapshots (
  owner_id uuid not null references auth.users(id) on delete cascade,
  resource text not null check (resource in ('journal', 'market/candles', 'execution', 'system')),
  resource_key text not null default '',
  provider text not null check (provider = 'weltrade'),
  observed_at timestamptz not null,
  received_at timestamptz not null default now(),
  payload jsonb not null check (jsonb_typeof(payload) = 'object'),
  primary key (owner_id, resource, resource_key)
);
alter table public.jqe_monitor_snapshots enable row level security;
revoke all on public.jqe_monitor_snapshots from anon, authenticated;
grant select on public.jqe_monitor_snapshots to authenticated;
grant all on public.jqe_monitor_snapshots to service_role;
create policy jqe_owner_reads_snapshots on public.jqe_monitor_snapshots
  for select to authenticated using (owner_id = (select auth.uid()));

-- Shared claims for a future cloud scheduler. Only trusted server code writes.
create table if not exists public.jqe_channel_post_claims (
  slot_key text primary key,
  claimed_at timestamptz not null default now(),
  status text not null default 'CLAIMED' check (status in ('CLAIMED', 'SENT', 'FAILED')),
  telegram_message_id bigint
);
alter table public.jqe_channel_post_claims enable row level security;
revoke all on public.jqe_channel_post_claims from anon, authenticated;
grant all on public.jqe_channel_post_claims to service_role;
