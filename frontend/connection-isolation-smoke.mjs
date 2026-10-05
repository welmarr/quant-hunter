/** Hold one actual owner response across an account switch; never substitute data. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const repository = path.resolve(import.meta.dirname, "..");
const base = process.env.QH_E2E_URL ?? "http://127.0.0.1:8765";
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/u);
assert.ok(process.env.QH_E2E_PRIVATE && process.env.QH_E2E_OUTPUT);
const accounts = JSON.parse(readFileSync(path.join(process.env.QH_E2E_PRIVATE, "test-accounts.json"), "utf8"));
const output = path.resolve(process.env.QH_E2E_OUTPUT);
const temporary = path.resolve(repository, ".tools/browser-temp");
mkdirSync(output, { recursive: true }); mkdirSync(temporary, { recursive: true });
process.env.TEMP = temporary; process.env.TMP = temporary;
const executablePath = [process.env.QH_E2E_BROWSER, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(candidate => candidate && existsSync(candidate));
assert.ok(executablePath);
const evidence = { started_at: new Date().toISOString(), reference: process.env.QH_E2E_REFERENCE, base_url: base, test: "Delayed actual owner connection response after reader login", status: "RUNNING", errors: [], provider_requests: 0 };
const browser = await chromium.launch({ executablePath, headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, timezoneId: "UTC", reducedMotion: "reduce" });
const page = await context.newPage();
page.on("pageerror", error => evidence.errors.push(error.message));
page.on("request", request => { if (/\/api\/sources\/[^/]+\/probe$/u.test(request.url())) evidence.provider_requests += 1; });
let release;
const releaseResponse = new Promise(resolve => { release = resolve; });
let captured;
const capturedResponse = new Promise(resolve => { captured = resolve; });
let delivered;
const deliveredResponse = new Promise(resolve => { delivered = resolve; });
let privateRoot;
let requested = 0;
let readerActive = false;
let readerPrivateRequests = 0;
async function signIn(account) {
  await page.getByLabel("Username", { exact: true }).fill(account.username);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.locator('#main[aria-busy="false"] #workspace-view').waitFor();
}
try {
  await page.goto(base); await signIn(accounts.owner);
  await page.route(`${base}/api/connections`, async route => {
    requested += 1;
    if (readerActive) readerPrivateRequests += 1;
    const response = await route.fetch();
    assert.equal(response.status(), 200);
    const body = await response.body();
    const actual = JSON.parse(body.toString("utf8"));
    privateRoot = actual.private_root;
    assert.ok(typeof privateRoot === "string" && privateRoot.length);
    evidence.actual_response_sha256 = createHash("sha256").update(body).digest("hex");
    evidence.actual_response_state_count = actual.connections.length;
    captured();
    await releaseResponse;
    await route.fulfill({ response });
    delivered();
  });
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await Promise.race([capturedResponse, new Promise((_, reject) => { setTimeout(() => reject(new Error("Actual owner response was not captured")), 20000).unref(); })]);
  assert.equal(await page.locator("#connections-panel").innerText(), "Loading masked connection status…");
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await page.getByRole("button", { name: "Sign in", exact: true }).waitFor();
  readerActive = true;
  await signIn(accounts.reader);
  await page.getByText(/This account cannot view or change private connection settings/).waitFor();
  release(); await deliveredResponse;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await page.locator("#connections-panel").count(), 0);
  assert.equal(await page.locator('[id^="connection-form-"]').count(), 0);
  assert.ok(!(await page.locator("body").innerText()).includes(privateRoot));
  assert.equal((await (await page.request.get(`${base}/api/session`)).json()).user.role, "reader");
  assert.equal(requested, 1); assert.equal(readerPrivateRequests, 0);
  assert.equal(evidence.errors.length, 0); assert.equal(evidence.provider_requests, 0);
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
  const screenshot = path.join(output, "24-delayed-owner-response-reader.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  evidence.screenshot = { path: screenshot, viewport: page.viewportSize(), captured_at: new Date().toISOString(), url: page.url(), sha256: createHash("sha256").update(readFileSync(screenshot)).digest("hex") };
  evidence.status = "PASS";
  evidence.assertions = ["Delayed response came from the actual owner-authorized local API", "Response released only after successful reader login", "No owner vault path or connection form rendered for reader", "Reader made no private connection request", "No provider probes or uncaught errors"];
} catch (error) {
  evidence.status = "FAIL"; evidence.failure = error.message; process.exitCode = 1;
} finally {
  release();
  await browser.close();
  evidence.finished_at = new Date().toISOString();
  writeFileSync(path.join(output, "connection-isolation-proof.json"), JSON.stringify(evidence, null, 2));
  console.log(`${evidence.status}: ${path.join(output, "connection-isolation-proof.json")}`);
}
