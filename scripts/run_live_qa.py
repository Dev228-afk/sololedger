#!/usr/bin/env python
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV_PY = BACKEND / ".venv" / "Scripts" / "python.exe"
VENV_CELERY = BACKEND / ".venv" / "Scripts" / "celery.exe"
VENV_WAITRESS = BACKEND / ".venv" / "Scripts" / "waitress-serve.exe"
VENV_LOCUST = BACKEND / ".venv" / "Scripts" / "locust.exe"

sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from apps.accounts.models import Account  # noqa: E402
from apps.audit.models import AuditEvent  # noqa: E402
from apps.categorization.models import MerchantCorrection  # noqa: E402
from apps.imports.models import ImportJob, ImportRow, ImportUploadPreview  # noqa: E402
from apps.transactions.models import (  # noqa: E402
    ClassificationSuggestion,
    ReviewDecision,
    Transaction,
)
from django.conf import settings  # noqa: E402
from tasks.import_tasks import process_import_job  # noqa: E402


def prepare_clean_accounts() -> None:
    from redis import Redis

    Redis.from_url(settings.CELERY_BROKER_URL).flushdb()
    acc_e2e_id = uuid.UUID("11111111-1111-5111-8111-111111111101")
    acc_warm_id = uuid.UUID("11111111-1111-5111-8111-111111111102")

    # Reset Demo Account 1 cleanly so Playwright starts on a deterministic empty workspace
    ReviewDecision.objects.filter(account_id=acc_e2e_id).delete()
    ClassificationSuggestion.objects.filter(transaction__account_id=acc_e2e_id).delete()
    Transaction.objects.filter(account_id=acc_e2e_id).delete()
    ImportRow.objects.filter(import_job__account_id=acc_e2e_id).delete()
    ImportJob.objects.filter(account_id=acc_e2e_id).delete()
    ImportUploadPreview.objects.filter(account_id=acc_e2e_id).delete()
    MerchantCorrection.objects.filter(account_id=acc_e2e_id).delete()
    AuditEvent.objects.filter(account_id=acc_e2e_id).delete()

    # Ensure Demo Account 2 has one warm 90-row imported statement for realistic Locust benchmarks
    warm_acc = Account.objects.get(id=acc_warm_id)
    if Transaction.objects.filter(account=warm_acc).count() == 0:
        sample_bytes = (ROOT / "fixtures" / "statements" / "sample_01.csv").read_bytes()
        sha = hashlib.sha256(sample_bytes).hexdigest()
        storage_key = "warm_benchmark_sample_01.csv"
        (Path(settings.SOLOLEDGER_STORAGE_DIR) / storage_key).write_bytes(sample_bytes)
        job = ImportJob.objects.create(
            account=warm_acc,
            upload_key=storage_key,
            file_sha256=sha,
            original_filename="sample_01.csv",
            mapping_json={
                "postedDateColumn": "Posted Date",
                "descriptionColumn": "Merchant",
                "amountMode": "DEBIT_CREDIT",
                "debitColumn": "Debit",
                "creditColumn": "Credit",
                "fixedCurrency": "USD",
                "transactionIdColumn": "Transaction ID",
                "dateFormat": "%Y-%m-%d",
                "decimalSeparator": ".",
                "headerRow": 1,
            },
        )
        process_import_job(str(job.id))


def wait_ready(url: str, label: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as res:
                if res.status == 200:
                    print(f"Ready: {label} ({url})")
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {label} at {url}")


def kill_proc_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            proc.terminate()
    except Exception:
        pass


def run_locust_profile(vus: int, spawn_rate: int, duration_sec: int, prefix: Path) -> dict:
    cmd = [
        str(VENV_LOCUST),
        "-f",
        str(ROOT / "load" / "locust" / "locustfile.py"),
        "--headless",
        "-u",
        str(vus),
        "-r",
        str(spawn_rate),
        "-t",
        f"{duration_sec}s",
        "--host",
        "http://127.0.0.1:8100",
        "--csv",
        str(prefix),
        "--csv-full-history",
        "--only-summary",
    ]
    res = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    stats_csv = Path(f"{prefix}_stats.csv")
    if res.returncode != 0 or not stats_csv.exists():
        raise RuntimeError(f"Locust {vus} VU run failed:\n{res.stdout}\n{res.stderr}")

    agg_row: dict = {}
    endpoints: list[dict] = []
    with stats_csv.open("r", encoding="utf-8", newline="") as fp:
        for row in csv.DictReader(fp):
            if row["Name"] == "Aggregated":
                agg_row = row
            else:
                endpoints.append(
                    {
                        "endpoint": row["Name"],
                        "requests": int(row["Request Count"]),
                        "failures": int(row["Failure Count"]),
                        "p50Ms": float(row["50%"]),
                        "p95Ms": float(row["95%"]),
                        "p99Ms": float(row["99%"]),
                        "rps": float(row["Requests/s"]),
                    }
                )

    def _num(val: str | None) -> float:
        if not val or val == "N/A":
            return 0.0
        return float(val)

    total_reqs = int(agg_row.get("Request Count", "0"))
    fail_cnt = int(agg_row.get("Failure Count", "0"))
    return {
        "vus": vus,
        "durationSec": duration_sec,
        "totalRequests": total_reqs,
        "failures": fail_cnt,
        "failureRatePct": round((fail_cnt / total_reqs * 100.0) if total_reqs else 0.0, 3),
        "requestsPerSec": round(_num(agg_row.get("Requests/s")), 2),
        "p50Ms": _num(agg_row.get("50%")),
        "p95Ms": _num(agg_row.get("95%")),
        "p99Ms": _num(agg_row.get("99%")),
        "endpoints": endpoints,
    }


def main() -> None:
    prepare_clean_accounts()
    procs: list[subprocess.Popen] = []

    env = os.environ.copy()
    env["DJANGO_DEBUG"] = "false"
    env["SOLOLEDGER_LLM_PROVIDER"] = "mock"
    pnpm_bin = Path(os.environ.get("APPDATA", "")) / "npm-global"
    env["PATH"] = f"{pnpm_bin};{env.get('PATH', '')}"

    load_dir = ROOT / "evidence" / "load"
    load_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(tempfile.mkdtemp(prefix="sololedger_qa_"))
    wsgi_log = (log_dir / "waitress.log").open("w", encoding="utf-8", buffering=1)
    celery_log = (log_dir / "celery.log").open("w", encoding="utf-8", buffering=1)
    vite_log = (log_dir / "vite.log").open("w", encoding="utf-8", buffering=1)

    try:
        wsgi_proc = subprocess.Popen(
            [
                str(VENV_WAITRESS),
                "--host=127.0.0.1",
                "--port=8100",
                "--threads=32",
                "--connection-limit=450",
                "--backlog=1024",
                "--channel-timeout=30",
                "config.wsgi:application",
            ],
            cwd=str(BACKEND),
            env=env,
            stdout=wsgi_log,
            stderr=subprocess.STDOUT,
        )
        procs.append(wsgi_proc)

        celery_proc = subprocess.Popen(
            [
                str(VENV_CELERY),
                "-A",
                "config",
                "worker",
                "-Q",
                "sololedger",
                "--pool=threads",
                "--concurrency=4",
                "--loglevel=INFO",
            ],
            cwd=str(BACKEND),
            env=env,
            stdout=celery_log,
            stderr=subprocess.STDOUT,
        )
        procs.append(celery_proc)

        vite_proc = subprocess.Popen(
            ["cmd", "/c", "pnpm run dev"],
            cwd=str(FRONTEND),
            env=env,
            stdout=vite_log,
            stderr=subprocess.STDOUT,
        )
        procs.append(vite_proc)

        wait_ready("http://127.0.0.1:8100/api/v1/health", "Django Waitress API")
        wait_ready("http://127.0.0.1:5201/dashboard", "Vite Frontend")
        # Give Celery worker threads ~2.5s to complete startup mingle and subscribe to queue 'sololedger'
        time.sleep(2.5)

        # 1. Run Locust headless smoke (50 VUs) + local max concurrency run (150 VUs) first
        #    so /engineering renders live measured load numbers during Playwright screenshot capture.
        smoke = run_locust_profile(50, 25, 12, load_dir / "locust_smoke_50vu")
        time.sleep(2.0)
        wait_ready("http://127.0.0.1:8100/api/v1/health", "Django Waitress API (pre-150VU)")
        local_conc = run_locust_profile(150, 50, 15, load_dir / "locust_local_150vu")
        if smoke["totalRequests"] <= 0 or local_conc["totalRequests"] <= 0:
            raise RuntimeError(
                f"Locust recorded zero requests (smoke={smoke['totalRequests']}, 150vu={local_conc['totalRequests']})"
            )

        summary = {
            **local_conc,
            "smoke50Vu": smoke,
            "classification": "LOCAL_SINGLE_HOST_BENCHMARK",
            "productionTarget": "500 VUs <150ms p95 (TARGET, requires multi-worker prod cluster; k6/Locust script authored in load/)",
            "hostSpec": {
                "os": platform.platform(),
                "cpuCount": os.cpu_count(),
                "server": "Waitress WSGI (32 threads, connection-limit 450, local PostgreSQL 16 in WSL2 Docker)",
            },
        }
        (load_dir / "load-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        pub_ev = FRONTEND / "public" / "evidence"
        pub_ev.mkdir(parents=True, exist_ok=True)
        (pub_ev / "load-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

        md_lines = [
            "# SoloLedger Local Load Benchmark Analysis",
            "",
            "- **Classification**: `LOCAL_SINGLE_HOST_BENCHMARK` (`TARGET` for production 500 VU / <150 ms p95; never falsely claims 500 VU prod capacity on single-laptop Waitress).",
            f"- **Host**: `{summary['hostSpec']['os']}`, `{summary['hostSpec']['cpuCount']}` logical CPUs, `{summary['hostSpec']['server']}`.",
            "",
            "## Summary Runs",
            f"- **50-VU Smoke (12s)**: `{smoke['totalRequests']}` reqs, `{smoke['requestsPerSec']}` req/s, `p50={smoke['p50Ms']} ms`, `p95={smoke['p95Ms']} ms`, `p99={smoke['p99Ms']} ms`, errors `{smoke['failureRatePct']}%`.",
            f"- **150-VU Local Concurrency (15s)**: `{local_conc['totalRequests']}` reqs, `{local_conc['requestsPerSec']}` req/s, `p50={local_conc['p50Ms']} ms`, `p95={local_conc['p95Ms']} ms`, `p99={local_conc['p99Ms']} ms`, errors `{local_conc['failureRatePct']}%`.",
            "",
            "## 150-VU Endpoint Breakdown",
        ]
        for ep in local_conc["endpoints"]:
            md_lines.append(
                f"- `{ep['endpoint']}`: `{ep['requests']}` reqs, `{ep['rps']:.1f}` req/s, `p50={ep['p50Ms']} ms`, `p95={ep['p95Ms']} ms`, `p99={ep['p99Ms']} ms`, failures `{ep['failures']}`"
            )
        (load_dir / "analysis.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))

        # 2. Run full Playwright + Axe + 3-viewport E2E suite against live Celery & Postgres
        time.sleep(1.5)
        wait_ready("http://127.0.0.1:8100/api/v1/health", "Django Waitress API (pre-E2E)")
        e2e_cmd = ["cmd", "/c", "pnpm run test:e2e"]
        e2e_res = subprocess.run(e2e_cmd, cwd=str(FRONTEND), env=env)
        if e2e_res.returncode != 0:
            raise RuntimeError(f"Playwright E2E failed with code {e2e_res.returncode}")
    finally:
        for p in procs:
            kill_proc_tree(p)
        for fp in (wsgi_log, celery_log, vite_log):
            try:
                fp.close()
            except Exception:
                pass
        print(f"Runtime logs written under: {log_dir}")


if __name__ == "__main__":
    main()

