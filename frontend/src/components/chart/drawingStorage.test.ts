// @vitest-environment happy-dom
import { afterEach, expect, it } from 'vitest';
import { readDrawings, saveDrawings, type Drawing } from './drawingStorage';
afterEach(() => sessionStorage.clear());
const drawing = { id:1,tool:'line',a:{time:1000,price:100},b:{time:1100,price:105},color:'#38bdf8',text:'Note' } as Drawing;
it('isolates markets and timeframes and clears only the selected chart', () => {
  saveDrawings('FX20:M5',[drawing]); saveDrawings('FX20:M1',[drawing]);
  expect(readDrawings('FX20:M5')).toEqual([drawing]);
  expect(readDrawings('FX40:M5')).toEqual([]);
  saveDrawings('FX20:M5',[]);
  expect(readDrawings('FX20:M5')).toEqual([]);
  expect(readDrawings('FX20:M1')).toEqual([drawing]);
});
it('rejects malformed anchors, oversized notes and duplicate ids', () => {
  sessionStorage.setItem('jqe:drawings:v1:weltrade:FX20:M5',JSON.stringify([drawing,drawing,
    {...drawing,id:2,a:{time:1000,price:-1}}, {...drawing,id:3,text:'x'.repeat(81)}]));
  expect(readDrawings('FX20:M5')).toEqual([drawing]);
});
it('handles corrupt storage without breaking chart rendering', () => {
  sessionStorage.setItem('jqe:drawings:v1:weltrade:FX20:M5','broken');
  expect(readDrawings('FX20:M5')).toEqual([]);
});
