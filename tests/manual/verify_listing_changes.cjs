// Disposable approval_preview.py only. No Cloud, OAuth or external traffic.
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const url = process.env.STAGE7_PREVIEW_URL;
if (!url || new URL(url).hostname !== '127.0.0.1') throw new Error('Local preview URL required');
const output = path.resolve('.tmp_stage7', 'screenshots');
fs.mkdirSync(output, { recursive: true });

async function stable(page) {
  await page.waitForFunction(() => document.querySelector('.stApp')?.getAttribute('data-test-script-state') === 'notRunning' && !document.querySelector('[data-stale="true"]'));
  await page.evaluate(async () => { await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))); });
}

(async () => {
  const results = [];
  for (const [engine, driver] of [['chromium', chromium], ['webkit', webkit]]) {
    const browser = await driver.launch({headless:true, ...(engine==='chromium' ? {channel:'chrome'} : {})});
    try {
      for (const width of [1440, 390, 414, 360]) {
        const context = await browser.newContext({viewport:{width,height:1000}});
        const page = await context.newPage();
        page.setDefaultTimeout(60000);
        await page.route('**/*', r => new URL(r.request().url()).hostname === '127.0.0.1' ? r.continue() : r.abort());
        try {
          await page.goto(url);
          await stable(page);
          await page.getByRole('tab',{name:'承認・実行',exact:true}).click();
          const workspace = page.locator('.st-key-approval_workspace');
          await workspace.getByText(/現在のeBay実行モード: MOCK/).waitFor();
          await workspace.getByText('Mock出品の変更を提案',{exact:true}).click();
          await stable(page);
          await workspace.getByText('Stage6 Camera 1 / UPDATE_PRICE / PENDING',{exact:true}).click();
          await stable(page);
          await workspace.getByText('提案内容を編集',{exact:true}).click();
          await stable(page);
          const layout = await page.evaluate(() => {
            for (const el of document.querySelectorAll('*')) if (el.scrollTop) el.scrollTop = 0;
            const h1 = document.querySelector('h1');
            const range = document.createRange(); range.selectNodeContents(h1);
            const root = document.querySelector('.st-key-approval_workspace');
            const visible = el => !!el.getClientRects().length;
            const controls = [...root.querySelectorAll('input,textarea,button')].filter(visible);
            return {
              titleTop:range.getBoundingClientRect().top,
              headerBottom:document.querySelector('[data-testid="stHeader"]').getBoundingClientRect().bottom,
              width:innerWidth, documentWidth:document.documentElement.scrollWidth,
              overflow:controls.filter(el => { const b=el.getBoundingClientRect(); return b.left < -1 || b.right > innerWidth+1; }).map(el => el.getAttribute('aria-label') || el.textContent),
              heights:[...root.querySelectorAll('[data-testid="stButton"] button')].filter(visible).map(el => el.getBoundingClientRect().height),
              exceptions:document.querySelectorAll('[data-testid="stException"]').length,
              binding:root.textContent.includes('Marketplace:') && root.textContent.includes('実行状態:'),
            };
          });
          assert(layout.titleTop >= layout.headerBottom, JSON.stringify(layout));
          assert(layout.documentWidth <= width && !layout.exceptions && layout.binding, JSON.stringify(layout));
          assert.deepEqual(layout.overflow, []);
          if (width<768) assert(layout.heights.every(h=>h>=44), JSON.stringify(layout));
          await page.screenshot({path:path.join(output,`${engine}-${width}-top.png`)});
          await workspace.getByRole('button',{name:'提案を承認',exact:true}).scrollIntoViewIfNeeded();
          await page.screenshot({path:path.join(output,`${engine}-${width}-review.png`)});
          results.push({engine,...layout});
          fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(results,null,2));
          console.log(JSON.stringify(results.at(-1)));
        } catch (error) {
          await page.screenshot({path:path.join(output,`${engine}-${width}-failure.png`)});
          fs.writeFileSync(path.join(output,'failure.txt'), await page.locator('body').innerText());
          throw error;
        } finally { await context.close(); }
      }
    } finally { await browser.close(); }
  }
})().catch(e=>{console.error(e); process.exitCode=1;});
