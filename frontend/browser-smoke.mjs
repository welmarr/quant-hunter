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
const phaseB = process.env.QH_E2E_PHASE_B === "1";
const connectionsEnabled = process.env.QH_E2E_CONNECTIONS === "1";
const marketsEnabled = process.env.QH_E2E_MARKETS === "1";
let instrumentCreated = null;
let instrumentPayload = null;
let importedDataset = null;
let importPayload = null;
page.on("pageerror", error => evidence.errors.push(error.message));
page.on("dialog", dialog => { evidence.errors.push(`Unexpected browser dialog: ${dialog.type()}`); void dialog.dismiss(); });
const check = text => { evidence.checks.push(text); console.log(`PASS ${text}`); };
async function screenshot(name) {
  const file = path.join(output, `${name}.png`);
  await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); window.scrollTo(0, 0); });
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
async function importFile(name, buffer, fileFormat = "CSV", sourceName = "Browser synthetic evidence") {
  await route("data");
  await page.getByLabel("Dataset file", { exact: true }).setInputFiles({ name, mimeType: "application/octet-stream", buffer });
  await page.getByLabel("File format", { exact: true }).selectOption(fileFormat);
  await page.getByLabel("Source name", { exact: true }).fill(sourceName);
  await page.getByLabel("Declared licence / access rights", { exact: true }).fill("Generated synthetic test data; local test use permitted");
  await page.getByLabel("Instrument symbol", { exact: true }).fill("SYNTH-CSV");
  await page.getByLabel(/I have checked my right to store/).check();
  const responsePromise = page.waitForResponse(response => response.url().endsWith("/api/datasets") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Import dataset", exact: true }).click();
  return responsePromise;
}
async function phaseBProof() {
  await route("sources");
  await page.getByLabel("Search catalogue", { exact: true }).waitFor();
  const catalogue = await page.request.get(`${base}/api/sources`);
  assert.equal(catalogue.status(), 200);
  const sources = (await catalogue.json()).sources;
  assert.equal(sources.length, 22);
  assert.equal(await page.locator(".source-grid .panel").count(), 22);
  assert.equal(await page.getByRole("button", { name: "Probe public endpoint", exact: true }).count(), 2);
  await page.getByLabel("Search catalogue", { exact: true }).fill(sources[0].name);
  assert.ok(await page.locator(".source-grid .panel").count() >= 1);
  await page.getByLabel("Search catalogue", { exact: true }).fill("");
  await screenshot("15-source-catalogue");
  check("Source catalogue renders all22 actual entries with searchable capabilities and explicit implementation status");
  check("Only the two implemented public probes have actionable controls; default browser test makes no external probe request");
  if (process.env.QH_E2E_LIVE_PROBE === "1") {
    const before = (await (await page.request.get(`${base}/api/data-operations`)).json()).operations.length;
    const responsePromise = page.waitForResponse(response => response.url().endsWith("/api/sources/SRC-08/probe") && response.request().method() === "POST");
    await page.locator(".source-grid .panel").filter({ has: page.getByText("SRC-08", { exact: true }) }).getByRole("button", { name: "Probe public endpoint", exact: true }).click();
    const response = await responsePromise;
    evidence.external_probe = { catalogue_id: "SRC-08", http_status: response.status(), actual_response: await response.json() };
    const after = (await (await page.request.get(`${base}/api/data-operations`)).json()).operations;
    assert.ok(after.length > before);
    check("Explicitly enabled ECB probe retains its actual success or failure in data operation history");
  }
  const firstPagePromise = page.waitForResponse(response => response.url().endsWith("/api/datasets?limit=25&offset=0") && response.request().method() === "GET");
  await route("data");
  const firstPage = await (await firstPagePromise).json();
  assert.equal(firstPage.limit, 25);
  assert.equal(firstPage.offset, 0);
  assert.ok(firstPage.datasets.length <= 25);
  assert.ok(firstPage.total >= firstPage.datasets.length);
  await page.getByRole("navigation", { name: "Dataset pages", exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Previous datasets", exact: true }).isDisabled(), true);
  check("Data library uses a bounded first page with the actual total and explicit navigation");
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download synthetic CSV", exact: true }).click();
  const download = await downloadPromise;
  assert.match(download.suggestedFilename(), /SYNTHETIC/u);
  const samplePath = path.join(output, "sample-SYNTHETIC.csv"); await download.saveAs(samplePath);
  const bytes = readFileSync(samplePath);
  const imported = await importFile("synthetic-browser.csv", bytes);
  assert.ok([200, 201].includes(imported.status()), `CSV import returned${imported.status()}: ${await imported.text()}`);
  importedDataset = await imported.json();
  importPayload = imported.request().postDataJSON();
  assert.equal(importedDataset.row_count, 3);
  assert.ok(importedDataset.raw_digest.includes(createHash("sha256").update(bytes).digest("hex")));
  await page.getByText(/Import recorded: 3 rows/).waitFor();
  await page.getByText(importedDataset.raw_digest, { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Previous datasets", exact: true }).isDisabled(), true);
  await page.locator("#dataset-list").getByText(/Showing 1–/).waitFor();
  await screenshot("16-csv-import-evidence");
  check("Real browser CSV upload retains exact-byte raw SHA-256, rows, quality and dataset identity");
  const before = (await (await page.request.get(`${base}/api/datasets?limit=1&offset=0`)).json()).total;
  const rejected = await importFile("invalid-synthetic.csv", Buffer.from("open_at,close_at,open_bid,open_ask,close\n2025-01-06T14:30:00Z,2025-01-06T21:00:00Z,1,2,1.5\n"));
  assert.ok([400, 422].includes(rejected.status()), `InvalidCSV must be rejected, received${rejected.status()}`);
  await page.locator('#dataset-form [role="alert"]').waitFor();
  await screenshot("17-invalid-import-error");
  assert.equal((await (await page.request.get(`${base}/api/datasets?limit=1&offset=0`)).json()).total, before);
  check("Missing required availability time is rejected visibly without publishing a dataset version");
  const current = await apiSession();
  const correctionBytes = Buffer.from(bytes.toString("utf8").replace(",102,103,101,900", ",103,103,101,900"));
  const correction = await page.request.post(`${base}/api/datasets`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": current.csrf }, data: { ...importPayload, content_base64: correctionBytes.toString("base64"), corrects_dataset_id: importedDataset.dataset_id, correction_reason: "Synthetic correction retention check" } });
  assert.ok([200, 201].includes(correction.status()), `Correction returned${correction.status()}: ${await correction.text()}`);
  const corrected = await correction.json();
  assert.notEqual(corrected.dataset_id, importedDataset.dataset_id);
  assert.equal((await (await page.request.get(`${base}/api/datasets/${importedDataset.dataset_id}`)).json()).dataset_id, importedDataset.dataset_id);
  assert.equal((await (await page.request.get(`${base}/api/datasets/${corrected.dataset_id}`)).json()).dataset_id, corrected.dataset_id);
  check("Correction API creates a new immutable version and retains the original dataset");
  if (process.env.QH_E2E_PARQUET) {
    const parquet = await importFile("synthetic-browser.parquet", readFileSync(process.env.QH_E2E_PARQUET), "PARQUET");
    assert.ok([200, 201].includes(parquet.status()), `Parquet import returned${parquet.status()}: ${await parquet.text()}`);
    const result = await parquet.json();
    assert.ok(result.row_count > 0);
    await page.getByText(/Import recorded:/).waitFor();
    await screenshot("18-parquet-import-evidence");
    check("Native timezone-aware/numeric Parquet file imported through the real browser UI");
  }
  const literalMarkup = "<img src=x onerror=window.__qhImportedXss=true>";
  const xssImport = await importFile("synthetic-markup.csv", bytes, "CSV", literalMarkup);
  assert.equal(xssImport.status(), 201);
  const xssDataset = await xssImport.json();
  await page.locator("#dataset-detail").getByText(literalMarkup, { exact: true }).waitFor();
  assert.equal(await page.locator('img[src="x"]').count(), 0);
  assert.equal(await page.evaluate(() => window.__qhImportedXss === true), false);
  assert.equal(evidence.errors.length, 0);
  evidence.imported_markup_check = { dataset_id: xssDataset.dataset_id, source_name: xssDataset.metadata.source_name, rendered_as_literal_text: true, injected_image_count: 0, executed: false };
  await screenshot("21-imported-markup-literal");
  check("Imported hostile markup renders as literal text without an image, script flag, or dialog");
  await page.setViewportSize({ width: 390, height: 844 });
  await route("sources"); await page.getByLabel("Search catalogue", { exact: true }).waitFor();
  await noPageOverflow("Mobile source catalogue390px"); await screenshot("19-mobile-sources");
  await route("data"); await page.locator("#dataset-list .table-link").first().waitFor();
  await page.locator("#dataset-list .table-link").first().click();
  await noPageOverflow("Mobile data import/evidence390px"); await screenshot("20-mobile-data");
  await page.setViewportSize({ width: 1440, height: 1080 });
}
async function connectionProof() {
  let probeRequests = 0;
  const countProbe = request => { if (/\/api\/sources\/[^/]+\/probe$/u.test(request.url())) probeRequests += 1; };
  page.on("request", countProbe);
  const operationCount = (await (await page.request.get(`${base}/api/data-operations`)).json()).operations.length;
  await route("settings");
  await page.locator("#connection-form-SRC-01").waitFor();
  assert.equal(await page.locator('#connections-panel input[type="checkbox"]:checked').count(), 0);
  const privateInputs = page.locator('#connections-panel input[data-private-field="true"]:not([type="checkbox"])');
  for (const input of await privateInputs.all()) { assert.equal(await input.getAttribute("type"), "password"); assert.equal(await input.inputValue(), ""); }
  const initial = await (await page.request.get(`${base}/api/connections`)).json();
  assert.equal(initial.live_credentials, "FORBIDDEN");
  assert.ok(initial.connections.every(connection => connection.externally_validated === false));
  check("Owner sees only masked connection metadata, blank password fields and unchecked rights declarations");
  const fakeOrg = "Synthetic Browser Lab";
  const fakeEmail = "synthetic-browser@example.invalid";
  const fakeKey = `SYNTHETIC_KEY_${randomBytes(8).toString("hex")}`;
  const fakeSecret = `SYNTHETIC_SECRET_${randomBytes(16).toString("hex")}`;
  await page.getByLabel("SEC organization", { exact: true }).fill(fakeOrg);
  await page.getByLabel("SEC contact email", { exact: true }).fill(fakeEmail);
  await page.getByLabel("SEC company CIK", { exact: true }).fill("0000320193");
  await page.getByLabel(/I have reviewed the SEC access terms/).check();
  await page.getByRole("button", { name: "Save SEC connection", exact: true }).click();
  await page.getByText(/SRC-01 configuration saved privately/).waitFor();
  await page.getByLabel("Alpaca key ID", { exact: true }).fill(fakeKey);
  await page.getByLabel("Alpaca secret key", { exact: true }).fill(fakeSecret);
  await page.getByLabel("Alpaca credential source", { exact: true }).selectOption("PAPER_ACCOUNT");
  await page.getByLabel(/I confirm that this account is entitled/).check();
  await page.getByLabel(/I confirm this bounded access adds no incremental charge/).check();
  await page.getByRole("button", { name: "Save Alpaca connection", exact: true }).click();
  await page.getByText(/SRC-02 configuration saved privately/).waitFor();
  const masked = await (await page.request.get(`${base}/api/connections`)).json();
  assert.ok(masked.connections.every(connection => connection.state === "CONFIGURED" && connection.masked === "********" && connection.externally_validated === false));
  for (const value of [fakeOrg, fakeEmail, fakeKey, fakeSecret]) assert.ok(!JSON.stringify(masked).includes(value));
  for (const input of await privateInputs.all()) assert.equal(await input.inputValue(), "");
  assert.equal(await page.locator('#connections-panel input[type="checkbox"]:checked').count(), 0);
  const storage = await page.evaluate(() => JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }));
  for (const value of [fakeOrg, fakeEmail, fakeKey, fakeSecret]) assert.ok(!storage.includes(value));
  await screenshot("22-private-connections-masked");
  check("Synthetic SEC/Alpaca settings save through real UI/API without exposing or storing plaintext in the browser");
  await page.getByLabel("Alpaca secret key", { exact: true }).fill("SYNTHETIC_UNSAVED_SECRET");
  const oldField = await page.getByLabel("Alpaca secret key", { exact: true }).elementHandle();
  await route("overview");
  assert.equal(await oldField.evaluate(input => input.value), ""); await oldField.dispose();
  await route("sources");
  await page.getByRole("button", { name: "Test configured source", exact: true }).first().waitFor();
  assert.equal(await page.getByRole("button", { name: "Test configured source", exact: true }).count(), 2);
  check("Navigation clears detached private fields; only configured owner sources expose explicit test actions");
  await route("settings");
  await page.getByRole("button", { name: "Rotate vault encryption key", exact: true }).waitFor();
  const rotationPromise = page.waitForResponse(response => response.url().endsWith("/api/connections/rotate") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Rotate vault encryption key", exact: true }).click();
  const rotated = await rotationPromise; assert.equal(rotated.status(), 200);
  const rotation = await rotated.json(); assert.ok(rotation.versions_rotated >= 2);
  await page.getByText("Vault encryption key rotated.", { exact: true }).waitFor();
  evidence.synthetic_connection_rotation = { versions_rotated: rotation.versions_rotated, old_keys_retained: rotation.old_keys_retained, protection: rotation.protection };
  check("Owner rotates actual encrypted test-vault versions through the UI and sees the returned protection limits");
  const badCsrf = await page.request.post(`${base}/api/connections/SRC-01/revoke`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": "incorrect" }, data: {} });
  assert.equal(badCsrf.status(), 403);
  for (const [name, id] of [["Revoke SEC connection", "SRC-01"], ["Revoke Alpaca connection", "SRC-02"]]) {
    await page.getByRole("button", { name, exact: true }).click();
    await page.getByText(`${id} connection revoked.`, { exact: true }).waitFor();
    await page.locator(`[data-connection="${id}"]`).getByText("REVOKED", { exact: true }).waitFor();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow("Mobile private settings390px"); await screenshot("23-private-connections-revoked-mobile");
  await page.setViewportSize({ width: 1440, height: 1080 });
  await route("sources"); await page.getByLabel("Search catalogue", { exact: true }).waitFor();
  await page.locator(".source-grid .panel").filter({ has: page.getByText("SRC-01", { exact: true }) }).getByText("REVOKED", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Test configured source", exact: true }).count(), 0);
  assert.equal((await (await page.request.get(`${base}/api/data-operations`)).json()).operations.length, operationCount);
  assert.equal(probeRequests, 0); page.off("request", countProbe);
  check("Revocation removes configured test actions; CSRF is enforced and save/rotate/revoke make zero provider-probe requests");
}
async function deniedConnectionProof() {
  let privateRequests = 0;
  const countRequest = request => { if (request.url().includes("/api/connections")) privateRequests += 1; };
  page.on("request", countRequest);
  await route("settings"); await page.getByText(/This account cannot view or change private connection settings/).waitFor();
  assert.equal(await page.locator('[id^="connection-form-"]').count(), 0);
  await route("sources"); await page.getByLabel("Search catalogue", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Test configured source", exact: true }).count(), 0);
  assert.equal(privateRequests, 0); page.off("request", countRequest);
  const current = await apiSession();
  assert.equal((await page.request.get(`${base}/api/connections`)).status(), 403);
  assert.equal((await page.request.post(`${base}/api/connections/rotate`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": current.csrf }, data: {} })).status(), 403);
  check(`${current.user.role}: private settings perform no connection read and direct configuration/rotation API access is denied`);
}
async function marketsProof() {
  await route("markets");
  await page.locator("#instrument-create-form").waitFor();
  const oldSymbol = `SYNTH${randomBytes(3).toString("hex").toUpperCase()}`;
  const newSymbol = `${oldSymbol}B`;
  await page.getByLabel("Instrument ticker / pair", { exact: true }).fill(oldSymbol);
  await page.getByLabel("Activity begins (UTC)", { exact: true }).fill("2020-01-01T00:00:00Z");
  await page.getByLabel("Instrument source reference", { exact: true }).fill("Synthetic browser fixture; no real listing or publication assertion");
  const createPromise = page.waitForResponse(response => response.url().endsWith("/api/instruments") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Register instrument", exact: true }).click();
  const created = await createPromise; assert.equal(created.status(), 201);
  instrumentCreated = await created.json(); instrumentPayload = created.request().postDataJSON();
  assert.equal(instrumentCreated.record.revision, 1); assert.equal(instrumentCreated.revision_count, 1);
  assert.equal(instrumentCreated.record.evidence_mode, "SYNTHETIC");
  assert.equal(instrumentCreated.historical_availability, "LOCAL_RECORDED_TIME_ONLY");
  assert.equal(instrumentCreated.empirically_validated, false);
  assert.match(instrumentCreated.record.instrument_id, /^INSTRUMENT-/u);
  await page.locator("#instrument-detail").getByText(instrumentCreated.digest, { exact: true }).waitFor();
  await page.getByLabel("New historical ticker", { exact: true }).fill(newSymbol);
  await page.getByLabel("New ticker begins (UTC)", { exact: true }).fill("2025-01-01T00:00:00Z");
  await page.getByLabel("Correction reason", { exact: true }).fill("Synthetic historical ticker correction; retain prior local knowledge");
  const correctionPromise = page.waitForResponse(response => response.url().endsWith(`/api/instruments/${instrumentCreated.record.instrument_id}`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "Append ticker correction", exact: true }).click();
  const correctionResponse = await correctionPromise; assert.equal(correctionResponse.status(), 200);
  const corrected = await correctionResponse.json();
  assert.equal(corrected.record.instrument_id, instrumentCreated.record.instrument_id);
  assert.equal(corrected.record.revision, 2); assert.equal(corrected.revision_count, 2);
  assert.equal(corrected.record.previous_revision_digest, instrumentCreated.digest);
  assert.deepEqual(corrected.record.instrument.symbols.map(row => row.symbol), [oldSymbol, newSymbol]);
  await page.locator("#instrument-detail").getByText(corrected.digest, { exact: true }).waitFor();
  assert.equal(await page.getByRole("table", { name: "Instrument historical symbols", exact: true }).locator("tbody tr").count(), 2);
  check("Markets UI creates a stable synthetic identity and appends a ticker correction with both canonical revisions retained");
  const current = await apiSession();
  const stale = await page.request.post(`${base}/api/instruments/${instrumentCreated.record.instrument_id}`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": current.csrf }, data: { ...instrumentPayload, expected_digest: instrumentCreated.digest } });
  assert.equal(stale.status(), 409);
  assert.equal((await (await page.request.get(`${base}/api/instruments/${instrumentCreated.record.instrument_id}`)).json()).revision_count, 2);
  check("Stale canonical instrument digest is rejected without replacing the latest revision");
  await page.getByLabel("Known by the app (UTC)", { exact: true }).fill(instrumentCreated.record.recorded_at);
  await page.getByLabel("Effective instrument time (UTC)", { exact: true }).fill("2025-06-01T12:00:00Z");
  await page.getByRole("button", { name: "Look up historical metadata", exact: true }).click();
  await page.locator("#instrument-asof-result").getByText(oldSymbol, { exact: true }).waitFor();
  await page.locator("#instrument-asof-result").getByText(instrumentCreated.digest, { exact: true }).waitFor();
  await screenshot("25-markets-prior-knowledge");
  await page.getByLabel("Known by the app (UTC)", { exact: true }).fill(corrected.record.recorded_at);
  await page.getByRole("button", { name: "Look up historical metadata", exact: true }).click();
  await page.locator("#instrument-asof-result").getByText(newSymbol, { exact: true }).waitFor();
  check("Historical lookup distinguishes original local knowledge from a later correction at the same effective time");
  await page.getByLabel("Calendar start date", { exact: true }).fill("2025-11-27");
  await page.getByLabel("Calendar end date", { exact: true }).fill("2025-11-28");
  const nyPromise = page.waitForResponse(response => response.url().includes("/api/calendars/XNYS?") && response.request().method() === "GET");
  await page.getByRole("button", { name: "Load trading sessions", exact: true }).click();
  const nyResponse = await nyPromise; assert.equal(nyResponse.status(), 200); const ny = await nyResponse.json();
  assert.equal(ny.schedule.sessions.length, 1); assert.equal(ny.schedule.sessions[0].label, "2025-11-28");
  assert.equal(Date.parse(ny.schedule.sessions[0].close_at), Date.parse("2025-11-28T18:00:00Z"));
  await page.getByRole("table", { name: "Actual market trading sessions", exact: true }).getByText(ny.schedule.sessions[0].close_at, { exact: true }).waitFor();
  await screenshot("26-markets-nyse-early-close");
  check("Actual NYSE calendar excludes Thanksgiving and renders the next day's 18:00 UTC early close");
  await page.getByLabel("Market calendar", { exact: true }).selectOption("FX_NY_17");
  await page.getByLabel("Calendar start date", { exact: true }).fill("2025-03-07");
  await page.getByLabel("Calendar end date", { exact: true }).fill("2025-03-10");
  const fxPromise = page.waitForResponse(response => response.url().includes("/api/calendars/FX_NY_17?") && response.request().method() === "GET");
  await page.getByRole("button", { name: "Load trading sessions", exact: true }).click();
  const fxResponse = await fxPromise; assert.equal(fxResponse.status(), 200); const fx = await fxResponse.json();
  assert.deepEqual(fx.schedule.sessions.map(row => row.label), ["2025-03-07", "2025-03-10"]);
  assert.equal(Date.parse(fx.schedule.sessions[1].open_at), Date.parse("2025-03-09T21:00:00Z"));
  await page.getByRole("table", { name: "Actual market trading sessions", exact: true }).getByText(fx.schedule.sessions[1].open_at, { exact: true }).waitFor();
  await screenshot("27-markets-fx-weekend");
  check("Named FX convention skips weekend labels and handles the spring DST Sunday opening in UTC");
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow("Mobile Markets forms/history/calendar390px"); await screenshot("28-mobile-markets");
  await page.setViewportSize({ width: 1440, height: 1080 });
  evidence.instrument_checks = { instrument_id: instrumentCreated.record.instrument_id, original_registry_digest: instrumentCreated.digest, corrected_registry_digest: corrected.digest, original_recorded_at: instrumentCreated.record.recorded_at, corrected_recorded_at: corrected.record.recorded_at, nyse_calendar_digest: ny.digest, fx_calendar_digest: fx.digest };
}
async function deniedInstrumentProof() {
  const current = await apiSession();
  await route("markets");
  await page.getByText(/Your account can read shared instruments and calendars/).waitFor();
  assert.equal(await page.locator("#instrument-create-form").count(), 0);
  const shared = await page.request.get(`${base}/api/instruments/${instrumentCreated.record.instrument_id}`); assert.equal(shared.status(), 200);
  assert.equal((await shared.json()).record.instrument_id, instrumentCreated.record.instrument_id);
  const denied = await page.request.post(`${base}/api/instruments`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": current.csrf }, data: instrumentPayload });
  assert.equal(denied.status(), 403);
  check(`${current.user.role}: shared instrument metadata is readable while registration is denied by UI and API`);
}
try {
  await page.goto(base);
  const served = await page.request.get(`${base}/static/app.js`);
  assert.equal(served.status(), 200);
  assert.deepEqual(await served.body(), readFileSync(process.env.QH_E2E_EXPECTED_STATIC ?? path.join(repository, "src/quant_hunter/web/static/app.js")), "The served UI must match the tested source build");
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
  if (connectionsEnabled) await connectionProof();
  if (phaseB) await phaseBProof();
  if (marketsEnabled) await marketsProof();
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
  if (connectionsEnabled) await deniedConnectionProof();
  if (marketsEnabled) await deniedInstrumentProof();
  if (phaseB) {
    const privateDatasets = (await (await page.request.get(`${base}/api/datasets`)).json()).datasets;
    assert.ok(!privateDatasets.some(dataset => dataset.dataset_id === importedDataset.dataset_id));
    check("Researcher dataset listing excludes the owner's imported evidence");
  }
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
  if (connectionsEnabled) await deniedConnectionProof();
  if (marketsEnabled) await deniedInstrumentProof();
  if (phaseB) {
    await route("data"); await page.getByText(/Your reader role can inspect datasets/).waitFor();
    assert.equal(await page.getByRole("button", { name: "Import dataset", exact: true }).count(), 0);
    const deniedImport = await page.request.post(`${base}/api/datasets`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": readerSession.csrf }, data: importPayload });
    assert.equal(deniedImport.status(), 403);
    check("Reader dataset write is denied by UI and real API");
    await route("sources"); await page.getByLabel("Search catalogue", { exact: true }).waitFor();
    assert.equal(await page.getByRole("button", { name: "Probe public endpoint", exact: true }).count(), 0);
    const deniedProbe = await page.request.post(`${base}/api/sources/SRC-08/probe`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": readerSession.csrf }, data: {} });
    assert.equal(deniedProbe.status(), 403);
    check("Reader cannot trigger a public probe through the UI or direct API");
  }
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
