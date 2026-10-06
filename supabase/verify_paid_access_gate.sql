-- Read-only check after applying 20261006000100_retire_free_trial.sql.
begin transaction read only;
select
  not has_function_privilege('authenticated', 'public.jqe_activate_existing_trial()', 'EXECUTE')
    as authenticated_free_activation_blocked,
  not has_function_privilege('anon', 'public.jqe_activate_existing_trial()', 'EXECUTE')
    as anonymous_free_activation_blocked;

select plan_key, name, price, currency, status
from public.jqe_plan_catalog
where plan_key in ('trial', 'subscription', 'lifetime')
order by price;
commit;
