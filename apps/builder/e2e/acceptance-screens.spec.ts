import { devices, expect, test } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const baseUrl = (process.env.E2E_BASE_URL || 'http://workcore.build').replace(/\/+$/, '');
const targetUrl = process.env.ACCEPTANCE_URL || `${baseUrl}/?e2e=1`;
const outputDir = process.env.ACCEPTANCE_SCREENSHOTS_DIR || '';
const waitSelector = (process.env.ACCEPTANCE_SELECTOR || '').trim();
const waitMsRaw = process.env.ACCEPTANCE_WAIT_MS || '3000';
const parsedWaitMs = Number.parseInt(waitMsRaw, 10);
const waitMs = Number.isNaN(parsedWaitMs) ? 3000 : Math.max(0, parsedWaitMs);
const fullPage = process.env.ACCEPTANCE_FULL_PAGE === '1';

const waitForReady = async (page: import('@playwright/test').Page) => {
  if (waitSelector) {
    await page.waitForSelector(waitSelector);
  }
  if (waitMs > 0) {
    await page.waitForTimeout(waitMs);
  }
};

test('capture acceptance screenshots (desktop and mobile)', async ({ browser, page }) => {
  test.skip(!outputDir, 'ACCEPTANCE_SCREENSHOTS_DIR is required');

  await fs.mkdir(outputDir, { recursive: true });
  const desktopPath = path.join(outputDir, 'desktop.png');
  const mobilePath = path.join(outputDir, 'mobile.png');

  await page.goto(targetUrl);
  await waitForReady(page);
  await page.screenshot({ path: desktopPath, fullPage });

  const mobileContext = await browser.newContext({ ...devices['iPhone 11'] });
  try {
    const mobilePage = await mobileContext.newPage();
    await mobilePage.goto(targetUrl);
    await waitForReady(mobilePage);
    await mobilePage.screenshot({ path: mobilePath, fullPage });
  } finally {
    await mobileContext.close();
  }

  const desktopStat = await fs.stat(desktopPath);
  const mobileStat = await fs.stat(mobilePath);
  expect(desktopStat.size).toBeGreaterThan(0);
  expect(mobileStat.size).toBeGreaterThan(0);
});
