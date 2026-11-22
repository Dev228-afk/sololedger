import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { DashboardPage } from './routes/DashboardPage.js';
import { ImportWizardPage } from './routes/ImportWizardPage.js';
import { ImportDetailPage } from './routes/ImportDetailPage.js';
import { TransactionsPage } from './routes/TransactionsPage.js';
import { ReviewQueuePage } from './routes/ReviewQueuePage.js';
import { RulesPage } from './routes/RulesPage.js';

const ReportsPage = lazy(() =>
  import('./routes/ReportsPage.js').then((m) => ({ default: m.ReportsPage })),
);
const EngineeringPage = lazy(() =>
  import('./routes/EngineeringPage.js').then((m) => ({ default: m.EngineeringPage })),
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: false,
    },
  },
});

export function AppRoutes() {
  return (
    <Suspense
      fallback={
        <div style={{ padding: '32px', color: 'var(--muted)' }}>Loading workspace view...</div>
      }
    >
      <Routes>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/imports/new" element={<ImportWizardPage />} />
        <Route path="/imports/:id" element={<ImportDetailPage />} />
        <Route path="/transactions" element={<TransactionsPage />} />
        <Route path="/review" element={<ReviewQueuePage />} />
        <Route path="/rules" element={<RulesPage />} />
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/engineering" element={<EngineeringPage />} />
      </Routes>
    </Suspense>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

