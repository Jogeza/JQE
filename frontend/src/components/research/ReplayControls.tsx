import type { KeyboardEvent } from 'react';
import { replayActionForKey } from './replayKeys';

interface Props {
  cursor: number;
  total: number;
  playing: boolean;
  speed: number;
  setCursor: (value: number | ((current: number) => number)) => void;
  setPlaying: (value: boolean | ((current: boolean) => boolean)) => void;
  setSpeed: (value: number) => void;
}

export function ReplayControls({
  cursor,
  total,
  playing,
  speed,
  setCursor,
  setPlaying,
  setSpeed,
}: Props) {
  const apply = (action: ReturnType<typeof replayActionForKey>) => {
    if (action === 'PREVIOUS') {
      setPlaying(false);
      setCursor((value) => Math.max(0, value - 1));
    }
    if (action === 'NEXT') {
      setPlaying(false);
      setCursor((value) => Math.min(total - 1, value + 1));
    }
    if (action === 'TOGGLE') setPlaying((value) => !value);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const action = replayActionForKey(event.key);
    if (action) {
      event.preventDefault();
      apply(action);
    }
  };

  return (
    <div
      className="research-replay-toolbar"
      tabIndex={0}
      onKeyDown={onKeyDown}
      aria-label="Market replay controls"
      title="Focus here: Left/Right step, Space plays or pauses"
    >
      <button
        onClick={() => {
          setPlaying(false);
          setCursor(0);
        }}
        disabled={cursor === 0}
        aria-label="Replay to start"
        title="Rewind to beginning"
      >
        |◀
      </button>
      <button
        onClick={() => apply('PREVIOUS')}
        disabled={cursor === 0}
        aria-label="Previous candle"
        title="Step back (←)"
      >
        ◀
      </button>
      <button
        onClick={() => apply('TOGGLE')}
        style={{
          fontWeight: 600,
          color: playing ? 'var(--quant-cyan)' : 'var(--text-primary)',
          minWidth: '52px',
        }}
      >
        {playing ? 'Pause' : 'Play'}
      </button>
      <button
        onClick={() => apply('NEXT')}
        disabled={cursor >= total - 1}
        aria-label="Next candle"
        title="Step forward (→)"
      >
        ▶
      </button>

      <select
        aria-label="Playback speed"
        value={speed}
        onChange={(event) => setSpeed(Number(event.target.value))}
      >
        {[1, 5, 20].map((value) => (
          <option value={value} key={value}>
            {value}×
          </option>
        ))}
      </select>

      <span style={{ fontWeight: 600, color: 'var(--text-primary)', marginLeft: '4px' }}>
        {cursor + 1} / {total}
      </span>

      <div style={{ marginLeft: 'auto', display: 'flex', gap: '3px', alignItems: 'center' }}>
        <kbd>←</kbd>
        <kbd>→</kbd>
        <kbd>Space</kbd>
      </div>
    </div>
  );
}
