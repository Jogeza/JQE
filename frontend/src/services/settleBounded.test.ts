import { expect, it } from 'vitest';
import { settleBounded } from './settleBounded';

it('limits outstanding requests, retains result order and continues after failures', async () => {
  let active = 0, maximum = 0;
  const releases: Array<() => void> = [];
  const run = settleBounded(Array.from({length: 9}, (_, index) => async () => {
    maximum = Math.max(maximum, ++active);
    await new Promise<void>(resolve => releases.push(resolve));
    active--;
    if (index === 2) throw new Error('offline');
    return index;
  }), new AbortController().signal);
  expect(releases).toHaveLength(4);
  while (releases.length) {
    releases.shift()!();
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  }
  const results = await run;
  expect(maximum).toBe(4);
  expect(results[2].status).toBe('rejected');
  expect(results[8]).toEqual({status:'fulfilled', value:8});
});

it('does not start queued requests when the selected market is superseded', async () => {
  const controller = new AbortController();
  let started = 0;
  let release!: () => void;
  const run = settleBounded(Array.from({length:3}, () => async () => {
    started++;
    await new Promise<void>(resolve => { release = resolve; });
  }), controller.signal, 1);
  controller.abort(); release();
  const results = await run;
  expect(started).toBe(1);
  expect(results.slice(1).map(result => result.status)).toEqual(['rejected', 'rejected']);
});
