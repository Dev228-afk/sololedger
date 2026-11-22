import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { AppRoutes } from '../App.js';
import { soloApi, SoloLedgerApiError } from '../api/client.js';

function renderAt(route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Route empty states, error banners, filters & edge branches', () => {
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
      ],
    });
    soloApi.listTransactions = async () => ({ items: [], nextCursor: null, totalCount: 0 });
    soloApi.listImports = async () => ({ items: [], nextCursor: null });
    soloApi.getMonthlyReport = async () => ({ currency: 'USD', months: [], categoryTotals: [] });
    soloApi.listMerchantRules = async () => ({ items: [], nextCursor: null });
    soloApi.getHealth = async () => ({
      status: 'degraded',
      version: '0.1.0',
      dependencies: { postgres: 'ok', redis: 'unavailable' },
    });
  });

  afterEach(() => {
    Object.assign(soloApi, originals);
  });

  test('/dashboard empty prompt & month filter changes', async () => {
    renderAt('/dashboard');
    await waitFor(() => {
      expect(screen.getByText('No imported statements in this demo workspace yet')).toBeInTheDocument();
    });
    fireEvent.change(screen.getByLabelText('From month'), { target: { value: '2026-02' } });
    fireEvent.change(screen.getByLabelText('To month'), { target: { value: '2026-03' } });
    expect(screen.getByLabelText('From month')).toHaveValue('2026-02');
  });

  test('/imports/new drag-drop upload error, column mapping switches & step navigation', async () => {
    soloApi.createImportPreview = async () => {
      throw new SoloLedgerApiError(422, {
        code: 'UNPARSEABLE',
        message: 'Bad file headers.',
        requestId: 'req_u',
        details: {},
        fieldErrors: {},
      });
    };

    renderAt('/imports/new');
    const dropText = screen.getByText(/Drag and drop a UTF-8/i);
    const dropZone = dropText.closest('div')!;
    fireEvent.dragOver(dropZone);
    fireEvent.dragLeave(dropZone);
    const badFile = new File(['bad'], 'bad.csv', { type: 'text/csv' });
    fireEvent.drop(dropZone, { dataTransfer: { files: [badFile] } });

    await waitFor(() => {
      expect(screen.getByText('Bad file headers.')).toBeInTheDocument();
    });

    // Next attempt succeeds cleanly and exercises all mapping dropdowns + Back button
    soloApi.createImportPreview = async () => ({
      uploadToken: 'tok-2',
      fileName: 'good.csv',
      sha256: '1234567890abcdef',
      headers: ['Date', 'Merchant', 'Amount'],
      previewRows: [{ Date: '2026-02-01', Merchant: 'ACME', Amount: '-10.00' }],
      suggestedMapping: {
        postedDateColumn: 'Date',
        descriptionColumn: 'Merchant',
        amountMode: 'SIGNED_AMOUNT',
        dateFormat: '%Y-%m-%d',
        decimalSeparator: '.',
        headerRow: 1,
      },
      expiresAt: '2026-02-11T00:00:00Z',
    });

    await userEvent.upload(
      screen.getByTestId('csv-file-input'),
      new File(['Date,Merchant,Amount\n2026-02-01,ACME,-10.00'], 'good.csv', { type: 'text/csv' }),
    );
    await waitFor(() => {
      expect(screen.getByLabelText('Posted date column')).toBeInTheDocument();
    });

    await userEvent.selectOptions(screen.getByLabelText('Posted date column'), 'Date');
    await userEvent.selectOptions(screen.getByLabelText('Description / Merchant column'), 'Merchant');
    await userEvent.selectOptions(screen.getByLabelText('Amount representation'), 'DEBIT_CREDIT');
    await userEvent.click(screen.getByRole('button', { name: 'Continue to confirm' }));
    await userEvent.click(screen.getByRole('button', { name: 'Edit mapping' }));
    await userEvent.click(screen.getByRole('button', { name: 'Back to file picker' }));
    expect(screen.getByRole('button', { name: 'Choose CSV file' })).toBeInTheDocument();
  });

  test('/imports/:id error and completed statuses', async () => {
    // Error loading import detail + COMPLETED status
    soloApi.getImportDetail = async () => {
      throw new SoloLedgerApiError(404, {
        code: 'NOT_FOUND',
        message: 'Import not found.',
        requestId: 'req_404',
        details: {},
        fieldErrors: {},
      });
    };
    const errView = renderAt('/imports/missing');
    await waitFor(() => {
      expect(screen.getByText('Import not found.')).toBeInTheDocument();
    });
    errView.unmount();

    soloApi.getImportDetail = async () => ({
      jobId: 'job-comp',
      status: 'COMPLETED',
      fileName: 'done.csv',
      fileSha256: 'bbb',
      totalRows: 5,
      processedRows: 5,
      validRows: 5,
      invalidRows: 0,
      needsReviewCount: 2,
      attempts: 1,
      phaseLabel: 'Completed',
      errorCode: null,
      errorMessage: null,
      canRetry: false,
      canCancel: false,
      startedAt: '2026-02-01T00:00:00Z',
      finishedAt: '2026-02-01T00:00:02Z',
      createdAt: '2026-02-01T00:00:00Z',
      errors: [],
    });
    renderAt('/imports/job-comp');
    await waitFor(() => {
      expect(screen.getByText('Review 2 items')).toBeInTheDocument();
    });
  });

  test('/rules error conflict/cancel, /reports month filters + positive bar, /transactions empty state', async () => {
    soloApi.listMerchantRules = async () => ({
      items: [
        {
          id: 'r1',
          merchantKey: 'TEST SHOP',
          categoryCode: 'SOFTWARE',
          categoryName: 'Software & Cloud',
          priority: 100,
          active: false,
          approvedAt: '2026-02-10T00:00:00Z',
          version: 1,
        },
      ],
      nextCursor: null,
    });
    soloApi.patchMerchantRule = async () => {
      throw new SoloLedgerApiError(409, {
        code: 'VERSION_CONFLICT',
        message: 'Rule changed concurrently.',
        requestId: 'req_r409',
        details: {},
        fieldErrors: {},
      });
    };
    const rView = renderAt('/rules');
    await waitFor(() => {
      expect(screen.getByText('Disabled')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Edit rule' }));
    await userEvent.click(screen.getByLabelText('Rule active'));
    await userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => {
      expect(screen.getByText('Rule changed concurrently.')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Refresh rules' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    rView.unmount();

    soloApi.getMonthlyReport = async () => ({
      currency: 'USD',
      months: [
        {
          month: '2026-02',
          byCategory: [{ code: 'SOFTWARE', name: 'Software & Cloud', netSpend: '75.00' }],
          netSpend: '75.00',
          totalCredits: '0.00',
          totalDebits: '75.00',
        },
      ],
      categoryTotals: [
        { code: 'SOFTWARE', name: 'Software & Cloud', netSpend: '75.00' },
        { code: 'EQUIPMENT', name: 'Hardware & Equipment', netSpend: '-25.00' },
      ],
    });
    const repView = renderAt('/reports');
    await waitFor(() => {
      expect(screen.getAllByText('$75.00').length).toBeGreaterThan(0);
    });
    const monthInputs = screen.getAllByDisplayValue(/2026-/);
    fireEvent.change(monthInputs[0]!, { target: { value: '2026-02' } });
    fireEvent.change(monthInputs[1]!, { target: { value: '2026-04' } });
    repView.unmount();

    const txView = renderAt('/transactions');
    await waitFor(() => {
      expect(screen.getByText('No transactions match the active filters.')).toBeInTheDocument();
    });
    txView.unmount();
  });

  test('ImportDetailPage FAILED retry error & Cancel error + ReviewQueue bulk failure', async () => {
    soloApi.getImportDetail = async () => ({
      jobId: 'job-fail',
      status: 'FAILED',
      fileName: 'err.csv',
      fileSha256: 'ccc',
      totalRows: 5,
      processedRows: 0,
      validRows: 0,
      invalidRows: 0,
      needsReviewCount: 0,
      attempts: 1,
      phaseLabel: 'Failed',
      errorCode: 'ERR',
      errorMessage: 'Failed',
      canRetry: true,
      canCancel: true,
      startedAt: null,
      finishedAt: null,
      createdAt: '2026-02-01T00:00:00Z',
      errors: [],
    });
    soloApi.retryImport = async () => {
      throw new Error('Retry boom');
    };
    soloApi.cancelImport = async () => {
      throw new SoloLedgerApiError(409, {
        code: 'INVALID_STATE',
        message: 'Cannot cancel terminal.',
        requestId: 'req_c',
        details: {},
        fieldErrors: {},
      });
    };
    const dView = renderAt('/imports/job-fail');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Retry failed import' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Retry failed import' }));
    await waitFor(() => expect(screen.getByText('Retry failed.')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Cancel job' }));
    await waitFor(() => expect(screen.getByText('Cannot cancel terminal.')).toBeInTheDocument());
    dView.unmount();

    // ImportWizard non-SoloLedgerApiError & Cancel / Bulk error on /review
    soloApi.createImportPreview = async () => {
      throw new Error('Offline preview');
    };
    const wView = renderAt('/imports/new');
    await userEvent.upload(
      screen.getByTestId('csv-file-input'),
      new File(['a'], 'a.csv', { type: 'text/csv' }),
    );
    await waitFor(() => {
      expect(screen.getByText('Failed to upload CSV preview.')).toBeInTheDocument();
    });
    wView.unmount();

    soloApi.listTransactions = async () => ({
      items: [
        {
          id: 't1',
          importJobId: 'j1',
          postedDate: '2026-02-01',
          description: 'ITEM',
          merchant: 'ITEM',
          signedAmount: '-10.00',
          currency: 'USD',
          externalRef: null,
          categoryCode: 'SOFTWARE',
          categoryName: 'Software & Cloud',
          categoryKind: 'EXPENSE',
          categorySource: 'KEYWORD',
          confidence: '0.600',
          reviewStatus: 'NEEDS_REVIEW',
          duplicateCandidate: false,
          explanationCode: null,
          version: 1,
        },
      ],
      nextCursor: null,
      totalCount: 1,
    });
    soloApi.bulkReview = async () => {
      throw new Error('Bulk failed');
    };
    renderAt('/review');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Accept all/i })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: /Accept all/i }));
    await waitFor(() => {
      expect(screen.getByText('Bulk review failed.')).toBeInTheDocument();
    });
  });

  test('/imports/:id active job cooperative cancel', async () => {
    soloApi.getImportDetail = async () => ({
      jobId: 'job-run',
      status: 'PROCESSING',
      fileName: 'running.csv',
      fileSha256: 'aaa',
      totalRows: 90,
      processedRows: 30,
      validRows: 30,
      invalidRows: 0,
      needsReviewCount: 0,
      attempts: 1,
      phaseLabel: 'Categorizing transactions',
      errorCode: null,
      errorMessage: null,
      canRetry: false,
      canCancel: true,
      startedAt: '2026-02-01T00:00:00Z',
      finishedAt: null,
      createdAt: '2026-02-01T00:00:00Z',
      errors: [],
    });
    let canceled = false;
    soloApi.cancelImport = async () => {
      canceled = true;
      return { jobId: 'job-run', status: 'CANCELED' };
    };

    renderAt('/imports/job-run');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Cancel job' })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Cancel job' }));
    expect(canceled).toBe(true);
  });

  test('/transactions filters, empty state, and inline edit error + cancel', async () => {
    soloApi.listTransactions = async () => ({
      items: [
        {
          id: 't1',
          importJobId: 'j1',
          postedDate: '2026-02-01',
          description: 'X',
          merchant: 'X',
          signedAmount: '-12.00',
          currency: 'USD',
          externalRef: null,
          categoryCode: 'SOFTWARE',
          categoryName: 'Software & Cloud',
          categoryKind: 'EXPENSE',
          categorySource: 'KEYWORD',
          confidence: null,
          reviewStatus: 'NEEDS_REVIEW',
          duplicateCandidate: false,
          explanationCode: null,
          version: 1,
        },
      ],
      nextCursor: null,
      totalCount: 1,
    });
    soloApi.reviewTransaction = async () => {
      throw new SoloLedgerApiError(409, {
        code: 'VERSION_CONFLICT',
        message: 'Stale row.',
        requestId: 'req_1',
        details: {},
        fieldErrors: {},
      });
    };

    renderAt('/transactions');
    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: 'Edit' }).length).toBeGreaterThan(0);
    });

    await userEvent.type(screen.getByLabelText('Search merchant'), 'DEMO');
    await userEvent.selectOptions(screen.getByLabelText('Filter by category'), 'SOFTWARE');
    await userEvent.selectOptions(screen.getByLabelText('Filter by review status'), 'NEEDS_REVIEW');

    await userEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]!);
    await userEvent.click(screen.getByLabelText('Remember this merchant'));
    await userEvent.click(screen.getByRole('button', { name: 'Save decision' }));
    await waitFor(() => {
      expect(screen.getByText('Stale row.')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Refresh ledger' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  });

  test('/review queue accepts suggested item, switches selection, and renders empty state', async () => {
    const itemsList = [
      {
        id: 't1',
        importJobId: 'j1',
        postedDate: '2026-02-01',
        description: 'ITEM ONE',
        merchant: 'ITEM ONE',
        signedAmount: '-10.00',
        currency: 'USD',
        externalRef: null,
        categoryCode: 'SOFTWARE',
        categoryName: 'Software & Cloud',
        categoryKind: 'EXPENSE',
        categorySource: 'LLM' as const,
        confidence: '0.620',
        reviewStatus: 'NEEDS_REVIEW' as const,
        duplicateCandidate: false,
        explanationCode: 'LOW',
        version: 1,
      },
      {
        id: 't2',
        importJobId: 'j1',
        postedDate: '2026-02-02',
        description: 'ITEM TWO',
        merchant: 'ITEM TWO',
        signedAmount: '-20.00',
        currency: 'USD',
        externalRef: null,
        categoryCode: 'EQUIPMENT',
        categoryName: 'Hardware & Equipment',
        categoryKind: 'EXPENSE',
        categorySource: 'LLM' as const,
        confidence: null,
        reviewStatus: 'NEEDS_REVIEW' as const,
        duplicateCandidate: false,
        explanationCode: null,
        version: 1,
      },
    ];
    soloApi.listTransactions = async () => ({
      items: itemsList,
      nextCursor: null,
      totalCount: 2,
    });
    let acceptedId = '';
    soloApi.reviewTransaction = async (id) => {
      acceptedId = id;
      return {
        transaction: { ...itemsList[1]!, reviewStatus: 'APPROVED', version: 2 },
        reviewDecision: {
          id: 'rd',
          transactionId: id,
          previousCategoryCode: 'EQUIPMENT',
          newCategoryCode: 'EQUIPMENT',
          previousStatus: 'NEEDS_REVIEW',
          decision: 'ACCEPT',
          createdAt: '2026-02-03T00:00:00Z',
        },
      };
    };

    const view = renderAt('/review');
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /ITEM TWO/i })).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('option', { name: /ITEM TWO/i }));
    await userEvent.click(screen.getByRole('checkbox'));
    await userEvent.click(screen.getByRole('button', { name: 'Accept suggested category' }));
    await waitFor(() => expect(acceptedId).toBe('t2'));

    await userEvent.selectOptions(screen.getByLabelText('Category for review'), 'EQUIPMENT');
    await userEvent.click(screen.getByRole('button', { name: 'Save changed category' }));
    await waitFor(() => {
      expect(screen.getByText(/Saved updated category/i)).toBeInTheDocument();
    });

    // Also test Refresh queue after non-409 SoloLedgerApiError + bulk failure
    await userEvent.selectOptions(screen.getByLabelText('Category for review'), 'SOFTWARE');
    soloApi.reviewTransaction = async () => {
      throw new SoloLedgerApiError(400, {
        code: 'BAD_REVIEW',
        message: 'Invalid category code.',
        requestId: 'req_bad',
        details: {},
        fieldErrors: {},
      });
    };
    await userEvent.click(screen.getByRole('button', { name: 'Accept suggested category' }));
    await waitFor(() => {
      expect(screen.getByText('Invalid category code.')).toBeInTheDocument();
    });
    soloApi.reviewTransaction = async () => {
      throw new Error('Network error');
    };
    await userEvent.click(screen.getByRole('button', { name: 'Accept suggested category' }));
    await waitFor(() => {
      expect(screen.getByText('Failed to save review decision.')).toBeInTheDocument();
    });
    soloApi.bulkReview = async () => {
      throw new Error('Bulk error');
    };
    await userEvent.click(screen.getByRole('button', { name: /Accept all/i }));
    await waitFor(() => {
      expect(screen.getByText('Bulk review failed.')).toBeInTheDocument();
    });
    await userEvent.click(screen.getByRole('button', { name: 'Refresh queue' }));
    view.unmount();

    soloApi.listTransactions = async () => ({ items: [], nextCursor: null, totalCount: 0 });
    renderAt('/review');
    await waitFor(() => {
      expect(screen.getByText('Review queue is clear')).toBeInTheDocument();
    });
  });

  test('/rules empty state, /reports empty + month change, and /engineering loaded evidence JSON', async () => {
    const view1 = renderAt('/rules');
    await waitFor(() => {
      expect(screen.getByText(/No merchant rules saved yet/i)).toBeInTheDocument();
    });
    view1.unmount();

    const view2 = renderAt('/reports');
    await waitFor(() => {
      expect(screen.getByText('No report data in selected range')).toBeInTheDocument();
    });
    view2.unmount();

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async (url: RequestInfo | URL) => {
      const u = String(url);
      if (u.includes('eval-report')) {
        return {
          ok: true,
          json: async () => ({
            datasetSha256: 'abc',
            heldOutRows: 338,
            heldOutFirstPassAccuracy: 0.932,
            heldOutMacroF1: 0.873,
            abstentionRate: 0.22,
            postReviewAccuracy: 1.0,
            secondImportRememberedAccuracy: 1.0,
          }),
        };
      }
      if (u.includes('backend-coverage')) {
        return { ok: true, json: async () => ({ totals: { percent_covered: 94.06 } }) };
      }
      if (u.includes('frontend-coverage')) {
        return { ok: true, json: async () => ({ total: { lines: { pct: 95.1 } } }) };
      }
      return {
        ok: true,
        json: async () => ({
          vus: 50,
          durationSec: 15,
          requestsPerSec: 120,
          totalRequests: 1800,
          failureRatePct: 0,
          p50Ms: 12,
          p95Ms: 28,
          p99Ms: 42,
          classification: 'LOCAL_SMOKE',
        }),
      };
    }) as unknown as typeof fetch;

    try {
      renderAt('/engineering');
      await waitFor(() => {
        expect(screen.getByText('94.06%')).toBeInTheDocument();
      });
      expect(screen.getByText('95.10%')).toBeInTheDocument();
      expect(screen.getByText('93.2%')).toBeInTheDocument();
      expect(screen.getByText('28.0 ms p95')).toBeInTheDocument();
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('covers Dashboard badges, ImportWizard confirm non-API err, Rules non-API err & Transactions First page', async () => {
    soloApi.listImports = async () => ({
      items: [
        {
          jobId: 'j-comp',
          status: 'COMPLETED',
          fileName: 'done.csv',
          fileSha256: '1',
          totalRows: 5,
          processedRows: 5,
          validRows: 5,
          invalidRows: 0,
          needsReviewCount: 0,
          attempts: 1,
          createdAt: '2026-02-01T00:00:00Z',
        },
        {
          jobId: 'j-fail',
          status: 'FAILED',
          fileName: 'fail.csv',
          fileSha256: '2',
          totalRows: 5,
          processedRows: 1,
          validRows: 1,
          invalidRows: 4,
          needsReviewCount: 0,
          attempts: 1,
          createdAt: '2026-02-01T00:00:00Z',
        },
        {
          jobId: 'j-q',
          status: 'QUEUED',
          fileName: 'q.csv',
          fileSha256: '3',
          totalRows: 5,
          processedRows: 0,
          validRows: 0,
          invalidRows: 0,
          needsReviewCount: 0,
          attempts: 0,
          createdAt: '2026-02-01T00:00:00Z',
        },
      ],
      nextCursor: null,
    });
    const dView = renderAt('/dashboard');
    await waitFor(() => {
      expect(screen.getByText('COMPLETED')).toBeInTheDocument();
    });
    expect(screen.getByText('FAILED')).toBeInTheDocument();
    expect(screen.getByText('QUEUED')).toBeInTheDocument();
    dView.unmount();

    soloApi.createImportPreview = async () => ({
      uploadToken: 'tok-ok',
      fileName: 'ok.csv',
      sha256: 'deadbeef1234',
      headers: ['Date', 'Description', 'Amount'],
      previewRows: [],
      suggestedMapping: {
        postedDateColumn: 'Date',
        descriptionColumn: 'Description',
        amountMode: 'SIGNED_AMOUNT',
        dateFormat: '%Y-%m-%d',
        decimalSeparator: '.',
        headerRow: 1,
      },
      expiresAt: '2026-02-10T00:00:00Z',
    });
    soloApi.createImport = async () => {
      throw new Error('Network fail confirm');
    };
    const wView = renderAt('/imports/new');
    await userEvent.upload(
      screen.getByTestId('csv-file-input'),
      new File(['Date,Description,Amount\n2026-02-01,A,-1.00'], 'ok.csv', { type: 'text/csv' }),
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'Continue to confirm' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Continue to confirm' }));
    await userEvent.click(screen.getByTestId('confirm-import-btn'));
    await waitFor(() => expect(screen.getByText('Failed to start import job.')).toBeInTheDocument());
    wView.unmount();

    soloApi.listMerchantRules = async () => ({
      items: [
        {
          id: 'r1',
          merchantKey: 'M',
          categoryCode: 'SOFTWARE',
          categoryName: 'Software & Cloud',
          priority: 100,
          active: true,
          approvedAt: '2026-02-01T00:00:00Z',
          version: 1,
        },
      ],
      nextCursor: null,
    });
    soloApi.patchMerchantRule = async () => {
      throw new Error('Rule net err');
    };
    const rView = renderAt('/rules');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit rule' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Edit rule' }));
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '' } });
    await userEvent.click(screen.getByRole('button', { name: 'Save rule' }));
    await waitFor(() => expect(screen.getByText('Failed to update rule.')).toBeInTheDocument());
    rView.unmount();

    soloApi.listTransactions = async () => ({
      items: [],
      nextCursor: 'next_cur_1',
      totalCount: 2,
    });
    const txView = renderAt('/transactions');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next page' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'First page' })).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'First page' }));
    txView.unmount();

    // ImportDetailPage CANCELED state & non-API cancel error
    soloApi.getImportDetail = async () => ({
      jobId: 'job-canc',
      status: 'CANCELED',
      fileName: 'canc.csv',
      fileSha256: 'ddd',
      totalRows: 0,
      processedRows: 0,
      validRows: 0,
      invalidRows: 0,
      needsReviewCount: 0,
      attempts: 1,
      phaseLabel: 'Canceled',
      errorCode: null,
      errorMessage: null,
      canRetry: false,
      canCancel: true,
      startedAt: null,
      finishedAt: '2026-02-01T00:00:05Z',
      createdAt: '2026-02-01T00:00:00Z',
      errors: [],
    });
    soloApi.cancelImport = async () => {
      throw new Error('Cancel boom');
    };
    const cancView = renderAt('/imports/job-canc');
    await waitFor(() => expect(screen.getByText('CANCELED')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Cancel job' }));
    await waitFor(() => expect(screen.getByText('Cancel failed.')).toBeInTheDocument());
    cancView.unmount();
  });
});
