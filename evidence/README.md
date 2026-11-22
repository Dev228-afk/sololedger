# SoloLedger — Evidence Provenance Policy

Each artifact bundle lives under `evidence/<topic>/<run-id>/` with `{commit.txt, environment.json, config.json, raw.json, summary.json, limitations.md}`.

## Claim Classification
- `HISTORICAL_RESUME_CLAIM`: `~85%` accuracy, `15 vs 45 min` human review time, `500 concurrent users < 150 ms`, `91%` coverage.
- `REPRODUCED`: Verified against held-out fixture split, scoped Pytest/Jest coverage runs, or actual Locust load runs.
- `NOT_REPRODUCED` / `NOT_MEASURED`: Explicitly reserved for human timing comparisons (`evidence/human-study/PROTOCOL.md`) and any unachieved hardware-limited targets.
- `BLOCKED_EXTERNAL`: Live AWS provisioning and live LLM API calls without user credentials/budget approval.

