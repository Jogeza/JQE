// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { Sidebar } from './Sidebar';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it('retracts the mobile header on downward scroll and restores it on upward scroll, tab change or near the top', async () => {
  vi.stubGlobal('matchMedia', vi.fn().mockImplementation(() => ({
    matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })));
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host);
  const scroller = document.createElement('div');
  scroller.className = 'workspace-page';
  document.body.append(scroller);
  let y = 0;
  Object.defineProperty(scroller, 'scrollTop', { get: () => y, set: value => { y = value; }, configurable: true });
  const retracted = () => (host.querySelector('.mobile-navigation-header') as HTMLDivElement).classList.contains('retracted');
  const scrollTo = async (next: number) => {
    y = next;
    await act(async () => scroller.dispatchEvent(new Event('scroll')));
  };
  try {
    await act(async () => root.render(<Sidebar activeTab="workspace" onTabChange={() => {}} />));
    expect(retracted()).toBe(false);
    await scrollTo(60); expect(retracted()).toBe(false);
    await scrollTo(120); expect(retracted()).toBe(true);
    await scrollTo(125); expect(retracted()).toBe(true);
    await scrollTo(70); expect(retracted()).toBe(false);
    await scrollTo(200); expect(retracted()).toBe(true);
    await act(async () => root.render(<Sidebar activeTab="markets" onTabChange={() => {}} />));
    expect(retracted()).toBe(false);
    await scrollTo(300); expect(retracted()).toBe(true);
    await scrollTo(5); expect(retracted()).toBe(false);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    scroller.remove();
    vi.unstubAllGlobals();
  }
});
