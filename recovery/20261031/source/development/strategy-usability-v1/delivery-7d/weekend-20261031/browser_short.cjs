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
    await card.locator('summary').filter({hasText:/AI evidence review|AI证据复核/}).click();
    const aiText=await card.innerText();
    if (config.agent_v2) {
      await card.locator('[data-review-version="research_review_v2"]').waitFor({state:'visible'});
      if (!/synthetic model transport|合成模型传输/.test(aiText)) throw Error('SYNTHETIC_MODEL_LABEL_MISSING');
      if (!/Q1/.test(aiText) || !/Follow-up|跟踪项/.test(aiText)) throw Error('RESEARCH_V2_FIELDS_MISSING');
      if (!aiText.includes('RESEARCH_AGENT_V2_20261101') || !aiText.includes('ASOF_LOCAL_TOOLS_V2')) throw Error('RESEARCH_V2_IDENTITY_MISMATCH');
      report.synthetic_agent_v2_display=true;
      report.real_api_call=false;
    } else if (config.ai_replay) {
      if (!aiText.includes('gpt-6.1-sol') || !/saved real API result|已保存真实API结果/.test(aiText)) throw Error('REAL_API_REPLAY_PROVENANCE_MISSING');
      if (!/0.0088058/.test(aiText)) throw Error('REAL_API_COST_MISSING');
      const evidence=card.locator('summary').filter({hasText:/Closed-bar prices|闭合价格/});
      await evidence.click();
      if (!/open/.test(await card.innerText()) || !/close/.test(await card.innerText())) throw Error('EVIDENCE_METRICS_MISSING');
      report.saved_real_api_display=true;
      report.not_this_market_analysis=true;
    } else {
      if (!aiText.includes('TEST_ONLY_MODEL_UNAVAILABLE')) throw Error('AI_UNAVAILABLE_STATE_NOT_RENDERED');
      if (!/Not verified|尚未核验/.test(aiText)) throw Error('RETURNED_MODEL_NOT_EXPLICITLY_UNKNOWN');
      report.ai_unavailable_nonblocking=true;
    }
    if (!report.initial.includes(config.contract)) throw Error('SPECIFIC_REFERENCE_NOT_RENDERED');
    if (!report.initial.includes('S0:') || !report.initial.includes('S1:')) throw Error('COMPARISON_NOT_RENDERED');
    if (await page.locator('.ops-trend-signal').count()) throw Error('UNAUTHORIZED_QUALIFIED_CARD');
    await page.screenshot({path:path.join(config.out,'first-hour-reference.png'), fullPage:true});
    fs.writeFileSync(config.control, JSON.stringify({advance_seconds:4}));
    await page.clock.fastForward(4000);
    await page.waitForFunction(target=>/Historical reference quote|历史参考报价/.test(
      document.querySelector(`[aria-label="${target}"]`)?.textContent ?? ''),config.target,{timeout:5000});
    if (/Original deadline expired|原期限已过/.test(await card.innerText())) throw Error('BBO_AGE_CONFUSED_WITH_FORMATION_DEADLINE');
    if (await card.getByRole('button',{name:/Sol/}).isDisabled()) throw Error('TECHNICAL_REVIEW_BLOCKED_BY_OLD_BBO');
    report.bbo_age_separate_from_original_deadline=true;
    fs.writeFileSync(config.control, JSON.stringify({advance_seconds:301}));
    await page.clock.fastForward(297000);
    await page.reload({waitUntil:'domcontentloaded'});
    await card.waitFor({state:'visible',timeout:20000});
    await page.waitForFunction(target => /expired|过期|已失效|原期限已过/i.test(document.querySelector(`[aria-label="${target}"]`)?.textContent ?? ''), config.target, {timeout:20000});
    report.expired = await card.innerText();
    await page.screenshot({path:path.join(config.out,'first-hour-expired.png'), fullPage:true});
    if (await page.locator('.ops-trend-signal').count()) throw Error('EXPIRED_QUALIFIED_CARD');
    report.page_delivery = true;
    report.original_deadline_expiry = true;
    await card.locator('summary').filter({hasText:/AI evidence review|AI证据复核/}).click();
    if (!await card.getByRole('button',{name:/Sol/}).isDisabled()) throw Error('EXPIRED_REVIEW_ENABLED');
    report.layouts=[];
    for (const width of (config.agent_v2 ? [390,1440,2560] : [1440,2560])) for (const language of ['zh','en']) for (const theme of ['dark','light']) {
      await page.setViewportSize({width,height:1000});
      await page.evaluate(({language,theme})=>{
        localStorage.setItem('kquant-unified:language',language);
        localStorage.setItem('kquant-unified:theme',theme);
      },{language,theme});
      await page.reload({waitUntil:'domcontentloaded'});
      await card.waitFor({state:'visible',timeout:20000});
      await card.locator('summary').filter({hasText:/AI evidence review|AI证据复核/}).click();
      const text=await card.innerText();
      if (!text.includes(config.ai_replay || config.agent_v2 ? 'gpt-6.1-sol' : 'TEST_ONLY_MODEL_UNAVAILABLE') || !text.includes(config.contract)) throw Error('STATE_LOST_ON_LAYOUT');
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
      const boxes=await card.locator('th,td,p,small,strong').evaluateAll(nodes=>nodes.filter(n=>
        n.clientWidth>0 && n.scrollWidth>n.clientWidth+2).map(n=>({tag:n.tagName,text:n.textContent})));
      const clippedColumns=await card.locator('table th').evaluateAll(nodes=>nodes.filter(n=>{
        const r=n.getBoundingClientRect(), parent=n.closest('.ops-signal-why').getBoundingClientRect();
        return r.left<Math.max(0,parent.left)-1 || r.right>Math.min(innerWidth,parent.right)+1;
      }).map(n=>n.textContent));
      const screenshot=`weekend-${width}-${language}-${theme}.png`;
      await page.screenshot({path:path.join(config.out,screenshot),fullPage:true});
      report.layouts.push({width,language,theme,screenshot,overflow,text_overflow:boxes,clipped_columns:clippedColumns});
      if (overflow || boxes.length || clippedColumns.length) throw Error('LAYOUT_OVERFLOW');
    }
    await context.setOffline(true);
    await page.waitForFunction(target=>/Connection or snapshot unavailable|连接或快照不可用/.test(
      document.querySelector(`[aria-label="${target}"]`)?.textContent ?? ''),config.target,{timeout:20000});
    report.disconnect_visible=true;
    await context.setOffline(false);
    await page.reload({waitUntil:'domcontentloaded'});
    await card.waitFor({state:'visible',timeout:20000});
    if (!/expired|原期限已过/i.test(await card.innerText())) throw Error('RECONNECT_RENEWED_DEADLINE');
    report.reconnect_preserves_expiry=true;
    if (report.page_errors.length) throw Error('PAGE_ERRORS');
    await context.close();
  } catch (e) { report.errors.push(String(e.stack ?? e)); process.exitCode=1; }
  finally { await browser.close(); fs.writeFileSync(path.join(config.out,'browser-result.json'),JSON.stringify(report,null,2)); }
})();
