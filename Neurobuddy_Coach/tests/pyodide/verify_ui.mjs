import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, 'ui-verify');
await mkdir(out, { recursive: true });

const puppeteer = await import('puppeteer-core');
const browser = await puppeteer.default.launch({
  executablePath: '/usr/bin/google-chrome-stable',
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage']
});
const page = await browser.newPage();
page.setDefaultTimeout(20000);
const consoleLines = [];
page.on('console', (msg) => consoleLines.push(msg.type() + ': ' + msg.text()));
page.on('pageerror', (err) => consoleLines.push('pageerror: ' + err.message));
await page.goto('http://127.0.0.1:8766/Index.html', { waitUntil: 'networkidle0' });
await page.waitForSelector('#library-tree');
await page.waitForFunction(() => document.getElementById('server-status')?.textContent !== 'Checking server', { timeout: 15000 }).catch(() => {});
const shot1 = join(out, 'library.png');
await page.screenshot({ path: shot1, fullPage: true });
const info = await page.evaluate(() => {
  const tabs = [...document.querySelectorAll('[data-tab]')].map((el) => el.dataset.tab);
  return {
    title: document.title,
    tabs,
    status: document.getElementById('server-status')?.textContent,
    kind: document.getElementById('workspace-kind')?.textContent,
    tree: document.getElementById('library-tree')?.innerText?.slice(0, 800),
    backup: Boolean(document.getElementById('backup-workspace')),
    restore: Boolean(document.getElementById('restore-workspace')),
    share: Boolean(document.getElementById('copy-share-link')),
    hasDemo: /Demo Track Club|Alex Rivera/.test(document.body.innerText)
  };
});
await page.click('#add-team');
await page.waitForSelector('#name-dialog[open], dialog#name-dialog');
await page.type('#name-value', 'Pyodide Track');
await page.click('#name-form button[type="submit"]');
await page.waitForFunction(() => document.body.innerText.includes('Pyodide Track'), { timeout: 10000 });
const shot2 = join(out, 'team.png');
await page.screenshot({ path: shot2, fullPage: true });
await page.click('[data-tab="analysis"]');
await page.waitForSelector('#view-analysis:not([hidden])');
const analysisEmpty = await page.evaluate(() => document.getElementById('job-list')?.innerText?.slice(0, 400));
await page.click('[data-tab="advanced"]');
await page.waitForSelector('#view-advanced:not([hidden])');
const shot3 = join(out, 'advanced.png');
await page.screenshot({ path: shot3, fullPage: true });
await writeFile(join(out, 'result.json'), JSON.stringify({ info, analysisEmpty, consoleLines: consoleLines.slice(0, 50) }, null, 2));
console.log(JSON.stringify({ info, analysisEmpty, consoleLines: consoleLines.slice(0, 30) }, null, 2));
await browser.close();
