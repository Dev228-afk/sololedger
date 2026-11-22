import { useEffect, useRef, type ReactNode } from 'react';
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
          <div
            aria-hidden="true"
            style={{
              width: '30px',
              height: '30px',
              borderRadius: '9px',
              backgroundColor: 'var(--accent)',
              color: '#ffffff',
              display: 'grid',
              placeItems: 'center',
              fontSize: '13px',
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            SL
          </div>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 700, lineHeight: 1.2 }}>SoloLedger</div>
            <div style={{ fontSize: '11px', color: 'var(--muted)' }}>Synthetic Demo Ledger</div>
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
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  minHeight: '42px',
                  padding: '8px 12px',
                  borderRadius: 'var(--r-sm)',
                  textDecoration: 'none',
                  fontSize: '14px',
                  fontWeight: active ? 600 : 500,
                  backgroundColor: active ? 'var(--accent-soft)' : 'transparent',
                  color: active ? 'var(--accent-hover)' : 'var(--ink)',
                }}
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
            padding: '10px 12px',
            borderRadius: 'var(--r-sm)',
            backgroundColor: 'var(--surface-muted)',
            border: '1px solid var(--line)',
            fontSize: '12px',
            color: 'var(--muted)',
          }}
        >
          <strong style={{ color: 'var(--ink)', display: 'block', marginBottom: '2px' }}>
            Synthetic demo workspace
          </strong>
          No live bank connections or tax filing advice. Signed amounts (&minus; debit / + credit).
        </div>
      </aside>

      <div className="sl-workspace">
        <header className="sl-header">
          <div>
            <h1 style={{ margin: 0, fontSize: '26px', lineHeight: 1.25, fontWeight: 700 }}>
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
                value={activeAccount?.id ?? ''}
                onChange={(e) => {
                  if (e.target.value) switchAccount.mutate(e.target.value);
                }}
                style={{
                  minHeight: '38px',
                  padding: '6px 10px',
                  borderRadius: 'var(--r-sm)',
                  border: '1px solid var(--line)',
                  backgroundColor: 'var(--surface)',
                  color: 'var(--ink)',
                  fontSize: '13px',
                  fontWeight: 500,
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

        <main className="sl-main">{children}</main>
      </div>
    </div>
  );
}

