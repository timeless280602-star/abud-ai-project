const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");

async function main() {
  const { url } = JSON.parse(fs.readFileSync(0, "utf8"));
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1063, height: 788 } });
    let user = { identity_id: "navigation-fixture", profile_completed: true, display_name: "Bara",
      dashboard_access: true, is_creator: true, permissions: [] };
    const chats = [{ id: "nav-chat", title: "Marketing brief", pinned: 1, updated_at: new Date().toISOString() }];
    const projects = [{ id: "nav-project", name: "Content planning", description: "Project description",
      instructions: "Use Indonesian.", memory_mode: "default", conversation_count: 1 }];
    const errors = [];
    const page = await context.newPage();
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/auth/me", (route) => route.fulfill({ json: user }));
    await page.route("**/auth/guilds", (route) => route.fulfill({ json: { guilds: [] } }));
    await page.route("**/web/chat/**", async (route) => {
      const request = route.request(), path = new URL(request.url()).pathname;
      if (path === "/web/chat/voice") return route.fulfill({ json: { enabled: false, provider: "ollama" } });
      if (path === "/web/chat/projects") {
        if (request.method() === "POST") {
          projects.push({ ...request.postDataJSON(), id: "new-project", conversation_count: 0 });
          return route.fulfill({ status: 201, json: projects.at(-1) });
        }
        return route.fulfill({ json: projects });
      }
      if (path === "/web/chat/conversations") return route.fulfill({ json: chats });
      return route.fulfill({ json: {
        id: "nav-chat", title: "Marketing brief", project_id: null, archived_at: null,
        messages: [
          { id: 1, role: "user", content: "Bantu susun ide konten untuk minggu ini." },
          { id: 2, role: "assistant", content: "Kita mulai dari pengenalan produk, cerita proses, lalu tips yang berguna untuk audiens." },
        ],
      } });
    });
    await page.goto(url);
    const mainNav = page.getByRole("navigation", { name: "Main navigation", exact: true });
    await mainNav.getByRole("button", { name: "AI Chat", exact: true }).click();
    const chatNavigation = mainNav.getByRole("region", { name: "Chat navigation" });
    await chatNavigation.waitFor();
    assert.equal(await page.locator("main .chat-sidebar").count(), 0);
    assert.equal(await chatNavigation.evaluate((element) =>
      element.closest("#chat-navigation").previousElementSibling.textContent.trim()), "AI Chat");
    await chatNavigation.getByRole("button", { name: /Marketing brief/ }).click();
    const draft = page.getByLabel("Message Abud", { exact: true });
    await draft.fill("Keep this draft");
    await mainNav.getByRole("button", { name: "AI Chat", exact: true }).click();
    await chatNavigation.waitFor({ state: "hidden" });
    assert.equal(await draft.inputValue(), "Keep this draft");
    await mainNav.getByRole("button", { name: "AI Chat", exact: true }).click();
    await chatNavigation.waitFor();
    const widths = await page.locator(".chat-main").evaluate((element) => ({
      chat: element.getBoundingClientRect().left,
      main: document.querySelector(".main-area").getBoundingClientRect().left,
    }));
    assert.ok(Math.abs(widths.chat - widths.main) <= 2, "Chat should begin at the main content boundary");
    await chatNavigation.getByRole("button", { name: "＋ New project", exact: true }).click();
    await page.getByRole("dialog", { name: "New project" }).getByRole("button", { name: "Cancel", exact: true }).click();
    await chatNavigation.getByRole("button", { name: /Content planning/ }).click();
    await page.getByRole("button", { name: "Project settings", exact: true }).click();
    await page.getByRole("dialog", { name: "Project settings" }).getByRole("button", { name: "Cancel", exact: true }).click();
    await chatNavigation.getByRole("button", { name: "Recent chats", exact: true }).click();
    await chatNavigation.getByRole("button", { name: /Marketing brief/ }).click();
    await draft.waitFor();
    await page.screenshot({ path: "/tmp/abud-navigation-chat.png", fullPage: true });

    await mainNav.getByRole("button", { name: "Dashboard", exact: true }).click();
    const dashboard = mainNav.getByRole("group", { name: "Dashboard modules" });
    await dashboard.waitFor();
    await dashboard.getByRole("button", { name: "Memory Matrix", exact: true }).waitFor();
    assert.equal(await dashboard.evaluate((element) => element.previousElementSibling.textContent.trim()), "Dashboard");
    assert.ok(await dashboard.evaluate((element) => Boolean(
      element.compareDocumentPosition([...document.querySelectorAll(".sidebar .nav-item")]
        .find((button) => button.textContent.trim() === "Integrasi")) & Node.DOCUMENT_POSITION_FOLLOWING
    )));
    await page.screenshot({ path: "/tmp/abud-navigation-dashboard.png", fullPage: true });
    await mainNav.getByRole("button", { name: "Dashboard", exact: true }).click();
    await dashboard.waitFor({ state: "hidden" });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Open menu", exact: true }).click();
    await mainNav.getByRole("button", { name: "AI Chat", exact: true }).click();
    await page.getByRole("button", { name: "Open chat history", exact: true }).click();
    await chatNavigation.waitFor();
    await chatNavigation.getByRole("button", { name: /Marketing brief/ }).click();
    await draft.waitFor();
    assert.equal(await page.locator(".sidebar").evaluate((element) => element.getBoundingClientRect().right <= 0), true);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.screenshot({ path: "/tmp/abud-navigation-mobile.png", fullPage: true });

    user = { ...user, is_creator: false, permissions: [{ permission: "memory.personal.view" }] };
    await page.setViewportSize({ width: 1063, height: 788 });
    await page.goto(url);
    await mainNav.getByRole("button", { name: "Dashboard", exact: true }).click();
    await dashboard.getByRole("button", { name: "Memory Matrix", exact: true }).waitFor();
    assert.equal(await dashboard.getByRole("button").count(), 1);
    user = { ...user, dashboard_access: false, permissions: [] };
    await page.reload();
    await mainNav.getByRole("button", { name: "AI Chat", exact: true }).waitFor();
    assert.equal(await mainNav.getByRole("button", { name: "Dashboard", exact: true }).count(), 0);
    assert.deepEqual(errors, []);
    console.log("Passed: one sidebar, nested chat and dashboard, preserved draft and project controls, mobile navigation and role permissions.");
  } finally {
    await browser.close();
  }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
