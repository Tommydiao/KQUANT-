// TEST_ONLY actual compiled page; no network interception or card injection.
const fs = require('node:fs');
const path = require('node:path');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const { chromium } = require(config.playwright_module);
const report = { test_only: true, market_acceptance: false, errors: [], responses: [], page_errors: [], current_cards: [] };
const responseTasks = [];
const save = () => fs.writeFileSync(path.join(config.out, 'browser-result.json'), JSON.stringify(report, null, 2));
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: config.browser_executable });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    // A fixed calendar offset, not a frozen clock: timers and Date.now keep advancing.
    await context.addInitScript(({ offset }) => {
      const NativeDate = Date;
      class TestDate extends NativeDate {
        constructor(...args) { super(...(args.length ? args : [NativeDate.now() + offset])); }
        static now() { return NativeDate.now() + offset; }
      }
      window.Date = TestDate;
      if (!localStorage.getItem('kquant-unified:language')) localStorage.setItem('kquant-unified:language', 'en');
      if (!localStorage.getItem('kquant-unified:theme')) localStorage.setItem('kquant-unified:theme', 'dark');
    }, { offset: config.clock_offset_ms });
    const page = await context.newPage();
    const network = await context.newCDPSession(page);
    await network.send('Network.enable');
    report.snapshot_ready_events = [];
    network.on('Network.eventSourceMessageReceived', event => {
      try {
        const outer = JSON.parse(event.data);
        const payload = typeof outer.payload === 'string' ? JSON.parse(outer.payload) : (outer.payload ?? outer);
        if (payload.type === 'options_one_minute_snapshot_ready') {
          report.snapshot_ready_events.push({ wall_ms: Date.now(), event_name: event.eventName,
            research_strategy: payload.research_strategy });
        }
      } catch { /* Other SSE frames are not source-snapshot evidence. */ }
    });
    page.on('pageerror', error => report.page_errors.push(error.message));
    page.on('response', response => {
      const pathname = new URL(response.url()).pathname;
      if (pathname.startsWith('/api/')) report.responses.push({ path: pathname, status: response.status(), observed_ms: Date.now() });
      if (pathname === '/api/options/opening-trend/current' && response.status() === 200) {
        responseTasks.push(response.json().then(payload => {
          for (const row of payload.candidates || []) report.current_cards.push({
            evaluation_id: row.evaluation_id, contract_id: row.contract_id, deadline_at: row.deadline_at,
            valid_until: row.current_eligibility?.valid_until, observed_wall_ms: Date.now()
          });
        }).catch(error => report.errors.push(`CURRENT_BODY_UNAVAILABLE:${error.message}`)));
      }
    });
    await page.goto(`${config.url}/?workspace=options&view=signals`, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.locator('input[type=email]').fill('test-only@example.invalid');
    await page.locator('input[type=password]').fill('TEST_ONLY_not_a_user_password');
    const login = page.waitForResponse(r => r.url().endsWith('/api/auth/login'), { timeout: 10000 });
    await page.locator('form button[type=submit]').click();
    if ((await login).status() !== 200) throw new Error('ACTUAL_FORM_LOGIN_FAILED');
    await page.locator('input[type=password]').waitFor({ state: 'detached', timeout: 10000 });
    await page.waitForFunction(() => /Alerts online/.test(document.querySelector('.stream-indicator')?.textContent || ''),
      undefined, { timeout: 15000 });
    report.login_via_form = true;
    report.clock_offset_ms = config.clock_offset_ms;
    report.clock_advances = await page.evaluate(async () => {
      const start = Date.now(); await new Promise(resolve => setTimeout(resolve, 100)); return Date.now() - start >= 80;
    });
    if (!report.clock_advances) throw new Error('TEST_CLOCK_NOT_ADVANCING');
    const sourceDetails = page.locator('details').filter({ has: page.locator('summary', { hasText: 'Source refresh and request evidence' }) });
    await sourceDetails.locator('summary').click();
    await sourceDetails.getByText('TEST_ONLY_DATED_INTERFACE_UNAVAILABLE', { exact: false }).waitFor();
    report.source_initial_text = await sourceDetails.innerText();
    report.source_ready_wall_ms = Date.now();
    fs.writeFileSync(path.join(config.out, 'browser-source-ready.json'), JSON.stringify({ test_only: true, wall_ms: Date.now() }));
    await sourceDetails.getByText('TEST_ONLY_SOURCE_REVISION_SEEN', { exact: false }).waitFor({ timeout: 12000 });
    report.source_updated_text = await sourceDetails.innerText();
    report.source_revision_reached_page = true;
    report.source_updated_wall_ms = Date.now();
    if (!report.snapshot_ready_events.some(event => event.research_strategy === 'opening_momentum'
        && event.wall_ms >= report.source_ready_wall_ms && event.wall_ms <= report.source_updated_wall_ms)) {
      throw new Error('SOURCE_UPDATE_HAS_NO_OBSERVED_SSE_NOTIFICATION');
    }
    await page.screenshot({ path: path.join(config.out, 'TEST_ONLY-source-diagnostics.png'), fullPage: true });
    fs.writeFileSync(path.join(config.out, 'browser-ready.json'), JSON.stringify({ test_only: true, wall_ms: Date.now() }));
    const card = page.locator('.ops-trend-signal');
    await card.waitFor({ state: 'visible', timeout: 12000 });
    report.first_render_wall_ms = Date.now();
    report.card_text = await card.innerText();
    const expected = ['TEST261006C105000.US', 'Call', '2026-10-06', '105.00', 'Calendar DTE',
      'Quote multiplier', '100', 'Bid / ask', '1.00 / 1.01', '101.00', 'USD', 'Eligibility checked', 'Setup remaining'];
    report.missing_fields = expected.filter(value => !report.card_text.includes(value));
    if (report.missing_fields.length) throw new Error('CONTRACT_CARD_FIELDS_MISSING');
    const facts = await card.locator('.ops-contract-facts > div').evaluateAll(rows => Object.fromEntries(
      rows.map(row => [row.querySelector('dt').textContent, row.querySelector('dd').textContent])));
    if (facts['Calendar DTE'] !== '4' || facts['Quote multiplier'] !== '100' || facts['Strike price'] !== '105.00') {
      throw new Error('CONTRACT_FACT_VALUES_MISMATCH');
    }
    report.facts = facts;
    await page.screenshot({ path: path.join(config.out, 'TEST_ONLY-specific-contract.png'), fullPage: true });
    fs.writeFileSync(path.join(config.out, 'browser-rendered.json'), JSON.stringify({ test_only: true, wall_ms: Date.now() }));
    if (config.mode.startsWith('manual')) {
      await card.getByRole('button', { name: 'Report independent trade' }).click();
    }
    if (config.mode === 'disconnect') {
      report.disconnected_wall_ms = Date.now();
      await context.setOffline(true);
    }
    await card.waitFor({ state: 'detached', timeout: ['disconnect', 'structure'].includes(config.mode) ? 1500 : 6000 });
    report.removed_wall_ms = Date.now();
    const observations = page.locator('.ops-trend-observation');
    await observations.first().waitFor({ state: 'visible', timeout: 3000 });
    report.invalidated_observation_text = await observations.allInnerTexts();
    if (report.invalidated_observation_text.some(text => /Currently qualified/.test(text))) {
      throw new Error('INVALIDATED_OBSERVATION_STILL_CURRENTLY_QUALIFIED');
    }
    report.invalidated_observation_has_no_current_qualification = true;
    await page.screenshot({ path: path.join(config.out, 'TEST_ONLY-quote-expired.png'), fullPage: true });
    if (config.mode === 'disconnect') {
      report.offline_warning = await page.getByRole('alert').filter({ hasText: 'Live connection unavailable' }).isVisible();
      if (!report.offline_warning) throw new Error('NO_OFFLINE_WARNING');
      await page.waitForTimeout(3500);
      await context.setOffline(false);
    }
    if (config.mode === 'deadline') {
      const limit = Date.now() + 315000;
      report.deadline_observations = [];
      while (!fs.existsSync(path.join(config.out, 'deadline-processed.json')) && Date.now() < limit) {
        if (await card.count()) throw new Error('STALE_QUOTE_REAPPEARED_BEFORE_DEADLINE');
        report.deadline_observations.push({ wall_ms: Date.now(), card_count: 0 });
        await page.waitForTimeout(1000);
      }
      if (!fs.existsSync(path.join(config.out, 'deadline-processed.json'))) throw new Error('DEADLINE_PROCESSING_MISSING');
    }
    if (config.mode.startsWith('manual')) {
      // Self-report an independent trade after quote expiry; this does not renew signal eligibility.
      await page.getByLabel('Actual option contract', { exact: true }).fill('TEST261006C105000.US');
      await page.getByLabel('Contracts', { exact: true }).fill('2');
      await page.getByLabel('Actual multiplier', { exact: true }).fill('100');
      await page.getByLabel('Reported entry premium per share', { exact: true }).fill('1.01');
      await page.getByLabel('Underlying reference at entry (optional)', { exact: true }).fill('105');
      await page.getByLabel('Entry fees paid (optional)', { exact: true }).fill('1');
      const entryResponse = page.waitForResponse(r => r.url().endsWith('/api/options/one-minute/manual/entries'), { timeout: 8000 });
      await page.getByRole('button', { name: 'Record reported entry', exact: true }).click();
      const entry = await entryResponse;
      let position = await entry.json();
      const entryPayload = entry.request().postDataJSON();
      let retryReconciled = false;
      if (config.mode === 'manual-response-loss') {
        if (entry.status() !== 503) throw new Error('EXPECTED_AFTER_COMMIT_FAULT_MISSING');
        await page.getByRole('alert').filter({ hasText: 'The outcome is unknown' }).waitFor({ state: 'visible' });
        const writesBefore = report.responses.filter(r => r.path.endsWith('/manual/entries')).length;
        await page.getByRole('button', { name: 'Check existing records', exact: true }).click();
        await page.getByRole('region', { name: 'Existing report check' }).getByText('TEST261006C105000.US', { exact: true }).waitFor();
        const checkResponse = page.waitForResponse(r => r.url().includes('/manual?operation_key='), { timeout: 8000 });
        await page.getByRole('button', { name: 'Retry original report', exact: true }).click();
        const checked = await checkResponse;
        const checkedBody = await checked.json();
        if (checked.status() !== 200 || checkedBody.operation_status !== 'COMMITTED') throw new Error('RETRY_DID_NOT_RECONCILE');
        position = checkedBody.report;
        await page.getByLabel('Actual option contract', { exact: true }).waitFor({ state: 'detached' });
        if (report.responses.filter(r => r.path.endsWith('/manual/entries')).length !== writesBefore) {
          throw new Error('UI_RETRY_POSTED_AFTER_COMMITTED_CHECK');
        }
        retryReconciled = true;
      } else if (entry.status() !== 200) throw new Error(`MANUAL_ENTRY_FAILED:${JSON.stringify(position)}`);
      const duplicate = await page.request.post(entry.url(), { data: entryPayload });
      if (duplicate.status() !== 200 || (await duplicate.json()).position_id !== position.position_id) {
        throw new Error('MANUAL_ENTRY_IDEMPOTENCY_FAILED');
      }
      const conflict = await page.request.post(entry.url(), { data: { ...entryPayload, quantity: 3 } });
      if (conflict.status() !== 400 || (await conflict.json()).detail !== 'IDEMPOTENCY_KEY_CONFLICT') {
        throw new Error('MANUAL_ENTRY_CHANGED_REQUEST_NOT_REJECTED');
      }
      const reconciliation = await page.request.get(`${config.url}/api/options/one-minute/manual?operation_key=${entryPayload.operation_key}`);
      const reconciled = await reconciliation.json();
      if (reconciliation.status() !== 200 || reconciled.operation_status !== 'COMMITTED'
          || reconciled.report.position_id !== position.position_id) throw new Error('MANUAL_OPERATION_RECONCILIATION_FAILED');
      if (position.evaluation_id !== config.evaluation_id || position.contract_id !== 'TEST261006C105000.US'
          || position.strategy_id !== 'STRAT-OPENING-MOMENTUM-5M-V1' || position.right !== 'CALL'
          || position.quantity !== 2 || position.paper_fill !== false || position.real_order_created !== false
          || position.broker_verified !== false || position.exit_fee_estimate !== null) {
        throw new Error('MANUAL_IDENTITY_OR_POLICY_BINDING_FAILED');
      }
      await page.getByRole('tab', { name: 'Positions and exits', exact: true }).click();
      await page.getByRole('button', { name: 'Report partial/full exit', exact: true }).click();
      await page.getByLabel('Quantity exited', { exact: true }).fill('1');
      await page.getByLabel('Reported exit premium per share', { exact: true }).fill('1.1');
      const exitResponse = page.waitForResponse(r => r.url().endsWith('/api/options/one-minute/manual/exits'), { timeout: 8000 });
      await page.getByRole('button', { name: 'Record reported exit', exact: true }).click();
      const exited = await exitResponse;
      let exitReport = await exited.json();
      let exitRetryReconciled = false;
      if (config.mode === 'manual-response-loss') {
        if (exited.status() !== 503) throw new Error('EXPECTED_EXIT_AFTER_COMMIT_FAULT_MISSING');
        await page.getByRole('alert').filter({ hasText: 'The outcome is unknown' }).waitFor({ state: 'visible' });
        const writesBefore = report.responses.filter(r => r.path.endsWith('/manual/exits')).length;
        await page.getByRole('button', { name: 'Check existing records', exact: true }).click();
        const checkedRecords = page.getByRole('region', { name: 'Existing report check' });
        await checkedRecords.getByText('TEST261006C105000.US · Current open contracts: 1', { exact: true }).waitFor();
        await page.screenshot({ path: path.join(config.out, 'TEST_ONLY-exit-reconciliation.png'), fullPage: true });
        const checkResponse = page.waitForResponse(r => r.url().includes('/manual?operation_key='), { timeout: 8000 });
        await page.getByRole('button', { name: 'Retry original report', exact: true }).click();
        const checked = await checkResponse;
        const checkedBody = await checked.json();
        if (checked.status() !== 200 || checkedBody.operation_status !== 'COMMITTED'
            || checkedBody.current_position?.open_quantity !== 1) throw new Error('EXIT_RETRY_DID_NOT_RECONCILE');
        exitReport = checkedBody.report;
        await page.getByLabel('Quantity exited', { exact: true }).waitFor({ state: 'detached' });
        if (report.responses.filter(r => r.path.endsWith('/manual/exits')).length !== writesBefore) {
          throw new Error('EXIT_UI_RETRY_POSTED_AFTER_COMMITTED_CHECK');
        }
        exitRetryReconciled = true;
      } else if (exited.status() !== 200) throw new Error(`MANUAL_PARTIAL_EXIT_FAILED:${JSON.stringify(exitReport)}`);
      if (exitReport.remaining_quantity !== 1 || exitReport.exit_fees !== null) {
        throw new Error(`MANUAL_PARTIAL_EXIT_FAILED:${JSON.stringify(exitReport)}`);
      }
      const exitDuplicate = await page.request.post(exited.url(), { data: exited.request().postDataJSON() });
      if (exitDuplicate.status() !== 200 || (await exitDuplicate.json()).remaining_quantity !== 1) {
        throw new Error('MANUAL_EXIT_IDEMPOTENCY_FAILED');
      }
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByRole('tab', { name: 'Positions and exits', exact: true }).click();
      await page.getByRole('button', { name: 'Report partial/full exit', exact: true }).waitFor({ state: 'visible' });
      const saved = await page.request.get(`${config.url}/api/options/one-minute/manual`);
      const status = await saved.json();
      if (saved.status() !== 200 || status.positions.length !== 1 || status.positions[0].open_quantity !== 1
          || status.positions[0].state !== 'OPEN_REPORTED') throw new Error('MANUAL_RELOAD_QUANTITY_FAILED');
      report.manual = { entry: position, exit: exitReport, persisted: status.positions[0],
        actual_forms: true, duplicate_checks_via_authenticated_http: true, operation_reconciled: true,
        ui_retry_reconciled_without_post: retryReconciled, exit_retry_reconciled_without_post: exitRetryReconciled };
      await page.screenshot({ path: path.join(config.out, 'TEST_ONLY-manual-partial-exit.png'), fullPage: true });
      report.manual.desktop_checks = [];
      for (const language of ['zh', 'en']) for (const theme of ['light', 'dark']) for (const width of [1440, 2560]) {
        await page.setViewportSize({ width, height: 900 });
        await page.evaluate(({ language, theme }) => {
          localStorage.setItem('kquant-unified:language', language);
          localStorage.setItem('kquant-unified:theme', theme);
        }, { language, theme });
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByRole('tab', { name: language === 'en' ? 'Positions and exits' : '持仓与退出', exact: true }).click();
        await page.getByRole('button', { name: language === 'en' ? 'Report partial/full exit' : '登记部分/全部退出', exact: true }).click();
        const input = page.getByLabel(language === 'en' ? 'Quantity exited' : '本次退出张数', { exact: true });
        if (await input.getAttribute('max') !== '1') throw new Error('DESKTOP_CURRENT_REMAINING_MISMATCH');
        await page.getByText(language === 'en' ? 'TEST261006C105000.US · Open when form opened: 1'
          : 'TEST261006C105000.US · 打开表单时剩余: 1', { exact: true }).waitFor();
        const overflow = await page.evaluate(() => ({ page: document.documentElement.scrollWidth > innerWidth,
          drawer: [...document.querySelectorAll('dialog[open]')].some(e => e.scrollWidth > e.clientWidth + 1) }));
        if (overflow.page || overflow.drawer) throw new Error('MANUAL_DESKTOP_HORIZONTAL_OVERFLOW');
        const screenshot = `TEST_ONLY-manual-${language}-${theme}-${width}.png`;
        await page.screenshot({ path: path.join(config.out, screenshot), fullPage: true });
        report.manual.desktop_checks.push({ language, theme, width, remaining: 1, overflow, screenshot });
        await page.getByRole('button', { name: language === 'en' ? 'Close' : '关闭', exact: true }).click();
      }
      await page.getByRole('button', { name: 'Sign out', exact: true }).click();
      await page.locator('input[type=password]').waitFor({ state: 'visible' });
      const denied = await page.request.get(`${config.url}/api/options/one-minute/manual`);
      if (denied.status() !== 401) throw new Error('LOGOUT_DID_NOT_REVOKE_MANUAL_ACCESS');
      await page.locator('input[type=email]').fill('test-only@example.invalid');
      await page.locator('input[type=password]').fill('TEST_ONLY_not_a_user_password');
      await page.locator('form button[type=submit]').click();
      await page.locator('input[type=password]').waitFor({ state: 'detached' });
      const recovered = await page.request.get(`${config.url}/api/options/one-minute/manual`);
      const recoveredBody = await recovered.json();
      if (recovered.status() !== 200 || recoveredBody.positions.length !== 1
          || recoveredBody.positions[0].position_id !== position.position_id
          || recoveredBody.positions[0].open_quantity !== 1) throw new Error('SESSION_RESTORE_LOST_POSITION');
      report.manual.session_revoked_and_restored = true;
    }
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1500);
    if (await card.count()) throw new Error('EXPIRED_CONTRACT_REAPPEARED');
    report.expired_not_replayed = true;
    if (['structure', 'deadline'].includes(config.mode)) {
      const response = await page.request.get(`${config.url}/api/options/one-minute/evaluations/${config.evaluation_id}`);
      if (response.status() !== 200) throw new Error('LIFECYCLE_DETAIL_UNAVAILABLE');
      const detail = await response.json();
      const expectedState = config.mode === 'structure' ? 'WITHDRAWN' : 'EXPIRED';
      if (detail.current_eligibility?.state !== expectedState || detail.deadline_at !== config.original_deadline) {
        throw new Error('LIFECYCLE_ORIGINAL_DEADLINE_MISMATCH');
      }
      report.lifecycle = { state: detail.current_eligibility.state, reasons: detail.current_eligibility.reasons,
        deadline_at: detail.deadline_at, evaluation_id: detail.evaluation_id, observed_wall_ms: Date.now() };
    }
    report.browser_positive_bridge = true;
    if (report.page_errors.length) throw new Error('PAGE_SCRIPT_ERROR');
  } catch (error) {
    report.errors.push(error.message);
    for (const context of browser.contexts()) for (const page of context.pages()) {
      report.failure_text = await page.locator('body').innerText().catch(() => 'UNAVAILABLE');
      await page.screenshot({ path: path.join(config.out, 'TEST_ONLY-failure.png'), fullPage: true }).catch(() => {});
    }
    process.exitCode = 1;
  } finally { await Promise.all(responseTasks); save(); await browser.close(); }
})().catch(error => { report.errors.push(error.message); save(); process.exitCode = 1; });
