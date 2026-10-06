import React, { useCallback, useEffect, useRef, useState } from 'react';
import { BadgeCheck, CandlestickChart, Compass, PenLine, X } from 'lucide-react';
import './QuickTour.css';

const TOUR_STORAGE_KEY = 'jqe:quick-tour:v1';

const tourCompleted = (): boolean => {
  try { return window.localStorage.getItem(TOUR_STORAGE_KEY) === 'done'; }
  catch { return true; }
};

const steps = [
  { icon: Compass, title: 'Find anything from the sidebar', detail: 'Every page is one tap away. On a phone, tap ☰; the top bar hides as you scroll down and returns when you scroll up.' },
  { icon: CandlestickChart, title: 'Read the chart', detail: 'Pick a timeframe (M1–H1) to reload the chart. Compact prices narrows the right price scale.' },
  { icon: PenLine, title: 'Draw and edit levels', detail: 'Choose a tool, drag on the chart to draw. Tap a shape to select it, drag to move it, then press Delete to remove it.' },
  { icon: BadgeCheck, title: 'Trust the labels', detail: 'LIVE, STALE and UNAVAILABLE show what is verified right now. Orders stay disabled; nothing on this screen authorizes execution.' },
];

export const QuickTour: React.FC = () => {
  const [open, setOpen] = useState(() => !tourCompleted());
  const dismissRef = useRef<HTMLButtonElement | null>(null);

  const dismiss = useCallback(() => {
    setOpen(false);
    try { window.localStorage.setItem(TOUR_STORAGE_KEY, 'done'); } catch { /* storage unavailable */ }
  }, []);

  useEffect(() => {
    if (!open) return;
    dismissRef.current?.focus();
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') dismiss(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [dismiss, open]);

  if (!open) return null;

  return (
    <div className="quick-tour-backdrop" onClick={event => { if (event.target === event.currentTarget) dismiss(); }}>
      <section className="quick-tour" role="dialog" aria-modal="true" aria-labelledby="quick-tour-title">
        <header className="quick-tour-heading">
          <div>
            <p className="quick-tour-eyebrow">FIRST LOOK</p>
            <h2 id="quick-tour-title">Quick tour</h2>
          </div>
          <button type="button" className="quick-tour-close" aria-label="Dismiss quick tour" onClick={dismiss}><X size={15} /></button>
        </header>
        <p className="quick-tour-intro">Four essentials before you explore.</p>
        <ul className="quick-tour-steps">
          {steps.map(step => (
            <li key={step.title}>
              <step.icon size={16} aria-hidden="true" />
              <div><strong>{step.title}</strong><span>{step.detail}</span></div>
            </li>
          ))}
        </ul>
        <button type="button" className="quick-tour-start" ref={dismissRef} onClick={dismiss}>Start exploring</button>
      </section>
    </div>
  );
};
