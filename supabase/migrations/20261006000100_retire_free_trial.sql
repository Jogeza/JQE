-- Paid access requires a future server-verified payment integration.
-- Preserve existing trials, owner overrides and quotas.
begin;
revoke execute on function public.jqe_activate_existing_trial() from authenticated;
revoke execute on function public.jqe_activate_existing_trial() from anon;
revoke execute on function public.jqe_activate_existing_trial() from public;

-- Abort the transaction if inherited grants still permit client execution.
do $$
begin
  if has_function_privilege('authenticated', 'public.jqe_activate_existing_trial()', 'EXECUTE')
     or has_function_privilege('anon', 'public.jqe_activate_existing_trial()', 'EXECUTE') then
    raise exception 'Legacy free-trial client execution remains enabled';
  end if;
end;
$$;
commit;
