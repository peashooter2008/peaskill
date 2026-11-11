import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const fixture = fileURLToPath(new URL('../skills/offline-course-delivery/examples/mini-course/', import.meta.url));
let server, browser, base;
before(async () => {
  await readFile(path.join(fixture, 'index.html'));
  server = http.createServer(async (req, res) => {
    try {
      const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
      const target = path.resolve(fixture, '.' + (pathname === '/' ? '/index.html' : pathname));
      if (!target.startsWith(fixture)) { res.writeHead(403).end(); return; }
      const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
      res.setHeader('Content-Type', `${mime[path.extname(target)] || 'text/plain'}; charset=utf-8`);
      res.end(await readFile(target));
    } catch { res.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
});
after(async () => {
  await browser?.close();
  if (server) await new Promise(resolve => server.close(resolve));
});

async function withPage(fn) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  const external = [], errors = [];
  await context.route('**/*', route => {
    const origin = new URL(route.request().url()).origin;
    if (origin !== base) { external.push(route.request().url()); return route.abort('internetdisconnected'); }
    return route.continue();
  });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(base);
    await fn(page, external);
    assert.deepEqual(errors, [], '课程不应有未处理的浏览器错误');
  } finally { await context.close(); }
}

test('外网全部拦截时，本地课程、附件和公式演示仍可用', async () => {
  await withPage(async (page, external) => {
    await page.waitForFunction(() => document.querySelector('#code')?.textContent.includes('print'));
    const source = await (await page.request.get(`${base}/numbers.py`)).text();
    assert.equal((await page.locator('#code').textContent()).trim(), source.trim());
    const href = await page.locator('#download-source').getAttribute('href');
    assert.equal(new URL(href, base).pathname, '/numbers.py');
    await page.locator('#run-example').click();
    assert.match(await page.locator('#result').textContent(), /平均数：4/);
    assert.deepEqual(external, [], '正常课程应无外部资源请求');
    await page.screenshot({ path: 'qa/offline-course.png', fullPage: true });
  });
});

test('离线课程笔记刷新后保留', async () => {
  await withPage(async page => {
    await page.locator('#notes').fill('离线笔记：比较均值与极端值。');
    await page.reload();
    assert.equal(await page.locator('#notes').inputValue(), '离线笔记：比较均值与极端值。');
  });
});

test('导出的备份可恢复，错误类型和错误课程备份不覆盖原笔记', async () => {
  await withPage(async page => {
    await page.locator('#notes').fill('保留的合成笔记');
    const downloadEvent = page.waitForEvent('download');
    await page.locator('#export-backup').click();
    const download = await downloadEvent;
    const chunks = [];
    for await (const chunk of await download.createReadStream()) chunks.push(chunk);
    const backup = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    assert.deepEqual(backup, { schemaVersion: 1, courseId: 'mean-demo', notes: '保留的合成笔记' });
    const load = async value => page.locator('#import-backup').setInputFiles({ name: 'notes.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) });
    await load({ ...backup, notes: '从合法备份恢复' });
    await page.waitForFunction(() => document.querySelector('#notes').value === '从合法备份恢复');
    for (const invalid of [{ ...backup, notes: 123 }, { ...backup, courseId: 'another-course' }]) {
      await load(invalid);
      await page.waitForFunction(() => /失败|无效|拒绝|不支持|错误/.test(document.querySelector('#import-status').textContent));
      assert.equal(await page.locator('#notes').inputValue(), '从合法备份恢复');
      await page.reload();
      assert.equal(await page.locator('#notes').inputValue(), '从合法备份恢复');
    }
  });
});

test('外网拦截器能够拒绝新增远程依赖（负面对照）', async () => {
  await withPage(async (page, external) => {
    const failed = await page.evaluate(async () => {
      try { await fetch('https://example.invalid/blocked-dependency.js'); return false; }
      catch { return true; }
    });
    assert.equal(failed, true);
    assert.equal(external.length, 1);
  });
});

test('长中文和最大长度转义字符笔记能导出再恢复', async () => {
  await withPage(async page => {
    for (const notes of ['课'.repeat(40000), '\u0001'.repeat(50000)]) {
      await page.locator('#notes').fill(notes);
      const event = page.waitForEvent('download');
      await page.locator('#export-backup').click();
      const download = await event;
      const chunks = [];
      for await (const chunk of await download.createReadStream()) chunks.push(chunk);
      const buffer = Buffer.concat(chunks);
      assert.equal(JSON.parse(buffer.toString('utf8')).notes, notes);
      await page.locator('#notes').fill('准备恢复长笔记');
      await page.locator('#import-backup').setInputFiles({ name: 'long-notes.json', mimeType: 'application/json', buffer });
      await page.waitForFunction(expected => document.querySelector('#notes').value === expected, notes);
      await page.reload();
      assert.equal(await page.locator('#notes').inputValue(), notes);
    }
  });
});

test('损坏JSON、错误版本、超长及过大备份不覆盖当前笔记', async () => {
  await withPage(async page => {
    await page.locator('#notes').fill('保护这份笔记');
    const valid = { schemaVersion: 1, courseId: 'mean-demo', notes: '恢复目标' };
    const invalidBuffers = [
      Buffer.from('{broken'),
      Buffer.from(JSON.stringify({ ...valid, schemaVersion: 2 })),
      Buffer.from(JSON.stringify({ ...valid, notes: 'a'.repeat(50001) })),
      Buffer.from(' '.repeat(301025)),
    ];
    for (const buffer of invalidBuffers) {
      await page.locator('#import-backup').setInputFiles({ name: 'invalid-notes.json', mimeType: 'application/json', buffer });
      await page.waitForFunction(() => /失败|无效|拒绝|不支持|错误/.test(document.querySelector('#import-status').textContent));
      assert.equal(await page.locator('#notes').inputValue(), '保护这份笔记');
      await page.reload();
      assert.equal(await page.locator('#notes').inputValue(), '保护这份笔记');
    }
  });
});
