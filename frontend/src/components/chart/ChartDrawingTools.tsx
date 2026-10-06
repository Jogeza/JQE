import React, { useEffect, useRef, useState } from 'react';
import { MousePointer2, Minus, MoveUpRight, Square, Circle, Ruler, Type, Undo2, Trash2, LockKeyhole, UnlockKeyhole, ZoomIn, ZoomOut, Maximize2, Eraser, X } from 'lucide-react';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import { readDrawings, saveDrawings, type Tool, type Anchor, type Drawing } from './drawingStorage';
import './ChartDrawingTools.css';

const tools = [
  ['cursor', MousePointer2, 'Cursor / pan'], ['line', Minus, 'Trend line'],
  ['horizontal', Minus, 'Horizontal level'], ['arrow', MoveUpRight, 'Arrow'],
  ['rectangle', Square, 'Rectangle'], ['ellipse', Circle, 'Ellipse'],
  ['measure', Ruler, 'Measure price change'], ['text', Type, 'Text note'], ['erase', Eraser, 'Erase drawing'],
] as const;

type DragPart = 'a' | 'b' | 'body';
type DragState = { id: number; tool: Tool; part: DragPart; pointerId: number; startX: number; startY: number; xa: number; ya: number; xb: number; yb: number; lastA: Anchor; lastB: Anchor };

export function ChartDrawingTools({ chart, series, scope, decimals }: {
  chart: IChartApi; series: ISeriesApi<'Candlestick'>; scope: string; decimals: number;
}) {
  const [tool, setTool] = useState<Tool>('cursor');
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [draft, setDraft] = useState<Drawing | null>(null);
  const [color, setColor] = useState('#38bdf8');
  const [note, setNote] = useState('Note');
  const [locked, setLocked] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [, repaint] = useState(0);
  const overlay = useRef<SVGSVGElement>(null);
  const pending = useRef<Drawing | null>(null);
  const drag = useRef<DragState | null>(null);
  const nextId = useRef(0);
  const [drawingsScope, setDrawingsScope] = useState<string | null>(null);
  const [storageAvailable, setStorageAvailable] = useState(true);
  useEffect(() => {
    const restored = readDrawings(scope);
    nextId.current = Math.max(0, ...restored.map(item => item.id));
    setDrawings(restored); setDrawingsScope(scope);
    setDraft(null); pending.current = null; drag.current = null; setTool('cursor'); setLocked(false); setSelectedId(null);
  }, [scope]);
  const drawingScope = useRef(scope);
  useEffect(() => {
    // Persist only once the rendered drawings actually belong to this scope:
    // a fresh mount or market switch still holds the previous drawings for one
    // render, and writing them here would wipe the new market's stored key.
    if (drawingsScope !== scope) return;
    if (drawingScope.current !== scope) { drawingScope.current = scope; return; }
    setStorageAvailable(saveDrawings(scope, drawings));
  }, [drawings, drawingsScope, scope]);
  useEffect(() => {
    const refresh = () => repaint(value => value + 1);
    chart.timeScale().subscribeVisibleLogicalRangeChange(refresh);
    const timer = window.setInterval(refresh, 200);
    return () => { clearInterval(timer); chart.timeScale().unsubscribeVisibleLogicalRangeChange(refresh); };
  }, [chart]);
  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        pending.current = null; drag.current = null; setDraft(null); setTool('cursor'); setSelectedId(null);
        return;
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedId !== null) {
        const target = event.target as HTMLElement | null;
        if (target && (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target.isContentEditable)) return;
        event.preventDefault();
        setDrawings(items => items.filter(item => item.id !== selectedId));
        setSelectedId(null);
      }
    };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, [selectedId]);
  const width = chart.timeScale().width();
  const height = chart.panes()[0]?.getHeight() ?? 0;
  const point = (anchor: Anchor) => {
    const x = chart.timeScale().timeToCoordinate(anchor.time);
    const y = series.priceToCoordinate(anchor.price);
    return x === null || y === null ? null : { x, y };
  };
  const anchor = (event: React.PointerEvent<SVGSVGElement>): Anchor | null => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left, y = event.clientY - box.top;
    if (x < 0 || x > width || y < 0 || y > height) return null;
    const time = chart.timeScale().coordinateToTime(x), price = series.coordinateToPrice(y);
    return time === null || price === null || !Number.isFinite(price) || price <= 0 ? null : { time, price };
  };
  const shiftAnchor = (base: Anchor, x0: number, y0: number, dx: number, dy: number): Anchor => {
    const time = chart.timeScale().coordinateToTime(x0 + dx);
    const price = series.coordinateToPrice(y0 + dy);
    return {
      time: typeof time === 'number' && time > 0 ? time : base.time,
      price: price !== null && Number.isFinite(price) && price > 0 ? price : base.price,
    };
  };
  const grab = (event: React.PointerEvent<SVGElement>, item: Drawing, part: DragPart) => {
    if (locked || tool !== 'cursor') return;
    event.stopPropagation();
    setSelectedId(item.id);
    drag.current = null;
    const xa = chart.timeScale().timeToCoordinate(item.a.time);
    const ya = series.priceToCoordinate(item.a.price);
    const xb = chart.timeScale().timeToCoordinate(item.b.time);
    const yb = series.priceToCoordinate(item.b.price);
    if (xa === null || ya === null || xb === null || yb === null) return;
    drag.current = { id: item.id, tool: item.tool, part, pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, xa, ya, xb, yb, lastA: { ...item.a }, lastB: { ...item.b } };
    overlay.current?.setPointerCapture?.(event.pointerId);
  };
  const removeDrawing = (id: number) => {
    setDrawings(items => items.filter(item => item.id !== id));
    setSelectedId(null);
  };
  const start = (event: React.PointerEvent<SVGSVGElement>) => {
    if (locked || tool === 'cursor') return;
    if (tool === 'erase') {
      const id = (event.target as Element).closest('[data-drawing-id]')?.getAttribute('data-drawing-id');
      if (id) setDrawings(items => items.filter(item => item.id !== Number(id)));
      return;
    }
    const a = anchor(event);
    if (!a || drawings.length >= 50) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const item = { id: ++nextId.current, tool, a, b: a, color, text: note.trim().slice(0, 80) || 'Note' };
    pending.current = item; setDraft(item);
  };
  const move = (event: React.PointerEvent<SVGSVGElement>) => {
    const state = drag.current;
    if (state) {
      if (state.pointerId !== event.pointerId) return;
      const dx = event.clientX - state.startX, dy = event.clientY - state.startY;
      let a = state.lastA, b = state.lastB;
      if (state.part !== 'b') a = shiftAnchor(state.lastA, state.xa, state.ya, dx, dy);
      if (state.part !== 'a') b = shiftAnchor(state.lastB, state.xb, state.yb, dx, dy);
      if (state.tool === 'horizontal') { a = { time: state.lastA.time, price: a.price }; b = a; }
      else if (state.tool === 'text') b = a;
      state.lastA = a; state.lastB = b;
      setDrawings(items => items.map(item => item.id === state.id ? { ...item, a, b } : item));
      return;
    }
    const b = anchor(event);
    if (!pending.current || !b) return;
    pending.current = { ...pending.current, b }; setDraft(pending.current);
  };
  const finish = () => {
    drag.current = null;
    const item = pending.current;
    if (item && (item.tool === 'horizontal' || item.tool === 'text' || item.a.time !== item.b.time || item.a.price !== item.b.price)) {
      setDrawings(items => [...items, item]);
      setSelectedId(item.id);
      pending.current = null; setDraft(null); setTool('cursor');
      return;
    }
    pending.current = null; setDraft(null);
  };
  const zoom = (factor: number) => {
    const range = chart.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const mid = (range.from + range.to) / 2, half = (range.to - range.from) * factor / 2;
    chart.timeScale().setVisibleLogicalRange({ from: mid - half, to: mid + half });
  };
  const renderDrawing = (item: Drawing) => {
    const a = point(item.a), b = point(item.b);
    if (!a || !b) return null;
    const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y), w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);
    const selected = item.id === selectedId;
    const twoAnchor = item.tool !== 'horizontal' && item.tool !== 'text';
    const common = { stroke: item.color, strokeWidth: selected ? 2.5 : 2, fill: 'none' };
    // Transparent hit shapes keep thin drawings draggable without widening their paint.
    const hit = { stroke: 'transparent', strokeWidth: 16, fill: 'transparent', pointerEvents: 'all' as const };
    const delta = item.b.price - item.a.price;
    const label = `${delta >= 0 ? '+' : ''}${delta.toFixed(decimals)} (${(delta / item.a.price * 100).toFixed(2)}%)`;
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    return <g key={item.id} data-drawing-id={item.id} style={{ cursor: locked ? undefined : tool === 'erase' ? 'crosshair' : tool === 'cursor' ? 'move' : undefined }} onPointerDown={event => grab(event, item, 'body')}>
      {item.tool === 'horizontal' ? <><line {...hit} x1={0} x2={width} y1={a.y} y2={a.y} /><line {...common} x1={0} x2={width} y1={a.y} y2={a.y} /><text x={8} y={Math.max(14, a.y - 6)} fill={item.color} pointerEvents="none">{item.a.price.toFixed(decimals)}</text></>
        : item.tool === 'rectangle' ? <><rect {...hit} x={x} y={y} width={w} height={h} /><rect {...common} x={x} y={y} width={w} height={h} fill={item.color} fillOpacity={0.1} /></>
        : item.tool === 'ellipse' ? <><ellipse {...hit} cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} /><ellipse {...common} cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} fill={item.color} fillOpacity={0.1} /></>
        : item.tool === 'text' ? <><rect {...hit} x={a.x - 4} y={a.y - 14} width={Math.max(24, item.text.length * 7)} height={18} /><text x={a.x} y={a.y} fill={item.color} pointerEvents="none">{item.text}</text></>
        : <><line {...hit} x1={a.x} y1={a.y} x2={b.x} y2={b.y} /><line {...common} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeDasharray={item.tool === 'measure' ? '4 3' : undefined} />
          {item.tool === 'arrow' && <polyline {...common} points={`${b.x - 10 * Math.cos(angle - .5)},${b.y - 10 * Math.sin(angle - .5)} ${b.x},${b.y} ${b.x - 10 * Math.cos(angle + .5)},${b.y - 10 * Math.sin(angle + .5)}`} pointerEvents="none" />}
          {item.tool === 'measure' && <text x={Math.min(x + 5, Math.max(0, width - 175))} y={Math.max(16, y - 8)} fill={item.color} pointerEvents="none">{label}</text>}
        </>}
      {selected && tool === 'cursor' && !locked && <>
        <circle cx={a.x} cy={a.y} r={13} fill="transparent" pointerEvents="all" style={{ cursor: 'grab' }} onPointerDown={event => grab(event, item, 'a')} />
        <circle cx={a.x} cy={a.y} r={4.5} fill="#38bdf8" stroke="#ffffff" strokeWidth={1.5} pointerEvents="none" />
        {twoAnchor && <>
          <circle cx={b.x} cy={b.y} r={13} fill="transparent" pointerEvents="all" style={{ cursor: 'grab' }} onPointerDown={event => grab(event, item, 'b')} />
          <circle cx={b.x} cy={b.y} r={4.5} fill="#38bdf8" stroke="#ffffff" strokeWidth={1.5} pointerEvents="none" />
        </>}
      </>}
    </g>;
  };
  const selected = drawings.find(item => item.id === selectedId) ?? null;
  return <>
    <div className="chart-drawing-rail" role="toolbar" aria-label="Chart drawing tools" aria-orientation="vertical">
      {tools.map(([id, Icon, label]) => <button key={id} type="button" title={label} aria-label={label} aria-pressed={tool === id} disabled={locked && id !== 'cursor'} onClick={() => { pending.current = null; setDraft(null); setTool(id); }}><Icon size={17} /></button>)}
      <input type="color" value={color} aria-label="Drawing color" title="Drawing color" onChange={event => setColor(event.target.value)} />
      <span className="drawing-divider" />
      <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => zoom(.75)}><ZoomIn size={17} /></button>
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => zoom(1.25)}><ZoomOut size={17} /></button>
      <button type="button" title="Fit chart" aria-label="Fit chart" onClick={() => chart.timeScale().fitContent()}><Maximize2 size={17} /></button>
      <button type="button" title="Undo last drawing" aria-label="Undo last drawing" disabled={locked || !drawings.length} onClick={() => setDrawings(items => items.slice(0, -1))}><Undo2 size={17} /></button>
      <button type="button" title={locked ? 'Unlock drawings' : 'Lock drawings'} aria-label={locked ? 'Unlock drawings' : 'Lock drawings'} aria-pressed={locked} onClick={() => { setLocked(value => !value); setTool('cursor'); pending.current = null; setDraft(null); setSelectedId(null); }}>{locked ? <LockKeyhole size={17} /> : <UnlockKeyhole size={17} />}</button>
      <button type="button" title="Clear drawings" aria-label="Clear drawings" disabled={locked || !drawings.length} onClick={() => { setDrawings([]); setSelectedId(null); pending.current = null; setDraft(null); }}><Trash2 size={17} /></button>
    </div>
    <span className="chart-drawing-session-status" role="status">{drawings.length} drawings · {storageAvailable ? 'Saved in this tab' : 'Storage unavailable; drawings temporary'}</span>
    {tool !== 'cursor' && !locked && <div className="chart-drawing-hint" role="status">{tool === 'erase' ? 'Tap a drawing to remove it' : tool === 'text' || tool === 'horizontal' ? 'Tap chart to place · Esc cancels' : 'Drag on chart to draw · Esc cancels'}{drawings.length >= 50 ? ' · 50 drawing limit' : ''}
      {tool === 'text' && <input aria-label="Chart note text" value={note} maxLength={80} onChange={event => setNote(event.target.value)} />}
    </div>}
    {tool === 'cursor' && !locked && !selected && drawings.length > 0 && <div className="chart-drawing-hint" role="status">Tap a shape to move or delete</div>}
    {selected && tool === 'cursor' && !locked && <div className="chart-drawing-selection" role="status" aria-label="Selected drawing actions">
      <span>Selected · drag to move</span>
      <button type="button" aria-label="Delete selected drawing" onClick={() => removeDrawing(selected.id)}><Trash2 size={13} /> Delete</button>
      <button type="button" className="drawing-deselect" aria-label="Deselect drawing" onClick={() => setSelectedId(null)}><X size={13} /></button>
    </div>}
    <svg ref={overlay} className="chart-drawing-overlay" width={width} height={height} aria-label="Chart annotations" style={{ pointerEvents: !locked && tool !== 'cursor' ? 'auto' : 'none', touchAction: 'none' }} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={() => { drag.current = null; pending.current = null; setDraft(null); }}>
      {drawings.map(renderDrawing)}{draft && renderDrawing(draft)}
    </svg>
  </>;
}
