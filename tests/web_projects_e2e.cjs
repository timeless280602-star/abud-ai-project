const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
(async () => {
  const { url, tokens } = JSON.parse(fs.readFileSync(0, "utf8"));
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium", headless: true, args: ["--no-sandbox"] });
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    await context.route("**/*", (r) => r.request().url().startsWith(url) ? r.continue() : r.abort());
    await context.addCookies([{ name: "abud_session", value: tokens[0], url, secure: true, httpOnly: true, sameSite: "Lax" }]);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const dialog = () => page.getByRole("dialog");
    const projectButton = (name) => page.getByRole("button", { name: new RegExp(`^${name}.*(?:Default|Project-only)$`) });
    async function menu(cid) {
      const chat = await (await context.request.get(url + "/web/chat/conversations/" + cid)).json();
      await page.getByRole("button", { name: `Options for ${chat.title}`, exact: true }).click();
    }
    async function newProject(name, mode) {
      await page.getByRole("button", { name: "＋ New project", exact: true }).click();
      await dialog().getByLabel("Name", { exact: true }).fill(name);
      await dialog().getByLabel("Description (optional)", { exact: true }).fill("A test workspace");
      await dialog().getByLabel("AI instructions (optional)", { exact: true }).fill("Jawab dalam bahasa Indonesia.");
      await dialog().getByLabel("Memory mode", { exact: true }).selectOption(mode);
      await dialog().getByRole("button", { name: "Save", exact: true }).click();
      await dialog().waitFor({ state: "hidden" });
      await projectButton(name).click();
      await page.getByRole("heading", { name, exact: true }).waitFor();
      return (await (await context.request.get(url + "/web/chat/projects")).json()).find((p) => p.name === name).id;
    }
    await page.goto(url);
    await page.getByText("Talk with Abud", { exact: true }).waitFor();
    const privateId = await newProject("Private Research", "project_only");
    await page.getByRole("button", { name: "Project settings", exact: true }).click();
    assert.equal(await dialog().getByLabel("Memory mode", { exact: true }).isDisabled(), true);
    await dialog().getByLabel("Description (optional)", { exact: true }).fill("Updated research");
    await dialog().getByRole("button", { name: "Save", exact: true }).click();
    await page.getByText("Updated research", { exact: true }).waitFor();
    await page.getByRole("button", { name: "New chat in project", exact: true }).click();
    await page.getByLabel("Message Abud", { exact: true }).fill("Bantu gue bikin strategi pemasaran kopi");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByText("world", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Regenerate response", exact: true }).waitFor();
    await page.waitForFunction(() => ![...document.querySelectorAll("button")].find((b) => b.textContent === "Regenerate response").disabled);
    const chats = await (await context.request.get(url + `/web/chat/projects/${privateId}/conversations`)).json();
    const cid = chats[0].id;
    assert.equal(chats[0].title, "Strategi pemasaran kopi");
    await menu(cid);
    // Keyboard menu navigation and Escape return focus to its trigger.
    await page.getByRole("menuitem", { name: "Rename", exact: true }).press("ArrowDown");
    assert.equal(await page.evaluate(() => document.activeElement.textContent), "Pin");
    await page.keyboard.press("Escape");
    await menu(cid);
    await page.getByRole("menuitem", { name: "Pin", exact: true }).click();
    await page.getByRole("heading", { name: "Pinned", exact: true }).waitFor();
    await menu(cid);
    await page.getByRole("menuitem", { name: "Rename", exact: true }).click();
    await dialog().getByLabel("Name", { exact: true }).fill("Manual research title");
    await dialog().getByRole("button", { name: "Save", exact: true }).click();
    await page.getByRole("button", { name: "Options for Manual research title", exact: true }).waitFor();
    if (process.env.ABUD_UI_CAPTURE_DIR) {
      await page.screenshot({ path: process.env.ABUD_UI_CAPTURE_DIR + "/projects-desktop.png" });
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForFunction(() => document.querySelector(".sidebar").getBoundingClientRect().right <= 1);
      await page.waitForTimeout(350);
      assert.ok(await page.evaluate(() => [".chat-main", ".chat-project-panel", ".chat-composer"].every((selector) => {
        const element = document.querySelector(selector); return element.scrollWidth <= element.clientWidth + 1;
      })));
      await page.screenshot({ path: process.env.ABUD_UI_CAPTURE_DIR + "/projects-mobile.png" });
      await page.setViewportSize({ width: 1280, height: 844 });
    }
    await menu(cid);
    await page.getByRole("menuitem", { name: "Archive", exact: true }).click();
    await page.getByRole("button", { name: "Archived chats", exact: true }).click();
    await page.getByRole("button", { name: "Options for Manual research title", exact: true }).waitFor();
    await menu(cid);
    await page.getByRole("menuitem", { name: "Unarchive", exact: true }).click();
    await projectButton("Private Research").click();
    await page.getByRole("button", { name: "Options for Manual research title", exact: true }).waitFor();
    await menu(cid);
    await page.getByRole("menuitem", { name: "Move to project", exact: true }).click();
    await dialog().getByLabel("Destination project", { exact: true }).selectOption("");
    await dialog().getByRole("button", { name: "Save", exact: true }).click();
    await dialog().getByRole("alert").filter({ hasText: "Only empty conversations" }).waitFor();
    await dialog().getByRole("button", { name: "Cancel", exact: true }).click();
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      await page.getByRole("button", { name: "Project settings", exact: true }).click();
      const box = await dialog().boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width);
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.keyboard.press("Escape");
    }
    const defaultId = await newProject("Default Work", "default");
    const normalCreated = page.waitForResponse((r) => r.url() === url + "/web/chat/conversations" && r.request().method() === "POST");
    await page.getByRole("button", { name: "New chat in project", exact: true }).click();
    const normal = (await (await normalCreated).json()).id;
    await page.getByLabel("Message Abud", { exact: true }).waitFor();
    await menu(normal);
    await page.getByRole("menuitem", { name: "Move to project", exact: true }).click();
    await dialog().getByLabel("Destination project", { exact: true }).selectOption("");
    await dialog().getByRole("button", { name: "Save", exact: true }).click();
    await dialog().waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Recent chats", exact: true }).click();
    await page.getByRole("button", { name: "Options for New conversation", exact: true }).waitFor();
    // Destructive operations require a modal confirmation; Cancel preserves data.
    await menu(normal);
    await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
    await dialog().getByRole("button", { name: "Cancel", exact: true }).click();
    assert.equal((await context.request.get(url + "/web/chat/conversations/" + normal)).status(), 200);
    await menu(normal);
    await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
    await dialog().getByRole("button", { name: "Delete permanently", exact: true }).click();
    await dialog().waitFor({ state: "hidden" });
    assert.equal((await context.request.get(url + "/web/chat/conversations/" + normal)).status(), 404);
    await projectButton("Default Work").click();
    const keptCreated = page.waitForResponse((r) => r.url() === url + "/web/chat/conversations" && r.request().method() === "POST");
    await page.getByRole("button", { name: "New chat in project", exact: true }).click();
    const kept = (await (await keptCreated).json()).id;
    await page.getByLabel("Message Abud", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Delete project", exact: true }).click();
    assert.equal(await dialog().getByRole("button", { name: "Delete permanently", exact: true }).isDisabled(), true);
    await dialog().getByLabel("I confirm this project deletion and the selected history action.", { exact: true }).check();
    await dialog().getByRole("button", { name: "Delete permanently", exact: true }).click();
    await dialog().waitFor({ state: "hidden" });
    assert.equal((await (await context.request.get(url + "/web/chat/conversations/" + kept)).json()).project_id, null);
    await projectButton("Private Research").click();
    await page.getByRole("button", { name: "Delete project", exact: true }).click();
    await dialog().getByLabel("Conversation history", { exact: true }).selectOption("delete");
    await dialog().getByLabel("I confirm this project deletion and the selected history action.", { exact: true }).check();
    await dialog().getByRole("button", { name: "Delete permanently", exact: true }).click();
    await dialog().waitFor({ state: "hidden" });
    assert.equal((await context.request.get(url + "/web/chat/conversations/" + cid)).status(), 404);
    assert.deepEqual(errors, []);
    console.log("PASS: real HTTPS Projects CRUD/settings, immutable modes, project streaming/titles, keyboard menus, pin, archive/restore, guarded moves, delete confirmations/history choice and 320/390/768/1280px dialogs. AI/OAuth mocked.");
  } finally { await browser.close(); }
})().catch((e) => { console.error(e); process.exit(1); });
