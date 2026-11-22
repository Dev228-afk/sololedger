from django.urls import path
from drf_spectacular.views import SpectacularAPIView

from apps.accounts.views import DemoAccountsListView, DemoSessionView, HealthView
from apps.categorization.views import (
    CategoriesListView,
    MerchantRuleDetailView,
    MerchantRulesListView,
)
from apps.imports.views import (
    ImportCancelView,
    ImportDetailView,
    ImportPreviewCreateView,
    ImportRetryView,
    ImportsCollectionView,
)
from apps.reports.views import LedgerCsvExportView, MonthlyReportView
from apps.transactions.views import (
    BulkReviewView,
    TransactionReviewView,
    TransactionsListView,
)

urlpatterns = [
    path("api/v1/health", HealthView.as_view(), name="health"),
    path("api/v1/schema", SpectacularAPIView.as_view(), name="openapi-schema"),
    path("api/v1/demo/accounts", DemoAccountsListView.as_view(), name="demo-accounts"),
    path("api/v1/demo/session", DemoSessionView.as_view(), name="demo-session"),
    path("api/v1/categories", CategoriesListView.as_view(), name="categories-list"),
    path("api/v1/import-previews", ImportPreviewCreateView.as_view(), name="import-previews"),
    path("api/v1/imports", ImportsCollectionView.as_view(), name="imports-collection"),
    path("api/v1/imports/<str:job_id>", ImportDetailView.as_view(), name="import-detail"),
    path("api/v1/imports/<str:job_id>/retry", ImportRetryView.as_view(), name="import-retry"),
    path("api/v1/imports/<str:job_id>/cancel", ImportCancelView.as_view(), name="import-cancel"),
    path("api/v1/transactions", TransactionsListView.as_view(), name="transactions-list"),
    path("api/v1/transactions/<str:transaction_id>/review", TransactionReviewView.as_view(), name="transaction-review"),
    path("api/v1/reviews/bulk", BulkReviewView.as_view(), name="reviews-bulk"),
    path("api/v1/merchant-rules", MerchantRulesListView.as_view(), name="merchant-rules-list"),
    path("api/v1/merchant-rules/<str:rule_id>", MerchantRuleDetailView.as_view(), name="merchant-rule-detail"),
    path("api/v1/reports/monthly", MonthlyReportView.as_view(), name="reports-monthly"),
    path("api/v1/exports/ledger.csv", LedgerCsvExportView.as_view(), name="exports-ledger-csv"),
]

