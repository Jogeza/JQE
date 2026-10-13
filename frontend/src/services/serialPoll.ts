/** Completion-paced polling: never overlap slow requests or poll hidden tabs. */
export function serialPoll(task: () => Promise<boolean>, delayMs: number): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout>;
  const tick = async () => {
    if (stopped) return;
    let keepPolling = true;
    try {
      if (document.visibilityState !== 'hidden') keepPolling = await task();
    } finally {
      if (!stopped && keepPolling) timer = setTimeout(() => { void tick(); }, delayMs);
    }
  };
  timer = setTimeout(() => { void tick(); }, delayMs);
  return () => { stopped = true; clearTimeout(timer); };
}
