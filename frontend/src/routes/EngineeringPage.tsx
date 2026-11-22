import { useQuery } from '@tanstack/react-query';
import { soloApi } from '../api/client.js';
import { slKeys } from '../api/hooks.js';
import { LedgerShell } from '../components/LedgerShell.js';
import { StatusBadge } from '../components/UiPrimitives.js';

interface EvalSummaryJson {
  datasetSha256: string;
  heldOutRows: number;
  heldOutFirstPassAccuracy: number;
  heldOutMacroF1: number;
  abstentionRate: number;
  postReviewAccuracy: number;
  secondImportRememberedAccuracy: number;
}

interface CoverageTotalJson {
  total?: {
    lines?: { pct: number; covered: number; total: number };
    branches?: { pct: number; covered: number; total: number };
    functions?: { pct: number; covered: number; total: number };
    statements?: { pct: number; covered: number; total: number };
  };
  totals?: {
    percent_covered?: number;
    covered_lines?: number;
    num_statements?: number;
  };
}

interface LoadSummaryJson {
  vus: number;
  durationSec: number;
  requestsPerSec: number;
  totalRequests: number;
  failureRatePct: number;
  p50Ms: number;
  p95Ms: number;
  p99Ms: number;
  classification: string;
}

async function fetchOptionalJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export function EngineeringPage() {
  const { data: health } = useQuery({
    queryKey: slKeys.health(),
    queryFn: ({ signal }) => soloApi.getHealth(signal),
  });
  const { data: evalData } = useQuery({
    queryKey: ['evidence-eval'],
    queryFn: () => fetchOptionalJson<EvalSummaryJson>('/evidence/eval-report.json'),
  });
  const { data: backendCov } = useQuery({
    queryKey: ['evidence-be-cov'],
    queryFn: () => fetchOptionalJson<CoverageTotalJson>('/evidence/backend-coverage.json'),
  });
  const { data: frontendCov } = useQuery({
    queryKey: ['evidence-fe-cov'],
    queryFn: () => fetchOptionalJson<CoverageTotalJson>('/evidence/frontend-coverage.json'),
  });
  const { data: loadSummary } = useQuery({
    queryKey: ['evidence-load'],
    queryFn: () => fetchOptionalJson<LoadSummaryJson>('/evidence/load-summary.json'),
  });

  const bePct = backendCov?.totals?.percent_covered;
  const feLines = frontendCov?.total?.lines?.pct;

  return (
    <LedgerShell
      title="Engineering & evidence"
      subtitle="Live dependencies, separate backend/frontend coverage scopes, held-out classification eval, and provenance labels"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
        <section className="sl-card">
          <h2 style={{ margin: '0 0 12px', fontSize: '18px', fontWeight: 600 }}>
            Live backend & broker health (<code>/api/v1/health</code>)
          </h2>
          <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
            {Object.entries(health?.dependencies ?? {}).map(([dep, state]) => (
              <div
                key={dep}
                style={{
                  padding: '8px 12px',
                  border: '1px solid var(--line)',
                  borderRadius: 'var(--r-sm)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <strong>{dep}</strong>
                <StatusBadge label={state} tone={state === 'ok' ? 'success' : 'danger'} />
              </div>
            ))}
          </div>
        </section>

        <section className="sl-card">
          <h2 style={{ margin: '0 0 12px', fontSize: '18px', fontWeight: 600 }}>
            Separate test coverage gates (&gt;=91% per measured scope)
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px' }}>
            <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                Backend Pytest (<code>apps</code>, <code>classification</code>, <code>tasks</code>)
              </div>
              <div className="tabular-nums" style={{ fontSize: '24px', fontWeight: 700 }}>
                {bePct !== undefined ? `${bePct.toFixed(2)}%` : 'Run make coverage'}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                Reported separately; never averaged with frontend Jest coverage.
              </div>
            </div>

            <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                Frontend Jest + RTL (<code>src/{'{components,routes,api}'}</code>)
              </div>
              <div className="tabular-nums" style={{ fontSize: '24px', fontWeight: 700 }}>
                {feLines !== undefined ? `${feLines.toFixed(2)}%` : 'Run pnpm test:coverage'}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                Threshold: &gt;= 91% across lines, statements, branches, functions.
              </div>
            </div>
          </div>
        </section>

        <section className="sl-card">
          <h2 style={{ margin: '0 0 12px', fontSize: '18px', fontWeight: 600 }}>
            Held-out 12×90 classification evaluation & provenance
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
            <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>REPRODUCED — Held-out accuracy</div>
              <div className="tabular-nums" style={{ fontSize: '20px', fontWeight: 700 }}>
                {evalData ? `${(evalData.heldOutFirstPassAccuracy * 100).toFixed(1)}%` : 'Pending eval'}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                {evalData
                  ? `Macro F1: ${evalData.heldOutMacroF1.toFixed(3)} · Post-review: ${(evalData.postReviewAccuracy * 100).toFixed(1)}%`
                  : 'Run scripts/score_classifier.py'}
              </div>
            </div>

            <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                LOCAL LOAD RUN ({loadSummary ? loadSummary.classification : 'TARGET: 500 VU / <150ms'})
              </div>
              <div className="tabular-nums" style={{ fontSize: '20px', fontWeight: 700 }}>
                {loadSummary ? `${loadSummary.p95Ms.toFixed(1)} ms p95` : 'Pending load run'}
              </div>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                {loadSummary
                  ? `${loadSummary.vus} VUs · ${loadSummary.requestsPerSec.toFixed(1)} req/s · ${loadSummary.failureRatePct.toFixed(2)}% err`
                  : 'Single-host Waitress benchmark'}
              </div>
            </div>

            <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>NOT_REPRODUCED — Human timing</div>
              <div style={{ fontSize: '16px', fontWeight: 700 }}>15 vs 45 min review</div>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                Historical resume claim; study protocol documented in <code>evidence/human-study/PROTOCOL.md</code>.
              </div>
            </div>

            <div style={{ padding: '12px', border: '1px solid var(--line)', borderRadius: 'var(--r-sm)' }}>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>BLOCKED_EXTERNAL</div>
              <div style={{ fontSize: '16px', fontWeight: 700 }}>AWS ECS/S3 & Live LLM</div>
              <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                Terraform authored cleanly; apply & live API keys require explicit user approval (<code>CLOUD_APPROVAL.md</code>).
              </div>
            </div>
          </div>
        </section>
      </div>
    </LedgerShell>
  );
}

