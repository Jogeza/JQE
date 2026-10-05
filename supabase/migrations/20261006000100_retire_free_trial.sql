-- Paid access requires a future server-verified payment integration.
-- Preserve existing trials, owner overrides and quotas.
revoke execute on function public.jqe_activate_existing_trial() from authenticated;
revoke execute on function public.jqe_activate_existing_trial() from anon;
revoke execute on function public.jqe_activate_existing_trial() from public;
