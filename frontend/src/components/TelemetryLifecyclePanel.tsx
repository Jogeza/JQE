import { TelemetryLifecycle } from '../services/telemetryLifecycle';

const utc = (value: string | Date | null | undefined) => {
  if (!value) return 'UNAVAILABLE';
  const date = value instanceof Date ? value : new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString() : 'UNAVAILABLE';
};

export const TelemetryLifecyclePanel: React.FC<{ lifecycle: TelemetryLifecycle }> = ({ lifecycle }) => {
  const assessment = lifecycle.assessment;
  const snapshot = lifecycle.snapshot;
  const blocking = assessment?.execution_authorization.reason_codes?.join(', ') || lifecycle.reason;
  return (
    <section className={`telemetry-lifecycle-panel lifecycle-${lifecycle.state.toLowerCase()}`} aria-label="Telemetry lifecycle status">
      <header><span>Monitoring lifecycle</span><strong>{lifecycle.state}</strong></header>
      <dl>
        <div><dt>Backend</dt><dd>{lifecycle.state === 'OFFLINE' ? 'OFFLINE' : snapshot?.backend.state ?? lifecycle.state}</dd></div>
        <div><dt>Last contact</dt><dd>{utc(lifecycle.lastSuccessfulContact)}</dd></div>
        <div><dt>Assessment</dt><dd>{utc(assessment?.observed_at)}</dd></div>
        <div><dt>Expiry</dt><dd>{utc(assessment?.expires_at)}</dd></div>
        <div><dt>Market</dt><dd>{assessment ? `${assessment.symbol} / ${assessment.timeframe}` : 'UNAVAILABLE'}</dd></div>
        <div><dt>Source</dt><dd>{assessment?.dataset_source ?? assessment?.data_freshness.source ?? 'UNAVAILABLE'}</dd></div>
        <div className="lifecycle-wide"><dt>Dataset</dt><dd>{assessment?.dataset_hash ?? 'UNAVAILABLE'}</dd></div>
        <div className="lifecycle-wide"><dt>Blocking reason</dt><dd>{blocking}</dd></div>
        <div><dt>Execution enabled</dt><dd>{snapshot?.broker_execution_enabled === false ? 'FALSE' : 'UNAVAILABLE'}</dd></div>
        <div><dt>Simulation starts</dt><dd>{snapshot ? `${snapshot.simulation_submissions.utc_count}/${snapshot.simulation_submissions.limit}` : 'UNAVAILABLE'}</dd></div>
      </dl>
    </section>
  );
};
