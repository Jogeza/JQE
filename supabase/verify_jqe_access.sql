-- Read-only catalog audit for Supabase SQL Editor. No credentials or user data.
-- Run against the project used by jqe.vercel.app before enabling readiness.
begin transaction read only;

select c.relname as table_name, c.relrowsecurity as rls_enabled,
  has_table_privilege('authenticated', c.oid, 'SELECT') as authenticated_select,
  has_table_privilege('authenticated', c.oid, 'INSERT') as authenticated_insert,
  has_table_privilege('authenticated', c.oid, 'UPDATE') as authenticated_update,
  has_table_privilege('authenticated', c.oid, 'DELETE') as authenticated_delete,
  has_table_privilege('anon', c.oid, 'INSERT') as anon_insert,
  has_table_privilege('anon', c.oid, 'UPDATE') as anon_update,
  has_table_privilege('anon', c.oid, 'DELETE') as anon_delete
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname in (
  'jqe_profiles', 'jqe_referral_applications', 'jqe_trial_activations',
  'jqe_usage_counters', 'jqe_feature_limits', 'jqe_plan_catalog'
) order by c.relname;

select tablename, policyname, roles, cmd, qual, with_check
from pg_policies where schemaname = 'public' and tablename like 'jqe_%'
order by tablename, policyname;

with expected(signature) as (values
  ('public.jqe_access_snapshot()'),
  ('public.jqe_activate_existing_trial()'),
  ('public.jqe_submit_referral(text)'),
  ('public.jqe_admin_referrals()'),
  ('public.jqe_review_referral(uuid,text)'),
  ('public.jqe_admin_set_access(uuid,text,timestamp with time zone)'),
  ('public.jqe_consume_feature(text)')
)
select e.signature, p.oid is not null as exists,
  pg_get_function_identity_arguments(p.oid) as arguments,
  pg_get_function_result(p.oid) as result_type,
  p.prosecdef as security_definer, p.proconfig as settings,
  has_function_privilege('authenticated', p.oid, 'EXECUTE') as authenticated_execute,
  has_function_privilege('anon', p.oid, 'EXECUTE') as anon_execute,
  exists (select 1 from aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
          where a.grantee = 0 and a.privilege_type = 'EXECUTE') as public_execute,
  pg_get_functiondef(p.oid) as definition
from expected e left join pg_proc p on p.oid = to_regprocedure(e.signature)
order by e.signature;

select t.tgname, t.tgenabled, pg_get_triggerdef(t.oid) as definition,
  pg_get_functiondef(t.tgfoid) as function_definition
from pg_trigger t where t.tgrelid = 'auth.users'::regclass
  and not t.tgisinternal and t.tgname = 'jqe_auth_user_created';

select count(*) as users_without_jqe_profile
from auth.users u left join public.jqe_profiles p on p.id = u.id
where p.id is null;

select c.relname as table_name, con.conname, pg_get_constraintdef(con.oid) as definition
from pg_constraint con join pg_class c on c.oid = con.conrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public' and c.relname like 'jqe_%'
order by c.relname, con.conname;

select plan_key, price, currency, status, feature_list from public.jqe_plan_catalog;
select plan_key, feature, daily_limit from public.jqe_feature_limits;
rollback;
