import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AppRoutes } from '../App.js';
import { soloApi, SoloLedgerApiError } from '../api/client.js';

function createMockContext() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return qc;
}

describe('SoloLedger 8 routes integration UI tests', () => {
  const originals = { ...soloApi };

  beforeEach(() => {
    soloApi.getDemoSession = async () => ({
      account: { id: 'acc-1', displayName: 'Studio North', timezone: 'UTC' },
      csrfToken: 'csrf_test',
    });
    soloApi.listDemoAccounts = async () => ({
      items: [{ id: 'acc-1', displayName: 'Studio North', timezone: 'UTC' }],
    });
    soloApi.listCategories = async () => ({
      items: [
        { id: 'c1', code: 'SOFTWARE', name: 'Software & Cloud', kind: 'EXPENSE', sortOrder: 10 },
        { id: 'c2', code: 'EQUIPMENT', name: 'Hardware & Equipment', kind: 'EXPENSE', sortOrder: 20 },
        { id: 'c3', code: 'UNCATEGORIZED', name: 'Uncategorized', kind: 'EXPENSE', sortOrder: 30 },
      ],
    });
    soloApi.listTransactions = async () => ({
      items: [],
      nextCursor: null,
      totalCount: 0,
    });
    soloApi.listImports = async () => ({ items: [], nextCursor: null });
    soloApi.getMonthlyReport = async () => ({
      currency: 'USD',
      months: [],
      categoryTotals: [],
    });
    soloApi.listMerchantRules = async () => ({ items: [], nextCursor: null });
    soloApi.getHealth = async () => ({
      status: 'ok',
      version: '0.1.0',
      dependencies: { postgres: 'ok', redis: 'ok' },
    });
  });

  afterEach(() => {
    Object.assign(soloApi, originals);
  });

  function renderRoute(route: string) {
    const qc = createMockContext();
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[route]}>
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  test('/dashboard renders populated report totals, negative refunds, and Review CTA', async () => {
    soloApi.getMonthlyReport = async () => ({
      currency: 'USD',
      months: [
        {
          month: '2026-02',
          byCategory: [
            { code: 'EQUIPMENT', name: 'Hardware & Equipment', netSpend: '-50.00' },
            { code: 'SOFTWARE', name: 'Software & Cloud', netSpend: '125.00' },
          ],
          netSpend: '75.00',
          totalCredits: '150.00',
          totalDebits: '75.00',
        },
      ],
      categoryTotals: [
        { code: 'EQUIPMENT', name: 'Hardware & Equipment', netSpend: '-50.00' },
        { code: 'SOFTWARE', name: 'Software & Cloud', netSpend: '125.00' },
      ],
    });
    soloApi.listTransactions = async () => ({ items: [], nextCursor: null, totalCount: 2 });
    soloApi.listImports = async () => ({
      items: [
        {
          jobId: 'job-1',
          status: 'AWAITING_REVIEW',
          fileName: 'feb.csv',
          fileSha256: 'abc',
          totalRows: 5,
          processedRows: 5,
          validRows: 5,
          invalidRows: 0,
          needsReviewCount: 2,
          attempts: 1,
          createdAt: '2026-02-10T00:00:00Z',
        },
      ],
      nextCursor: null,
    });

    renderRoute('/dashboard');
    await waitFor(() => {
      expect(screen.getByTestId('dashboard-net-spend')).toHaveTextContent('$75.00');
    });
    expect(screen.getByText('Review 2 items')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Q1 2026' }));
    expect(screen.getByLabelText('From month')).toHaveValue('2026-01');
    expect(screen.getByLabelText('To month')).toHaveValue('2026-03');
  });

  test('/imports/new handles ambiguous dates, 409 duplicate import, and back navigation', async () => {
    soloApi.createImportPreview = async () => ({
      uploadToken: 'tok-1',
      fileName: 'amb.csv',
      sha256: 'deadbeef1234567890',
      headers: ['Date', 'Description', 'Amount'],
      previewRows: [{ Date: '02/03/2026', Description: 'TEST', Amount: '-10.00' }],
      suggestedMapping: {
        postedDateColumn: 'Date',
        descriptionColumn: 'Description',
        amountMode: 'SIGNED_AMOUNT',
        dateFormat: 'AMBIGUOUS_SLASH',
        decimalSeparator: '.',
        headerRow: 1,
      },
      expiresAt: '2026-02-11T00:00:00Z',
    });
    soloApi.createImport = async () => {
      throw new SoloLedgerApiError(409, {
        code: 'DUPLICATE_IMPORT',
        message: 'Duplicate statement.',
        requestId: 'req_dup',
        details: { existingImportId: 'job-existing' },
        fieldErrors: {},
      });
    };

    renderRoute('/imports/new');
    const fileInput = screen.getByTestId('csv-file-input');
    const file = new File(['Date,Description,Amount\n02/03/2026,TEST,-10.00'], 'amb.csv', {
      type: 'text/csv',
    });
    await userEvent.upload(fileInput, file);

    await waitFor(() => {
      expect(screen.getByText('Ambiguous slash dates detected')).toBeInTheDocument();
    });
    const continueBtn = screen.getByRole('button', { name: 'Continue to confirm' });
    expect(continueBtn).toBeDisabled();

    await userEvent.selectOptions(screen.getByLabelText('Date format'), '%m/%d/%Y');
    expect(continueBtn).toBeEnabled();
    await userEvent.click(continueBtn);

    await userEvent.click(screen.getByTestId('confirm-import-btn'));
    await waitFor(() => {
      expect(screen.getByText('View existing import')).toBeInTheDocument();
    });
  });

  test('/imports/:id shows error rows and retry/cancel triggers', async () => {
    soloApi.getImportDetail = async () => ({
      jobId: 'job-err',
      status: 'FAILED',
      fileName: 'broken.csv',
      fileSha256: 'fff',
      totalRows: 3,
      processedRows: 2,
      validRows: 2,
      invalidRows: 1,
      needsReviewCount: 0,
      attempts: 1,
      phaseLabel: 'Failed',
      errorCode: 'BAD_ROW',
      errorMessage: 'Row parse failed',
      canRetry: true,
      canCancel: false,
      startedAt: null,
      finishedAt: null,
      createdAt: '2026-02-10T00:00:00Z',
      errors: [{ sourceLineNo: 2, errorCode: 'INVALID_DATE', errorDetail: 'Bad date' }],
    });
    let retried = false;
    soloApi.retryImport = async () => {
      retried = true;
      return { jobId: 'job-err', status: 'QUEUED' };
    };

    renderRoute('/imports/job-err');
    await waitFor(() => {
      expect(screen.getByText('INVALID_DATE')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Retry failed import' }));
    expect(retried).toBe(true);
  });

  test('/transactions filters, opens inline editor, and handles pagination', async () => {
    soloApi.listTransactions = async () => ({
      items: [
        {
          id: 'tx-1',
          importJobId: 'j1',
          postedDate: '2026-02-01',
          description: 'DEMO CLOUD HOSTING',
          merchant: 'DEMO CLOUD HOSTING',
          signedAmount: '-25.00',
          currency: 'USD',
          externalRef: null,
          categoryCode: 'SOFTWARE',
          categoryName: 'Software & Cloud',
          categoryKind: 'EXPENSE',
          categorySource: 'KEYWORD',
          confidence: '0.950',
          reviewStatus: 'SUGGESTED',
          duplicateCandidate: false,
          explanationCode: 'EXACT',
          version: 1,
        },
      ],
      nextCursor: '2026-02-01|tx-1',
      totalCount: 2,
    });
    let saved = false;
    soloApi.reviewTransaction = async (_id, body) => {
      saved = body.categoryCode === 'EQUIPMENT';
      return {
        transaction: {
          id: 'tx-1',
          importJobId: 'j1',
          postedDate: '2026-02-01',
          description: 'DEMO CLOUD HOSTING',
          merchant: 'DEMO CLOUD HOSTING',
          signedAmount: '-25.00',
          currency: 'USD',
          externalRef: null,
          categoryCode: 'EQUIPMENT',
          categoryName: 'Hardware & Equipment',
          categoryKind: 'EXPENSE',
          categorySource: 'USER_REVIEW',
          confidence: '0.940',
          reviewStatus: 'APPROVED',
          duplicateCandidate: false,
          explanationCode: 'EXACT',
          version: 2,
        },
        reviewDecision: {
          id: 'rd1',
          transactionId: 'tx-1',
          previousCategoryCode: 'SOFTWARE',
          newCategoryCode: 'EQUIPMENT',
          previousStatus: 'SUGGESTED',
          decision: 'CHANGE',
          createdAt: '2026-02-02T00:00:00Z',
        },
      };
    };

    renderRoute('/transactions');
    await waitFor(() => {
      expect(screen.getAllByText('DEMO CLOUD HOSTING').length).toBeGreaterThan(0);
    });
    await userEvent.click(screen.getAllByRole('button', { name: 'Edit' })[1]!);
    await userEvent.selectOptions(screen.getByLabelText('Category choice'), 'EQUIPMENT');
    await userEvent.click(screen.getByRole('button', { name: 'Save decision' }));
    await waitFor(() => expect(saved).toBe(true));

    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(screen.getByRole('button', { name: 'First page' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'First page' }));
  });

  test('/review retains unsaved category on 409 conflict and allows bulk accept', async () => {
    soloApi.listTransactions = async () => ({
      items: [
        {
          id: 'tx-rev-1',
          importJobId: 'j1',
          postedDate: '2026-02-03',
          description: 'NORTHWOOD MART #402',
          merchant: 'NORTHWOOD MART',
          signedAmount: '-31.40',
          currency: 'USD',
          externalRef: null,
          categoryCode: 'UNCATEGORIZED',
          categoryName: 'Uncategorized',
          categoryKind: 'EXPENSE',
          categorySource: 'FALLBACK',
          confidence: '0.520',
          reviewStatus: 'NEEDS_REVIEW',
          duplicateCandidate: true,
          explanationCode: 'MOCK_TOKEN_MART',
          version: 1,
        },
      ],
      nextCursor: null,
      totalCount: 1,
    });
    soloApi.reviewTransaction = async () => {
      throw new SoloLedgerApiError(409, {
        code: 'VERSION_CONFLICT',
        message: 'Concurrent update occurred.',
        requestId: 'req_409',
        details: { currentVersion: 2 },
        fieldErrors: {},
      });
    };

    renderRoute('/review');
    await waitFor(() => {
      expect(screen.getByText('Cross-import duplicate candidate')).toBeInTheDocument();
    });
    expect(screen.getByText('Classification trace')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Software & Cloud' }));
    expect(screen.getByLabelText('Category for review')).toHaveValue('SOFTWARE');
    await userEvent.selectOptions(screen.getByLabelText('Category for review'), 'EQUIPMENT');
    expect(screen.getByLabelText('Category for review')).toHaveValue('EQUIPMENT');
    await userEvent.click(screen.getByRole('button', { name: 'Save changed category' }));

    await waitFor(() => {
      expect(screen.getByText(/Version conflict \(HTTP 409\)/i)).toBeInTheDocument();
    });
    expect(screen.getByLabelText('Category for review')).toHaveValue('EQUIPMENT');

    let bulkCalled = false;
    soloApi.bulkReview = async () => {
      bulkCalled = true;
      return { accepted: [], conflicts: [] };
    };
    await userEvent.click(screen.getByRole('button', { name: /Accept all/i }));
    await waitFor(() => expect(bulkCalled).toBe(true));
  });

  test('/rules lists saved rules and updates rule with optimistic version', async () => {
    soloApi.listMerchantRules = async () => ({
      items: [
        {
          id: 'rule-1',
          merchantKey: 'NORTHWOOD MART',
          categoryCode: 'SOFTWARE',
          categoryName: 'Software & Cloud',
          priority: 100,
          active: true,
          approvedAt: '2026-02-10T00:00:00Z',
          version: 1,
        },
      ],
      nextCursor: null,
    });
    let patched = false;
    soloApi.patchMerchantRule = async () => {
      patched = true;
      return {
        rule: {
          id: 'rule-1',
          merchantKey: 'NORTHWOOD MART',
          categoryCode: 'EQUIPMENT',
          categoryName: 'Hardware & Equipment',
          priority: 50,
          active: false,
          approvedAt: '2026-02-10T00:00:00Z',
          version: 2,
        },
      };
    };

    renderRoute('/rules');
    await waitFor(() => {
      expect(screen.getByText('NORTHWOOD MART')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Edit rule' }));
    await userEvent.selectOptions(screen.getByLabelText('Rule category'), 'EQUIPMENT');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '50' } });
    await userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => expect(patched).toBe(true));
  });

  test('/reports and /engineering render charts, export link, and provenance cards', async () => {
    soloApi.getMonthlyReport = async () => ({
      currency: 'USD',
      months: [
        {
          month: '2026-02',
          byCategory: [{ code: 'EQUIPMENT', name: 'Hardware & Equipment', netSpend: '-50.00' }],
          netSpend: '-50.00',
          totalCredits: '150.00',
          totalDebits: '100.00',
        },
      ],
      categoryTotals: [{ code: 'EQUIPMENT', name: 'Hardware & Equipment', netSpend: '-50.00' }],
    });

    const rep = renderRoute('/reports');
    await waitFor(() => {
      expect(screen.getByText('Net spend by expense category (USD)')).toBeInTheDocument();
    });
    expect(screen.getAllByText('-$50.00').length).toBeGreaterThan(0);
    rep.unmount();

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({}), { status: 404 })) as unknown as typeof fetch;
    try {
      renderRoute('/engineering');
      await waitFor(() => {
        expect(screen.getByText(/Held-out 12×90 classification evaluation/i)).toBeInTheDocument();
      });
      expect(screen.getByText('15 vs 45 min review')).toBeInTheDocument();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});

