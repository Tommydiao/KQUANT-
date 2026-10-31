const fs = require('node:fs');
const path = require('node:path');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const { chromium } = require(config.playwright_module);
const report = { test_only: true, market_acceptance: false, cases: [], errors: [], api: [], page_errors: [] };
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: config.browser_executable });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.on('pageerror', e => report.page_errors.push(e.message));
    page.on('response', r => {
      if (r.url().includes('/api/')) report.api.push({ url: r.url(), status: r.status(),
        isolation: r.headers()['x-kquant-test-isolation'] ?? null });
    });
    await page.goto(`${config.url}/?workspace=options&view=signals`);
    await page.locator('input[type=email]').fill('test-only@example.invalid');
    await page.locator('input[type=password]').fill('TEST_ONLY_not_a_user_password');
    const login = page.waitForResponse(r => r.url().endsWith('/api/auth/login'));
    await page.locator('form button[type=submit]').click();
    if ((await login).status() !== 200) throw Error('LOGIN_FAILED');
    report.real_form_login = true;
    for (const width of [1440, 2560]) for (const language of ['zh', 'en']) for (const theme of ['dark', 'light']) {
      await page.setViewportSize({ width, height: 1000 });
      await page.evaluate(({language, theme}) => {
        localStorage.setItem('kquant-unified:language', language);
        localStorage.setItem('kquant-unified:theme', theme);
      }, {language, theme});
      await page.reload({ waitUntil: 'domcontentloaded' });
      const card = page.getByRole('article', {name: config.target, exact: true});
      await card.waitFor({ state: 'visible', timeout: 20000 });
      await card.scrollIntoViewIfNeeded();
      await card.locator('summary').filter({hasText:/AI证据复核|AI evidence review/}).click();
      const text = await card.innerText();
      if (!text.includes('S0:') || !text.includes('S1:')) throw Error('COMPARISON_MISSING');
      if (config.synthetic_reference && !text.includes('TEST261006C105000.US')) throw Error('REFERENCE_CONTRACT_MISSING');
      if (!text.includes('gpt-6.1-sol') || !text.includes('TEST_ONLY_HISTORICAL_REVIEW')) throw Error('AI_SECTION_MISSING');
      const astra=card.getByRole('button',{name:/Astra复核|Astra review/});
      if (!(await astra.isDisabled())) throw Error('EXPIRED_ASTRA_BUTTON_ENABLED');
      if (await page.locator('.ops-trend-signal').count()) throw Error('REPLAY_APPEARED_QUALIFIED');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      const boxes = await card.locator('th,td,strong,small,p').evaluateAll(nodes => nodes.map(n => {
        const r = n.getBoundingClientRect();
        return { tag: n.tagName, width: r.width, scrollWidth: n.scrollWidth, clientWidth: n.clientWidth };
      }).filter(r => r.clientWidth > 0 && r.scrollWidth > r.clientWidth + 2));
      const name = `replay-${width}-${language}-${theme}.png`;
      await page.screenshot({ path: path.join(config.out, name), fullPage: true });
      report.cases.push({ width, language, theme, text, overflow, text_overflow: boxes, screenshot: name });
      if (overflow || boxes.length) throw Error('LAYOUT_OVERFLOW');
    }
    await context.setOffline(true);
    await page.waitForFunction(target => /Connection or snapshot unavailable|连接或快照不可用/.test(document.querySelector(`[aria-label="${target}"]`)?.textContent ?? ''), config.target, {timeout: 20000});
    report.disconnect_visible = true;
    await page.screenshot({path: path.join(config.out, 'replay-disconnected.png'), fullPage: true});
    await context.setOffline(false);
    await page.reload();
    await page.getByRole('article', {name: config.target, exact: true}).waitFor();
    report.reconnect_preserves_expired = await page.getByRole('article', {name: config.target, exact: true}).innerText();
    if (!report.reconnect_preserves_expired.includes('expired')) throw Error('ORIGINAL_DEADLINE_LOST');
    if (report.page_errors.length) throw Error('PAGE_ERROR');
    const forbiddenRole=await page.request.post(config.url+'/api/options/opening-trend/ai-review',{data:{role:'OTHER',evaluation_id:'TEST_ONLY'}});
    report.invalid_role_status=forbiddenRole.status();
    if (forbiddenRole.status()!==422) throw Error('ASTRA_ROLE_GATE_MISSING');
    const anonymous=await browser.newContext();
    const unauth=await anonymous.request.post(config.url+'/api/options/opening-trend/ai-review',{data:{role:'ASTRA',evaluation_id:'TEST_ONLY'}});
    report.anonymous_review_status=unauth.status();
    await anonymous.close();
    if (unauth.status()!==401) throw Error('AI_REVIEW_AUTH_MISSING');
    await context.close();
  } catch (e) { report.errors.push(e.stack ?? String(e)); process.exitCode = 1; }
  finally {
    await browser.close();
    fs.writeFileSync(path.join(config.out, 'browser-result.json'), JSON.stringify(report, null, 2));
  }
})();
