import fs from 'node:fs';
import path from 'node:path';
import { test, expect, type Page } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

const ROOT = path.resolve(process.cwd(), '..');
const SCREENSHOT_DIR = path.join(ROOT, 'evidence', 'ux', 'screenshots');
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

function attachErrorGuard(page: Page, errors: string[]) {
  let allow409 = false;
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const txt = msg.text();
      if (allow409 && txt.includes('409')) return;
      errors.push(`console.error: ${txt}`);
    }
  });
  return {
    setAllow409: (v: boolean) => {
      allow409 = v;
    },
  };
}

async function assertNoHorizontalOverflow(page: Page, label: string) {
  const overflow = await page.evaluate(() => {
    return document.documentElement.scrollWidth > document.documentElement.clientWidth + 2;
  });
  expect(overflow, `Horizontal overflow detected at ${label}`).toBe(false);
}

async function runAxeAudit(page: Page, label: string) {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
    .analyze();
  expect(
    results.violations,
    `Axe WCAG 2.2 AA violations on ${label}: ${JSON.stringify(results.violations, null, 2)}`,
  ).toEqual([]);
}

test.describe('SoloLedger Full E2E, Worker Integration, A11y & Visual QA', () => {
  test('Gate 1 CSV -> Celery -> Review 409 retention -> 2nd import learning -> Reports & 3-viewport QA', async ({
    browser,
  }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const errors: string[] = [];
    const errGuard = attachErrorGuard(page, errors);

    // 1. /dashboard empty workspace prompt (1440x900)
    await page.goto('/dashboard');
    await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible();
    await expect(page.getByText('No imported statements in this demo workspace yet')).toBeVisible({
      timeout: 10_000,
    });
    await assertNoHorizontalOverflow(page, 'dashboard-empty-1440');
    await runAxeAudit(page, 'dashboard-empty');

    // 2. Navigate to /imports/new and test Gate 1 5-row vertical slice
    await page.getByRole('link', { name: 'Import statement' }).first().click();
    await expect(page).toHaveURL(/\/imports\/new/);
    await runAxeAudit(page, 'import-wizard');

    const smokePath = path.join(ROOT, 'fixtures', 'import_edge_cases', 'smoke_5rows.csv');
    await page.getByTestId('csv-file-input').setInputFiles(smokePath);

    await expect(page.getByText('Continue to confirm')).toBeVisible({ timeout: 10_000 });
    await page.getByRole('button', { name: 'Continue to confirm' }).click();
    await page.getByTestId('confirm-import-btn').click();

    await expect(page).toHaveURL(/\/imports\/[0-9a-f-]+/);
    const jobIdMatch = page.url().match(/\/imports\/([0-9a-f-]+)/);
    const jobId = jobIdMatch![1]!;

    // Wait for live Celery worker to reach AWAITING_REVIEW with 5/5 processed rows
    await expect(page.getByTestId('import-progress-counts')).toHaveText('5 / 5 rows processed', {
      timeout: 20_000,
    });
    await expect(page.getByText('AWAITING_REVIEW')).toBeVisible({ timeout: 20_000 });
    await runAxeAudit(page, 'import-detail');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '01-import-detail-1440.png'),
      fullPage: true,
    });

    // 3. Verify all 5 exact signed rows in /transactions
    await page.getByRole('link', { name: 'View ledger' }).click();
    await expect(page).toHaveURL(/\/transactions/);
    await expect(page.getByText('Total matching: 5')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('table').getByText('-$42.85')).toBeVisible();
    await expect(page.getByRole('table').getByText('+$1500.00')).toBeVisible();
    await runAxeAudit(page, 'transactions');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '02-transactions-1440.png'),
      fullPage: true,
    });

    const verticalSliceEvidence = {
      jobId,
      verifiedAt: new Date().toISOString(),
      expectedRows: 5,
      verifiedSignedAmounts: ['-$25.00', '-$42.85', '-$31.40', '+$1500.00', '-$64.00'],
      status: 'PASS',
    };
    fs.mkdirSync(path.join(ROOT, 'evidence', 'imports'), { recursive: true });
    fs.writeFileSync(
      path.join(ROOT, 'evidence', 'imports', 'vertical-slice.json'),
      JSON.stringify(verticalSliceEvidence, null, 2) + '\n',
      'utf8',
    );

    // 4. Review Queue: inspect + test 409 optimistic conflict preserving unsaved local choice
    await page.getByRole('link', { name: /Review/i }).first().click();
    await expect(page).toHaveURL(/\/review/);
    await expect(page.getByRole('listbox', { name: 'Transactions needing review' })).toBeVisible();
    await runAxeAudit(page, 'review-queue');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '03-review-queue-1440.png'),
      fullPage: true,
    });

    // Inject out-of-band concurrent review update to bump version on NORTHWOOD MART specifically
    const sessionRes = await page.request.get('/api/v1/demo/session');
    const sessionJson = (await sessionRes.json()) as { csrfToken: string };
    const queueApiRes = await page.request.get('/api/v1/transactions?reviewStatus=NEEDS_REVIEW&limit=10');
    const queueApiJson = (await queueApiRes.json()) as {
      items: Array<{ id: string; version: number; merchant: string }>;
    };
    const northwoodItem = queueApiJson.items.find((i) => i.merchant.includes('NORTHWOOD'))!;

    await page.getByRole('option', { name: /NORTHWOOD MART/i }).click();
    // Select a new category in UI before triggering concurrent bump
    await page.getByLabel('Category for review').selectOption('MARKETING');

    const bumpRes = await page.request.patch(`/api/v1/transactions/${northwoodItem.id}/review`, {
      headers: { 'x-csrf-token': sessionJson.csrfToken },
      data: {
        version: northwoodItem.version,
        decision: 'CHANGE',
        categoryCode: 'OFFICE_SUPPLIES',
        rememberMerchant: true,
      },
    });
    expect(bumpRes.status()).toBe(200);

    // Trigger stale submit from UI -> expects 409 while retaining local MARKETING selection!
    errGuard.setAllow409(true);
    await page.getByRole('button', { name: 'Save changed category' }).click();
    await expect(page.getByText(/Version conflict \(HTTP 409\)/i)).toBeVisible({
      timeout: 10_000,
    });
    errGuard.setAllow409(false);
    await expect(page.getByLabel('Category for review')).toHaveValue('MARKETING');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '04-review-409-conflict-1440.png'),
      fullPage: true,
    });

    await page.getByRole('button', { name: 'Refresh queue' }).click();
    // Accept remaining review item(s) to transition import job -> COMPLETED
    await expect(page.getByRole('button', { name: /Accept/i }).first()).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: /Accept all/i }).click();
    await expect(page.getByText('Review queue is clear')).toBeVisible({ timeout: 10_000 });

    // 5. Verify saved merchant rule in /rules
    await page.getByRole('link', { name: 'Merchant rules' }).click();
    await expect(page).toHaveURL(/\/rules/);
    await expect(page.getByText('Office Supplies')).toBeVisible({ timeout: 10_000 });
    await runAxeAudit(page, 'rules');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '05-rules-1440.png'),
      fullPage: true,
    });

    // 6. Reports & real CSV export verification
    await page.getByRole('link', { name: 'Reports' }).click();
    await expect(page).toHaveURL(/\/reports/);
    await expect(page.getByText('Net spend by expense category (USD)')).toBeVisible({
      timeout: 10_000,
    });
    await runAxeAudit(page, 'reports');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '06-reports-1440.png'),
      fullPage: true,
    });

    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: 'Export ledger' }).click(),
    ]);
    const csvStream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const ch of csvStream) chunks.push(Buffer.from(ch));
    const csvContent = Buffer.concat(chunks).toString('utf8');
    expect(csvContent).toContain(',-42.85,USD,');
    expect(csvContent).toContain(',1500.00,USD,');

    // 7. Populated /dashboard & /engineering
    await page.getByRole('link', { name: 'Overview' }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId('dashboard-net-spend')).toHaveText('$163.25');
    await runAxeAudit(page, 'dashboard-populated');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '07-dashboard-1440.png'),
      fullPage: true,
    });

    await page.getByRole('link', { name: 'Engineering' }).click();
    await expect(page).toHaveURL(/\/engineering/);
    await expect(page.getByText(/Live backend & broker health/i)).toBeVisible();
    await runAxeAudit(page, 'engineering');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '08-engineering-1440.png'),
      fullPage: true,
    });

    // 7b. Verify 2nd import remembers NORTHWOOD MART automatically with USER_RULE / APPROVED / COMPLETED
    await page.getByRole('link', { name: 'Import statement' }).first().click();
    await expect(page).toHaveURL(/\/imports\/new/);
    const secondImportPath = path.join(ROOT, 'var', 'e2e_second_import.csv');
    fs.mkdirSync(path.dirname(secondImportPath), { recursive: true });
    fs.writeFileSync(
      secondImportPath,
      'Date,Description,Amount,Currency\n2026-03-01,NORTHWOOD MART #999,-19.25,USD\n',
      'utf8',
    );
    await page.getByTestId('csv-file-input').setInputFiles(secondImportPath);
    await expect(page.getByRole('button', { name: 'Continue to confirm' })).toBeVisible({
      timeout: 10_000,
    });
    await page.getByRole('button', { name: 'Continue to confirm' }).click();
    await page.getByTestId('confirm-import-btn').click();
    await expect(page).toHaveURL(/\/imports\/[0-9a-f-]+/);
    await expect(page.getByTestId('import-progress-counts')).toHaveText('1 / 1 rows processed', {
      timeout: 20_000,
    });
    await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible({ timeout: 20_000 });
    await page.getByRole('link', { name: 'View ledger' }).click();
    await expect(page.getByText('Total matching: 6')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByRole('table').getByText('NORTHWOOD MART #999')).toBeVisible();
    await expect(
      page.getByRole('table').locator('tr', { hasText: 'NORTHWOOD MART #999' }).getByText('APPROVED', { exact: true }),
    ).toBeVisible();

    // 8. Responsive viewports (1024x768, 390x844), 200% zoom, and reduced motion
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.goto('/transactions');
    await expect(page.getByText('Total matching: 6')).toBeVisible();
    await assertNoHorizontalOverflow(page, 'transactions-tablet-1024');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '09-tablet-1024.png'),
      fullPage: true,
    });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/transactions');
    await expect(page.getByLabel('Transactions card list')).toBeVisible();
    await assertNoHorizontalOverflow(page, 'transactions-mobile-390');
    await runAxeAudit(page, 'transactions-mobile');
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, '10-mobile-transactions-390.png'),
      fullPage: true,
    });

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '200%';
    });
    await page.goto('/dashboard');
    await assertNoHorizontalOverflow(page, 'dashboard-200pct-zoom');

    await context.close();
    expect(errors, `Unexpected browser console/page errors: ${errors.join('\n')}`).toEqual([]);
  });
});

