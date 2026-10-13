import React, { Fragment, useState } from 'react';
import { Briefcase, ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { PositionDTO } from '../types/api';
import { formatInstrumentPrice, formatMoney } from '../utils/format';

interface PositionsTableProps {
  positions: PositionDTO[];
  brokerName?: string;
  loading?: boolean;
  currency?: string;
}

export const PositionsTable: React.FC<PositionsTableProps> = ({
  positions,
  loading,
  currency,
}) => {
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <div className="quant-panel positions-panel">
      <div className="quant-panel-header">
        <div className="quant-panel-title">
          <Briefcase size={14} color="var(--quant-cyan)" />
          <span>Open Positions ({positions.length})</span>
        </div>
        <span className="badge badge-neutral">BROKER POSITIONS</span>
      </div>

      <div className="quant-table-wrapper">
        <table className="quant-table">
          <thead>
            <tr>
              <th>Ticket ID</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Volume</th>
              <th>Open Price</th>
              <th>Current Price</th>
              <th title="Stop loss">SL</th>
              <th title="Take profit">TP</th>
              <th style={{ textAlign: 'right' }}>Unrealized P&L</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', padding: '30px', color: 'var(--text-muted)' }}>
                  {loading ? 'Fetching active positions...' : 'NO OPEN POSITIONS ACTIVE ON BROKER'}
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const isBuy = pos.side.toUpperCase() === 'BUY';
                const isProfitable = pos.profit >= 0;
                const open = openId === pos.id;
                const toggle = () => setOpenId(open ? null : pos.id);

                return (
                  <Fragment key={pos.id}>
                  <tr className="position-row" tabIndex={0} aria-expanded={open} onClick={toggle}
                    onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); } }}>
                    <td style={{ color: 'var(--text-dim)' }}>#{pos.id}</td>
                    <td style={{ fontWeight: 700 }}>{pos.symbol}</td>
                    <td>
                      <span className={`badge ${isBuy ? 'badge-green' : 'badge-red'}`} style={{ padding: '1px 5px' }}>
                        {isBuy ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
                        {pos.side}
                      </span>
                    </td>
                    <td>{pos.volume.toFixed(2)}</td>
                    <td>{formatInstrumentPrice(pos.open_price, pos.price_decimals)}</td>
                    <td>
                      {pos.current_price !== null
                        ? formatInstrumentPrice(pos.current_price, pos.price_decimals)
                        : '—'}
                    </td>
                    <td style={{ color: 'var(--quant-red)' }}>
                      {pos.stop_loss !== null ? formatInstrumentPrice(pos.stop_loss, pos.price_decimals) : '—'}
                    </td>
                    <td style={{ color: 'var(--quant-green)' }}>
                      {pos.take_profit !== null ? formatInstrumentPrice(pos.take_profit, pos.price_decimals) : '—'}
                    </td>
                    <td style={{ textAlign: 'right', fontWeight: 700, color: isProfitable ? 'var(--quant-green)' : 'var(--quant-red)' }}>
                      {formatMoney(pos.profit, currency, true)}
                    </td>
                  </tr>
                  {open && <tr className="position-detail-row"><td colSpan={9}>
                    <div className="trade-detail">
                      <span><em>Ticket ID</em>#{pos.id}</span>
                      <span><em>Volume</em>{pos.volume.toFixed(2)}</span>
                      <span><em>Open price</em>{formatInstrumentPrice(pos.open_price, pos.price_decimals)}</span>
                      <span><em>Current price</em>{pos.current_price == null ? '—' : formatInstrumentPrice(pos.current_price, pos.price_decimals)}</span>
                      <span><em>Stop loss</em>{pos.stop_loss == null ? '—' : formatInstrumentPrice(pos.stop_loss, pos.price_decimals)}</span>
                      <span><em>Take profit</em>{pos.take_profit == null ? '—' : formatInstrumentPrice(pos.take_profit, pos.price_decimals)}</span>
                    </div>
                  </td></tr>}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
