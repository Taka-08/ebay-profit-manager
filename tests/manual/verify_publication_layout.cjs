// Local fixture only. External HTTP is blocked; no production records are used.
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const output = path.resolve('.tmp_stage5/screenshots');
fs.mkdirSync(output, { recursive: true });

async function stable(page) {
  await page.waitForFunction(() => document.querySelector('.stApp')?.getAttribute('data-test-script-state') === 'notRunning' && !document.querySelector('[data-stale="true"]'));
  await page.evaluate(async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); });
}
async function header(page) {
  await stable(page);
  return page.evaluate(() => {
    for (const element of document.querySelectorAll('*')) if (element.scrollTop) element.scrollTop = 0;
    const h1 = document.querySelector('h1');
    const range = document.createRange(); range.selectNodeContents(h1);
    return { top: range.getBoundingClientRect().top,
      headerBottom: document.querySelector('[data-testid="stHeader"]').getBoundingClientRect().bottom,
      width: innerWidth, documentWidth: document.documentElement.scrollWidth,
      exceptions: document.querySelectorAll('[data-testid="stException"]').length };
  });
}
(async () => {
  const results = [];
  for (const [engine, driver] of [['chromium', chromium], ['webkit', webkit]]) {
    const browser = await driver.launch({ headless: true, ...(engine === 'chromium' ? {channel:'chrome'} : {}) });
    try {
      for (const width of [1440, 390, 414, 360]) {
        const context = await browser.newContext({viewport:{width,height:900}});
        const page = await context.newPage();
        try {
        page.setDefaultTimeout(60000);
        const errors = [];
        page.on('pageerror', e => errors.push(e.message));
        await page.route('**/*', route => new URL(route.request().url()).hostname === '127.0.0.1' ? route.continue() : route.abort());
        await page.goto('http://127.0.0.1:8515');
        await stable(page);
        await page.getByRole('tab', {name:'AI出品',exact:true}).click();
        const workspace = page.locator('.st-key-ai_listing_workspace');
        const name = `E2E-${engine}-${width}`;
        await workspace.getByRole('combobox', {name:'下書きの商品',exact:true}).click();
        await page.getByRole('option', {name:`${name} / ${name}`,exact:true}).click();
        await stable(page);
        await workspace.getByLabel('操作者名（監査記録用・ログイン認証ではありません）').fill('Browser reviewer');
        await workspace.getByText('公開前の商品・配送・費用確認',{exact:true}).click();
        await stable(page);
        const overflowingInputs = await workspace.locator('input:visible, textarea:visible').evaluateAll(elements =>
          elements.filter(element => {
            const box = element.getBoundingClientRect();
            return box.left < -1 || box.right > innerWidth + 1;
          }).map(element => element.getAttribute('aria-label') || element.name));
        assert.deepEqual(overflowingInputs, []);
        await workspace.getByLabel('SKU',{exact:true}).scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(output,`${engine}-${width}-editor.png`)});
        await workspace.getByLabel('Title',{exact:true}).fill(`Reviewed ${name}`);
        await workspace.getByRole('button',{name:'下書きを保存',exact:true}).click();
        await workspace.getByText('保存しました。編集後は承認が解除され、DRAFTに戻ります。',{exact:true}).waitFor();
        await stable(page);
        await workspace.getByRole('button',{name:'レビュー待ちにする',exact:true}).click();
        await workspace.getByText('READY_FOR_REVIEWに変更しました。外部サービスへの送信はありません。',{exact:true}).waitFor();
        await stable(page);
        await workspace.getByText('保存済みの本文・状態・価格・数量・未確認事項を人間が確認しました',{exact:true}).click();
        await stable(page);
        await workspace.getByRole('button',{name:'承認',exact:true}).click();
        await workspace.getByRole('heading',{name:'公開処理（Mock検証）',exact:true}).waitFor();
        await stable(page);
        const approval = await header(page);
        assert(approval.top >= approval.headerBottom && approval.documentWidth <= width && !approval.exceptions);
        await page.screenshot({path:path.join(output,`${engine}-${width}-approved.png`)});
        await workspace.getByText('ローカル検証DBへのMock登録を確認して実行する',{exact:true}).click();
        await stable(page);
        const publish = workspace.getByRole('button',{name:'Mockで公開',exact:true});
        await publish.scrollIntoViewIfNeeded();
        const box = await publish.boundingBox();
        if (width <= 768) assert(box.height >= 44 && box.x >= 0 && box.x + box.width <= width);
        await page.screenshot({path:path.join(output,`${engine}-${width}-publish.png`)});
        await publish.click();
        await workspace.getByText(/Mock Item ID: MOCK-/).waitFor();
        await stable(page);
        assert(await workspace.getByRole('button',{name:'下書きを保存',exact:true}).isDisabled());
        const published = await header(page);
        assert(published.top >= published.headerBottom && published.documentWidth <= width && !published.exceptions);
        assert.deepEqual(errors, []);
        results.push({engine,width,approval,published,buttonHeight:box.height,overflowingInputs,errors});
        fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
        console.log(JSON.stringify(results.at(-1)));
        } catch (error) {
          await page.screenshot({path:path.join(output,`${engine}-${width}-failure.png`)});
          fs.writeFileSync(path.join(output,'failure.txt'),await page.locator('body').innerText());
          throw error;
        }
        await context.close();
      }
    } finally { await browser.close(); }
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
