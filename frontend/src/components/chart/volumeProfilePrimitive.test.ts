import { describe, expect, it } from 'vitest';
import { adaptVolumeProfile, isValidProfileRange, volumeProfileLabel } from './volumeProfilePrimitive';
import type { VolumeProfileSnapshotDTO } from '../../types/research';

const snapshot: VolumeProfileSnapshotDTO = {
  dataset_identity: 'sha256:test', range_start_index: 2, range_end_index: 4,
  start_time: '2026-01-01T00:00:00Z', end_time: '2026-01-01T00:30:00Z', candle_count: 3,
  volume_type: 'TICK_VOLUME', volume_source: 'broker tick count', profile_low: '0.1', profile_high: '0.3',
  total_volume: '6', bin_size: '0.1', bin_count: 2, value_area_fraction: '0.70',
  allocation_method: 'UNIFORM_RANGE_OVERLAP_V1', algorithm_version: 'frvp-contract-v1',
  point_of_control: '0.15', value_area_high: '0.3', value_area_low: '0.1',
  range_has_gaps: false, gap_count: 0,
  bins: [{ low: '0.1', high: '0.2', volume: '4' }, { low: '0.2', high: '0.3', volume: '2' }],
};

describe('volume profile presentation adapter', () => {
  it('maps backend-computed bins and levels without financial recalculation', () => {
    expect(adaptVolumeProfile(snapshot)).toEqual({
      bins: [{ low: 0.1, high: 0.2, volume: 4 }, { low: 0.2, high: 0.3, volume: 2 }],
      poc: 0.15, vah: 0.3, val: 0.1, maxVolume: 4,
    });
  });

  it.each([
    ['REAL_VOLUME', 'Real Volume Profile'], ['TICK_VOLUME', 'Tick Volume Profile'],
    ['BROKER_VOLUME', 'Broker Volume Profile'], ['SIMULATED_VOLUME', 'Simulated Volume Profile'],
  ])('labels %s semantics explicitly', (type, label) => expect(volumeProfileLabel(type)).toBe(label));

  it('makes unavailable and unknown semantics explicit', () => {
    expect(volumeProfileLabel('UNAVAILABLE')).toContain('unavailable');
    expect(volumeProfileLabel('UNKNOWN')).toContain('UNKNOWN');
  });

  it('enforces the replay range guard as frontend defense in depth', () => {
    expect(isValidProfileRange(0, 4, 4)).toBe(true);
    expect(isValidProfileRange(0, 5, 4)).toBe(false);
    expect(isValidProfileRange(3, 2, 4)).toBe(false);
    expect(isValidProfileRange(0.5, 2, 4)).toBe(false);
  });
});
