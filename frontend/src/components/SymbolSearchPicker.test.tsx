// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SUPPORTED_WELTRADE_SYMBOLS } from '../services/symbolUniverse';
import { SymbolSearchPicker } from './SymbolSearchPicker';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const assignValue = (element: HTMLInputElement, value: string) => {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
};

describe('SymbolSearchPicker', () => {
  let host: HTMLDivElement;
  let root: Root;

  const render = async (onSelect: (symbol: string) => void, watchedSymbols: string[] = ['SFX Vol 99']) => {
    await act(async () => root.render(
      <SymbolSearchPicker selectedSymbol="FX Vol 20" watchedSymbols={watchedSymbols} onSelect={onSelect} />,
    ));
  };
  const trigger = () => host.querySelector('.symbol-picker-trigger') as HTMLButtonElement;
  const input = () => host.querySelector('.symbol-picker-input') as HTMLInputElement;
  const options = () => Array.from(host.querySelectorAll('.symbol-picker-option')) as HTMLElement[];
  const open = async () => { await act(async () => trigger().click()); };

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
  });

  it('opens from the trigger, lists the full Weltrade scope, and flags the watched symbol', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await render(vi.fn());
    expect(trigger().textContent).toContain('FX Vol 20');
    expect(trigger().getAttribute('aria-expanded')).toBe('false');
    expect(host.querySelector('.symbol-picker-popover')).toBeNull();

    await open();
    expect(trigger().getAttribute('aria-expanded')).toBe('true');
    expect(input().placeholder).toBe('Search symbols…');
    expect(options()).toHaveLength(SUPPORTED_WELTRADE_SYMBOLS.length);
    expect(host.querySelector('.symbol-picker-family')?.textContent).toBe('FX Volatility');
    const watched = Array.from(host.querySelectorAll('.symbol-picker-watch'));
    expect(watched).toHaveLength(1);
    expect(watched[0].closest('.symbol-picker-option')?.textContent).toContain('SFX Vol 99');
    expect(host.querySelector('.symbol-picker-hint')?.textContent).toContain('backend validates each symbol');
  });

  it('filters by family alias and selects a symbol through a click', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    const onSelect = vi.fn();
    await render(onSelect);
    await open();

    await act(async () => { assignValue(input(), 'fibonacci'); });
    expect(options().map(option => option.textContent)).toEqual(['FiboX']);
    expect(host.querySelector('.symbol-picker-empty')).toBeNull();

    await act(async () => options()[0].click());
    expect(onSelect).toHaveBeenCalledWith('FiboX');
    expect(host.querySelector('.symbol-picker-popover')).toBeNull();
  });

  it('supports arrow-key navigation and Enter selection with aria-activedescendant', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    const onSelect = vi.fn();
    await render(onSelect);
    await open();

    await act(async () => { assignValue(input(), 'max gainx'); });
    expect(options().map(option => option.textContent)).toEqual(['MAX GainX 1000', 'MAX GainX 2000']);
    const listId = host.querySelector('.symbol-picker-list')?.id;
    expect(input().getAttribute('aria-activedescendant')).toBe(`${listId}-option-0`);

    await act(async () => { input().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); });
    expect(input().getAttribute('aria-activedescendant')).toBe(`${listId}-option-1`);

    await act(async () => { input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });
    expect(onSelect).toHaveBeenCalledWith('MAX GainX 2000');
    expect(host.querySelector('.symbol-picker-popover')).toBeNull();
  });

  it('closes on Escape without letting the event reach document listeners and restores trigger focus', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await render(vi.fn());
    await open();

    const documentSpy = vi.fn();
    document.addEventListener('keydown', documentSpy);
    try {
      await act(async () => { input().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
      expect(host.querySelector('.symbol-picker-popover')).toBeNull();
      expect(documentSpy).not.toHaveBeenCalled();
      expect(document.activeElement).toBe(trigger());
    } finally {
      document.removeEventListener('keydown', documentSpy);
    }
  });

  it('closes when a mousedown lands outside the picker', async () => {
    host = document.createElement('div'); document.body.append(host); root = createRoot(host);
    await render(vi.fn());
    await open();
    expect(host.querySelector('.symbol-picker-popover')).not.toBeNull();

    await act(async () => { document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); });
    expect(host.querySelector('.symbol-picker-popover')).toBeNull();
  });
});
