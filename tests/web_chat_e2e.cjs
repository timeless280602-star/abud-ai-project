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
    const context = await browser.newContext({ ignoreHTTPSErrors: true, timezoneId: "Asia/Jakarta", locale: "id-ID" });
    await context.addInitScript(() => {
      window.spoken = [];
      window.speechStops = 0;
      window.SpeechSynthesisUtterance = function(text) { this.text = text; };
      Object.defineProperty(window, "speechSynthesis", { configurable: true, value: {
        getVoices: () => [{ lang: "id-ID" }, { lang: "en-US" }],
        speak: (utterance) => { window.activeUtterance = utterance; window.spoken.push({ text: utterance.text, lang: utterance.lang }); },
        cancel: () => { window.speechStops++; },
      } });
    });
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
      .fill("remember that I like");
    await page.getByLabel("Message Abud", { exact: true }).press("Shift+Enter");
    await page.getByLabel("Message Abud", { exact: true }).pressSequentially("coffee");
    assert.equal(await page.getByLabel("Message Abud", { exact: true }).inputValue(), "remember that I like\ncoffee");
    assert.equal(await page.locator("article.chat-message").count(), 0);
    // IME confirmation must not send a message.
    await page.getByLabel("Message Abud", { exact: true }).dispatchEvent("keydown", { key: "Enter", isComposing: true });
    assert.equal(await page.locator("article.chat-message").count(), 0);
    await page.getByLabel("Message Abud", { exact: true }).press("Enter");
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
    assert.equal(await page.locator("time.chat-time").count(), 2);
    assert.ok(await page.locator("time.chat-time").first().evaluate((time) => {
      const expected = new Intl.DateTimeFormat(undefined, {
        year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
      }).format(new Date(time.dateTime));
      return time.textContent === expected && Intl.DateTimeFormat().resolvedOptions().timeZone === "Asia/Jakarta";
    }));
    const localStamp = await page.locator("time.chat-time").first().textContent();
    const otherZone = await browser.newContext({ ignoreHTTPSErrors: true, timezoneId: "America/New_York", locale: "id-ID", storageState: await context.storageState() });
    await otherZone.route("**/*", (r) => r.request().url().startsWith(url) ? r.continue() : r.abort());
    const otherPage = await otherZone.newPage();
    await otherPage.goto(url);
    await otherPage.getByRole("button", { name: history.title, exact: true }).click();
    await otherPage.locator("time.chat-time").first().waitFor();
    assert.notEqual(await otherPage.locator("time.chat-time").first().textContent(), localStamp);
    assert.equal(await otherPage.locator("time.chat-time").first().getAttribute("datetime"), history.messages[0].created_at);
    await otherZone.close();
    assert.equal(await page.getByRole("button", { name: "Good response", exact: true }).count(), 0);
    await page.getByRole("button", { name: "Read aloud", exact: true }).click();
    assert.equal(await page.evaluate(() => window.spoken[0].lang), "en-US");
    assert.ok(!(await page.evaluate(() => window.spoken[0].text)).includes("Copy"));
    await page.getByRole("button", { name: "Stop reading", exact: true }).click();
    assert.equal(await page.evaluate(() => window.speechStops), 1);
    await page.getByRole("button", { name: "Rate response", exact: true }).click();
    await page.getByRole("button", { name: "Good response", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "Feedback saved" }).waitFor();
    const rated = await (await context.request.get(url + "/web/chat/conversations/" + cid)).json();
    assert.equal(rated.messages[1].rating, "good");
    await page.reload();
    await page
      .getByRole("button", { name: history.title, exact: true })
      .click();
    await page.getByText("world", { exact: true }).waitFor();
    assert.ok((await page.getByRole("button", { name: "Rate response", exact: true }).textContent()).includes("Good"));
    await page.getByRole("button", { name: "Rate response", exact: true }).click();
    await page.getByRole("button", { name: "Bad response", exact: true }).click();
    assert.equal(await page.getByRole("button", { name: "Submit feedback", exact: true }).isDisabled(), true);
    for (const width of [320, 390, 768]) {
      await page.setViewportSize({ width, height: 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const field = await page.getByLabel("What was wrong or should be improved?", { exact: true }).boundingBox();
      assert.ok(field.width > 100 && field.x >= 0 && field.x + field.width <= width);
    }
    await page.setViewportSize({ width: 1280, height: 844 });
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      const box = await page.getByLabel("What was wrong or should be improved?", { exact: true }).boundingBox();
      assert.ok(box.width > 100 && box.x >= 0 && box.x + box.width <= width);
    }
    await page.getByLabel("What was wrong or should be improved?", { exact: true }).fill("Use shorter paragraphs next time.");
    await page.getByRole("button", { name: "Submit feedback", exact: true }).click();
    await page.getByRole("status").filter({ hasText: "Feedback saved" }).waitFor();
    const corrected = await (await context.request.get(url + "/web/chat/conversations/" + cid)).json();
    assert.equal(corrected.messages[1].rating, "bad");
    assert.equal(corrected.messages[1].feedback_reason, "Use shorter paragraphs next time.");
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
    assert.equal((await bob.request.post(url + `/web/chat/conversations/${cid}/messages/${history.messages[1].id}/feedback`, {
      data: { rating: "good" }, headers: { Origin: url },
    })).status(), 404);
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
    await page.getByRole("button", { name: "＋ New conversation", exact: true }).click();
    await page.getByLabel("Message Abud", { exact: true }).fill("[test-id]");
    await page.waitForFunction(() => !Array.from(document.querySelectorAll("button")).find((b) => b.textContent === "Send").disabled);
    await page.getByLabel("Message Abud", { exact: true }).press("Enter");
    await page.getByText("Halo, saya bisa membantu Anda dengan pertanyaan ini.", { exact: true }).waitFor();
    await page.getByRole("button", { name: "Read aloud", exact: true }).click();
    assert.equal(await page.evaluate(() => window.spoken.at(-1).lang), "id-ID");
    await page.evaluate(() => window.activeUtterance.onerror());
    await page.getByRole("alert").filter({ hasText: "Could not read" }).waitFor();
    await page.getByRole("button", { name: "Read aloud", exact: true }).waitFor();
    console.log(
      "PASS: HTTPS FastAPI + built React + real sessions/SQLite; Enter/Shift+Enter/IME, local timestamps, speech controls (mock speech engine), good/bad feedback persistence, streaming, reload, regenerate, isolation, CSRF, errors, mobile and deletion. Only AI/OAuth and speech engine are simulated.",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
