import {
  formatCentsToDecimalString,
  formatDisplayUsd,
  parseDecimalToCents,
  sumDecimalStrings,
} from '../api/money.js';
import {
  getCsrfToken,
  setCsrfToken,
  soloApi,
  SoloLedgerApiError,
} from '../api/client.js';

describe('Exact BigInt money helpers', () => {
  test('parses, sums, and formats signed decimal strings without float drift', () => {
    expect(parseDecimalToCents('-42.85')).toBe(-4285n);
    expect(parseDecimalToCents('+1500.5')).toBe(150050n);
    expect(parseDecimalToCents('.25')).toBe(25n);
    expect(formatCentsToDecimalString(-4285n)).toBe('-42.85');
    expect(formatCentsToDecimalString(5n)).toBe('0.05');
    expect(formatDisplayUsd('-50.00')).toBe('-$50.00');
    expect(formatDisplayUsd('80.00', true)).toBe('+$80.00');
    expect(formatDisplayUsd('80.00', false)).toBe('$80.00');
    expect(sumDecimalStrings(['0.10', '0.20', '-0.30', '-50.00'])).toBe('-50.00');
  });
});

describe('SoloLedger typed API client', () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    setCsrfToken('');
  });

  function mockJsonResponse(body: unknown, status = 200, extraHeaders: Record<string, string> = {}) {
    globalThis.fetch = (async () => ({
      ok: status >= 200 && status < 300,
      status,
      headers: new Headers({ 'content-type': 'application/json', ...extraHeaders }),
      json: async () => body,
    })) as unknown as typeof fetch;
  }

  test('attaches CSRF token and parses API envelopes + errors cleanly', async () => {
    mockJsonResponse({ account: { id: 'a1', displayName: 'Studio', timezone: 'UTC' }, csrfToken: 'csrf_1' });
    const session = await soloApi.getDemoSession();
    expect(session.csrfToken).toBe('csrf_1');
    expect(getCsrfToken()).toBe('csrf_1');

    mockJsonResponse({ status: 'ok', version: '0.1.0', dependencies: { postgres: 'ok' } });
    const health = await soloApi.getHealth();
    expect(health.status).toBe('ok');

    mockJsonResponse({ items: [] });
    await soloApi.listDemoAccounts();
    await soloApi.listCategories();

    let capturedHeaders: Headers | undefined;
    globalThis.fetch = (async (_url: RequestInfo | URL, init?: RequestInit) => {
      capturedHeaders = new Headers(init?.headers);
      return {
        ok: false,
        status: 409,
        headers: new Headers({ 'x-request-id': 'req_1' }),
        json: async () => ({
          error: {
            code: 'VERSION_CONFLICT',
            message: 'Stale version',
            requestId: 'req_1',
            details: { currentVersion: 2 },
            fieldErrors: {},
          },
        }),
      };
    }) as unknown as typeof fetch;

    await expect(
      soloApi.reviewTransaction('tx1', { version: 1, decision: 'ACCEPT' }),
    ).rejects.toMatchObject({
      status: 409,
      code: 'VERSION_CONFLICT',
    });
    expect(capturedHeaders?.get('x-csrf-token')).toBe('csrf_1');

    // Non-JSON error response fallback
    globalThis.fetch = (async () => ({
      ok: false,
      status: 502,
      headers: new Headers({ 'x-request-id': 'req_bad' }),
      json: async () => {
        throw new SyntaxError('Unexpected token');
      },
    })) as unknown as typeof fetch;

    await expect(soloApi.listImports()).rejects.toBeInstanceOf(SoloLedgerApiError);

    // JSON object without error key fallback
    globalThis.fetch = (async () => ({
      ok: false,
      status: 500,
      headers: new Headers(),
      json: async () => ({ detail: 'unstructured' }),
    })) as unknown as typeof fetch;

    await expect(soloApi.listImports()).rejects.toMatchObject({
      status: 500,
      code: 'HTTP_500',
    });
  });

  test('covers remaining client methods and buildCsvExportUrl', async () => {
    setCsrfToken('csrf_abc');
    mockJsonResponse({ account: null, csrfToken: 'csrf_new' });
    await soloApi.switchDemoSession('acc_2');
    expect(getCsrfToken()).toBe('csrf_new');

    const file = new File(['Date,Description,Amount\n2026-02-01,X,-1.00\n'], 'x.csv', {
      type: 'text/csv',
    });
    mockJsonResponse({ uploadToken: 'u1' }, 201);
    await soloApi.createImportPreview(file);

    mockJsonResponse({ jobId: 'j1', status: 'QUEUED' }, 202);
    await soloApi.createImport(
      {
        uploadToken: 'u1',
        mapping: {
          postedDateColumn: 'Date',
          descriptionColumn: 'Description',
          amountMode: 'SIGNED_AMOUNT',
          dateFormat: '%Y-%m-%d',
          decimalSeparator: '.',
          headerRow: 1,
        },
      },
      'idem_1',
    );
    await soloApi.retryImport('j1', 'idem_2');
    await soloApi.cancelImport('j1', 'stop');

    mockJsonResponse({ items: [], nextCursor: null, totalCount: 0 });
    await soloApi.listImports();
    await soloApi.listImports('c1', 10);
    await soloApi.getImportDetail('j1');
    await soloApi.listTransactions({});
    await soloApi.listTransactions({
      cursor: 'c',
      limit: 20,
      category: 'SOFTWARE',
      reviewStatus: 'APPROVED',
      from: '2026-01-01',
      to: '2026-02-01',
      q: 'demo',
    });
    await soloApi.bulkReview([{ transactionId: 't1', version: 1, decision: 'ACCEPT' }]);
    await soloApi.listMerchantRules();
    await soloApi.listMerchantRules('10', 25);
    await soloApi.patchMerchantRule('r1', { version: 1, active: false });
    await soloApi.getMonthlyReport({});
    await soloApi.getMonthlyReport({ fromMonth: '2026-01', toMonth: '2026-02', currency: 'USD' });
    setCsrfToken(null);
    expect(getCsrfToken()).toBe('');

    expect(soloApi.buildCsvExportUrl({})).toBe('/api/v1/exports/ledger.csv');
    expect(
      soloApi.buildCsvExportUrl({
        from: '2026-01-01',
        to: '2026-02-01',
        category: 'SOFTWARE',
        reviewStatus: 'APPROVED',
        q: 'demo',
      }),
    ).toContain('category=SOFTWARE');
  });
});

