import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart2,
  BookOpen,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Filter,
  Layers,
  RefreshCw,
  Search,
  Star,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import { jqeApi } from "../services/api";
import { weltradeReferralUrl } from "../auth/supabase";
import type { SyntXFamilyDTO, SyntXMarketCardDTO, SyntXOverviewResponse } from "../types/api";
import "./SyntXMarketsPage.css";

// ── Freshness helper ──────────────────────────────────────────────────────
function formatCandleAge(isoTime: string | null | undefined): string {
  if (!isoTime) return "";
  try {
    const ms = Date.now() - new Date(isoTime).getTime();
    const h = ms / 3600_000;
    if (h < 1) return `${Math.max(1, Math.round(h * 60))}m ago`;
    if (h < 48) return `${Math.round(h)}h ago`;
    return `${Math.round(h / 24)}d ago`;
  } catch {
    return "";
  }
}

function formatFreshness(ageSeconds: number | null): string {
  if (ageSeconds == null) return "Freshness unknown";
  if (ageSeconds < 60) return `${Math.round(ageSeconds)}s after close`;
  if (ageSeconds < 3600) return `${Math.round(ageSeconds / 60)}m after close`;
  return `${Math.round(ageSeconds / 3600)}h after close`;
}

function formatCandleTime(isoTime: string | null | undefined): string {
  if (!isoTime) return "";
  try {
    return new Date(isoTime).toLocaleString("en-GB", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      hour12: false, timeZone: "UTC",
    }) + " UTC";
  } catch {
    return "";
  }
}

// ── Tiny inline sparkline SVG ───────────────────────────────────────────────
const Sparkline: React.FC<{ data: number[]; positive: boolean }> = ({ data, positive }) => {
  if (!data || data.length < 2) {
    return (
      <svg className="syntx-sparkline" viewBox="0 0 80 30" aria-hidden="true">
        <line x1="0" y1="15" x2="80" y2="15" stroke="currentColor" strokeWidth="1.5" strokeOpacity="0.2" />
      </svg>
    );
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 80, h = 30, pad = 2;
  const pts = data.map((v, i) => {
    const x = pad + (i / (data.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return x.toFixed(1) + "," + y.toFixed(1);
  });
  const strokeColor = positive ? "var(--quant-green)" : "var(--quant-red)";
  const d = "M" + pts.join("L");
  const closeX = (w - pad).toFixed(1);
  const baseY = (h - pad).toFixed(1);
  const area = d + "L" + closeX + "," + baseY + "L" + pad + "," + baseY + "Z";
  const gradId = positive ? "sg-up" : "sg-dn";
  return (
    <svg className="syntx-sparkline" viewBox={"0 0 " + w + " " + h} aria-hidden="true" preserveAspectRatio="none">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={strokeColor} stopOpacity="0.22" />
          <stop offset="100%" stopColor={strokeColor} stopOpacity="0.01" />
        </linearGradient>
      </defs>
      <path d={area} fill={"url(#" + gradId + ")"} />
      <path d={d} fill="none" stroke={strokeColor} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
};

// ── RSI zone badge ─────────────────────────────────────────────────────────
const RsiGauge: React.FC<{ value: number | null }> = ({ value }) => {
  if (value == null) return <span className="syntx-stat-val dim">—</span>;
  const zone = value >= 70
    ? { label: "OB", cls: "rsi-ob" }
    : value <= 30
    ? { label: "OS", cls: "rsi-os" }
    : { label: "N", cls: "rsi-neutral" };
  return (
    <span className={"syntx-rsi-pill " + zone.cls} title={"RSI " + value.toFixed(1)}>
      {value.toFixed(0)}<small>{zone.label}</small>
    </span>
  );
};

// ── Individual market card ─────────────────────────────────────────────────
interface CardProps {
  card: SyntXMarketCardDTO;
  onSelect: (sym: string) => void;
  referralUrl: string;
}

const SyntXCard: React.FC<CardProps> = ({ card, onSelect, referralUrl }) => {
  const positive = (card.change_pct ?? 0) >= 0;
  const hasPrice = card.latest_close != null;
  const fmt = (v: number | null, decimals = card.specs.digits) =>
    v == null
      ? "—"
      : v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  const cacheColor =
    card.cache_status === "CACHED"
      ? "var(--quant-green)"
      : card.cache_status === "PARTIAL"
      ? "var(--quant-amber)"
      : "var(--quant-red)";
  const cardClass = "syntx-card" + (card.is_watched ? " syntx-card--watched" : "");
  const changeClass = "syntx-price-change " + (positive ? "pos" : "neg");
  const deltaClass = "syntx-price-delta " + (positive ? "pos" : "neg");

  return (
    <article
      className={cardClass}
      aria-label={card.symbol + " market card"}
      onClick={() => onSelect(card.symbol)}
      role="button"
      tabIndex={0}
      onKeyDown={e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(card.symbol); }
      }}
    >
      <div className="syntx-card-header">
        <div className="syntx-card-identity">
          <span className="syntx-card-symbol">{card.symbol}</span>
          <span className="syntx-card-family">{card.family_name}</span>
        </div>
        <div className="syntx-card-badges">
          <span
            className="syntx-cache-dot"
            style={{ background: cacheColor }}
            title={"Cache: " + card.cache_status + " · " + card.candle_count + " candles"}
          />
          {card.is_watched && <Star size={10} className="syntx-watched-star" aria-label="Watched" />}
        </div>
      </div>

      <div className="syntx-card-sparkline">
        <Sparkline data={card.sparkline} positive={positive} />
        {hasPrice && (
          <div className={changeClass}>
            {positive ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
            <span>{positive ? "+" : ""}{(card.change_pct ?? 0).toFixed(2)}%</span>
          </div>
        )}
      </div>

      {card.cache_status === "MISSING" || card.cache_status === "UNAVAILABLE" ? (
        <div className="syntx-card-no-data">
          <span className="syntx-no-data-label">No cached data</span>
          <span className="syntx-no-data-sub">MT5 connection required to populate</span>
        </div>
      ) : (
        <>
          <div className="syntx-card-price">
            <div className="syntx-price-label-row">
              <span className="syntx-price-cache-label">Latest cached close</span>
              <span
                className={"syntx-price-freshness" + (card.cache_status === "STALE" ? " stale" : "")}
                title={formatCandleTime(card.last_candle_time)}
              >
                {formatFreshness(card.freshness_age_seconds)}
              </span>
            </div>
            <div className="syntx-price-row">
              <span className="syntx-price-main">{fmt(card.latest_close)}</span>
              <span className={deltaClass}>
                {card.change_value != null ? (positive ? "+" : "") + fmt(card.change_value) : "—"}
              </span>
            </div>
          </div>

          <div className="syntx-card-stats">
            <div className="syntx-stat">
              <span className="syntx-stat-lbl">ATR</span>
              <span className="syntx-stat-val">{card.atr != null ? card.atr.toFixed(2) : "—"}</span>
            </div>
            <div className="syntx-stat">
              <span className="syntx-stat-lbl">RSI</span>
              <RsiGauge value={card.rsi} />
            </div>
            <div className="syntx-stat">
              <span className="syntx-stat-lbl">H / L</span>
              <span className="syntx-stat-val" style={{ fontSize: "9px" }}>
                {card.high_price != null && card.low_price != null
                  ? fmt(card.high_price) + " / " + fmt(card.low_price)
                  : "—"}
              </span>
            </div>
          </div>
          <div className="syntx-card-data-meta">
            <span title={card.provenance}>{card.provenance}</span>
            <span title={formatCandleTime(card.last_tick_time)}>
              {card.last_tick_time
                ? "Tick " + formatCandleAge(card.last_tick_time)
                : "Tick unavailable"}
            </span>
          </div>
        </>
      )}

      <div className="syntx-card-footer">
        <span className="syntx-card-tf">{card.timeframe}</span>
        <span className="syntx-card-vol-spec">
          <Layers size={9} /> {card.specs.volume_min}–{card.specs.volume_max}
        </span>
        <a
          href={referralUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="syntx-trade-btn"
          aria-label={"Trade " + card.symbol + " on Weltrade"}
          onClick={e => e.stopPropagation()}
        >
          Trade <ExternalLink size={9} />
        </a>
      </div>
    </article>
  );
};

// ── Skeleton loading card ──────────────────────────────────────────────────
const CardSkeleton: React.FC = () => (
  <div className="syntx-card syntx-card--skeleton" aria-hidden="true">
    <div className="skeleton-line" style={{ width: "60%", height: 14 }} />
    <div className="skeleton-line" style={{ width: "40%", height: 10, marginTop: 4 }} />
    <div className="skeleton-sparkline" />
    <div className="skeleton-line" style={{ width: "50%", height: 18, marginTop: 8 }} />
    <div className="skeleton-line" style={{ width: "100%", height: 10, marginTop: 6 }} />
  </div>
);

// ── Sort / filter constants ────────────────────────────────────────────────
const TIMEFRAMES = ["M1", "M5", "H1"] as const;
type TF = (typeof TIMEFRAMES)[number];
const SORT_OPTIONS = [
  { id: "family" as const, label: "Family" },
  { id: "symbol" as const, label: "Symbol" },
  { id: "change" as const, label: "Change%" },
  { id: "rsi" as const, label: "RSI" },
  { id: "atr" as const, label: "ATR" },
];
type SortId = (typeof SORT_OPTIONS)[number]["id"];

interface Props {
  onSelectSymbol?: (symbol: string, timeframe?: string) => void;
}

// ── Main page component ────────────────────────────────────────────────────
export const SyntXMarketsPage: React.FC<Props> = ({ onSelectSymbol }) => {
  const [timeframe, setTimeframe] = useState<TF>("M5");
  const [family, setFamily] = useState("all");
  const [search, setSearch] = useState("");
  const [sortId, setSortId] = useState<SortId>("family");
  const [sortAsc, setSortAsc] = useState(true);
  const [overview, setOverview] = useState<SyntXOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshed, setLastRefreshed] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setLoading(true);
    setError(null);
    try {
      const data = await jqeApi.getSyntXOverview(timeframe, family, search, ac.signal);
      setOverview(data);
      setLastRefreshed(new Date().toLocaleTimeString("en-GB", { hour12: false }));
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError(err instanceof Error ? err.message : "Failed to load market data");
      }
    } finally {
      if (!ac.signal.aborted) setLoading(false);
    }
  }, [timeframe, family, search]);

  useEffect(() => { load(); }, [load]);

  const families: SyntXFamilyDTO[] = overview?.families ?? [];
  const referralUrl = weltradeReferralUrl;

  const sorted = useMemo(() => {
    const items = [...(overview?.instruments ?? [])];
    const dir = sortAsc ? 1 : -1;
    items.sort((a, b) => {
      switch (sortId) {
        case "symbol": return dir * a.symbol.localeCompare(b.symbol);
        case "change": return dir * ((a.change_pct ?? -999) - (b.change_pct ?? -999));
        case "rsi":    return dir * ((a.rsi ?? -1) - (b.rsi ?? -1));
        case "atr":    return dir * ((a.atr ?? -1) - (b.atr ?? -1));
        case "family":
          return dir * a.family_id.localeCompare(b.family_id) || a.symbol.localeCompare(b.symbol);
        default: return 0;
      }
    });
    return items;
  }, [overview?.instruments, sortId, sortAsc]);

  const toggleSort = (id: SortId) => {
    if (sortId === id) setSortAsc(a => !a);
    else { setSortId(id); setSortAsc(true); }
  };

  const cachedCount = overview?.cached_instruments ?? 0;
  const totalCount = overview?.total_instruments ?? 0;
  const coveragePct = totalCount > 0 ? Math.round((cachedCount / totalCount) * 100) : 0;

  return (
    <div className="syntx-page dashboard-page-container">

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <header className="syntx-hero">
        <div className="syntx-hero-left">
          <span className="syntx-hero-kicker">
            <Zap size={12} /> Weltrade SyntX Universe
          </span>
          <h1 className="syntx-hero-title">
            SyntX Markets
            <span className="syntx-hero-badge">{totalCount} instruments</span>
          </h1>
          <p className="syntx-hero-sub">
            Native Weltrade synthetic indices · Cached closes from MT5 terminal · Not live quotes
          </p>
        </div>
        <div className="syntx-hero-right">
          <div
            className="syntx-coverage-pill"
            aria-label={cachedCount + " of " + totalCount + " instruments have cached data"}
          >
            <div className="syntx-coverage-bar">
              <div className="syntx-coverage-fill" style={{ width: coveragePct + "%" }} />
            </div>
            <span>{cachedCount}/{totalCount} cached</span>
          </div>
          <a
            id="open-account-btn"
            href={referralUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="syntx-open-account-btn"
            aria-label="Open a Weltrade account"
          >
            <Activity size={14} /> Open Account <ExternalLink size={12} />
          </a>
        </div>
      </header>

      {/* ── Controls ─────────────────────────────────────────────── */}
      <div className="syntx-controls">
        <div className="syntx-search-wrap">
          <Search size={13} className="syntx-search-icon" />
          <input
            id="syntx-search"
            type="search"
            className="syntx-search-input"
            placeholder="Search symbols…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            aria-label="Search SyntX instruments"
          />
        </div>

        <div className="syntx-filter-group" role="group" aria-label="Family filter">
          <Filter size={12} className="syntx-filter-icon" />
          {[{ id: "all", name: "All" }, ...families].map(f => (
            <button
              key={f.id}
              className={"syntx-filter-btn" + (family === f.id ? " active" : "")}
              onClick={() => setFamily(f.id)}
              aria-pressed={family === f.id}
            >
              {f.name}
            </button>
          ))}
        </div>

        <div className="syntx-tf-group" role="group" aria-label="Timeframe">
          {TIMEFRAMES.map(tf => (
            <button
              key={tf}
              className={"syntx-tf-btn" + (timeframe === tf ? " active" : "")}
              onClick={() => setTimeframe(tf)}
              aria-pressed={timeframe === tf}
            >
              {tf}
            </button>
          ))}
        </div>

        <div className="syntx-sort-wrap">
          <BarChart2 size={12} className="syntx-filter-icon" />
          {SORT_OPTIONS.map(opt => (
            <button
              key={opt.id}
              className={"syntx-sort-btn" + (sortId === opt.id ? " active" : "")}
              onClick={() => toggleSort(opt.id)}
              aria-label={"Sort by " + opt.label}
            >
              {opt.label}
              {sortId === opt.id && (sortAsc ? <ChevronUp size={10} /> : <ChevronDown size={10} />)}
            </button>
          ))}
        </div>

        <div className="syntx-refresh-group">
          {lastRefreshed && <span className="syntx-refresh-time">Updated {lastRefreshed}</span>}
          <button
            className="syntx-refresh-btn"
            onClick={load}
            disabled={loading}
            aria-label="Refresh market data"
          >
            <RefreshCw size={13} className={loading ? "spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── Error banner ─────────────────────────────────────────── */}
      {error && (
        <div className="syntx-error-banner" role="alert">
          <Zap size={14} />
          <span>{error}</span>
          <button onClick={load}>Retry</button>
        </div>
      )}

      {/* ── Cards grid ───────────────────────────────────────────── */}
      <div className="syntx-grid" role="list" aria-label="SyntX market cards" aria-busy={loading}>
        {loading && !overview ? (
          Array.from({ length: 12 }).map((_, i) => <CardSkeleton key={i} />)
        ) : sorted.length === 0 ? (
          <div className="syntx-empty">
            <BookOpen size={32} />
            <p>No instruments match your filters</p>
            <button onClick={() => { setSearch(""); setFamily("all"); }}>Clear filters</button>
          </div>
        ) : (
          sorted.map(card => (
            <SyntXCard
              key={card.symbol + "-" + card.timeframe}
              card={card}
              referralUrl={referralUrl}
              onSelect={sym => onSelectSymbol?.(sym, timeframe)}
            />
          ))
        )}
      </div>

      {/* ── Footer ───────────────────────────────────────────────── */}
      <footer className="syntx-footer">
        <span>
          Cached closes from Weltrade MT5 terminal · Prices are NOT live quotes ·
          Observation only · Not investment advice
        </span>
        <a href={referralUrl} target="_blank" rel="noopener noreferrer" className="syntx-footer-link">
          Open a Weltrade account <ExternalLink size={10} />
        </a>
      </footer>
    </div>
  );
};
