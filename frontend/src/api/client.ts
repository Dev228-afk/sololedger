import type { components } from './schema.d.ts';

export type AccountDto = components['schemas']['ApiAccount'];
export type DemoSessionDto = components['schemas']['DemoSessionResponse'];
export type CategoryDto = components['schemas']['ApiCategory'];
export type MappingConfigDto = components['schemas']['MappingConfig'];
export type ImportPreviewDto = components['schemas']['ImportPreviewResponse'];
export type ImportAcceptedDto = components['schemas']['ImportAcceptedResponse'];
export type ImportSummaryDto = components['schemas']['ApiImportSummary'];
export type ImportDetailDto = components['schemas']['ImportDetailResponse'];
export type TransactionDto = components['schemas']['ApiTransaction'];
export type TransactionsListDto = components['schemas']['TransactionsListResponse'];
export type MerchantRuleDto = components['schemas']['ApiMerchantRule'];
export type MonthlyReportDto = components['schemas']['MonthlyReportResponse'];
export type HealthDto = components['schemas']['HealthResponse'];

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    requestId: string;
    details: Record<string, unknown>;
    fieldErrors: Record<string, string[]>;
  };
}

export class SoloLedgerApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;
  readonly details: Record<string, unknown>;
  readonly fieldErrors: Record<string, string[]>;

  constructor(status: number, envelope: ApiErrorEnvelope['error']) {
    super(envelope.message);
    this.status = status;
    this.code = envelope.code;
    this.requestId = envelope.requestId;
    this.details = envelope.details ?? {};
    this.fieldErrors = envelope.fieldErrors ?? {};
  }
}

let inMemoryCsrfToken = '';

export function setCsrfToken(token: string | null | undefined): void {
  inMemoryCsrfToken = token ?? '';
}

export function getCsrfToken(): string {
  return inMemoryCsrfToken;
}

async function requestJson<T>(
  path: string,
  init: RequestInit & { skipCsrf?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (!init.skipCsrf && inMemoryCsrfToken) {
    headers.set('x-csrf-token', inMemoryCsrfToken);
  }
  if (!(init.body instanceof FormData) && init.body !== undefined && !headers.has('content-type')) {
    headers.set('content-type', 'application/json');
  }

  const res = await fetch(path, {
    ...init,
    credentials: 'include',
    headers,
  });

  if (!res.ok) {
    let errBody: ApiErrorEnvelope['error'] = {
      code: `HTTP_${res.status}`,
      message: `Request failed with HTTP ${res.status}.`,
      requestId: res.headers.get('x-request-id') ?? 'unknown',
      details: {},
      fieldErrors: {},
    };
    try {
      const parsed = (await res.json()) as Partial<ApiErrorEnvelope>;
      if (parsed.error) {
        errBody = parsed.error;
      }
    } catch {
      // keep default error body
    }
    throw new SoloLedgerApiError(res.status, errBody);
  }

  return (await res.json()) as T;
}

export const soloApi = {
  getHealth(signal?: AbortSignal) {
    return requestJson<HealthDto>('/api/v1/health', { skipCsrf: true, signal });
  },
  listDemoAccounts(signal?: AbortSignal) {
    return requestJson<{ items: AccountDto[] }>('/api/v1/demo/accounts', {
      skipCsrf: true,
      signal,
    });
  },
  async getDemoSession(signal?: AbortSignal) {
    const data = await requestJson<DemoSessionDto>('/api/v1/demo/session', {
      skipCsrf: true,
      signal,
    });
    if (data.csrfToken) setCsrfToken(data.csrfToken);
    return data;
  },
  async switchDemoSession(accountId: string) {
    const data = await requestJson<DemoSessionDto>('/api/v1/demo/session', {
      method: 'POST',
      skipCsrf: true,
      body: JSON.stringify({ accountId }),
    });
    setCsrfToken(data.csrfToken);
    return data;
  },
  listCategories(signal?: AbortSignal) {
    return requestJson<{ items: CategoryDto[] }>('/api/v1/categories', { signal });
  },
  createImportPreview(file: File, signal?: AbortSignal) {
    const form = new FormData();
    form.append('file', file);
    return requestJson<ImportPreviewDto>('/api/v1/import-previews', {
      method: 'POST',
      body: form,
      signal,
    });
  },
  createImport(
    payload: { uploadToken: string; mapping: MappingConfigDto },
    idempotencyKey: string,
  ) {
    return requestJson<ImportAcceptedDto>('/api/v1/imports', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(payload),
    });
  },
  listImports(cursor?: string, limit = 20, signal?: AbortSignal) {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (cursor) qs.set('cursor', cursor);
    return requestJson<{ items: ImportSummaryDto[]; nextCursor: string | null }>(
      `/api/v1/imports?${qs.toString()}`,
      { signal },
    );
  },
  getImportDetail(jobId: string, signal?: AbortSignal) {
    return requestJson<ImportDetailDto>(`/api/v1/imports/${jobId}`, { signal });
  },
  retryImport(jobId: string, idempotencyKey: string) {
    return requestJson<ImportAcceptedDto>(`/api/v1/imports/${jobId}/retry`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({}),
    });
  },
  cancelImport(jobId: string, reason?: string) {
    return requestJson<ImportAcceptedDto>(`/api/v1/imports/${jobId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },
  listTransactions(
    params: {
      cursor?: string;
      limit?: number;
      category?: string;
      reviewStatus?: string;
      from?: string;
      to?: string;
      q?: string;
    },
    signal?: AbortSignal,
  ) {
    const qs = new URLSearchParams();
    qs.set('limit', String(params.limit ?? 50));
    if (params.cursor) qs.set('cursor', params.cursor);
    if (params.category) qs.set('category', params.category);
    if (params.reviewStatus) qs.set('reviewStatus', params.reviewStatus);
    if (params.from) qs.set('from', params.from);
    if (params.to) qs.set('to', params.to);
    if (params.q) qs.set('q', params.q);
    return requestJson<TransactionsListDto>(`/api/v1/transactions?${qs.toString()}`, {
      signal,
    });
  },
  reviewTransaction(
    id: string,
    payload: {
      version: number;
      decision: 'ACCEPT' | 'CHANGE';
      categoryCode?: string;
      rememberMerchant?: boolean;
    },
  ) {
    return requestJson<components['schemas']['TransactionReviewResponse']>(
      `/api/v1/transactions/${id}/review`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      },
    );
  },
  bulkReview(
    items: Array<{
      transactionId: string;
      version: number;
      decision: 'ACCEPT' | 'CHANGE';
      categoryCode?: string;
      rememberMerchant?: boolean;
    }>,
  ) {
    return requestJson<components['schemas']['BulkReviewResponse']>(
      '/api/v1/reviews/bulk',
      {
        method: 'POST',
        body: JSON.stringify({ items }),
      },
    );
  },
  listMerchantRules(cursor?: string, limit = 50, signal?: AbortSignal) {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (cursor) qs.set('cursor', cursor);
    return requestJson<components['schemas']['MerchantRulesListResponse']>(
      `/api/v1/merchant-rules?${qs.toString()}`,
      { signal },
    );
  },
  patchMerchantRule(
    id: string,
    payload: { version: number; categoryCode?: string; active?: boolean; priority?: number },
  ) {
    return requestJson<components['schemas']['MerchantRulePatchResponse']>(
      `/api/v1/merchant-rules/${id}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      },
    );
  },
  getMonthlyReport(
    params: { fromMonth?: string; toMonth?: string; currency?: string },
    signal?: AbortSignal,
  ) {
    const qs = new URLSearchParams({ currency: params.currency ?? 'USD' });
    if (params.fromMonth) qs.set('fromMonth', params.fromMonth);
    if (params.toMonth) qs.set('toMonth', params.toMonth);
    return requestJson<MonthlyReportDto>(`/api/v1/reports/monthly?${qs.toString()}`, {
      signal,
    });
  },
  buildCsvExportUrl(params: {
    from?: string;
    to?: string;
    category?: string;
    reviewStatus?: string;
    q?: string;
  }) {
    const qs = new URLSearchParams();
    if (params.from) qs.set('from', params.from);
    if (params.to) qs.set('to', params.to);
    if (params.category) qs.set('category', params.category);
    if (params.reviewStatus) qs.set('reviewStatus', params.reviewStatus);
    if (params.q) qs.set('q', params.q);
    const tail = qs.toString();
    return tail ? `/api/v1/exports/ledger.csv?${tail}` : '/api/v1/exports/ledger.csv';
  },
};

