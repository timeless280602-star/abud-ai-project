const assert = require('node:assert/strict');
const { mkdirSync, readFileSync } = require('node:fs');
const { chromium } = require('playwright');

(async () => {
  const { url, tokens } = JSON.parse(readFileSync(0, 'utf8'));
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH,
    headless: true,
    args: ['--no-sandbox'],
  });
  try {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      reducedMotion: 'reduce',
      viewport: { width: 1440, height: 900 },
    });
    await context.addCookies([{
      name: 'abud_session', value: tokens[0], url, secure: true, httpOnly: true, sameSite: 'Lax',
    }]);
    await context.route('**/*', async (route) => {
      const address = new URL(route.request().url());
      if (address.origin !== new URL(url).origin) return route.abort();
      if (address.pathname === '/auth/me') {
        const response = await route.fetch();
        const user = await response.json();
        return route.fulfill({
          response,
          json: { ...user, display_name: 'Demo Operator', dashboard_access: true, is_creator: true },
        });
      }
      if (address.pathname === '/auth/guilds') return route.fulfill({ json: { guilds: [] } });
      return route.continue();
    });

    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto(url);
    await page.getByText('Talk with Abud', { exact: true }).waitFor();

    const preview = process.env.ABUD_SIDEBAR_PREVIEW_DIR;
    if (preview) mkdirSync(preview, { recursive: true });
    const capture = async (name) => {
      if (preview) await page.screenshot({ path: preview + '/' + name + '.png' });
    };

    const nav = page.getByRole('navigation', { name: 'Dashboard navigation' });
    const chat = nav.getByRole('button', { name: 'AI Chat', exact: true });
    assert.equal(await nav.getByRole('button').count(), 10);
    assert.equal(await chat.getAttribute('aria-current'), 'page');
    await capture('desktop-expanded');

    await page.getByRole('button', { name: 'Collapse sidebar' }).click();
    assert.equal(await page.getByRole('button', { name: 'Expand sidebar' }).getAttribute('aria-expanded'), 'false');
    assert.equal(await chat.getByText('AI Chat').isVisible(), false);
    assert.equal(await nav.getByRole('button').count(), 10);
    await capture('desktop-collapsed');

    await page.reload();
    await page.getByRole('button', { name: 'Expand sidebar' }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    const menu = page.getByRole('button', { name: 'Open menu', exact: true });
    const drawer = page.getByRole('dialog', { name: 'Dashboard menu' });
    assert.equal(await menu.getAttribute('aria-expanded'), 'false');
    assert.equal(await nav.isVisible(), false);
    await menu.click();
    await drawer.waitFor();
    await page.waitForFunction(() => document.activeElement?.classList.contains('mobile-close'));
    assert.equal(await drawer.getAttribute('aria-modal'), 'true');
    assert.equal(await page.locator('main').evaluate((element) => element.inert), true);
    assert.equal(await chat.getByText('AI Chat').isVisible(), true);
    await capture('mobile-drawer');

    await page.keyboard.press('Shift+Tab');
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-label')), 'Sign out');
    await page.keyboard.press('Tab');
    await page.waitForFunction(() => document.activeElement?.classList.contains('mobile-close'));
    await page.keyboard.press('Escape');
    await drawer.waitFor({ state: 'hidden' });
    await page.waitForFunction(() => document.activeElement?.classList.contains('mobile-menu'));
    assert.equal(await menu.getAttribute('aria-expanded'), 'false');

    await menu.click();
    await nav.getByRole('button', { name: 'Command Center', exact: true }).click();
    await drawer.waitFor({ state: 'hidden' });
    assert.match(await page.locator('.breadcrumb').innerText(), /COMMAND CENTER/);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole('button', { name: 'Expand sidebar' }).click();
    assert.equal(await page.getByRole('button', { name: 'Collapse sidebar' }).getAttribute('aria-expanded'), 'true');
    assert.deepEqual(errors, []);
    console.log('PASS dashboard sidebar: desktop collapse, persisted preference, mobile focus and navigation');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
