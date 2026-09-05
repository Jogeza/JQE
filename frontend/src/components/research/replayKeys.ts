export type ReplayKeyAction = 'PREVIOUS' | 'NEXT' | 'TOGGLE' | null;

export function replayActionForKey(key: string): ReplayKeyAction {
  if (key === 'ArrowLeft') return 'PREVIOUS';
  if (key === 'ArrowRight') return 'NEXT';
  if (key === ' ') return 'TOGGLE';
  return null;
}
