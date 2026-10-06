import { describe, expect, it } from 'vitest';
import { ObservationSchedule } from './observationSchedule';

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
    expect(schedule.due('watchlist', 59999)).toBe(false);
    expect(schedule.due('watchlist', 60000)).toBe(true);
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
});
