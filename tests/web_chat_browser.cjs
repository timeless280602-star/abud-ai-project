const { chromium } = require("playwright");
const assert = require("node:assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({ ignoreHTTPSErrors: true });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let conversations = [],
    messages = [];
  let streamFailure = null, historyFailure = false;
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
  await page.route("**/web/chat/projects", (r) => r.fulfill({ json: [] }));
  await page.route("**/health", (r) =>
    r.fulfill({ json: { status: "healthy" } }),
  );
  await page.route("**/web/chat/conversations**", async (r) => {
    const q = r.request(),
      path = new URL(q.url()).pathname,
      method = q.method();
    if (path.endsWith("/messages")) {
      if (streamFailure) {
        messages = [...messages, { id: 3, role: "user", content: q.postDataJSON().message }];
        const ending = streamFailure === "malformed" ? "data: invalid-json\n\n"
          : streamFailure === "server-error" ? 'data: {"type":"error","message":"Please regenerate."}\n\n' : "";
        return r.fulfill({ contentType: "text/event-stream",
          body: 'data: {"type":"delta","text":"Unfinished answer"}\n\n' + ending });
      }
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
    if (historyFailure) return r.fulfill({ status: 503, json: { detail: "History unavailable. Please regenerate." } });
    return r.fulfill({
      json: { id: "abc", title: "New conversation", messages },
    });
  });
  const input = require("node:fs").readFileSync(0, "utf8").trim();
  await page.goto(input ? JSON.parse(input).url : "http://localhost:5173");
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
  for (const failure of ["truncated", "malformed", "server-error"]) {
    await page.waitForFunction(() => ![...document.querySelectorAll("button")].find((b) => b.textContent === "Regenerate response").disabled);
    streamFailure = failure;
    historyFailure = true;
    await page.getByLabel("Message Abud", { exact: true }).fill("A new question");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByText("Incomplete response · Regenerate to retry.", { exact: true }).waitFor();
    await page.waitForFunction(() => ![...document.querySelectorAll("button")].find((b) => b.textContent === "Regenerate response").disabled);
    assert.equal(await page.getByText("Unfinished answer", { exact: true }).count(), 1);
    await page.getByLabel("Message Abud", { exact: true }).fill("Do not send a duplicate");
    assert.equal(await page.getByRole("button", { name: "Send", exact: true }).isDisabled(), true);
    assert.equal(await page.getByRole("button", { name: "Rate response", exact: true }).count(), 1);
    streamFailure = null;
    historyFailure = false;
    await page.getByRole("button", { name: "Regenerate response", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "not saved or restored" }).waitFor();
    assert.equal(await page.getByText("Incomplete response · Regenerate to retry.", { exact: true }).count(), 0);
  }
  await page.getByRole("status").filter({ hasText: "not saved or restored" }).waitFor();
  assert.equal(await page.locator("pre code .hljs-keyword").count(), 1);
  await page
    .getByRole("button", { name: "Regenerate response", exact: true })
    .click();
  await page.getByText("world", { exact: true }).waitFor();
  await page.getByRole("button", { name: "Options for New conversation", exact: true }).click();
  await page.getByRole("menuitem", { name: "Rename", exact: true }).click();
  await page.getByRole("dialog").getByLabel("Name", { exact: true }).fill("Renamed");
  await page.getByRole("dialog").getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("button", { name: "Renamed", exact: true }).waitFor();
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    const composer = await page.getByLabel("Message Abud", { exact: true }).boundingBox();
    assert.ok(composer.width > 100 && composer.x >= 0 && composer.x + composer.width <= width);
  }
  await page.getByRole("button", { name: "Options for Renamed", exact: true }).click();
  await page.getByRole("menuitem", { name: "Delete", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete permanently", exact: true }).click();
  await page.getByText("Talk with Abud", { exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log(
    "PASS: Google-only UI, loading guard, create/send, Markdown/highlighting, truncated/malformed/error streams with unavailable history, incomplete labels, duplicate-send guard, regenerate, rename/delete, 320/390/768/1280px layouts (mock HTTP).",
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
