import { useEffect, useRef, useState, type ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  Activity,
  BarChart3,
  BookOpenCheck,
  CheckSquare,
  FileUp,
  LayoutDashboard,
  ListOrdered,
} from 'lucide-react';
import {
  useDemoAccounts,
  useDemoSession,
  useReviewQueue,
  useSwitchDemoAccount,
} from '../api/hooks.js';
import { AlertBanner } from './UiPrimitives.js';

function SoloLedgerLogo() {
  return (
    <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true" style={{ flexShrink: 0 }}>
      <rect x="2" y="2" width="26" height="26" rx="8" fill="#10b981" />
      <path d="M9 10.5h12M9 15h8.5M9 19.5h10.5" stroke="#071912" strokeWidth="2.3" strokeLinecap="round" />
      <circle cx="21" cy="19.5" r="2" fill="#071912" />
    </svg>
  );
}

export function LedgerShell({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const location = useLocation();
  const { data: sessionData, isLoading: sessionLoading } = useDemoSession();
  const { data: accountsData } = useDemoAccounts();
  const switchAccount = useSwitchDemoAccount();
  const autoBootstrapped = useRef(false);
  const [accountNotice, setAccountNotice] = useState<string | null>(null);

  const activeAccount = sessionData?.account ?? null;
  const { data: queueData } = useReviewQueue(activeAccount?.id);
  const needsReviewCount = queueData?.totalCount ?? 0;

  useEffect(() => {
    if (
      !autoBootstrapped.current &&
      !sessionLoading &&
      !sessionData?.account &&
      accountsData?.items?.length &&
      !switchAccount.isPending
    ) {
      const first = accountsData.items[0];
      if (first) {
        autoBootstrapped.current = true;
        switchAccount.mutate(first.id);
      }
    }
  }, [sessionLoading, sessionData, accountsData, switchAccount]);

  const navItems = [
    { to: '/dashboard', label: 'Overview', icon: LayoutDashboard },
    { to: '/imports/new', label: 'Import statement', icon: FileUp },
    { to: '/transactions', label: 'Transactions', icon: ListOrdered },
    {
      to: '/review',
      label: needsReviewCount > 0 ? `Review (${needsReviewCount})` : 'Review queue',
      icon: CheckSquare,
    },
    { to: '/rules', label: 'Merchant rules', icon: BookOpenCheck },
    { to: '/reports', label: 'Reports', icon: BarChart3 },
    { to: '/engineering', label: 'Engineering', icon: Activity },
  ];

  return (
    <div className="sl-shell">
      <aside className="sl-sidebar" aria-label="Primary navigation">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '4px 6px' }}>
          <SoloLedgerLogo />
          <div>
            <div style={{ fontSize: '15px', fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--rail-ink)', lineHeight: 1.2 }}>
              SoloLedger
            </div>
            <div style={{ fontSize: '11px', color: 'var(--rail-muted)' }}>Minor-Unit Bookkeeping</div>
          </div>
        </div>

        <nav className="sl-nav" aria-label="Workspace navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active =
              location.pathname === item.to ||
              (item.to === '/imports/new' && location.pathname.startsWith('/imports/'));
            return (
              <NavLink
                key={item.to}
                to={item.to}
                aria-current={active ? 'page' : undefined}
                className={`sl-nav-link ${active ? 'active' : ''}`}
              >
                <Icon size={17} aria-hidden="true" />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div
          style={{
            marginTop: 'auto',
            padding: '12px',
            borderRadius: 'var(--r-sm)',
            backgroundColor: 'var(--rail-hover)',
            border: '1px solid var(--rail-border)',
            fontSize: '12px',
            color: 'var(--rail-muted)',
          }}
        >
          <strong style={{ color: 'var(--rail-ink)', display: 'block', marginBottom: '2px' }}>
            Synthetic demo workspace
          </strong>
          No live bank connections or tax filing advice. Signed amounts (&minus; debit / + credit).
        </div>
      </aside>

      <div className="sl-workspace">
        <header className="sl-header">
          <div>
            <h1 style={{ margin: 0, fontSize: '26px', letterSpacing: '-0.025em', lineHeight: 1.2, fontWeight: 700 }}>
              {title}
            </h1>
            {subtitle ? (
              <p style={{ margin: '2px 0 0', fontSize: '13px', color: 'var(--muted)' }}>
                {subtitle}
              </p>
            ) : null}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
            {actions}
            <label
              htmlFor="demo-account-select"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
                fontSize: '13px',
                color: 'var(--muted)',
              }}
            >
              <span>Workspace:</span>
              <select
                id="demo-account-select"
                aria-label="Demo workspace account"
                className="sl-input"
                value={activeAccount?.id ?? ''}
                onChange={(e) => {
                  const id = e.target.value;
                  if (!id) return;
                  const chosen = accountsData?.items.find((a) => a.id === id);
                  switchAccount.mutate(id, {
                    onSuccess: () => {
                      setAccountNotice(`Active workspace switched to ${chosen?.displayName ?? 'selected ledger'}.`);
                    },
                  });
                }}
                style={{
                  minHeight: '38px',
                  padding: '6px 10px',
                  fontSize: '13px',
                  fontWeight: 600,
                }}
              >
                {accountsData?.items.map((acc) => (
                  <option key={acc.id} value={acc.id}>
                    {acc.displayName}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </header>

        <main className="sl-main">
          {accountNotice ? (
            <div style={{ marginBottom: 'var(--space-4)' }}>
              <AlertBanner kind="info" message={accountNotice} />
            </div>
          ) : null}
          {children}
        </main>
      </div>
    </div>
  );
}
