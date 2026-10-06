/** Bound observation traffic and stop queued work after a market is superseded. */
export async function settleBounded<T>(
  requests: Array<() => Promise<T>>, signal: AbortSignal, concurrency = 4,
): Promise<PromiseSettledResult<T>[]> {
  const results: PromiseSettledResult<T>[] = new Array(requests.length);
  let next = 0;
  const worker = async () => {
    while (next < requests.length) {
      const index = next++;
      try {
        if (signal.aborted) throw new DOMException('Observation superseded', 'AbortError');
        results[index] = { status: 'fulfilled', value: await requests[index]() };
      } catch (reason) {
        results[index] = { status: 'rejected', reason };
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(Math.max(1, concurrency), requests.length) }, worker));
  return results;
}
