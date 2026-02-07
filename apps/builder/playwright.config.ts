import { defineConfig } from '@playwright/test';
import fs from 'node:fs';

const baseURL = process.env.E2E_BASE_URL || 'http://workcore.build';
const chromiumPath =
  process.env.E2E_CHROMIUM_PATH || '/Applications/Chromium.app/Contents/MacOS/Chromium';
const useSystemChromium = fs.existsSync(chromiumPath);
const workers = process.env.E2E_WORKERS ? Math.max(1, Number(process.env.E2E_WORKERS)) : 2;

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  workers,
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1280, height: 800 },
    ...(useSystemChromium ? { launchOptions: { executablePath: chromiumPath } } : {})
  }
});
