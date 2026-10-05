/** Real local API + installed Chromium. Creates only synthetic test users/jobs. */
import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const repository = path.resolve(import.meta.dirname, "..");
const base = process.env.QH_E2E_URL ?? "http://127.0.0.1:8765";
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/u, "Browser proof must target a local test server");
const output = path.resolve(process.env.QH_E2E_OUTPUT ?? path.join(repository, ".local/v0-proof"));
const privateDir = path.resolve(process.env.QH_E2E_PRIVATE ?? path.join(repository, ".local/v0-browser-private"));
assert.notEqual(output, privateDir, "Test credentials must be separate from shareable evidence");
const temporary = path.resolve(repository, ".tools/browser-temp");
for (const directory of [output, privateDir, temporary]) mkdirSync(directory, { recursive: true });
process.env.TEMP = temporary;
process.env.TMP = temporary;
const executablePath = [process.env.QH_E2E_BROWSER, "C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(candidate => candidate && existsSync(candidate));
assert.ok(executablePath, "An installed Chrome/Edge browser is required; this test never downloads one");
const credentialPath = path.join(privateDir, "test-accounts.json");
const accounts = existsSync(credentialPath) ? JSON.parse(readFileSync(credentialPath, "utf8")) : {
  owner: { username: `proof_owner_${randomBytes(5).toString("hex")}`, password: randomBytes(24).toString("base64url") },
  researcher: { username: `proof_researcher_${randomBytes(5).toString("hex")}`, password: randomBytes(24).toString("base64url") },
  reader: { username: `proof_reader_${randomBytes(5).toString("hex")}`, password: randomBytes(24).toString("base64url") },
};
// Preserve the owner for reruns; exercise actual account creation each time.
for (const role of ["researcher", "reader"]) accounts[role] = { username: `proof_${role}_${randomBytes(5).toString("hex")}`, password: randomBytes(24).toString("base64url") };
writeFileSync(credentialPath, JSON.stringify(accounts), { mode: 0o600 });
const evidence = { started_at: new Date().toISOString(), base_url: base, reference: process.env.QH_E2E_REFERENCE ?? "uncommitted local test snapshot", evidence_mode: "SYNTHETIC", browser: "", checks: [], screenshots: [], errors: [] };
const browser = await chromium.launch({ executablePath, headless: true, downloadsPath: output });
evidence.browser = browser.version();
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, locale: "en-US", timezoneId: "UTC", reducedMotion: "reduce" });
const page = await context.newPage();
page.on("pageerror", error => evidence.errors.push(error.message));
const check = text => { evidence.checks.push(text); console.log(`PASS ${text}`); };
async function screenshot(name) {
  const file = path.join(output, `${name}.png`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: file, fullPage: true });
  evidence.screenshots.push({ name, path: file, viewport: page.viewportSize(), url: page.url(), captured_at: new Date().toISOString(), sha256: createHash("sha256").update(readFileSync(file)).digest("hex") });
}
async function route(view) {
  await page.goto(`${base}/#${view}`);
  await page.locator('#main[aria-busy="false"] #workspace-view').waitFor();
}
async function noPageOverflow(label) {
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, body: document.documentElement.scrollWidth }));
  assert.ok(dimensions.body <= dimensions.viewport, `${label} overflows: ${JSON.stringify(dimensions)}`);
  check(`${label}: no horizontal page overflow`);
}
async function apiSession() { const response = await page.request.get(`${base}/api/session`); assert.equal(response.status(), 200); return response.json(); }
async function signIn(account) {
  await page.goto(base);
  await page.getByLabel("Username", { exact: true }).fill(account.username);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.locator("#workspace-view").waitFor();
}
async function signOut() { await page.getByRole("button", { name: "Sign out", exact: true }).click(); await page.getByRole("button", { name: "Sign in", exact: true }).waitFor(); }
async function runMarket(market, expectedEquity) {
  await route("backtests");
  await page.getByLabel("Market fixture").selectOption(market);
  const responsePromise = page.waitForResponse(response => response.url().endsWith("/api/jobs") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Run backtest", exact: true }).click();
  const response = await responsePromise;
  assert.equal(response.status(), 202);
  const job = await response.json();
  await page.locator("#run-detail .stat-value").first().waitFor({ timeout: 45000 });
  let detail;
  for (let attempt = 0; attempt < 45; attempt += 1) {
    const response = await page.request.get(`${base}/api/jobs/${job.id}`);
    detail = await response.json();
    if (["COMPLETED", "SUCCEEDED"].includes(detail.job.status)) break;
    assert.notEqual(detail.job.status, "FAILED", `Actual job failed: ${detail.job.error}`);
    await page.waitForTimeout(1000);
  }
  assert.ok(["COMPLETED", "SUCCEEDED"].includes(detail.job.status));
  await page.locator("#run-detail .panel-head .badge").filter({ hasText: /SUCCEEDED|COMPLETED/u }).waitFor({ timeout: 10000 });
  assert.equal(detail.run.evidence_mode, "SYNTHETIC");
  assert.ok(detail.run.result.trades.length > 0);
  assert.equal(detail.run.result.equity_curve.length, 4);
  assert.equal(detail.run.lifecycle_status, "EVALUATED");
  assert.ok(detail.run.result_digest);
  if (expectedEquity !== undefined) assert.equal(Number(detail.run.result.summary.final_equity), expectedEquity);
  assert.equal(await page.locator("#run-detail .stat-value").first().innerText(), Number(detail.run.result.summary.final_equity).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  await page.getByText("View accessible chart data", { exact: true }).click();
  assert.equal(await page.getByRole("table", { name: "Exact cash and equity chart observations" }).locator("tbody tr").count(), 4);
  await page.getByText("View accessible chart data", { exact: true }).click();
  check(`${market}: real queued job, governed EVALUATED result, fills and accessible chart data`);
  return detail;
}
async function createUser(role) {
  await route("settings");
  await page.getByLabel("Username", { exact: true }).fill(accounts[role].username);
  await page.getByLabel("Initial password").fill(accounts[role].password);
  await page.getByLabel("Role", { exact: true }).selectOption(role);
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await page.getByText("Account created.", { exact: true }).waitFor();
  await page.getByRole("cell", { name: accounts[role].username, exact: true }).waitFor();
}
try {
  await page.goto(base);
  const served = await page.request.get(`${base}/static/app.js`);
  assert.equal(served.status(), 200);
  assert.deepEqual(await served.body(), readFileSync(path.join(repository, "src/quant_hunter/web/static/app.js")), "The served UI must match the tested source build");
  const initial = await apiSession();
  if (initial.needs_owner) {
    await screenshot("01-owner-setup");
    await page.getByLabel("Username", { exact: true }).fill(accounts.owner.username);
    await page.getByLabel("Password", { exact: true }).fill(accounts.owner.password);
    await page.getByRole("button", { name: "Create local owner", exact: true }).click();
    await page.locator("#workspace-view").waitFor();
    check("First-launch owner created through the real browser UI; no fixed credentials");
  } else if (!initial.user) await signIn(accounts.owner);
  assert.equal((await apiSession()).user.role, "owner");
  const cookie = (await context.cookies()).find(item => item.name === "qh_session");
  assert.ok(cookie?.httpOnly); assert.equal(cookie.sameSite, "Strict");
  check("Session cookie is HttpOnly and SameSite=Strict");
  await page.getByRole("heading", { name: "Research, with a clear record.", exact: true }).waitFor();
  await page.locator(".fixture-row").first().waitFor();
  await screenshot("02-overview"); await noPageOverflow("Desktop overview 1440px");
  const equity = await runMarket("EQUITY", 10008);
  let jobPolls = 0;
  const countJobPolls = request => { if (request.url().endsWith("/api/jobs") && request.method() === "GET") jobPolls += 1; };
  page.on("request", countJobPolls);
  await page.waitForTimeout(1500);
  page.off("request", countJobPolls);
  assert.equal(jobPolls, 0); check("Automatic job polling stops after terminal completion");
  await screenshot("03-equity-result"); await noPageOverflow("Desktop backtest 1440px");
  const fx = await runMarket("FX_SPOT");
  await screenshot("04-fx-result");
  evidence.result_checks = { equity_job_id: equity.job.id, equity_experiment_id: equity.job.experiment_id, equity_final_equity: equity.run.result.summary.final_equity, fx_job_id: fx.job.id, fx_experiment_id: fx.job.experiment_id, fx_final_equity: fx.run.result.summary.final_equity };
  await route("portfolio");
  await page.locator("#run-detail .stat-value").first().waitFor();
  await screenshot("05-portfolio");
  const csrf = (await apiSession()).csrf;
  const forbidden = await page.request.post(`${base}/api/jobs`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": "incorrect" }, data: equity.job.config });
  assert.equal(forbidden.status(), 403); check("Mutation with incorrect CSRF token is rejected by the real API");
  const ownerUsers = await page.request.get(`${base}/api/users`);
  const users = await ownerUsers.json();
  for (const role of ["researcher", "reader"]) if (!users.some(user => user.username === accounts[role].username)) await createUser(role);
  await route("settings"); await page.getByRole("cell", { name: accounts.reader.username, exact: true }).waitFor();
  await screenshot("06-owner-users"); check("Owner creates researcher and reader accounts through settings");
  await route("project"); await page.getByRole("heading", { name: "Project checkpoint", exact: true }).waitFor(); await screenshot("07-project-status");
  await route("overview"); await context.setOffline(true);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.getByText(/Cannot reach the local service/).waitFor();
  await screenshot("08-offline-error");
  await context.setOffline(false);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.getByText("Workspace refreshed from the local service.", { exact: true }).waitFor(); check("Real browser offline failure is visible and refresh recovers");
  await signOut();
  await page.getByLabel("Username", { exact: true }).fill(accounts.owner.username);
  await page.getByLabel("Password", { exact: true }).fill("invalid-test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByText("Invalid username or password", { exact: true }).waitFor();
  await page.getByLabel("Password", { exact: true }).fill("");
  await screenshot("09-login-error"); check("Incorrect credentials show the API error without authenticating");
  await signIn(accounts.researcher);
  const foreign = await page.request.get(`${base}/api/jobs/${equity.job.id}`); assert.equal(foreign.status(), 403);
  const ownedJobs = await page.request.get(`${base}/api/jobs`); assert.ok(!(await ownedJobs.json()).some(job => job.id === equity.job.id));
  const researcherUsers = await page.request.get(`${base}/api/users`); assert.equal(researcherUsers.status(), 403);
  check("Researcher cannot read owner job IDs/list or users through the API");
  await screenshot("10-researcher-isolated-overview");
  await runMarket("EQUITY", 10008); check("Researcher can execute its own governed synthetic backtest");
  await signOut(); await signIn(accounts.reader);
  await route("backtests"); await page.getByText(/Your reader account can inspect accessible results/).waitFor();
  assert.equal(await page.getByRole("button", { name: "Run backtest", exact: true }).count(), 0);
  const readerSession = await apiSession();
  const rejected = await page.request.post(`${base}/api/jobs`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": readerSession.csrf }, data: equity.job.config });
  assert.equal(rejected.status(), 403);
  const crossAccess = await page.request.get(`${base}/api/jobs/${equity.job.id}`); assert.equal(crossAccess.status(), 403);
  await screenshot("11-reader-restrictions"); check("Reader cannot submit jobs or read another user's result even through direct API requests");
  await signOut(); await signIn(accounts.owner);
  await page.setViewportSize({ width: 390, height: 844 });
  await route("overview"); await screenshot("12-mobile-overview"); await noPageOverflow("Mobile overview 390px");
  await page.getByRole("button", { name: "Toggle workspace navigation" }).click();
  await page.getByRole("link", { name: "Backtests", exact: true }).click();
  await page.locator("#backtest-form").waitFor();
  await page.locator("#job-list .table-link").first().click();
  await page.locator("#run-detail .stat-value").first().waitFor();
  await screenshot("13-mobile-backtest"); await noPageOverflow("Mobile backtest and chart 390px");
  await page.setViewportSize({ width: 320, height: 700 });
  await noPageOverflow("Narrow mobile backtest 320px");
  await page.setViewportSize({ width: 768, height: 1024 });
  await noPageOverflow("Tablet backtest 768px");
  await screenshot("14-tablet-backtest");
  assert.equal(evidence.errors.length, 0, `Uncaught browser errors: ${evidence.errors.join("; ")}`);
  assert.ok(csrf); check("No uncaught JavaScript errors during the real-browser workflow");
  evidence.status = "PASS";
} catch (error) {
  evidence.status = "FAIL";
  evidence.failure = error.message;
  await screenshot("failure-state").catch(() => {});
  process.exitCode = 1;
  console.error(error.message);
} finally {
  evidence.finished_at = new Date().toISOString();
  writeFileSync(path.join(output, "browser-proof.json"), JSON.stringify(evidence, null, 2));
  await browser.close();
  console.log(`Evidence: ${path.join(output, "browser-proof.json")}`);
}
