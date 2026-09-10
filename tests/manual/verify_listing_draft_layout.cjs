// Run against listing_draft_preview.py only. No production data or external URLs.
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const output = path.resolve('.tmp_stage4', 'screenshots');
  fs.mkdirSync(output, { recursive: true });
  const results = [];
  for (const [engine, driver] of [['chromium', chromium], ['webkit', webkit]]) {
    const systemChrome = engine === 'chromium' && fs.existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe');
    if (!systemChrome && !fs.existsSync(driver.executablePath())) {
      results.push({ engine, skipped: 'Browser binary is not installed' });
      continue;
    }
    const browser = await driver.launch({ headless: true, ...(systemChrome ? { channel: 'chrome' } : {}) });
    try {
      for (const [name, width, height] of [['desktop', 1440, 1000], ['iphone', 390, 844], ['android', 360, 800], ['tablet', 768, 1024]]) {
        for (const colorScheme of ['light', 'dark']) {
          const context = await browser.newContext({ viewport: { width, height }, colorScheme });
          const page = await context.newPage();
          const errors = [];
          page.on('pageerror', error => errors.push(error.message));
          await page.route('**/*', route => {
            const url = new URL(route.request().url());
            if (url.hostname === '127.0.0.1') route.continue();
            else route.abort();
          });
          await page.goto('http://127.0.0.1:8514');
          await page.getByRole('tab', { name: '商品マスター', exact: true }).click();
          await page.getByRole('button', { name: 'AI出品下書きを作成', exact: true }).click();
          await page.getByRole('tab', { name: 'AI出品', exact: true }).waitFor();
          await page.waitForFunction(() => document.querySelector('[role="tab"][aria-selected="true"]')?.textContent === 'AI出品');
          const workspace = page.locator('.st-key-ai_listing_workspace');
          await workspace.getByLabel('Title', { exact: true }).waitFor();
          const title = await workspace.getByLabel('Title', { exact: true }).inputValue();
          assert(title.includes('Camera'));
          await workspace.getByRole('heading', { name: 'AI出品', exact: true }).scrollIntoViewIfNeeded();
          await page.screenshot({ path: path.join(output, `${engine}-${name}-${colorScheme}-top.png`) });
          await workspace.getByLabel('Title', { exact: true }).scrollIntoViewIfNeeded();
          await page.screenshot({ path: path.join(output, `${engine}-${name}-${colorScheme}-editor.png`) });
          const measurements = await workspace.evaluate((root) => {
            const fields = [...root.querySelectorAll('input,textarea,button')].filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
            const overflow = fields.filter(el => { const r = el.getBoundingClientRect(); return r.left < -1 || r.right > innerWidth + 1; }).map(el => ({ tag: el.tagName, label: el.getAttribute('aria-label') || el.textContent, rect: el.getBoundingClientRect().toJSON() }));
            const approve = [...root.querySelectorAll('button')].find(el => el.textContent.trim() === '承認');
            return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, overflow,
              approvalHeight: approve.getBoundingClientRect().height,
              mobileCards: getComputedStyle(root.querySelector('.draft-mobile-list')).display,
              desktopTable: getComputedStyle(root.querySelector('.st-key-draft_desktop_list')).display };
          });
          console.log(JSON.stringify({ engine, name, colorScheme, ...measurements, pageErrors: errors }));
          assert.deepEqual(measurements.overflow, []);
          assert(measurements.documentWidth <= width + 1);
          if (width <= 768) {
            assert.equal(measurements.mobileCards, 'block');
            assert.equal(measurements.desktopTable, 'none');
            assert(measurements.approvalHeight >= 44);
          }
          assert.deepEqual(errors, []);
          results.push({ engine, name, colorScheme, ...measurements, pageErrors: errors });
          await context.close();
        }
      }
    } finally {
      await browser.close();
    }
  }
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
