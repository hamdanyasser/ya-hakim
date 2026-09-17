const puppeteer = require('puppeteer');
(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader',
           '--enable-webgl', '--ignore-gpu-blocklist', '--no-sandbox']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 900, deviceScaleFactor: 1 });

  const errors = [];
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });

  const url = process.argv[2] || 'http://127.0.0.1:8777/screen';
  await page.goto(url, { waitUntil: 'networkidle2', timeout: 45000 });

  // get past the title card and the level card
  await new Promise(r => setTimeout(r, 1200));
  await page.evaluate(() => { const b = document.getElementById('begin'); if (b) b.click(); });
  await new Promise(r => setTimeout(r, 1500));
  await page.evaluate(() => { const g = document.getElementById('cardGo'); if (g) g.click(); });
  await new Promise(r => setTimeout(r, 4000));   // let the scene render + drift

  await page.screenshot({ path: process.argv[3] || 'screen.png' });

  const info = await page.evaluate(() => {
    const c = document.getElementById('room3d');
    const r = c ? c.getBoundingClientRect() : null;
    return {
      canvas: r ? Math.round(r.width) + 'x' + Math.round(r.height) : 'none',
      fps: (document.getElementById('fps') || {}).textContent,
      patient: (document.getElementById('patient') || {}).textContent,
      hr: (document.getElementById('vHr') || {}).textContent,
      flat: document.body.classList.contains('flat')
    };
  });
  console.log(JSON.stringify(info));
  errors.slice(0, 8).forEach(e => console.log(e));
  await browser.close();
})();
