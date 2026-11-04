/** Actual local UI + API only. Draft: run after the root integrator's stable restart. */
import assert from 'node:assert/strict';
import { createHash, randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

const root = path.resolve(process.env.QH_PROJECT_ROOT ?? 'D:/quant-hunter');
assert.match(root, /^D:[\\/]/iu);
const { chromium } = createRequire(path.join(root, 'frontend/package.json'))('playwright');
const base = process.env.QH_E2E_URL ?? 'http://127.0.0.1:8767';
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/u);
const runTag = new Date().toISOString().replaceAll(':', '').replaceAll('.', '');
const output = path.resolve(process.env.QH_E2E_OUTPUT ?? path.join(root, `.local/v0-research-product-proof/product-${runTag}`));
const accountFile = path.resolve(process.env.QH_E2E_ACCOUNT_FILE ?? path.join(root, '.local/v0-research-product-proof/test-accounts.json'));
const privateDir = path.resolve(path.join(root, '.local/v0-product-browser-private'));
const temporary = path.resolve(path.join(root, '.tools/browser-temp'));
for (const location of [output, accountFile, privateDir, temporary]) assert.match(location, /^D:[\\/]/iu);
assert.ok(existsSync(accountFile), 'Existing research-browser account file required');
assert.ok(!existsSync(output), 'Use a NEW output directory to preserve earlier failures');
assert.ok(!accountFile.startsWith(output + path.sep) && output !== privateDir, 'Private credentials must stay outside this proof directory');
for (const directory of [output, privateDir, temporary]) mkdirSync(directory, { recursive: true });
process.env.TEMP = temporary; process.env.TMP = temporary;
const revision = process.env.QH_E2E_SOURCE_REVISION;
assert.match(revision ?? '', /^[a-f0-9]{40}$/u, 'Set QH_E2E_SOURCE_REVISION to the real source checkpoint; plan generation does not certify dirty source');
const accounts = JSON.parse(readFileSync(accountFile, 'utf8'));
const maintenance = { username: `product_${randomBytes(6).toString('hex')}`, password: randomBytes(24).toString('base64url'), role: 'researcher' };
writeFileSync(path.join(privateDir, `${runTag}-maintenance.json`), JSON.stringify(maintenance), { flag: 'wx', mode: 0o600 });
const secrets = [accounts.owner.password, accounts.reader.password, maintenance.password].filter(Boolean);
const safe = value => secrets.reduce((text, secret) => text.replaceAll(secret, '[REDACTED]'), String(value));
const proof = { started_at: new Date().toISOString(), base_url: base, reference: process.env.QH_E2E_REFERENCE ?? `${revision} plus current uncommitted integration`, evidence_mode: 'SYNTHETIC_SOFTWARE_TEST', checks: [], errors: [], external_requests: [], screenshots: [], mutations: [] };
const executablePath = process.env.QH_E2E_BROWSER ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
assert.ok(existsSync(executablePath));
const browser = await chromium.launch({ executablePath, headless: true, downloadsPath: output, args: ['--disable-background-networking', '--disable-component-update'] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, locale: 'en-US', timezoneId: 'UTC', reducedMotion: 'reduce' });
const page = await context.newPage(); page.setDefaultTimeout(135000);
proof.browser = browser.version();
page.on('pageerror', error => proof.errors.push(safe(error.message)));
page.on('dialog', dialog => { proof.errors.push(`Unexpected ${dialog.type()} dialog`); void dialog.dismiss(); });
page.on('request', request => { if (new URL(request.url()).origin !== base) proof.external_requests.push(safe(request.url())); });
const check = text => { proof.checks.push(text); console.log(`PASS ${text}`); };
const shortId = id => id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-6)}` : id;
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
async function get(route, request = page.request) {
  for (let attempt = 0; attempt < 6; attempt++) {
    const response = await request.get(`${base}/api${route}`, { timeout: 130000 });
    if (response.status() === 503 && attempt < 5) { await pause(3000); continue; }
    assert.equal(response.status(), 200, `GET ${route}: ${safe(await response.text())}`);
    return response.json();
  }
  throw new Error('Bounded read retry exhausted');
}
async function post(route, data, expected = 200, request = page.request) {
  const session = await get('/session', request);
  const response = await request.post(`${base}/api${route}`, { headers: { 'X-QH-Request': '1', 'X-CSRF-Token': session.csrf ?? '' }, data, timeout: 130000 });
  assert.equal(response.status(), expected, `POST ${route}: ${safe(await response.text())}`);
  return response.json(); // Mutations are never automatically retried.
}
async function navigate(view) { await page.goto(`${base}/#${view}`); await page.locator('#workspace-view').waitFor(); }
async function signIn(account) {
  await page.goto(base); await page.getByLabel('Username', { exact: true }).fill(account.username); await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click(); await page.locator('#workspace-view').waitFor();
}
async function screen(name) {
  await page.evaluate(() => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); window.scrollTo(0, 0); });
  const file = path.join(output, `${name}.png`); await page.screenshot({ path: file, fullPage: true });
  proof.screenshots.push({ name, path: file, captured_at: new Date().toISOString(), viewport: page.viewportSize(), url: page.url(), sha256: createHash('sha256').update(readFileSync(file)).digest('hex') });
}
async function mobile(name) {
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}: page overflow at390px`);
  await screen(`${name}-mobile`); check(`${name}: actual390px layout has no page overflow`);
  await page.setViewportSize({ width: 1440, height: 1080 });
}
async function findPaged(locator, nextLabel, bound = 40) {
  for (let n = 0; n < bound; n++) {
    if (await locator.count()) return;
    const next = page.getByRole('button', { name: nextLabel, exact: true });
    await next.waitFor(); if (await locator.count()) return;
    assert.equal(await next.isDisabled(), false, 'Expected owned record is absent from bounded pages');
    const resource = nextLabel === 'Next accounts' ? '/api/administration/users' : nextLabel === 'Next historical dataset page' ? '/api/quality/datasets' : null;
    const loaded = resource ? page.waitForResponse(response => new URL(response.url()).pathname === resource && response.request().method() === 'GET') : null;
    await next.click(); if (loaded) { const response = await loaded; assert.equal(response.status(), 200); await response.body(); }
    await pause(150);
  }
  throw new Error('Bounded UI pagination exhausted');
}

let secondary;
try {
  assert.equal((await get('/session')).needs_owner, false, 'Use the existing isolated8767runtime, not an empty owner bootstrap');
  await signIn(accounts.owner); assert.equal((await get('/session')).user.role, 'owner');
  const beforeJobs = await get('/jobs');
  const pattern = beforeJobs.find(job => job.status === 'SUCCEEDED' && job.experiment_id && job.config.kind === 'PATTERN_JOB');
  const validation = beforeJobs.find(job => job.status === 'SUCCEEDED' && job.experiment_id && job.config.kind === 'CHRONOLOGICAL_VALIDATION');
  assert.ok(pattern && validation, 'Complete existing research-smoke Pattern and validation runs before this product smoke');

  // Test data explicitly declares its artificial origin. HISTORICAL is only the
  // route admission under test; these generated prices are NOT market history.
  const symbol = `PUI${randomBytes(3).toString('hex').toUpperCase()}`;
  const instrument = await post('/instruments', {
    instrument: { asset_class: 'EQUITY', venue: 'XNYS', base_currency: 'USD', quote_currency: 'USD', price_precision: 2, quantity_precision: 0, lot_size: '1', tick_size: '0.01', multiplier: '1', timezone: 'America/New_York', calendar_id: 'XNYS', activity: [{ start: '2020-01-01T00:00:00Z', end: null }], symbols: [{ symbol, start: '2020-01-01T00:00:00Z', end: null }], status: 'ACTIVE' },
    reason: 'SYNTHETIC product UI oracle; no empirical claim', evidence_mode: 'SYNTHETIC', source_reference: 'Generated locally for chart-only software test',
  }, 201);
  const names = ['open_at', 'close_at', 'open', 'high', 'low', 'close', 'available_at', 'volume', 'revision_time'];
  const lines = [names.join(',')];
  for (const day of ['2025-01-06', '2025-01-07']) for (let minute = 0; minute < 390; minute++) {
    const opening = new Date(Date.parse(`${day}T14:30:00Z`) + minute * 60000).toISOString();
    const close = new Date(Date.parse(opening) + 60000).toISOString();
    lines.push(`${opening},${close},100,102,99,101,${close},2,${close}`);
  }
  const dataset = await post('/quality/datasets', {
    file_format: 'CSV', content_base64: Buffer.from(lines.join('\n') + '\n').toString('base64'),
    instrument_id: instrument.record.instrument_id, instrument_revision_digest: instrument.digest, calendar_start: '2025-01-06', calendar_end: '2025-01-07',
    metadata: { source_name: 'SYNTHETIC UI oracle with historical declaration for chart-only test', declared_license: 'Self-generated software fixture; no external data rights needed', evidence_mode: 'HISTORICAL', declared_restrictions: 'NOT genuine market history. Generated software test; causal research must remain blocked.', instrument: { symbol, asset_class: 'EQUITY', base_currency: 'USD', quote_currency: 'USD', quantity_step: '1' } },
    mapping: { columns: Object.fromEntries(names.map(name => [name, name])), timezone: 'OFFSET_REQUIRED', price_scale: '1', price_currency: 'USD', volume_unit: 'UNITS', reject_policy: 'REJECT_DATASET', revision_mode: 'KNOWN' },
  }, 201);
  proof.mutations.push({ kind: 'ARTIFICIAL_CHART_DECLARATION_FIXTURE', dataset_id: dataset.dataset_id, instrument_id: instrument.record.instrument_id, rows: 780 });
  await navigate('historical');
  const datasetButton = page.getByRole('button', { name: shortId(dataset.dataset_id), exact: true });
  await findPaged(datasetButton, 'Next historical dataset page'); await datasetButton.click();
  const count = page.getByLabel('Number of rows (maximum 512)', { exact: true }); await count.waitFor();
  await page.getByLabel('First normalized row (zero based)', { exact: true }).fill('388'); await count.fill('4');
  const inspectedResponse = page.waitForResponse(response => response.url() === `${base}/api/quality/inspections` && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Inspect and retain audit receipt', exact: true }).click();
  const inspected = await inspectedResponse; assert.equal(inspected.status(), 201, safe(await inspected.text()));
  const preview = await inspected.json(); assert.equal(preview.rows.length, 4); assert.equal(preview.snapshot.causal_eligible, false); assert.equal(preview.causal_research, 'BLOCKED');
  assert.equal(preview.rows[0].gap_before_ns, null); assert.ok(BigInt(preview.rows[2].gap_before_ns) > 0n);
  const visual = page.locator('#historical-preview'); await visual.locator('svg circle').first().waitFor();
  assert.equal(await visual.locator('svg circle').count(), 4); assert.equal(await visual.locator('svg path,svg polyline,svg line').count(), 0);
  assert.equal(await visual.locator('tbody tr').count(), 4); assert.ok((await visual.textContent()).includes(preview.rows[0].close_ns));
  for (const row of preview.rows) assert.ok((await visual.textContent()).includes(row.values[0]));
  assert.ok((await visual.textContent()).includes('Predecessor outside this page'));
  check('Actual4-row chart/table retains exact prices/ns and overnight gap with no interpolation or causal upgrade'); await screen('historical-desktop'); await mobile('historical');
  await page.getByRole('button', { name: 'Refresh inspection receipts', exact: true }).click();
  const auditButton = page.getByRole('button', { name: shortId(preview.inspection_id), exact: true }); await auditButton.waitFor(); await auditButton.click();
  await page.locator('#historical-audit-detail').getByText(`Inspection ${preview.inspection_id} · PREPARED`, { exact: true }).waitFor();
  const receipt = await get(`/quality/inspections/${preview.inspection_id}`); assert.equal(receipt.receipt_digest, preview.inspection_receipt_digest);
  await count.fill('513'); assert.equal(await count.evaluate(input => input.validity.rangeOverflow), true);
  const tooLarge = await page.request.post(`${base}/api/quality/inspections`, { headers: { 'X-QH-Request': '1', 'X-CSRF-Token': (await get('/session')).csrf }, data: { dataset_id: dataset.dataset_id, record_digest: dataset.record_digest, quality_report_digest: dataset.quality_report_digest, start: 0, stop: 513 } });
  assert.equal(tooLarge.status(), 400); check('Historical audit receipt remains inspectable; UI and real API reject ranges above512');

  await navigate('comparison');
  for (const job of [pattern, validation].sort((a, b) => beforeJobs.indexOf(a) - beforeJobs.indexOf(b))) {
    const box = page.getByLabel(`Compare ${job.id}`, { exact: true }); await findPaged(box, 'Next recorded runs page', 400); await box.check();
  }
  await page.getByRole('button', { name: 'Inspect selected results', exact: true }).click();
  const compared = page.getByRole('table', { name: 'Verified recorded experiment comparison', exact: true }); await compared.waitFor();
  assert.ok((await compared.textContent()).includes(pattern.experiment_id)); assert.ok((await compared.textContent()).includes(validation.experiment_id));
  assert.ok((await compared.textContent()).includes('sha256:'));
  assert.deepEqual((await get('/jobs')).map(job => job.id), beforeJobs.map(job => job.id));
  check('Two existing completed Pattern/validation experiments compare without adding a job or experiment'); await screen('comparison-desktop'); await mobile('comparison');

  await navigate('settings');
  await page.getByLabel('Username', { exact: true }).fill(maintenance.username); await page.getByLabel('Initial password', { exact: true }).fill(maintenance.password); await page.getByLabel('Role', { exact: true }).selectOption('researcher');
  const createdResponse = page.waitForResponse(response => response.url() === `${base}/api/users` && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Create account', exact: true }).click(); const created = await createdResponse; assert.equal(created.status(), 200);
  const user = await created.json(); proof.mutations.push({ kind: 'DEDICATED_MAINTENANCE_ACCOUNT', user_id: user.id, username: maintenance.username });
  await page.getByText('Account created.', { exact: true }).waitFor(); assert.equal(await page.getByLabel('Initial password', { exact: true }).inputValue(), '');
  secondary = await browser.newContext();
  async function maintenanceLogin() { const response = await secondary.request.post(`${base}/api/login`, { headers: { 'X-QH-Request': '1' }, data: { username: maintenance.username, password: maintenance.password } }); assert.equal(response.status(), 200); }
  await maintenanceLogin();
  const adminRole = page.getByLabel(`Role for ${maintenance.username}`, { exact: true }); await findPaged(adminRole, 'Next accounts');
  const card = page.locator('details').filter({ has: adminRole }); await card.locator('summary').click(); await adminRole.selectOption('reader');
  const roleResponse = page.waitForResponse(response => response.url().endsWith(`/administration/users/${user.id}/change`) && response.request().method() === 'POST');
  await card.getByRole('button', { name: 'Apply role', exact: true }).click(); const roleChanged = await roleResponse; assert.equal(roleChanged.status(), 200); const roleResult = await roleChanged.json(); assert.ok(roleResult.revoked_sessions >= 1);
  await page.getByText(`Account ${maintenance.username} updated. ${roleResult.revoked_sessions} session(s) revoked.`, { exact: true }).waitFor();
  assert.equal((await get('/session', secondary.request)).user, null); await maintenanceLogin();
  await navigate('settings');
  const refreshedRole = page.getByLabel(`Role for ${maintenance.username}`, { exact: true }); await findPaged(refreshedRole, 'Next accounts');
  const refreshed = page.locator('details').filter({ has: refreshedRole }); await refreshed.locator('summary').click(); assert.equal(await refreshedRole.inputValue(), 'reader');
  const revokedResponse = page.waitForResponse(response => response.url().endsWith(`/administration/users/${user.id}/change`) && response.request().method() === 'POST');
  await refreshed.getByRole('button', { name: 'Revoke all sessions', exact: true }).click(); const revoked = await revokedResponse; assert.equal(revoked.status(), 200); const revokeResult = await revoked.json(); assert.ok(revokeResult.revoked_sessions >= 1);
  await page.getByText(`Account ${maintenance.username} updated. ${revokeResult.revoked_sessions} session(s) revoked.`, { exact: true }).waitFor();
  assert.equal((await get('/session', secondary.request)).user, null);
  await page.getByText('Inspect retained account audit', { exact: true }).click(); await page.getByRole('table', { name: 'Owner account maintenance audit', exact: true }).waitFor();
  check('Dedicated synthetic account role change and explicit revocation end real sessions and retain account audit');

  const runtimeInput = page.getByLabel('Original runtime on D:', { exact: true }); await runtimeInput.waitFor();
  const project = await get('/project'); await runtimeInput.fill(project.runtime); await page.getByLabel('Exact source commit', { exact: true }).fill(revision);
  const archiveInput = page.getByLabel('New private archive on D:', { exact: true }); await archiveInput.fill('C:\\invalid.qhbackup');
  await page.getByRole('button', { name: 'Prepare offline commands', exact: true }).click(); await page.getByText('New archive must be an absolute path on D:, no longer than 240 characters.', { exact: true }).waitFor();
  await archiveInput.fill(`D:\\quant-hunter\\.local\\backups\\product-${runTag}.qhbackup`); await page.getByLabel('New restore destination on D:', { exact: true }).fill(`D:\\quant-hunter\\.local\\product-restored-${runTag}`);
  await page.getByRole('button', { name: 'Prepare offline commands', exact: true }).click(); await page.getByText('1. Stop and create a new archive', { exact: true }).waitFor();
  const backup = page.locator('section.panel').filter({ has: page.getByRole('heading', { name: 'Private backup and recovery', exact: true }) });
  const commands = await backup.locator('pre').allTextContents(); assert.equal(commands.length, 3); assert.ok(commands[0].includes('-m quant_hunter.web.backup create')); assert.ok(commands[1].includes('-m quant_hunter.web.backup restore')); assert.ok(commands[2].includes('start_v0.ps1')); assert.ok((await backup.textContent()).includes('Plan prepared, not executed.'));
  await backup.getByRole('button', { name: 'Copy Create archive command', exact: true }).click();
  await page.waitForFunction(() => document.body.textContent.includes('Create archive command copied. It has not been executed.') || document.body.textContent.includes('Clipboard unavailable. Select the command text and copy it manually.'));
  assert.ok(!existsSync(`D:/quant-hunter/.local/backups/product-${runTag}.qhbackup`));
  check('Backup plan rejects C path, prepares three existing offline CLI commands and reports copy outcome without executing backup'); await screen('settings-backup-desktop'); await mobile('settings-backup');

  await post('/logout', {}); await signIn(accounts.reader); await navigate('settings');
  assert.equal(await page.getByRole('button', { name: 'Apply role', exact: true }).count(), 0); assert.equal(await page.getByRole('button', { name: 'Prepare offline commands', exact: true }).count(), 0);
  assert.equal((await page.request.get(`${base}/api/administration/users`)).status(), 403);
  assert.equal((await page.request.get(`${base}/api/quality/inspections/${preview.inspection_id}`)).status(), 403);
  check('Reader Settings hides owner maintenance/backup preparation; real API denies foreign historical receipt and administration'); await screen('reader-settings');
  assert.deepEqual(proof.errors, []); assert.deepEqual(proof.external_requests, []); proof.finished_at = new Date().toISOString();
} catch (error) {
  proof.failure = safe(error.stack ?? error); try { await screen('failure'); } catch (captureError) { proof.capture_failure = safe(captureError); }
  process.exitCode = 1; console.error(proof.failure);
} finally {
  writeFileSync(path.join(output, 'product-proof.json'), JSON.stringify(proof, null, 2));
  await secondary?.close(); await browser.close();
}
