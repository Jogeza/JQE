-- Preserve the applied base migration; tighten quota edge cases and table grants.
begin;

revoke all on public.jqe_profiles, public.jqe_referral_applications,
  public.jqe_trial_activations, public.jqe_usage_counters, public.jqe_feature_limits,
  public.jqe_plan_catalog from public, anon, authenticated;
grant select on public.jqe_profiles, public.jqe_referral_applications,
  public.jqe_trial_activations, public.jqe_usage_counters,
  public.jqe_plan_catalog to authenticated;

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
  -- Serialize with suspension/trial operations for this user, never other users.
  perform 1 from public.jqe_profiles where id = uid for update;
  snapshot := public.jqe_access_snapshot();
  if p_feature is null
    or not coalesce((snapshot ->> 'access_granted')::boolean, false)
    or not coalesce(snapshot -> 'feature_access' ? p_feature, false) then
    raise exception 'FEATURE_ACCESS_DENIED' using errcode = '42501';
  end if;
  if p_feature <> 'ai_chat' then
    return jsonb_build_object('allowed', true, 'feature', p_feature);
  end if;

  select daily_limit into limit_value from public.jqe_feature_limits
  where plan_key = case when snapshot ->> 'access_status' = 'ADMIN_GRANTED' then 'admin' else 'trial' end
    and feature = p_feature;
  if limit_value is null then limit_value := 5; end if;
  if limit_value = 0 then
    select used into used_value from public.jqe_usage_counters
    where user_id = uid and feature = p_feature and utc_day = today_utc;
    return jsonb_build_object('allowed', false, 'feature', p_feature,
      'used', coalesce(used_value, 0), 'limit', limit_value);
  end if;
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

revoke all on function public.jqe_consume_feature(text) from public, anon;
grant execute on function public.jqe_consume_feature(text) to authenticated;
notify pgrst, 'reload schema';
commit;
