import { useState } from 'react';
import { soloApi, SoloLedgerApiError, type TransactionDto } from '../api/client.js';
import {
  useCategories,
  useDemoSession,
  useReviewTransaction,
  useTransactions,
} from '../api/hooks.js';
import { LedgerShell } from '../components/LedgerShell.js';
import {
  AlertBanner,
  Button,
  SignedMoneyCell,
  StatusBadge,
} from '../components/UiPrimitives.js';

export function TransactionsPage() {
  const { data: session } = useDemoSession();
  const accountId = session?.account?.id;
  const { data: categories } = useCategories();
  const reviewMutation = useReviewTransaction();

  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [reviewStatus, setReviewStatus] = useState('');
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [editingTxn, setEditingTxn] = useState<TransactionDto | null>(null);
  const [selectedCategoryCode, setSelectedCategoryCode] = useState('');
  const [rememberMerchant, setRememberMerchant] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  const { data, isLoading, refetch } = useTransactions(accountId, {
    q: q || undefined,
    category: category || undefined,
    reviewStatus: reviewStatus || undefined,
    cursor,
    limit: 50,
  });

  function startInlineEdit(txn: TransactionDto) {
    setEditingTxn(txn);
    setSelectedCategoryCode(txn.categoryCode);
    setRememberMerchant(false);
    setEditError(null);
  }

  async function saveInlineEdit() {
    if (!editingTxn) return;
    setEditError(null);
    try {
      await reviewMutation.mutateAsync({
        id: editingTxn.id,
        version: editingTxn.version,
        decision: selectedCategoryCode === editingTxn.categoryCode ? 'ACCEPT' : 'CHANGE',
        categoryCode: selectedCategoryCode,
        rememberMerchant,
      });
      setEditingTxn(null);
    } catch (err) {
      setEditError(
        err instanceof SoloLedgerApiError ? err.message : 'Failed to update transaction.',
      );
    }
  }

  return (
    <LedgerShell
      title="Transactions"
      subtitle="Signed USD ledger (debit negative / credit positive) with exact SQL cursor pagination"
      actions={
        <a
          href={soloApi.buildCsvExportUrl({ q, category, reviewStatus })}
          download="sololedger-ledger.csv"
          className="sl-btn-link sl-btn-link--secondary"
        >
          Export ledger
        </a>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
        <div
          className="sl-card"
          style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-end' }}
        >
          <label style={{ fontSize: '13px', flex: '1 1 220px' }}>
            Search merchant
            <input
              type="search"
              className="sl-input"
              placeholder="e.g. DEMO CLOUD"
              value={q}
              onChange={(e) => {
                setCursor(undefined);
                setQ(e.target.value);
              }}
              style={{
                width: '100%',
                minHeight: '40px',
                marginTop: '4px',
                padding: '6px 10px',
              }}
            />
          </label>

          <label style={{ fontSize: '13px' }}>
            Category
            <select
              aria-label="Filter by category"
              className="sl-input"
              value={category}
              onChange={(e) => {
                setCursor(undefined);
                setCategory(e.target.value);
              }}
              style={{
                display: 'block',
                minHeight: '40px',
                marginTop: '4px',
                padding: '6px 10px',
              }}
            >
              <option value="">All categories</option>
              {categories?.items.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>

          <label style={{ fontSize: '13px' }}>
            Review status
            <select
              aria-label="Filter by review status"
              className="sl-input"
              value={reviewStatus}
              onChange={(e) => {
                setCursor(undefined);
                setReviewStatus(e.target.value);
              }}
              style={{
                display: 'block',
                minHeight: '40px',
                marginTop: '4px',
                padding: '6px 10px',
              }}
            >
              <option value="">All statuses</option>
              <option value="NEEDS_REVIEW">NEEDS_REVIEW</option>
              <option value="SUGGESTED">SUGGESTED</option>
              <option value="APPROVED">APPROVED</option>
            </select>
          </label>
        </div>

        {editingTxn ? (
          <div className="sl-card" role="region" aria-label="Edit transaction category">
            <h2 style={{ margin: '0 0 10px', fontSize: '16px', fontWeight: 600 }}>
              Update category: {editingTxn.description}
            </h2>
            {editError ? (
              <div style={{ marginBottom: '10px' }}>
                <AlertBanner
                  kind="danger"
                  message={editError}
                  action={
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void refetch()}
                    >
                      Refresh ledger
                    </Button>
                  }
                />
              </div>
            ) : null}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
              <select
                aria-label="Category choice"
                value={selectedCategoryCode}
                onChange={(e) => setSelectedCategoryCode(e.target.value)}
                style={{ minHeight: '40px', padding: '6px 10px' }}
              >
                {categories?.items.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '14px' }}>
                <input
                  type="checkbox"
                  checked={rememberMerchant}
                  onChange={(e) => setRememberMerchant(e.target.checked)}
                />
                Remember this merchant
              </label>
              <Button size="sm" onClick={() => void saveInlineEdit()}>
                Save decision
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setEditingTxn(null)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : null}

        <div className="sl-card">
          {isLoading ? (
            <div>Loading ledger rows...</div>
          ) : (data?.items.length ?? 0) === 0 ? (
            <div style={{ color: 'var(--muted)', fontSize: '14px' }}>
              No transactions match the active filters.
            </div>
          ) : (
            <>
              <div className="sl-desktop-table">
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                  <thead>
                    <tr
                      style={{
                        borderBottom: '1px solid var(--line)',
                        textAlign: 'left',
                        color: 'var(--muted)',
                        fontSize: '12px',
                      }}
                    >
                      <th style={{ padding: '10px 8px' }}>Date</th>
                      <th style={{ padding: '10px 8px' }}>Merchant</th>
                      <th style={{ padding: '10px 8px' }}>Category</th>
                      <th style={{ padding: '10px 8px' }}>Confidence</th>
                      <th style={{ padding: '10px 8px', textAlign: 'right' }}>Amount</th>
                      <th style={{ padding: '10px 8px' }}>Status</th>
                      <th style={{ padding: '10px 8px' }}>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data?.items.map((t) => (
                      <tr key={t.id} className="sl-row-hover" style={{ borderBottom: '1px solid var(--line)' }}>
                        <td className="tabular-nums" style={{ padding: '12px 8px', whiteSpace: 'nowrap' }}>
                          {t.postedDate}
                        </td>
                        <td style={{ padding: '12px 8px', fontWeight: 500 }}>{t.description}</td>
                        <td style={{ padding: '12px 8px' }}>{t.categoryName}</td>
                        <td className="tabular-nums" style={{ padding: '12px 8px', color: 'var(--muted)' }}>
                          {t.confidence ?? '—'}
                        </td>
                        <td style={{ padding: '12px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                          <SignedMoneyCell amount={t.signedAmount} currency={t.currency} />
                        </td>
                        <td style={{ padding: '12px 8px' }}>
                          <StatusBadge
                            label={t.reviewStatus}
                            tone={
                              t.reviewStatus === 'APPROVED'
                                ? 'success'
                                : t.reviewStatus === 'NEEDS_REVIEW'
                                  ? 'warning'
                                  : 'neutral'
                            }
                          />
                        </td>
                        <td style={{ padding: '12px 8px' }}>
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => startInlineEdit(t)}
                          >
                            Edit
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="sl-mobile-cards" aria-label="Transactions card list">
                {data?.items.map((t) => (
                  <div
                    key={t.id}
                    style={{
                      padding: '12px',
                      border: '1px solid var(--line)',
                      borderRadius: 'var(--r-sm)',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong style={{ fontSize: '14px' }}>{t.description}</strong>
                      <SignedMoneyCell amount={t.signedAmount} currency={t.currency} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--muted)' }}>
                      <span>{t.postedDate}</span>
                      <span>{t.categoryName}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '4px' }}>
                      <StatusBadge
                        label={t.reviewStatus}
                        tone={t.reviewStatus === 'APPROVED' ? 'success' : 'warning'}
                      />
                      <Button size="sm" variant="secondary" onClick={() => startInlineEdit(t)}>
                        Edit
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}

          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginTop: '14px',
              fontSize: '13px',
              color: 'var(--muted)',
            }}
          >
            <span className="tabular-nums">Total matching: {data?.totalCount ?? 0}</span>
            <div style={{ display: 'flex', gap: '8px' }}>
              {cursor ? (
                <Button size="sm" variant="secondary" onClick={() => setCursor(undefined)}>
                  First page
                </Button>
              ) : null}
              {data?.nextCursor ? (
                <Button size="sm" variant="secondary" onClick={() => setCursor(data.nextCursor!)}>
                  Next page
                </Button>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </LedgerShell>
  );
}

