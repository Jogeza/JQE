import { useEffect, useReducer, useRef, useState } from 'react';
import { isCached, marketGroups, searchMarkets } from '../components/chart/marketCatalogueAdapter';
import { MarketSidebar } from '../components/research/MarketSidebar';
import { ResearchChartWorkspace } from '../components/research/ResearchChartWorkspace';
import { ExperimentCatalog } from '../components/research/ExperimentCatalog';
import {
  createResearchWorkspace,
  initialResearchLayout,
  type ResearchWorkspaceAction,
  type ResearchWorkspaceId,
  type ResearchWorkspaceState,
  updateResearchLayout,
  updateResearchWorkspace,
} from '../components/research/researchWorkspace';
import {
  loadResearchPreferences,
  saveResearchPreferences,
  toggleFavourite,
  validateResearchPreferences,
} from '../components/research/researchPreferences';
import type { MarketInstrumentDTO, ResearchMarketsDTO } from '../types/research';

async function loadMarkets(): Promise<ResearchMarketsDTO> {
  const response = await fetch('/api/v1/research/markets');
  if (!response.ok) throw new Error(`Research catalogue failed (${response.status})`);
  return response.json();
}

interface WorkspacePair {
  primary: ResearchWorkspaceState | null;
  comparison: ResearchWorkspaceState | null;
}
type WorkspacePairAction = {
  workspaceId: ResearchWorkspaceId;
  action: ResearchWorkspaceAction;
  seed?: MarketInstrumentDTO;
};

function workspacePairReducer(state: WorkspacePair, change: WorkspacePairAction): WorkspacePair {
  const current =
    state[change.workspaceId] ??
    (change.seed ? createResearchWorkspace(change.workspaceId, change.seed) : null);
  return current
    ? { ...state, [change.workspaceId]: updateResearchWorkspace(current, change.action) }
    : state;
}

export function ResearchPage() {
  const [researchView, setResearchView] = useState<'charts' | 'experiments'>('charts');
  const [markets, setMarkets] = useState<ResearchMarketsDTO | null>(null);
  const [workspaces, dispatchPair] = useReducer(workspacePairReducer, {
    primary: null,
    comparison: null,
  });
  const [layout, dispatchLayout] = useReducer(updateResearchLayout, initialResearchLayout);
  const { comparisonEnabled, activeWorkspaceId } = layout;
  const [category, setCategory] = useState('All');
  const [search, setSearch] = useState('');
  const [favourites, setFavourites] = useState<string[]>([]);
  const [catalogueError, setCatalogueError] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadMarkets()
      .then((result) => {
        const preferences = validateResearchPreferences(
          loadResearchPreferences(),
          result.catalogue.instruments
        );
        const fallback = result.catalogue.instruments[0];
        if (!fallback) throw new Error('Research catalogue contains no instruments');
        const primary =
          result.catalogue.instruments.find(
            (item) => item.provider_symbol === preferences.selectedProviderSymbol
          ) ?? fallback;
        const comparison =
          result.catalogue.instruments.find(
            (item) => item.provider_symbol === preferences.comparisonProviderSymbol
          ) ??
          result.catalogue.instruments.find(
            (item) => item.provider_symbol !== primary.provider_symbol
          ) ??
          primary;
        dispatchPair({
          workspaceId: 'primary',
          seed: primary,
          action: { type: 'select-instrument', instrument: primary },
        });
        dispatchPair({
          workspaceId: 'primary',
          seed: primary,
          action: { type: 'select-timeframe', timeframe: preferences.timeframe ?? 'M15' },
        });
        dispatchPair({
          workspaceId: 'comparison',
          seed: comparison,
          action: { type: 'select-instrument', instrument: comparison },
        });
        dispatchPair({
          workspaceId: 'comparison',
          seed: comparison,
          action: {
            type: 'select-timeframe',
            timeframe: preferences.comparisonTimeframe ?? 'H1',
          },
        });
        dispatchLayout({
          type: 'set-comparison',
          enabled: preferences.comparisonEnabled ?? false,
        });
        setFavourites(preferences.favourites);
        if (
          preferences.category === 'All' ||
          (preferences.category && marketGroups(result).includes(preferences.category))
        )
          setCategory(preferences.category);
        setMarkets(result);
      })
      .catch((reason) => setCatalogueError(String(reason)));
  }, []);

  useEffect(() => {
    if (!markets || !workspaces.primary || !workspaces.comparison) return;
    saveResearchPreferences({
      favourites,
      category,
      comparisonEnabled,
      selectedProviderSymbol: workspaces.primary.instrument.provider_symbol,
      timeframe: workspaces.primary.timeframe,
      comparisonProviderSymbol: workspaces.comparison.instrument.provider_symbol,
      comparisonTimeframe: workspaces.comparison.timeframe,
    });
  }, [markets, workspaces, favourites, category, comparisonEnabled]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const editing =
        target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA' || target?.tagName === 'SELECT';
      if (
        ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') ||
        (event.key === '/' && !editing)
      ) {
        event.preventDefault();
        searchRef.current?.focus();
        searchRef.current?.select();
      }
      if (event.key === 'Escape' && document.activeElement === searchRef.current) {
        setSearch('');
        searchRef.current?.blur();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const primary = workspaces.primary;
  const comparison = workspaces.comparison;
  if (!markets || !primary || !comparison)
    return (
      <div className="dashboard-page-container research-terminal">
        <div className="research-context-bar">
          <div><span className="research-eyebrow">Research workspace</span><strong>Explore historical market behaviour</strong><span>Charts and durable experiment observations remain separate research views.</span></div>
        </div>
        <nav className="research-view-tabs" aria-label="Research views">
          <button aria-current={researchView === 'charts' ? 'page' : undefined} onClick={() => setResearchView('charts')}>Chart workspace</button>
          <button aria-current={researchView === 'experiments' ? 'page' : undefined} onClick={() => setResearchView('experiments')}>Experiment catalog</button>
        </nav>
        {researchView === 'charts' && <p role={catalogueError ? 'alert' : undefined} style={{ color: catalogueError ? 'var(--quant-red)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {catalogueError ?? 'Loading Research Terminal\u2026'}
        </p>}
        {researchView === 'experiments' && <ExperimentCatalog />}
      </div>
    );

  const pair = { primary, comparison };
  const active = pair[activeWorkspaceId];
  const visibleMarkets = searchMarkets(markets.catalogue.instruments, '', category);
  const matchedMarkets = searchMarkets(markets.catalogue.instruments, search, category);
  const selectionOptions = matchedMarkets.some(
    (item) => item.provider_symbol === active.instrument.provider_symbol
  )
    ? matchedMarkets
    : [active.instrument, ...matchedMarkets];
  const dispatch = (workspaceId: ResearchWorkspaceId) => (action: ResearchWorkspaceAction) =>
    dispatchPair({ workspaceId, action });
  const selectMarket = (instrument: MarketInstrumentDTO) =>
    dispatchPair({
      workspaceId: activeWorkspaceId,
      action: { type: 'select-instrument', instrument },
    });

  return (
    <div className="dashboard-page-container research-terminal">
      <div className="research-context-bar">
        <div>
          <span className="research-eyebrow">Research workspace</span>
          <strong>Explore historical market behaviour</strong>
          <span>
            {comparisonEnabled ? 'Compare two independent datasets side by side.' : 'Inspect cached data, indicators, and replay outcomes.'}
          </span>
        </div>
        <button
          hidden={researchView !== 'charts'}
          aria-pressed={comparisonEnabled}
          onClick={() => dispatchLayout({ type: 'set-comparison', enabled: !comparisonEnabled })}
        >
          {comparisonEnabled ? 'Single workspace' : 'Compare workspaces'}
        </button>
      </div>

      <nav className="research-view-tabs" aria-label="Research views">
        <button aria-current={researchView === 'charts' ? 'page' : undefined} onClick={() => setResearchView('charts')}>Chart workspace</button>
        <button aria-current={researchView === 'experiments' ? 'page' : undefined} onClick={() => setResearchView('experiments')}>Experiment catalog</button>
      </nav>

      {/* Main Research Layout */}
      <div className="research-layout" hidden={researchView !== 'charts'}>
        <MarketSidebar
          markets={markets}
          items={visibleMarkets}
          selected={active.instrument}
          timeframe={active.timeframe}
          favourites={favourites}
          query={search}
          onSelect={selectMarket}
          onToggleFavourite={(symbol) =>
            setFavourites((values) => toggleFavourite(values, symbol))
          }
        />

        <main className="research-workspace">
          <div className="quant-panel research-toolbar">
            <div className="quant-panel-header">
              <div className="quant-panel-title">Market selection</div>
              <span className="research-toolbar-target">
                Editing {activeWorkspaceId}
              </span>
            </div>
            <div className="quant-panel-body research-inline-controls">
              {comparisonEnabled && (
                <label>
                  Target:{' '}
                  <select
                    aria-label="Active workspace"
                    value={activeWorkspaceId}
                    onChange={(event) =>
                      dispatchLayout({
                        type: 'activate',
                        workspaceId: event.target.value as ResearchWorkspaceId,
                      })
                    }
                  >
                    <option value="primary">Primary</option>
                    <option value="comparison">Comparison</option>
                  </select>
                </label>
              )}
              <label className="research-control research-control-category">
                <span>Market</span>
                <select value={category} onChange={(event) => setCategory(event.target.value)}>
                  <option>All</option>
                  {marketGroups(markets).map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <label className="research-control research-control-search">
                <span>Quick search</span>
                <input
                  ref={searchRef}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search name or symbol"
                />
                <kbd>Ctrl K</kbd>
              </label>
              <label className="research-control research-control-instrument">
                <span>Instrument</span>
                <select
                  value={active.instrument.provider_symbol}
                  onChange={(event) => {
                    const item = markets.catalogue.instruments.find(
                      (value) => value.provider_symbol === event.target.value
                    );
                    if (item) selectMarket(item);
                  }}
                >
                  {selectionOptions.map((item) => (
                    <option
                      key={item.provider_symbol}
                      value={item.provider_symbol}
                      disabled={item.is_trading_suspended}
                    >
                      {item.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="research-control research-control-timeframe">
                <span>Timeframe</span>
                <select
                  value={active.timeframe}
                  onChange={(event) =>
                    dispatchPair({
                      workspaceId: activeWorkspaceId,
                      action: { type: 'select-timeframe', timeframe: event.target.value },
                    })
                  }
                >
                  {active.instrument.timeframes.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </label>
              <span className={`research-source-state ${isCached(markets, active.instrument, active.timeframe) ? 'cached' : ''}`}>
                {markets.catalogue.source_status} · {isCached(markets, active.instrument, active.timeframe) ? 'Cached locally' : 'Not cached'}
              </span>
            </div>
          </div>

          {/* Chart Workspaces Grid (Single or Comparison) */}
          <div className={`research-workspace-grid ${comparisonEnabled ? 'comparison' : 'single'}`}>
            <ResearchChartWorkspace
              state={primary}
              markets={markets}
              active={activeWorkspaceId === 'primary'}
              dispatch={dispatch('primary')}
              onActivate={() => dispatchLayout({ type: 'activate', workspaceId: 'primary' })}
              onMarketsChanged={setMarkets}
            />
            {comparisonEnabled && (
              <ResearchChartWorkspace
                state={comparison}
                markets={markets}
                active={activeWorkspaceId === 'comparison'}
                dispatch={dispatch('comparison')}
                onActivate={() => dispatchLayout({ type: 'activate', workspaceId: 'comparison' })}
                onMarketsChanged={setMarkets}
              />
            )}
          </div>
        </main>
      </div>
      {researchView === 'experiments' && <ExperimentCatalog />}
    </div>
  );
}
