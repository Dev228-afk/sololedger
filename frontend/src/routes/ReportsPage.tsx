import { useState } from 'react';
import { soloApi } from '../api/client.js';
import { useDemoSession, useMonthlyReport } from '../api/hooks.js';
import { formatDisplayUsd, parseDecimalToCents } from '../api/money.js';
import { LedgerShell } from '../components/LedgerShell.js';

export function ReportsPage() {
  const { data: session } = useDemoSession();
  const accountId = session?.account?.id;
  const [fromMonth, setFromMonth] = useState('2026-01');
  const [toMonth, setToMonth] = useState('2026-12');

  const { data: report, isLoading } = useMonthlyReport(accountId, {
    fromMonth,
    toMonth,
    currency: 'USD',
  });

  const categories = report?.categoryTotals ?? [];
  const months = report?.months ?? [];

  let maxAbsCatCents = 100n;
  for (const c of categories) {
    const val = parseDecimalToCents(c.netSpend);
    const abs = val < 0n ? -val : val;
    if (abs > maxAbsCatCents) maxAbsCatCents = abs;
  }

  let maxMonthAbsCents = 100n;
  for (const m of months) {
    const val = parseDecimalToCents(m.netSpend);
    const abs = val < 0n ? -val : val;
    if (abs > maxMonthAbsCents) maxMonthAbsCents = abs;
  }

  const exportUrl = soloApi.buildCsvExportUrl({
    from: fromMonth ? `${fromMonth}-01` : undefined,
  });

  return (
    <LedgerShell
      title="Reports"
      subtitle="Exact SQL category net spend and monthly totals with formula-safe CSV ledger export"
      actions={
        <a
          href={exportUrl}
          download="sololedger-ledger.csv"
          className="sl-btn-link sl-btn-link--primary"
        >
          Export ledger
        </a>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
        <div className="sl-card" style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', alignItems: 'center' }}>
          <label style={{ fontSize: '13px' }}>
            From month
            <input
              type="month"
              value={fromMonth}
              onChange={(e) => setFromMonth(e.target.value)}
              style={{ marginLeft: '8px', padding: '6px 8px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}
            />
          </label>
          <label style={{ fontSize: '13px' }}>
            To month
            <input
              type="month"
              value={toMonth}
              onChange={(e) => setToMonth(e.target.value)}
              style={{ marginLeft: '8px', padding: '6px 8px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}
            />
          </label>
          <span style={{ fontSize: '12px', color: 'var(--muted)' }}>
            Currency: <strong>{report?.currency ?? 'USD'}</strong> · Refunds preserve positive amounts and can yield negative net spend (never clamped to zero).
          </span>
        </div>

        {isLoading ? (
          <div className="sl-card">Loading report totals...</div>
        ) : categories.length === 0 && months.length === 0 ? (
          <div className="sl-card">
            <h2 style={{ margin: '0 0 6px', fontSize: '18px', fontWeight: 600 }}>No report data in selected range</h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: '14px' }}>
              Import a statement or widen your month range to inspect SQL category totals and CSV export.
            </p>
          </div>
        ) : (
          <>
            <section className="sl-card" aria-label="Ranked category net spend">
              <h2 style={{ margin: '0 0 14px', fontSize: '18px', fontWeight: 600 }}>
                Net spend by expense category (USD)
              </h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {categories.map((c) => {
                  const cents = parseDecimalToCents(c.netSpend);
                  const abs = cents < 0n ? -cents : cents;
                  const widthPct = Number((abs * 100n) / maxAbsCatCents);
                  const isNegativeRefund = cents < 0n;
                  return (
                    <div key={c.code} style={{ display: 'grid', gridTemplateColumns: '180px minmax(0, 1fr) 110px', gap: '12px', alignItems: 'center' }}>
                      <span style={{ fontSize: '13px', fontWeight: 600 }}>{c.name}</span>
                      <div
                        style={{
                          height: '12px',
                          borderRadius: '999px',
                          backgroundColor: 'var(--surface-muted)',
                          overflow: 'hidden',
                        }}
                      >
                        <div
                          style={{
                            width: `${Math.max(4, Math.min(100, widthPct))}%`,
                            height: '100%',
                            backgroundColor: isNegativeRefund ? 'var(--success)' : 'var(--accent)',
                          }}
                        />
                      </div>
                      <span className="tabular-nums" style={{ fontSize: '13px', fontWeight: 700, textAlign: 'right' }}>
                        {formatDisplayUsd(c.netSpend)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </section>

            <section className="sl-card" aria-label="Monthly ledger trend and SQL totals">
              <h2 style={{ margin: '0 0 14px', fontSize: '18px', fontWeight: 600 }}>
                Monthly trend & exact SQL totals
              </h2>
              {months.length > 0 ? (
                <svg
                  role="img"
                  aria-label="Monthly net spend bar visualization in USD"
                  viewBox={`0 0 ${Math.max(360, months.length * 80)} 150`}
                  style={{ width: '100%', maxWidth: '720px', height: '150px', display: 'block', marginBottom: '16px' }}
                >
                  <line x1="16" y1="120" x2={Math.max(344, months.length * 80 - 16)} y2="120" stroke="#dce4df" strokeWidth="1" />
                  {months.map((m, idx) => {
                    const cents = parseDecimalToCents(m.netSpend);
                    const abs = cents < 0n ? -cents : cents;
                    const barH = Math.max(8, Number((abs * 88n) / maxMonthAbsCents));
                    const x = 24 + idx * 72;
                    return (
                      <g key={m.month}>
                        <rect
                          x={x}
                          y={120 - barH}
                          width="36"
                          height={barH}
                          rx="4"
                          fill={cents < 0n ? '#147d5c' : '#166b58'}
                        />
                        <text x={x + 18} y="138" textAnchor="middle" fontSize="11" fill="#586762">
                          {m.month}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              ) : null}

              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--line)', textAlign: 'left', color: 'var(--muted)', fontSize: '12px' }}>
                      <th style={{ padding: '10px 8px' }}>Month</th>
                      <th style={{ padding: '10px 8px', textAlign: 'right' }}>Total Debits</th>
                      <th style={{ padding: '10px 8px', textAlign: 'right' }}>Total Credits</th>
                      <th style={{ padding: '10px 8px', textAlign: 'right' }}>Net Expense Spend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {months.map((m) => (
                      <tr key={m.month} style={{ borderBottom: '1px solid var(--line)' }}>
                        <td className="tabular-nums" style={{ padding: '10px 8px', fontWeight: 600 }}>
                          {m.month}
                        </td>
                        <td className="tabular-nums" style={{ padding: '10px 8px', textAlign: 'right' }}>
                          {formatDisplayUsd(m.totalDebits)}
                        </td>
                        <td className="tabular-nums" style={{ padding: '10px 8px', textAlign: 'right', color: 'var(--success)' }}>
                          {formatDisplayUsd(m.totalCredits, true)}
                        </td>
                        <td className="tabular-nums" style={{ padding: '10px 8px', textAlign: 'right', fontWeight: 700 }}>
                          {formatDisplayUsd(m.netSpend)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}
      </div>
    </LedgerShell>
  );
}

