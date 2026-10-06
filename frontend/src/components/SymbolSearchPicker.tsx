import React, { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Search } from 'lucide-react';
import { filterSymbols, groupSymbolsByFamily, mergeSymbolOptions, SUPPORTED_WELTRADE_SYMBOLS, symbolSearchKey } from '../services/symbolUniverse';

interface SymbolSearchPickerProps {
  selectedSymbol: string;
  watchedSymbols?: readonly string[];
  onSelect: (symbol: string) => void;
  disabled?: boolean;
}

export const SymbolSearchPicker: React.FC<SymbolSearchPickerProps> = ({ selectedSymbol, watchedSymbols = [], onSelect, disabled = false }) => {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listId = useId();
  const optionId = (index: number) => `${listId}-option-${index}`;

  const options = filterSymbols(mergeSymbolOptions([selectedSymbol], watchedSymbols, SUPPORTED_WELTRADE_SYMBOLS), query);
  const groups = groupSymbolsByFamily(options);
  const watched = new Set(watchedSymbols.map(symbolSearchKey));

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) closePicker();
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    rootRef.current?.querySelector<HTMLElement>('.symbol-picker-option[data-active="true"]')?.scrollIntoView?.({ block: 'nearest' });
  }, [activeIndex, open]);

  const closePicker = (restoreFocus = true) => {
    setOpen(false); setQuery(''); setActiveIndex(0);
    if (restoreFocus) rootRef.current?.querySelector<HTMLButtonElement>('.symbol-picker-trigger')?.focus();
  };

  const choose = (symbol: string) => {
    onSelect(symbol);
    closePicker();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    // Escape must close the picker without bubbling to document-level handlers
    // (the chart fullscreen listener would otherwise exit the overlay too).
    if (event.key === 'Escape') { event.stopPropagation(); closePicker(); return; }
    if (event.key === 'ArrowDown') { event.preventDefault(); setActiveIndex(index => Math.min(index + 1, options.length - 1)); return; }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActiveIndex(index => Math.max(index - 1, 0)); return; }
    if (event.key === 'Enter') { event.preventDefault(); if (options[activeIndex]) choose(options[activeIndex]); return; }
    if (event.key === 'Tab') closePicker(false);
  };

  return <div className={`symbol-picker${open ? ' is-open' : ''}`} ref={rootRef}>
    <button type="button" className="symbol-picker-trigger" aria-haspopup="listbox" aria-expanded={open}
      aria-label={`Change symbol · current ${selectedSymbol}`} disabled={disabled}
      onClick={() => (open ? closePicker() : setOpen(true))}>
      <Search size={12} aria-hidden="true" />
      <strong>{selectedSymbol}</strong>
      <ChevronDown size={12} aria-hidden="true" />
    </button>
    {open && <div className="symbol-picker-popover">
      <input ref={inputRef} type="text" role="combobox" className="symbol-picker-input"
        aria-label="Search Weltrade synthetic symbols" aria-expanded="true" aria-controls={listId}
        aria-autocomplete="list" aria-activedescendant={options[activeIndex] ? optionId(activeIndex) : undefined}
        placeholder="Search symbols…" value={query}
        onChange={event => { setQuery(event.target.value); setActiveIndex(0); }} onKeyDown={onKeyDown} />
      <ul id={listId} role="listbox" aria-label="Weltrade symbols" className="symbol-picker-list">
        {options.length === 0 && <li className="symbol-picker-empty" role="presentation">No matching symbols</li>}
        {groups.map(group => <li key={group.family} role="group" aria-label={group.family} className="symbol-picker-group">
          <span className="symbol-picker-family" aria-hidden="true">{group.family}</span>
          <ul role="none" className="symbol-picker-family-list">
            {group.symbols.map(symbol => {
              const index = options.indexOf(symbol);
              return <li key={symbol} id={optionId(index)} role="option" className="symbol-picker-option"
                aria-selected={symbol === selectedSymbol}
                data-active={index === activeIndex ? 'true' : undefined}
                onMouseEnter={() => setActiveIndex(index)} onMouseDown={event => event.preventDefault()}
                onClick={() => choose(symbol)}>
                <span>{symbol}</span>
                {watched.has(symbolSearchKey(symbol)) && <em className="symbol-picker-watch">WATCHED</em>}
              </li>;
            })}
          </ul>
        </li>)}
      </ul>
      <small className="symbol-picker-hint">Weltrade synthetic scope · backend validates each symbol</small>
    </div>}
  </div>;
};
