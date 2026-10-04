create extension if not exists pgcrypto;

create table if not exists public.jqe_profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  role text not null default 'user' check (role in ('user', 'admin')),
  onboarding_path text not null default 'existing_account'
    check (onboarding_path in ('referral', 'existing_account')),
  access_override text not null default 'NONE'
    check (access_override in ('NONE', 'ACTIVE', 'SUSPENDED')),
  access_override_expires_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.jqe_referral_applications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  status text not null default 'PENDING' check (status in ('PENDING', 'APPROVED', 'REJECTED')),
  note text,
  submitted_at timestamptz not null default now(),
  reviewed_at timestamptz,
  reviewed_by uuid references auth.users(id)
);

create table if not exists public.jqe_trial_activations (
  user_id uuid primary key references auth.users(id) on delete cascade,
  activated_at timestamptz not null,
  expires_at timestamptz not null,
  constraint jqe_trial_exactly_24h check (expires_at = activated_at + interval '24 hours')
);

create table if not exists public.jqe_usage_counters (
  user_id uuid not null references auth.users(id) on delete cascade,
  feature text not null,
  utc_day date not null,
  used integer not null default 0 check (used >= 0),
  primary key (user_id, feature, utc_day)
);

create table if not exists public.jqe_feature_limits (
  plan_key text not null,
  feature text not null,
  daily_limit integer not null check (daily_limit >= 0),
  primary key (plan_key, feature)
);

create table if not exists public.jqe_plan_catalog (
  plan_key text primary key,
  name text not null,
  price numeric(12, 2),
  currency text,
  status text not null default 'NOT_CONFIGURED'
    check (status in ('NOT_CONFIGURED', 'AVAILABLE', 'DISABLED')),
  feature_list text[] not null default '{}',
  updated_at timestamptz not null default now()
);

insert into public.jqe_plan_catalog (plan_key, name, price, currency, status, feature_list)
values
  ('trial', '24-hour trial', null, null, 'NOT_CONFIGURED', array['workspace_read', 'research_read', 'ai_chat']),
  ('subscription', 'JQE subscription', null, null, 'NOT_CONFIGURED', array['workspace_read', 'research_read', 'ai_chat'])
on conflict (plan_key) do nothing;

insert into public.jqe_feature_limits (plan_key, feature, daily_limit)
values ('trial', 'ai_chat', 5)
on conflict (plan_key, feature) do nothing;

alter table public.jqe_profiles enable row level security;
alter table public.jqe_referral_applications enable row level security;
alter table public.jqe_trial_activations enable row level security;
alter table public.jqe_usage_counters enable row level security;
alter table public.jqe_feature_limits enable row level security;
alter table public.jqe_plan_catalog enable row level security;

grant select on public.jqe_profiles, public.jqe_referral_applications,
  public.jqe_trial_activations, public.jqe_usage_counters to authenticated;
grant select on public.jqe_plan_catalog to authenticated;
revoke insert, update, delete on public.jqe_profiles, public.jqe_referral_applications,
  public.jqe_trial_activations, public.jqe_usage_counters, public.jqe_feature_limits,
  public.jqe_plan_catalog from anon, authenticated;

create or replace function public.jqe_new_profile()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  selected_path text := coalesce(new.raw_user_meta_data ->> 'onboarding_path', 'existing_account');
begin
  if selected_path not in ('referral', 'existing_account') then
    selected_path := 'existing_account';
  end if;
  insert into public.jqe_profiles (id, email, onboarding_path)
  values (new.id, coalesce(new.email, ''), selected_path)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists jqe_auth_user_created on auth.users;
create trigger jqe_auth_user_created
after insert on auth.users
for each row execute function public.jqe_new_profile();

insert into public.jqe_profiles (id, email, onboarding_path)
select
  u.id,
  coalesce(u.email, ''),
  case
    when u.raw_user_meta_data ->> 'onboarding_path' in ('referral', 'existing_account')
      then u.raw_user_meta_data ->> 'onboarding_path'
    else 'existing_account'
  end
from auth.users u
on conflict (id) do nothing;

create or replace function public.jqe_is_admin()
returns boolean
language sql
stable
security definer
set search_path = public, auth
as $$
  select exists (
    select 1 from public.jqe_profiles
    where id = auth.uid() and role = 'admin'
  );
$$;

create policy jqe_profiles_read_self_or_admin on public.jqe_profiles
for select to authenticated using (id = auth.uid() or public.jqe_is_admin());
create policy jqe_referrals_read_self_or_admin on public.jqe_referral_applications
for select to authenticated using (user_id = auth.uid() or public.jqe_is_admin());
create policy jqe_trials_read_self_or_admin on public.jqe_trial_activations
for select to authenticated using (user_id = auth.uid() or public.jqe_is_admin());
create policy jqe_usage_read_self on public.jqe_usage_counters
for select to authenticated using (user_id = auth.uid());
create policy jqe_plan_catalog_read on public.jqe_plan_catalog
for select to authenticated using (true);

create or replace function public.jqe_access_snapshot()
returns jsonb
language plpgsql
stable
security definer
set search_path = public, auth
as $$
declare
  uid uuid := auth.uid();
  profile public.jqe_profiles%rowtype;
  trial public.jqe_trial_activations%rowtype;
  referral_state text := 'NOT_SUBMITTED';
  allowed boolean := false;
  current_state text := 'ONBOARDING';
  features text[] := '{}';
  ai_limit integer;
  ai_used integer := 0;
  plan_json jsonb;
begin
  if uid is null then raise exception 'AUTHENTICATION_REQUIRED' using errcode = '28000'; end if;
  select * into profile from public.jqe_profiles where id = uid;
  if not found then raise exception 'PROFILE_UNAVAILABLE' using errcode = 'P0002'; end if;
  select * into trial from public.jqe_trial_activations where user_id = uid;
  select status into referral_state from public.jqe_referral_applications where user_id = uid;
  referral_state := coalesce(referral_state, 'NOT_SUBMITTED');

  if profile.access_override = 'SUSPENDED' then
    current_state := 'SUSPENDED';
  elsif profile.access_override = 'ACTIVE'
    and (profile.access_override_expires_at is null or profile.access_override_expires_at > now()) then
    current_state := 'ADMIN_GRANTED'; allowed := true;
    features := array['workspace_read', 'research_read', 'ai_chat'];
  elsif trial.user_id is not null and trial.expires_at > now() then
    current_state := 'TRIAL_ACTIVE'; allowed := true;
    features := array['workspace_read', 'research_read', 'ai_chat'];
  elsif trial.user_id is not null then
    current_state := 'TRIAL_EXPIRED';
  elsif referral_state = 'PENDING' then
    current_state := 'REFERRAL_PENDING';
  elsif referral_state = 'APPROVED' then
    current_state := 'REFERRAL_APPROVED';
  elsif referral_state = 'REJECTED' then
    current_state := 'REFERRAL_REJECTED';
  end if;

  select daily_limit into ai_limit from public.jqe_feature_limits
  where plan_key = case when current_state = 'ADMIN_GRANTED' then 'admin' else 'trial' end
    and feature = 'ai_chat';
  ai_limit := coalesce(ai_limit, 5);
  select used into ai_used from public.jqe_usage_counters
  where user_id = uid and feature = 'ai_chat' and utc_day = (now() at time zone 'utc')::date;
  select coalesce(jsonb_agg(jsonb_build_object(
    'key', plan_key, 'name', name, 'price', price, 'currency', currency, 'status', status
  ) order by plan_key), '[]'::jsonb) into plan_json from public.jqe_plan_catalog;

  return jsonb_build_object(
    'authenticated', true,
    'role', profile.role,
    'onboarding_path', profile.onboarding_path,
    'access_status', current_state,
    'access_granted', allowed,
    'trial_available', profile.onboarding_path = 'existing_account' and trial.user_id is null and profile.access_override = 'NONE',
    'trial_activated_at', trial.activated_at,
    'trial_expires_at', trial.expires_at,
    'referral_status', referral_state,
    'feature_access', features,
    'ai_daily_limit', ai_limit,
    'ai_used_today', coalesce(ai_used, 0),
    'backend_state', 'UNAVAILABLE',
    'plans', plan_json
  );
end;
$$;

create or replace function public.jqe_activate_existing_trial()
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  uid uuid := auth.uid();
  selected_path text;
  started timestamptz := now();
  ended timestamptz;
begin
  if uid is null then raise exception 'AUTHENTICATION_REQUIRED' using errcode = '28000'; end if;
  select onboarding_path into selected_path from public.jqe_profiles where id = uid for update;
  if selected_path is distinct from 'existing_account' then
    raise exception 'EXISTING_ACCOUNT_PATH_REQUIRED' using errcode = '42501';
  end if;
  if exists (select 1 from public.jqe_profiles where id = uid and access_override = 'SUSPENDED') then
    raise exception 'ACCOUNT_ACCESS_SUSPENDED' using errcode = '42501';
  end if;
  if exists (select 1 from public.jqe_trial_activations where user_id = uid) then
    raise exception 'TRIAL_ALREADY_USED' using errcode = '23505';
  end if;
  ended := started + interval '24 hours';
  insert into public.jqe_trial_activations (user_id, activated_at, expires_at)
  values (uid, started, ended);
  return jsonb_build_object('activated_at', started, 'expires_at', ended);
end;
$$;

create or replace function public.jqe_submit_referral(p_note text default null)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  uid uuid := auth.uid();
  selected_path text;
  application public.jqe_referral_applications%rowtype;
begin
  if uid is null then raise exception 'AUTHENTICATION_REQUIRED' using errcode = '28000'; end if;
  select onboarding_path into selected_path from public.jqe_profiles where id = uid;
  if selected_path is distinct from 'referral' then
    raise exception 'REFERRAL_PATH_REQUIRED' using errcode = '42501';
  end if;
  insert into public.jqe_referral_applications (user_id, note)
  values (uid, left(nullif(trim(p_note), ''), 500))
  on conflict (user_id) do update set
    note = excluded.note,
    status = case when jqe_referral_applications.status = 'APPROVED' then 'APPROVED' else 'PENDING' end,
    submitted_at = now()
  returning * into application;
  return jsonb_build_object('status', application.status, 'submitted_at', application.submitted_at);
end;
$$;

create or replace function public.jqe_admin_referrals()
returns jsonb
language plpgsql
stable
security definer
set search_path = public, auth
as $$
begin
  if not public.jqe_is_admin() then raise exception 'ADMIN_REQUIRED' using errcode = '42501'; end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object(
      'id', r.id, 'user_id', r.user_id, 'email', u.email, 'submitted_at', r.submitted_at,
      'status', r.status, 'note', r.note,
      'access_override', p.access_override,
      'access_expires_at', p.access_override_expires_at
    ) order by r.submitted_at desc)
    from public.jqe_referral_applications r
    join auth.users u on u.id = r.user_id
    join public.jqe_profiles p on p.id = r.user_id
  ), '[]'::jsonb);
end;
$$;

create or replace function public.jqe_review_referral(p_id uuid, p_status text)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  reviewed public.jqe_referral_applications%rowtype;
begin
  if not public.jqe_is_admin() then raise exception 'ADMIN_REQUIRED' using errcode = '42501'; end if;
  if p_status not in ('APPROVED', 'REJECTED') then raise exception 'INVALID_REVIEW_STATUS' using errcode = '22023'; end if;
  update public.jqe_referral_applications
  set status = p_status, reviewed_at = now(), reviewed_by = auth.uid()
  where id = p_id returning * into reviewed;
  if not found then raise exception 'REFERRAL_NOT_FOUND' using errcode = 'P0002'; end if;
  return jsonb_build_object('id', reviewed.id, 'status', reviewed.status, 'reviewed_at', reviewed.reviewed_at);
end;
$$;

create or replace function public.jqe_admin_set_access(p_user_id uuid, p_status text, p_expires_at timestamptz default null)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  resolved_expiry timestamptz;
begin
  if not public.jqe_is_admin() then raise exception 'ADMIN_REQUIRED' using errcode = '42501'; end if;
  if p_status not in ('ACTIVE', 'SUSPENDED', 'NONE') then raise exception 'INVALID_ACCESS_STATUS' using errcode = '22023'; end if;
  resolved_expiry := case when p_status = 'ACTIVE' then now() + interval '24 hours' else null end;
  update public.jqe_profiles set
    access_override = p_status,
    access_override_expires_at = resolved_expiry,
    updated_at = now()
  where id = p_user_id;
  if not found then raise exception 'PROFILE_NOT_FOUND' using errcode = 'P0002'; end if;
  return jsonb_build_object('user_id', p_user_id, 'access_override', p_status, 'expires_at', resolved_expiry);
end;
$$;

create or replace function public.jqe_consume_feature(p_feature text)
returns jsonb
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  uid uuid := auth.uid();
  snapshot jsonb;
  limit_value integer;
  used_value integer;
  today_utc date := (now() at time zone 'utc')::date;
begin
  if uid is null then raise exception 'AUTHENTICATION_REQUIRED' using errcode = '28000'; end if;
  snapshot := public.jqe_access_snapshot();
  if not coalesce((snapshot ->> 'access_granted')::boolean, false)
    or not (snapshot -> 'feature_access' ? p_feature) then
    raise exception 'FEATURE_ACCESS_DENIED' using errcode = '42501';
  end if;
  if p_feature <> 'ai_chat' then
    return jsonb_build_object('allowed', true, 'feature', p_feature);
  end if;

  select daily_limit into limit_value from public.jqe_feature_limits
  where plan_key = case when snapshot ->> 'access_status' = 'ADMIN_GRANTED' then 'admin' else 'trial' end
    and feature = p_feature;
  if limit_value is null then limit_value := 5; end if;
  insert into public.jqe_usage_counters (user_id, feature, utc_day, used)
  values (uid, p_feature, today_utc, 1)
  on conflict (user_id, feature, utc_day) do update
    set used = public.jqe_usage_counters.used + 1
    where public.jqe_usage_counters.used < limit_value
  returning used into used_value;
  if used_value is null then
    select used into used_value from public.jqe_usage_counters
    where user_id = uid and feature = p_feature and utc_day = today_utc;
    return jsonb_build_object('allowed', false, 'feature', p_feature, 'used', used_value, 'limit', limit_value);
  end if;
  return jsonb_build_object('allowed', true, 'feature', p_feature, 'used', used_value, 'limit', limit_value);
end;
$$;

revoke all on function public.jqe_access_snapshot() from public, anon;
revoke all on function public.jqe_activate_existing_trial() from public, anon;
revoke all on function public.jqe_submit_referral(text) from public, anon;
revoke all on function public.jqe_admin_referrals() from public, anon;
revoke all on function public.jqe_review_referral(uuid, text) from public, anon;
revoke all on function public.jqe_admin_set_access(uuid, text, timestamptz) from public, anon;
revoke all on function public.jqe_consume_feature(text) from public, anon;
grant execute on function public.jqe_access_snapshot() to authenticated;
grant execute on function public.jqe_activate_existing_trial() to authenticated;
grant execute on function public.jqe_submit_referral(text) to authenticated;
grant execute on function public.jqe_admin_referrals() to authenticated;
grant execute on function public.jqe_review_referral(uuid, text) to authenticated;
grant execute on function public.jqe_admin_set_access(uuid, text, timestamptz) to authenticated;
grant execute on function public.jqe_consume_feature(text) to authenticated;
