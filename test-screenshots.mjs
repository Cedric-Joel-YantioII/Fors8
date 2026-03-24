import puppeteer from 'puppeteer';
import { mkdirSync } from 'fs';

const SCREENSHOTS_DIR = './screenshots';
mkdirSync(SCREENSHOTS_DIR, { recursive: true });

const pages = [
  { name: '01-home-hero', url: 'http://localhost:3000/', wait: 3000 },
  { name: '02-home-scrolled', url: 'http://localhost:3000/', wait: 2000, scroll: true },
  { name: '03-settings', url: 'http://localhost:3000/settings', wait: 1500 },
];

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--window-size=1440,900'],
    defaultViewport: { width: 1440, height: 900 },
  });

  for (const page of pages) {
    console.log(`Capturing: ${page.name} → ${page.url}`);
    const tab = await browser.newPage();
    await tab.goto(page.url, { waitUntil: 'networkidle2', timeout: 15000 });
    await new Promise(r => setTimeout(r, page.wait));

    if (page.scroll) {
      await tab.evaluate(() => window.scrollTo(0, 600));
      await new Promise(r => setTimeout(r, 1000));
    }

    await tab.screenshot({
      path: `${SCREENSHOTS_DIR}/${page.name}.png`,
      fullPage: false,
    });
    console.log(`  Saved: ${SCREENSHOTS_DIR}/${page.name}.png`);
    await tab.close();
  }

  // Full page screenshot of home
  const fullTab = await browser.newPage();
  await fullTab.goto('http://localhost:3000/', { waitUntil: 'networkidle2', timeout: 15000 });
  await new Promise(r => setTimeout(r, 3000));
  await fullTab.screenshot({
    path: `${SCREENSHOTS_DIR}/04-home-full.png`,
    fullPage: true,
  });
  console.log(`  Saved: ${SCREENSHOTS_DIR}/04-home-full.png`);

  await browser.close();
  console.log('\nDone! Screenshots in ./screenshots/');
})();
