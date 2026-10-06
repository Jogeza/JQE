// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { QuickTour } from './QuickTour';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  window.localStorage.clear();
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const mount = () => act(async () => root.render(<QuickTour />));

const withStorage = async (storage: Pick<Storage, 'getItem' | 'setItem'>, run: () => Promise<void>) => {
  const original = Object.getOwnPropertyDescriptor(window, 'localStorage');
  Object.defineProperty(window, 'localStorage', { configurable: true, value: storage });
  try { await run(); }
  finally {
    if (original) Object.defineProperty(window, 'localStorage', original);
    else delete (window as unknown as Record<string, unknown>).localStorage;
  }
};

it('shows once with the four essentials, focuses dismissal and records completion', async () => {
  await mount();
  const dialog = host.querySelector('[role="dialog"]');
  expect(dialog?.getAttribute('aria-modal')).toBe('true');
  expect(dialog?.textContent).toContain('Quick tour');
  expect(dialog?.textContent).toContain('Find anything from the sidebar');
  expect(dialog?.textContent).toContain('Draw and edit levels');
  expect(dialog?.textContent).toContain('Orders stay disabled');
  expect(host.querySelectorAll('.quick-tour-steps li')).toHaveLength(4);
  expect(document.activeElement).toBe(host.querySelector('.quick-tour-start'));
  await act(async () => (host.querySelector('.quick-tour-start') as HTMLButtonElement).click());
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(window.localStorage.getItem('jqe:quick-tour:v1')).toBe('done');
});

it('does not reappear for a completed tour', async () => {
  window.localStorage.setItem('jqe:quick-tour:v1', 'done');
  await mount();
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(host.textContent).toBe('');
});

it('dismisses on Escape', async () => {
  await mount();
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); });
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(window.localStorage.getItem('jqe:quick-tour:v1')).toBe('done');
});

it('dismisses from the close button', async () => {
  await mount();
  await act(async () => (host.querySelector('.quick-tour-close') as HTMLButtonElement).click());
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  expect(window.localStorage.getItem('jqe:quick-tour:v1')).toBe('done');
});

it('dismisses on backdrop tap but not on card interaction', async () => {
  await mount();
  const backdrop = host.querySelector('.quick-tour-backdrop') as HTMLDivElement;
  await act(async () => (host.querySelector('.quick-tour-intro') as HTMLParagraphElement).click());
  expect(host.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => backdrop.click());
  expect(host.querySelector('[role="dialog"]')).toBeNull();
});

it('stays hidden when storage cannot be read', async () => {
  await withStorage({ getItem: () => { throw new Error('denied'); }, setItem: () => {} }, async () => {
    await mount();
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(host.textContent).toBe('');
  });
});

it('still dismisses when storage writes are rejected', async () => {
  await withStorage({ getItem: () => null, setItem: () => { throw new Error('denied'); } }, async () => {
    await mount();
    expect(host.querySelector('[role="dialog"]')).not.toBeNull();
    await act(async () => (host.querySelector('.quick-tour-start') as HTMLButtonElement).click());
    expect(host.querySelector('[role="dialog"]')).toBeNull();
  });
});
