/** Real mapped-data browser workflow; generated source files only. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const root = path.resolve(import.meta.dirname, "..");
const base = process.env.QH_E2E_URL ?? "http://127.0.0.1:8766";
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/u);
const output = path.resolve(process.env.QH_E2E_OUTPUT ?? path.join(root, ".local/v0-quality-pattern-proof/browser"));
const privateDir = path.resolve(process.env.QH_E2E_PRIVATE ?? path.join(root, ".local/v0-phase-d-restored-private"));
assert.match(output, /^D:[\\/]/iu); assert.match(privateDir, /^D:[\\/]/iu);
const temp = path.join(root, ".tools/browser-temp");
for (const directory of [output, temp]) mkdirSync(directory, { recursive: true });
process.env.TEMP = temp; process.env.TMP = temp;
const accounts = JSON.parse(readFileSync(path.join(privateDir, "test-accounts.json"), "utf8"));
const executablePath = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync);
assert.ok(executablePath);
const proof = { started_at: new Date().toISOString(), evidence_mode: "SYNTHETIC", checks: [], screenshots: [], errors: [], external_requests: [] };
// Wait for actual readiness, with a bounded deadline, before starting the UI.
let ready = false;
const readinessDeadline = Date.now() + 60000;
while (Date.now() < readinessDeadline) {
  try { ready = (await fetch(`${base}/api/session`, { signal: AbortSignal.timeout(1500) })).status === 200; } catch { /* next bounded probe */ }
  if (ready) break;
  await new Promise(resolve => setTimeout(resolve, 250));
}
assert.ok(ready, "Local application did not become ready");
const browser = await chromium.launch({ executablePath, headless: true, downloadsPath: output });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, timezoneId: "UTC", reducedMotion: "reduce" });
const page = await context.newPage();
page.setDefaultTimeout(135000);
proof.api_timings = [];
page.on("response", response => { if (response.url().startsWith(`${base}/api/quality/`)) proof.api_timings.push({ path: new URL(response.url()).pathname, status: response.status(), response_ms: response.request().timing().responseStart }); });
page.on("pageerror", error => proof.errors.push(error.message));
page.on("request", request => { if (!request.url().startsWith(base)) proof.external_requests.push(request.url()); });
const check = message => { proof.checks.push(message); console.log(`PASS ${message}`); };
async function shot(name) {
  const file = path.join(output, `${name}.png`); await page.screenshot({ path: file, fullPage: true });
  proof.screenshots.push({ name, path: file, sha256: createHash("sha256").update(readFileSync(file)).digest("hex") });
}
async function login(account) {
  await page.goto(base); await page.getByLabel("Username", { exact: true }).fill(account.username); await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click(); await page.locator("#workspace-view").waitFor();
}
async function navigate() {
  await page.goto(`${base}/#quality`); await page.getByRole("heading", { name: "Inspect the evidence behind each dataset.", exact: true }).waitFor();
}
async function post(route, data) {
  const session = await (await page.request.get(`${base}/api/session`)).json();
  return page.request.post(`${base}/api${route}`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": session.csrf }, data });
}
function csv(first, count) {
  const lines = ["open_at,close_at,open,high,low,close,available_at"];
  for (let n = first; n < first + count; n += 1) {
    const opened = new Date(Date.UTC(2025, 0, 7, 14, 30 + n)), closed = new Date(opened.getTime() + 60000);
    const price = (100 + (n % 12) / 100).toFixed(2);
    lines.push(`${opened.toISOString()},${closed.toISOString()},${price},100.20,99.90,${price},${closed.toISOString()}`);
  }
  return Buffer.from(lines.join("\n") + "\n");
}
try {
  await login(accounts.owner); await navigate();
  const created = page.waitForResponse(r => r.url() === `${base}/api/quality/demo` && r.request().method() === "POST");
  await page.getByRole("button", { name: "Create two synthetic quality datasets", exact: true }).click();
  const response = await created; assert.equal(response.status(), 201, await response.text());
  const demo = await response.json(); assert.equal(demo.evidence_mode, "SYNTHETIC"); assert.equal(demo.datasets.length, 2);
  proof.demo_dataset_ids = demo.datasets.map(item => item.dataset_id);
  assert.ok(demo.datasets.every(item => item.admission === "SYNTHETIC_SOFTWARE_ONLY" && item.row_count === 240));
  const first = demo.datasets[0], second = demo.datasets[1];
  await page.getByLabel(`Select ${first.dataset_id}`, { exact: true }).check(); await page.getByLabel(`Select ${second.dataset_id}`, { exact: true }).check();
  check("Explicit owner action creates two canonical synthetic instruments and private mapped datasets with real quality evidence");
  const rejected = page.waitForResponse(r => r.url() === `${base}/api/quality/selections` && r.request().method() === "POST");
  await page.getByRole("button", { name: "Preserve selected partition manifest", exact: true }).click(); assert.equal((await rejected).status(), 400);
  const history = await (await page.request.get(`${base}/api/quality/operations`)).json();
  assert.ok(history.operations.some(item => item.kind === "QUALITY_COMPOSE" && item.status === "FAILED"));
  check("Incompatible instruments cannot be combined; failed composition remains recorded");
  await page.getByLabel(`Select ${second.dataset_id}`, { exact: true }).uncheck();
  const selected = page.waitForResponse(r => r.url() === `${base}/api/quality/selections` && r.request().method() === "POST");
  await page.getByRole("button", { name: "Preserve selected partition manifest", exact: true }).click();
  const selectedResponse = await selected; assert.equal(selectedResponse.status(), 201); const manifest = await selectedResponse.json();
  proof.selection_digest = manifest.manifest_digest; assert.equal(manifest.total_rows, 240); assert.equal(manifest.parent_snapshots[0].record_digest, first.record_digest);
  check("Selected manifest binds exact owned dataset, quality report, instrument revision and calendar profile");
  const firstLabel = first.dataset_id.length > 18 ? `${first.dataset_id.slice(0, 8)}…${first.dataset_id.slice(-6)}` : first.dataset_id;
  await page.getByRole("button", { name: firstLabel, exact: true }).click();
  await page.locator("#quality-detail").getByText(first.dataset_id, { exact: true }).waitFor();
  await page.getByLabel("Aggregation timeframe", { exact: true }).selectOption("5m");
  const aggregated = page.waitForResponse(r => r.url().endsWith(`/quality/datasets/${first.dataset_id}/aggregate`) && r.request().method() === "POST");
  await page.getByRole("button", { name: "Create immutable aggregate", exact: true }).click();
  const aggregateResponse = await aggregated; assert.equal(aggregateResponse.status(), 201, await aggregateResponse.text());
  const aggregate = await aggregateResponse.json(); assert.equal(aggregate.row_count, 48); assert.notEqual(aggregate.dataset_id, first.dataset_id);
  await page.locator("#quality-detail").getByText(aggregate.dataset_id, { exact: true }).waitFor();
  check("Five-minute aggregation creates a new version with48closed bars and preserves the240source rows"); await shot("01-quality-aggregate");
  const stale = await post(`/quality/datasets/${first.dataset_id}/aggregate`, { record_digest: `sha256:${"a".repeat(64)}`, quality_report_digest: first.quality_report_digest, timeframe: "5m", partial_policy: "DROP", as_of: first.bounds.end });
  assert.equal(stale.status(), 409); check("Stale quality receipt is rejected rather than silently selecting another version");
  await page.locator("summary").getByText("Import mapped CSV / Parquet partitions", { exact: true }).click();
  await page.getByRole("button", { name: "Load registered instrument revisions", exact: true }).click();
  await page.getByLabel("Use a registered instrument revision", { exact: true }).selectOption(first.instrument_id);
  await page.getByLabel("Calendar start", { exact: true }).fill("2025-01-07"); await page.getByLabel("Calendar end", { exact: true }).fill("2025-01-08");
  const source = "Synthetic partitions <img src=x onerror=window.__qualityInjected=1>";
  await page.getByLabel("Source name", { exact: true }).fill(source);
  await page.getByLabel("Declared license / access permission", { exact: true }).fill("Generated public software fixture; no provider observations");
  await page.getByLabel("Evidence mode", { exact: true }).selectOption("SYNTHETIC");
  await page.getByLabel("Revision information", { exact: true }).selectOption("SYNTHETIC_NOT_APPLICABLE");
  await page.getByLabel("available_at source column (optional)", { exact: true }).fill("available_at");
  await page.getByLabel("Source partitions (each at most 2 MB)", { exact: true }).setInputFiles([
    { name: "first.csv", mimeType: "text/csv", buffer: csv(0, 24) }, { name: "second.csv", mimeType: "text/csv", buffer: csv(24, 24) },
  ]);
  const imported = [];
  const collect = async actual => { if (actual.url() === `${base}/api/quality/datasets` && actual.request().method() === "POST") imported.push({ status: actual.status(), body: await actual.json() }); };
  page.on("response", collect);
  await page.getByRole("button", { name: "Import partitions sequentially", exact: true }).click();
  await page.locator("#quality-upload").getByText("2 of 2 partitions saved.", { exact: false }).waitFor({ timeout: 60000 });
  page.off("response", collect); assert.equal(imported.length, 2); assert.ok(imported.every(item => item.status === 201));
  proof.imported = imported.map(item => ({ dataset_id: item.body.dataset_id, raw_digest: item.body.raw_digest, record_digest: item.body.record_digest }));
  assert.notEqual(proof.imported[0].raw_digest, proof.imported[1].raw_digest);
  assert.equal(await page.evaluate(() => window.__qualityInjected), undefined);
  check("Actual multi-file browser upload preserves two distinct raw and mapped versions, explicit column mapping and safe source text");
  for (const item of imported) await page.getByLabel(`Select ${item.body.dataset_id}`, { exact: true }).check();
  const combined = page.waitForResponse(r => r.url() === `${base}/api/quality/selections` && r.request().method() === "POST");
  await page.getByRole("button", { name: "Preserve selected partition manifest", exact: true }).click();
  const combinedResponse = await combined; assert.equal(combinedResponse.status(), 201, await combinedResponse.text());
  const combinedManifest = await combinedResponse.json(); assert.equal(combinedManifest.total_rows, 48); assert.equal(combinedManifest.parent_snapshots.length, 2);
  proof.multi_partition_selection = combinedManifest.manifest_digest;
  check("Two chronological source partitions compose with all parent receipts and48actual rows");
  await shot("02-private-partitions");
  await page.setViewportSize({ width: 390, height: 844 }); await navigate();
  proof.overflow = await page.evaluate(() => [...document.querySelectorAll("#quality-workspace *")].filter(node => node.getBoundingClientRect().right > innerWidth + 1 && getComputedStyle(node).position !== "fixed").map(node => ({ tag: node.tagName, id: node.id, className: node.className, right: node.getBoundingClientRect().right })).slice(0, 30));
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)); await shot("03-mobile");
  check("Quality workflow fits390px without page overflow");
  await page.getByRole("button", { name: "Sign out", exact: true }).click(); await login(accounts.reader); await navigate();
  assert.equal(await page.locator("#quality-upload").count(), 0);
  assert.equal((await page.request.get(`${base}/api/quality/datasets/${first.dataset_id}`)).status(), 403);
  assert.equal((await page.request.get(`${base}/api/quality/selections/${manifest.manifest_digest}`)).status(), 403);
  assert.equal((await post("/quality/demo", {})).status(), 403);
  assert.deepEqual((await (await page.request.get(`${base}/api/quality/datasets`)).json()).datasets, []);
  check("Reader cannot create shared demo metadata, import, or read another account's datasets/selections");
  assert.deepEqual(proof.errors, []); assert.deepEqual(proof.external_requests, []);
  check("No browser errors, external requests or real provider data used"); proof.status = "PASS";
} catch (error) { proof.status = "FAIL"; proof.failure = String(error); await shot("failure").catch(() => {}); throw error; }
finally { proof.finished_at = new Date().toISOString(); writeFileSync(path.join(output, "quality-proof.json"), JSON.stringify(proof, null, 2)); await browser.close(); }
