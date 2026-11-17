const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const { url, token, cookieName } = JSON.parse(fs.readFileSync(0, "utf8"));
  const recording = path.resolve(process.argv[2]);
  const browser = await chromium.launch({
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      `--use-file-for-fake-audio-capture=${recording}`,
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  try {
    const context = await browser.newContext({ permissions: ["microphone"], ignoreHTTPSErrors: true });
    await context.addCookies([{ name: cookieName, value: token, url, httpOnly: true }]);
    const page = await context.newPage();
    page.setDefaultTimeout(120_000);
    await page.addInitScript(() => {
      const play = Audio.prototype.play;
      Audio.prototype.play = function (...args) {
        if (this.src.startsWith("blob:")) {
          window.abudVoiceWavHeader = fetch(this.src)
            .then((response) => response.blob())
            .then((blob) => blob.slice(0, 4).text());
          this.addEventListener("playing", () => { window.abudVoicePlaybackStarted = true; }, { once: true });
        }
        return play.apply(this, args);
      };
    });
    await page.goto(url);
    await page.getByRole("navigation").getByRole("button", { name: "AI Chat", exact: true }).click({ timeout: 30000 });
    await page.getByRole("button", { name: "＋ New conversation", exact: true }).click();
    await page.getByRole("button", { name: "Rekam suara", exact: true }).click();
    const stop = page.getByRole("button", { name: "Berhenti merekam", exact: true });
    await stop.waitFor();
    await page.waitForTimeout(4500);
    await stop.click();

    const send = page.getByRole("button", { name: "Kirim ke Ollama", exact: true });
    await send.waitFor();
    const draft = page.getByLabel("Message Abud", { exact: true });
    assert.match(await draft.inputValue(), /halo/i, "Whisper should transcribe the Indonesian greeting");
    const prompt = "Halo Abud. Jawab dalam satu kalimat pendek dalam bahasa Indonesia.";
    await draft.fill(prompt);
    const wavResponse = page.waitForResponse((response) =>
      /\/voice\/messages\/\d+\/audio$/.test(new URL(response.url()).pathname)
    );
    await send.click();
    const audio = await wavResponse;
    assert.equal(audio.status(), 200);
    assert.match(audio.headers()["content-type"], /^audio\/wav/);
    await page.waitForFunction(() => window.abudVoicePlaybackStarted === true, null, { timeout: 15000 });
    assert.equal(await page.evaluate(() => window.abudVoiceWavHeader), "RIFF");
    const conversation = new URL(audio.url()).pathname.split("/").slice(0, 5).join("/");
    const messages = await (await context.request.get(url + conversation)).json();
    assert.equal(messages.messages.at(-2).content, prompt);
    assert.equal(messages.messages.at(-1).voice, 1);
    assert.ok(messages.messages.at(-1).content.trim());
    const branchResponse = page.waitForResponse((response) =>
      /\/messages\/\d+\/branch$/.test(new URL(response.url()).pathname)
    );
    await page.getByRole("button", { name: "Branch in new chat" }).click();
    const branch = await branchResponse;
    assert.equal(branch.status(), 201);
    const { id } = await branch.json();
    const replay = await (await context.request.get(`${url}/web/chat/conversations/${id}`)).json();
    assert.deepEqual(replay.messages.map((message) => message.content), messages.messages.map((message) => message.content));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Open chat history" }).click();
    await page.getByRole("navigation", { name: "Conversations" }).waitFor();
    await page.getByRole("button", { name: "Close chat history", exact: true }).click();
    await page.getByLabel("Add attachment", { exact: true }).click();
    await page.getByRole("button", { name: /Upload a document/ }).waitFor();
    console.log("Passed: Chromium recording, Whisper transcript, Ollama response, Piper WAV, saved history, branch, mobile history and attachment menu.");
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
