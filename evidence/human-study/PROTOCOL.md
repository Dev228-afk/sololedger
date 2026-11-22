# Human Review Time Comparison Protocol (`NOT_REPRODUCED`)

- **Claim Under Review**: `~15 min automated review vs 45 min manual spreadsheet categorization` (`HISTORICAL_RESUME_CLAIM`).
- **Status**: **`NOT_REPRODUCED`** (no multi-participant human timing sessions were conducted or simulated cleanly during software build verification).
- **Policy**: Software execution timings and automated Playwright suite durations do **not** measure human cognitive triage speed and must never be misrepresented as validating the 15-vs-45-minute ratio.

## Controlled Study Protocol (When Executed With Human Participants)
1. **Sample Size & Crossover Design**: Minimum `N = 12` freelance/bookkeeping participants assigned via balanced AB/BA crossover across two disjoint 90-transaction synthetic statements from `fixtures/statements/`.
2. **Arm A (Spreadsheet Baseline)**: Categorize 90 transactions into the 13 SoloLedger categories using a clean spreadsheet template with category data validation.
3. **Arm B (SoloLedger Assisted)**: Upload the 90-transaction statement into `/imports/new`, await worker categorization, triage the `NEEDS_REVIEW` (`< 0.700`) subset inside `/review` (with `"Remember this merchant"` enabled), and inspect `/reports`.
4. **Measured Endpoints**: Active human categorization + reconciliation elapsed minutes (excluding computer boot), post-task error count against `fixtures/ground_truth.csv`, and NASA-TLX workload score.
5. **Prohibition**: Never generate fake participant logs or extrapolated "human times" from Playwright runs.

