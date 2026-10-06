import { describe, expect, it } from 'vitest';
import { ObservationSchedule, RESOURCE_OFFSETS_MS } from './observationSchedule';

describe('observation cadence', () => {
  it('keeps chart/heartbeat current without repeatedly fetching ancillary resources', () => {
    const schedule = new ObservationSchedule();
    for (const name of ['activeAnalysis', 'observationHealth', 'watchlist']) {
      expect(schedule.due(name, 0)).toBe(true);
      schedule.completed(name, 0, true);
      expect(schedule.due(name, 4000)).toBe(false);
    }
    expect(schedule.due('activeAnalysis', 15000)).toBe(true);
    expect(schedule.due('observationHealth', 15000)).toBe(true);
    const watchlistNext = 60_000 + RESOURCE_OFFSETS_MS.watchlist;
    expect(schedule.due('watchlist', watchlistNext - 1)).toBe(false);
    expect(schedule.due('watchlist', watchlistNext)).toBe(true);
  });
  it('backs off failures to two minutes and resets after recovery', () => {
    const schedule = new ObservationSchedule();
    schedule.completed('activeAnalysis', 0, false);
    expect(schedule.due('activeAnalysis', 29999)).toBe(false);
    schedule.completed('activeAnalysis', 30000, false);
    expect(schedule.due('activeAnalysis', 89999)).toBe(false);
    schedule.completed('activeAnalysis', 90000, false);
    expect(schedule.due('activeAnalysis', 209999)).toBe(false);
    schedule.completed('activeAnalysis', 210000, true);
    expect(schedule.due('activeAnalysis', 225000)).toBe(true);
  });
  it('staggers steady-state refreshes across distinct four-second ticks', () => {
    const critical = ['activeAnalysis', 'terminalObservation', 'observationHealth', 'risk', 'safety', 'execution'];
    const ancillary = ['brokerStatus', 'watchlist', 'monitoring', 'watchlistCapUsage', 'notificationStatus', 'assistantStatus'];
    const schedule = new ObservationSchedule();
    const nextOf = (name: string) => (critical.includes(name) ? 15_000 : 60_000) + (RESOURCE_OFFSETS_MS[name] ?? 0);
    for (const name of [...critical, ...ancillary]) {
      schedule.completed(name, 0, true);
      expect(schedule.due(name, nextOf(name) - 1)).toBe(false);
      expect(schedule.due(name, nextOf(name))).toBe(true);
    }
    const tick = (name: string) => Math.ceil(nextOf(name) / 4000);
    expect(new Set(ancillary.map(tick)).size).toBe(ancillary.length);
    const grouped = new Map<number, string[]>();
    for (const name of [...critical, ...ancillary]) grouped.set(tick(name), [...(grouped.get(tick(name)) ?? []), name]);
    for (const group of grouped.values()) expect(group.length).toBeLessThanOrEqual(2);
  });
});
