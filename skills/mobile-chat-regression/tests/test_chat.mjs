import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const skill = fileURLToPath(new URL('../', import.meta.url));
const script = path.join(skill, 'scripts/check_chat_layout.mjs');
const config = path.join(skill, 'examples/selectors.json');
const output = path.resolve(skill, '../../qa/mobile');

async function invoke(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [script, ...args], { cwd: skill });
    let stdout = '', stderr = '';
    child.stdout.on('data', x => { stdout += x; });
    child.stderr.on('data', x => { stderr += x; });
    child.on('error', reject);
    child.on('close', code => resolve({ code, stdout, stderr }));
  });
}

async function startDemoServer() {
  const index = await readFile(path.join(skill, 'examples/index.html'), 'utf8');
  const help = await readFile(path.join(skill, 'examples/help.html'), 'utf8');
  const server = createServer((req, res) => {
    const url = new URL(req.url, 'http://localhost');
    let html = url.pathname.endsWith('help.html') ? help : index;
    if (url.searchParams.get('broken') === 'enter' && !url.pathname.endsWith('help.html')) {
      html = html.replace('</body>', '<script>document.querySelector("#draft").addEventListener("keydown",event=>{if(event.key==="Enter")event.preventDefault()});</script></body>');
    }
    if (url.searchParams.get('broken') === 'layout') {
      html = html.replace('</head>', '<style>.chat{min-width:800px}</style></head>');
    }
    if (url.searchParams.get('broken') === 'discard' && !url.pathname.endsWith('help.html')) {
      html = html.replace('</body>', '<script>document.querySelector("#composer").addEventListener("submit",event=>{event.preventDefault();event.stopImmediatePropagation();document.querySelector("#draft").value="";const log=document.querySelector("#history");log.scrollTop=log.scrollHeight;},{capture:true});</script></body>');
    }
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(html);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return { server, url: `http://127.0.0.1:${server.address().port}/index.html` };
}

test('synthetic chat passes real viewport, draft and scroll interactions; broken input is rejected', async () => {
  await mkdir(output, { recursive: true });
  const { server, url } = await startDemoServer();
  const browser = process.env.PEASKILL_BROWSER ? ['--browser-path', process.env.PEASKILL_BROWSER] : [];
  try {
    const goodReport = path.join(output, 'good.json');
    const good = await invoke(['--url', url, '--config', config, '--report', goodReport, '--allow-test-actions', ...browser]);
    assert.equal(good.code, 0, good.stderr || good.stdout);
    const goodData = JSON.parse(await readFile(goodReport, 'utf8'));
    assert.equal(goodData.status, 'passed');
    assert.equal(goodData.results.length, 4);
    assert.equal(goodData.results.every(row => row.checks.every(check => check.status === 'passed' || (row.viewport.width > 600 && check.id === 'mobile-enter-newline' && check.status === 'skipped'))), true);
    const enterChecks = goodData.results.map(row => row.checks.find(check => check.id === 'mobile-enter-newline').status);
    assert.deepEqual(enterChecks, ['passed', 'passed', 'passed', 'skipped']);
    assert.equal(goodData.realKeyboardTested, false);

    const layoutReport = path.join(output, 'layout-fault.json');
    const layout = await invoke(['--url', `${url}?broken=layout`, '--config', config, '--report', layoutReport, ...browser]);
    assert.equal(layout.code, 1, layout.stderr || layout.stdout);
    const layoutData = JSON.parse(await readFile(layoutReport, 'utf8'));
    assert.equal(layoutData.results.some(row => row.checks.some(check => check.id === 'horizontal-overflow' && check.status === 'failed')), true);

    const enterReport = path.join(output, 'enter-fault.json');
    const enter = await invoke(['--url', `${url}?broken=enter`, '--config', config, '--report', enterReport, '--allow-test-actions', ...browser]);
    assert.equal(enter.code, 1, enter.stderr || enter.stdout);
    const enterData = JSON.parse(await readFile(enterReport, 'utf8'));
    assert.equal(enterData.results.some(row => row.checks.some(check => check.id === 'mobile-enter-newline' && check.status === 'failed')), true);
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});

test('discarded message fails even when input clears and history scrolls to the bottom', async () => {
  await mkdir(output, { recursive: true });
  const { server, url } = await startDemoServer();
  const browser = process.env.PEASKILL_BROWSER ? ['--browser-path', process.env.PEASKILL_BROWSER] : [];
  try {
    const report = path.join(output, 'discard-fault.json');
    const result = await invoke(['--url', `${url}?broken=discard`, '--config', config, '--report', report, '--allow-test-actions', ...browser]);
    assert.equal(result.code, 1, result.stderr || result.stdout);
    const data = JSON.parse(await readFile(report, 'utf8'));
    assert.equal(data.results.every(row => row.checks.some(check => check.id === 'send-scroll-bottom' && check.status === 'failed')), true);
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});

test('remote targets and ambiguous CLI arguments are rejected before navigation', async () => {
  const remote = await invoke(['--url', 'https://example.invalid', '--config', config, '--report', path.join(output, 'remote.json')]);
  assert.equal(remote.code, 2);
  assert.match(remote.stderr, /allow-remote/);
  const typo = await invoke(['--url', 'http://localhost', '--config', config, '--report', path.join(output, 'typo.json'), '--alow-test-actions']);
  assert.equal(typo.code, 2);
  assert.match(typo.stderr, /未知参数/);
});
