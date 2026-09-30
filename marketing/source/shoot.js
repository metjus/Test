// Screenshot every generated page to ../out/<name>.png
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const pages = JSON.parse(fs.readFileSync(path.join(__dirname, 'pages', 'pages.json')));
  const only = process.argv.slice(2);
  const outDir = path.join(__dirname, 'out');
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  for (const p of pages) {
    if (only.length && !only.includes(p.name)) continue;
    const page = await browser.newPage({ viewport: { width: p.width, height: p.height }, deviceScaleFactor: 1 });
    await page.goto('file://' + path.join(__dirname, 'pages', p.name + '.html'), { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    const inter = await page.evaluate(() => document.fonts.check('600 20px Inter'));
    await page.screenshot({ path: path.join(outDir, p.name + '.png'), omitBackground: p.name === 'icon' });
    console.log(p.name, inter ? 'Inter loaded' : 'FALLBACK FONT');
    await page.close();
  }
  await browser.close();
})();
