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
    for (const title of ['Shipment tracking', 'Project brainstorm']) {
      const response = await context.request.post(url + '/web/chat/conversations', {
        headers: { Origin: url }, data: { title },
      });
      assert.equal(response.status(), 201);
    }
    await page.goto(url);
    await page.getByText('Talk with Abud', { exact: true }).waitFor();

    const preview = process.env.ABUD_SIDEBAR_PREVIEW_DIR;
    if (preview) mkdirSync(preview, { recursive: true });
    const capture = async (name) => {
      if (preview) await page.screenshot({ path: preview + '/' + name + '.png' });
    };

    const nav = page.getByRole('navigation', { name: 'Dashboard navigation' });
    const chat = nav.getByRole('button', { name: 'AI Chat', exact: true });
    assert.equal(await nav.locator('.nav-item').count(), 10);
    assert.equal(await chat.getAttribute('aria-current'), 'page');
    const projects = nav.getByRole('navigation', { name: 'Projects', exact: true });
    const conversations = nav.getByRole('navigation', { name: 'Conversations', exact: true });
    assert.equal(await projects.isVisible(), true);
    assert.equal(await conversations.isVisible(), true);
    assert.equal(await page.locator('.web-chat aside').count(), 0);
    await nav.getByRole('button', { name: 'Hide chat navigation' }).click();
    assert.equal(await conversations.isVisible(), false);
    await nav.getByRole('button', { name: 'Show chat navigation' }).click();
    assert.equal(await conversations.isVisible(), true);
    const projectToggle = nav.getByRole('button', { name: 'Projects', exact: true });
    const recentToggle = conversations.getByRole('button', { name: 'Recent', exact: true });
    const chatRows = conversations.locator('.chat-conversation > button:first-child');
    await projectToggle.click();
    assert.equal(await projects.isVisible(), false);
    await projectToggle.click();
    await projects.waitFor();
    await recentToggle.click();
    assert.equal(await chatRows.first().isVisible(), false);
    await recentToggle.click();
    await chatRows.first().waitFor();

    const beforeSort = await chatRows.allTextContents();
    assert.equal(beforeSort.length, 2);
    await nav.getByRole('button', { name: 'Chat sorting settings' }).click();
    await capture('sort-menu');
    await nav.getByRole('button', { name: 'Manual order', exact: true }).click();
    await conversations.getByRole('button', { name: 'Options for ' + beforeSort[0].trim(), exact: true }).click();
    await conversations.getByRole('menuitem', { name: 'Move down' }).click();
    assert.deepEqual(await chatRows.allTextContents(), [...beforeSort].reverse());

    await conversations.getByRole('button', { name: 'Shipment tracking', exact: true }).click();
    const input = page.getByLabel('Message Abud', { exact: true });
    await input.fill('Hello, Abud.');
    await input.press('Enter');
    await page.getByText('world', { exact: true }).waitFor();
    const toolbar = page.getByRole('group', { name: 'Response actions' });
    for (const label of ['Copy response', 'Rate response', 'Read aloud', 'Share response', 'Branch in new chat']) {
      await toolbar.getByRole('button', { name: label, exact: true }).waitFor();
    }
    assert.equal(await toolbar.getByRole('button').count(), 5);
    await toolbar.getByRole('button', { name: 'Copy response', exact: true }).hover();
    await capture('response-toolbar');
    await page.locator('.breadcrumb').hover();
    await capture('desktop-expanded');

    await page.getByRole('button', { name: 'Collapse sidebar' }).click();
    assert.equal(await page.getByRole('button', { name: 'Expand sidebar' }).getAttribute('aria-expanded'), 'false');
    assert.equal(await chat.getByText('AI Chat').isVisible(), false);
    assert.equal(await nav.locator('.nav-item').count(), 10);
    assert.equal(await conversations.isVisible(), false);
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
    assert.deepEqual(await chatRows.allTextContents(), [...beforeSort].reverse());
    const createProject = nav.getByRole('button', { name: 'New project', exact: true });
    assert.equal(await createProject.isVisible(), true);
    assert.equal((await createProject.innerText()).trim(), '');
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
    await nav.getByRole('button', { name: '＋ New conversation', exact: true }).click();
    await drawer.waitFor({ state: 'hidden' });
    await page.getByLabel('Message Abud', { exact: true }).waitFor();

    await menu.click();
    await nav.getByRole('button', { name: 'Command Center', exact: true }).click();
    await drawer.waitFor({ state: 'hidden' });
    assert.match(await page.locator('.breadcrumb').innerText(), /COMMAND CENTER/);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole('button', { name: 'Expand sidebar' }).click();
    assert.equal(await page.getByRole('button', { name: 'Collapse sidebar' }).getAttribute('aria-expanded'), 'true');
    await nav.getByRole('button', { name: 'AI Chat', exact: true }).click();
    await conversations.getByRole('button', { name: 'Shipment tracking', exact: true }).click();
    await page.getByText('world', { exact: true }).waitFor();
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'share', {
        configurable: true, value: async ({ text }) => { window.sharedResponse = text; },
      });
    });
    await toolbar.getByRole('button', { name: 'Share response', exact: true }).click();
    assert.match(await page.evaluate(() => window.sharedResponse), /world/);
    await toolbar.getByRole('button', { name: 'Branch in new chat', exact: true }).click();
    const branch = conversations.getByRole('button', { name: 'Branch: Shipment tracking', exact: true });
    await branch.waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('nav[aria-label="Conversations"] button')]
      .some((button) => button.textContent.trim() === 'Branch: Shipment tracking' && button.getAttribute('aria-current') === 'page'));
    await page.getByText('world', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS dashboard sidebar: desktop collapse, persisted preference, mobile focus and navigation');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
