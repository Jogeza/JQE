import { afterEach, expect, it, vi } from 'vitest';
import { jqeApi, setApiAccessToken } from './api';

afterEach(() => { setApiAccessToken(null); vi.unstubAllGlobals(); });

it('sends the current session to hosted APIs and clears it after sign-out', async () => {
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => ({ ok: true, json: async () => ({}) }));
  vi.stubGlobal('fetch', fetch);
  setApiAccessToken('first-test-session');
  await jqeApi.getAssistantStatus();
  expect((fetch.mock.calls[0][1]?.headers as Record<string, string>).Authorization).toBe('Bearer first-test-session');
  setApiAccessToken('refreshed-test-session');
  await jqeApi.getAssistantStatus();
  expect((fetch.mock.calls[1][1]?.headers as Record<string, string>).Authorization).toBe('Bearer refreshed-test-session');
  setApiAccessToken(null);
  await jqeApi.getAssistantStatus();
  expect((fetch.mock.calls[2][1]?.headers as Record<string, string>).Authorization).toBeUndefined();
});
