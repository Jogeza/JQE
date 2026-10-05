// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthShell } from './AuthShell';

const mocks = vi.hoisted(() => {
  const state: { session: any; listener: ((event: string, session: any) => void) | null } = { session: null, listener: null };
  const testSession = { access_token: 'test-session-token', user: { id: 'user-1', email: 'user@example.com' } };
  const emit = (value: any) => { state.session = value; state.listener?.(value ? 'SIGNED_IN' : 'SIGNED_OUT', value); };
  const auth = {
    getSession: vi.fn(async () => ({ data: { session: state.session } })),
    onAuthStateChange: vi.fn((listener: (event: string, session: any) => void) => {
      state.listener = listener;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    }),
    signInWithPassword: vi.fn(async () => { emit(testSession); return { error: null }; }),
    signUp: vi.fn(async () => { emit(testSession); return { data: { session: testSession }, error: null }; }),
    resetPasswordForEmail: vi.fn(async () => ({ error: null })),
    updateUser: vi.fn(async () => ({ error: null })),
    signOut: vi.fn(async () => { emit(null); return { error: null }; }),
  };
  return { state, testSession, auth, emit };
});

vi.mock('./supabase', () => ({
  authConfigured: true,
  authProviderConfigured: true,
  accessSchemaReady: true,
  weltradeReferralUrl: 'https://track.gowt.me/visit/?bta=44132&brand=weltrade',
  supabase: { auth: mocks.auth },
}));
vi.mock('../App', () => ({ App: ({ authenticated, onSignOut }: { authenticated?: boolean; onSignOut?: () => void }) => <div data-authenticated={authenticated}>Protected dashboard<button onClick={onSignOut}>Sign out</button></div> }));

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
type AccessFixture = {
  authenticated: boolean; role: string; onboarding_path: 'referral' | 'existing_account';
  access_status: string; access_granted: boolean;
  trial_available: boolean; trial_expires_at: string | null; referral_status: string;
  backend_state: string; feature_access: string[]; ai_daily_limit: number | null;
  ai_used_today: number; plans: { key: string; name: string; price: number | null; currency: string | null; status: string }[];
};
const defaultAccess = (): AccessFixture => ({
  authenticated: true, role: 'user', onboarding_path: 'existing_account', access_status: 'ONBOARDING', access_granted: false,
  trial_available: true, trial_expires_at: null, referral_status: 'NOT_SUBMITTED',
  backend_state: 'UNAVAILABLE', feature_access: [], ai_daily_limit: 5, ai_used_today: 0,
  plans: [{ key: 'subscription', name: 'JQE subscription', price: null, currency: null, status: 'NOT_CONFIGURED' }],
});

const assignValue = (element: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
};

describe('AuthShell hosted access flows', () => {
  let host: HTMLDivElement;
  let root: Root;
  let access: ReturnType<typeof defaultAccess>;
  let requests: { path: string; method: string; body: any }[];

  const render = async (path = '/') => {
    window.history.replaceState({}, '', path);
    await act(async () => root.render(<AuthShell />));
  };
  const click = async (name: string) => {
    const button = Array.from(host.querySelectorAll('button')).find(item => item.textContent?.includes(name));
    expect(button).toBeTruthy();
    await act(async () => { button!.click(); await new Promise(resolve => setTimeout(resolve, 0)); });
  };
  const respond = (body: unknown, status = 200) => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  });

  beforeEach(() => {
    access = defaultAccess(); requests = [];
    mocks.state.session = null; mocks.state.listener = null;
    Object.values(mocks.auth).forEach(value => { if (typeof value === 'function' && 'mockClear' in value) value.mockClear(); });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? 'GET';
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      requests.push({ path, method, body });
      if (path === '/api/access') return respond(access);
      if (path === '/api/onboarding/trial/activate') {
        access = { ...access, access_status: 'TRIAL_ACTIVE', access_granted: true, trial_available: false, trial_expires_at: '2026-10-05T12:00:00+00:00', feature_access: ['workspace_read', 'research_read', 'ai_chat'] };
        return respond({ activated_at: '2026-10-04T12:00:00+00:00', expires_at: access.trial_expires_at });
      }
      if (path === '/api/onboarding/referral') return respond({ status: 'PENDING' });
      if (path === '/api/admin/referrals') return respond([{ id: 'app-1', user_id: 'user-2', email: 'member@example.com', submitted_at: '2026-10-04T12:00:00Z', status: 'PENDING', note: null, access_override: 'NONE', access_expires_at: null }]);
      if (path === '/api/admin/access') return respond({ status: 'OK' });
      return respond({ detail: 'unavailable' }, 503);
    }));
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals();
    document.documentElement.classList.remove('auth-scroll-enabled');
    document.body.classList.remove('auth-scroll-enabled');
    document.getElementById('root')?.classList.remove('auth-scroll-enabled');
  });

  it('redirects protected dashboard paths to sign-in without a session', async () => {
    await render('/app');
    expect(host.textContent).toContain('Sign in to JQE.');
    expect(host.textContent).not.toContain('Protected dashboard');
  });

  it('uses the shared configured Weltrade link for the brand and registration action', async () => {
    await render('/signup?path=referral');
    const brand = host.querySelector('.auth-brand') as HTMLAnchorElement;
    const registration = host.querySelector('.auth-side-note .auth-referral-link') as HTMLAnchorElement;
    expect(brand.href).toBe(registration.href);
    expect(brand.target).toBe('_blank');
    expect(brand.rel).toBe('noopener noreferrer');
  });

  it('links the landing registration action directly to the partner URL', async () => {
    await render('/');
    const registration = host.querySelector('.auth-hero-actions a') as HTMLAnchorElement;
    expect(registration.href).toBe('https://track.gowt.me/visit/?bta=44132&brand=weltrade');
    expect(registration.target).toBe('_blank');
    await click('Submit registration for review');
    expect(window.location.search).toBe('?path=referral');
  });

  it('locks the workspace and rechecks server access when the trial expires', async () => {
    vi.useFakeTimers();
    try {
      access = { ...access, access_status: 'TRIAL_ACTIVE', access_granted: true,
        trial_available: false, trial_expires_at: new Date(Date.now() + 2000).toISOString() };
      mocks.emit(mocks.testSession);
      await render('/onboarding');
      expect(host.textContent).toContain('Protected dashboard');
      access = { ...access, access_status: 'TRIAL_EXPIRED', access_granted: false };
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      expect(host.textContent).not.toContain('Protected dashboard');
      expect(host.textContent).toContain('Your one-time trial expired');
    } finally { vi.useRealTimers(); }
  });

  it('does not restore access from an old request after sign-out', async () => {
    let finishAccess: ((value: unknown) => void) | undefined;
    vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { finishAccess = resolve; })));
    mocks.emit(mocks.testSession);
    await render('/onboarding');
    await act(async () => mocks.emit(null));
    await act(async () => finishAccess?.(respond({ ...defaultAccess(), access_granted: true })));
    expect(host.textContent).not.toContain('Protected dashboard');
    await act(async () => mocks.emit(mocks.testSession));
    expect(host.textContent).not.toContain('Protected dashboard');
  });

  it('submits signup with the selected referral path and never asks for a Weltrade password', async () => {
    await render('/signup?path=referral');
    const email = host.querySelector('#account-email') as HTMLInputElement;
    const password = host.querySelector('#account-password') as HTMLInputElement;
    assignValue(email, 'new@example.com'); assignValue(password, 'jqe-password-123');
    await click('Create account');
    expect(mocks.auth.signUp).toHaveBeenCalledWith(expect.objectContaining({
      email: 'new@example.com',
      options: expect.objectContaining({ data: { onboarding_path: 'referral' } }),
    }));
    access = { ...access, onboarding_path: 'referral' };
    await act(async () => mocks.state.listener?.('TOKEN_REFRESHED', { ...mocks.testSession, access_token: 'referral-session-token' }));
    expect(host.textContent).toContain('Submit for review');
    expect(host.textContent).not.toContain('Activate 24-hour trial');
    expect(host.textContent).toContain('Weltrade passwords are never requested');
  });

  it('signs in and signs out through the provider session', async () => {
    await render('/login');
    assignValue(host.querySelector('#account-email') as HTMLInputElement, 'member@example.com');
    assignValue(host.querySelector('#account-password') as HTMLInputElement, 'jqe-password-123');
    await click('Sign in');
    expect(mocks.auth.signInWithPassword).toHaveBeenCalledWith({ email: 'member@example.com', password: 'jqe-password-123' });
    expect(host.textContent).toContain('Choose your JQE access.');
    await click('Sign out');
    expect(mocks.auth.signOut).toHaveBeenCalled();
    expect(host.textContent).toContain('See the evidence.');
  });

  it('sends password recovery without disclosing whether an email exists', async () => {
    await render('/recover');
    assignValue(host.querySelector('#account-email') as HTMLInputElement, 'member@example.com');
    await click('Send recovery email');
    expect(mocks.auth.resetPasswordForEmail).toHaveBeenCalledWith('member@example.com', expect.objectContaining({ redirectTo: expect.stringContaining('/recover') }));
    expect(host.textContent).toContain('If an account exists for that address');
  });

  it('accepts a recovery callback, updates the JQE password, and signs out', async () => {
    mocks.emit(mocks.testSession);
    await render('/recover');
    assignValue(host.querySelector('#new-password') as HTMLInputElement, 'new-jqe-password-123');
    await click('Update password');
    expect(mocks.auth.updateUser).toHaveBeenCalledWith({ password: 'new-jqe-password-123' });
    expect(mocks.auth.signOut).toHaveBeenCalled();
    expect(host.textContent).toContain('Your JQE password was updated');
  });

  it('opens paid access plans without activating a free trial', async () => {
    mocks.emit(mocks.testSession);
    await render('/onboarding');
    await click('View access plans');
    expect(requests.filter(item => item.path === '/api/onboarding/trial/activate')).toHaveLength(0);
    expect(host.textContent).toContain('JQE PREMIUM ACCESS');
  });

  it('shows server catalog prices with checkout disabled', async () => {
    access.plans = [
      { key: 'trial', name: '24-hour access', price: 20, currency: 'USD', status: 'NOT_CONFIGURED' },
      { key: 'subscription', name: 'Monthly', price: 1500, currency: 'USD', status: 'NOT_CONFIGURED' },
      { key: 'lifetime', name: 'Lifetime', price: 5000, currency: 'USD', status: 'NOT_CONFIGURED' },
    ];
    mocks.emit(mocks.testSession);
    await render('/upgrade');
    for (const price of ['$20', '$1,500', '$5,000']) expect(host.textContent).toContain(price);
    const checkout = Array.from(host.querySelectorAll('button')).filter(button => button.textContent === 'Checkout coming soon');
    expect(checkout).toHaveLength(3);
    expect(checkout.every(button => button.disabled)).toBe(true);
  });

  it('shows the expired trial upgrade state without inventing prices or payments', async () => {
    access = { ...access, access_status: 'TRIAL_EXPIRED', trial_available: false, trial_expires_at: '2026-10-04T12:00:00Z' };
    mocks.emit(mocks.testSession);
    await render('/onboarding');
    expect(host.textContent).toContain('Your one-time trial expired');
    await click('View plans');
    expect(host.textContent).toContain('Payments are not collected until checkout is configured.');
    expect(host.textContent).toContain('Price unavailable');
  });

  it('denies the admin route to a normal authenticated user', async () => {
    mocks.emit(mocks.testSession);
    await render('/admin');
    expect(host.textContent).toContain('Administrator access required.');
    expect(host.textContent).not.toContain('Approve');
  });

  it('renders admin review and server-backed expiring access controls only for admin role', async () => {
    access = { ...access, role: 'admin' };
    mocks.emit(mocks.testSession);
    await render('/admin');
    await click('Refresh queue');
    expect(host.textContent).toContain('member@example.com');
    await click('Grant 24 hours');
    const grant = requests.find(item => item.path === '/api/admin/access');
    expect(grant?.method).toBe('PATCH');
    expect(grant?.body).toEqual(expect.objectContaining({ user_id: 'user-2', status: 'ACTIVE' }));
    expect(grant?.body).not.toHaveProperty('expires_at');
  });
});
