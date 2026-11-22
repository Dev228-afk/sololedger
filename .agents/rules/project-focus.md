---
trigger: always_on
---
Never upload, store, or display real bank data, real bank credentials, or real personal transaction details; use synthetic statements only.
Never invent categorization accuracy, human timing comparisons (15 vs 45 min), 500-user load latencies, or combined coverage metrics without real scoped runs.
Require backend accounting accuracy (Decimal / integer minor units, signed amounts, exact SQL sums) and working React/TypeScript async flows before UI polish.
Enforce safe CSV/PII handling: stream uploads up to 10 MB, verify MIME/content, guard formula injection on export without breaking numeric amounts, redact financial payloads from logs and default LLM providers.
All fetched server state lives in TanStack Query; Jest + React Testing Library covers frontend unit/component tests and Pytest covers backend.
Enforce confidence < 0.700 -> NEEDS_REVIEW and account-scoped tenant isolation.

