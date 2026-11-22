# SoloLedger — Contract Index (Canonical V2 Reference)

Authoritative source: `PROJECT_CONSTITUTION.md` Sections A–J.

## 1. Accounting & Precision Rules
- Signed integer minor units (`bigint` USD) in Postgres; `Decimal` in Python parser/classifier; exact decimal strings (`"-42.85"`) in JSON APIs. Never use JS `number` or SQL `float` for money.
- Negative = debit/expense; positive = credit/income/refund.
- `netSpend = -SUM(amount_minor)` for `EXPENSE` categories, excluding invalid raw rows and ignoring `TRANSFER` / `INCOME` categories; refunds preserve positive amounts and can make category `netSpend` negative (do not clamp to 0).
- USD only for MVP totals; non-USD currencies rejected/quarantined at row level.

## 2. PostgreSQL Tables & Constraints
- `accounts` (`id uuid PK`, `display_name`, `timezone`, `created_at`)
- `categories` (`id uuid PK`, `code unique`, `name`, `kind enum(EXPENSE,INCOME,TRANSFER)`, `active`, `sort_order`) — 13 canonical codes (`SOFTWARE`, `OFFICE_SUPPLIES`, `TRANSPORT`, `MEALS`, `UTILITIES`, `PROFESSIONAL_SERVICES`, `MARKETING`, `EDUCATION`, `EQUIPMENT`, `SUBSCRIPTIONS`, `INCOME`, `TRANSFER`, `UNCATEGORIZED`)
- `import_jobs` (`id`, `account_id`, `upload_key`, `file_sha256`, `original_filename`, `status enum(QUEUED,VALIDATING,PROCESSING,AWAITING_REVIEW,COMPLETED,FAILED,CANCELED)`, `idempotency_key nullable`, `total_rows`, `processed_rows`, `valid_rows`, `invalid_rows`, `needs_review_count`, `attempts`, `error_code`, `enqueued_at nullable`, `started_at`, `finished_at`, `created_at`, `updated_at`) — unique `(account_id, idempotency_key)` where non-null
- `import_rows` (`id`, `import_job_id`, `source_line_no`, `raw_hash`, `normalized_description`, `posted_date nullable`, `signed_amount_minor nullable`, `currency`, `source_txn_id nullable`, `status enum(PENDING,VALID,INVALID,DUPLICATE_CANDIDATE)`, `error_code nullable`) — unique `(import_job_id, source_line_no)`
- `transactions` (`id`, `account_id`, `import_row_id unique`, `posted_date`, `description varchar(300)`, `normalized_merchant varchar(160)`, `amount_minor bigint`, `currency char(3)`, `external_ref nullable`, `category_id`, `category_source enum(USER_RULE,KEYWORD,LLM,FALLBACK,USER_REVIEW)`, `confidence numeric(4,3) nullable`, `review_status enum(SUGGESTED,NEEDS_REVIEW,APPROVED)`, `version int`, timestamps) — unique `(account_id, import_row_id)`, indexes `(account_id, posted_date desc, id desc)`, `(account_id, review_status)`
- `merchant_corrections` (`id`, `account_id`, `merchant_key`, `category_id`, `priority`, `active`, `approved_at`, `version`) — unique active `(account_id, merchant_key)`
- `classification_suggestions` (`id`, `transaction_id`, `suggested_category_id`, `confidence`, `method`, `rule_version`, `model_version nullable`, `explanation_code`, `created_at`)
- `review_decisions` (`id`, `transaction_id`, `account_id`, `previous_category_id`, `new_category_id`, `previous_status`, `decision enum(ACCEPT,CHANGE)`, `created_at`)
- `audit_events` (`id`, `account_id`, `actor`, `entity_type`, `entity_id`, `event_type`, `redacted_detail jsonb`, `created_at`)

## 3. Canonical REST Routes (`/api/v1`)
- `GET/POST /api/v1/demo/session` (server-side signed HttpOnly session cookie)
- `POST /api/v1/import-previews` (multipart CSV max 10 MB -> `201 {uploadToken,fileName,sha256,headers,previewRows,suggestedMapping,expiresAt}`)
- `POST /api/v1/imports` (`{uploadToken,mapping}` + `Idempotency-Key` -> `202 {jobId,status:"QUEUED",statusUrl}` or `409 DUPLICATE_IMPORT`)
- `GET /api/v1/imports?cursor=&limit=`, `GET /api/v1/imports/:jobId`, `POST /api/v1/imports/:jobId/retry`, `POST /api/v1/imports/:jobId/cancel`
- `GET /api/v1/transactions?cursor=&limit=&category=&reviewStatus=&from=&to=&q=`
- `PATCH /api/v1/transactions/:id/review` (`{version,decision:"ACCEPT"|"CHANGE",categoryCode?,rememberMerchant?}`)
- `POST /api/v1/reviews/bulk`, `GET /api/v1/merchant-rules`, `PATCH /api/v1/merchant-rules/:id`
- `GET /api/v1/reports/monthly?fromMonth=&toMonth=&currency=USD`
- `GET /api/v1/exports/ledger.csv?from=&to=&category=` (formula-safe text escape preserving numeric amount)
- `GET /api/v1/health`

## 4. Confidence & State Machines
- `confidence is None or confidence < 0.700` -> `NEEDS_REVIEW`; `confidence >= 0.700` -> `SUGGESTED` (`0 <= confidence <= 1`).
- Import: `QUEUED -> VALIDATING -> PROCESSING -> AWAITING_REVIEW -> COMPLETED` (or `PROCESSING -> COMPLETED` when 0 `NEEDS_REVIEW`); `VALIDATING/PROCESSING -> FAILED | CANCELED`; `FAILED -> QUEUED` on explicit retry.
