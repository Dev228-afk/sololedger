from __future__ import annotations

from locust import HttpUser, between, task

WARM_ACCOUNT_ID = "11111111-1111-5111-8111-111111111102"


class SoloLedgerApiUser(HttpUser):
    """Locust benchmark user targeting warm ordinary read/report endpoints (excludes CSV ingestion)."""

    wait_time = between(0.05, 0.25)

    def on_start(self) -> None:
        self.client.post(
            "/api/v1/demo/session",
            json={"accountId": WARM_ACCOUNT_ID},
            name="/api/v1/demo/session",
        )

    @task(4)
    def list_transactions(self) -> None:
        self.client.get("/api/v1/transactions?limit=50", name="/api/v1/transactions")

    @task(3)
    def monthly_report(self) -> None:
        self.client.get(
            "/api/v1/reports/monthly?fromMonth=2026-01&toMonth=2026-12&currency=USD",
            name="/api/v1/reports/monthly",
        )

    @task(2)
    def list_imports(self) -> None:
        self.client.get("/api/v1/imports?limit=20", name="/api/v1/imports")

    @task(1)
    def list_rules(self) -> None:
        self.client.get("/api/v1/merchant-rules?limit=50", name="/api/v1/merchant-rules")

    @task(1)
    def health_check(self) -> None:
        self.client.get("/api/v1/health", name="/api/v1/health")

