# SoloLedger — Architecture Decisions

1. **Python 3.12 Virtualenv**: Explicitly pin Python 3.12.10 (`backend/.venv`) because Windows default Python 3.14 lacks ecosystem wheels for Django/Psycopg/Celery/LangChain dependencies.
2. **Exact Signed Money**: Store `bigint` minor units in PostgreSQL and parse/format strictly with Python `Decimal`, emitting decimal strings in JSON and never using floating-point math.
3. **Broker-Gap Safe Dispatch**: Persist `ImportJob(QUEUED, enqueued_at=None)`, enqueue Celery inside `transaction.on_commit`, and run `recover_stranded_imports` to catch `on_commit` dispatch failures.
4. **Windows Celery Pool**: Use `--pool=threads --concurrency=4` when launching Celery natively on Windows; Docker/Linux deployment uses `--pool=prefork`.
5. **OpenAPI -> TypeScript Codegen**: Export schema via `drf-spectacular` and generate `frontend/src/api/schema.d.ts` via `openapi-typescript`.
6. **Test Runners**: Backend uses `pytest` + `pytest-cov`; frontend uses `Jest + React Testing Library` (explicitly required by V2) plus `Playwright` for E2E/visual QA.

