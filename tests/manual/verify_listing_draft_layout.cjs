// Run against listing_draft_preview.py only. No production data or external URLs.
const { chromium, webkit } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

async function waitForRender(page) {
  await page.waitForFunction(() => document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state') === 'notRunning' && !document.querySelector('[data-stale="true"]'));
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

async function verifyPageHeader(page, width) {
  await waitForRender(page);
  const header = await page.evaluate(() => {
    for (const element of document.querySelectorAll('*')) {
      if (element.scrollTop) element.scrollTop = 0;
    }
    const title = document.querySelector('h1');
    const walker = document.createTreeWalker(title, NodeFilter.SHOW_TEXT);
    const rects = [];
    while (walker.nextNode()) {
      if (!walker.currentNode.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(walker.currentNode);
      rects.push(range.getBoundingClientRect());
    }
    return {
      title: title.textContent,
      titleTextTop: Math.min(...rects.map(rect => rect.top)),
      titleTextRight: Math.max(...rects.map(rect => rect.right)),
      headerBottom: document.querySelector('[data-testid="stHeader"]').getBoundingClientRect().bottom,
      contentPaddingTop: parseFloat(getComputedStyle(document.querySelector('.block-container')).paddingTop),
      rootFontSize: parseFloat(getComputedStyle(document.documentElement).fontSize),
      documentWidth: document.documentElement.scrollWidth,
    };
  });
  assert(header.title.includes('出品管理ツール'));
  if (width <= 768) {
    assert(header.titleTextTop >= header.headerBottom, `App title overlaps the fixed header: ${JSON.stringify(header)}`);
  }
  assert(header.titleTextRight <= width + 1);
  assert(header.documentWidth <= width + 1);
  // Keep the desktop spacing unchanged while reserving the header on mobile.
  assert(Math.abs(header.contentPaddingTop - header.rootFontSize * (width <= 768 ? 4.3 : 0.75)) < 1);
  return header;
}

(async () => {
  const output = path.resolve('.tmp_stage4', 'header-fix-screenshots');
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
      for (const [name, width, height] of [['desktop', 1440, 1000], ['iphone', 390, 844], ['iphone-plus', 414, 896], ['android', 360, 800], ['tablet', 768, 1024]]) {
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
          const initialHeader = await verifyPageHeader(page, width);
          await page.getByRole('tab', { name: '商品マスター', exact: true }).click();
          await page.getByRole('button', { name: 'AI出品下書きを作成', exact: true }).click();
          await page.getByRole('tab', { name: 'AI出品', exact: true }).waitFor();
          await page.waitForFunction(() => document.querySelector('[role="tab"][aria-selected="true"]')?.textContent === 'AI出品');
          const workspace = page.locator('.st-key-ai_listing_workspace');
          await workspace.getByLabel('Title', { exact: true }).waitFor();
          const title = await workspace.getByLabel('Title', { exact: true }).inputValue();
          assert(title.includes('Camera'));
          const draftHeader = await verifyPageHeader(page, width);
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
          await page.reload();
          const reloadedHeader = await verifyPageHeader(page, width);
          results.push({ engine, name, colorScheme, initialHeader, draftHeader, reloadedHeader, ...measurements, pageErrors: errors });
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
