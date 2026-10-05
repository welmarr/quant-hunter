/** Real browser/worker/Item8 proof. Synthetic inputs only; all output stays on D:. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const repository = path.resolve(import.meta.dirname, "..");
const base = process.env.QH_E2E_URL ?? "http://127.0.0.1:8766";
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/u);
const output = path.resolve(process.env.QH_E2E_OUTPUT ?? path.join(repository, ".local/v0-phase-d-proof/studies-browser"));
const privateDir = path.resolve(process.env.QH_E2E_PRIVATE ?? path.join(repository, ".local/v0-phase-d-browser-private"));
assert.match(output, /^D:[\\/]/iu); assert.match(privateDir, /^D:[\\/]/iu);
assert.notEqual(output, privateDir);
const temporary = path.join(repository, ".tools/browser-temp");
for (const directory of [output, temporary]) mkdirSync(directory, { recursive: true });
process.env.TEMP = temporary; process.env.TMP = temporary;
const accounts = JSON.parse(readFileSync(path.join(privateDir, "test-accounts.json"), "utf8"));
const executablePath = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
assert.ok(executablePath);
const proof = { started_at: new Date().toISOString(), reference: process.env.QH_E2E_REFERENCE ?? "uncommitted exact runtime snapshot", evidence_mode: "SYNTHETIC", checks: [], screenshots: [], jobs: [], errors: [], external_requests: [] };
const browser = await chromium.launch({ executablePath, headless: true, downloadsPath: output });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, timezoneId: "UTC", reducedMotion: "reduce" });
const page = await context.newPage();
page.on("pageerror", error => proof.errors.push(error.message));
page.on("request", request => { if (!request.url().startsWith(base)) proof.external_requests.push(request.url()); });
const check = message => { proof.checks.push(message); console.log(`PASS ${message}`); };
async function screenshot(name) {
  const file = path.join(output, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  proof.screenshots.push({ name, path: file, sha256: createHash("sha256").update(readFileSync(file)).digest("hex"), captured_at: new Date().toISOString(), viewport: page.viewportSize() });
}
async function login(account) {
  await page.goto(base);
  await page.getByLabel("Username", { exact: true }).fill(account.username);
  await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.locator("#workspace-view").waitFor();
}
async function study(studyId, scenario = "POSITIVE", failed = false) {
  await page.goto(`${base}/#studies`);
  const form = page.locator("#study-form"); await form.waitFor();
  await form.getByLabel("Study method", { exact: true }).selectOption(studyId);
  await form.getByLabel("Study scenario", { exact: true }).selectOption(scenario);
  const submitted = page.waitForResponse(response => response.url().endsWith("/api/studies/jobs") && response.request().method() === "POST");
  await form.getByRole("button", { name: "Run study", exact: true }).click();
  const response = await submitted; assert.equal(response.status(), 202);
  const job = await response.json();
  let detail;
  for (let i = 0; i < 120; i += 1) {
    detail = await (await page.request.get(`${base}/api/jobs/${job.id}`)).json();
    if (["SUCCEEDED", "FAILED"].includes(detail.job.status)) break;
    await page.waitForTimeout(500);
  }
  assert.equal(detail.job.status, failed ? "FAILED" : "SUCCEEDED", JSON.stringify(detail.job));
  assert.equal(detail.run.variants_attempted, 1);
  assert.equal(detail.run.evaluation_outcome, failed ? "FAILED" : "INCONCLUSIVE");
  assert.equal(detail.run.decision, null);
  await page.locator("#run-detail .panel-head .badge").filter({ hasText: failed ? "FAILED" : "SUCCEEDED" }).waitFor({ timeout: 20000 });
  if (!failed) {
    assert.equal(detail.run.result.study_id, studyId);
    assert.equal(detail.run.result.assessment, "EMPIRICALLY_UNVALIDATED");
    assert.equal(await page.getByRole("table", { name: "Actual study metrics", exact: true }).locator("tbody tr").count(), Object.keys(detail.run.result.metrics).length);
    assert.equal(await page.locator("#run-detail .stat-value").count(), 0, "Study cannot display invented cash-backtest summary");
    assert.equal(detail.run.result.config_digest, detail.run.bindings.configuration_digest);
    assert.equal(detail.run.result.input_digest, detail.run.bindings.dataset_digest);
  } else assert.equal(detail.run.variant_accounting.failed_attempts, 1);
  proof.jobs.push({ study_id: studyId, scenario, job_id: job.id, experiment_id: detail.job.experiment_id, status: detail.job.status, result_digest: detail.run.result_digest, configuration_digest: detail.run.bindings.configuration_digest, dataset_digest: detail.run.bindings.dataset_digest });
  await screenshot(`${studyId}-${scenario}`);
  check(`${studyId} ${scenario}: actual frozen experiment, computed ${failed ? "retained failure" : "result"}, one counted variant and private provenance`);
  return detail;
}
try {
  await login(accounts.owner);
  await page.goto(`${base}/#studies`); await page.locator("#study-form").waitFor();
  assert.equal(await page.getByLabel("Study method", { exact: true }).locator("option").count(), 12);
  check("Studies catalogue exposes ten CRP methods and two explicitly synthetic comparison baselines");
  for (const method of ["CRP-01", "CRP-02", "CRP-03", "CRP-04", "CRP-05", "CRP-06", "CRP-07", "CRP-08", "CRP-09", "CRP-10", "ENS-COV", "META-OOF"]) await study(method);
  for (const method of ["CRP-05", "CRP-07", "CRP-08"]) await study(method, "NULL", true);
  await study("CRP-01", "SENSITIVITY");
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await screenshot("mobile-study-result"); check("Mobile Studies390px: no horizontal overflow");
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await login(accounts.reader);
  await page.goto(`${base}/#studies`); await page.locator("#study-form").waitFor();
  assert.ok(await page.getByRole("button", { name: "Run study", exact: true }).isDisabled());
  const session = await (await page.request.get(`${base}/api/session`)).json();
  assert.equal((await page.request.post(`${base}/api/studies/jobs`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": session.csrf }, data: { study_id: "CRP-01" } })).status(), 403);
  assert.equal((await page.request.get(`${base}/api/jobs/${proof.jobs[0].job_id}`)).status(), 403);
  await screenshot("reader-studies"); check("Reader sees method catalogue, cannot execute or read owner study results through UI or API");
  assert.deepEqual(proof.errors, []); assert.deepEqual(proof.external_requests, []);
  check("No uncaught browser errors or external requests"); proof.status = "PASS";
} catch (error) {
  proof.status = "FAIL"; proof.failure = String(error); process.exitCode = 1;
  await screenshot("failure").catch(() => {}); console.error(String(error));
} finally {
  proof.finished_at = new Date().toISOString();
  writeFileSync(path.join(output, "study-proof.json"), JSON.stringify(proof, null, 2));
  await browser.close(); console.log(`Evidence: ${output}`);
}
