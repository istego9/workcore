import { expect, test } from '@playwright/test';

test('integration kit modal exposes shareable URLs', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    const item = document.querySelector('[data-testid="open-integration-kit"]');
    if (item instanceof HTMLElement) {
      item.click();
    }
  });

  const modal = page.getByRole('dialog', { name: 'Agent integration kit' });
  await expect(modal).toBeVisible();

  const shareableUrl = modal.getByLabel('Shareable URL');
  await expect(shareableUrl).toHaveValue(/agent-integration-kit$/);

  await expect(modal.getByRole('link', { name: 'JSON bundle' })).toHaveAttribute(
    'href',
    /agent-integration-kit\.json$/
  );
  await expect(modal.getByRole('link', { name: 'Integration test UI' })).toHaveAttribute(
    'href',
    /agent-integration-test$/
  );
  await expect(modal.getByRole('link', { name: 'OpenAPI contract' })).toHaveAttribute(
    'href',
    /openapi\.yaml$/
  );
  await expect(modal.getByRole('link', { name: 'Workflow draft JSON schema' })).toHaveAttribute(
    'href',
    /workflow-draft\.schema\.json$/
  );
});
