# SoloLedger — System Design Workbook (`SD-SOL-*`)

Six production-depth system design prompts grounded in SoloLedger's implemented architecture, showing both current single-region implementation and explicit scaling paths.

---

## `SD-SOL-01` — Asynchronous Financial Statement Ingestion (Scaling from 10 MB Local CSVs to 100 MB+ Multi-Tenant Workloads)
1. **Requirements**: Accept arbitrary bank/card CSV statements, map heterogeneous schemas (`DEBIT`/`CREDIT` vs signed `AMOUNT`, varying date formats), reject exact duplicate uploads safely, isolate per-row format errors without aborting valid rows, guarantee zero lost jobs during queue outages, and prevent API worker starvation at 100 MB+.
2. **Current Implementation (`<= 10 MB`)**:
   - Browser uploads CSV multipart -> `POST /api/v1/import-previews` (`ImportPreviewCreateView`) streams bytes, computes SHA-256, infers headers, stores object under `SOLOLEDGER_STORAGE_DIR`, returns 24h `uploadToken`.
   - Confirm POST (`ImportsCollectionView.post`) enforces `Idempotency-Key`, creates `ImportJob(QUEUED, enqueued_at=None)` + `consumed_at`, schedules `dispatch_import_job` inside `transaction.on_commit`, and returns `202 Accepted`.
   - `process_import_job` streams rows into `ImportRow`, classifies outside open write locks in 100-row atomic chunks, updates `processed_rows`, and `recover_stranded_imports` catches broker outages.
3. **Scaling to 100 MB+ (500k–1M rows)**:
   - Replace Django WSGI upload buffering with **S3 presigned multipart upload** (`PUT` directly browser -> private S3 bucket) + short header-probe `Range: bytes=0-65535` from preview endpoint to auto-detect headers without downloading 100 MB on the API pod.
   - Stream `smart_open` / `boto3` S3 `Body` iterators line-by-line in worker (`chunksize=1000`), use PostgreSQL `COPY` / `bulk_create(ignore_conflicts=True)` into staging table before classification, and shard oversized files into chunk subtasks (`Celery chord`) with shared parent job progress counter (`ATOMIC UPDATE ... processed_rows = processed_rows + delta`).
   - Push progress via SSE/WebSockets backed by Redis Pub/Sub instead of `1s->2s->4s` polling when thousands of users watch concurrently.

---

## `SD-SOL-02` — Human-in-the-Loop Hybrid Categorization Without Data Leakage or Stale Bias
1. **Requirements**: Classify incoming charges into 13 accounting categories, prioritize user authority over AI guesses, prevent low-confidence noise from corrupting tax/spend totals, learn across imports, evaluate truthfully without data leakage, and protect PII from third-party LLM providers.
2. **Design Architecture (`classification/`)**:
   - **Precedence Stack**: `MerchantCorrection` (`USER_RULE`, `1.000`, `APPROVED`) -> `EXACT_LEXICON` -> `KEYWORD_RULE` -> sanitized LangChain runnable -> `UNCATEGORIZED` (`NEEDS_REVIEW`).
   - **Explicit Abstention Threshold (`0.700`)**: Anything `< 0.700`, `None`, or `duplicate_candidate=True` enters `ReviewQueuePage.tsx`. Crucially, user overrides only create future `MerchantCorrection` rules when `rememberMerchant=True` and **never retroactively overwrite previously approved transactions** unless explicitly requested.
   - **Privacy Firewall (`SanitizedSuggestionInput`)**: Strip `account_id`, raw memo dates, store numbers, external transaction IDs, and dollar magnitudes; pass only `(normalized_merchant, amount_sign, allowed_categories)`. Validate structured output against `allowed_categories` whitelist (`if cat not in self.allowed_categories: cat = "UNCATEGORIZED"`).
   - **Leak-Free Evaluation (`scripts/score_classifier.py`)**: Freeze deterministic seed (`2026`), split strictly by **disjoint `merchant_family`** (`13` held-out families / `338` rows vs `742` dev rows) so no store pattern leaks from dev into first-pass evaluation; measure abstention rate (`22.19%`), macro F1 (`0.8729`), and second-import rule transfer (`100.0%` over `75` rule hits) separately.

---

## `SD-SOL-03` — Multi-Tenant Exact-Precision Financial Ledger & Reporting Engine
1. **Requirements**: Zero floating-point penny drift, accurate handling of debits, credits, income, transfers, and full/partial refunds, deterministic historical queries, safe concurrent edits, and spreadsheet-safe CSV exports.
2. **Design Choices**:
   - **Data Model**: `Transaction.amount_minor` (`BigIntegerField`), `Transaction.version` (`IntegerField`), composite indexes `(account, -posted_date, -id)` and `(account, review_status, -posted_date)`, `Category.kind` (`EXPENSE | INCOME | TRANSFER`).
   - **Ledger Invariant (`MonthlyReportView`)**: Never cache mutable report sums; aggregate SQL `TruncMonth("posted_date")` + `Sum("amount_minor")` per query. Expenses have negative `amount_minor`; refunds carry positive `amount_minor` inside `EXPENSE` categories, so `net_spend_minor = -SUM(amount_minor)` reflects refunds naturally (even going negative if refunds exceed charges). Exclude `INCOME` and `TRANSFER` from `netSpend`.
   - **Concurrency Control**: Concurrent `apply_single_review` calls acquire `SELECT ... FOR UPDATE`, verify `txn.version == expected_version`, create immutable `ReviewDecision` + `AuditEvent` (`redacted_detail`), increment `version`, and reconcile `ImportJob.needs_review_count` atomically (`AWAITING_REVIEW -> COMPLETED` when 0 left).
   - **Safe Export (`LedgerCsvExportView`)**: `StreamingHttpResponse` over `qs.iterator(chunk_size=250)` calling `sanitize_csv_cell` on text columns only so numeric amounts (`"-42.85"`) remain math-summable in Excel without executing `=HYPERLINK` payloads.

---

## `SD-SOL-04` — Reaching Production 500 VUs at `< 150 ms` p95 from Single-Host Local Baseline
1. **Observed Single-Host Baseline (`LOCAL_SINGLE_HOST_BENCHMARK`)**:
   - Windows 10 Waitress (32 threads, `connection-limit=450`) + local WSL2 Docker PG 16 hit `133.4 req/s` (`p95=390 ms`, 50 VUs) and `141.6 req/s` (`p95=1200 ms`, 150 VUs) with `0.0%` errors. Saturation comes from single-process CPython GIL + Windows `select` loop + `CONN_MAX_AGE=60` without PgBouncer + synchronous HMAC session DB lookup per request.
2. **Production Architecture to Hit `500 VUs < 150 ms p95` (`TARGET`)**:
   - **API Tier**: 4–8 Linux ECS Fargate tasks (`2 vCPU / 4 GB`), **Gunicorn + `uvicorn`/gevent or multi-worker `gthread`** behind an AWS ALB (eliminates single-GIL ceiling).
   - **DB Pooling & Read Replicas**: Insert **RDS Proxy / PgBouncer** (transaction pooling, `max_client_conn=1000`, `default_pool_size=40`) ahead of Multi-AZ RDS PostgreSQL; route heavy `/api/v1/reports/monthly` read aggregations to a read replica if needed.
   - **Hot Path Eliminations**: Cache demo/user `Account` lookups in Redis (`60s` TTL) instead of hitting `Account.objects.get` every request; eliminate N+1 `Transaction.objects.filter(import_job=row, review_status=NEEDS_REVIEW).count()` inside `ImportsCollectionView.get` by reading the maintained `import_jobs.needs_review_count` column directly; add Redis read-through cache for `/reports/monthly` invalidated/version-bumped on import completion or review mutation.
   - **Isolation**: Run Celery workers (`worker` ECS service) on a separate task definition & DB connection pool from API tasks so heavy CSV imports never starve synchronous `/transactions` or `/reports` requests.

---

## `SD-SOL-05` — Resilient Accounting SPA Architecture (TanStack Query, Optimistic Concurrency UX & Accessibility)
1. **Requirements**: Never lose user triage progress, avoid stuck polling spinners, reconcile cached reports instantly after review, preserve precision in UI calculations, and meet WCAG 2.2 AA across desktop, tablet, and mobile.
2. **Design Architecture (`frontend/src/`)**:
   - **Centralized Keys & Invalidations (`frontend/src/api/hooks.ts`)**: Hierarchical query keys (`slKeys`) scoped by `accountId` ensure switching demo accounts (`useSwitchDemoAccount`) evicts all tenant data immediately (`qc.removeQueries`).
   - **Bounded Exponential Backoff Polling (`useImportDetail`)**: Active states (`QUEUED | VALIDATING | PROCESSING`) poll `1s` (first 3 polls) -> `2s` (next 5) -> `4s` cap, stopping immediately (`false`) upon entering terminal states (`AWAITING_REVIEW | COMPLETED | FAILED | CANCELED`) and invalidating `transactions`, `reviewQueue`, `monthlyReport`, and `imports`.
   - **BigInt UI Precision (`frontend/src/api/money.ts`)**: Render formatted currency strictly via string splitting and `BigInt` integer cents; zero `parseFloat`/`Number` conversions on amounts.
   - **WCAG 2.2 AA & Responsive Grids**: Semantic `<ol>`/`aria-current="step"` wizards, distinct table (`>= 768px`) -> stacked card (`< 768px`) layouts verified at `1440px`, `1024px`, `390px`, 200% zoom, and `prefers-reduced-motion`, plus explicit `409 VERSION_CONFLICT` recovery UI in `ReviewQueuePage.tsx`.

---

## `SD-SOL-06` — Privacy-Preserving Financial Cloud Topology on AWS (`infra/terraform/aws/main.tf`)
1. **Status**: `BLOCKED_EXTERNAL` (`CLOUD_APPROVAL.md`) — Terraform verified statically cleanly; apply withheld pending user credentials and spend authorization (~`$0.06/hr`).
2. **Target AWS Architecture**:
   - **Networking & Edge**: CloudFront OAC -> private S3 frontend bucket (`bucket_prefix = "sololedger-web-<env>-"`, all 4 `block_public_*` enabled); ALB HTTPS -> private ECS Fargate subnets (`sololedger-<env>-cluster`, `sololedger-<env>-backend` ECR image running API & worker services).
   - **Object Security & Retention**: Private S3 statement upload bucket (`bucket_prefix = "sololedger-uploads-<env>-"`, public access completely blocked, **7-day object expiration lifecycle rule** `uploads_ttl`) so uploaded bank statements never linger indefinitely.
   - **Secrets & Audit**: AWS Secrets Manager (`name_prefix = "sololedger-<env>-secret-"`, Django signing keys + DB credentials) injected via ECS Task Execution IAM roles with least-privilege scoping; CloudWatch log groups (`/ecs/sololedger-<env>`) with **7-day retention** and structured redaction filters (`redacted_detail`) preventing PII/statement text from entering logs.
   - **One-Command Teardown**: `force_destroy = true`, `force_delete = true`, `recovery_window_in_days = 0` allow immediate clean `terraform destroy -auto-approve`.

