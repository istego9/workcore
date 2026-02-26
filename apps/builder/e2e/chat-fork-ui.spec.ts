import { expect, test } from '@playwright/test';

test('chat fork page renders controls', async ({ page }) => {
  await page.goto('/chat-fork.html');
  test.skip((await page.title()) !== 'Chat Fork', 'chat-fork page is not available at current E2E base URL');
  await expect(page.getByText('API URL')).toBeVisible();
  await expect(page.getByText('Workflow ID')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Connect' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Mic' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send' })).toBeVisible();
});

test('chat fork embed mode hides setup panel', async ({ page }) => {
  await page.goto('/chat-fork.html?embed=1');
  test.skip((await page.title()) !== 'Chat Fork', 'chat-fork page is not available at current E2E base URL');
  await expect(page.getByText('Thread')).toBeVisible();
  await expect(page.getByText('API URL')).toHaveCount(0);
});
