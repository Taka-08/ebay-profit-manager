// Local fake HTTP preview only; never visits eBay or Cloud.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const url = process.env.STAGE7_SANDBOX_PREVIEW_URL;
if (!url || new URL(url).hostname !== '127.0.0.1') throw new Error('Local preview required');
const output = '.tmp_stage7/sandbox_layout';
fs.mkdirSync(output, {recursive:true});
async function stable(page) {
  await page.waitForFunction(() => document.querySelector('.stApp')?.getAttribute('data-test-script-state') === 'notRunning' && !document.querySelector('[data-stale="true"]'));
  await page.evaluate(async () => {await document.fonts.ready; await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));});
}
(async () => {
  const results=[];
  for (const [engine, driver] of [['chromium',chromium],['webkit',webkit]]) {
    const browser=await driver.launch({headless:true,...(engine==='chromium'?{channel:'chrome'}:{})});
    try {
      for (const width of [1440,390,414,360]) {
        const page=await browser.newPage({viewport:{width,height:1000}});
        page.setDefaultTimeout(60000);
        await page.route('**/*',r=>new URL(r.request().url()).hostname==='127.0.0.1'?r.continue():r.abort());
        await page.goto(url); await stable(page);
        await page.getByRole('tab',{name:'承認・実行',exact:true}).click();
        const workspace=page.locator('.st-key-approval_workspace');
        await workspace.getByText(/現在のeBay実行モード: SANDBOX/).waitFor();
        await workspace.getByText('Sandbox出品の変更を提案',{exact:true}).click();
        await workspace.getByText('提案内容を編集',{exact:true}).click();
        await stable(page);
        const result=await page.evaluate(()=>{
          for(const el of document.querySelectorAll('*')) if(el.scrollTop) el.scrollTop=0;
          const root=document.querySelector('.st-key-approval_workspace');
          const r=document.createRange(); r.selectNodeContents(document.querySelector('h1'));
          const controls=[...root.querySelectorAll('input,textarea,button')].filter(e=>e.getClientRects().length);
          return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,
            titleTop:r.getBoundingClientRect().top,headerBottom:document.querySelector('[data-testid="stHeader"]').getBoundingClientRect().bottom,
            overflow:controls.filter(e=>{const b=e.getBoundingClientRect();return b.left<0||b.right>innerWidth+1;}).map(e=>e.outerHTML.slice(0,80)),
            buttonHeights:[...root.querySelectorAll('[data-testid="stButton"] button')].map(e=>e.getBoundingClientRect().height),
            exceptions:document.querySelectorAll('[data-testid="stException"]').length,
            binding:root.textContent.includes('Sandbox Offer ID: 1001')&&root.textContent.includes('Seller照合ID:')&&root.textContent.includes('Production書き込み無効')};
        });
        assert(result.titleTop>=result.headerBottom,JSON.stringify(result));
        assert(result.documentWidth<=width&&!result.exceptions&&result.binding,JSON.stringify(result));
        assert.equal(result.overflow.length,0,JSON.stringify(result));
        assert(result.buttonHeights.filter(h=>h>0).every(h=>h>=46),JSON.stringify(result));
        await page.screenshot({path:`${output}/${engine}-${width}.png`});
        results.push({engine,...result}); console.log(JSON.stringify(results.at(-1)));
        fs.writeFileSync(`${output}/results.json`,JSON.stringify(results,null,2));
        await page.close();
      }
    } finally {await browser.close();}
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
