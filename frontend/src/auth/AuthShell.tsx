import React, { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowLeft, ArrowRight, Check, ExternalLink, LockKeyhole, ShieldCheck } from 'lucide-react';
import type { Session } from '@supabase/supabase-js';
import { App } from '../App';
import { setApiAccessToken } from '../services/api';
import { accessSchemaReady, authConfigured, authProviderConfigured, supabase, weltradeReferralUrl } from './supabase';
import './AuthShell.css';

type Route = 'home' | 'login' | 'signup' | 'recover' | 'onboarding' | 'admin' | 'upgrade' | 'dashboard';
type AccessState = {
  role: 'user' | 'admin'; onboarding_path: 'referral' | 'existing_account';
  access_status: string; access_granted: boolean;
  trial_available: boolean; trial_expires_at: string | null; referral_status: string;
  backend_state: 'AVAILABLE' | 'UNAVAILABLE'; feature_access: string[];
  ai_daily_limit: number | null; ai_used_today: number | null;
  plans: { key: string; name: string; price: number | null; currency: string | null; status: string }[];
};
type Referral = { id: string; user_id: string; email: string; submitted_at: string; status: string; note: string | null; access_override: string; access_expires_at: string | null };

const currentRoute = (): Route => {
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  return ({ '/login': 'login', '/signup': 'signup', '/recover': 'recover', '/onboarding': 'onboarding', '/admin': 'admin', '/upgrade': 'upgrade', '/app': 'dashboard' } as Record<string, Route>)[path] ?? 'home';
};

async function api<T>(path: string, session: Session, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.detail || result.reason_code || `HTTP ${response.status}`);
  return result as T;
}

export const AuthShell: React.FC = () => {
  const [route, setRoute] = useState<Route>(currentRoute);
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [access, setAccess] = useState<AccessState | null>(null);
  const [accessError, setAccessError] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [proofNote, setProofNote] = useState('');
  const [referrals, setReferrals] = useState<Referral[]>([]);
  const accessRequest = useRef(0);

  const go = useCallback((path: string) => {
    window.history.pushState({}, '', path);
    setRoute(currentRoute()); setMessage(''); setError('');
  }, []);

  useEffect(() => {
    const pop = () => setRoute(currentRoute());
    window.addEventListener('popstate', pop);
    if (!supabase) { setReady(true); return () => window.removeEventListener('popstate', pop); }
    let mounted = true;
    void supabase.auth.getSession().then(({ data }) => {
      if (mounted) { setApiAccessToken(data.session?.access_token ?? null); setSession(data.session); setReady(true); }
    }).catch(() => { if (mounted) setReady(true); });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, value) => {
      accessRequest.current += 1;
      setApiAccessToken(value?.access_token ?? null);
      setSession(value); setAccess(null); setAccessError('');
    });
    return () => { mounted = false; accessRequest.current += 1; setApiAccessToken(null); subscription.unsubscribe(); window.removeEventListener('popstate', pop); };
  }, []);

  useEffect(() => {
    if (route === 'dashboard') go(session ? '/onboarding' : '/login');
    else if (session && route === 'home') go('/onboarding');
  }, [go, route, session]);

  useEffect(() => {
    const documentScroll = !session || route !== 'onboarding' || !access?.access_granted;
    document.documentElement.classList.toggle('auth-scroll-enabled', documentScroll);
    document.body.classList.toggle('auth-scroll-enabled', documentScroll);
    document.getElementById('root')?.classList.toggle('auth-scroll-enabled', documentScroll);
    return () => {
      document.documentElement.classList.remove('auth-scroll-enabled');
      document.body.classList.remove('auth-scroll-enabled');
      document.getElementById('root')?.classList.remove('auth-scroll-enabled');
    };
  }, [access?.access_granted, route, session]);

  const loadAccess = useCallback(async () => {
    const request = ++accessRequest.current;
    if (!session) { setAccess(null); return; }
    try {
      const result = await api<AccessState>('/api/access', session);
      if (request !== accessRequest.current) return;
      setAccess(result); setAccessError('');
    }
    catch (cause) {
      if (request !== accessRequest.current) return;
      setAccess(null); setAccessError(cause instanceof Error ? cause.message : 'Access service unavailable');
    }
  }, [session]);
  useEffect(() => { void loadAccess(); }, [loadAccess]);
  useEffect(() => {
    if (!session) return;
    const refresh = () => { void loadAccess(); };
    const interval = window.setInterval(refresh, 60_000);
    window.addEventListener('focus', refresh);
    return () => { window.clearInterval(interval); window.removeEventListener('focus', refresh); };
  }, [loadAccess, session]);
  useEffect(() => {
    if (access?.access_status !== 'TRIAL_ACTIVE' || !access.trial_expires_at) return;
    const remaining = Date.parse(access.trial_expires_at) - Date.now();
    if (!Number.isFinite(remaining)) { setAccess(null); setAccessError('Trial expiry could not be verified.'); return; }
    const timeout = window.setTimeout(() => {
      setAccess(null);
      void loadAccess();
    }, Math.max(0, remaining));
    return () => window.clearTimeout(timeout);
  }, [access, loadAccess]);

  const submitAuth = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setMessage(''); setError('');
    try {
      if (!supabase) throw new Error('Authentication is unavailable until Supabase is configured for this deployment.');
      if (route === 'login') {
        const { error: authError } = await supabase.auth.signInWithPassword({ email, password });
        if (authError) throw authError;
        go('/onboarding');
      } else if (route === 'signup') {
        const onboardingPath = new URLSearchParams(window.location.search).get('path') === 'referral' ? 'referral' : 'existing_account';
        const { data, error: authError } = await supabase.auth.signUp({
          email, password,
          options: { emailRedirectTo: `${window.location.origin}/onboarding`, data: { onboarding_path: onboardingPath } },
        });
        if (authError) throw authError;
        if (data.session) go('/onboarding');
        else setMessage('Check your email to confirm your JQE account. Do not provide your Weltrade password.');
      } else {
        const { error: authError } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/recover` });
        if (authError) throw authError;
        setMessage('If an account exists for that address, recovery instructions have been sent.');
      }
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Authentication request failed.'); }
    finally { setBusy(false); }
  };

  const completePasswordReset = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      if (!supabase) throw new Error('Authentication is not configured.');
      const { error: authError } = await supabase.auth.updateUser({ password });
      if (authError) throw authError;
      await supabase.auth.signOut(); setSession(null); setAccess(null); go('/login');
      setMessage('Your JQE password was updated. Sign in with the new password.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Password update failed.'); }
    finally { setBusy(false); }
  };

  const signOut = async () => {
    setBusy(true);
    try { await supabase?.auth.signOut(); setSession(null); setAccess(null); go('/'); }
    finally { setBusy(false); }
  };

  const postAction = async <T,>(path: string, body: unknown): Promise<T> => {
    if (!session) throw new Error('Sign in required');
    return api<T>(path, session, 'POST', body);
  };
  const submitReferral = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await postAction<{ status: string }>('/api/onboarding/referral', { note: proofNote });
      setMessage(result.status === 'PENDING' ? 'Sent for manual admin review. A link click does not verify registration.' : 'Referral status updated.');
      await loadAccess();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Referral review unavailable.'); }
    finally { setBusy(false); }
  };
  const activateTrial = async () => {
    setBusy(true); setError(''); setMessage('');
    try {
      const result = await postAction<{ activated_at: string; expires_at: string }>('/api/onboarding/trial/activate', {});
      setMessage(`Activated ${result.activated_at} UTC · expires ${result.expires_at} UTC`);
      await loadAccess();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Trial service unavailable.'); }
    finally { setBusy(false); }
  };
  const loadReferrals = async () => {
    if (!session) return;
    setBusy(true); setError('');
    try { setReferrals(await api<Referral[]>('/api/admin/referrals', session)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Admin service unavailable.'); }
    finally { setBusy(false); }
  };
  const reviewReferral = async (id: string, status: 'APPROVED' | 'REJECTED') => {
    if (!session) return;
    setBusy(true); setError('');
    try {
      await api('/api/admin/referrals', session, 'PATCH', { id, status });
      setReferrals(await api<Referral[]>('/api/admin/referrals', session));
      await loadAccess();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Admin action failed.'); }
    finally { setBusy(false); }
  };
  const setUserAccess = async (userId: string, status: 'ACTIVE' | 'SUSPENDED' | 'NONE') => {
    if (!session) return;
    setBusy(true); setError('');
    try {
      await api('/api/admin/access', session, 'PATCH', { user_id: userId, status });
      setReferrals(await api<Referral[]>('/api/admin/referrals', session));
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Access status update failed.'); }
    finally { setBusy(false); }
  };

  const brand = <a className="auth-brand" href={weltradeReferralUrl} target="_blank" rel="noopener noreferrer" aria-label="Weltrade registration partner link, opens in a new tab"><img src="/weltrade-logo.svg" alt="" /><span>JQE <i>Quant</i></span><ExternalLink size={14} aria-hidden="true" /></a>;
  const referral = <a className="auth-referral-link" href={weltradeReferralUrl} target="_blank" rel="noopener noreferrer">Register with Weltrade <ExternalLink size={14} aria-hidden="true" /></a>;

  if (!ready || route === 'dashboard' || (session && route === 'home')) return <main className="auth-loading">Checking secure account access…</main>;
  if (authProviderConfigured && !accessSchemaReady) return <main className="auth-page"><section className="auth-panel">{brand}<p className="auth-eyebrow">ACCOUNT ACCESS · VERIFICATION PENDING</p><h1>Account access is paused.</h1><p>Production account setup is still being verified. Sign-up, sign-in and password recovery will become available when those checks are complete.</p></section></main>;
  if (session && route === 'recover') return <main className="auth-page"><section className="auth-panel auth-form-panel">{brand}<p className="auth-eyebrow">PASSWORD RECOVERY</p><h1>Choose a new JQE password.</h1><form onSubmit={event => void completePasswordReset(event)}><label htmlFor="new-password">New JQE password</label><input id="new-password" type="password" minLength={8} autoComplete="new-password" required value={password} onChange={event => setPassword(event.target.value)} /><button className="auth-primary" disabled={busy} type="submit">Update password <ArrowRight size={15} /></button></form>{error && <p role="alert" className="auth-error">{error}</p>}{message && <p role="status" className="auth-notice">{message}</p>}</section></main>;
  if (session && route === 'onboarding' && access?.access_granted) return <div className="hosted-workspace"><App authenticated onSignOut={() => void signOut()} onAdmin={access.role === "admin" ? () => go("/admin") : undefined} /></div>;

  if (session && route === 'admin') {
    if (accessError) return <main className="auth-page"><section className="auth-panel">{brand}<h1>Admin service unavailable.</h1><p>Role verification failed closed. No admin controls are enabled.</p><button className="auth-secondary" onClick={() => void loadAccess()}>Retry</button></section></main>;
    if (!access) return <main className="auth-loading">Verifying administrator role…</main>;
    if (access.role !== 'admin') return <main className="auth-page"><section className="auth-panel">{brand}<h1>Administrator access required.</h1><p>This account does not have the server-assigned admin role.</p><button className="auth-text-button" onClick={() => void signOut()}>Sign out</button></section></main>;
    return <main className="auth-page"><section className="auth-panel auth-admin">{brand}<button className="auth-back" onClick={() => go('/onboarding')}><ArrowLeft size={15} /> Back</button><p className="auth-eyebrow">SERVER-VERIFIED ADMIN</p><h1>Referral review</h1><p>Approval records verified registration; it grants no permanent free access.</p><button className="auth-primary" onClick={() => void loadReferrals()} disabled={busy}>Refresh queue</button>{referrals.map(item => <article className="auth-application" key={item.id}><div><strong>{item.email}</strong><small>{item.status} · {item.submitted_at}</small><p>{item.note || 'No evidence note'}</p><small>Access: {item.access_override}{item.access_expires_at ? ` · until ${item.access_expires_at}` : ''}</small></div><button disabled={busy} onClick={() => void reviewReferral(item.id, 'APPROVED')}>Approve</button><button disabled={busy} onClick={() => void reviewReferral(item.id, 'REJECTED')}>Reject</button><button disabled={busy} onClick={() => void setUserAccess(item.user_id, 'ACTIVE')}>Grant 24 hours</button><button disabled={busy} onClick={() => void setUserAccess(item.user_id, 'SUSPENDED')}>Suspend</button><button disabled={busy} onClick={() => void setUserAccess(item.user_id, 'NONE')}>Clear override</button></article>)}{error && <p role="alert" className="auth-error">{error}</p>}</section></main>;
  }

  if (session && route === 'upgrade') return <main className="auth-page"><section className="auth-panel">{brand}<button className="auth-back" onClick={() => go('/onboarding')}><ArrowLeft size={15} /> Back</button><p className="auth-eyebrow">UPGRADE</p><h1>Plans are being configured.</h1><p>No price or payment method has been approved. Nothing can be purchased here.</p><div className="auth-plan-list">{(access?.plans ?? []).map(plan => <article key={plan.key}><strong>{plan.name}</strong><span>{plan.price == null ? 'Pricing not announced' : `${plan.currency ?? ''} ${plan.price}`}</span><small>{plan.status}</small></article>)}</div></section></main>;

  if (session) {
    if (accessError) return <main className="auth-page"><section className="auth-panel">{brand}<p className="auth-eyebrow">AUTHENTICATED · ACCESS UNKNOWN</p><h1>Dashboard locked.</h1><p>{accessError}</p><p>Permissions cannot be verified. Hosted MT5 and market evidence require a separately reachable authenticated backend.</p><button className="auth-secondary" onClick={() => void loadAccess()}>Retry access check</button><button className="auth-text-button" onClick={() => void signOut()}>Sign out</button></section></main>;
    if (!access) return <main className="auth-loading">Verifying server-side permissions…</main>;
    if (access.access_granted) return <div className="hosted-workspace"><App authenticated onSignOut={() => void signOut()} onAdmin={access.role === "admin" ? () => go("/admin") : undefined} /></div>;
    if (access.access_status === 'TRIAL_EXPIRED') return <main className="auth-page"><section className="auth-panel">{brand}<p className="auth-eyebrow">TRIAL ENDED</p><h1>Continue with a plan.</h1><p>Your one-time trial expired. Upgrade terms are not configured and no payment is collected.</p><button className="auth-primary" onClick={() => go('/upgrade')}>View plans <ArrowRight size={15} /></button><button className="auth-text-button" onClick={() => void signOut()}>Sign out</button></section></main>;
    const referralPath = access.onboarding_path === 'referral';
    return <main className="auth-page"><section className="auth-panel auth-onboarding">{brand}<p className="auth-eyebrow">ACCESS · {access.access_status.replace(/_/g, ' ')}</p><h1>{referralPath ? 'Verify your Weltrade registration.' : 'Start your JQE trial.'}</h1><p>JQE credentials are separate. Weltrade passwords are never requested.</p>{referralPath ? <div className="auth-path-card"><div><ExternalLink size={18} /><div><h2>Register with Weltrade</h2><p>Registration evidence is reviewed manually. Opening the link never verifies registration.</p></div></div>{referral}<label htmlFor="proof-note">Evidence note <small>Optional. Do not enter passwords or financial details.</small></label><textarea id="proof-note" maxLength={500} value={proofNote} onChange={event => setProofNote(event.target.value)} /><button className="auth-secondary" onClick={() => void submitReferral()} disabled={busy}>Submit for review</button><small>Review: {access.referral_status}</small></div> : <div className="auth-path-card"><div><Activity size={18} /><div><h2>I already have a Weltrade account</h2><p>Start one 24-hour trial when you explicitly activate it. Time is set by the server in UTC.</p></div></div><button className="auth-primary" disabled={busy || !access.trial_available} onClick={() => void activateTrial()}>{access.trial_available ? 'Activate 24-hour trial' : 'Trial unavailable or already used'}</button>{access.trial_expires_at && <small>Trial expires: {access.trial_expires_at} UTC</small>}</div>}<div className="auth-onboarding-footer"><span><Check size={14} /> Automated execution is excluded</span><button className="auth-text-button" onClick={() => go('/upgrade')}>Upgrade plans <ArrowRight size={14} /></button><button className="auth-text-button" onClick={() => void signOut()}>Sign out</button></div>{message && <p role="status" className="auth-notice">{message}</p>}{error && <p role="alert" className="auth-error">{error}</p>}</section></main>;
  }

  if (route === 'login' || route === 'signup' || route === 'recover') {
    const signup = route === 'signup';
    const recover = route === 'recover';
    const onboarding = new URLSearchParams(window.location.search).get('path') === 'referral' ? 'Weltrade referral review' : 'existing account trial';
    return <main className="auth-page"><section className="auth-panel auth-form-panel">{brand}<button className="auth-back" onClick={() => go('/')}><ArrowLeft size={15} /> Home</button><p className="auth-eyebrow">{recover ? 'ACCOUNT RECOVERY' : signup ? 'CREATE JQE ACCOUNT' : 'MEMBER ACCESS'}</p><h1>{recover ? 'Reset your password.' : signup ? 'Make room for better research.' : 'Sign in to JQE.'}</h1><p>{signup ? `Next: ${onboarding}.` : 'Your JQE account is separate from Weltrade.'}</p><form onSubmit={event => void submitAuth(event)}><label htmlFor="account-email">Email</label><input id="account-email" type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} />{!recover && <><label htmlFor="account-password">JQE password</label><input id="account-password" type="password" autoComplete={signup ? 'new-password' : 'current-password'} minLength={8} required value={password} onChange={event => setPassword(event.target.value)} /><small className="auth-password-note"><LockKeyhole size={13} /> JQE password only. Never enter your Weltrade password.</small></>}{error && <p role="alert" className="auth-error">{error}</p>}{message && <p role="status" className="auth-notice">{message}</p>}<button className="auth-primary" type="submit" disabled={busy || !authConfigured}>{busy ? 'Please wait…' : recover ? 'Send recovery email' : signup ? 'Create account' : 'Sign in'} <ArrowRight size={15} /></button></form>{!authConfigured && <p role="status" className="auth-unavailable">Authentication unavailable: configure VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.</p>}<div className="auth-switch-links">{route !== 'login' && <button onClick={() => go('/login')}>Sign in</button>}{route !== 'signup' && <button onClick={() => go('/signup?path=existing')}>Create account</button>}{!recover && <button onClick={() => go('/recover')}>Forgot password?</button>}</div></section><aside className="auth-side-note"><span>JQE / ACCESS</span><strong>Research access, with visible limits.</strong><p>Server-verified entitlements. No payment details collected. No broker execution.</p>{referral}</aside></main>;
  }

  return <main className="auth-landing"><header className="auth-nav">{brand}<nav><button onClick={() => go('/login')}>Sign in</button><button className="auth-nav-primary" onClick={() => go('/signup?path=existing')}>Create account <ArrowRight size={14} /></button></nav></header><section className="auth-hero"><div className="auth-hero-copy"><p className="auth-eyebrow"><span /> QUANTITATIVE RESEARCH WORKSPACE</p><h1>See the evidence.<br /><em>Know the limits.</em></h1><p>Research tools and market context for Weltrade synthetic indices, with access controls and provenance made explicit.</p><div className="auth-hero-actions"><a className="auth-primary" href={weltradeReferralUrl} target="_blank" rel="noopener noreferrer">Register with Weltrade <ExternalLink size={16} /></a><button className="auth-text-button" onClick={() => go('/signup?path=referral')}>Submit registration for review <ArrowRight size={16} /></button><button className="auth-secondary" onClick={() => go('/signup?path=existing')}>I already have a Weltrade account <ArrowRight size={16} /></button></div><small className="auth-hero-disclaimer">Demo observation only · No promise of returns · Automated execution excluded</small></div><div className="auth-hero-visual" aria-label="JQE access overview"><div className="auth-visual-top"><span>JQE / ACCESS</span><span><i /> SESSION REQUIRED</span></div><div className="auth-visual-line"><span>01</span><div><strong>Identity</strong><small>Email verified through the auth provider</small></div><LockKeyhole size={16} /></div><div className="auth-visual-line"><span>02</span><div><strong>Entitlement</strong><small>Trial, manual review, or configured plan</small></div><ShieldCheck size={16} /></div><div className="auth-visual-line"><span>03</span><div><strong>Market evidence</strong><small>Visible only when authenticated services are reachable</small></div><Activity size={16} /></div><div className="auth-visual-foot"><span>ACCESS CHECK</span><strong>SERVER ENFORCED</strong></div></div></section><section className="auth-landing-footer"><span>01 / Weltrade identity</span><span>02 / Manual referral review</span><span>03 / One 24-hour trial</span><span>04 / Execution remains off</span></section>{!authConfigured && <p className="auth-config-banner">Hosted sign-up is unavailable until authentication is configured.</p>}</main>;
};
