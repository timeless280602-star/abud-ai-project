// Run through run_web_chat_e2e.py, which supplies disposable sessions on stdin.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
(async () => {
  const { url, tokens } = JSON.parse(fs.readFileSync(0, "utf8"));
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    await context.route("**/*", (r) =>
      r.request().url().startsWith(url) ? r.continue() : r.abort(),
    );
    await context.addCookies([
      {
        name: "abud_session",
        value: tokens[0],
        url,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(url);
    await page.getByText("Talk with Abud", { exact: true }).waitFor();
    await page
      .getByRole("button", { name: "＋ New conversation", exact: true })
      .click();
    await page
      .getByLabel("Message Abud", { exact: true })
      .fill("remember that I like coffee");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByText("world", { exact: true }).waitFor();
    await page
      .getByRole("button", { name: "Regenerate response", exact: true })
      .waitFor({ state: "visible" });
    await page.waitForFunction(
      () =>
        !Array.from(document.querySelectorAll("button")).find(
          (b) => b.textContent === "Regenerate response",
        ).disabled,
    );
    assert.equal(await page.locator("pre code .hljs-keyword").count(), 1);
    const list = await (
      await context.request.get(url + "/web/chat/conversations")
    ).json();
    const cid = list[0].id;
    const history = await (
      await context.request.get(url + "/web/chat/conversations/" + cid)
    ).json();
    assert.deepEqual(
      history.messages.map((m) => m.role),
      ["user", "assistant"],
    );
    await page.reload();
    await page
      .getByRole("button", { name: "New conversation", exact: true })
      .click();
    await page.getByText("world", { exact: true }).waitFor();
    await page
      .getByRole("button", { name: "Regenerate response", exact: true })
      .click();
    await page.waitForFunction(
      () =>
        !Array.from(document.querySelectorAll("button")).find(
          (b) => b.textContent === "Regenerate response",
        ).disabled,
    );
    assert.equal(
      (
        await (
          await context.request.get(url + "/web/chat/conversations/" + cid)
        ).json()
      ).messages.length,
      2,
    );
    const bob = await browser.newContext({ ignoreHTTPSErrors: true });
    await bob.addCookies([
      {
        name: "abud_session",
        value: tokens[1],
        url,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    assert.deepEqual(
      await (await bob.request.get(url + "/web/chat/conversations")).json(),
      [],
    );
    assert.equal(
      (await bob.request.get(url + "/web/chat/conversations/" + cid)).status(),
      404,
    );
    assert.equal(
      (
        await context.request.post(url + "/web/chat/conversations", {
          data: {},
          headers: { Origin: "https://attacker.invalid" },
        })
      ).status(),
      403,
    );
    await page.getByLabel("Message Abud", { exact: true }).fill("[test-error]");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page
      .getByRole("alert")
      .filter({ hasText: "Unable to complete" })
      .waitFor();
    assert.equal(
      (
        await (
          await context.request.get(url + "/web/chat/conversations/" + cid)
        ).json()
      ).messages.length,
      3,
    );
    assert.ok(!(await page.content()).includes("private fixture error"));
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    assert.deepEqual(errors, []);
    await context.request.delete(url + "/web/chat/conversations/" + cid, {
      headers: { Origin: url },
    });
    assert.equal(
      (
        await context.request.get(url + "/web/chat/conversations/" + cid)
      ).status(),
      404,
    );
    console.log(
      "PASS: local HTTPS FastAPI + built React + real sessions/SQLite; streaming, Markdown, reload persistence, regenerate, user isolation, CSRF, failed-stream recovery, mobile layout and deletion. Only AI/OAuth are simulated.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
