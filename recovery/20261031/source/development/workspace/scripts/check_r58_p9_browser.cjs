// TEST_ONLY: shipped frontend, real network and login, no route interception.
const fs = require('node:fs');
const path = require('node:path');
const { responseEvidence, isolationCode } = require('./browser_response_evidence.cjs');
const cliValue = flag => {
  const index = process.argv.indexOf(flag);
  return index >= 0 ? process.argv[index + 1] : undefined;
};
const playwrightModule = cliValue('--playwright-module') || 'playwright';
const { chromium } = require(playwrightModule);
const browserExecutable = cliValue('--browser-executable');
if (browserExecutable && !fs.existsSync(browserExecutable)) throw new Error('BROWSER_EXECUTABLE_MISSING');
const launchOptions = { headless: true, ...(browserExecutable ? { executablePath: browserExecutable } : {}) };
if (process.argv.includes('--preflight-only')) {
  (async () => {
    const browser = await chromium.launch(launchOptions);
    const version = browser.version();
    await browser.close();
    console.log(JSON.stringify({ test_only: true, browser_launch_verified: true, browser_version: version,
      playwright_module: require.resolve(playwrightModule),
      playwright_version: require(path.join(path.dirname(require.resolve(playwrightModule)), 'package.json')).version,
      browser_executable: browserExecutable || chromium.executablePath(), sdk_connections: 0, production_writes: 0 }));
  })().catch(error => { console.error(error.message); process.exitCode = 1; });
} else {
const out = process.argv[2];
const url = process.argv[3] || 'http://127.0.0.1:8132';
const checkEpochBoundary = process.argv.includes('--test-only-epoch-boundary');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  const start = Date.now(), log = fs.createWriteStream(path.join(out, 'browser-events.jsonl'));
  const emit = item => log.write(JSON.stringify({ observed_at: new Date().toISOString(), test_only: true, ...item }) + '\n');
  const browser = await chromium.launch(launchOptions);
  const pages = [], problems = [], apiFailures = [], renderedIssues = [], connectionStates = [], continuityStates = [], refreshes = [0, 0, 0];
  const requests = new WeakMap();
  const responseTasks = new Set();
  let requestSequence = 0;
  const observeRequests = (page, scope) => {
    page.on('request', request => {
      requests.set(request, { id: `TEST_ONLY-browser-${++requestSequence}`, started: Date.now() });
    });
    page.on('requestfinished', request => {
      const record = requests.get(request);
      if (new URL(request.url()).pathname.startsWith('/api/')) {
        emit({ type: 'request-finished', ...scope, request_id: record?.id ?? null,
          path: new URL(request.url()).pathname, finished_at: new Date().toISOString(),
          elapsed_ms: record ? Date.now() - record.started : null });
      }
    });
  };
  const observeEpochBoundary = async (page, scope) => {
    if (!checkEpochBoundary) return;
    let response, data;
    for (let attempt = 0; attempt < 3; attempt++) {
      response = await page.request.get(`${url}/api/options/one-minute/manual`, { timeout: 3000 });
      data = await response.json();
      emit({ type: 'manual-api-boundary-observed', ...scope, attempt, status: response.status(),
        data_status: data.status, old_position_continuity: data.old_position_continuity,
        position_records_complete: data.position_records_complete, detail: data.detail });
      if (response.status() !== 503) break;
      await sleep(500);
    }
    if (response.status() !== 200 || data.old_position_continuity !== 'UNKNOWN' || data.position_records_complete !== false) {
      throw new Error('ACTUAL_MANUAL_API_EPOCH_BOUNDARY_MISSING');
    }
    const zh = scope.language !== 'en';
    await page.getByRole('tab', { name: zh ? '持仓与退出' : 'Positions and exits', exact: true }).click();
    const alert = page.getByRole('alert').filter({ hasText: zh ? '旧持仓状态未确认' : 'Prior positions are unconfirmed' });
    await alert.waitFor({ state: 'visible', timeout: 10000 });
    const notice = await alert.innerText();
    if (!(zh ? /空列表不代表没有持仓或已经平仓/ : /An empty list does not establish no positions or confirmed exits/).test(notice)) {
      throw new Error('EMPTY_EPOCH_MISREPRESENTED_AS_NO_POSITIONS');
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    const state = { ...scope, actual_api_status: response.status(), old_position_continuity: data.old_position_continuity,
      position_records_complete: data.position_records_complete, warning_visible: true, overflow, production_data: false };
    continuityStates.push(state);
    emit({ type: 'manual-epoch-boundary', ...state });
    await page.screenshot({ path: path.join(out, `TEST_ONLY-epoch-${scope.width}-${scope.language}-${scope.theme}.png`), fullPage: true });
    await page.getByRole('tab', { name: zh ? '机会与资格' : 'Opportunities and eligibility', exact: true }).click();
  };
  const observeResponse = (response, scope) => {
    const address = new URL(response.url());
    if (!address.pathname.startsWith('/api/')) return;
    const observation = responseEvidence(response, scope, requests.get(response.request()));
    const task = (async () => {
      const length = Number(response.headers()['content-length']);
      if (response.status() === 503 && Number.isFinite(length) && length > 0 && length <= 4096) {
        try {
          const code = await isolationCode(response);
          if (code === 'TEST_ONLY_LEGACY_NOT_MOUNTED') {
            observation.classification = 'TEST_ONLY_UNMOUNTED';
            observation.error_code = 'TEST_ONLY_LEGACY_NOT_MOUNTED';
          }
        } catch { observation.error_code = 'ERROR_BODY_UNAVAILABLE'; }
      }
      emit({ type: 'response', ...observation });
      if (response.status() >= 400) apiFailures.push(observation);
    })();
    responseTasks.add(task);
    task.finally(() => responseTasks.delete(task));
  };
  const observeRenderedState = async (page, scope) => {
    const body = await page.locator('body').innerText();
    const errors = [...new Set(body.match(/HTTP_\d{3}/g) ?? [])];
    const observation = { ...scope, visible_http_errors: errors };
    emit({ type: 'rendered-state', ...observation });
    if (errors.length) renderedIssues.push(observation);
    const service = await page.locator('.topbar-actions .status-chip').first().innerText().catch(() => 'MISSING');
    const stream = await page.locator('.stream-indicator').innerText().catch(() => 'MISSING');
    const state = { ...scope, gateway_service_label: service, stream_label: stream,
      web_service_scope_explicit: /Web service|Checking web service|网页服务/.test(service),
      does_not_prove_market_or_signal_readiness: true };
    connectionStates.push(state);
    emit({ type: 'connection-scope', ...state });
  };
  try {
    for (const [index, view] of ['signals', 'today', 'settings'].entries()) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      await context.addInitScript(() => { localStorage.setItem('kquant-unified:language', 'zh'); localStorage.setItem('kquant-unified:theme', 'dark'); });
      const page = await context.newPage();
      observeRequests(page, { index });
      page.on('pageerror', error => { problems.push({ index, message: error.message }); emit({ type: 'pageerror', index, message: error.message }); });
      page.on('requestfailed', request => emit({ type: 'requestfailed', index, path: new URL(request.url()).pathname, failure: request.failure()?.errorText }));
      page.on('response', response => observeResponse(response, { index }));
      await page.goto(`${url}/?workspace=options&view=${view}`, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.locator('input[type=email]').fill('test-only@example.invalid');
      await page.locator('input[type=password]').fill('TEST_ONLY_not_a_user_password');
      const response = page.waitForResponse(r => r.url().endsWith('/api/auth/login'), { timeout: 15000 });
      await page.locator('form button[type=submit]').click();
      if ((await response).status() !== 200) throw new Error('ISOLATED_LOGIN_FAILED');
      await page.locator('input[type=password]').waitFor({ state: 'detached', timeout: 15000 });
      await page.screenshot({ path: path.join(out, `TEST_ONLY-initial-${view}.png`), fullPage: true });
      emit({ type: 'login', index, through_real_form: true, production_login_verified: false });
      pages.push(page);
    }
    await observeEpochBoundary(pages[0], { width: 1440, language: 'zh', theme: 'dark', initial: true });
    // Establish the healthy baseline before the controller injects its backend crash.
    fs.writeFileSync(path.join(out, 'browser-ready.json'), JSON.stringify({ test_only: true, three_real_pages: true,
      initial_epoch_boundary_checked: checkEpochBoundary, started_at: new Date().toISOString() }));
    let lastRefresh = Date.now(), lastShot = Date.now();
    while (!fs.existsSync(path.join(out, 'browser-stop.json'))) {
      if (Date.now() - start > 3900000) throw new Error('BROWSER_TEST_STOP_NOT_RECEIVED');
      if (Date.now() - lastRefresh >= 30000) {
        for (const [index, page] of pages.entries()) {
          const before = Date.now();
          await page.reload({ waitUntil: 'domcontentloaded', timeout: 15000 });
          refreshes[index]++;
          const initialCharacters = (await page.locator('body').innerText()).length;
          const renderStarted = Date.now();
          try {
            await page.waitForFunction(() => document.body.innerText.trim().length >= 50, { timeout: 5000 });
          } catch {
            problems.push({ index, code: 'BLANK_PAGE_AFTER_RENDER_DEADLINE' });
            await page.screenshot({ path: path.join(out, `TEST_ONLY-blank-${index}-${Date.now()}.png`) });
          }
          const bytes = (await page.locator('body').innerText()).length;
          emit({ type: 'refresh', index, milliseconds: Date.now() - before, body_characters: bytes,
            initial_body_characters: initialCharacters, render_wait_ms: Date.now() - renderStarted });
        }
        lastRefresh = Date.now();
      }
      if (Date.now() - lastShot > 300000) {
        await pages[0].screenshot({ path: path.join(out, `TEST_ONLY-signal-${Math.floor((Date.now() - start) / 1000)}s.png`) });
        lastShot = Date.now();
      }
      await sleep(250);
    }
    for (const width of [1440, 2560]) for (const language of ['zh', 'en']) for (const theme of ['dark', 'light']) {
      const page = pages[0];
      await page.setViewportSize({ width, height: 1000 });
      // Disable the initial preset before changing preferences on the live page.
      await page.context().clearCookies();
      await page.context().close();
      const context = await browser.newContext({ viewport: { width, height: 1000 } });
      await context.addInitScript(({ language, theme }) => { localStorage.setItem('kquant-unified:language', language); localStorage.setItem('kquant-unified:theme', theme); }, { language, theme });
      const current = await context.newPage();
      observeRequests(current, { width, language, theme });
      current.on('pageerror', error => {
        const issue = { width, language, theme, message: error.message };
        problems.push(issue); emit({ type: 'variant-pageerror', ...issue });
      });
      current.on('response', async response => {
        observeResponse(response, { width, language, theme });
        const endpoint = new URL(response.url()).pathname;
        if (!endpoint.startsWith('/api/auth/')) return;
        emit({ type: 'variant-auth', width, language, theme, path: endpoint, status: response.status() });
        if (endpoint === '/api/auth/session') {
          try {
            const body = await response.json();
            emit({ type: 'variant-session-state', width, language, theme,
              authenticated: body.authenticated, configured: body.configured,
              restart_required: body.restart_required,
              configuration_check_unavailable: body.configuration_check_unavailable,
              mode: body.mode, configuration_check: body.configuration_check });
          } catch { emit({ type: 'variant-session-state-unavailable', width, language, theme }); }
        }
      });
      await current.goto(`${url}/?workspace=options&view=signals`, { waitUntil: 'domcontentloaded' });
      await current.locator('input[type=email]').fill('test-only@example.invalid');
      await current.locator('input[type=password]').fill('TEST_ONLY_not_a_user_password');
      const loginResponse = current.waitForResponse(r => r.url().endsWith('/api/auth/login'), { timeout: 15000 });
      await current.locator('form button[type=submit]').click();
      const logged = await loginResponse;
      if (logged.status() !== 200) {
        emit({ type: 'variant-login-failed', width, language, theme, status: logged.status(), response: await logged.text() });
        await current.screenshot({ path: path.join(out, `TEST_ONLY-login-failed-${width}-${language}-${theme}.png`) });
        throw new Error(`VARIANT_LOGIN_${logged.status()}`);
      }
      try {
        await current.locator('input[type=password]').waitFor({ state: 'detached', timeout: 15000 });
      } catch (error) {
        emit({ type: 'variant-login-view-failed', width, language, theme, body: await current.locator('body').innerText() });
        await current.screenshot({ path: path.join(out, `TEST_ONLY-login-view-failed-${width}-${language}-${theme}.png`) });
        throw error;
      }
      await sleep(500);
      await observeRenderedState(current, { width, language, theme });
      await current.screenshot({ path: path.join(out, `TEST_ONLY-${width}-${language}-${theme}.png`), fullPage: true });
      await current.screenshot({ path: path.join(out, `TEST_ONLY-viewport-${width}-${language}-${theme}.png`) });
      await observeEpochBoundary(current, { width, language, theme });
      const overflow = await current.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      emit({ type: 'viewport', width, language, theme, overflow });
      pages[0] = current;
    }
  } catch (error) {
    problems.push({ code: 'BROWSER_EXCEPTION', error_type: error.name || 'Error',
      timed_out: /Timeout|timed out/i.test(String(error.message)),
      detail: 'Raw Playwright call logs omitted because they may contain session cookies.' });
    emit({ type: 'exception', error_type: error.name || 'Error',
      timed_out: /Timeout|timed out/i.test(String(error.message)) });
    fs.writeFileSync(path.join(out, 'browser-failed.json'), JSON.stringify(problems));
  } finally {
    await Promise.allSettled([...responseTasks]);
    const report = { test_only: true, duration_seconds: (Date.now() - start) / 1000, three_real_pages: pages.length === 3,
      refreshes, problems, api_failure_observations: apiFailures, rendered_http_issues: renderedIssues,
      api_failure_classification: apiFailures.reduce((counts, row) => {
        counts[row.classification] = (counts[row.classification] || 0) + 1;
        return counts;
      }, {}),
      connection_scope_observations: connectionStates,
      manual_epoch_continuity_observations: continuityStates,
      signal_delivery_accepted: false, production_data: false, intercepted_routes: 0,
      browser_executable: browserExecutable || chromium.executablePath(),
      browser_version: browser.version(), playwright_module: require.resolve(playwrightModule) };
    fs.writeFileSync(path.join(out, 'browser-report.json'), JSON.stringify(report, null, 2));
    await browser.close();
    log.end();
  }
})();
}
