// 모션그래픽/제목 렌더러: jobs.json 을 읽어 장면마다 PNG 프레임을 찍는다.
// 사용: node render_scenes.js jobs.json
// job = {kind:"scene", data, duration, fps, out_dir, width, height, content_h, colors}
//     | {kind:"title", data, out_png, width, height}
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

async function renderJob(browser, job, workDir) {
  const page = await browser.newPage({ viewport: { width: job.width || 1080, height: job.height || 1140 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'scenes', 'scene.html'));
  // 사진 경로는 작업 폴더 기준
  const data = JSON.parse(JSON.stringify(job.data));
  if (Array.isArray(data.images)) data.images = data.images.map((p) => (/^(https?:|file:)/.test(p) ? p : 'file://' + path.resolve(workDir, p)));
  const known = await page.evaluate(([d, dur, o]) => window.__build(d, dur, o), [data, job.duration || 1, { content_h: job.content_h, colors: job.colors, stage_h: job.height }]);
  await page.evaluate(() => window.__ready());
  if (!known) console.error(`  (알 수 없는 템플릿 "${data.template}" → statement 로 대체)`);
  if (job.kind === 'title') {
    await page.screenshot({ path: job.out_png, omitBackground: true, clip: { x: 0, y: 0, width: job.width || 1080, height: job.height || 560 } });
  } else {
    fs.mkdirSync(job.out_dir, { recursive: true });
    const fps = job.fps || 30;
    const n = Math.max(1, Math.round(job.duration * fps));
    for (let f = 0; f < n; f++) {
      await page.evaluate((t) => window.__seek(t), f / fps);
      await page.screenshot({ path: path.join(job.out_dir, String(f).padStart(5, '0') + '.png'), clip: { x: 0, y: 0, width: job.width || 1080, height: job.height || 1140 } });
    }
  }
  await page.close();
}

(async () => {
  const jobsPath = process.argv[2];
  const jobs = JSON.parse(fs.readFileSync(jobsPath, 'utf8'));
  const workDir = process.argv[3] || process.cwd();
  const browser = await chromium.launch();
  const workers = Math.max(1, Math.min(3, jobs.length));
  let next = 0;
  await Promise.all(Array.from({ length: workers }, async () => {
    while (next < jobs.length) {
      const job = jobs[next++];
      await renderJob(browser, job, workDir);
      console.error(`  그래픽 완료: ${job.out_dir || job.out_png}`);
    }
  }));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
