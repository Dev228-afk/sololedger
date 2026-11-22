# SoloLedger — Freelance Statement Ingestion, Hybrid Categorization & Signed-Integer Ledger

SoloLedger is a full-stack **Django 5 + Celery + PostgreSQL 16 + Redis 7 + React 19 + TypeScript** personal business accounting workbench built around a strict engineering invariant: **AI/heuristic categorization assists review; exact SQL integer math and human approval own the ledger.**

> [!NOTE]
> All accounts (`11111111-1111-5111-8111-111111111101` *Demo Freelancer — Studio North*, `...1102` *Demo Consultant — Cedar Labs*) and CSV statements are synthetic. No live bank OAuth/Plaid connections, tax advice, or production cloud billing are active.

---

## Architecture Overview

```text
  React 19 SPA (Vite + TanStack Query v5 + BigInt money helpers)
        │  Cookie Session + X-CSRFToken + Idempotency-Key
        ▼
  Django 5 / DRF API (Waitress WSGI locally · Gunicorn/ECS target)
        ├─── POST /api/v1/import-previews ───▶ ImportUploadPreview (disk/private S3, 24h TTL)
        ├─── POST /api/v1/imports ──────────▶ Atomic ImportJob(QUEUED)
        │                                       └─ transaction.on_commit ──▶ Celery Redis queue `sololedger`
        │                                                                      (+ beat `recover_stranded_imports`)
        ├─── Celery Worker ──▶ Stream CSV parse ──▶ Batch 100 classify OUTSIDE DB write lock:
        │        1. Active MerchantCorrection (APPROVED, 1.000)
        │        2. EXACT_LEXICON / 3. KEYWORD_RULE / 4. LangChain MockCategorizerProvider (SanitizedSuggestionInput)
        │        5. Fallback UNCATEGORIZED + `<0.700` -> NEEDS_REVIEW
        └─── GET /api/v1/reports/monthly & /api/v1/exports/ledger.csv
                 └─ SQL SUM(amount_minor) in signed USD cents + formula-safe text escaping
```

### Core Guarantees
- **Signed Minor-Unit Accounting (`bigint`)**: Amounts are parsed into integer USD cents via `Decimal` (`backend/apps/transactions/money.py:parse_decimal_to_minor`) and formatted on the client with `BigInt` (`frontend/src/api/money.ts`), avoiding IEEE-754 float drift across expenses (`< 0`), refunds (`> 0` inside expense categories), and income (`> 0`).
- **Commit-Safe Async Enqueue & Crash Recovery**: `ImportsCollectionView.post` persists `ImportJob(status="QUEUED", enqueued_at=None)` and enqueues `process_import_job.delay(job_id)` strictly inside `transaction.on_commit`. If the broker drops during commit, periodic `recover_stranded_imports` re-dispatches orphaned jobs, while `ImportRow` `(import_job, source_line_no)` and `Transaction` `(account, import_row)` unique constraints guarantee idempotent batch retries.
- **Explicit Review Gate (`< 0.700`) & Optimistic Locking**: Transactions below heuristic confidence `0.700`, `None` confidence, or flagged as `duplicate_candidate` route to `/review` (`NEEDS_REVIEW`). Concurrent tabs are protected by `select_for_update()` and monotonically checked `version` (`409 VERSION_CONFLICT`).
- **Privacy-Minimization & Safe CSV Export**: Third-party/LangChain classification consumes only `SanitizedSuggestionInput(normalized_merchant, amount_sign, allowed_categories)`—never account IDs, raw CSV lines, or transaction references. CSV exports (`LedgerCsvExportView`) escape leading `= + - @ \t \r` in text columns (`sanitize_csv_cell`) while keeping the numeric `Signed Amount` column exact.

---

## Verified Evidence & Honest Provenance

Every claim below is labeled with strict provenance (`REPRODUCED`, `LOCAL_SINGLE_HOST_BENCHMARK`, `TARGET`, `HISTORICAL_RESUME_CLAIM`, `NOT_REPRODUCED`, `BLOCKED_EXTERNAL`) and backed by committed artifacts under `evidence/`.

| Metric / Claim | Measured / Status | Provenance | Evidence Artifact |
|---|---|---|---|
| **Backend Pytest Suite & Gate (`>=91%`)** | `15 passed in 8.25s`, **`94.06%`** (`1650` stmts, `98` miss) across `apps`, `classification`, `tasks`; `ruff check .` passed | `REPRODUCED` | [backend-coverage.txt](evidence/coverage/backend-coverage.txt) |
| **Frontend Jest + RTL Gate (`>=91%`)** | `4` suites, `22 passed`, **`98.10%` Lines / `96.46%` Stmts / `91.24%` Branches / `98.26%` Funcs** (reported separately from Pytest) | `REPRODUCED` | [frontend-coverage.json](evidence/coverage/frontend-coverage.json) |
| **Frontend Build & Static Checks** | `tsc --noEmit`, `eslint src e2e`, `vite build` passed | `REPRODUCED` | [package.json](frontend/package.json) |
| **12x90 Held-Out Classification Eval** | **`93.2%`** (`315/338`) held-out accuracy across `13` disjoint `merchant_family` groups (vs `~85%` historical claim); `0.8729` macro F1; `22.19%` `<0.700` abstention; **`100.0%`** post-review & second-import rule reuse (`75` hits) | `REPRODUCED` (vs `HISTORICAL_RESUME_CLAIM`) | [eval-report.json](evidence/categorization/eval-report.json), [confusion-matrix.md](evidence/categorization/confusion-matrix.md) |
| **Playwright + Axe WCAG 2.2 AA E2E** | `1 passed (17.1s)`, 0 console/page errors, 0 WCAG 2.2 AA violations across `1440x900`, `1024x768`, `390x844`, 200% zoom & reduced motion; `$163.25` ledger reconciliation + `NORTHWOOD MART #999` auto-approved | `REPRODUCED` | [vertical-slice.json](evidence/imports/vertical-slice.json), [playwright-report.json](evidence/ux/playwright-report.json) |
| **Locust 50-VU Smoke (Single Host)** | `1472` reqs, `0.0%` err, `133.43 req/s`, `p50=190.0 ms`, `p95=390.0 ms`, `p99=510.0 ms` | `LOCAL_SINGLE_HOST_BENCHMARK` | [load-summary.json](evidence/load/load-summary.json) |
| **Locust 150-VU Concurrency (Single Host)** | `1993` reqs, `0.0%` err, `141.62 req/s`, `p50=570.0 ms`, `p95=1200.0 ms`, `p99=6600.0 ms` | `LOCAL_SINGLE_HOST_BENCHMARK` | [analysis.md](evidence/load/analysis.md) |
| **Production 500 VU `<150 ms` p95** | Multi-worker cluster target; k6 (`load/k6/script.js`) & Locust scripts authored | `TARGET` | [locustfile.py](load/locust/locustfile.py), [script.js](load/k6/script.js) |
| **15-min vs 45-min Manual Review Time** | Controlled crossover protocol authored; human timing trials not run | `NOT_REPRODUCED` | [PROTOCOL.md](evidence/human-study/PROTOCOL.md) |
| **AWS Infrastructure & Live LLM Key** | Terraform (`infra/terraform/aws/main.tf`) authored; `apply` & live OpenAI/Anthropic calls blocked without user spend sign-off & credentials | `BLOCKED_EXTERNAL` | [CLOUD_APPROVAL.md](CLOUD_APPROVAL.md) |

---

## Local Setup & 60–90 Second Reviewer Demo

### Prerequisites
- Docker Desktop / WSL2 Docker Compose (PostgreSQL 16 on `127.0.0.1:5436`, Redis 7 on `127.0.0.1:6382`)
- Python `3.12.10` (`backend/.venv` configured via `backend/requirements.txt`)
- Node 20+ & `pnpm`

### Reproduce Tests, Eval & Live QA
```powershell
# 1. Start Postgres 16 + Redis 7, install frontend deps, migrate & seed synthetic accounts
make setup

# 2. Run ruff + Pytest (>=91%) + Jest (>=91%) + typecheck + eslint
make test

# 3. Re-generate 12x90 fixtures (seed 2026) and score disjoint merchant-family evaluation
make fixtures
make eval-categorization

# 4. Run full end-to-end live stack (Waitress + Celery threads + Vite + Locust 50/150 VU + Playwright/Axe)
.\backend\.venv\Scripts\python.exe scripts\run_live_qa.py
```

### 60–90 Second Browser Walkthrough
1. Visit `/imports/new`, download or drop `frontend/public/samples/smoke_5rows.csv` (or `sample_statement.csv`), review auto-detected column mappings, and click **Start asynchronous import**.
2. Watch `/imports/:id` transition `QUEUED -> VALIDATING -> PROCESSING -> AWAITING_REVIEW` as the Celery worker processes rows asynchronously.
3. Open `/review`, inspect `NORTHWOOD MART #402` (`-$31.40`, confidence `0.520`), switch its category to `Office Supplies` with **Remember this merchant** checked, approve `VALLEY OUTPOST #19` (`-$64.00`), and verify `/dashboard` reconciles to `$163.25` Net Expense Spend.
4. Import a second statement containing `NORTHWOOD MART #999` (`-$19.25`) to observe instant `USER_RULE` `APPROVED` classification without manual triage, then export CSV safely from `/reports`.

---

## Security, Privacy & Known Limitations
- **CSRF & Tenant Isolation**: Write requests enforce double-submit `X-CSRFToken` matching HMAC-signed HttpOnly session tokens (`apps/accounts/auth.py`). Cross-tenant lookups return `404` (`evidence/security/isolation-check.json`).
- **Live LLM Opt-In Gate**: `LangChainCategorizerAdapter` defaults to `SOLOLEDGER_LLM_PROVIDER=mock`; setting `live` without explicit spend approval fails closed with `BLOCKED_EXTERNAL`.
- **Single-Host Benchmark Ceiling**: On Windows 10 Waitress (32 threads, `connection-limit=450`), thread/GIL contention and WSL2 NAT latency drive `p95` to `390 ms` at 50 VUs and `1200 ms` at 150 VUs. Achieving the `500 VU <150 ms p95` production `TARGET` requires multi-worker Linux Gunicorn/ECS tasks with PgBouncer/RDS.
- **Interview Guide**: Deep implementation walkthroughs, ADRs, failure stories, and system designs live in [interview/SOLOLEDGER_INTERVIEW_GUIDE.md](interview/SOLOLEDGER_INTERVIEW_GUIDE.md).

