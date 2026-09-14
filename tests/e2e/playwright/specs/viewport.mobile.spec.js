const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('./_navigate');

test.describe('Viewport Mobile (375x812)', () => {
  test.use({
    viewport: { width: 375, height: 812 },
    isMobile: true,
    hasTouch: true,
  });

  async function expectNoHorizontalOverflow(page) {
    const overflowPx = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    // Allow tiny sub-pixel/layout jitter on mobile remote environments
    expect(overflowPx).toBeLessThanOrEqual(3);
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

  async function expectMobileBottomNav(page) {
    // Bottom nav is in a fixed Paper at bottom of page - use CSS selector
    const bottomNav = page.locator('.MuiPaper-root:has(.MuiBottomNavigation-root)');
    await expect(bottomNav.getByRole('button', { name: 'Dashboard', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'Device', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'Run', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'Heatmap', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'Settings', exact: true })).toBeVisible();
  }

  test('Dashboard uses compact mobile layout', async ({ page }) => {
    await gotoWithAutoSign(page, '/');
    await skipIfNotAuthenticated(page);

    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expectMobileBottomNav(page);
    await expect(page.getByLabel('Ask AI')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });

  test('Device Control fits mobile viewport', async ({ page }) => {
    await gotoWithAutoSign(page, '/device-control');
    await skipIfNotAuthenticated(page);

    await expect(page.getByRole('heading', { name: 'Device' })).toBeVisible();
    await expectMobileBottomNav(page);
    await expect(page.getByLabel('Ask AI')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });

  test('Heatmap renders compact view', async ({ page }) => {
    await gotoWithAutoSign(page, '/monitoring/heatmap');
    await skipIfNotAuthenticated(page);

    await expect(page.getByRole('heading', { name: '24h Heatmap' })).toBeVisible();
    await expectMobileBottomNav(page);
    await expect(page.getByLabel('Ask AI')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });

  test('Run Tests fits mobile viewport', async ({ page }) => {
    await gotoWithAutoSign(page, '/test-execution/run-tests');
    await skipIfNotAuthenticated(page);

    await expect(page.getByRole('heading', { name: 'Run Tests' })).toBeVisible();

    await expectMobileBottomNav(page);
    await expect(page.getByLabel('Ask AI')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });
});
