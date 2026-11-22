import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import {
  AlertBanner,
  Button,
  SignedMoneyCell,
  StatusBadge,
} from '../components/UiPrimitives.js';
import { LedgerShell } from '../components/LedgerShell.js';
import { soloApi } from '../api/client.js';

describe('UiPrimitives & LedgerShell', () => {
  test('renders primitives with signed formatting and variants', () => {
    render(
      <div>
        <Button variant="primary" size="md">
          Primary
        </Button>
        <Button variant="secondary" size="sm">
          Secondary
        </Button>
        <Button variant="ghost">Ghost</Button>
        <Button variant="danger" disabled>
          Disabled
        </Button>
        <StatusBadge tone="success" label="COMPLETED" />
        <StatusBadge tone="warning" label="NEEDS_REVIEW" />
        <StatusBadge tone="danger" label="FAILED" />
        <StatusBadge tone="accent" label="PROCESSING" />
        <StatusBadge tone="neutral" label="SUGGESTED" />
        <SignedMoneyCell amount="-42.85" currency="USD" />
        <SignedMoneyCell amount="1500.00" currency="USD" />
        <AlertBanner kind="warning" title="Heads up" message="Test alert" />
        <AlertBanner kind="danger" message="Danger alert" />
        <AlertBanner kind="success" message="Success alert" />
      </div>,
    );

    expect(screen.getByRole('button', { name: 'Disabled' })).toBeDisabled();
    expect(screen.getByText('-$42.85')).toBeInTheDocument();
    expect(screen.getByText('+$1500.00')).toBeInTheDocument();
    expect(screen.getByText('Heads up')).toBeInTheDocument();
  });

  test('LedgerShell auto-selects first demo account and supports workspace switching', async () => {
    const accounts = [
      { id: 'acc-1', displayName: 'Studio North', timezone: 'UTC' },
      { id: 'acc-2', displayName: 'Cedar Labs', timezone: 'UTC' },
    ];
    let currentAcc = accounts[0]!;

    const listAccountsOrig = soloApi.listDemoAccounts;
    const getSessOrig = soloApi.getDemoSession;
    const switchOrig = soloApi.switchDemoSession;
    const listTxnsOrig = soloApi.listTransactions;

    soloApi.listDemoAccounts = async () => ({ items: accounts });
    let firstCall = true;
    soloApi.getDemoSession = async () => {
      if (firstCall) {
        firstCall = false;
        return { account: null, csrfToken: null };
      }
      return { account: currentAcc, csrfToken: 'csrf_test' };
    };
    soloApi.switchDemoSession = async (id: string) => {
      currentAcc = accounts.find((a) => a.id === id)!;
      return { account: currentAcc, csrfToken: `csrf_${id}` };
    };
    soloApi.listTransactions = async () => ({ items: [], nextCursor: null, totalCount: 3 });

    try {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      render(
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/dashboard']}>
            <LedgerShell title="Overview" subtitle="Test sub" actions={<span>ActionSlot</span>}>
              <div>ShellBody</div>
            </LedgerShell>
          </MemoryRouter>
        </QueryClientProvider>,
      );

      await waitFor(() => {
        expect(screen.getByText('Review (3)')).toBeInTheDocument();
      });

      const select = screen.getByLabelText('Demo workspace account');
      await userEvent.selectOptions(select, 'acc-2');
      await waitFor(() => {
        expect(currentAcc.id).toBe('acc-2');
      });
    } finally {
      soloApi.listDemoAccounts = listAccountsOrig;
      soloApi.getDemoSession = getSessOrig;
      soloApi.switchDemoSession = switchOrig;
      soloApi.listTransactions = listTxnsOrig;
    }
  });
});

