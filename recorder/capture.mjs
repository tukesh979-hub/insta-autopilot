// Records a scrolling screen capture of a web page with Playwright, then converts
// it to a 30 fps H.264 MP4 with ffmpeg.
//
// usage: node recorder/capture.mjs <url> <out.mp4> [seconds=8]
//
// Setup (once):  cd recorder && npm install && npx playwright install chromium

import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const [, , url, out, secsArg = '8'] = process.argv;
if (!url || !out) {
  console.error('usage: node recorder/capture.mjs <url> <out.mp4> [seconds=8]');
  process.exit(2);
}
const seconds = Number(secsArg);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'capture-'));

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1080 },
  recordVideo: { dir: tmp, size: { width: 1440, height: 1080 } },
});
const page = await context.newPage();

try {
  await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
} catch (err) {
  console.error(`page load warning: ${err.message}`);
}

// Let animations and WebGL start, then scroll smoothly so the clip shows content.
await page.waitForTimeout(1500);
const steps = 40;
const stepMs = Math.max(20, ((seconds * 1000) - 3000) / steps);
const maxScroll = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
const perStep = Math.max(0, Math.floor(maxScroll / steps));
for (let i = 0; i < steps; i++) {
  await page.evaluate((y) => window.scrollBy(0, y), perStep);
  await page.waitForTimeout(stepMs);
}

const videoPath = await page.video().path();
await context.close();
await browser.close();

const tmpMp4 = path.join(tmp, 'raw.mp4');
execFileSync('ffmpeg', [
  '-y', '-loglevel', 'error', '-i', videoPath,
  '-t', String(seconds), '-vf', 'fps=30,format=yuv420p',
  '-c:v', 'libx264', '-preset', 'veryfast', '-an', tmpMp4,
], { stdio: 'inherit' });

fs.mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
fs.copyFileSync(tmpMp4, out);
console.log(`saved ${out}`);
