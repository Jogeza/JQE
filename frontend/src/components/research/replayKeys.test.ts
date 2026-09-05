import { describe, expect, it } from 'vitest';
import { replayActionForKey } from './replayKeys';

describe('replay keyboard controls', () => {
  it.each([['ArrowLeft', 'PREVIOUS'], ['ArrowRight', 'NEXT'], [' ', 'TOGGLE'], ['Enter', null]])(
    'maps %s without claiming unrelated keys', (key, action) => expect(replayActionForKey(key)).toBe(action));
});
