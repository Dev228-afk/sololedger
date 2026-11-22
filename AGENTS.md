# SoloLedger — Agent Operating Contract

1. **Source of Truth**: [PROJECT_CONSTITUTION.md](file:///C:/Users/devan/OneDrive/Desktop/apple_ads/sololedger/PROJECT_CONSTITUTION.md) (verbatim copy of `02_SoloLedger_Antigravity_Implementation_Plan_V2.md`, SHA-256 `3B90D5C374033213BAA65A06E9E4968567DADF64B27DB50E88947B2BE47229FC`).
2. **Runtime Rules**:
   - Python **MUST** use `C:\Users\devan\AppData\Local\Programs\Python\Python312\python.exe` to build `backend/.venv`. Never run global `pip install`.
   - Local Windows Celery worker runs with `--pool=threads --concurrency=4` (Docker/Linux uses `--pool=prefork`).
   - Postgres 16 runs on host port `5436`; Redis 7 runs on host port `6382` (NEVER `6379`).
   - Frontend uses React/Vite/strict TS + **Jest + React Testing Library** + Playwright.
3. **Accounting & Async Contracts**:
   - Integer minor units (`bigint`) in Postgres, `Decimal` in Python parser/classifier, exact decimal strings in JSON (`"-42.85"`), `netSpend = -SUM(amount_minor)` for `EXPENSE` categories without clamping refunds.
   - `transaction.on_commit` dispatches Celery task AFTER DB transaction commits; periodic/command recovery handles broker outage gaps (`enqueued_at IS NULL`).
   - Confidence `< 0.700` or `None` -> `NEEDS_REVIEW`; `>= 0.700` -> `SUGGESTED`.
4. **Tracking**: Update `TASKS.md`, `IMPLEMENTATION_STATUS.md`, and `NEXT_AGENT_HANDOFF.md` at every task boundary.
