/** Real local research UI; all created observations and accounts are synthetic. */
import assert from 'node:assert/strict';
import { randomBytes, createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
const root = path.resolve(import.meta.dirname, '..');
const base = process.env.QH_E2E_URL ?? 'http://127.0.0.1:8767';
assert.match(base, /^http:\/\/(localhost|127\.0\.0\.1):\d+$/u);
const output = path.resolve(process.env.QH_E2E_OUTPUT ?? path.join(root, '.local/v0-research-product-proof/browser-1'));
assert.match(output, /^D:[\\/]/iu);
mkdirSync(output, { recursive: true });
process.env.TEMP = path.join(root, '.tools/browser-temp'); process.env.TMP = process.env.TEMP;
mkdirSync(process.env.TEMP, { recursive: true });
const accountFile = path.join(root, '.local/v0-research-product-proof/test-accounts.json');
const accounts = existsSync(accountFile) ? JSON.parse(readFileSync(accountFile, 'utf8')) : Object.fromEntries(['owner','researcher','reader'].map(role => [role, { username: `proof_${role}`, password: randomBytes(24).toString('base64url'), role }]));
if (!existsSync(accountFile)) writeFileSync(accountFile, JSON.stringify(accounts), { flag: 'wx' });
const proof = { started_at: new Date().toISOString(), checks: [], errors: [], external_requests: [], screenshots: [] };
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true, downloadsPath: output });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, timezoneId: 'UTC', reducedMotion: 'reduce' });
const page = await context.newPage(); page.setDefaultTimeout(135000);
page.on('pageerror', error => proof.errors.push(error.message));
page.on('request', req => { if (!req.url().startsWith(base)) proof.external_requests.push(req.url()); });
const check = value => { proof.checks.push(value); console.log(`PASS ${value}`); };
async function post(route, data) {
  const session = await (await page.request.get(`${base}/api/session`)).json();
  return page.request.post(`${base}/api${route}`, { headers: { 'X-QH-Request': '1', 'X-CSRF-Token': session.csrf }, data });
}
async function screen(name) {
  const file = path.join(output, `${name}.png`); await page.screenshot({ path: file, fullPage: true });
  proof.screenshots.push({ path: file, sha256: createHash('sha256').update(readFileSync(file)).digest('hex') });
}
async function navigate(view) { await page.goto(`${base}/#${view}`); await page.locator('#workspace-view').waitFor(); }
async function jobDone(id) {
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    const res = await page.request.get(`${base}/api/jobs/${id}`, { timeout: 130000 });
    assert.equal(res.status(), 200, await res.text());
    const detail = await res.json();
    if (!['RUNNING','QUEUED'].includes(detail.job.status)) { assert.equal(detail.job.status, 'SUCCEEDED', JSON.stringify(detail)); return detail; }
    await new Promise(resolve => setTimeout(resolve, 750));
  }
  throw new Error('Bounded job completion deadline exceeded');
}
try {
  let ready = false;
  for (let attempt = 0; attempt < 120 && !ready; attempt++) {
    try { ready = (await fetch(`${base}/api/session`)).status === 200; } catch { /* bounded readiness */ }
    if (!ready) await new Promise(resolve => setTimeout(resolve, 250));
  }
  assert.ok(ready);
  const initial = await (await page.request.get(`${base}/api/session`)).json();
  await page.goto(base);
  await page.getByLabel('Username', { exact: true }).fill(accounts.owner.username);
  await page.getByLabel('Password', { exact: true }).fill(accounts.owner.password);
  await page.getByRole('button', { name: initial.needs_owner ? 'Create local owner' : 'Sign in', exact: true }).click();
  await page.locator('#workspace-view').waitFor();
  const existingUsers = await (await page.request.get(`${base}/api/users`)).json();
  for (const role of ['researcher','reader']) if (!existingUsers.some(user => user.username === accounts[role].username)) { const r = await post('/users', accounts[role]); assert.equal(r.status(), 200, await r.text()); }
  check('Real owner authentication and separate researcher/reader accounts');
  await navigate('quality');
  const created = page.waitForResponse(r => r.url().endsWith('/api/quality/demo') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create two synthetic quality datasets', exact: true }).click();
  const demoResponse = await created; assert.equal(demoResponse.status(), 201, await demoResponse.text());
  const dataset = (await demoResponse.json()).datasets[0]; proof.dataset_id = dataset.dataset_id;
  await page.getByLabel(`Select ${dataset.dataset_id}`, { exact: true }).check();
  const selectionResponse = page.waitForResponse(r => r.url().endsWith('/api/quality/selections') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Preserve selected partition manifest', exact: true }).click();
  const selection = await selectionResponse; assert.equal(selection.status(), 201, await selection.text());
  const manifest = await selection.json();
  await navigate('patterns'); await page.getByLabel('Owned partition selection', { exact: true }).selectOption(manifest.manifest_digest);
  const corpusQueued = page.waitForResponse(r => r.url().endsWith('/api/patterns/corpora') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Queue corpus build', exact: true }).click();
  const queuedResponse = await corpusQueued; assert.equal(queuedResponse.status(), 202, await queuedResponse.text());
  const corpusJob = await queuedResponse.json(); const corpusDetail = await jobDone(corpusJob.id);
  check('Actual queued immutable corpus completed');
  await page.getByRole('button', { name: 'Refresh Pattern workspace', exact: true }).click();
  await page.getByLabel('Owned corpus', { exact: true }).selectOption(corpusDetail.corpus.dataset_id);
  const previewResponse = page.waitForResponse(r => r.url().includes('/preview?start=') && r.request().method() === 'GET');
  await page.getByRole('button', { name: 'Inspect actual bars', exact: true }).click();
  await page.getByRole('button', { name: 'Refresh Pattern workspace', exact: true }).click();
  const preview = await previewResponse; assert.equal(preview.status(), 200, await preview.text());
  await page.locator('#pattern-workspace svg').first().waitFor();
  check('Literal preview survives concurrent workspace metadata refresh');
  await page.getByLabel('Pattern family', { exact: true }).selectOption('PAT-05');
  await page.getByLabel('Research scenario', { exact: true }).selectOption('POSITIVE');
  await page.getByRole('button', { name: 'Prepare and review exact protocol', exact: true }).click();
  await page.getByRole('button', { name: 'Queue this exact Pattern experiment', exact: true }).waitFor();
  await page.getByLabel('Pattern family', { exact: true }).selectOption('PAT-13');
  assert.equal(await page.getByRole('button', { name: 'Queue this exact Pattern experiment', exact: true }).count(), 0);
  await page.getByLabel('Pattern family', { exact: true }).selectOption('PAT-05');
  await page.getByRole('button', { name: 'Prepare and review exact protocol', exact: true }).click();
  const patternQueued = page.waitForResponse(r => r.url().endsWith('/api/patterns/jobs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Queue this exact Pattern experiment', exact: true }).click();
  const patternResponse = await patternQueued; assert.equal(patternResponse.status(), 202, await patternResponse.text());
  const patternJob = await patternResponse.json(); proof.pattern_job = patternJob.id;
  const patternResult = await jobDone(patternJob.id); assert.equal(patternResult.run.variants_attempted, 1);
  await page.getByText(`Job ${patternJob.id}: SUCCEEDED.`, { exact: false }).waitFor();
  check('Owned corpus, actual bars, stale protocol invalidation, learned PAT-05 and counted canonical result');
  await screen('pattern-desktop');
  await navigate('validation'); await page.getByLabel('Owned quality dataset', { exact: true }).selectOption(dataset.dataset_id);
  await page.getByText('All frozen split and uncertainty controls', { exact: true }).click();
  await page.getByLabel('Bootstrap confidence', { exact: true }).selectOption('0.90');
  const validationQueued = page.waitForResponse(r => r.url().endsWith('/api/validations/jobs') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Freeze and queue this candidate', exact: true }).click();
  const validationResponse = await validationQueued; assert.equal(validationResponse.status(), 202, await validationResponse.text());
  const validationJob = await validationResponse.json(); proof.validation_job = validationJob.id;
  const validationResult = await jobDone(validationJob.id); assert.ok(validationResult.run.result.canonical_models);
  await page.getByRole('button', { name: 'Inspect exact memberships and predictions', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Inspect exact memberships and predictions', exact: true }).click();
  await page.getByText('Full report metadata and source exclusions', { exact: true }).waitFor();
  check('Chronological candidate, exact confidence value, canonical model identities and actual fold report'); await screen('validation-desktop');
  await navigate('notifications'); await page.getByRole('button', { name: 'Create local test event', exact: true }).click();
  await page.getByRole('button', { name: 'Mark read', exact: true }).first().waitFor();
  const configuration = await (await page.request.get(`${base}/api/notifications/configuration`)).json(); assert.equal(configuration.enabled, false);
  check('Actual private local notification; external delivery disabled');
  await navigate('operations'); await page.getByText('RUNNING', { exact: true }).waitFor();
  check('Actual worker, database, private resource and storage observations');
  await page.setViewportSize({ width: 390, height: 844 }); await screen('operations-mobile');
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  await post('/logout', {}); await page.goto(`${base}/#patterns`);
  await page.getByLabel('Username', { exact: true }).fill(accounts.reader.username); await page.getByLabel('Password', { exact: true }).fill(accounts.reader.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click(); await page.locator('#workspace-view').waitFor();
  assert.equal((await page.request.get(`${base}/api/jobs/${patternJob.id}`)).status(), 403);
  assert.equal((await post('/patterns/jobs', { prepared_id: patternJob.config.prepared_id })).status(), 403);
  assert.equal((await page.request.get(`${base}/api/administration/users`)).status(), 403);
  check('Reader and foreign-account API boundaries enforced independently of UI');
  assert.deepEqual(proof.errors, []); assert.deepEqual(proof.external_requests, []); proof.finished_at = new Date().toISOString();
} catch (error) { proof.failure = error.stack; await screen('failure'); throw error; }
finally { writeFileSync(path.join(output, 'research-proof.json'), JSON.stringify(proof, null, 2)); await browser.close(); }
