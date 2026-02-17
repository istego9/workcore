import { expect, test } from '@playwright/test';

test('chatkit local page renders controls', async ({ page }) => {
  await page.goto('/chatkit.html');
  await expect(page.getByText('API URL')).toBeVisible();
  await expect(page.getByText('Domain key')).toBeVisible();
  await expect(page.getByText('Workflow ID')).toBeVisible();
  await expect(page.getByText('Project ID')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Connect' })).toBeVisible();
  await expect(page.locator('openai-chatkit')).toBeVisible();
});
