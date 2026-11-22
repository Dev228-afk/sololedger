import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  vus: Number(__ENV.K6_VUS || 500),
  duration: __ENV.K6_DURATION || '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<150'],
  },
};

const BASE = __ENV.BASE_URL || 'http://127.0.0.1:8100';
const WARM_ACCOUNT_ID = '11111111-1111-5111-8111-111111111102';

export function setup() {
  const res = http.post(
    `${BASE}/api/v1/demo/session`,
    JSON.stringify({ accountId: WARM_ACCOUNT_ID }),
    { headers: { 'Content-Type': 'application/json' } },
  );
  check(res, { 'demo session ok': (r) => r.status === 200 });
  return { cookie: res.headers['Set-Cookie'] };
}

export default function () {
  const r1 = http.get(`${BASE}/api/v1/transactions?limit=50`);
  check(r1, { 'transactions 200': (r) => r.status === 200 });

  const r2 = http.get(
    `${BASE}/api/v1/reports/monthly?fromMonth=2026-01&toMonth=2026-12&currency=USD`,
  );
  check(r2, { 'report 200': (r) => r.status === 200 });

  sleep(0.2);
}

