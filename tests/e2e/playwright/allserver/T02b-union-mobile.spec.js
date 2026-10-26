/**
 * TASK-113 / T02-mobile — ALL union at 390×844.
 *
 * The TASK-113 PR-C row was duplicated to the mobile `ServerSelector`
 * (rendered through `MobileServerBar` for `isMobile && showsServerPicker`)
 * AND the desktop `ScopePicker` (BUG-0564). The desktop path is T02;
 * this is the same probe at a phone viewport.
 *
 * At 390×844 the dashboard's chrome is the mobile bar:
 *   - The "Add widget" / "More" / user-menu row is at the top
 *   - MobileServerBar mounts above the row (shows the server chip)
 *   - Clicking the chip opens a MuiSelect dropdown (not a Popover)
 *
 * The row text "All servers" is the same, the wiring is through the
 * same useServerPicker hook, but the rendered control is MuiSelect
 * (not MuiPopover). The PoC opens the chip and asserts the row is
 * present + clickable.
 */
const { test, expect } = require('@playwright/test');
const { gotoWithAutoSign } = require('../specs/_navigate');

test.use({ viewport: { width: 390, height: 844 } });

test('T02-mobile ALL — picker shows the "All servers" row at 390×844', async ({ page }) => {
  await gotoWithAutoSign(page, '/');

  // At a phone viewport (390×844), the mobile chrome is in effect:
  // the dashboard widgets render, and the server picker is a
  // MuiSelect (role="combobox"), not a ButtonBase (aria-haspopup).
  // The accessibility name is the server's display name.
  const chip = page.locator('[role="combobox"]').first();
  await expect(chip).toBeVisible({ timeout: 15_000 });

  // The "All servers" row should already be in the option list
  // before we click (MuiSelect renders its options inside the
  // hidden Menu, but accessible text is exposed via aria-controls).
  // Easier path: open the menu and assert the option is visible.
  await chip.click();
  const listbox = page.locator('[role="listbox"]').first();
  await expect(listbox).toBeVisible();

  // The "All servers" row is present in the MuiSelect menu.
  await expect(listbox.getByText('All servers', { exact: true })).toBeVisible();

  // Click the row and assert the chip updates.
  await listbox.getByText('All servers', { exact: true }).click();
  await expect(chip).toHaveText(/All servers/i, { timeout: 5_000 });
});