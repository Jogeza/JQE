// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest';
import { serialPoll } from './serialPoll';

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it('waits for slow requests to finish and stops without rescheduling', async () => {
  vi.useFakeTimers();
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  let resolve!: (value: boolean) => void;
  const task = vi.fn(() => new Promise<boolean>(done => { resolve = done; }));
  const stop = serialPoll(task, 1000);
  await vi.advanceTimersByTimeAsync(5000);
  expect(task).toHaveBeenCalledTimes(1);
  stop(); resolve(true);
  await vi.advanceTimersByTimeAsync(5000);
  expect(task).toHaveBeenCalledTimes(1);
});

it('pauses hidden tabs and stops on terminal task result', async () => {
  vi.useFakeTimers();
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
  const task = vi.fn().mockResolvedValue(false);
  const stop = serialPoll(task, 1000);
  await vi.advanceTimersByTimeAsync(3000);
  expect(task).not.toHaveBeenCalled();
  visibility.mockReturnValue('visible');
  await vi.advanceTimersByTimeAsync(4000);
  expect(task).toHaveBeenCalledTimes(1);
  stop();
});
