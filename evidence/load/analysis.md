# SoloLedger Local Load Benchmark Analysis

- **Classification**: `LOCAL_SINGLE_HOST_BENCHMARK` (`TARGET` for production 500 VU / <150 ms p95; never falsely claims 500 VU prod capacity on single-laptop Waitress).
- **Host**: `Windows-10-10.0.19045-SP0`, `16` logical CPUs, `Waitress WSGI (32 threads, connection-limit 450, local PostgreSQL 16 in WSL2 Docker)`.

## Summary Runs
- **50-VU Smoke (12s)**: `1472` reqs, `133.43` req/s, `p50=190.0 ms`, `p95=390.0 ms`, `p99=510.0 ms`, errors `0.0%`.
- **150-VU Local Concurrency (15s)**: `1993` reqs, `141.62` req/s, `p50=570.0 ms`, `p95=1200.0 ms`, `p99=6600.0 ms`, errors `0.0%`.

## 150-VU Endpoint Breakdown
- `/api/v1/demo/session`: `150` reqs, `10.7` req/s, `p50=3600.0 ms`, `p95=6900.0 ms`, `p99=7300.0 ms`, failures `0`
- `/api/v1/health`: `177` reqs, `12.6` req/s, `p50=670.0 ms`, `p95=1200.0 ms`, `p99=1300.0 ms`, failures `0`
- `/api/v1/imports`: `328` reqs, `23.3` req/s, `p50=530.0 ms`, `p95=1100.0 ms`, `p99=1200.0 ms`, failures `0`
- `/api/v1/merchant-rules`: `163` reqs, `11.6` req/s, `p50=520.0 ms`, `p95=990.0 ms`, `p99=1100.0 ms`, failures `0`
- `/api/v1/reports/monthly`: `508` reqs, `36.1` req/s, `p50=530.0 ms`, `p95=1100.0 ms`, `p99=1100.0 ms`, failures `0`
- `/api/v1/transactions`: `667` reqs, `47.4` req/s, `p50=560.0 ms`, `p95=1100.0 ms`, `p99=1200.0 ms`, failures `0`
