-- Real PostgreSQL assertions; all fixtures/configuration changes are rolled back.
-- Requires an isolated identity created by tools/verify_hosted_access.py.
begin;
do $$
declare
  audit_uid uuid;
  outcome jsonb;
  rejected boolean := false;
begin
  select id into audit_uid from auth.users
  where email like 'jqe-auth-audit-%@example.com'
    and raw_user_meta_data ? 'jqe_auth_audit'
  order by created_at limit 1;
  if audit_uid is null then raise exception 'ISOLATED_AUDIT_IDENTITY_REQUIRED'; end if;
  perform set_config('request.jwt.claim.sub', audit_uid::text, true);
  update public.jqe_profiles set access_override = 'NONE' where id = audit_uid;
  insert into public.jqe_trial_activations(user_id, activated_at, expires_at)
  values (audit_uid, now(), now() + interval '24 hours')
  on conflict (user_id) do update set activated_at = excluded.activated_at, expires_at = excluded.expires_at;
  delete from public.jqe_usage_counters where user_id = audit_uid;
  begin
    perform public.jqe_consume_feature(null);
  exception when insufficient_privilege then rejected := true;
  end;
  if not rejected then raise exception 'NULL_FEATURE_MUST_BE_DENIED'; end if;
  update public.jqe_feature_limits set daily_limit = 0 where plan_key = 'trial' and feature = 'ai_chat';
  outcome := public.jqe_consume_feature('ai_chat');
  if outcome ->> 'allowed' is distinct from 'false' or outcome ->> 'limit' is distinct from '0' then
    raise exception 'ZERO_QUOTA_MUST_DENY_FIRST_REQUEST';
  end if;
  if exists (select 1 from public.jqe_usage_counters where user_id = audit_uid) then
    raise exception 'ZERO_QUOTA_MUST_NOT_INCREMENT';
  end if;
  if exists (
    select 1 from pg_class c
    where c.relnamespace = 'public'::regnamespace and c.relname like 'jqe_%'
      and (has_table_privilege('authenticated', c.oid, 'TRUNCATE')
        or has_table_privilege('anon', c.oid, 'TRUNCATE'))
  ) then raise exception 'CLIENT_TRUNCATE_MUST_BE_REVOKED'; end if;
end;
$$;
rollback;
select 'PASS' as null_feature_denial, 'PASS' as zero_quota_denial,
  'PASS' as no_zero_quota_increment, 'PASS' as client_truncate_revoked,
  'ROLLED_BACK' as fixtures;
