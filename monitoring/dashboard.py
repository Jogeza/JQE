"""Local read-only live-paper dashboard served by FastAPI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from monitoring.live_paper_reader import dashboard_snapshot


def create_dashboard(evidence_path: Path, ledger_path: Path) -> FastAPI:
    """Create a monitoring-only app bound to two existing SQLite files."""
    evidence = evidence_path.expanduser().resolve()
    ledger = ledger_path.expanduser().resolve()
    app = FastAPI(title="JQE Live-Paper Monitor", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return _PAGE

    @app.get("/api/snapshot")
    async def snapshot(
        session_id: str | None = Query(default=None),
        feed_limit: int = Query(default=100, ge=10, le=500),
    ) -> dict:
        try:
            return dashboard_snapshot(evidence, ledger, session_id, feed_limit=feed_limit)
        except (FileNotFoundError, sqlite3.Error, ValueError) as exc:
            raise HTTPException(status_code=503, detail=f"Monitoring data unavailable: {exc}") from exc

    return app


def main() -> None:
    global _PAGE
    parser = argparse.ArgumentParser(description="Run the read-only JQE live-paper monitor")
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--refresh-seconds", default=3, type=int)
    args = parser.parse_args()
    import uvicorn

    page = _PAGE.replace("const REFRESH_MS = 3000", f"const REFRESH_MS = {max(1, args.refresh_seconds) * 1000}")
    _PAGE = page
    uvicorn.run(create_dashboard(args.evidence, args.ledger), host=args.host, port=args.port)


_PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JQE Live-Paper Monitor</title><style>
:root{color-scheme:dark;--bg:#08111f;--panel:#101d30;--muted:#91a4bd;--line:#203653;--accent:#37d6ae;--danger:#ff5f6d;--warn:#ffbd59}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#edf5ff;font:14px system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:24px}.top{display:flex;justify-content:space-between;align-items:center}h1{margin:0 0 4px}.muted{color:var(--muted)}.alerts{margin:20px 0}.alert{border:2px solid var(--danger);background:#35151e;padding:14px;margin:8px 0;border-radius:8px;font-weight:700}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}.metric{font-size:22px;font-weight:750;color:var(--accent)}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted)}select{background:var(--panel);color:#fff;border:1px solid var(--line);padding:8px;border-radius:6px}.pill{display:inline-block;padding:3px 8px;border-radius:99px;background:#173b38;color:var(--accent)}pre{white-space:pre-wrap;margin:3px 0;color:#bfd0e5}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}.scroll{overflow:auto}}
</style></head><body><main><div class="top"><div><h1>JQE Live-Paper Monitor</h1><div class="muted">Read-only evidence and position ledger view</div></div><select id="sessions"></select></div>
<section id="alerts" class="alerts"></section><section id="status" class="grid"></section>
<section class="card"><h2>Open positions</h2><div id="open" class="scroll"></div></section>
<section class="card"><h2>Recent evidence</h2><div id="feed" class="scroll"></div></section>
<section class="card"><h2>Closed positions</h2><div id="closed" class="scroll"></div></section>
<div id="stamp" class="muted"></div></main><script>
const REFRESH_MS = 3000; const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(cols,rows)=>`<table><thead><tr>${cols.map(c=>`<th>${esc(c[0])}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${esc(c[1](r))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
const sel=document.querySelector('#sessions');async function refresh(){const q=sel.value?`?session_id=${encodeURIComponent(sel.value)}`:'';try{const d=await fetch('/api/snapshot'+q,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error(r.status);return r.json()});const prior=sel.value;sel.innerHTML=d.sessions.map(s=>`<option value="${esc(s.session_id)}">${esc(s.session_id)} · ${esc(s.state)}</option>`).join('');if(prior)sel.value=prior;if(!d.selected_session)return;const s=d.selected_session,p=s.progress;document.querySelector('#alerts').innerHTML=d.alerts.length?`<h2>Critical alerts (${d.alerts.length})</h2>`+d.alerts.map(a=>`<div class="alert">${esc(a.facts.reason_code||'REJECTED ENTRY')} · ${esc(a.occurred_at)}<pre>${esc(JSON.stringify(a.facts,null,2))}</pre></div>`).join(''):'<div class="card"><span class="pill">No critical alerts</span></div>';document.querySelector('#status').innerHTML=[['State',s.state],['Market',`${s.broker} · ${s.symbol} ${s.timeframe}`],['Candles',`${p.candles_observed} / ${p.max_candles??'—'}`],['Elapsed',`${p.elapsed_seconds==null?'—':Math.round(p.elapsed_seconds)+'s'} / ${p.max_duration_seconds??'—'}`]].map(x=>`<div class="card"><div class="muted">${esc(x[0])}</div><div class="metric">${esc(x[1])}</div></div>`).join('');document.querySelector('#open').innerHTML=table([['Position',r=>r.position_id],['Side',r=>r.side],['Size',r=>r.size],['Entry',r=>r.entry_price],['Current',r=>r.current_price],['SL',r=>r.stop_loss],['TP',r=>r.take_profit],['Opened',r=>r.opened_at],['Recovery',r=>r.recovered?r.recovery_path:'No']],d.open_positions);document.querySelector('#feed').innerHTML=table([['Time',r=>r.occurred_at],['Type',r=>r.event_type],['Reason',r=>r.facts.reason_code],['Details',r=>JSON.stringify(r.facts)]],d.recent_evidence);document.querySelector('#closed').innerHTML=table([['Position',r=>r.position_id],['Symbol',r=>r.symbol],['Side',r=>r.side],['Closed',r=>r.closed_at],['Reason',r=>r.exit_reason],['Requested',r=>r.requested_price],['Filled',r=>r.filled_price],['Slippage',r=>r.slippage],['Exit',r=>r.exit_price],['PnL',r=>r.pnl]],d.closed_positions);document.querySelector('#stamp').textContent='Last refreshed '+d.refreshed_at}catch(e){document.querySelector('#alerts').innerHTML=`<div class="alert">Dashboard data unavailable: ${esc(e.message)}</div>`}}sel.addEventListener('change',refresh);refresh();setInterval(refresh,REFRESH_MS);
</script></body></html>'''


if __name__ == "__main__":
    main()
