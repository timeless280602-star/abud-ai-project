const { chromium, firefox, webkit } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");

async function main() {
  const { url } = JSON.parse(fs.readFileSync(0, "utf8"));
  const engine = process.env.BROWSER || "chromium";
  const browser = await ({ chromium, firefox, webkit })[engine].launch({
    executablePath: process.env.CHROMIUM_EXECUTABLE_PATH,
    ...(engine === "chromium" ? { args: ["--no-sandbox"] } : {}),
  });
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 390, height: 844 },
      ...(engine !== "firefox" ? { isMobile: true, hasTouch: true } : {}) });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const title = "Rencana konten promosi kopi dan laporan penjualan mingguan yang judulnya sangat panjang";
    const markdown = [
      "## Rencana konten",
      "Paragraf panjang untuk menguji pembacaan riwayat. ".repeat(100),
      "https://example.test/" + "tautan-panjang".repeat(60),
      "```js\nconst laporan = '" + "kode_panjang_".repeat(100) + "';\n```",
      "| Produk | Senin | Selasa | Rabu | Kamis | Jumat | Sabtu | Minggu |\n|---|---|---|---|---|---|---|---|\n| Kopi susu | 125 | 150 | 170 | 135 | 190 | 210 | 200 |",
      "![Contoh gambar lebar](/responsive-image.svg)",
    ].join("\n\n");
    let messages = [{ id: 1, role: "user", content: "Bantu susun rencana konten.", created_at: "2026-11-17T20:00:00Z" },
      { id: 2, role: "assistant", content: markdown, created_at: "2026-11-17T20:00:01Z" }];
    await page.route("**/responsive-image.svg", (route) => route.fulfill({ contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="2400" height="1200"><rect width="2400" height="1200" fill="#533541"/></svg>' }));
    await page.route("**/auth/me", (route) => route.fulfill({ json: { identity_id: "responsive-fixture", profile_completed: true,
      display_name: "Bara", dashboard_access: true, is_creator: true, permissions: [] } }));
    await page.route("**/auth/guilds", (route) => route.fulfill({ json: { guilds: [] } }));
    await page.route("**/health", (route) => route.fulfill({ json: { status: "healthy" } }));
    await page.route("**/web/chat/**", (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/web/chat/voice") return route.fulfill({ json: { enabled: true, provider: "router" } });
      if (path === "/web/chat/projects") return route.fulfill({ json: [{ id: "project", name: "Kopi", description: "Detail proyek. ".repeat(100), instructions: "Gunakan bahasa Indonesia.", memory_mode: "default" }] });
      if (path === "/web/chat/conversations") return route.fulfill({ json: [{ id: "responsive", title }, { id: "other", title: "Catatan pribadi" }] });
      return route.fulfill({ json: { id: "responsive", title, messages } });
    });
    await page.addInitScript(() => {
      // A controlled visual viewport reproduces keyboard resize events, not a device keyboard.
      const viewport = new EventTarget();
      viewport.height = window.innerHeight;
      viewport.offsetTop = 0;
      Object.defineProperty(window, "visualViewport", { value: viewport, configurable: true });
      window.resizeVisibleArea = (height) => { viewport.height = height; viewport.dispatchEvent(new Event("resize")); };
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (resource, options) => {
        if (options?.method === "POST" && String(resource).endsWith("/messages")) {
          const stream = new ReadableStream({ start(controller) {
            window.replyFrame = (frame) => controller.enqueue(new TextEncoder().encode("data: " + JSON.stringify(frame) + "\n\n"));
            window.finishReply = () => controller.close();
          } });
          return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
        }
        return originalFetch(resource, options);
      };
    });
    await page.goto(url);
    const mainNav = page.getByRole("navigation", { name: "Main navigation", exact: true });
    async function openMenu() {
      if (await page.getByRole("button", { name: "Open menu", exact: true }).isVisible())
        await page.getByRole("button", { name: "Open menu", exact: true }).click();
    }
    await openMenu();
    await mainNav.getByRole("button", { name: "AI Chat", exact: true }).click();
    await page.getByRole("button", { name: "Open chat history", exact: true }).click();
    const search = page.getByRole("searchbox", { name: "Search chat titles", exact: true });
    await search.fill("KOPI");
    const chats = mainNav.getByRole("navigation", { name: "Conversations", exact: true });
    assert.equal(await chats.locator(".chat-conversation").count(), 1);
    await search.fill("tidak ditemukan");
    await page.getByText("No matching chat titles.", { exact: true }).waitFor();
    await search.fill("");
    await chats.getByRole("button", { name: title, exact: true }).click();
    const draft = page.getByLabel("Message Abud", { exact: true });
    await draft.waitFor();
    await page.locator(".chat-table-scroll table").waitFor();
    await draft.fill("Draft tetap tersimpan.");
    const pane = page.locator(".chat-messages");
    for (const [width, height] of [[320, 740], [390, 844], [600, 960], [768, 1024], [820, 1180], [1024, 768], [1180, 820], [1440, 900], [844, 390]]) {
      await page.setViewportSize({ width, height });
      await page.evaluate((height) => window.resizeVisibleArea(height), height);
      await page.waitForFunction(() => {
        const rect = document.querySelector(".abud-chat-room").getBoundingClientRect();
        return Math.abs(rect.bottom - window.visualViewport.height) < 2;
      });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}x${height}: page overflow`);
      assert.ok(await pane.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), `${width}x${height}: message pane overflow`);
      const send = await page.getByRole("button", { name: "Send", exact: true }).boundingBox();
      assert.ok(send.x >= 0 && send.x + send.width <= width + 1 && send.y >= 0 && send.y + send.height <= height + 1, `${width}x${height}: send visible`);
      const touchSize = width <= 900 || await page.evaluate(() => matchMedia("(pointer: coarse)").matches) ? 44 : 36;
      assert.ok(send.width >= touchSize - 0.1 && send.height >= touchSize - 0.1, `${width}x${height}: controls meet ${touchSize}px target`);
      assert.equal(await draft.inputValue(), "Draft tetap tersimpan.");
      const table = page.getByRole("region", { name: "Response table", exact: true });
      assert.ok(await table.evaluate((el) => el.scrollWidth > el.clientWidth), "Wide table scrolls inside its own region");
      assert.ok(await page.locator("pre").evaluate((el) => [el, el.querySelector("code")].some((block) => block.scrollWidth > block.clientWidth)), "Long code scrolls inside its block");
      assert.ok(await page.locator(".chat-message-body img").evaluate((el) => el.width <= el.parentElement.clientWidth), "Image fits message");
      await page.screenshot({ path: `/tmp/abud-responsive-${engine}-${width}x${height}.png`, fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => window.resizeVisibleArea(844));
    await draft.focus();
    await page.evaluate(() => window.resizeVisibleArea(360));
    await page.waitForFunction(() => document.querySelector(".chat-composer").getBoundingClientRect().bottom <= 361);
    assert.equal(await draft.inputValue(), "Draft tetap tersimpan.");
    await page.screenshot({ path: `/tmp/abud-responsive-${engine}-keyboard.png`, fullPage: true });
    await page.evaluate(() => window.resizeVisibleArea(844));
    await openMenu();
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => document.querySelector(".sidebar").hasAttribute("inert"));
    await openMenu();
    await mainNav.getByRole("button", { name: "Dashboard", exact: true }).click();
    await openMenu();
    await mainNav.getByRole("group", { name: "Dashboard modules" }).getByRole("button", { name: "Memory Matrix", exact: true }).waitFor();
    await mainNav.getByRole("button", { name: "AI Chat", exact: true }).click();
    await page.getByRole("button", { name: "Open chat history", exact: true }).click();
    await chats.getByRole("button", { name: title, exact: true }).click();
    await draft.fill("Uji respons panjang");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "Abud is responding" }).waitFor();
    await page.evaluate(() => window.replyFrame({ type: "delta", text: "Jawaban sedang dikirim. ".repeat(100) }));
    await page.getByText(/Jawaban sedang dikirim/).first().waitFor();
    await pane.evaluate((el) => { el.scrollTop = 0; });
    await page.getByRole("button", { name: "Latest message", exact: true }).waitFor();
    await page.evaluate(() => window.replyFrame({ type: "delta", text: "Tambahan jawaban." }));
    await page.getByText(/Tambahan jawaban/).waitFor();
    assert.ok(await pane.evaluate((el) => el.scrollTop < 5), "Streaming preserves reading position");
    await page.getByRole("button", { name: "Latest message", exact: true }).click();
    assert.ok(await pane.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight < 80), "Jump returns to newest content");
    messages = [...messages, { id: 3, role: "user", content: "Uji respons panjang" }, { id: 4, role: "assistant", content: "Respons selesai." }];
    await page.evaluate(() => { window.replyFrame({ type: "done" }); window.finishReply(); });
    await page.getByText("Respons selesai.", { exact: true }).waitFor();
    // Failed stream keeps a clear retry control and recovers without resending the user's message.
    await draft.fill("Uji kegagalan");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "Abud is responding" }).waitFor();
    messages = [...messages, { id: 5, role: "user", content: "Uji kegagalan" }];
    await page.evaluate(() => { window.replyFrame({ type: "error", message: "Layanan sementara tidak tersedia." }); window.finishReply(); });
    await page.getByRole("alert").filter({ hasText: "Layanan sementara" }).waitFor();
    await page.getByRole("button", { name: "Regenerate response", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "Abud is responding" }).waitFor();
    messages = [...messages, { id: 6, role: "assistant", content: "Pemulihan berhasil." }];
    await page.evaluate(() => { window.replyFrame({ type: "delta", text: "Pemulihan berhasil." }); window.replyFrame({ type: "done" }); window.finishReply(); });
    await page.getByText("Pemulihan berhasil.", { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log(`PASS ${engine}: nine phone/tablet/desktop sizes, local table/code scrolling, images, keyboard viewport simulation, title search, draft, dashboard, drawer Escape, streaming reading position and retry (mock HTTP).`);
  } catch (error) {
    for (const context of browser.contexts()) for (const page of context.pages())
      await page.screenshot({ path: `/tmp/abud-responsive-${engine}-failure.png`, fullPage: true }).catch(() => {});
    throw error;
  } finally { await browser.close(); }
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
