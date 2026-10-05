/** Real owned publication browser workflow; synthetic documents only. */
import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const root = path.resolve(import.meta.dirname, "..");
const base = process.env.QH_E2E_URL ?? "http://127.0.0.1:8766";
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/u);
const output = path.resolve(process.env.QH_E2E_OUTPUT ?? path.join(root, ".local/v0-publication-proof/browser"));
const privateDir = path.resolve(process.env.QH_E2E_PRIVATE ?? path.join(root, ".local/v0-phase-d-restored-private"));
assert.match(output, /^D:[\\/]/iu); assert.match(privateDir, /^D:[\\/]/iu); assert.notEqual(output, privateDir);
const temp = path.join(root, ".tools/browser-temp"); for (const dir of [output, temp]) mkdirSync(dir, { recursive: true });
process.env.TEMP = temp; process.env.TMP = temp;
const accounts = JSON.parse(readFileSync(path.join(privateDir, "test-accounts.json"), "utf8"));
const executablePath = ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"].find(existsSync); assert.ok(executablePath);
const proof = { started_at: new Date().toISOString(), evidence_mode: "SYNTHETIC", checks: [], screenshots: [], errors: [], external_requests: [] };
const browser = await chromium.launch({ executablePath, headless: true, downloadsPath: output });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, timezoneId: "UTC", reducedMotion: "reduce" });
const page = await context.newPage();
page.on("pageerror", error => proof.errors.push(error.message));
page.on("request", request => { if (!request.url().startsWith(base)) proof.external_requests.push(request.url()); });
const check = message => { proof.checks.push(message); console.log(`PASS ${message}`); };
function syntheticPdf() {
  const content = "BT /F1 10 Tf 10 50 Td (Synthetic native PDF proof) Tj ET";
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>", "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", `<< /Length ${content.length} >>\nstream\n${content}\nendstream`];
  let data = "%PDF-1.4\n"; const offsets = [0];
  objects.forEach((value, i) => { offsets.push(Buffer.byteLength(data)); data += `${i + 1} 0 obj\n${value}\nendobj\n`; });
  const xref = Buffer.byteLength(data); data += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(data, "ascii");
}
async function shot(name) {
  const file = path.join(output, `${name}.png`); await page.screenshot({ path: file, fullPage: true });
  proof.screenshots.push({ name, path: file, sha256: createHash("sha256").update(readFileSync(file)).digest("hex"), at: new Date().toISOString() });
}
async function login(account) {
  await page.goto(base); await page.getByLabel("Username", { exact: true }).fill(account.username); await page.getByLabel("Password", { exact: true }).fill(account.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click(); await page.locator("#workspace-view").waitFor();
}
async function detail() { const response = await page.request.get(`${base}/api/publications/${proof.paper_id}`); assert.equal(response.status(), 200); return response.json(); }
async function submitForm(id, buttonName, suffix = "") {
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url() === `${base}/api/publications/${proof.paper_id}${suffix}`);
  await page.locator(id).getByRole("button", { name: buttonName, exact: true }).click(); const actual = await response; assert.equal(actual.status(), 200, await actual.text());
  await page.locator("#publication-detail h2").waitFor();
  // Await the actual revision refresh, not an arbitrary delay.
  const value = await actual.json(); await page.locator("#publication-detail").getByText(value.revision_digest, { exact: true }).waitFor(); return value;
}
async function disclosure(name) { const summary = page.locator("#publication-detail summary").filter({ hasText: name }); await summary.click(); }
try {
  await login(accounts.owner); await page.goto(`${base}/#publications`); await page.getByRole("heading", { name: "Publication library", exact: true }).waitFor();
  const references = await (await page.request.get(`${base}/api/publication-reference-catalog`)).json();
  assert.equal(references.references.length, 10);
  await page.locator("summary").filter({ hasText: "CRP-01 · Time Series Momentum" }).click();
  await page.getByRole("button", { name: "Register CRP-01 reference", exact: true }).click();
  await page.locator("#publication-detail h2").getByText("Time Series Momentum", { exact: true }).waitFor();
  const cards = await (await page.request.get(`${base}/api/publications`)).json();
  const source = cards.publications.find(p => p.metadata.title === "Time Series Momentum");
  assert.ok(source); assert.equal(source.text_access, "UNAVAILABLE"); assert.equal(source.reading.status, "UNREAD"); assert.ok(source.dossier.equation_links.length);
  proof.canonical_paper_id = source.paper_id; check("Ten source cards are available; explicit registration retains a private method dossier without retrieval or reading claims");
  const url = `https://example.org/quant-hunter-synthetic-${randomBytes(4).toString("hex")}.pdf`;
  await page.getByLabel("DOI or public HTTPS URL", { exact: true }).fill(url);
  const created = page.waitForResponse(r => r.url().endsWith("/api/publications") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Register reference", exact: true }).click(); const result = await created; assert.equal(result.status(), 201); const paper = await result.json(); proof.paper_id = paper.paper_id;
  await page.locator("#publication-detail").getByText(paper.revision_digest, { exact: true }).waitFor();
  assert.equal(paper.reading.status, "UNREAD"); assert.equal(paper.text_access, "UNAVAILABLE"); check("Reference creates actual permanent PAPER identity without fetching or claiming reading");
  await disclosure("Edit bibliographic metadata");
  const title = "Synthetic paper <img src=x onerror=window.__paperInjected=1>";
  await page.getByLabel("Publication title", { exact: true }).fill(title); await page.getByLabel("Authors (semicolon-separated)", { exact: true }).fill("Synthetic Fixture Author");
  await page.getByLabel("Publication year", { exact: true }).fill("2020"); await page.getByLabel("Publication version", { exact: true }).fill("synthetic-v1");
  await submitForm("#publication-metadata", "Save publication metadata");
  assert.equal(await page.evaluate(() => window.__paperInjected), undefined); await page.getByRole("heading", { name: title, exact: true }).waitFor(); check("Bibliographic metadata appends a real revision and hostile title is rendered as text");
  await disclosure("Attach a source document");
  const text = "Synthetic verification document. Equation QH-1: final cash = initial cash + net proceeds. No published or empirical result is asserted.";
  await page.getByLabel("PDF or UTF-8 text", { exact: true }).setInputFiles({ name: "synthetic-method.txt", mimeType: "text/plain", buffer: Buffer.from(text) });
  await page.getByLabel("Declared document license or access permission", { exact: true }).fill("Generated synthetic test fixture");
  await submitForm("#publication-attachment", "Attach immutable document", "/attachment");
  let current = await detail(); assert.equal(current.reading.status, "UNREAD");
  await disclosure("Extract text with bounded resources"); await submitForm("#publication-extract", "Extract selected pages", "/extract");
  current = await detail(); assert.equal(current.text_access, "COMPLETE"); assert.equal(current.reading.status, "UNREAD");
  await page.getByRole("button", { name: "Inspect extracted text", exact: true }).click(); await page.locator("#publication-text").getByText(text, { exact: false }).waitFor();
  check("Immutable text attachment and actual extraction preserve separate access and reading states"); await shot("01-extracted-text");
  await disclosure("Declare reading status"); await page.getByLabel("Declared reading status", { exact: true }).selectOption("FULL"); await page.getByLabel("Reading note", { exact: true }).fill("Read the complete single-page generated fixture in this browser test."); await page.getByLabel("Pages actually read (comma-separated)", { exact: true }).fill("1");
  await submitForm("#publication-reading", "Save reading declaration"); current = await detail(); assert.equal(current.reading.status, "FULL"); assert.equal(current.reading.text_digest, current.text.text_digest); check("Explicit reading declaration binds the exact extracted text and pages");
  await disclosure("Method, equations and limitations"); await page.getByLabel("Research question", { exact: true }).fill("Does immutable publication metadata preserve a synthetic method annotation?"); await page.getByLabel("Limitations", { exact: true }).fill("Synthetic workflow fixture; no external paper or empirical reproduction."); await submitForm("#publication-dossier", "Save methodological dossier");
  await disclosure("Map equations to implementation and oracles"); await page.getByRole("button", { name: "Add equation mapping", exact: true }).click();
  await page.getByLabel("Equation or source section 1", { exact: true }).fill("Synthetic equation QH-1"); await page.getByLabel("Implementation function 1", { exact: true }).fill("Synthetic annotation only; no function verification claim"); await page.getByLabel("Equation assumptions 1", { exact: true }).fill("No fees, positions or empirical observations in this document fixture"); await page.getByLabel("Independent oracle or test reference 1", { exact: true }).fill("Controlled text round-trip assertion in publication-smoke.mjs");
  await submitForm("#publication-equations", "Save equation mappings"); current = await detail(); assert.equal(current.dossier.equation_links.length, 1); check("Methodological dossier and equation-to-test annotations persist in immutable revisions");
  const jobs = await (await page.request.get(`${base}/api/jobs`)).json(); const ownExperiment = jobs.find(j => j.experiment_id)?.experiment_id; assert.ok(ownExperiment);
  await disclosure("Link governed experiments"); await page.getByLabel("Reproduction evidence", { exact: true }).selectOption("LINKED_EXPERIMENTS"); await page.getByLabel("Owned experiment IDs (comma-separated)", { exact: true }).fill(ownExperiment); await submitForm("#publication-reproduction", "Save experiment links"); current = await detail(); assert.deepEqual(current.reproduction.experiment_ids, [ownExperiment]); check("An actual owned experiment links without creating a scientific approval");
  const session = await (await page.request.get(`${base}/api/session`)).json();
  const stale = await page.request.post(`${base}/api/publications/${proof.paper_id}`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": session.csrf }, data: { expected_digest: paper.revision_digest, metadata: current.metadata } }); assert.equal(stale.status(), 409); check("Stale publication revision is rejected and retained");
  await disclosure("Attach a source document");
  const pdf = syntheticPdf(); proof.pdf_sha256 = createHash("sha256").update(pdf).digest("hex");
  await page.getByLabel("PDF or UTF-8 text", { exact: true }).setInputFiles({ name: "synthetic-native.pdf", mimeType: "application/pdf", buffer: pdf });
  await page.getByLabel("Declared document license or access permission", { exact: true }).fill("Generated synthetic PDF fixture");
  await submitForm("#publication-attachment", "Attach immutable document", "/attachment");
  assert.equal((await detail()).reading.status, "UNREAD");
  await disclosure("Extract text with bounded resources"); await submitForm("#publication-extract", "Extract selected pages", "/extract");
  const pdfText = await (await page.request.get(`${base}/api/publications/${proof.paper_id}/text`)).json();
  assert.equal(pdfText.pages[0].text, "Synthetic native PDF proof"); assert.equal(pdfText.ocr, false);
  check("Actual production web.main extracts generated PDF in bounded native child; replacement resets reading");
  await shot("02-dossier-evidence"); await page.setViewportSize({ width: 390, height: 844 }); await page.goto(`${base}/#publications`); await page.getByRole("heading", { name: "Publication library", exact: true }).waitFor(); assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)); await shot("03-mobile"); check("Publication library fits390px without page overflow");
  await page.getByRole("button", { name: "Sign out", exact: true }).click(); await login(accounts.reader); await page.goto(`${base}/#publications`); await page.getByRole("heading", { name: "Publication library", exact: true }).waitFor(); assert.equal(await page.locator("#publication-create").count(), 0);
  assert.equal((await page.request.get(`${base}/api/publications/${proof.paper_id}`)).status(), 403); const reader = await (await page.request.get(`${base}/api/session`)).json(); const denied = await page.request.post(`${base}/api/publications`, { headers: { "X-QH-Request": "1", "X-CSRF-Token": reader.csrf }, data: { url } }); assert.equal(denied.status(), 403); check("Reader cannot create or access another account's private publication");
  assert.deepEqual(proof.errors, []); assert.deepEqual(proof.external_requests, []); check("No browser errors or external retrievals occurred"); proof.status = "PASS";
} catch (error) { proof.status = "FAIL"; proof.failure = String(error); await shot("failure").catch(() => {}); throw error; }
finally { proof.finished_at = new Date().toISOString(); writeFileSync(path.join(output, "publication-proof.json"), JSON.stringify(proof, null, 2)); await browser.close(); }
