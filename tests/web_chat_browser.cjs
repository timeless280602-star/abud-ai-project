const { chromium } = require("playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let conversations = [],
    messages = [];
  let releaseHistory;
  const historyReady = new Promise((resolve) => { releaseHistory = resolve; });
  await page.route("**/auth/me", (r) =>
    r.fulfill({
      json: {
        identity_id: "google-only",
        profile_completed: true,
        dashboard_access: false,
        permissions: [],
        display_name: "Web User",
      },
    }),
  );
  await page.route("**/health", (r) =>
    r.fulfill({ json: { status: "healthy" } }),
  );
  await page.route("**/web/chat/conversations**", async (r) => {
    const q = r.request(),
      path = new URL(q.url()).pathname,
      method = q.method();
    if (path.endsWith("/messages")) {
      messages = [
        { id: 1, role: "user", content: "Hello" },
        {
          id: 2,
          role: "assistant",
          content: "Hello **world**\n```js\nconst x = 1;\n```",
        },
      ];
      return r.fulfill({
        contentType: "text/event-stream",
        body:
          "data: " +
          JSON.stringify({ type: "delta", text: messages[1].content }) +
          '\n\ndata: {"type":"memory_not_saved","message":"This personal memory is archived. It was not saved or restored."}\n\ndata: {"type":"done"}\n\n',
      });
    }
    if (path.endsWith("/conversations")) {
      if (method === "POST") {
        const c = { id: "abc", title: "New conversation" };
        conversations.push(c);
        return r.fulfill({ status: 201, json: c });
      }
      return r.fulfill({ json: conversations });
    }
    if (method === "PATCH") {
      conversations[0].title = q.postDataJSON().title;
      return r.fulfill({ json: { success: true } });
    }
    if (method === "DELETE") {
      conversations = [];
      messages = [];
      return r.fulfill({ json: { success: true } });
    }
    await historyReady;
    return r.fulfill({
      json: { id: "abc", title: "New conversation", messages },
    });
  });
  await page.goto("http://localhost:5173");
  await page.getByText("Talk with Abud", { exact: true }).waitFor();
  assert.equal(
    await page.getByText("Memory Matrix", { exact: true }).count(),
    0,
  );
  await page
    .getByRole("button", { name: "＋ New conversation", exact: true })
    .click();
  await page.getByLabel("Message Abud", { exact: true }).fill("Hello");
  assert.equal(await page.getByRole("button", { name: "Send", exact: true }).isDisabled(), true);
  releaseHistory();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await page.getByText("world", { exact: true }).waitFor();
  await page.getByRole("status").filter({ hasText: "not saved or restored" }).waitFor();
  assert.equal(await page.locator("pre code .hljs-keyword").count(), 1);
  await page
    .getByRole("button", { name: "Regenerate response", exact: true })
    .click();
  await page.getByText("world", { exact: true }).waitFor();
  page.once("dialog", (d) => d.accept("Renamed"));
  await page
    .getByRole("button", { name: "Rename New conversation", exact: true })
    .click();
  await page.getByRole("button", { name: "Renamed", exact: true }).waitFor();
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    const composer = await page.getByLabel("Message Abud", { exact: true }).boundingBox();
    assert.ok(composer.width > 100 && composer.x >= 0 && composer.x + composer.width <= width);
  }
  page.once("dialog", (d) => d.accept());
  await page
    .getByRole("button", { name: "Delete Renamed", exact: true })
    .click();
  await page.getByText("Talk with Abud", { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log(
    "PASS: Google-only UI, loading guard, create/send, archive notice, Markdown/highlighting, regenerate, rename/delete, 320/390/768/1280px layouts, no JS errors (mock HTTP).",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
