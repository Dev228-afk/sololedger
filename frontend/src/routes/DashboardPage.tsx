import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  useDemoSession,
  useImports,
  useMonthlyReport,
  useReviewQueue,
} from '../api/hooks.js';
import { formatDisplayUsd, sumDecimalStrings } from '../api/money.js';
import { LedgerShell } from '../components/LedgerShell.js';
import { AlertBanner, StatusBadge } from '../components/UiPrimitives.js';

export function DashboardPage() {
  const { data: session } = useDemoSession();
  const accountId = session?.account?.id;
  const [fromMonth, setFromMonth] = useState('2026-01');
  const [toMonth, setToMonth] = useState('2026-12');

  const { data: report, isLoading: reportLoading } = useMonthlyReport(accountId, {
    fromMonth,
    toMonth,
    currency: 'USD',
  });
  const { data: imports } = useImports(accountId);
  const { data: reviewQueue } = useReviewQueue(accountId);

  const months = report?.months ?? [];
  const totalNetDecimal = sumDecimalStrings(months.map((m) => m.netSpend));
  const totalNetStr = formatDisplayUsd(totalNetDecimal);
  const reviewCount = reviewQueue?.totalCount ?? 0;

  return (
    <LedgerShell
      title="Overview"
      subtitle="Server-derived monthly expense totals, recent statement imports, and review queue"
      actions={
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {reviewCount > 0 ? (
            <Link to="/review" className="sl-btn-link sl-btn-link--secondary">
              Review {reviewCount} items
            </Link>
          ) : null}
          <Link to="/imports/new" className="sl-btn-link sl-btn-link--primary">
            Import statement
          </Link>
        </div>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
        <div
          className="sl-card"
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 'var(--space-4)',
          }}
        >
          <div>
            <div style={{ fontSize: '13px', color: 'var(--muted)' }}>
              Net Expense Spend ({fromMonth} to {toMonth})
            </div>
            <div
              className="tabular-nums"
              data-testid="dashboard-net-spend"
              style={{ fontSize: '36px', fontWeight: 700, lineHeight: 1.15 }}
            >
              {reportLoading ? 'Loading...' : totalNetStr}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--muted)', marginTop: '4px' }}>
              Derived directly from ledger SQL (-SUM of expense minor units; refunds may lower or negate spend).
            </div>
          </div>

          <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: '13px', color: 'var(--muted)' }}>
              From month{' '}
              <input
                type="month"
                value={fromMonth}
                onChange={(e) => setFromMonth(e.target.value)}
                aria-label="From month"
                style={{
                  marginLeft: '6px',
                  padding: '6px 8px',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--r-sm)',
                }}
              />
            </label>
            <label style={{ fontSize: '13px', color: 'var(--muted)' }}>
              To month{' '}
              <input
                type="month"
                value={toMonth}
                onChange={(e) => setToMonth(e.target.value)}
                aria-label="To month"
                style={{
                  marginLeft: '6px',
                  padding: '6px 8px',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--r-sm)',
                }}
              />
            </label>
          </div>
        </div>

        {(imports?.items.length ?? 0) === 0 ? (
          <AlertBanner
            kind="info"
            title="No imported statements in this demo workspace yet"
            message="Upload a synthetic CSV statement (or download our sample CSV inside the wizard) to run asynchronous Celery categorization."
            action={
              <Link to="/imports/new" className="sl-btn-link sl-btn-link--primary">
                Import statement
              </Link>
            }
          />
        ) : null}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 'var(--space-6)',
          }}
        >
          <section className="sl-card" aria-label="Category spending summary">
            <h2 style={{ margin: '0 0 14px', fontSize: '18px', fontWeight: 600 }}>
              Category spending
            </h2>
            {(report?.categoryTotals.length ?? 0) === 0 ? (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '14px' }}>
                No expense transactions in selected months.
              </p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {report?.categoryTotals.map((cat) => (
                  <li
                    key={cat.code}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      borderBottom: '1px solid var(--line)',
                      paddingBottom: '8px',
                      fontSize: '14px',
                    }}
                  >
                    <span>{cat.name}</span>
                    <span className="tabular-nums" style={{ fontWeight: 600 }}>
                      {cat.netSpend.startsWith('-')
                        ? `-$${cat.netSpend.slice(1)}`
                        : `$${cat.netSpend}`}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="sl-card" aria-label="Recent imports">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Recent imports</h2>
              <Link to="/imports/new" style={{ color: 'var(--accent)', fontSize: '13px', fontWeight: 600 }}>
                New import
              </Link>
            </div>
            {(imports?.items.length ?? 0) === 0 ? (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '14px' }}>
                Statements you import will appear here with live worker progress and row counts.
              </p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {imports?.items.slice(0, 6).map((job) => (
                  <li
                    key={job.jobId}
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '10px',
                      borderBottom: '1px solid var(--line)',
                      paddingBottom: '8px',
                      fontSize: '14px',
                    }}
                  >
                    <div>
                      <Link
                        to={`/imports/${job.jobId}`}
                        style={{ color: 'var(--ink)', fontWeight: 600, textDecoration: 'none' }}
                      >
                        {job.fileName}
                      </Link>
                      <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                        {job.validRows} valid · {job.invalidRows} invalid · {job.needsReviewCount} to review
                      </div>
                    </div>
                    <StatusBadge
                      label={job.status}
                      tone={
                        job.status === 'COMPLETED'
                          ? 'success'
                          : job.status === 'FAILED'
                            ? 'danger'
                            : job.status === 'AWAITING_REVIEW'
                              ? 'warning'
                              : 'accent'
                      }
                    />
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </LedgerShell>
  );
}
