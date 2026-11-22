import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { soloApi, type MappingConfigDto } from './client.js';

export const slKeys = {
  demoAccounts: () => ['demoAccounts'] as const,
  demoSession: () => ['demoSession'] as const,
  categories: () => ['categories'] as const,
  health: () => ['health'] as const,
  imports: (accountId: string, cursor?: string) =>
    ['imports', accountId, cursor ?? 'first'] as const,
  importDetail: (accountId: string, jobId: string) =>
    ['importDetail', accountId, jobId] as const,
  transactions: (accountId: string, filterKey: string) =>
    ['transactions', accountId, filterKey] as const,
  reviewQueue: (accountId: string) => ['reviewQueue', accountId] as const,
  merchantRules: (accountId: string) => ['merchantRules', accountId] as const,
  monthlyReport: (accountId: string, fromMonth?: string, toMonth?: string) =>
    ['monthlyReport', accountId, fromMonth ?? '', toMonth ?? ''] as const,
};

export function useDemoAccounts() {
  return useQuery({
    queryKey: slKeys.demoAccounts(),
    queryFn: ({ signal }) => soloApi.listDemoAccounts(signal),
    staleTime: 60_000,
  });
}

export function useDemoSession() {
  return useQuery({
    queryKey: slKeys.demoSession(),
    queryFn: ({ signal }) => soloApi.getDemoSession(signal),
    staleTime: 60_000,
    retry: false,
  });
}

export function useSwitchDemoAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (accountId: string) => soloApi.switchDemoSession(accountId),
    onSuccess: (session) => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'demoSession' });
      qc.setQueryData(slKeys.demoSession(), session);
    },
  });
}

export function useCategories() {
  return useQuery({
    queryKey: slKeys.categories(),
    queryFn: ({ signal }) => soloApi.listCategories(signal),
    staleTime: 300_000,
  });
}

export function useImports(accountId: string | undefined, cursor?: string) {
  return useQuery({
    queryKey: slKeys.imports(accountId ?? 'anon', cursor),
    queryFn: ({ signal }) => soloApi.listImports(cursor, 20, signal),
    enabled: Boolean(accountId),
  });
}

const ACTIVE_IMPORT_STATES = new Set(['QUEUED', 'VALIDATING', 'PROCESSING']);

export function useImportDetail(accountId: string | undefined, jobId: string | undefined) {
  const qc = useQueryClient();
  const pollCountRef = useRef(0);
  const prevStatusRef = useRef<string | undefined>(undefined);

  const query = useQuery({
    queryKey: slKeys.importDetail(accountId ?? 'anon', jobId ?? ''),
    queryFn: ({ signal }) => soloApi.getImportDetail(jobId!, signal),
    enabled: Boolean(accountId && jobId),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (!status || ACTIVE_IMPORT_STATES.has(status)) {
        pollCountRef.current += 1;
        // Back off smoothly: 1s initially -> 2s -> 4s cap
        if (pollCountRef.current <= 3) return 1000;
        if (pollCountRef.current <= 8) return 2000;
        return 4000;
      }
      return false;
    },
  });

  useEffect(() => {
    const status = query.data?.status;
    if (status && status !== prevStatusRef.current) {
      if (!ACTIVE_IMPORT_STATES.has(status) && prevStatusRef.current) {
        void qc.invalidateQueries({ queryKey: ['transactions'] });
        void qc.invalidateQueries({ queryKey: ['reviewQueue'] });
        void qc.invalidateQueries({ queryKey: ['monthlyReport'] });
        void qc.invalidateQueries({ queryKey: ['imports'] });
      }
      prevStatusRef.current = status;
    }
  }, [query.data?.status, qc]);

  return query;
}

export function useCreateImport(accountId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      uploadToken,
      mapping,
      idempotencyKey,
    }: {
      uploadToken: string;
      mapping: MappingConfigDto;
      idempotencyKey: string;
    }) => soloApi.createImport({ uploadToken, mapping }, idempotencyKey),
    onSuccess: async () => {
      if (accountId) {
        await qc.invalidateQueries({ queryKey: ['imports', accountId] });
      }
    },
  });
}

export function useTransactions(
  accountId: string | undefined,
  params: {
    cursor?: string;
    limit?: number;
    category?: string;
    reviewStatus?: string;
    from?: string;
    to?: string;
    q?: string;
  },
) {
  const filterKey = JSON.stringify(params);
  return useQuery({
    queryKey: slKeys.transactions(accountId ?? 'anon', filterKey),
    queryFn: ({ signal }) => soloApi.listTransactions(params, signal),
    enabled: Boolean(accountId),
  });
}

export function useReviewQueue(accountId: string | undefined) {
  return useQuery({
    queryKey: slKeys.reviewQueue(accountId ?? 'anon'),
    queryFn: ({ signal }) =>
      soloApi.listTransactions({ reviewStatus: 'NEEDS_REVIEW', limit: 100 }, signal),
    enabled: Boolean(accountId),
  });
}

export function useReviewTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      version,
      decision,
      categoryCode,
      rememberMerchant,
    }: {
      id: string;
      version: number;
      decision: 'ACCEPT' | 'CHANGE';
      categoryCode?: string;
      rememberMerchant?: boolean;
    }) =>
      soloApi.reviewTransaction(id, {
        version,
        decision,
        categoryCode,
        rememberMerchant,
      }),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['reviewQueue'] }),
        qc.invalidateQueries({ queryKey: ['transactions'] }),
        qc.invalidateQueries({ queryKey: ['monthlyReport'] }),
        qc.invalidateQueries({ queryKey: ['merchantRules'] }),
        qc.invalidateQueries({ queryKey: ['imports'] }),
      ]);
    },
  });
}

export function useBulkReview() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: soloApi.bulkReview,
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['reviewQueue'] }),
        qc.invalidateQueries({ queryKey: ['transactions'] }),
        qc.invalidateQueries({ queryKey: ['monthlyReport'] }),
        qc.invalidateQueries({ queryKey: ['merchantRules'] }),
        qc.invalidateQueries({ queryKey: ['imports'] }),
      ]);
    },
  });
}

export function useMerchantRules(accountId: string | undefined) {
  return useQuery({
    queryKey: slKeys.merchantRules(accountId ?? 'anon'),
    queryFn: ({ signal }) => soloApi.listMerchantRules(undefined, 100, signal),
    enabled: Boolean(accountId),
  });
}

export function usePatchMerchantRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      version,
      categoryCode,
      active,
      priority,
    }: {
      id: string;
      version: number;
      categoryCode?: string;
      active?: boolean;
      priority?: number;
    }) => soloApi.patchMerchantRule(id, { version, categoryCode, active, priority }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['merchantRules'] });
    },
  });
}

export function useMonthlyReport(
  accountId: string | undefined,
  params: { fromMonth?: string; toMonth?: string; currency?: string },
) {
  return useQuery({
    queryKey: slKeys.monthlyReport(
      accountId ?? 'anon',
      params.fromMonth,
      params.toMonth,
    ),
    queryFn: ({ signal }) => soloApi.getMonthlyReport(params, signal),
    enabled: Boolean(accountId),
  });
}

