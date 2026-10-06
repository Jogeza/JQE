import React, { useEffect, useRef, useState } from 'react';
import { MousePointer2, Minus, MoveUpRight, Square, Circle, Ruler, Type, Undo2, Trash2, LockKeyhole, UnlockKeyhole, ZoomIn, ZoomOut, Maximize2, Eraser } from 'lucide-react';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';
import { readDrawings, saveDrawings, type Tool, type Anchor, type Drawing } from './drawingStorage';
import './ChartDrawingTools.css';

const tools = [
  ['cursor', MousePointer2, 'Cursor / pan'], ['line', Minus, 'Trend line'],
  ['horizontal', Minus, 'Horizontal level'], ['arrow', MoveUpRight, 'Arrow'],
  ['rectangle', Square, 'Rectangle'], ['ellipse', Circle, 'Ellipse'],
  ['measure', Ruler, 'Measure price change'], ['text', Type, 'Text note'], ['erase', Eraser, 'Erase drawing'],
] as const;

export function ChartDrawingTools({ chart, series, scope, decimals }: {
  chart: IChartApi; series: ISeriesApi<'Candlestick'>; scope: string; decimals: number;
}) {
  const [tool, setTool] = useState<Tool>('cursor');
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [draft, setDraft] = useState<Drawing | null>(null);
  const [color, setColor] = useState('#38bdf8');
  const [note, setNote] = useState('Note');
  const [locked, setLocked] = useState(false);
  const [, repaint] = useState(0);
  const overlay = useRef<SVGSVGElement>(null);
  const pending = useRef<Drawing | null>(null);
  const nextId = useRef(0);
  const loadedScope = useRef<string | null>(null);
  const [storageAvailable, setStorageAvailable] = useState(true);
  useEffect(() => {
    const restored = readDrawings(scope);
    loadedScope.current = scope;
    nextId.current = Math.max(0, ...restored.map(item => item.id));
    setDrawings(restored); setDraft(null); pending.current = null; setTool('cursor'); setLocked(false);
  }, [scope]);
  const drawingScope = useRef(scope);
  useEffect(() => {
    // Skip the render that changes scope: its drawings still belong to the
    // previous market, and must never be written into the new market's key.
    if (drawingScope.current !== scope) { drawingScope.current = scope; return; }
    if (loadedScope.current === scope) setStorageAvailable(saveDrawings(scope, drawings));
  }, [drawings, scope]);
  useEffect(() => {
    const refresh = () => repaint(value => value + 1);
    chart.timeScale().subscribeVisibleLogicalRangeChange(refresh);
    const timer = window.setInterval(refresh, 200);
    return () => { clearInterval(timer); chart.timeScale().unsubscribeVisibleLogicalRangeChange(refresh); };
  }, [chart]);
  useEffect(() => {
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { pending.current = null; setDraft(null); setTool('cursor'); }
    };
    window.addEventListener('keydown', cancel);
    return () => window.removeEventListener('keydown', cancel);
  }, []);
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
    const b = anchor(event);
    if (!pending.current || !b) return;
    pending.current = { ...pending.current, b }; setDraft(pending.current);
  };
  const finish = () => {
    const item = pending.current;
    if (item && (item.tool === 'horizontal' || item.tool === 'text' || item.a.time !== item.b.time || item.a.price !== item.b.price)) {
      setDrawings(items => [...items, item]);
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
    const common = { stroke: item.color, strokeWidth: 2, fill: 'none' };
    const delta = item.b.price - item.a.price;
    const label = `${delta >= 0 ? '+' : ''}${delta.toFixed(decimals)} (${(delta / item.a.price * 100).toFixed(2)}%)`;
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    return <g key={item.id} data-drawing-id={item.id} style={{ cursor: tool === 'erase' ? 'crosshair' : undefined }}>
      {item.tool === 'horizontal' ? <><line {...common} x1={0} x2={width} y1={a.y} y2={a.y} /><text x={8} y={Math.max(14, a.y - 6)} fill={item.color}>{item.a.price.toFixed(decimals)}</text></>
        : item.tool === 'rectangle' ? <rect {...common} x={x} y={y} width={w} height={h} fill={item.color} fillOpacity={0.1} />
        : item.tool === 'ellipse' ? <ellipse {...common} cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} fill={item.color} fillOpacity={0.1} />
        : item.tool === 'text' ? <text x={a.x} y={a.y} fill={item.color}>{item.text}</text>
        : <><line {...common} x1={a.x} y1={a.y} x2={b.x} y2={b.y} strokeDasharray={item.tool === 'measure' ? '4 3' : undefined} />
          {item.tool === 'arrow' && <polyline {...common} points={`${b.x - 10 * Math.cos(angle - .5)},${b.y - 10 * Math.sin(angle - .5)} ${b.x},${b.y} ${b.x - 10 * Math.cos(angle + .5)},${b.y - 10 * Math.sin(angle + .5)}`} />}
          {item.tool === 'measure' && <text x={Math.min(x + 5, Math.max(0, width - 175))} y={Math.max(16, y - 8)} fill={item.color}>{label}</text>}
        </>}
    </g>;
  };
  return <>
    <div className="chart-drawing-rail" role="toolbar" aria-label="Chart drawing tools" aria-orientation="vertical">
      {tools.map(([id, Icon, label]) => <button key={id} type="button" title={label} aria-label={label} aria-pressed={tool === id} disabled={locked && id !== 'cursor'} onClick={() => { pending.current = null; setDraft(null); setTool(id); }}><Icon size={17} /></button>)}
      <input type="color" value={color} aria-label="Drawing color" title="Drawing color" onChange={event => setColor(event.target.value)} />
      <span className="drawing-divider" />
      <button type="button" title="Zoom in" aria-label="Zoom in" onClick={() => zoom(.75)}><ZoomIn size={17} /></button>
      <button type="button" title="Zoom out" aria-label="Zoom out" onClick={() => zoom(1.25)}><ZoomOut size={17} /></button>
      <button type="button" title="Fit chart" aria-label="Fit chart" onClick={() => chart.timeScale().fitContent()}><Maximize2 size={17} /></button>
      <button type="button" title="Undo last drawing" aria-label="Undo last drawing" disabled={locked || !drawings.length} onClick={() => setDrawings(items => items.slice(0, -1))}><Undo2 size={17} /></button>
      <button type="button" title={locked ? 'Unlock drawings' : 'Lock drawings'} aria-label={locked ? 'Unlock drawings' : 'Lock drawings'} aria-pressed={locked} onClick={() => { setLocked(value => !value); setTool('cursor'); pending.current = null; setDraft(null); }}>{locked ? <LockKeyhole size={17} /> : <UnlockKeyhole size={17} />}</button>
      <button type="button" title="Clear drawings" aria-label="Clear drawings" disabled={locked || !drawings.length} onClick={() => { setDrawings([]); pending.current = null; setDraft(null); }}><Trash2 size={17} /></button>
    </div>
    <span className="chart-drawing-session-status" role="status">{drawings.length} drawings · {storageAvailable ? 'Saved in this tab' : 'Storage unavailable; drawings temporary'}</span>
    {tool !== 'cursor' && !locked && <div className="chart-drawing-hint" role="status">{tool === 'erase' ? 'Tap a drawing to remove it' : tool === 'text' || tool === 'horizontal' ? 'Tap chart to place · Esc cancels' : 'Drag on chart to draw · Esc cancels'}{drawings.length >= 50 ? ' · 50 drawing limit' : ''}
      {tool === 'text' && <input aria-label="Chart note text" value={note} maxLength={80} onChange={event => setNote(event.target.value)} />}
    </div>}
    <svg ref={overlay} className="chart-drawing-overlay" width={width} height={height} aria-label="Chart annotations" style={{ left: chart.priceScale('left').width(), pointerEvents: !locked && tool !== 'cursor' ? 'auto' : 'none', touchAction: 'none' }} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={() => { pending.current = null; setDraft(null); }}>
      {drawings.map(renderDrawing)}{draft && renderDrawing(draft)}
    </svg>
  </>;
}
