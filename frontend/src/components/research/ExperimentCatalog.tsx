import { useEffect, useState } from 'react';
import { jqeApi } from '../../services/api';
import type {
  ExperimentComparisonResponse,
  ExperimentDetailDTO,
  ExperimentListFilters,
  ExperimentListResponse,
  ExperimentStatus,
} from '../../types/api';
import { IdentityRow } from './IdentityRow';
import {
  canPageNext,
  catalogRange,
  classificationLabels,
  displayValue,
  filterRequest,
  toggleComparisonSelection,
} from './experimentCatalogLogic';

const PAGE_SIZE = 25;
const emptyFilters: ExperimentListFilters = {};

function dateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString();
}

function dateRange(start: string, end: string) {
  return `${dateTime(start)} \u2013 ${dateTime(end)}`;
}

function Reproducibility({ status, fully }: { status: ExperimentStatus; fully: boolean }) {
  const label = fully ? 'Fully reproducible' : status === 'LEGACY_INCOMPLETE' ? 'Legacy / incomplete' : 'Identity unavailable';
  return <span className={`reproducibility-state ${fully ? 'complete' : 'incomplete'}`}>{label}</span>;
}

function FactGrid({ values }: { values: Record<string, unknown> }) {
  return (
    <dl className="experiment-fact-grid">
      {Object.entries(values).map(([label, value]) => (
        <div key={label}>
          <dt>{label.replace(/_/g, ' ')}</dt>
          <dd className={value == null ? 'unavailable' : ''}>
            {typeof value === 'object' && value !== null
              ? <pre>{displayValue(value)}</pre>
              : displayValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function DetailPanel({ detail, loading, error, onClose }: {
  detail: ExperimentDetailDTO | null; loading: boolean; error: string | null; onClose: () => void;
}) {
  return (
    <aside className="experiment-detail" aria-label="Experiment detail" aria-live="polite">
      <div className="experiment-detail-heading">
        <div><span>Authoritative record</span><strong>{detail?.experiment_id ?? 'Experiment detail'}</strong></div>
        <button className="btn-quant" type="button" onClick={onClose} aria-label="Close experiment detail">Close</button>
      </div>
      {loading && <p className="experiment-state">Loading experiment detail\u2026</p>}
      {error && <p className="experiment-state error" role="alert">{error}</p>}
      {detail && !loading && (
        <div className="experiment-detail-content">
          <section><h3>Observation</h3><FactGrid values={{ experiment_id: detail.experiment_id, created_at: dateTime(detail.created_at), status: detail.status }} /></section>
          <section><h3>Dataset</h3><FactGrid values={{ symbol: detail.symbol, timeframe: detail.timeframe, partition: detail.partition, effective_range: dateRange(detail.partition_first_candle, detail.partition_last_candle), candle_count: detail.partition_candle_count }} /><IdentityRow label="Dataset" value={detail.dataset_hash} /></section>
          <section><h3>Run configuration</h3><FactGrid values={{ strategy_name: detail.strategy_name, ...detail.configuration }} /><IdentityRow label="Run" value={detail.run_fingerprint} /></section>
          <section><h3>Result identity</h3><IdentityRow label="Result" value={detail.result_hash} /></section>
          <section><h3>Versioning</h3><FactGrid values={{ persistence_schema: detail.schema_version, engine_version: detail.engine_version, identity_schema_version: detail.identity_schema_version }} /></section>
          <section><h3>Factual metrics</h3><FactGrid values={detail.metrics} /></section>
          <section><h3>Provenance</h3><FactGrid values={detail.provenance} /></section>
        </div>
      )}
    </aside>
  );
}

function ComparisonPanel({ comparison, loading, error, onClose }: {
  comparison: ExperimentComparisonResponse | null; loading: boolean; error: string | null; onClose: () => void;
}) {
  const facts = comparison ? {
    controlled_comparison: comparison.controlled_comparison,
    both_fully_reproducible: comparison.both_fully_reproducible,
    same_dataset: comparison.same_dataset,
    same_run_configuration: comparison.same_run_configuration,
    same_result: comparison.same_result,
    same_strategy_configuration: comparison.same_strategy_configuration,
    same_risk_configuration: comparison.same_risk_configuration,
    same_execution_assumptions: comparison.same_execution_assumptions,
  } : {};
  return (
    <aside className="experiment-detail experiment-comparison" aria-label="Experiment comparison" aria-live="polite">
      <div className="experiment-detail-heading"><div><span>Backend-authoritative comparison</span><strong>Experiment comparison</strong></div><button className="btn-quant" type="button" onClick={onClose}>Close</button></div>
      {loading && <p className="experiment-state">Loading authoritative comparison\u2026</p>}
      {error && <p className="experiment-state error" role="alert">{error}</p>}
      {comparison && !loading && <div className="experiment-detail-content">
        <section className="comparison-classification"><span>Classification</span><strong>{classificationLabels[comparison.classification]}</strong><small>{comparison.classification}</small></section>
        <section><h3>Compared observations</h3><FactGrid values={{ left: comparison.left_experiment_id, right: comparison.right_experiment_id }} /></section>
        <section><h3>Reproducibility facts</h3><FactGrid values={facts} /></section>
        <section><h3>Metric deltas (left {'\u2212'} right)</h3><FactGrid values={comparison.metric_deltas} /></section>
      </div>}
    </aside>
  );
}

export function ExperimentCatalog() {
  const [draft, setDraft] = useState<ExperimentListFilters>(emptyFilters);
  const [filters, setFilters] = useState<ExperimentListFilters>(emptyFilters);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<ExperimentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ExperimentDetailDTO | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [comparison, setComparison] = useState<ExperimentComparisonResponse | null>(null);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null);
    jqeApi.listExperiments({ ...filters, limit: PAGE_SIZE, offset }, controller.signal)
      .then(setData)
      .catch((reason) => { if (!controller.signal.aborted) setError(String(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [filters, offset]);

  useEffect(() => {
    if (!detailId) return;
    const controller = new AbortController();
    setDetail(null); setDetailError(null); setDetailLoading(true);
    jqeApi.getExperiment(detailId, controller.signal).then(setDetail)
      .catch((reason) => { if (!controller.signal.aborted) setDetailError(String(reason)); })
      .finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [detailId]);

  const apply = () => {
    const request = filterRequest(draft);
    setOffset(request.offset);
    setFilters(request.filters);
  };
  const clear = () => { setDraft(emptyFilters); setOffset(0); setFilters(emptyFilters); };
  const compare = () => {
    if (selected.length !== 2) return;
    setComparison(null); setComparisonError(null); setComparisonLoading(true);
    jqeApi.compareExperiments(selected[0], selected[1]).then(setComparison)
      .catch((reason) => setComparisonError(String(reason))).finally(() => setComparisonLoading(false));
  };
  const hasFilters = Object.keys(filters).length > 0;

  return (
    <section className="experiment-catalog" aria-labelledby="experiment-catalog-title">
      <header className="experiment-catalog-header"><div><span className="research-eyebrow">Persisted deterministic research runs</span><h2 id="experiment-catalog-title">Durable experiment catalog</h2><p>Inspect reproducibility identities and compare two recorded observations without changing them.</p></div><div className="comparison-actions"><span aria-live="polite">{selected.length} of 2 selected</span><button className="btn-quant btn-quant-primary" disabled={selected.length !== 2 || comparisonLoading} onClick={compare}>Compare selected</button><button className="btn-quant" disabled={!selected.length} onClick={() => setSelected([])}>Clear selection</button></div></header>
      <form className="experiment-filters" onSubmit={(event) => { event.preventDefault(); apply(); }}>
        <label><span>Symbol</span><input value={draft.symbol ?? ''} onChange={(e) => setDraft({ ...draft, symbol: e.target.value })} /></label>
        <label><span>Timeframe</span><input value={draft.timeframe ?? ''} onChange={(e) => setDraft({ ...draft, timeframe: e.target.value })} /></label>
        <label><span>Status</span><select value={draft.status ?? ''} onChange={(e) => setDraft({ ...draft, status: (e.target.value || undefined) as ExperimentStatus | undefined })}><option value="">Any status</option><option value="COMPLETED">Completed</option><option value="LEGACY_INCOMPLETE">Legacy / incomplete</option></select></label>
        <label><span>Reproducibility</span><select value={draft.fully_reproducible === undefined ? '' : String(draft.fully_reproducible)} onChange={(e) => setDraft({ ...draft, fully_reproducible: e.target.value === '' ? undefined : e.target.value === 'true' })}><option value="">Any state</option><option value="true">Fully reproducible</option><option value="false">Not fully reproducible</option></select></label>
        <label className="identity-filter"><span>Dataset hash</span><input value={draft.dataset_hash ?? ''} onChange={(e) => setDraft({ ...draft, dataset_hash: e.target.value })} /></label>
        <label className="identity-filter"><span>Run fingerprint</span><input value={draft.run_fingerprint ?? ''} onChange={(e) => setDraft({ ...draft, run_fingerprint: e.target.value })} /></label>
        <div className="filter-actions"><button className="btn-quant btn-quant-primary" type="submit">Apply filters</button><button className="btn-quant" type="button" onClick={clear}>Reset</button></div>
      </form>

      {data?.issues.length ? <div className="catalog-warning" role="status"><strong>Some catalog records could not be read.</strong>{data.issues.map((issue) => <span key={`${issue.file_name}-${issue.message}`}>{issue.file_name} {'\u00b7'} {issue.code} {'\u00b7'} {issue.message}</span>)}</div> : null}
      {loading && !data && <p className="experiment-state">Loading persisted experiments\u2026</p>}
      {error && <p className="experiment-state error" role="alert">{error}</p>}
      {!loading && !error && data?.total === 0 && <div className="experiment-state empty"><strong>{hasFilters ? 'No experiments match the current filters.' : 'No persisted training experiments are available yet.'}</strong><span>{hasFilters ? 'Adjust or reset the filters to inspect other records.' : 'Durable research observations will appear here when available.'}</span></div>}
      {data && data.experiments.length > 0 && <>
        <div className="experiment-table-wrap"><table className="quant-table experiment-table"><thead><tr><th>Compare</th><th>Experiment</th><th>Market</th><th>Created</th><th>Dataset range</th><th>Candles</th><th>Status</th><th>Reproducibility</th><th>Total return</th><th>Trades</th></tr></thead><tbody>{data.experiments.map((item) => {
          const checked = selected.includes(item.experiment_id);
          return <tr key={item.experiment_id} className={checked ? 'selected' : ''}><td><input type="checkbox" aria-label={`Select ${item.experiment_id} for comparison`} checked={checked} disabled={!checked && selected.length === 2} onChange={() => setSelected(toggleComparisonSelection(selected, item.experiment_id))} /></td><td><button className="experiment-open" onClick={() => setDetailId(item.experiment_id)}>{item.experiment_id}</button><div className="summary-identities"><IdentityRow label="Dataset" value={item.dataset_hash} /><IdentityRow label="Run" value={item.run_fingerprint} /></div></td><td><strong>{item.symbol}</strong><small>{item.timeframe}</small></td><td>{dateTime(item.created_at)}</td><td>{dateRange(item.effective_start, item.effective_end)}</td><td>{item.candle_count}</td><td><span className={`badge ${item.status === 'COMPLETED' ? 'badge-green' : 'badge-neutral'}`}>{item.status === 'COMPLETED' ? 'Completed' : 'Legacy / incomplete'}</span></td><td><Reproducibility status={item.status} fully={item.fully_reproducible} /></td><td>{displayValue(item.total_return)}</td><td>{displayValue(item.total_trades)}</td></tr>;
        })}</tbody></table></div>
        <div className="experiment-cards">{data.experiments.map((item) => { const checked = selected.includes(item.experiment_id); return <article key={item.experiment_id} className={checked ? 'selected' : ''}><div className="experiment-card-top"><label><input type="checkbox" checked={checked} disabled={!checked && selected.length === 2} onChange={() => setSelected(toggleComparisonSelection(selected, item.experiment_id))} /><span>Compare</span></label><Reproducibility status={item.status} fully={item.fully_reproducible} /></div><button className="experiment-open" onClick={() => setDetailId(item.experiment_id)}>{item.experiment_id}</button><strong>{item.symbol} {'\u00b7'} {item.timeframe}</strong><small>{dateTime(item.created_at)}</small><FactGrid values={{ dataset_range: dateRange(item.effective_start, item.effective_end), candle_count: item.candle_count, status: item.status === 'COMPLETED' ? 'Completed' : 'Legacy / incomplete', total_return: item.total_return, total_trades: item.total_trades }} /><IdentityRow label="Dataset" value={item.dataset_hash} /><IdentityRow label="Run" value={item.run_fingerprint} /></article>; })}</div>
        <footer className="experiment-pagination"><span>{catalogRange(data.offset, data.limit, data.total)}</span><div><button className="btn-quant" disabled={data.offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button><button className="btn-quant" disabled={!canPageNext(data.offset, data.limit, data.total) || loading} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button></div></footer>
      </>}
      {detailId && <DetailPanel detail={detail} loading={detailLoading} error={detailError} onClose={() => setDetailId(null)} />}
      {(comparisonLoading || comparison || comparisonError) && <ComparisonPanel comparison={comparison} loading={comparisonLoading} error={comparisonError} onClose={() => { setComparison(null); setComparisonError(null); }} />}
    </section>
  );
}
