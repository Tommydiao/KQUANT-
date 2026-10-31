const fs = require('fs');
const path = require('path');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const { chromium } = require(config.playwright_module);
const report = { test_only: true, natural_signal: false, errors: [], api_failures: [], page_errors: [] };
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:config.browser_executable});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const page = await context.newPage();
    await page.clock.install({time:new Date(config.test_clock)});
    page.on('pageerror', e => report.page_errors.push(e.message));
    page.on('response', async r => { if (r.url().includes('/api/') && r.status() >= 400) { const item={url:r.url(),status:r.status()}; report.api_failures.push(item); try {item.body=(await r.text()).slice(0,6000);} catch {} } });
    await page.goto(`${config.url}/?workspace=options&view=signals`);
    await page.locator('input[type=email]').fill('test-only@example.invalid');
    await page.locator('input[type=password]').fill('TEST_ONLY_not_a_user_password');
    const login = page.waitForResponse(r => r.url().endsWith('/api/auth/login'));
    await page.locator('form button[type=submit]').click();
    if ((await login).status() !== 200) throw Error('TEST_ONLY_LOGIN_FAILED');
    const card = page.getByRole('article', {name:config.target, exact:true});
    await card.waitFor({state:'visible', timeout:20000});
    report.initial = await card.innerText();
    await page.getByText('09:35–10:25 ET · 11 checkpoints · 10:30 cutoff', {exact:false}).waitFor({state:'visible'});
    if (await page.getByText('09:35–10:00 ET', {exact:false}).count()) throw Error('OLD_WINDOW_HEADING');
    report.window_heading_verified = true;
    if (!report.initial.includes(config.contract)) throw Error('SPECIFIC_REFERENCE_NOT_RENDERED');
    if (!report.initial.includes('S0:') || !report.initial.includes('S1:')) throw Error('COMPARISON_NOT_RENDERED');
    if (await page.locator('.ops-trend-signal').count()) throw Error('UNAUTHORIZED_QUALIFIED_CARD');
    await page.screenshot({path:path.join(config.out,'first-hour-reference.png'), fullPage:true});
    fs.writeFileSync(config.control, JSON.stringify({advance_seconds:301}));
    await page.clock.fastForward(301000);
    await page.reload({waitUntil:'domcontentloaded'});
    await card.waitFor({state:'visible',timeout:20000});
    await page.waitForFunction(target => /expired|过期|已失效|原期限已过/i.test(document.querySelector(`[aria-label="${target}"]`)?.textContent ?? ''), config.target, {timeout:20000});
    report.expired = await card.innerText();
    await page.screenshot({path:path.join(config.out,'first-hour-expired.png'), fullPage:true});
    if (await page.locator('.ops-trend-signal').count()) throw Error('EXPIRED_QUALIFIED_CARD');
    report.page_delivery = true;
    report.original_deadline_expiry = true;
    if (report.page_errors.length) throw Error('PAGE_ERRORS');
    await context.close();
  } catch (e) { report.errors.push(String(e.stack ?? e)); process.exitCode=1; }
  finally { await browser.close(); fs.writeFileSync(path.join(config.out,'browser-result.json'),JSON.stringify(report,null,2)); }
})();
