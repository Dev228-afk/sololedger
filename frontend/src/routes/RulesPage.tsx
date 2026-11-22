import { useState } from 'react';
import { SoloLedgerApiError, type MerchantRuleDto } from '../api/client.js';
import {
  useCategories,
  useDemoSession,
  useMerchantRules,
  usePatchMerchantRule,
} from '../api/hooks.js';
import { LedgerShell } from '../components/LedgerShell.js';
import { AlertBanner, Button, StatusBadge } from '../components/UiPrimitives.js';

export function RulesPage() {
  const { data: session } = useDemoSession();
  const accountId = session?.account?.id;
  const { data: rulesData, isLoading, refetch } = useMerchantRules(accountId);
  const { data: categories } = useCategories();
  const patchRule = usePatchMerchantRule();

  const [editingRule, setEditingRule] = useState<MerchantRuleDto | null>(null);
  const [nextCategory, setNextCategory] = useState('');
  const [nextPriority, setNextPriority] = useState('100');
  const [nextActive, setNextActive] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  function startEdit(rule: MerchantRuleDto) {
    setEditingRule(rule);
    setNextCategory(rule.categoryCode);
    setNextPriority(String(rule.priority));
    setNextActive(rule.active);
    setErrorMsg(null);
  }

  async function saveRule() {
    if (!editingRule) return;
    setErrorMsg(null);
    const parsedPriority = Number.parseInt(nextPriority, 10);
    try {
      await patchRule.mutateAsync({
        id: editingRule.id,
        version: editingRule.version,
        categoryCode: nextCategory,
        active: nextActive,
        priority: Number.isFinite(parsedPriority) ? parsedPriority : editingRule.priority,
      });
      setEditingRule(null);
    } catch (err) {
      setErrorMsg(err instanceof SoloLedgerApiError ? err.message : 'Failed to update rule.');
    }
  }

  return (
    <LedgerShell
      title="Merchant rules"
      subtitle="Explicitly approved account-scoped merchant associations used on future imports"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>
        <AlertBanner
          kind="info"
          message="Future-import semantics: updating or disabling a merchant rule applies only to future statement imports and never retroactively alters already approved historical transactions."
        />

        {editingRule ? (
          <section className="sl-card" aria-label="Edit merchant rule">
            <h2 style={{ margin: '0 0 10px', fontSize: '16px', fontWeight: 600 }}>
              Edit rule: <code>{editingRule.merchantKey}</code> (v{editingRule.version})
            </h2>
            {errorMsg ? (
              <div style={{ marginBottom: '10px' }}>
                <AlertBanner
                  kind="danger"
                  message={errorMsg}
                  action={
                    <Button size="sm" variant="secondary" onClick={() => void refetch()}>
                      Refresh rules
                    </Button>
                  }
                />
              </div>
            ) : null}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
              <select
                aria-label="Rule category"
                value={nextCategory}
                onChange={(e) => setNextCategory(e.target.value)}
                style={{ minHeight: '40px', padding: '6px 10px' }}
              >
                {categories?.items.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
              <label style={{ fontSize: '13px' }}>
                Priority{' '}
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={nextPriority}
                  onChange={(e) => setNextPriority(e.target.value)}
                  style={{ width: '80px', minHeight: '40px', padding: '6px 8px', marginLeft: '6px' }}
                />
              </label>
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '14px' }}>
                <input
                  type="checkbox"
                  checked={nextActive}
                  onChange={(e) => setNextActive(e.target.checked)}
                />
                Rule active
              </label>
              <Button size="sm" disabled={patchRule.isPending} onClick={() => void saveRule()}>
                Save rule
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setEditingRule(null)}>
                Cancel
              </Button>
            </div>
          </section>
        ) : null}

        <section className="sl-card" aria-label="Saved merchant rules table">
          {isLoading ? (
            <div>Loading merchant rules...</div>
          ) : (rulesData?.items.length ?? 0) === 0 ? (
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--muted)' }}>
              No merchant rules saved yet. Approve a transaction in the Review Queue with &ldquo;Remember this merchant&rdquo; checked to create your first rule.
            </p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--line)', textAlign: 'left', color: 'var(--muted)', fontSize: '12px' }}>
                    <th style={{ padding: '10px 8px' }}>Normalized merchant key</th>
                    <th style={{ padding: '10px 8px' }}>Mapped category</th>
                    <th style={{ padding: '10px 8px' }}>Priority</th>
                    <th style={{ padding: '10px 8px' }}>State</th>
                    <th style={{ padding: '10px 8px' }}>Version</th>
                    <th style={{ padding: '10px 8px' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rulesData?.items.map((r) => (
                    <tr key={r.id} style={{ borderBottom: '1px solid var(--line)' }}>
                      <td style={{ padding: '12px 8px', fontWeight: 600 }}>
                        <code>{r.merchantKey}</code>
                      </td>
                      <td style={{ padding: '12px 8px' }}>{r.categoryName}</td>
                      <td className="tabular-nums" style={{ padding: '12px 8px' }}>
                        {r.priority}
                      </td>
                      <td style={{ padding: '12px 8px' }}>
                        <StatusBadge
                          label={r.active ? 'Active' : 'Disabled'}
                          tone={r.active ? 'success' : 'neutral'}
                        />
                      </td>
                      <td className="tabular-nums" style={{ padding: '12px 8px' }}>
                        v{r.version}
                      </td>
                      <td style={{ padding: '12px 8px' }}>
                        <Button size="sm" variant="secondary" onClick={() => startEdit(r)}>
                          Edit rule
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </LedgerShell>
  );
}

