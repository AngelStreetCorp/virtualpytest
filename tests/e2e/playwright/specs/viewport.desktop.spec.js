const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

test.describe('Viewport Desktop (1280x800)', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  async function expectNoHorizontalOverflow(page) {
    const overflowPx = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    // Allow tiny sub-pixel/layout jitter from fixed header controls on remote env.
    expect(overflowPx).toBeLessThanOrEqual(5);
  }

  // Check if redirected to login page - if so, skip the test
  // This handles both server-side and client-side redirects
  async function skipIfNotAuthenticated(page, options = {}) {
    const { timeout = 5000 } = options;
    
    // First check immediate URL (handles server-side redirect)
    let url = page.url();
    if (url.includes('/login') || url.includes('signin')) {
      test.skip(true, 'Not authenticated - redirected to login');
      return;
    }
    
    // Wait a bit for potential client-side redirect after React hydration
    // Then check URL again
    await page.waitForTimeout(timeout);
    url = page.url();
    if (url.includes('/login') || url.includes('signin')) {
      test.skip(true, 'Not authenticated - client-side redirect to login');
      return;
    }
  }

  const cases = [
    { name: 'Dashboard', path: '/', heading: { role: 'heading', name: 'Dashboard' } },
    { name: 'Device Control', path: '/device-control', heading: { role: 'heading', name: 'Device' } },
    { name: 'Heatmap', path: '/monitoring/heatmap', heading: { role: 'heading', name: '24h Heatmap' } },
    { name: 'Incidents', path: '/monitoring/incidents', heading: { role: 'heading', name: 'Incident Summary' } },
    { name: 'Run Tests', path: '/test-execution/run-tests', heading: { role: 'heading', name: 'Run Tests' } },
    { name: 'Campaigns', path: '/run/build', heading: { role: 'heading', name: 'Build Campaign' } },
    { name: 'Deployments', path: '/run/deployments', heading: { role: 'heading', name: 'Monitor Tests' } },
    { name: 'Requirements', path: '/test-plan/requirements', heading: { role: 'heading', name: 'Requirements' } },
    // Coverage page - skipped in CI until deployed (no 'Test Coverage Dashboard' heading in page)
    // { name: 'Coverage', path: '/test-plan/coverage', heading: { role: 'heading', name: 'Test Coverage Dashboard' } },
  ];

  for (const pageCase of cases) {
    test(`${pageCase.name} layout has no horizontal overflow`, async ({ page }) => {
      await gotoWithAutoSign(page, pageCase.path);
      await skipIfNotAuthenticated(page);
      const { role, ...headingOptions } = pageCase.heading;
      await expect(page.getByRole(role, headingOptions)).toBeVisible();
      await expectNoHorizontalOverflow(page);
    });
  }

  test('API docs layout has no horizontal overflow', async ({ page }) => {
    await gotoWithAutoSign(page, '/docs/api');
    await skipIfNotAuthenticated(page);
    await expect(page.getByRole('heading', { name: /API Documentation/i })).toBeVisible();
    await expect(page.locator('iframe')).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });
});
