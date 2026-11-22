import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { soloApi, SoloLedgerApiError } from '../api/client.js';
import { useDemoSession, useImportDetail } from '../api/hooks.js';
import { LedgerShell } from '../components/LedgerShell.js';
import { AlertBanner, Button, StatusBadge } from '../components/UiPrimitives.js';

export function ImportDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: session } = useDemoSession();
  const accountId = session?.account?.id;
  const { data: job, isLoading, error, refetch } = useImportDetail(accountId, id);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  async function handleRetry() {
    if (!id) return;
    setActionMsg(null);
    try {
      await soloApi.retryImport(id, `retry_${id}_${Date.now()}`);
      await refetch();
    } catch (err) {
      setActionMsg(err instanceof SoloLedgerApiError ? err.message : 'Retry failed.');
    }
  }

  async function handleCancel() {
    if (!id) return;
    setActionMsg(null);
    try {
      await soloApi.cancelImport(id, 'Canceled by user in browser');
      await refetch();
    } catch (err) {
      setActionMsg(err instanceof SoloLedgerApiError ? err.message : 'Cancel failed.');
    }
  }

  const pct =
    job && job.totalRows > 0
      ? Math.min(100, Math.round((job.processedRows / job.totalRows) * 100))
      : 0;

  return (
    <LedgerShell
      title={job ? `Import: ${job.fileName}` : 'Import job status'}
      subtitle="Asynchronous Celery progress tracking with cooperative cancel and idempotent retry"
      actions={
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {job && job.needsReviewCount > 0 ? (
            <Link to="/review" className="sl-btn-link sl-btn-link--primary">
              Review {job.needsReviewCount} items
            </Link>
          ) : null}
          <Link to="/transactions" className="sl-btn-link sl-btn-link--secondary">
            View ledger
          </Link>
        </div>
      }
    >
      {error ? (
        <AlertBanner
          kind="danger"
          message={error instanceof SoloLedgerApiError ? error.message : 'Failed to load import job.'}
        />
      ) : null}

      {actionMsg ? <AlertBanner kind="warning" message={actionMsg} /> : null}

      {isLoading || !job ? (
        <div className="sl-card">Loading import job details...</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
          <section className="sl-card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '13px', color: 'var(--muted)' }}>
                  Phase: <strong>{job.phaseLabel}</strong> · Attempts: {job.attempts}
                </div>
                <div
                  className="tabular-nums"
                  data-testid="import-progress-counts"
                  style={{ fontSize: '24px', fontWeight: 700, marginTop: '4px' }}
                >
                  {job.processedRows} / {job.totalRows} rows processed
                </div>
              </div>
              <StatusBadge
                label={job.status}
                tone={
                  job.status === 'COMPLETED'
                    ? 'success'
                    : job.status === 'FAILED' || job.status === 'CANCELED'
                      ? 'danger'
                      : job.status === 'AWAITING_REVIEW'
                        ? 'warning'
                        : 'accent'
                }
              />
            </div>

            <div
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Import completion percentage"
              style={{
                marginTop: '14px',
                height: '10px',
                borderRadius: '999px',
                backgroundColor: 'var(--surface-muted)',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: '100%',
                  backgroundColor: 'var(--accent)',
                  transition: 'width 160ms ease',
                }}
              />
            </div>

            <div
              className="tabular-nums"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                gap: '12px',
                marginTop: '18px',
                fontSize: '14px',
              }}
            >
              <div>
                <div style={{ color: 'var(--muted)', fontSize: '12px' }}>Valid rows</div>
                <strong>{job.validRows}</strong>
              </div>
              <div>
                <div style={{ color: 'var(--muted)', fontSize: '12px' }}>Invalid rows quarantined</div>
                <strong>{job.invalidRows}</strong>
              </div>
              <div>
                <div style={{ color: 'var(--muted)', fontSize: '12px' }}>Needs review (&lt; 0.700)</div>
                <strong>{job.needsReviewCount}</strong>
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '18px' }}>
              {job.canRetry ? (
                <Button onClick={() => void handleRetry()}>Retry failed import</Button>
              ) : null}
              {job.canCancel ? (
                <Button variant="secondary" onClick={() => void handleCancel()}>
                  Cancel job
                </Button>
              ) : null}
            </div>
          </section>

          {job.errors.length > 0 ? (
            <section className="sl-card" aria-label="Quarantined invalid CSV rows">
              <h2 style={{ margin: '0 0 12px', fontSize: '17px', fontWeight: 600 }}>
                Row validation issues ({job.errors.length})
              </h2>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line)', textAlign: 'left' }}>
                    <th style={{ padding: '8px' }}>CSV line</th>
                    <th style={{ padding: '8px' }}>Error code</th>
                    <th style={{ padding: '8px' }}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {job.errors.map((err) => (
                    <tr key={err.sourceLineNo} style={{ borderBottom: '1px solid var(--line)' }}>
                      <td className="tabular-nums" style={{ padding: '8px' }}>
                        {err.sourceLineNo}
                      </td>
                      <td style={{ padding: '8px', fontWeight: 600 }}>{err.errorCode}</td>
                      <td style={{ padding: '8px', color: 'var(--muted)' }}>{err.errorDetail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
        </div>
      )}
    </LedgerShell>
  );
}

