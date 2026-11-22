import { useEffect, useState } from 'react';
import { SoloLedgerApiError } from '../api/client.js';
import {
  useBulkReview,
  useCategories,
  useDemoSession,
  useReviewQueue,
  useReviewTransaction,
} from '../api/hooks.js';
import { LedgerShell } from '../components/LedgerShell.js';
import {
  AlertBanner,
  Button,
  SignedMoneyCell,
  StatusBadge,
} from '../components/UiPrimitives.js';

export function ReviewQueuePage() {
  const { data: session } = useDemoSession();
  const accountId = session?.account?.id;
  const { data: queueData, isLoading, refetch } = useReviewQueue(accountId);
  const { data: categories } = useCategories();
  const reviewMutation = useReviewTransaction();
  const bulkMutation = useBulkReview();

  const items = queueData?.items ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [chosenCategory, setChosenCategory] = useState<string>('UNCATEGORIZED');
  const [rememberMerchant, setRememberMerchant] = useState<boolean>(true);
  const [conflictState, setConflictState] = useState<{
    message: string;
    serverVersion?: number;
  } | null>(null);
  const [statusFeedback, setStatusFeedback] = useState<string | null>(null);

  const activeTxn = items.find((t) => t.id === selectedId) ?? items[0] ?? null;

  useEffect(() => {
    if (activeTxn && !conflictState) {
      setChosenCategory(activeTxn.categoryCode);
    }
  }, [activeTxn?.id, activeTxn?.categoryCode, conflictState]);

  async function submitDecision(decision: 'ACCEPT' | 'CHANGE') {
    if (!activeTxn) return;
    setConflictState(null);
    setStatusFeedback(null);
    try {
      await reviewMutation.mutateAsync({
        id: activeTxn.id,
        version: activeTxn.version,
        decision,
        categoryCode: chosenCategory,
        rememberMerchant,
      });
      setStatusFeedback(
        `Saved ${decision === 'ACCEPT' ? 'accepted' : 'updated'} category (${chosenCategory}) for ${activeTxn.merchant}.`,
      );
      setSelectedId(null);
    } catch (err) {
      if (err instanceof SoloLedgerApiError && err.code === 'VERSION_CONFLICT') {
        const currentVer = err.details?.currentVersion;
        // Preserve unsaved category & checkbox selection without wiping user work
        setConflictState({
          message: `${err.message} Your local selection (${chosenCategory}) is preserved below.`,
          serverVersion: typeof currentVer === 'number' ? currentVer : undefined,
        });
      } else {
        setConflictState({
          message: err instanceof SoloLedgerApiError ? err.message : 'Failed to save review decision.',
        });
      }
    }
  }

  async function handleBulkAcceptAll() {
    if (items.length === 0) return;
    setConflictState(null);
    setStatusFeedback(null);
    try {
      const payload = items.slice(0, 100).map((t) => ({
        transactionId: t.id,
        version: t.version,
        decision: 'ACCEPT' as const,
        categoryCode: t.categoryCode,
        rememberMerchant: false,
      }));
      const res = await bulkMutation.mutateAsync(payload);
      setStatusFeedback(
        `Bulk reviewed ${res.accepted.length} transactions (${res.conflicts.length} conflicts).`,
      );
    } catch (err) {
      setConflictState({
        message: err instanceof SoloLedgerApiError ? err.message : 'Bulk review failed.',
      });
    }
  }

  return (
    <LedgerShell
      title="Review queue"
      subtitle="Transactions routed for human confirmation (confidence below 0.700, missing confidence, or cross-import duplicate candidates)"
      actions={
        items.length > 0 ? (
          <Button
            size="sm"
            variant="secondary"
            disabled={bulkMutation.isPending}
            onClick={() => void handleBulkAcceptAll()}
          >
            Accept all {items.length} suggested
          </Button>
        ) : null
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {statusFeedback ? <AlertBanner kind="success" message={statusFeedback} /> : null}
        {conflictState ? (
          <AlertBanner
            kind="danger"
            title="Version conflict (HTTP 409)"
            message={conflictState.message}
            action={
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  setConflictState(null);
                  void refetch();
                }}
              >
                Refresh queue
              </Button>
            }
          />
        ) : null}

        {isLoading ? (
          <div className="sl-card">Loading review queue...</div>
        ) : items.length === 0 ? (
          <div className="sl-card">
            <h2 style={{ margin: '0 0 6px', fontSize: '18px', fontWeight: 600 }}>
              Review queue is clear
            </h2>
            <p style={{ margin: 0, color: 'var(--muted)', fontSize: '14px' }}>
              All imported transactions have confidence &gt;= 0.700 or have already been reviewed.
            </p>
          </div>
        ) : (
          <div className="sl-review-grid">
            <div
              className="sl-card"
              role="listbox"
              aria-label="Transactions needing review"
              style={{ padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}
            >
              {items.map((txn) => {
                const isSelected = activeTxn?.id === txn.id;
                return (
                  <button
                    key={txn.id}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => {
                      setConflictState(null);
                      setSelectedId(txn.id);
                      setChosenCategory(txn.categoryCode);
                    }}
                    style={{
                      width: '100%',
                      textAlign: 'left',
                      padding: '10px 12px',
                      borderRadius: 'var(--r-sm)',
                      border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--line)'}`,
                      backgroundColor: isSelected ? 'var(--accent-soft)' : 'var(--surface)',
                      cursor: 'pointer',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '4px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '6px' }}>
                      <strong style={{ fontSize: '13px', color: 'var(--ink)' }}>
                        {txn.merchant}
                      </strong>
                      <SignedMoneyCell amount={txn.signedAmount} currency={txn.currency} />
                    </div>
                    <div style={{ fontSize: '12px', color: 'var(--muted)', display: 'flex', justifyContent: 'space-between' }}>
                      <span>{txn.postedDate}</span>
                      <span>
                        conf: {txn.confidence ?? 'n/a'} · v{txn.version}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            {activeTxn ? (
              <section className="sl-card" aria-label="Selected transaction review detail">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                  <div>
                    <div style={{ fontSize: '12px', color: 'var(--muted)' }}>
                      {activeTxn.postedDate} · Version {activeTxn.version}
                    </div>
                    <h2 style={{ margin: '4px 0', fontSize: '20px', fontWeight: 700 }}>
                      {activeTxn.description}
                    </h2>
                    <div style={{ fontSize: '13px', color: 'var(--muted)' }}>
                      Normalized merchant: <code>{activeTxn.merchant}</code>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: '24px' }}>
                      <SignedMoneyCell amount={activeTxn.signedAmount} currency={activeTxn.currency} />
                    </div>
                    <div style={{ marginTop: '6px' }}>
                      <StatusBadge
                        tone="warning"
                        label={`Heuristic confidence: ${activeTxn.confidence ?? 'none'}`}
                      />
                    </div>
                  </div>
                </div>

                {activeTxn.duplicateCandidate ? (
                  <div style={{ marginTop: '14px' }}>
                    <AlertBanner
                      kind="warning"
                      title="Cross-import duplicate candidate"
                      message="Matches date, merchant, and amount (or external ID) from a previous import. Verify before approving."
                    />
                  </div>
                ) : null}

                <div
                  style={{
                    marginTop: '16px',
                    padding: '12px 14px',
                    borderRadius: 'var(--r-sm)',
                    backgroundColor: 'var(--surface-muted)',
                    fontSize: '13px',
                    color: 'var(--muted)',
                  }}
                >
                  Suggested source: <strong>{activeTxn.categorySource}</strong> · Explanation code:{' '}
                  <code>{activeTxn.explanationCode ?? 'LOW_CONFIDENCE_THRESHOLD'}</code> · Heuristic score below{' '}
                  <code>0.700</code> (not a calibrated probability).
                </div>

                <div style={{ marginTop: '18px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <label style={{ fontSize: '14px', fontWeight: 600 }}>
                    Category decision
                    <select
                      aria-label="Category for review"
                      value={chosenCategory}
                      onChange={(e) => setChosenCategory(e.target.value)}
                      style={{
                        display: 'block',
                        width: '100%',
                        maxWidth: '340px',
                        minHeight: '42px',
                        marginTop: '6px',
                        padding: '8px 10px',
                        borderRadius: 'var(--r-sm)',
                        border: '1px solid var(--line)',
                      }}
                    >
                      {categories?.items.map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.name} ({c.code})
                        </option>
                      ))}
                    </select>
                  </label>

                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', fontSize: '14px' }}>
                    <input
                      type="checkbox"
                      checked={rememberMerchant}
                      onChange={(e) => setRememberMerchant(e.target.checked)}
                    />
                    Remember this merchant (<code>{activeTxn.merchant}</code>) for future imports
                  </label>

                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
                    <Button
                      disabled={reviewMutation.isPending}
                      onClick={() =>
                        void submitDecision(
                          chosenCategory === activeTxn.categoryCode ? 'ACCEPT' : 'CHANGE',
                        )
                      }
                    >
                      {chosenCategory === activeTxn.categoryCode
                        ? 'Accept suggested category'
                        : 'Save changed category'}
                    </Button>
                  </div>
                </div>
              </section>
            ) : null}
          </div>
        )}
      </div>
    </LedgerShell>
  );
}

