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
    // Bottom nav is in a fixed Paper at bottom of page - use CSS selector.
    // The fifth slot is "More" (a menu), not "Settings": /settings is not even a route at
    // this width — it answers the SPA's 404 page. Verified against the deployed site at
    // 375x812, 2026-09-16.
    const bottomNav = page.locator('.MuiPaper-root:has(.MuiBottomNavigation-root)');
    await expect(bottomNav.getByRole('button', { name: 'Dashboard', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'Device', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'Run', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'Heatmap', exact: true })).toBeVisible();
    await expect(bottomNav.getByRole('button', { name: 'More', exact: true })).toBeVisible();
  }

  test('Dashboard uses compact mobile layout', async ({ page }) => {
    await gotoWithAutoSign(page, '/');
    await skipIfNotAuthenticated(page);

    // The Dashboard renders the standard <PageTitle title="Dashboard" /> even at
    // mobile width — the heading itself is what says "this is the dashboard,
    // rendered". (An earlier version of the test asserted a "Hosts" section heading
    // because the mobile view used to open straight on the Hosts tab; the Dashboard
    // Tabs refactor made Overview the default tab, so the "Hosts" heading is no
    // longer on first paint at any width.)
    await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
    await expectMobileBottomNav(page);
    await expect(page.getByLabel('Ask AI')).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  });

  test('Device Control fits mobile viewport', async ({ page }) => {
    await gotoWithAutoSign(page, '/device-control');
    await skipIfNotAuthenticated(page);

    // No heading on this page at mobile width: the content is device cards, and there are
    // none when no host exposes an AV device. The two filters above them are the page's own
    // controls and render either way.
    // After 8a352bf75 (fix(device-control): compact rows in the targets dropdown) the
    // targets filter became a Button (chip-style control) at every width; the Models filter
    // is still a multi-Select. Match each control by its role, not by a shared combobox list.
    await expect(page.getByRole('button').filter({ hasText: 'All Targets' })).toBeVisible();
    await expect(page.getByRole('combobox').filter({ hasText: 'All Models' })).toBeVisible();
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
