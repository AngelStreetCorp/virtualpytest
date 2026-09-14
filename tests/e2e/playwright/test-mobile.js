const { test, expect, chromium } = require('@playwright/test');

(async () => {
  const browser = await chromium.launch({ 
    headless: true,
    args: ['--ignore-certificate-errors']
  });
  
  const context = await browser.newContext({ 
    viewport: { width: 375, height: 812 },
    isMobile: true,
    hasTouch: true,
    ignoreHTTPSErrors: true
  });
  
  const page = await context.newPage();
  
  // Navigate
  await page.goto(`${process.env.E2E_BASE_URL || 'http://localhost:5073'}/test-execution/run-tests?auto_signed=${process.env.E2E_AUTO_SIGN_TOKEN || 'test'}`, { 
    waitUntil: 'domcontentloaded',
    timeout: 30000 
  });
  
  // Wait for React
  await page.waitForTimeout(3000);
  
  // Check heading
  const heading = page.getByRole('heading', { name: 'Run Tests' });
  try {
    await heading.waitFor({ state: 'visible', timeout: 10000 });
    console.log('Heading is visible');
  } catch (e) {
    console.log('Heading NOT visible');
  }
  
  // Wait more for MUI
  await page.waitForTimeout(1000);
  
  // Check Advanced options
  const advanced = page.getByText('Advanced options');
  const count = await advanced.count();
  console.log('Advanced options count:', count);
  
  await browser.close();
})();
