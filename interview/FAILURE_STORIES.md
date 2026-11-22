# SoloLedger — Debug, Reliability & Production Failure Stories (`FS-SOL-*`)

Each entry documents a real issue caught during build/QA (`FS-SOL-01` through `FS-SOL-05`) or an implemented & tested failure-mode scenario (`FS-SOL-06` through `FS-SOL-16`) with root cause, fix, code path, and regression test/verification.

---

## `FS-SOL-01` — Waitress WSGI Jobs Stuck Forever in `QUEUED` Due to Missing `config/__init__.py`
- **Symptom**: During initial live browser Playwright QA, uploading `smoke_5rows.csv` returned `202 Accepted` (`status: QUEUED`), Celery worker sat idle polling `sololedger` Redis queue, and `/imports/:id` polled until timeout without transitioning.
- **Root Cause**: Django `config/wsgi.py` imported Django settings without importing `config/celery.py`. Without `backend/config/__init__.py` exporting `from .celery import app as celery_app`, `@shared_task` (`tasks/import_tasks.py:process_import_job`) inside Waitress bound to Celery's default AMQP localhost fallback rather than `CELERY_BROKER_URL = "redis://127.0.0.1:6382/0"`. Pytest EAGER/direct invocation masked it because Pytest never started separate WSGI + worker OS processes.
- **Fix**: Created `backend/config/__init__.py` exporting `celery_app`.
- **Prevention & Proof**: Live multi-process Playwright QA (`scripts/run_live_qa.py`) starting real Waitress WSGI (`:8100`) + real Celery `--pool=threads` (`:6382`) passed `1 passed (17.1s)`, completing the 5-row smoke job cleanly (`evidence/imports/vertical-slice.json`).

## `FS-SOL-02` — Keyset Pagination `400 INVALID_CURSOR` on `+00:00` UTC Timestamps
- **Symptom**: Fetching page 2 of `GET /api/v1/imports?cursor=2026-11-22T03:00:00+00:00|uuid` returned HTTP `400 INVALID_CURSOR`.
- **Root Cause**: Unencoded `+` inside query parameter strings is decoded as an ASCII space (`" "`) by standard form/URL query parsers (`2026-11-22T03:00:00 00:00`), breaking `datetime.fromisoformat(ts_str)` in `ImportsCollectionView.get`.
- **Fix**: Updated `ImportsCollectionView.get` (`apps/imports/views.py`) to encode cursors as padding-stripped `base64.urlsafe_b64encode` and decode defensively with padding restoration.
- **Prevention & Proof**: Covered by cursor pagination test in `backend/tests/test_imports_and_worker.py` + `test_endpoints_and_errors.py`.

## `FS-SOL-03` — 4 KB Windows `subprocess.PIPE` Deadlock During 50 -> 150 VU Locust Stress
- **Symptom**: During initial live load-plus-E2E verification, Locust `50`-VU smoke finished (`836` reqs), then `150`-VU recorded `0` requests (`locust_local_150vu_stats.csv` 0 reqs) and Playwright timed out on `"Uploading preview..."` because Waitress (`:8100`) stopped accepting requests entirely.
- **Root Cause**: `scripts/run_live_qa.py` spawned `waitress-serve`, `celery`, and `vite` with `stdout=subprocess.PIPE, stderr=subprocess.STDOUT` with no reader thread draining the pipes. As soon as Waitress emitted queue-depth logs exceeding Windows' 4 KB OS pipe buffer, synchronous stderr writes deadlocked Waitress, while `--connection-limit=1000` also exceeded Windows CPython `select()` `FD_SETSIZE = 512`.
- **Fix**: Redirected child stdout/stderr to temporary disk log files (`log_dir / "waitress.log"`, `celery.log`, `vite.log`), lowered Waitress `--connection-limit=450` (under 512), and added `wait_ready(..., "Django Waitress API (pre-150VU)")` and non-zero request assertions.
- **Prevention & Proof**: Re-running `scripts/run_live_qa.py` passed completely (`50` VU `1472` reqs `0` failures; `150` VU `1993` reqs `0` failures; Playwright `1 passed (17.1s)`).

## `FS-SOL-04` — Axe WCAG 2.2 AA Failures (`role="tablist"` Misuse, `4.46:1` Badge Contrast, Nested Interactive Elements)
- **Symptom**: Automated `@axe-core/playwright` scan caught ARIA violations on `/imports/new`, contrast `< 4.5:1` (`4.46:1`) on spruce green status badges, and nested interactive `<Button>` elements inside React Router `<Link>` wrappers.
- **Root Cause**: Progress step pills used `role="tablist"` without `role="tab"` children; light green status text (`#147d5c` on `#e5f3ed`) measured slightly short of 4.5:1 AA normal-text ratio; and action links wrapped `<Button>` inside `<Link>` (`<a>` wrapping `<button>` violates HTML5 content model & screen-reader focus semantics).
- **Fix**: Switched step indicator in `ImportWizardPage.tsx` to semantic `<ol aria-label="Import steps">` with `aria-current="step"`; darkened green badge foreground token to `--accent-hover` (`#105443`); and introduced `.sl-btn-link` CSS classes on `<Link>`/`<a>` navigation triggers across 5 routes.
- **Prevention & Proof**: Zero WCAG 2.2 AA violations across all 8 routes & 3 viewports (`1440`, `1024`, `390`) in `frontend/e2e/sololedger.spec.ts`.

## `FS-SOL-05` — Raw Markdown Backticks Leaked Into Review & Engineering Screen Copy
- **Symptom**: Visual screenshot review caught literal `` ` `` backtick characters inside JSX labels (`MOCK_LOW_CONFIDENCE_ABSTAIN`, normalized merchant strings, file paths).
- **Root Cause**: Markdown prose habits carried directly into JSX text nodes instead of HTML `<code>` elements on `ReviewQueuePage.tsx` and `EngineeringPage.tsx`.
- **Fix**: Audited review and engineering copy rendered across live captures (`03-review-queue-1440.png`, `08-engineering-1440.png`) and replaced literal backtick spans with semantic `<code>` elements, re-running Jest (`22/22`), `vite build`, and live screenshots.

## `FS-SOL-06` — Broker Outage Between `transaction.atomic()` Commit and Celery `.delay()`
- **Failure Scenario**: PostgreSQL commits `ImportJob(QUEUED)`, then Redis is unreachable inside `transaction.on_commit(lambda: dispatch_import_job(job_id))`.
- **Handling**: `dispatch_import_job` catches broker errors, returns `False`, and leaves `enqueued_at=None` without rolling back or failing the client's `202` upload. Periodic task `recover_stranded_imports` (`tasks/import_tasks.py`) scans `QUEUED` jobs with `enqueued_at IS NULL` older than `min_age_seconds` and re-dispatches them once Redis returns.
- **Verified By**: `backend/tests/test_imports_and_worker.py` (stranded job dispatch & recovery test).

## `FS-SOL-07` — Mid-Batch Worker Crash + Celery `acks_late` Redelivery
- **Failure Scenario**: A worker processes rows `1..100` of a `250`-row statement, commits batch 1, and crashes (`SIGKILL` / `RuntimeError`) before acking Redis. Celery redelivers the task to another worker.
- **Handling**: `process_import_job` runs with `acks_late=True` and `CELERY_TASK_REJECT_ON_WORKER_LOST=True`. On retry, `ImportRow.objects.get_or_create(import_job=job, source_line_no=...)` and `Transaction.objects.get_or_create(account_id=job.account_id, import_row=...)` skip already persisted rows without duplicating debits or classifications.
- **Verified By**: `process_import_job(..., _fail_after_batch=1)` simulated crash-and-retry test in `backend/tests/test_imports_and_worker.py`.

## `FS-SOL-08` — Duplicate Statement Upload vs. Legitimate Same-Day Identical Charges
- **Failure Scenario**: (A) User uploads the exact same `smoke_5rows.csv` file bytes again; (B) User uploads two *different* statements or rows where a coffee shop was legitimately visited twice on the same day for `$5.00`.
- **Handling**: Case A computes SHA-256 (`file_sha256`) during preview and rejects re-import of non-FAILED/CANCELED jobs with HTTP `409 DUPLICATE_IMPORT`. Case B keeps both distinct `ImportRow` lines in PostgreSQL (`(import_job, source_line_no)`); cross-import matches flag `duplicate_candidate=True` + `NEEDS_REVIEW` (`_detect_cross_import_duplicate`) so the user decides whether to approve or adjust rather than silently dropping real spend.
- **Verified By**: `backend/tests/test_imports_and_worker.py` and `test_review_reports_and_isolation.py`.

## `FS-SOL-09` — Concurrent Tab Stale Review Write (`409 VERSION_CONFLICT`)
- **Failure Scenario**: Tab A opens `NORTHWOOD MART #402` (`version: 1`). Tab B reviews it first (`version: 1 -> 2`). Tab A clicks Approve sending stale `version: 1`.
- **Handling**: `apply_single_review` locks the row with `select_for_update()` and validates `txn.version != expected_version`, raising HTTP `409 VERSION_CONFLICT` with `currentVersion` and `currentCategoryCode`. `ReviewQueuePage.tsx` catches `409`, renders an alert banner, and lets the user refresh without silently overwriting Tab B's work.
- **Verified By**: `backend/tests/test_review_reports_and_isolation.py`, `evidence/imports/contract-samples.json`, and live Playwright + screenshot `04-review-409-conflict-1440.png`.

## `FS-SOL-10` — CSV Formula / DDE Injection on Export
- **Failure Scenario**: Malicious merchant description in bank CSV reads `=HYPERLINK("http://evil.example","Click")` or `+cmd|'/C calc'!A0`. Exporting raw CSV lets Excel execute formulas when opened by the freelancer's accountant.
- **Handling**: `LedgerCsvExportView` (`apps/reports/views.py`) passes text cells (`description`, `normalized_merchant`, `category.code`) through `sanitize_csv_cell` (`apps/transactions/money.py`), prefixing `'` on leading `=`, `+`, `-`, `@`, `\t`, `\r`, while intentionally *not* escaping the numeric `Signed Amount` column (`"-42.85"` remains numeric).
- **Verified By**: `backend/tests/test_money_and_csv.py` + `evidence/security/isolation-check.json` (`formulaNeutralizedInExport: true`, `numericAmountsPreservedInExport: true`).

## `FS-SOL-11` — Refund Exceeding Expense Category Spend (`netSpend < 0`)
- **Failure Scenario**: Freelancer returns a `$150.00` monitor in February (`EQUIPMENT` `+150.00`) after spending `$100.00` (`EQUIPMENT` `-100.00`), yielding net `-50.00` spend.
- **Handling**: `MonthlyReportView` computes `net_spend_minor = -int(row["sum_minor"] or 0)` without clamping negative numbers to zero (`"-50.00"`), keeping monthly ledger reconciliation algebraically exact (`evidence/imports/contract-samples.json`).
- **Verified By**: `backend/tests/test_review_reports_and_isolation.py`.

## `FS-SOL-12` — Non-USD Rows, Excess Decimal Precision & Malformed UTF-8/BOM CSVs
- **Failure Scenario**: CSV contains `"12.345"` (3 decimals), `"EUR"` row, blank posted date, Windows CRLF line endings, or UTF-8 BOM `\ufeff`.
- **Handling**: `validate_upload_bytes` validates UTF-8 (`csv_parser.py`), `stream_parse_csv` strips BOM and normalizes dialects, while row-level errors (`EXCESS_DECIMAL_PRECISION`, `UNSUPPORTED_CURRENCY`, `INVALID_DATE`, `INVALID_AMOUNT`) quarantine only failing rows into `ImportRow(status="INVALID")` instead of aborting valid rows.
- **Verified By**: `fixtures/import_edge_cases/` + `backend/tests/test_money_and_csv.py`.

## `FS-SOL-13` — Cross-Tenant Session Forgery & ID Enumeration (`401`/`403`/`404`)
- **Failure Scenario**: Attacker passes Demo Account 2's UUID in `/api/v1/imports/:id` or `/api/v1/transactions/:id/review`, tampers with cookie signature, or sends CSRF-less `POST`/`PATCH`.
- **Handling**: `require_account(request, check_csrf=True)` verifies HMAC-SHA256 cookie token (`401 UNAUTHORIZED`), validates `X-CSRFToken` (`403 CSRF_MISMATCH`), and scopes all ORM queries to `account=account`, yielding `404` even when an ID exists for another tenant.
- **Verified By**: `evidence/security/isolation-check.json` (`unauth401Status: 401`, `csrf403Status: 403`, `crossTenantImport404Status: 404`, `crossTenantTransactionCount: 0`).

## `FS-SOL-14` — LLM Provider Exception, Timeout, or Hallucinated Category Code
- **Failure Scenario**: External/custom `CategorizerProvider` raises `TimeoutError` or returns category `"CRYPTO_GAMBLING"` not present in seeded `Category` table.
- **Handling**: `LangChainCategorizerAdapter.classify` wraps `self._provider_chain.invoke(...)` in `try/except`: exceptions degrade safely to `UNCATEGORIZED` + `confidence=None` -> `NEEDS_REVIEW` (`explanation_code="PROVIDER_UNAVAILABLE_FALLBACK"`), while unknown `category_code` outputs are clamped via `if cat not in self.allowed_categories: cat = "UNCATEGORIZED"` and routed through `determine_review_status(suggestion.confidence, ...)` (`NEEDS_REVIEW` when confidence is missing or `< 0.700`). Live mode without approval fails closed with `BLOCKED_EXTERNAL`.
- **Verified By**: `backend/tests/test_classification.py`.

## `FS-SOL-15` — Stale Dashboard / Report Totals Right After Review Approval
- **Failure Scenario**: User approves a `-$31.40` transaction on `/review` and immediately navigates to `/dashboard` or `/reports`, or a polling loop for `/imports/:id` finishes while `/transactions` still caches the old empty list.
- **Handling**: Both `useReviewTransaction` and `useBulkReview` invalidate `['reviewQueue']`, `['transactions']`, `['monthlyReport']`, `['merchantRules']`, and `['imports']`, and `useImportDetail` invalidates those keys cleanly as soon as `status` exits `QUEUED|VALIDATING|PROCESSING` (`frontend/src/api/hooks.ts`).
- **Verified By**: `frontend/src/tests/routesFlow.test.tsx` + live Playwright flow asserting `$163.25` immediately on `/dashboard`.

## `FS-SOL-16` — Cancellation Race Mid-Import
- **Failure Scenario**: User clicks **Cancel import** (`POST /api/v1/imports/:id/cancel`) while Celery worker is between batch 1 and batch 2.
- **Handling**: Cancel endpoint sets `cancel_requested=True`; `process_import_job` calls `job.refresh_from_db()` before each 100-row batch and before final completion transition, honoring `CANCELED` atomically without promoting partially processed batches into `COMPLETED`.
- **Verified By**: `backend/tests/test_endpoints_and_errors.py` & `backend/tests/test_imports_and_worker.py`.

