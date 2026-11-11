#!/usr/bin/env node
// Original peaskill test utility. Operates in a new, isolated browser context.
import { readFile, mkdir, writeFile, realpath } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const viewports = [
  { width: 390, height: 844 }, { width: 320, height: 568 },
  { width: 390, height: 440 }, { width: 1366, height: 900 },
];

function parseArgs(argv) {
  const values = new Set(['--url', '--config', '--report', '--browser-path', '--channel']);
  const switches = new Set(['--allow-remote', '--allow-test-actions']);
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (!values.has(key) && !switches.has(key)) throw new Error(`未知参数：${key}`);
    if (key in args) throw new Error(`重复参数：${key}`);
    if (switches.has(key)) args[key] = true;
    else {
      const value = argv[++i];
      if (!value || value.startsWith('--')) throw new Error(`参数缺少值：${key}`);
      args[key] = value;
    }
  }
  for (const key of ['--url', '--config', '--report']) if (!args[key]) throw new Error(`缺少 ${key}`);
  const url = new URL(args['--url']);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('URL 必须是无内嵌凭证的 HTTP(S) 地址');
  if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) && !args['--allow-remote']) throw new Error('远程测试目标需要显式 --allow-remote；请仅使用已授权的测试站点');
  if (args['--browser-path'] && args['--channel']) throw new Error('--browser-path 与 --channel 只能选择一个');
  return { args, url };
}

async function configFrom(args) {
  const input = await realpath(path.resolve(args['--config']));
  const output = path.resolve(args['--report']);
  const existingOutput = await realpath(output).catch(() => output);
  if (existingOutput.toLowerCase() === input.toLowerCase()) throw new Error('报告路径不能覆盖选择器配置');
  const config = JSON.parse(await readFile(input, 'utf8'));
  if (!config || Array.isArray(config) || typeof config !== 'object') throw new Error('配置必须是 JSON 对象');
  const required = args['--allow-test-actions'] ? ['input', 'send', 'history', 'leave', 'back'] : ['input', 'send'];
  for (const key of required) if (typeof config[key] !== 'string' || !config[key].trim()) throw new Error(`配置缺少有效选择器：${key}`);
  return config;
}

async function visibleWithin(page, selector) {
  const element = page.locator(selector);
  if (await element.count() !== 1) throw new Error(`选择器需要唯一匹配：${selector}`);
  if (!await element.isVisible()) throw new Error(`元素不可见：${selector}`);
  const box = await element.boundingBox();
  const viewport = page.viewportSize();
  if (!box || box.width <= 0 || box.height <= 0 || box.x < -1 || box.y < -1 || box.x + box.width > viewport.width + 1 || box.y + box.height > viewport.height + 1) throw new Error(`元素超出可视区域：${selector}`);
  const usable = await element.evaluate(node => {
    const box = node.getBoundingClientRect();
    const top = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
    return top === node || node.contains(top);
  });
  if (!usable) throw new Error(`元素被其他内容遮挡：${selector}`);
}

async function runViewport(browser, url, config, viewport, actions, blockedOrigins) {
  const context = await browser.newContext({ viewport, isMobile: viewport.width <= 600, hasTouch: viewport.width <= 600, serviceWorkers: 'block' });
  const page = await context.newPage();
  page.setDefaultTimeout(5000);
  const checks = [];
  let pageErrors = 0;
  page.on('pageerror', () => { pageErrors++; });
  await context.route('**/*', route => {
    const request = new URL(route.request().url());
    if (request.origin === url.origin) return route.continue();
    blockedOrigins.add(request.origin);
    return route.abort();
  });
  const check = async (id, fn) => {
    try { await fn(); checks.push({ id, status: 'passed' }); return true; }
    catch (error) { checks.push({ id, status: 'failed', reason: String(error.message).split('\n')[0] }); return false; }
  };
  const layout = async prefix => {
    await check(`${prefix}horizontal-overflow`, async () => {
      const overflow = await page.evaluate(width => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - width, page.viewportSize().width);
      if (overflow > 1) throw new Error(`页面横向溢出 ${overflow}px`);
    });
    await check(`${prefix}input-visible`, () => visibleWithin(page, config.input));
    await check(`${prefix}send-visible`, () => visibleWithin(page, config.send));
  };
  try {
    const navigated = await check('navigation', async () => {
      await page.goto(url.href, { waitUntil: 'load', timeout: 10000 });
      if (new URL(page.url()).origin !== url.origin) throw new Error('导航离开已授权的同源测试站点');
      await page.locator(config.input).waitFor({ state: 'visible' });
    });
    if (!navigated) return { viewport, checks };
    await layout('');
    if (actions) {
      const draft = `peaskill synthetic draft ${viewport.width}`;
      if (viewport.width <= 600) {
        await check('mobile-enter-newline', async () => {
          await page.locator(config.input).fill(draft);
          await page.locator(config.input).press('End');
          await page.locator(config.input).press('Enter');
          if (await page.locator(config.input).inputValue() !== `${draft}\n`) throw new Error('Enter 没有保留换行，或触发了发送');
        });
      } else {
        checks.push({ id: 'mobile-enter-newline', status: 'skipped', reason: '桌面 Enter 行为由应用约定，本项仅检查手机宽度' });
      }
      await check('draft-navigation-retention', async () => {
        const expected = 'peaskill synthetic draft\n保留这一行';
        await page.locator(config.input).fill(expected);
        await page.locator(config.leave).click();
        await page.locator(config.back).waitFor({ state: 'visible' });
        await page.locator(config.back).click();
        await page.locator(config.input).waitFor({ state: 'visible' });
        if (await page.locator(config.input).inputValue() !== expected) throw new Error('离开并返回聊天后草稿变化');
      });
      let previousScroll;
      const canScroll = await check('history-read-position', async () => {
        previousScroll = await page.locator(config.history).evaluate(node => {
          if (node.scrollHeight - node.clientHeight < 100) throw new Error('历史记录不足以测试滚动，请准备足够的虚构消息');
          node.scrollTop = 50;
          return node.scrollTop;
        });
        await page.waitForTimeout(150);
        const actual = await page.locator(config.history).evaluate(node => node.scrollTop);
        if (Math.abs(actual - previousScroll) > 2) throw new Error('阅读历史时滚动位置被抢占');
      });
      await page.setViewportSize({ width: viewport.width, height: Math.max(260, Math.min(440, viewport.height - 220)) });
      await page.waitForTimeout(150);
      await layout('reduced-viewport-');
      await check('history-retained-after-resize', async () => {
        if (!canScroll) throw new Error('历史滚动前置检查失败');
        const actual = await page.locator(config.history).evaluate(node => node.scrollTop);
        if (Math.abs(actual - previousScroll) > 2) throw new Error('可视区域缩小时历史阅读位置跳动');
      });
      await check('send-scroll-bottom', async () => {
        const message = `peaskill synthetic send ${randomUUID()}`;
        await page.locator(config.input).fill(message);
        await page.locator(config.send).click();
        await page.waitForFunction(({ input, history, message }) => {
          const field = document.querySelector(input), log = document.querySelector(history);
          return field && log && field.value === '' && log.innerText.includes(message) && log.scrollHeight - log.clientHeight - log.scrollTop <= 4;
        }, { input: config.input, history: config.history, message });
      });
    }
    await check('no-page-errors', async () => { if (pageErrors) throw new Error(`页面脚本错误 ${pageErrors} 个`); });
    return { viewport, checks };
  } finally { await context.close(); }
}

async function main() {
  let args;
  try {
    const parsed = parseArgs(process.argv.slice(2));
    args = parsed.args;
    const config = await configFrom(args);
    const { chromium } = await import('playwright');
    const launch = { headless: true };
    if (args['--browser-path']) launch.executablePath = args['--browser-path'];
    if (args['--channel']) launch.channel = args['--channel'];
    const browser = await chromium.launch(launch);
    const results = [], blockedOrigins = new Set();
    try {
      for (const viewport of viewports) results.push(await runViewport(browser, parsed.url, config, viewport, Boolean(args['--allow-test-actions']), blockedOrigins));
    } finally { await browser.close(); }
    const failed = results.some(row => row.checks.some(item => item.status === 'failed'));
    const status = failed ? 'failed' : args['--allow-test-actions'] ? 'passed' : 'partial';
    const summary = { passed: 0, failed: 0, skipped: 0 };
    for (const row of results) for (const item of row.checks) summary[item.status]++;
    const report = {
      schemaVersion: 1, status, target: `${parsed.url.origin}${parsed.url.pathname}`,
      actionsEnabled: Boolean(args['--allow-test-actions']),
      keyboardSimulation: 'viewport-resize-only', realKeyboardTested: false,
      skipped: args['--allow-test-actions'] ? ['桌面 Enter 约定', '真实手机系统键盘与业务服务'] : ['Enter、草稿往返、历史滚动、测试发送、视口收缩交互', '真实手机系统键盘与业务服务'],
      summary, blockedOrigins: [...blockedOrigins].sort(), results,
    };
    await mkdir(path.dirname(path.resolve(args['--report'])), { recursive: true });
    await writeFile(args['--report'], `${JSON.stringify(report, null, 2)}\n`, 'utf8');
    process.stdout.write(`${status}: ${summary.passed} passed, ${summary.failed} failed, ${summary.skipped} skipped; report written\n`);
    process.exitCode = failed ? 1 : 0;
  } catch (error) {
    process.stderr.write(`检查未完成：${String(error.message)}\n`);
    process.exitCode = 2;
  }
}

await main();
