/* 给自选股面板拍一张照（复用 _browser_check.js 的 CDP 套路） */
'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9345;
const PAGE = path.join(__dirname, '..', 'build', '股票分析助手.html');
const OUT = path.join(__dirname, '_shot_e_fav.png');

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function reqJson(url, method) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.request({ hostname: u.hostname, port: u.port,
      path: u.pathname + u.search, method: method || 'GET' }, res => {
      let b = '';
      res.on('data', d => { b += d; });
      res.on('end', () => { try { resolve(JSON.parse(b)); } catch (e) { reject(e); } });
    });
    req.on('error', reject);
    req.end();
  });
}

(async () => {
  const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'safav-'));
  const child = spawn(EDGE, [
    '--headless=new', '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + prof, '--no-first-run', '--disable-gpu',
    '--window-size=414,900', '--hide-scrollbars', 'about:blank'
  ], { stdio: 'ignore' });

  let ver = null;
  for (let i = 0; i < 50; i++) {
    await sleep(300);
    try { ver = await reqJson('http://127.0.0.1:' + PORT + '/json/version'); break; }
    catch (e) { /* wait */ }
  }
  if (!ver) { throw new Error('Edge 没起来'); }
  const target = await reqJson('http://127.0.0.1:' + PORT + '/json/new?' +
    encodeURIComponent('file:///' + PAGE.replace(/\\/g, '/')), 'PUT');

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => { ws.onopen = r; });
  let mid = 0;
  const pend = {};
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pend[m.id]) { pend[m.id](m); delete pend[m.id]; }
  };
  const send = (method, params) => new Promise(res => {
    const id = ++mid;
    pend[id] = res;
    ws.send(JSON.stringify({ id, method, params: params || {} }));
  });
  const evalJs = async expr => {
    const r = await send('Runtime.evaluate',
      { expression: expr, returnByValue: true, awaitPromise: true });
    return r.result && r.result.result ? r.result.result.value : undefined;
  };
  const waitFor = async (cond, ms) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      if (await evalJs(cond)) { return true; }
      await sleep(400);
    }
    return false;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await waitFor('!!window.__app', 15000);
  await waitFor('window.__app.state.analysis && !window.__app.state.busy', 50000);

  // 造两只自选：当前茅台 + 宁德时代
  await evalJs("localStorage.removeItem('sa_favs');" +
               "document.getElementById('favStar').click(); 'ok'");
  await evalJs("document.getElementById('kw').value='300750';" +
               "document.getElementById('go').click(); 'ok'");
  await waitFor("window.__app.state.secid==='0.300750' && !window.__app.state.busy" +
                " && window.__app.state.analysis", 50000);
  await evalJs("document.getElementById('favStar').click(); 'ok'");
  await evalJs("document.getElementById('favBtn').click(); 'ok'");
  await waitFor("document.querySelectorAll('#favSheet .fav-row').length >= 2" +
                " && document.querySelector('#favSheet .fav-px').textContent !== '…'",
                30000);
  await sleep(600);

  const shot = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(OUT, Buffer.from(shot.result.data, 'base64'));

  const rows = await evalJs(`(function(){
    var a=[];
    Array.prototype.forEach.call(document.querySelectorAll('#favSheet .fav-row'),
      function(r){a.push(Array.prototype.map.call(r.children,
        function(c){return c.textContent;}).join(' | '));});
    return a.join('\\n');
  })()`);
  fs.writeFileSync(path.join(__dirname, '_shot_fav.txt'),
    '截图: ' + OUT + '\n' + rows, 'utf-8');

  ws.close();
  child.kill();
  await sleep(400);
  fs.rmSync(prof, { recursive: true, force: true });
  console.log('done');
  process.exit(0);
})().catch(e => { console.error(e && e.stack ? e.stack : e); process.exit(1); });
