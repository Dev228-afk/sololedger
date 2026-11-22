import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import {
  useDemoSession,
  useImports,
  useMonthlyReport,
  useReviewQueue,
} from '../api/hooks.js';
import { formatDisplayUsd, parseDecimalToCents, sumDecimalStrings } from '../api/money.js';
import { LedgerShell } from '../components/LedgerShell.js';
import { AlertBanner, Button, StatusBadge } from '../components/UiPrimitives.js';

const PERIOD_PRESETS = [
  { label: 'Full 2026', from: '2026-01', to: '2026-12' },
  { label: 'Q1 2026', from: '2026-01', to: '2026-03' },
  { label: 'H1 2026', from: '2026-01', to: '2026-06' },
];

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
  const categories = report?.categoryTotals ?? [];
  const totalNetDecimal = sumDecimalStrings(months.map((m) => m.netSpend));
  const totalNetStr = formatDisplayUsd(totalNetDecimal);
  const reviewCount = reviewQueue?.totalCount ?? 0;

  let maxCatCents = 100n;
  let totalCatAbsCents = 0n;
  const parsedCategories = categories.map((cat) => {
    const cents = parseDecimalToCents(cat.netSpend);
    const abs = cents < 0n ? -cents : cents;
    totalCatAbsCents += abs;
    if (abs > maxCatCents) maxCatCents = abs;
    return { ...cat, cents, abs };
  });

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
            background: 'linear-gradient(135deg, #ffffff 0%, #f5f7f3 100%)',
          }}
        >
          <div>
            <div style={{ fontSize: '12px', fontWeight: 600, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--muted)' }}>
              Net Expense Spend ({fromMonth} to {toMonth})
            </div>
            <div
              className="tabular-nums"
              data-testid="dashboard-net-spend"
              style={{ fontSize: '40px', fontWeight: 700, letterSpacing: '-0.03em', lineHeight: 1.12, marginTop: '4px' }}
            >
              {reportLoading ? 'Loading...' : totalNetStr}
            </div>
            <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '6px' }}>
              Signed ledger total across approved &amp; imported entries (refunds net against expenses).
            </div>
            <details style={{ marginTop: '6px', fontSize: '12px', color: 'var(--muted)' }}>
              <summary style={{ cursor: 'pointer', fontWeight: 600 }}>Accounting basis note</summary>
              <div style={{ marginTop: '4px' }}>
                Computed server-side directly in integer USD cents (`-SUM(amount_minor)` for expenses) so floating-point rounding drift never accumulates.
              </div>
            </details>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '10px' }}>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }} role="group" aria-label="Quick period presets">
              {PERIOD_PRESETS.map((preset) => {
                const active = fromMonth === preset.from && toMonth === preset.to;
                return (
                  <Button
                    key={preset.label}
                    size="sm"
                    variant={active ? 'primary' : 'secondary'}
                    onClick={() => {
                      setFromMonth(preset.from);
                      setToMonth(preset.to);
                    }}
                  >
                    {preset.label}
                  </Button>
                );
              })}
            </div>

            <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
              <label style={{ fontSize: '13px', color: 'var(--muted)' }}>
                From month{' '}
                <input
                  type="month"
                  className="sl-input"
                  value={fromMonth}
                  onChange={(e) => setFromMonth(e.target.value)}
                  aria-label="From month"
                  style={{
                    marginLeft: '6px',
                    padding: '6px 8px',
                  }}
                />
              </label>
              <label style={{ fontSize: '13px', color: 'var(--muted)' }}>
                To month{' '}
                <input
                  type="month"
                  className="sl-input"
                  value={toMonth}
                  onChange={(e) => setToMonth(e.target.value)}
                  aria-label="To month"
                  style={{
                    marginLeft: '6px',
                    padding: '6px 8px',
                  }}
                />
              </label>
            </div>
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
            gridTemplateColumns: 'repeat(auto-fit, minmax(310px, 1fr))',
            gap: 'var(--space-6)',
          }}
        >
          <section className="sl-card" aria-label="Category spending summary">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>
                Category spending
              </h2>
              <Link to="/reports" style={{ color: 'var(--accent)', fontSize: '13px', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '4px', textDecoration: 'none' }}>
                Full breakdown <ArrowRight size={13} aria-hidden="true" />
              </Link>
            </div>
            {parsedCategories.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '14px' }}>
                No expense transactions in selected months.
              </p>
            ) : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {parsedCategories.map((cat) => {
                  const barPct = Number((cat.abs * 100n) / maxCatCents);
                  const sharePct = totalCatAbsCents > 0n ? Number((cat.abs * 100n) / totalCatAbsCents) : 0;
                  return (
                    <li
                      key={cat.code}
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '6px',
                        borderBottom: '1px solid var(--line)',
                        paddingBottom: '10px',
                        fontSize: '14px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontWeight: 500 }}>{cat.name}</span>
                        <span className="tabular-nums" style={{ fontWeight: 700 }}>
                          {formatDisplayUsd(cat.netSpend)}{' '}
                          <span style={{ fontSize: '11px', fontWeight: 500, color: 'var(--muted)' }}>
                            ({sharePct}%)
                          </span>
                        </span>
                      </div>
                      <div style={{ height: '7px', borderRadius: '999px', backgroundColor: 'var(--surface-muted)', overflow: 'hidden' }}>
                        <div
                          className="sl-bar-fill"
                          style={{
                            width: `${Math.max(5, Math.min(100, barPct))}%`,
                            height: '100%',
                            backgroundColor: cat.cents < 0n ? 'var(--success)' : 'var(--accent)',
                            borderRadius: '999px',
                          }}
                        />
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="sl-card" aria-label="Recent imports">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Recent imports</h2>
              <Link to="/imports/new" style={{ color: 'var(--accent)', fontSize: '13px', fontWeight: 600, textDecoration: 'none' }}>
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
                    className="sl-row-hover"
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '10px',
                      borderBottom: '1px solid var(--line)',
                      padding: '6px 4px 10px',
                      borderRadius: '6px',
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
