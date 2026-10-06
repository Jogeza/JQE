import type { Time } from 'lightweight-charts';

export type Tool = 'cursor' | 'line' | 'horizontal' | 'arrow' | 'rectangle' | 'ellipse' | 'measure' | 'text' | 'erase';
export type Anchor = { time: Time; price: number };
export type Drawing = { id: number; tool: Tool; a: Anchor; b: Anchor; color: string; text: string };
const drawable = new Set(['line','horizontal','arrow','rectangle','ellipse','measure','text']);
const key = (scope: string) => `jqe:drawings:v1:weltrade:${scope}`;
function validAnchor(value: unknown): value is Anchor {
  if (!value || typeof value !== 'object') return false;
  const a = value as Anchor;
  return typeof a.time === 'number' && Number.isFinite(a.time) && a.time > 0
    && typeof a.price === 'number' && Number.isFinite(a.price) && a.price > 0;
}
export function readDrawings(scope: string): Drawing[] {
  try {
    const raw = sessionStorage.getItem(key(scope));
    if (!raw || raw.length > 40000) return [];
    const data: unknown = JSON.parse(raw);
    if (!Array.isArray(data) || data.length > 50) return [];
    const ids = new Set<number>();
    return data.filter((d): d is Drawing => {
      if (!d || typeof d !== 'object' || !Number.isSafeInteger(d.id) || d.id < 1 || ids.has(d.id)
          || !drawable.has(d.tool) || !validAnchor(d.a) || !validAnchor(d.b)
          || typeof d.color !== 'string' || !/^#[0-9a-f]{6}$/i.test(d.color)
          || typeof d.text !== 'string' || d.text.length > 80) return false;
      ids.add(d.id); return true;
    });
  } catch { return []; }
}
export function saveDrawings(scope: string, drawings: Drawing[]): boolean {
  try {
    if (drawings.length) sessionStorage.setItem(key(scope), JSON.stringify(drawings));
    else sessionStorage.removeItem(key(scope));
    return true;
  } catch { return false; }
}
