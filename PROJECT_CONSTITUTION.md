# SoloLedger — Antigravity Implementation Specification

**Target interview:** Apple Software Engineer – Early Career (Front-end), Apple Ads Engineering  
**Resume project:** SoloLedger: Expense Categorization Platform for Freelancers  
**Priority:** P1 — full-stack user experience, async workflows, state correctness, testing and scalability  
**Specification revision:** V2, 2026-11-20. This file supersedes the earlier brief plan.
**Deliverable:** a functional Django + React/TypeScript expense-import workflow, evidence-backed categorization/review system, load tests and test coverage, cloud option, and project-specific interview training.

> **Privacy rule:** all public demonstrations, fixtures, screenshots and benchmark loads use **synthetic statements only**. Never upload actual bank statements or transaction details to a public server/LLM by default. This is an expense-organization demo, not a bank integration or financial-advice system.

## V2 implementation contract — authoritative models, workflows, APIs and visual specification

**Provenance.** The uploaded resume establishes Django/React/TypeScript, statement CSV imports, async processing, LangChain with previous-correction context, confidence below 0.70 routed for review, 12×~90 benchmark, 15-vs-45-minute historical comparison, ~85% historical first-pass accuracy, 500 concurrent users, and 91% historical CI coverage. The detailed tables, contracts, constraints and designs below are **new inferred decisions**, not implied by the resume; implement them consistently to eliminate ambiguity. This V2 contract overrides older sketch-level shapes where fields differ. Log unresolved contradictions to `IMPLEMENTATION_STATUS.md` and stop that feature rather than guessing.

**Priority:** correct real accounting and asynchronous workflows **and excellent product UX in every vertical slice**; then performance/evaluation evidence; finally AWS/cloud. UI craftsmanship is a release gate, not decorative last-mile work. All demo data is synthetic. Never show a fake banking institution connection, tax advice, savings claims or live customer transactions.

### A. Canonical accounting definitions (do not improvise)

A transaction has a **signed amount**: negative = money out (expense/debit), positive = money in (credit/refund). Store integer minor units for USD in PostgreSQL `bigint`; serialize all amounts as exact decimal strings in external APIs (e.g. `"-42.85"`); convert to/from minor units only in validated utility functions. Never use JS `number` arithmetic for money. Currency is ISO 4217 uppercase; the MVP accepts USD only for imported totals, and **rejects or quarantines** other currencies with a row-level error rather than silently FX-converting. Reports group by posting date in UTC-derived calendar date; tenant timezone is used only for displayed timestamp. Refunds credit a category and can make net category spend negative (show negative net spend rather than clamping it to zero). `netSpend = -SUM(signed_amount_minor)` for expense-category transactions in range, excluding unreviewed invalid rows and ignoring non-spend transfer categories. A correctly categorized refund preserves its positive amount and reduces net spending.

Use `Decimal` in parser/classification boundary, integer minor units in DB, and string-typed decimal monetary fields in JSON; document sign conventions in UI and CSV. No currency symbols in stored numeric fields. All IDs UUID, timestamps UTC ISO 8601, all API JSON camelCase, SQL snake_case. Periods are `YYYY-MM` calendar months and date range filters are inclusive start/exclusive end.

### B. PostgreSQL domain model and relationships

| Table | Fields (minimum) | Constraints, ownership, relationship |
|---|---|---|
| `accounts` | `id uuid PK`, `display_name`, `timezone`, `created_at` | Seeded demo identities; not real banking authentication. Production must implement proper identity. |
| `categories` | `id uuid PK`, `code unique`, `name`, `kind enum(EXPENSE,INCOME,TRANSFER)`, `active`, `sort_order` | Seed fixed list; UNKNOWN category exists and does not count as approved business classification. |
| `import_jobs` | `id uuid PK`, `account_id FK`, `upload_key`, `file_sha256`, `original_filename`, `status enum(QUEUED,VALIDATING,PROCESSING,AWAITING_REVIEW,COMPLETED,FAILED,CANCELED)`, `idempotency_key nullable`, `total_rows`, `processed_rows`, `valid_rows`, `invalid_rows`, `needs_review_count`, `attempts`, `error_code`, `started_at`, `finished_at`, timestamps | Unique `(account_id,idempotency_key)` where non-null. Same-account exact file hash can return existing import or explicit duplicate confirmation; no cross-account reuse. |
| `import_rows` | `id uuid PK`, `import_job_id FK`, `source_line_no int`, `raw_hash`, `normalized_description`, `posted_date date nullable`, `signed_amount_minor bigint nullable`, `currency`, `source_txn_id nullable`, `status enum(PENDING,VALID,INVALID,DUPLICATE_CANDIDATE)`, `error_code nullable` | Unique `(import_job_id,source_line_no)` makes retry idempotent. Never discard invalid rows without evidence. Raw financial content must not enter public logs. |
| `transactions` | `id uuid PK`, `account_id FK`, `import_row_id unique FK`, `posted_date date`, `description varchar(300)`, `normalized_merchant varchar(160)`, `amount_minor bigint`, `currency char(3)`, `external_ref nullable`, `category_id FK`, `category_source enum(USER_RULE,KEYWORD,LLM,FALLBACK,USER_REVIEW)`, `confidence numeric(4,3) nullable`, `review_status enum(SUGGESTED,NEEDS_REVIEW,APPROVED)`, `version int`, timestamps | One transaction per valid import row; identical merchant/date/amount on two distinct source lines may be two legitimate purchases. DB unique `(account_id,import_row_id)` plus index on `(account_id,posted_date,id)`. |
| `merchant_corrections` | `id uuid PK`, `account_id FK`, `merchant_key`, `category_id FK`, `priority int`, `active bool`, `approved_at`, `version int` | Unique active exact `(account_id,merchant_key)`; only account owner can change. Later imports use latest approved correction; no retroactive mutation of approved past transactions. |
| `classification_suggestions` | `id uuid PK`, `transaction_id FK`, `suggested_category_id FK`, `confidence numeric(4,3) nullable`, `method`, `rule_version`, `model_version nullable`, `explanation_code`, `created_at` | Audit candidate separately from final chosen category. `confidence` is heuristic unless calibration demonstrated. |
| `review_decisions` | `id uuid PK`, `transaction_id FK`, `account_id FK`, `previous_category_id`, `new_category_id`, `previous_status`, `decision enum(ACCEPT,CHANGE)`, `created_at` | Append-only review history; lock version atomically. |
| `audit_events` | `id uuid PK`, `account_id FK`, `actor`, `entity_type`, `entity_id`, `event_type`, `redacted_detail jsonb`, `created_at` | No full statement rows, raw prompts, full merchant free text or secrets. |
| `export_jobs` (optional, only for large files) | `id`, `account_id`, `status`, `object_key nullable`, `row_count`, `created_at`, `expires_at` | Simple streaming export for MVP can omit this table. If implemented, do not return public object URLs. |

Indexes: `(account_id,posted_date desc,id desc)` on transactions, `(account_id,review_status)` on transactions, `(import_job_id,source_line_no)` on import rows, `(account_id,merchant_key)` on corrections. Foreign keys use restrictive deletes except account-deletion lifecycle which has explicit cascade/delete semantics. Migration files and factory fixtures are mandatory.

**State machines (no magical shortcuts):**

```text
import: QUEUED -> VALIDATING -> PROCESSING -> AWAITING_REVIEW -> COMPLETED
                                    \----------------------> COMPLETED (0 review rows)
       VALIDATING/PROCESSING -> FAILED or CANCELED (cooperative cancellation)
       FAILED -> QUEUED only with explicit retry and retryable code
       AWAITING_REVIEW -> COMPLETED only after all review items resolved

transaction: NEEDS_REVIEW -> APPROVED (accept/change)
             SUGGESTED -> APPROVED (optional user approval)
             APPROVED -> APPROVED new category with version+1 and audit entry
```

`processedRows` <= `totalRows` monotonic, `invalidRows` + `validRows` equals parsed nonheader rows at finish, `needsReviewCount` must equal the query result (not a separately drifting counter). The default dashboard excludes invalid raw rows but displays separate import error details. A canceled worker cannot continue writing rows after cancellation acknowledgment.

### C. Exact fixture generation and CSV mapping rules

Use `scripts/generate_statements.py --seed 2026 --count 12 --rows 90` to create exactly 12 statement files and an independent golden label file. Export fixtures of four distinct header formats, but never falsely imply a branded real bank file. Categories: `SOFTWARE`, `OFFICE_SUPPLIES`, `TRANSPORT`, `MEALS`, `UTILITIES`, `PROFESSIONAL_SERVICES`, `MARKETING`, `EDUCATION`, `EQUIPMENT`, `SUBSCRIPTIONS`, `INCOME`, `TRANSFER`, `UNCATEGORIZED`. Include realistic ambiguous cases: two same-amount charges on same day, refunds, a positive income, a negative debit with currency sign, a quote-comma multiline description, Unicode/BOM, CRLF, invalid dates, blank description, duplicate statement, bank-supplied transaction ID, 10MB limit, formula strings. Ground truth must be generated independently of classifier rules and frozen with SHA256; 12 statements ~90 **valid logical transactions** each plus a separate negative-case fixture set.

Normalized parser mapping:

```json
{
  "postedDateColumn":"Posted Date",
  "descriptionColumn":"Merchant",
  "amountMode":"DEBIT_CREDIT",
  "debitColumn":"Debit",
  "creditColumn":"Credit",
  "currencyColumn":null,
  "fixedCurrency":"USD",
  "transactionIdColumn":"Transaction ID",
  "dateFormat":"%Y-%m-%d",
  "decimalSeparator":".",
  "headerRow":1
}
```

Other supported amount mode: `SIGNED_AMOUNT` with `amountColumn`; if debit and credit both filled, reject row `AMBIGUOUS_DIRECTION`. In `DEBIT_CREDIT` mode, positive debit maps to negative signed amount, positive credit to positive; negative values in debit/credit columns are invalid unless a documented file format explicitly supports them. Reject ambiguous US/EU date formats until user selects mapping. CSV parse is streamed with encoding sniff/preview (UTF-8 and UTF-8 BOM required), no arbitrary executable upload. Retain original upload private for limited TTL (default 7 days), configurable deletion and purging on demo reset. On Excel-compatible CSV export, prefix **text fields** beginning `=`, `+`, `-`, `@`, tab or CR to prevent formula injection, while preserving signed numeric amount cells as verified numeric output.

**Deduplication:** same account+exact statement SHA256 returns `409 DUPLICATE_IMPORT` with `{existingImportId}` unless user explicitly chooses “View existing import”; repeated `POST` with same Idempotency-Key returns exact prior result (`202/200` as appropriate) and cannot schedule two tasks. Within an import, `(import_id,source_line_no)` is authoritative unique. Across *different* statements, same merchant/date/amount is only `DUPLICATE_CANDIDATE` and **requires review**; never silently delete legitimate repeated purchases. Stable external bank transaction ID (if present and documented) can trigger stronger duplicate detection, but record conflict evidence.

### D. Asynchronous job execution without message/DB race

Use Django REST Framework + PostgreSQL + Celery + Redis, with local MinIO/private filesystem storage and S3 cloud mode. `POST /api/v1/import-previews` uploads once, safely validates content and returns temporary upload token and 10 normalized preview rows; `POST /api/v1/imports` commits the import request and starts a real background job. `transaction.on_commit` sends a Celery task **after** the DB transaction; a periodic dispatch-recovery process scans QUEUED jobs not successfully enqueued after a broker outage, so `on_commit` failure cannot silently strand imports. Worker claims job with lease/attempt fencing; task delivery is at-least-once, not magic exactly once. Each row inserts with unique import-row key; categorization and progress checkpoints are idempotent. Do not keep a DB transaction open around an LLM call. Retry only transient I/O/database/broker/model unavailability using bounded exponential backoff; invalid CSV/columns, unresolvable currency and row validation errors are deterministic.

Complete job operations:

1. Preview upload → compute checksum, sample header/rows, infer suggestions, return mapping choices + token. Never process full import yet.
2. Confirm mapping → create `ImportJob(QUEUED)`, store file key, enqueue after commit, return `202`.
3. Worker VALIDATING → parses stream and creates `import_rows` with error codes. Progress visible.
4. Worker PROCESSING → normalize/dedupe/classify in batches of e.g. 100; store transactions and suggestions; test worker death after DB commit and before task acknowledgment.
5. Worker finalizes AWAITING_REVIEW or COMPLETED; UI polls with increasing delay and stops at stable terminal state; AWAITING_REVIEW has a direct “Review N transactions” CTA.
6. User reviews uncertain transactions; review decision commits transaction+correction+audit in one DB transaction, invalidates monthly aggregate and queue; when queue empty, import becomes COMPLETED.
7. Export streams canonical ledger rows and exact totals. No precomputed fake chart data.

The reviewer must retain existing values when a 409 version conflict occurs; provide Refresh/Compare action. Do not clear a user's edits on a failed save.

### E. Canonical REST API contracts (versioned `/api/v1`)

Demo identity is a fixed per-session account context on server; all querysets scoped to that account. For public showcase make accounts disposable and clearly labeled Demo; do not pretend this is bank-grade authentication. No account ID supplied by browser confers access.

| Endpoint | Input | Response | Required tests/errors |
|---|---|---|---|
| `POST /import-previews` | multipart CSV field `file` max 10 MB | `201 {uploadToken,fileName,sha256,headers,previewRows:[...<=10],suggestedMapping,expiresAt}` | 400 malformed, 413 over limit, 415 wrong media, 422 unparseable, temp-object cleanup. |
| `POST /imports` | `{uploadToken,mapping}` and `Idempotency-Key` header | `202 {jobId,status:"QUEUED",statusUrl}` | 409 `DUPLICATE_IMPORT`, 422 bad mapping/expired token. |
| `GET /imports?cursor=&limit=` | `limit` 1–50 | `200 {items:ImportSummary[],nextCursor}` | Account filtered; stable `(created_at,id)` cursor. |
| `GET /imports/:jobId` | UUID | `200 ImportDetail` with counts, phase, failure code, `canRetry`,`canCancel` | 404 other owner; visible row errors capped/paginated. |
| `POST /imports/:jobId/retry` | empty body + Idempotency-Key | `202 {jobId,status}` | 409 if not retryable; no duplicate row business effect. |
| `POST /imports/:jobId/cancel` | `{reason?}` | `202 {jobId,status}` | Cooperative cancellation; 409 already terminal. |
| `GET /transactions?cursor=&limit=&category=&reviewStatus=&from=&to=&q=` | limit 1–100 | `200 {items:Transaction[],nextCursor,totalCount}` | 400 invalid filters; stable `postedDate DESC,id DESC`. |
| `PATCH /transactions/:id/review` | `{version,decision:"ACCEPT"|"CHANGE",categoryCode?,rememberMerchant?:boolean}` | `200 {transaction,reviewDecision}` | 409 version conflict, 422 bad code, automatic correction created only when user explicitly opts `rememberMerchant:true`. |
| `POST /reviews/bulk` | `{items:[{transactionId,version,decision,categoryCode?,rememberMerchant?}]}` max 100 | `200 {accepted:[...],conflicts:[...]}` | Per-item atomic updates, never silently partial without result list. |
| `GET /merchant-rules?cursor=&limit=` | standard | `200 {items:MerchantCorrection[],nextCursor}` | Tenant scoped. |
| `PATCH /merchant-rules/:id` | `{version,categoryCode?,active?,priority?}` | `200 {rule}` | 409 conflict; affects future suggestions only. |
| `GET /reports/monthly?fromMonth=&toMonth=&currency=USD` | <= 24 months | `200 {currency,months:[{month,byCategory:[{code,netSpend}],netSpend,totalCredits,totalDebits}]}` | All amounts decimal strings and sum exactly to ledger SQL. |
| `GET /exports/ledger.csv?from=&to=&category=` | date/filter | `200 text/csv` with Content-Disposition | Proper CSV quoting + formula guard; account scoped. |
| `GET /health` | none | `200 {status,version}` | No secrets. |

Example `Transaction` JSON:

```json
{
  "id":"9fcfe9b8-5c8f-474c-8271-66b01f6d6a44",
  "importJobId":"88ae7a3b-a0d5-49ba-8fbd-8b1709d6970b",
  "postedDate":"2026-02-04",
  "description":"DEMO CLOUD HOSTING",
  "merchant":"DEMO CLOUD HOSTING",
  "signedAmount":"-25.00",
  "currency":"USD",
  "categoryCode":"SOFTWARE",
  "categorySource":"KEYWORD",
  "confidence":"0.680",
  "reviewStatus":"NEEDS_REVIEW",
  "version":1
}
```

Example import status:

```json
{"jobId":"88ae7a3b-a0d5-49ba-8fbd-8b1709d6970b","status":"PROCESSING","totalRows":90,"processedRows":43,"validRows":42,"invalidRows":1,"needsReviewCount":8,"phaseLabel":"Categorizing transactions","canRetry":false,"canCancel":true,"errors":[]}
```

Shared error envelope:

```json
{"error":{"code":"DUPLICATE_IMPORT","message":"This statement is already in your ledger.","requestId":"req_01","details":{"existingImportId":"..."},"fieldErrors":{}}}
```

HTTP status policy: 400 malformed query/json, 401 missing session, 403 forbidden, 404 absent/other user, 409 duplicate/version/state, 413 size limit, 415 unsupported, 422 invalid mapping/row or business rule, 429 rate limited, 503 transient dependency. Add DRF response serializers/OpenAPI and generate TS client types; **never handwrite divergent backend and frontend shapes**. Progress polling every 1s initially then 2–4s backoff, stop in COMPLETED/FAILED/CANCELED; AWAITING_REVIEW stops processing polling but keeps review count query invalidation. Abort pending fetch on unmount.

### F. Classification and evaluation rules

**Precedence:** account-approved merchant rule > exact deterministic merchant lexicon > high-confidence keyword/fuzzy rules > opt-in LangChain provider > UNCATEGORIZED. Apply confident deterministic correction as `APPROVED` only if user explicitly approved that merchant association earlier; model suggestions above threshold are still `SUGGESTED` and user can override. Unknown confidence → NEEDS_REVIEW. `confidence < 0.700` → NEEDS_REVIEW, `confidence == 0.700` → SUGGESTED; `confidence > 1` or `< 0` invalid. Do not call heuristic confidence a calibrated probability. Normalize merchant with Unicode normalization, whitespace folding and safe punctuation cleanup; avoid collapsing distinct merchants by overaggressive fuzzy matching. Correction scope `(account,normalizedMerchant)`; later upload demonstrates remembered correction and avoids leakage across accounts.

Label generation and evaluation: freeze 12×90 fixture ground truth; split into development/held-out sets **by merchant family** to avoid leakage; record categorical confusion matrix, accuracy denominator, macro F1, abstention rate, post-review correctness and count of corrections consulted. The historical 85% is not a forced output. For the 15-vs-45-minute claim, provide a human-study protocol and `NOT_REPRODUCED` until real timed sessions happen; software-generated timings cannot validate human time reduction. For 500-VU API test report endpoint-specific p95, p99, throughput, error rate, resource profile; do not confuse “500 virtual users” with 500 simultaneous in-flight requests. Cover the ordinary read/write API endpoints, separate asynchronous import completion duration. Enforce CI Jest and Pytest coverage >=91% **per explicitly measured scope**, and save separate summaries (do not average unrelated language percentages).

### G. SoloLedger visual system: quiet financial precision, not a fintech template

Design identity: **a considered personal finance workbench**. Calm, legible, secure-feeling, editorial hierarchy; warm-neutral backgrounds with restrained deep teal as action color, precise financial typography, no arcade charts. No external bank logos or copied financial-product screens. Use synthetic merchant names, no transaction screenshots from real people.

```css
:root {
 --canvas:#f6f7f5; --surface:#fff; --surface-muted:#f0f3f1;
 --ink:#17221f; --muted:#60706b; --subtle:#87938e; --line:#dce4df;
 --accent:#166b58; --accent-hover:#105443; --accent-soft:#e5f3ed;
 --danger:#a93f43; --warning:#966416; --success:#147d5c;
 --r-sm:9px; --r-card:16px; --r-dialog:20px;
 --shadow-soft:0 10px 30px rgba(17,37,31,.05);
}
```

System font stack, no bundled proprietary font files. Body 15–16px, meaningful page headings 32–38px, numeric totals 30–44px with `font-variant-numeric:tabular-nums`; readable data grid >=14px. 8px-based spacing with 4px fine increments. Desktop sidebar 220px / main content max 1280px, 24–32px gutters; data table sticky header, 52–60px rows, subtle separators (not giant striped boxes). Use negative sign and restrained tone to represent expenses; do not rely on color alone to distinguish credits/debits. Doughnut charts optional, prefer a clean ranked horizontal category visualization + monthly trend line with axis/unit labels; no giant decorative pie charts.

**UX flow specification:**

| Screen | Exact purposeful layout | States/feedback to verify |
|---|---|---|
| `/dashboard` | Page title “Overview”, period chooser, real net spending total, monthly trend, category list, recent imports and “Review N” CTA | All derived from server; month changes recompute; empty demo prompt invites sample import; no invented chart figures. |
| `/imports/new` | Focused 3-step import composer: Choose file → Map columns → Confirm; right preview pane, helpful file details | Drag/drop **and** button equivalent; mapping validation, date example, +/- amount interpretation, 10 rows, errors and cancellation without losing selection. |
| `/imports/:id` | Progress with descriptive phase, processed/total, timestamp, list of row errors, next action | QUEUED/VALIDATING/PROCESSING/AWAITING_REVIEW/COMPLETED/FAILED/CANCELED all distinct, polling stops appropriately, error retry only when safe. |
| `/transactions` | Dense, beautifully aligned ledger table: Date / Merchant / Category / Amount / Status; filter row and pagination | Full-row keyboard navigation, coherent sort, exact decimals, inline edit focus, no clipping at 200% zoom. |
| `/review` | Split review queue and one transaction detail with suggested category, reason, confidence explanation, alternatives | Accept/Change/Remember merchant actions explicit; optimistic update rollback; 409 conflict retains unsaved decision, focus management. |
| `/rules` | Approved merchant associations and applicability, optional disable; compact detail editor | Explain future-import effect; a changed rule does not silently alter existing approved rows. |
| `/reports` | Calm category ranking, monthly line, exact sum table, CSV export | Currency, date context, CSV equals displayed filtered ledger, meaningful no-data state. |
| `/engineering` | Actual evaluation matrix, load/coverage cards, errors and raw artifact links | Recorded/historical/not-measured status displayed clearly. |

**Responsive:** desktop 1440×900, compact 1024×768, mobile 390×844. On small screens ledger becomes horizontally contained accessible list of transaction rows/cards with preserved amount/category/date—not a cramped 8-column table; summary charts use concise textual alternatives; import steps stack. 44px touch controls, keyboard and screen-reader support, visible focus, descriptive errors, reduced motion, 200% zoom, WCAG 2.2 AA. Animations only for progress transition/row insertion ~150–180ms and disable under prefers-reduced-motion. No gradient hero, fake investment graph, purple-gold fintech cards, emojis, meaningless illustration or unreadable text. Microcopy should be “Import statement”, “Map columns”, “Review 8 items”, “Remember this merchant”, “Export ledger”, not motivational slogans.

### H. Exact unit, end-to-end and visual test matrix

Test each boundary with at least these fixtures:

- CSV: UTF-8 BOM, multiline escaped commas, wrong date format, missing header, blank amount, debit+credit both filled, USD vs unknown currency, 10MB+ rejection, duplicate file, two legitimate identical charges, formula text, negative refund sign, retry after worker interruption.
- DB: amount and report sum exact, unique import row, optimistic review concurrency, tenant A cannot read tenant B, correction only influences future imports, cancel during processing, broker unavailable after DB commit, duplicate queued task.
- Classifier: exact .699/.700/None/invalid, prior correction precedence, model timeout fallback, synthetic-only provider payload, held-out metrics, no leakage from evaluation labels.
- UI: drag/drop + button file input, mapping errors, queue progress, failed/blocked retry, route refresh, reviewed row disappears from review queue, dashboard totals change, CSV export matches ledger, large dataset pagination, error/empty/loading state, keyboard-only journey.
- Performance: full 500 virtual user run only on approved machine; capture p95/p99 separately for reads/writes, DB connections, worker utilization; release gate does not falsely say pass on a 50-user smoke run.
- Browser visual QA: capture all page states at 1440/1024/390; Playwright pinned Chromium screenshots plus independent manual/browser agent review; check text overflow, row alignment, card density, charts, sticky actions, form errors, mobile scrolling and screenshot consistency. No blanket approval from a computer vision score alone.

**Performance budgets for *UI* as targets:** route bundle split, no synchronously imported massive chart lib on upload step; input-to-feedback feels immediate, avoid rerendering full table per row change, only poll active import jobs; report LCP and total JS bytes. Never pass mocked data as a live import during demo.

### I. Small-agent implementation sequence with concrete completion checks

1. Scaffold Django/DRF, PostgreSQL migrations, React/Vite/Jest/RTL, Docker Compose; run static checks.
2. Implement account-scoped categories, `import_jobs`, `import_rows`, `transactions` models and required DB constraints; seed categories and 12×90 fixtures; run migration twice.
3. Implement preview upload endpoint, temp upload TTL, mapping inference and schema validators; test 10MB, bad CSV and ambiguous date.
4. Implement import-create endpoint + Celery dispatch/recovery; process **one known 5-row fixture** and show exact row counts in DB.
5. Build React import journey using tokens and real endpoints; browser verify it including progress. **First vertical-slice gate requires actual file -> queued worker -> ledger in browser.**
6. Add categorization rules, previous corrections, review API, second-import effect and queue UI; test 0.699/0.700.
7. Implement immutable review decisions, exact reports, CSV export, corrections page; confirm SQL sums match export.
8. Add duplicate retry, worker crash after commit, broker restart, tenant isolation, cancel/409 conflict, data minimization tests.
9. Add independent held-out classifier evaluation and separate load/coverage harness; record full environment and raw outputs.
10. Complete visual/accessibility and screenshot review of all routes and states; fix rough spacing/uneven typography and overflow, not only functional bugs.
11. CI, optional approved AWS deployment, teardown, user-facing walkthrough, interview packet generated from code and measured evidence.

Each task handoff format: `FILES CHANGED`, `WHY`, `EXACT COMMANDS`, `API SAMPLE`, `TEST OUTPUT`, `SCREENSHOT`, `EVIDENCE`, `OPEN BLOCKERS`, `NEXT STEP`. Lead agent must not mark a step VERIFIED until commands actually run. Independent reviewer must challenge financial arithmetic and worker replay, not only check UI snapshots. Maintain `IMPLEMENTATION_STATUS.md` with states `NOT_STARTED`, `IMPLEMENTED_UNVERIFIED`, `VERIFIED`, `BLOCKED_EXTERNAL`, `BLOCKED_CONTRACT`.

### J. Interview completion gate

Generate `interview/SOLOLEDGER_INTERVIEW_GUIDE.md` with at least 45 principal questions, 90 follow-ups and 15 debug scenarios. For **each** answer provide 30/90/300-second versions, concrete Django/React files, API shapes, DB constraints, error and retry behavior, measured result or explicit `NOT_MEASURED`, rejected alternative and failure follow-ups. Must include: 202 vs synchronous import; `transaction.on_commit` and broker outage gap; Celery duplicate delivery; strict signed money/refunds and exact SQL sums; confidence boundary; held-out evaluation; human time claim; 500 virtual users scope; queryset N+1; React Query cache keys; worker progress UX; 91% coverage denominators; simulated privacy model; AWS S3 private objects and ECS cost. Interview agent reads source and artifacts only after code/tests exist; no generic invented “we optimized...” stories.


### Universal Antigravity execution protocol — mandatory for less capable agents

**This is not a one-shot generation prompt.** The lead agent must create `IMPLEMENTATION_STATUS.md`, `TASKS.md`, `docs/architecture-decisions.md`, `docs/contracts/`, and `evidence/` before work starts. Break delivery into tasks small enough to finish with tests in one coding session; never ask a subagent to "build the whole app". The **latest V2 data/API/UX contract in this file is the single source of truth**. Existing abbreviated examples below are educational context, not permission to invent alternate routes or fields.

Each subagent task must be issued with this exact format:

```text
TASK ID: <e.g. ADC-006>
GOAL: <one independently testable behavior>
ALLOWED FILES: <explicit paths/directories>
READ FIRST: <relevant sections of this specification and existing source>
DO NOT TOUCH: <other agents' files, database contracts unless approved>
INPUT CONTRACT: <exact types, routes, sample payloads>
OUTPUT CONTRACT: <exact types, routes, sample payloads>
STEPS: <small ordered implementation steps>
TESTS TO RUN: <exact commands + expected assertions>
BROWSER STATES TO CHECK: <URLs, viewport sizes, interactions, if UI>
EVIDENCE TO SAVE: <raw output/log/screenshot/trace paths>
DONE WHEN: <all listed assertions pass>
BLOCKER POLICY: stop, write reason in IMPLEMENTATION_STATUS.md; never fabricate a stub.
```

The lead agent works in this loop: **read existing code → select one task → confirm contract → implement smallest working slice → run typecheck/lint/tests → run browser check if visible → inspect diff → record evidence → mark VERIFIED → merge**. If the environment lacks Docker, Kafka, cloud permissions, browser, or LLM credentials, mark that specific test `BLOCKED_EXTERNAL` with a reproduction command and preserve what genuinely worked. Do not treat a green mocked test as evidence for a live integration.

**Hard prohibitions:** never silently change an API name, never add fields just to make frontend types compile, never use `any`/`@ts-ignore`/disabled ESLint in the frontend, never hardcode a business success response, never use a JSON fixture in a route described as live, never add fabricated KPI cards or synthetic "real" screenshots, never mark a performance target achieved without raw runs, never suppress an error in a catch block, never bypass a failing test by deleting it. No giant `App.tsx` or `views.py`/`main.go` monolith: split by feature and contract; refuse circular imports. Use stable IDs and deterministic seeds in tests, and always test the negative/failure branch.

**UI review is mandatory at every visible feature.** Implement a shared token sheet and base primitives first; never import an unreviewed component library/theme that overrides the specified look. Take actual browser screenshots of the user journey at desktop/tablet/mobile; inspect them yourself and through an independent reviewer/browser agent. Score each page **pass/fail** on hierarchy, spacing, typography, alignment, affordances, accessible keyboard/focus, responsive behavior, empty/loading/error/partial states and whether the content is real. If any critical dimension fails, return the task to the UI agent with the screenshot and one precise issue; visual QA is **not** satisfied by a build passing. External inspiration should emphasize clarity, consistency and meaningful feedback, not copy Apple brand assets or proprietary screens. Reference: https://developer.apple.com/design/human-interface-guidelines/design-principles/ ; WCAG 2.2 AA https://www.w3.org/TR/WCAG22/ ; Playwright screenshots https://playwright.dev/docs/test-snapshots .

**Test strategy:** unit → contract/component → real DB/broker integration → real user/browser E2E → performance/fault injection → visual regression. Pin browser/OS in screenshot CI, freeze seed/time where tests require repeatability, capture console/network warnings, and test 200% zoom. Report `NOT_MEASURED` or `NOT_EXECUTED` for benchmarks/cloud providers without evidence. Never copy historical resume numbers into metrics storage or dashboards.

**Acceptance is by evidence, not confidence:** a task is VERIFIED only with `commit ID`, `commands+exit codes`, `raw test output`, `affected API sample`, `screenshot/trace if UI`, `known limitations`. Lead reviewer may veto a task even with passing tests if it violates the contracts or visual instructions. At the end, an **independent interview agent** reads the final source, tests, architecture decisions and raw benchmark outputs and writes accurate resume-aligned answers; a fictional explanation must be flagged as hypothetical, not phrased as something already implemented.



---

## Original scope, delivery, tests, cloud and interview requirements retained below

## 0. Coding-agent operating contract

Priority is **(1) substantiate every SoloLedger resume bullet, (2) make decisions and measured results interview-defensible, (3) deliver an excellent responsive frontend, (4) optional cloud deployment and cosmetic polish**. Apple Ads will care about your React/TypeScript/UX/testing decisions, so don't reduce this to a Django API demonstration.

Stop expanding scope when a useful vertical slice is untested. Do not claim benchmark results match historical resume bullets unless actually measured with documented methodology.

## 1. Resume-to-evidence acceptance matrix

| Resume claim | Implementation | Required proof |
|---|---|---|
| Django + React/TypeScript replaces spreadsheet categorization | Fully working browser import, categorized ledger, monthly totals, export | Recorded E2E walkthrough and backend API contracts |
| CSV statement uploads | Parser with selectable mappings, validation, row errors, normalization | Fixture suite covering multiple formats, corrupted CSV, duplicates |
| Background jobs kept uploads responsive | Real Celery task/Redis queue, 202 + status polling, retries and idempotency | API response timings while categorization job runs |
| LangChain suggestion logic incorporating prior corrections | Rules + retrieval of user-approved merchant corrections + LLM fallback behind adapter | Accuracy test and before/after correction fixture |
| Confidence **below 0.7** routes to review | Explicit `confidence < 0.70` logic; user-editable review decisions | Boundary tests at .699/.700 and UI review queue |
| Corrections saved for later imports | User-scoped correction model, versioned rule precedence | Second import shows remembered correction and no cross-user leakage |
| 12 statements × ~90 transactions | Generator emits 12 labeled fixtures totaling ~1,080 rows | Seed manifest and independent ground-truth labels |
| ~15 min vs 45 min manual review | Human-comparison protocol or clearly labeled historical-only claim | Timed study notes if performed; never fake human session durations |
| ~85% first-pass correct categories | Categorizer scored against labeled ground truth, with confusion matrix | Accuracy, macro F1, coverage, abstention/review rate, dataset hash |
| API endpoints <150 ms at 500 concurrent users | k6/Locust load against *ordinary APIs* with warm data, excluding long-running imports | p50/p95/p99, throughput, errors, concurrency, hardware/cloud specification |
| CI enforced **91%** coverage | Jest/Vitest UI and Pytest backend coverage thresholds, aggregate or separately reported | Raw coverage reports, exact denominator, CI workflow |

Treat the numbers in the resume as **historical**. A reconstruction with different numbers must disclose its measured values without dressing them up.

## 2. Product experience — complete user journey

A freelancer visits SoloLedger, downloads a synthetic sample bank statement (or uploads an allowed CSV), maps columns, imports asynchronously, watches progress, reviews suggested categories, edits uncertain categories, sees monthly totals and trends, and exports the finalized ledger. On a future import, previously approved merchant rules should meaningfully improve suggestions.

**Required frontend pages:**

1. `/dashboard` — monthly spending, category breakdown, trend, recent imports and needs-review count.
2. `/imports/new` — drag/drop CSV, file size/type safeguards, mapping wizard and preview of normalized first rows.
3. `/imports/:id` — real job state `queued → validating → processing → completed / failed`, per-row errors, retry and cancel safety.
4. `/transactions` — searchable, filterable, paginated categorized ledger; keyboard-accessible inline edits and bulk review.
5. `/review` — only suggestions below 0.7 or flagged by rules; accept, edit, reject, and explain the confidence signal.
6. `/rules` — prior user-approved merchant corrections, simple edit/disable/priority control.
7. `/reports` — monthly/category totals and **actual downloadable CSV**.
8. `/engineering` — optional performance, coverage and categorization-evaluation evidence.

**Frontend specifics:** React 18+/strict TypeScript, Vite, React Query for server state, local component state/Zustand only where necessary, accessible form controls, error/empty/loading states, keyboard navigation, responsive desktop/mobile. Optimize import progress without aggressive polling; stop polling on terminal job status, switch to SSE only if it adds measurable value. Protect unsaved review edits. Reports must sum exactly to the underlying ledger, not random frontend chart values.

## 3. Where data comes from — no machine or privacy blockers

The core system requires **no paid bank API or real financial data**. Generate deterministic CSVs with `Faker` plus labeled merchant/category templates and a fixed RNG seed; commit only small fixtures, not secrets or actual user statements.

```text
fixtures/statements/sample_01.csv ... sample_12.csv
fixtures/ground_truth.csv
fixtures/merchant_aliases.json
fixtures/import_edge_cases/*.csv
```

At least 12 representative statements with approximately 90 rows each; use multiple banks' *generic* header styles without impersonating a financial institution. Example header variants:

```csv
Date,Description,Amount,Currency
2026-01-02,ACME OFFICE SUPPLIES,-42.85,USD
```

```csv
Posted Date,Merchant,Debit,Credit,Transaction ID
2026-01-03,DEMO CLOUD HOSTING,25.00,,test-123
```

Fixture families: repeated merchant spellings, ambiguous merchant names, subscriptions, refunds/reversals, split charges, duplicate rows, currency codes, date ambiguity, UTF-8 BOM, CRLF, quoted commas, blank cells, large files, invalid amount, formula-injection strings, CSV file pretending to be an executable, same amount/date legitimately occurring twice. Ground-truth categories fixed independently from output of the actual classifier to prevent label leakage.

Suggested categories: software, office supplies, transport, meals, utilities, professional services, marketing, education, equipment, subscriptions and uncategorized. Do not claim the system automatically determines tax deductibility; it is a user-driven organization tool.

Optional public datasets may be added only with explicit license and provenance; synthetic data is sufficient and best for reproducibility. For a real user's private statement, require local/authorized deployment, clear retention/deletion behavior and no third-party model transmission by default.

## 4. System architecture

```text
  React/TypeScript + Vite
       |    |      |
       |    |      +-- ledger / review / monthly charts / CSV export
       |    +--------- React Query polling/status + controlled edits
       |
       v
  Django REST API ---- PostgreSQL
       |                   |
  upload validation      transactions, imports, corrections, audits
       |
  private object storage (local disk/MinIO; AWS S3 in cloud)
       |
  Celery queue (Redis dev broker)
       |
  Celery worker: parse -> normalize -> dedupe -> categorize
       |                              |
       |                         deterministic prior-correction lookup
       |                              |
       +------------------------- LangChain/provider adapter (optional)
                                      |
                                confidence + review queue
```

**Design choices:** Django + DRF, PostgreSQL, Celery, Redis for local queue, Python classification domain layer with testable interfaces, LangChain orchestration only when it adds value. Do not require LLM API keys for core categorization or CI. The default classifier can use merchant rules and a deterministic mock suggestion provider; live LLM is opt-in. If confidence cannot be calibrated honestly, present it as a **heuristic confidence**, not a probability guaranteed correct.

## 5. Repository layout

```text
sololedger/
├── AGENTS.md
├── PROJECT_CONSTITUTION.md
├── .agents/rules/project-focus.md
├── .agents/agents/{frontend,backend,classification,worker,qa-perf,cloud,interview}.md
├── backend/
│   ├── config/
│   ├── apps/{accounts,imports,transactions,categorization,reports,audit}/
│   ├── classification/{rules.py,confidence.py,provider.py,langchain_adapter.py}/
│   ├── tasks/
│   └── tests/
├── frontend/
│   ├── src/{routes,components,features,api,models,tests}/
│   ├── e2e/
│   └── vite.config.ts
├── fixtures/{statements,import_edge_cases,ground_truth.csv}/
├── scripts/{seed.py,generate_statements.py,score_classifier.py}/
├── load/{k6,locust}/
├── infra/{docker,terraform/aws}/
├── evidence/{categorization,load,coverage,imports,security,cloud,ux}/
├── interview/
├── .github/workflows/
├── Makefile
└── README.md
```

Implement **Jest + React Testing Library** for the frontend unit/component suite because the resume explicitly names Jest. Vitest is optional for extra Vite-native tests, not a substitute for the promised Jest implementation; avoid maintaining duplicate suites for the same cases. The backend must use Pytest + coverage.

## 7. CSV ingestion and asynchronous workflow

1. User uploads allowed `.csv` (MIME plus content checks), configurable max e.g. 10 MB; reject unsafe/huge/garbled files without loading entirely in RAM.
2. Store private upload and create `ImportJob` transactionally; return **202** with stable job ID.
3. On DB commit enqueue Celery task; do not enqueue before persistence (`transaction.on_commit`).
4. Worker streams CSV, applies column mapping, normalizes dates/currency/amount/merchant, checks duplicates, validates rows, then classifies in batches.
5. Persist results in bounded DB transactions with progress checkpoints, idempotent resumption, and row-level errors; never hold a DB transaction open across slow LLM calls.
6. UI shows progress without blocking, stops polling when job reaches terminal state. Failed jobs retain evidence and can be safely retried if failure is transient.
7. CSV export escapes spreadsheet formulas beginning `=`, `+`, `-`, `@` where appropriate while preserving true numeric fields; document handling for negative amounts vs formula strings. Export only user's data.

Required states: `QUEUED`, `VALIDATING`, `PROCESSING`, `AWAITING_REVIEW`, `COMPLETED`, `FAILED`, `CANCELED`. Clear status transitions and idempotent duplicate-trigger test.

## 8. Categorization and human correction logic

**Decision order:**

```text
1. user-approved exact merchant correction (highest precedence)
2. user-approved stable normalized-merchant rule
3. deterministic category keyword/rule set
4. optional LLM suggested category via LangChain
5. uncategorized fallback
```

Each suggestion has `{ category, confidence, method, explanationCode, modelVersion, ruleVersion }`. Apply:

```python
if confidence < 0.70:
    review_status = "NEEDS_REVIEW"
else:
    review_status = "SUGGESTED"  # user can still override
```

Test exact boundary `.699`, `.700`, `None`, invalid probabilities. A user's approved category becomes a scoped correction, influences a later import, and invalidates relevant React Query cache. Category overrides must never silently change already approved historical transactions unless user explicitly requests a bulk reclassification.

**LLM privacy:** default to sanitized, synthetic merchant label; require explicit opt-in and data minimization for live model requests. Do not send bank account numbers, transaction IDs, full statements or other sensitive fields to third parties. Mock LangChain/provider outputs in CI with deterministic fixtures. Logging redacts descriptions and uploaded file content by default. An LLM suggestion is not automatically accepted as ground truth.

## 10. Automated categorization evaluation: ~85% claim

Generate 12 statements of ~90 rows each with *independent* ground truth. Freeze a held-out split before tuning. Report:

- first-pass accuracy = correct suggestions / all labeled imported transactions (specify whether abstentions count as incorrect);
- coverage (suggested vs needs-review), precision per category, macro F1, confusion matrix;
- breakdown before/after applying user corrections **without leaking future corrections into prior evaluation**;
- reproducibility: seed, dataset checksum, classifier/model version and exact commands.

Use `make eval-categorization`. The historical ~85% is a target to examine, **not a required fabricated output**. Any live-LLM evaluation must record model version, token cost and nondeterminism. Default regression suite uses deterministic mock model.

## 11. 15-minute vs 45-minute manual process claim

This is a human-time comparison, not a software benchmark you can fake. Define a reproducible experiment: same sample statements, same reviewers or matched participants, stopwatch, same category taxonomy, timed manual spreadsheet categorization vs SoloLedger review-assisted workflow, no cherry-picked cases, record variation and limitations. If no human comparison is actually conducted, mark the historical claim **unverified in this reproduction** and report measurable automated steps/decisions instead. Do not synthesize human timing logs.

## 12. 500 concurrent users / <150 ms endpoint claim

**Performance contract must be explicit.** Load test with k6 or Locust using 500 *concurrently active virtual users* (not 500 total requests). Choose realistic steady-state mix:

```text
GET /api/v1/transactions?page=...    35%
GET /api/v1/reports/monthly          25%
GET /api/v1/imports/:id              20%
GET /api/v1/merchant-rules           15%
PATCH /api/v1/transactions/:id        5%
```

Do not include background classification time in ordinary synchronous endpoint latency; report async job end-to-end duration separately. Record warm-up, 3–5 minute steady state where feasible, user count, arrival rate, concurrency, seed, DB size, worker processes, DB pool, connection count, machine/instance type, p50/p95/p99, error rate and throughput. State clearly which percentile (e.g. p95 <150 ms) is the *new* acceptance target. A 500-VU run on an underpowered machine may fail; preserve result and use a budget-approved EC2/ECS profile rather than fabricating it.

Performance work: PostgreSQL indexes on `owner_id, posted_at, category`, cursor pagination, N+1 query checks, response sizes, serializer overhead, DB connection pooling, caching if measured, and preventing Celery workers from starving API resources.

## 13. Testing and coverage claim

- **Pytest:** CSV parsing, boundary dates/currencies, Decimal math, duplicate imports, retry/idempotency, DB transactions, corrections, category threshold, tenant authorization, CSV export injection, row errors, timeout and fallback.
- **Jest + React Testing Library:** upload wizard, progress states, category review, accessible dialogs, report sums, query invalidation, errors, keyboard navigation.
- **Playwright E2E:** upload generated sample → progress → categorized ledger → needs-review → approve correction → second import → rule reused → export CSV → re-import attempt remains safe.
- **Load:** k6/Locust separate profiles; CI smoke ≠ 500 concurrent stress test.
- **Coverage:** collect backend + frontend metrics, publish raw HTML/XML/JSON and separate percentages. Enforce a **91% project-defined coverage gate** only where the instrumentation and covered scope are explicit; do not combine percentages across different languages into one misleading percentage. Branch coverage and critical-path tests matter more than a high but hollow headline.
- **CI:** static checks, migrations, isolated Postgres+Redis services, tests, fixtures, lint/typecheck, E2E, coverage, Docker build/security scan, optional preview deployment.

## 14. Cloud deployment (use when materially useful)

**Local reproducible:** Docker Compose PostgreSQL + Redis + Django web + Celery worker; local private storage / MinIO; Vite app; deterministic fixtures. `make dev`, `make reset`, `make test` should work without cloud/model keys.

**AWS production-shaped profile with user-approved credentials/budget:**

```text
S3 private bucket           -> CSV uploads and generated exports
CloudFront/S3              -> React SPA
ECR                       -> versioned backend/worker images
ECS Fargate               -> API and Celery workers
RDS PostgreSQL            -> managed data store (optional if budget limited)
CloudWatch                -> app/queue metrics
Secrets Manager or SSM     -> keys and DB credentials
Terraform                 -> provisioning and teardown
```

SQS may replace the Celery Redis broker **only if the agent implements and tests the actual broker configuration**; do not include both for architecture decoration. ElastiCache is optional/expensive; local Redis container in a cloud lab must be labeled a dev-only tradeoff. Use IAM least privilege, no public S3 bucket for statements, encrypted storage/transit, lifecycle/retention and deletion controls. The public demo should work entirely with fictional statements and resettable demo accounts. Include cost estimates, tags, teardown and `make cloud-destroy`. Do not provision fee-bearing infrastructure without approval. If blocked, mark cloud `BLOCKED_EXTERNAL`.

## 15. Reviewable final product

A live URL is useful but not a substitute for the project. A reviewer should be able to import **one** fixture, watch a real background job, approve low-confidence transactions, see monthly totals update and export CSV. Top of README: story, architecture, setup, 60–90-second demo, what was measured, limitations, security/privacy notes. Screenshots should show genuine end-to-end state rather than styled placeholders. Browser verify form labels, mobile/tablet screens, no stuck spinners and no console errors.

## 16. Antigravity execution and subagent contracts

**Lead:** plan gates, data contracts, end-to-end integration, review of evidence and scope. **Do not delegate first vertical slice**. Build:

```text
fixture CSV -> Django upload API -> Celery -> PostgreSQL categorized rows
            -> React import progress -> review -> monthly totals
```

Then freeze model/API contracts and use isolated subagents/worktrees where available:

| Agent | Files owned | Completion proof |
|---|---|---|
| `frontend-agent` | React app, typed client, UI tests | Browser upload-to-export demo and screenshots |
| `backend-agent` | Django models, DRF API, imports | Migration/tests, idempotent API smoke |
| `classification-agent` | Rule/LLM adapters, evaluation | Independent labeled accuracy report and privacy tests |
| `worker-agent` | Celery retry/progress/failure behaviors | Real background completion, crash/retry tests |
| `perf-qa-agent` | k6, test infrastructure, coverage | Raw 500-VU run where possible, CI reports |
| `cloud-agent` | Terraform/Docker/deploy | Cloud evidence or explicit external blocker |
| `interview-agent` | Read-only after implementation | File-specific interview Q&A, honest metrics |

Keep `AGENTS.md` at repository root and create `.agents/rules/project-focus.md` with YAML frontmatter declaring `trigger: always_on`. The leading rule must forbid real bank data in public demo, prohibit invented accuracy/latency/human timings, require backend/React correctness before polish, and mandate safe CSV/PII handling. Agent may use browser subagent for UI verification and independent tester subagent to break import/review flows. Integrate changes through passing tests; no unreviewed concurrent edits to shared schema or API contracts.

### Initial prompt for Antigravity

```text
You are the lead implementing SoloLedger from this plan. The primary deliverable is a real Django+React/TypeScript application with async CSV imports, a correct user-reviewable ledger, previous-correction-aware categorization and measurable load/accuracy/coverage evidence. Start with one fixture CSV -> 202 response -> Celery processing -> DB rows -> React progress/list/review. No workstream may expand before that vertical slice passes. Use deterministic sample statements, never real financial data. Then delegate isolated frontend, classifier, worker, testing and AWS tasks after freezing contracts. Enforce the <0.7 review gate, exact Decimal accounting, safe exports, cross-user isolation and idempotent imports. Preserve actual 12-statement evaluation, user-timing study status, 500-concurrent-user performance, and 91% coverage reports without fabricating historical outcomes. End with actual browser verification and a code/evidence-grounded interview guide.
```

## 17. Milestone gates, commands and stop conditions

```text
make setup
make seed-statements
make dev
make test-backend
make test-frontend
make test-e2e
make eval-categorization
make load-smoke
make load-500        # manual/approved machine or cloud profile
make coverage
make demo-record
make cloud-plan      # opt-in
make cloud-destroy   # opt-in
```

- **Gate 0:** environment, fixture provenance, Django migrations and app scaffold.
- **Gate 1:** single-file asynchronous import and real React progress/ledger working.
- **Gate 2:** review threshold/correction memory and second-import regression pass.
- **Gate 3:** 12×90 scored evaluation, private-data safety, duplicate/retry handling.
- **Gate 4:** exact monthly reports, CSV export, accessibility, browser E2E.
- **Gate 5:** coverage enforcement and separate load/accuracy/review-time evidence.
- **Gate 6:** optional cloud deployment or explicit blocker, teardown docs.
- **Gate 7:** structured interview evidence packet and genuine reviewer demo.

Do not add bank OAuth, Plaid integration, credit scoring, taxes, billing, accounting integrations, mobile-native apps, multi-agent LLMs, complicated infrastructure, or elaborate design systems. Preserve focus on the precise resume bullets.

Evidence schema per run: `evidence/<topic>/<run-id>/{commit.txt,environment.json,config.json,raw.json,summary.json,limitations.md}`. For privacy, logs and screenshots must contain only synthetic data.

## 18. Interview package — every answer references actual implementation

Generate `interview/SOLOLEDGER_INTERVIEW_GUIDE.md`, `DECISIONS.md`, `FAILURE_STORIES.md` and `SYSTEM_DESIGN.md` only when code, E2E and benchmark evidence exist. Each primary answer: 30 seconds / 90 seconds / deep technical explanation; concrete code paths; decision and rejected alternatives; real measurement; edge cases; failure; 2–4 hard follow-ups.

**Minimum: 45 primary questions, 90 follow-ups, 15 debug situations, 6 design prompts.** Cover:

- React controlled forms, async progress UX, polling vs SSE, React Query invalidation, error state, re-renders, large ledger virtualization, accessible data grids, responsive charts.
- Django request lifecycle, ORM N+1, `select_related`/`prefetch_related`, indexes, pagination, serializer performance, `transaction.atomic`, `transaction.on_commit`.
- Celery queue semantics, retries vs poison data, worker crash after DB commit, exactly-once *business effect* with idempotency, race between upload and queue publish.
- CSV hazards: encoding, bank schema variations, dates, decimal accuracy, duplicate statement vs repeated charges, formula injection on export, multi-tenant privacy.
- LangChain use, deterministic prior correction precedence, confidence calibration, why threshold is 0.7, held-out evaluation, false positives vs false negatives, user feedback loops, privacy and model failure.
- Meaning of 85% first-pass accuracy, bias and class imbalance; whether 15 vs45 is reproducible human measurement; load-test percentile, 500 concurrent vs 500 requests, error rate, test coverage denominator.
- PostgreSQL vs Redis roles; S3 private upload flow; ECS/RDS tradeoffs; CI/CD; secret management; deployment/rollback.
- Apple-style frontend design: efficient table rendering, asynchronous workflow UX, API caching, reusable components, failure recovery and user control.

**Mandatory skeptical follow-ups:**

1. "Why is your classifier confidence 0.70? Is that calibrated?"
2. "Can an LLM override a prior user correction?"
3. "How do you avoid classifying the same charge twice after Celery restarts?"
4. "What if a user uploads the same statement twice? What if two identical $10 charges are legitimate?"
5. "Why use Celery rather than run the job inside Django?"
6. "What transaction boundary prevents enqueue-before-commit races?"
7. "How do you protect private financial information from model APIs and logs?"
8. "Did you actually measure 500 simultaneous users? What was p95?"
9. "Does 91% coverage mean your failure paths were tested?"
10. "What did you count as a correct first-pass category?"
11. "How do you ensure monthly totals remain exactly correct after edits?"
12. "What happens if category review and report refetch race each other?"
13. "What would you change if uploads were 100 MB each?"
14. "Where did the 15 vs 45 minute figure come from?"
15. "Why Django instead of Node for this project, given Apple Ads is Node-heavy?"

## 19. Definition of done

The implementation is complete when an actual CSV file flows through a real async job into PostgreSQL and a correct React ledger; user corrections are reusable; 0.7 threshold, safe import/export and idempotency are tested; monthly totals reconcile; the 12-sample evaluation, 500-user benchmark status, human timing-study status and 91%-coverage gate are transparently documented; CI works; optional cloud is executed or blocked honestly; and interview answers cite actual code/tests/measurements. UI-only or API-only demos are not sufficient.

## Technical references for the agent

- Django transactions/on_commit: https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- Django REST Framework: https://www.django-rest-framework.org/
- Celery: https://docs.celeryq.dev/
- React Query: https://tanstack.com/query/latest/docs/framework/react/overview
- Playwright: https://playwright.dev/docs/intro
- Antigravity rules: https://antigravity.google/docs/rules/
