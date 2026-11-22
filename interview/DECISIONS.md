# SoloLedger — Architecture & Engineering Decisions (`DEC-SOL-*`)

Each Architecture Decision Record documents the choice made in code, rejected alternatives, verified tradeoffs, and exact file locations.

---

## `DEC-SOL-001` — Signed Integer Minor Units (`BigIntegerField` + Python `Decimal` + JS `BigInt`)
- **Context**: Accounting ledgers cannot tolerate IEEE-754 floating-point drift (`0.1 + 0.2 = 0.30000000000000004`) across thousands of debits, refunds, and exports.
- **Decision**: Persist PostgreSQL `amount_minor = models.BigIntegerField()` (`apps/transactions/models.py`), parse/format exclusively via `Decimal` (`apps/transactions/money.py:parse_decimal_to_minor`, `minor_to_decimal_str`), serialize fixed two-decimal strings over JSON (`"-42.85"`, `"1500.00"`), and compute client sums in `BigInt` (`frontend/src/api/money.ts:parseDecimalToCents`, `sumDecimalStrings`). Negative `amount_minor` represents expenses/debits; positive `amount_minor` represents income or expense-category refunds.
- **Rejected Alternatives**: IEEE-754 `float` columns/numbers (rounding drift) or client-side `number` cents (unsafe beyond $2^{53}-1$ and prone to accidental division into floats). `NUMERIC(12,2)` in DB works too, though signed integer cents guarantee exact equality comparisons without scale mismatch.
- **Tradeoff**: Multi-currency scaling (e.g., 0-decimal `JPY` or 3-decimal `BHD`) requires storing a `currency_exponent` per row later; explicitly scoped MVP to `USD` (`currency.upper() != "USD"` returns `UNSUPPORTED_CURRENCY` / `422`).

## `DEC-SOL-002` — Exact SQL Net Spend Derivation Allowing Negative Category Totals
- **Context**: Monthly category spend (`MonthlyReportView`) must stay consistent after transaction edits, approvals, and refunds.
- **Decision**: Derive totals directly in SQL via `Transaction.objects.filter(...).annotate(month_start=TruncMonth("posted_date")).values(...).annotate(sum_minor=Sum("amount_minor"))` (`apps/reports/views.py`), using `net_spend_minor = -int(row["sum_minor"] or 0)`. If an expense category has `$100` spending and a `$150` refund, `netSpend` reports `"-50.00"` honestly rather than clamping at `0.00` (verified in `evidence/imports/contract-samples.json`).
- **Rejected Alternatives**: Cached summary tables incremented during review mutations (drift risk on worker retries or bulk updates) or `max(0, netSpend)` clamping (destroys multi-month accounting conservation).
- **Tradeoff**: Scans indexed `(account_id, posted_date)` rows per report query; fast at personal-business scale (`p50=190 ms` locally at 50 VUs) and trivially cacheable per `(account_id, version_stamp)` later.

## `DEC-SOL-003` — Two-Phase Upload Preview (`ImportUploadPreview`) + Asynchronous `202` Pipeline
- **Context**: Parsing a large CSV, running classification, and validating rows inside a synchronous HTTP POST would tie up WSGI workers, hit proxy timeouts, and fail browser UX for malformed header mapping.
- **Decision**: Stage 1 (`POST /api/v1/import-previews`, `ImportPreviewCreateView`) reads the upload bytes, validates UTF-8/size (`<=10 MB`), computes `file_sha256`, detects headers/mapping via `infer_mapping_and_preview`, writes the object to `SOLOLEDGER_STORAGE_DIR`, and returns a 24-hour `ImportUploadPreview` `uploadToken`. Stage 2 (`POST /api/v1/imports`, `ImportsCollectionView.post`) validates the mapping (`validate_mapping_schema`), rejects active duplicate hashes (`409 DUPLICATE_IMPORT`), creates `ImportJob(QUEUED)`, marks `consumed_at`, schedules `dispatch_import_job` inside `transaction.on_commit`, and returns `202 Accepted` immediately.
- **Rejected Alternatives**: Synchronous `POST /imports` processing or Base64 JSON embedding raw CSV payloads.
- **Tradeoff**: Requires lifecycle cleanup for unconsumed previews (`_cleanup_expired_previews` locally; S3 7-day expiration lifecycle rule in `infra/terraform/aws/main.tf`).

## `DEC-SOL-004` — Enqueue-After-Commit (`transaction.on_commit`) + `recover_stranded_imports` Recovery
- **Context**: Calling `process_import_job.delay(job_id)` inside `transaction.atomic()` lets a fast Celery worker read the DB *before* Postgres commits `ImportJob`, causing `ImportJob matching query does not exist`. Conversely, committing first and failing on Redis leaves jobs stuck in `QUEUED`.
- **Decision**: Persist `ImportJob(status="QUEUED", enqueued_at=None)` atomically, execute `dispatch_import_job(job_id_str)` inside `transaction.on_commit(...)` (`apps/imports/views.py`), stamp `enqueued_at=timezone.now()` only on publish success (`tasks/import_tasks.py`), and schedule periodic Celery Beat `recover_stranded_imports` (`config/settings.py`) to sweep any `QUEUED` jobs where `enqueued_at IS NULL` and `created_at <= cutoff`.
- **Rejected Alternatives**: Transactional outbox table polling via standalone daemon (higher operational complexity; current design achieves the exact same durability guarantee directly on `import_jobs` indexed by `(status, enqueued_at)`).
- **Tradeoff**: During total Redis unavailability, jobs wait up to the `recover_stranded_imports` Beat interval (`30s`) instead of failing the client upload `202` unnecessarily.

## `DEC-SOL-005` — Batched Worker Commits Outside Classification Calls & DB Idempotency Guards
- **Context**: Holding a PostgreSQL transaction open across slow external/LLM calls exhausts DB connections and increases lock contention; meanwhile Celery `acks_late=True` means a crashed worker re-delivers the task.
- **Decision**: `process_import_job` (`tasks/import_tasks.py`) parses all `ImportRow`s with `get_or_create(import_job=job, source_line_no=...)`, closes that write transaction, iterates in `100`-row chunks, skips rows with an existing `Transaction(import_row=...)`, classifies *outside* any DB write transaction, and commits each 100-row batch atomically via `Transaction.objects.get_or_create(account_id=job.account_id, import_row=imp_row, ...)` + `IntegrityError` catch. Terminal states (`AWAITING_REVIEW`, `COMPLETED`, `CANCELED`) return `idempotentSkip: True`.
- **Rejected Alternatives**: Single giant transaction for the entire CSV (loses all progress on crash at row 950/1000) or unguarded `.create()` calls (duplicates rows on redelivery).

## `DEC-SOL-006` — Strict 5-Step Categorization Precedence & `< 0.700` Review Boundary
- **Context**: An LLM or noisy heuristic must never silently overrule explicit bookkeeping decisions from the user or poison reports with guesses.
- **Decision**: `LangChainCategorizerAdapter.classify` (`classification/langchain_adapter.py`) evaluates strictly in order: (1) account-scoped `MerchantCorrection` (`USER_RULE`, confidence `1.000`, `APPROVED`), (2) `EXACT_LEXICON`, (3) `KEYWORD_RULE`, (4) LangChain `RunnableLambda` chain (`_build_sanitized_input | provider.suggest`), and (5) `UNCATEGORIZED` fallback. `determine_review_status` (`classification/confidence.py`) routes `duplicate_candidate=True`, `confidence is None`, and `confidence < Decimal("0.700")` to `NEEDS_REVIEW`, while `>= 0.700` becomes `SUGGESTED` (except `USER_RULE` -> `APPROVED`).
- **Rejected Alternatives**: Allowing high-confidence LLM predictions to supersede prior `MerchantCorrection` rows, or auto-approving `>= 0.700` rules as `APPROVED` without review visibility.
- **Evidence**: Exact boundary tests for `0.699`, `0.700`, `None`, and invalid scores pass in `backend/tests/test_classification.py`.

## `DEC-SOL-007` — Privacy-Minimized `SanitizedSuggestionInput` & Deterministic `MockCategorizerProvider`
- **Context**: Sending raw bank descriptions, account UUIDs, external transaction IDs, or exact dollar amounts to third-party LLM endpoints violates data minimization and creates nondeterministic CI regressions.
- **Decision**: `_build_sanitized_input` strips payload down to `SanitizedSuggestionInput(normalized_merchant, amount_sign, allowed_categories)` (`classification/provider.py`). Local/CI runs use `SOLOLEDGER_LLM_PROVIDER=mock` (`MockCategorizerProvider`), while `SOLOLEDGER_LLM_PROVIDER=live` without explicit spend approval fails closed with `RuntimeError("BLOCKED_EXTERNAL: ...")`.
- **Rejected Alternatives**: Sending raw CSV rows to external models or using mock sleeps/fake LLM latencies.

## `DEC-SOL-008` — Disjoint `merchant_family` Held-Out Split for 12×90 Evaluation
- **Context**: Evaluating categorization rules on random row splits leaks identical merchants across train and test sets, artificially inflating first-pass accuracy.
- **Decision**: `scripts/generate_statements.py` emits 12 statements × 90 rows (`1080` rows, deterministic seed `2026`, ground truth SHA-256 `e85b3b6d...`) tagged with synthetic `merchant_family`. `scripts/score_classifier.py` holds out `13` disjoint `merchant_family` groups (`338` rows) vs `742` dev rows, strictly prohibiting future `MerchantCorrection` leaks into first-pass scoring while measuring second-import rule reuse separately (`75` hits, `100.0%` accuracy).
- **Result**: Reproduced `93.2%` (`315/338`) held-out first-pass accuracy and `0.8729` macro F1 vs `~85%` `HISTORICAL_RESUME_CLAIM` (`evidence/categorization/eval-report.json`).

## `DEC-SOL-009` — Base64url Cursor Encoding on Timestamp-Keyed Import Pagination
- **Context**: Keyset pagination (`-created_at, -id`) avoids expensive PostgreSQL `OFFSET` scans, but raw ISO-8601 UTC timestamps end with `+00:00`. Unescaped `+` in query strings decodes as a space (` `) on HTTP receipt, causing `datetime.fromisoformat()` to raise `400 INVALID_CURSOR`.
- **Decision**: Encode import pagination cursors via `base64.urlsafe_b64encode` without `=` padding (`apps/imports/views.py`), while `TransactionsListView` uses `YYYY-MM-DD|uuid` date keys which contain only URL-safe characters.
- **Rejected Alternatives**: Requiring frontend callers to manually `encodeURIComponent` cursors everywhere or falling back to `OFFSET`.

## `DEC-SOL-010` — Optimistic Locking (`version`) + Pessimistic Row Lock (`select_for_update`) on Review Mutations
- **Context**: Reviewing from two open browser tabs—or racing a bulk review action against a single review—must never silently overwrite another user decision.
- **Decision**: Both `Transaction` and `MerchantCorrection` carry an integer `version` field incremented atomically inside `transaction.atomic()` under `select_for_update()` (`apps/transactions/views.py:apply_single_review`, `apps/categorization/views.py:MerchantRuleDetailView.patch`). Mismatched `expected_version` returns HTTP `409 VERSION_CONFLICT` with `currentVersion` and `currentCategoryCode`, surfacing an explicit reload banner in `ReviewQueuePage.tsx` (verified live in screenshot `04-review-409-conflict-1440.png`).

## `DEC-SOL-011` — OpenAPI (`drf-spectacular`) → TypeScript (`openapi-typescript`) Schema Contract
- **Context**: Hand-maintained API DTOs drift quickly between Python serializers and TypeScript components.
- **Decision**: Declare explicit DRF response/request schemas in `apps/accounts/api_schemas.py`, export `backend/openapi.yaml` (`Warnings: 0`), and generate `frontend/src/api/schema.d.ts` consumed directly by `frontend/src/api/client.ts`.

## `DEC-SOL-012` — Separate Backend & Frontend `>= 91%` Coverage Gates (Never Averaged)
- **Context**: Averaging Python line/statement coverage with TypeScript/JS branch/statement coverage produces a meaningless composite metric that masks gaps in critical paths.
- **Decision**: Enforce `--cov-fail-under=91` in Pytest (`pyproject.toml`, measured **`94.06%`** across `apps`, `classification`, `tasks`) and `>= 91%` thresholds across statements/branches/functions/lines in Jest (`jest.config.mjs`, measured **`96.46%` stmts / `91.24%` branches / `98.26%` funcs / `98.10%` lines**), displaying both side-by-side on `/engineering` (`EngineeringPage.tsx`).

## `DEC-SOL-013` — Windows Development Host Compatibility (Python 3.12.10, Celery `threads`, Waitress `connection-limit=450`)
- **Context**: On the Windows 10 host, Python 3.14 lacked wheels for `psycopg`/`langchain` dependencies, Celery `prefork` fails without `os.fork()`, Waitress `asyncore`/`select` is bounded by `FD_SETSIZE = 512`, and `subprocess.PIPE` deadlocks processes past 4 KB logs.
- **Decision**: Pin Python 3.12.10 (`backend/.venv`), invoke Celery locally with `--pool=threads --concurrency=4`, bound Waitress to `--threads=32 --connection-limit=450`, redirect spawned subprocess logs to files in `scripts/run_live_qa.py`, and document Linux `--pool=prefork` + Gunicorn/ECS for production while labeling local Locust outputs `LOCAL_SINGLE_HOST_BENCHMARK`.

## `DEC-SOL-014` — Declarative Terraform AWS Blueprint Marked `BLOCKED_EXTERNAL`
- **Context**: Provisioning live AWS S3, ECR, ECS Fargate, RDS, or Secrets Manager consumes cloud credits and requires IAM credentials absent in this environment.
- **Decision**: Author reproducible least-privilege Terraform in `infra/terraform/aws/main.tf` (private `sololedger-uploads` bucket with all 4 `block_public_*` guards + 7-day expiration lifecycle, private frontend S3 bucket, ECR, ECS cluster, 7-day CloudWatch log retention, Secrets Manager zero-day recovery for teardown), document budget estimates and teardown in `CLOUD_APPROVAL.md`, and fail closed in `Makefile` (`cloud-plan`) with `BLOCKED_EXTERNAL` until approved.

