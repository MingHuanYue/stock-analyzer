/* 用系统 Edge 无头模式 + CDP 真实校验网页版：串一遍主要使用路径。 */
'use strict';
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9333;
const OUTDIR = __dirname;
const REPORT = path.join(OUTDIR, '_browser_report.txt');
const PAGE = process.argv[2] ||
  path.join(__dirname, '..', 'build', '股票分析助手.html');

const lines = [];
function say(s) { lines.push(s); console.log(s); }
function save() { fs.writeFileSync(REPORT, lines.join('\n'), 'utf-8'); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function reqJson(url, method) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.request({
      hostname: u.hostname, port: u.port, path: u.pathname + u.search,
      method: method || 'GET'
    }, res => {
      let b = '';
      res.on('data', d => { b += d; });
      res.on('end', () => {
        try { resolve(JSON.parse(b)); }
        catch (e) { reject(new Error('HTTP ' + res.statusCode + ': ' + b.slice(0, 120))); }
      });
    });
    req.on('error', reject);
    req.end();
  });
}

const SNAP = `(function(){
  var s = window.__app && window.__app.state;
  if (!s) { return { hasApp:false }; }
  var panel = document.getElementById('panel');
  var secs = [];
  if (panel) {
    Array.prototype.forEach.call(panel.querySelectorAll('.sec-h b'), function(b){
      secs.push(b.textContent);
    });
  }
  var rows = [];
  if (panel) {
    Array.prototype.forEach.call(panel.querySelectorAll('.kv .k, .kv .v'), function(n){
      rows.push(n.textContent);
    });
  }
  var ladder = [];
  if (panel) {
    Array.prototype.forEach.call(panel.querySelectorAll('.ladder .row'), function(r){
      ladder.push(Array.prototype.map.call(r.children, function(c){return c.textContent;})
                  .join(' | '));
    });
  }
  return {
    secid: s.secid, period: s.period, adjust: s.adjust, busy: s.busy,
    quote: s.quote ? {name:s.quote.name, code:s.quote.code, price:s.quote.price,
                      pct:s.quote.pct, dec:s.quote.dec, source:s.quote.source,
                      pe:s.quote.pe, pb:s.quote.pb, cap:s.quote.totalCap,
                      turn:s.quote.turnover, vr:s.quote.volRatio,
                      lu:s.quote.limitUp, amt:s.quote.amount} : null,
    bars: s.bundle ? (s.bundle.bars||[]).length : 0,
    trends: s.bundle && s.bundle.trends ? s.bundle.trends.length : 0,
    ksrc: s.bundle ? s.bundle.kline_source : null,
    flowN: s.bundle ? (s.bundle.flow||[]).length : 0,
    finN: s.bundle ? Object.keys(s.bundle.finance||{}).length : 0,
    bench: s.bundle ? s.bundle.bench_name : null,
    benchN: s.bundle ? (s.bundle.bench_bars||[]).length : 0,
    score: s.analysis ? s.analysis.score : null,
    level: s.analysis ? s.analysis.level : null,
    bulls: s.analysis ? s.analysis.bulls.length : null,
    bears: s.analysis ? s.analysis.bears.length : null,
    dims: s.analysis ? s.analysis.dims.map(function(d){return d.name+'='+Math.round(d.score);}) : [],
    risk: s.analysis ? s.analysis.risk.score : null,
    secs: secs,
    kvSample: rows.slice(0, 24),
    ladder: ladder,
    err: (panel && panel.textContent.indexOf('获取失败') >= 0)
         ? panel.textContent.slice(0, 300) : null,
    canvas: (function(){ var c=document.getElementById('chart');
                         return c ? c.width+'x'+c.height : null; })(),
    legend: (document.getElementById('legend')||{}).textContent || '',
    hint: (document.getElementById('hint')||{}).textContent || ''
  };
})()`;

(async () => {
  const profile = path.join(os.tmpdir(), 'edge-cdp-' + Date.now());
  const child = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-first-run',
    '--no-default-browser-check', '--disable-extensions',
    '--allow-file-access-from-files',
    '--remote-debugging-port=' + PORT,
    '--user-data-dir=' + profile,
    '--window-size=412,900', 'about:blank'
  ], { stdio: 'ignore' });
  say('启动 Edge 无头模式');
  say('目标页面: ' + PAGE);

  let ver = null;
  for (let i = 0; i < 40; i++) {
    try { ver = await reqJson('http://127.0.0.1:' + PORT + '/json/version'); break; }
    catch (e) { await sleep(400); }
  }
  if (!ver) { say('!! 调试端口未就绪'); child.kill(); save(); return process.exit(1); }
  say('浏览器: ' + ver['Browser']);

  const target = await reqJson('http://127.0.0.1:' + PORT + '/json/new?' +
    encodeURIComponent('file:///' + PAGE.replace(/\\/g, '/')), 'PUT');

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();
  const events = [];
  function send(method, params) {
    return new Promise((resolve, reject) => {
      const mid = ++id;
      pending.set(mid, { resolve, reject });
      ws.send(JSON.stringify({ id: mid, method, params: params || {} }));
    });
  }
  await new Promise((res, rej) => {
    ws.addEventListener('open', res);
    ws.addEventListener('error', rej);
  });
  ws.addEventListener('message', ev => {
    let m;
    try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      if (m.error) { p.reject(new Error(JSON.stringify(m.error))); }
      else { p.resolve(m.result); }
    } else if (m.method) { events.push(m); }
  });

  await send('Runtime.enable');
  await send('Page.enable');
  await send('Log.enable');
  await send('Page.navigate', { url: 'file:///' + PAGE.replace(/\\/g, '/') });

  async function evalJs(expr) {
    const r = await send('Runtime.evaluate', {
      expression: expr, awaitPromise: true, returnByValue: true
    });
    if (r.exceptionDetails) {
      throw new Error(r.exceptionDetails.text + ' ' +
        JSON.stringify((r.exceptionDetails.exception || {}).description || ''));
    }
    return r.result.value;
  }

  async function waitFor(cond, label, ms) {
    const r = await evalJs(`new Promise(function(resolve){
      var t0 = Date.now();
      function tick(){
        var ok = false;
        try { ok = (${cond}); } catch(e) { ok = false; }
        if (ok) { resolve('ok'); return; }
        if (Date.now() - t0 > ${ms || 40000}) { resolve('timeout'); return; }
        setTimeout(tick, 400);
      }
      tick();
    })`);
    return r;
  }

  async function scenario(label, cond, ms) {
    const st = await waitFor(cond, label, ms);
    const info = await evalJs(SNAP);
    say('');
    say('======== ' + label + '  [' + st + '] ========');
    say('  标的 ' + info.secid + '  周期 ' + info.period + '  复权 ' + info.adjust);
    if (info.quote) {
      say('  行情 ' + info.quote.name + ' ' + info.quote.code + '  价 ' +
          info.quote.price + '  涨跌 ' + info.quote.pct + '%  dec=' +
          info.quote.dec + '  源=' + info.quote.source);
      say('  估值 PE=' + info.quote.pe + ' PB=' + info.quote.pb +
          ' 市值=' + info.quote.cap + ' 换手=' + info.quote.turn +
          ' 量比=' + info.quote.vr + ' 涨停=' + info.quote.lu +
          ' 成交额=' + info.quote.amt);
    }
    say('  数据 bars=' + info.bars + ' trends=' + info.trends + ' K线源=' + info.ksrc +
        ' 资金流=' + info.flowN + ' 财务字段=' + info.finN +
        ' 大盘=' + info.bench + '(' + info.benchN + ')');
    say('  分析 评分=' + (info.score === null ? 'null' : info.score.toFixed(2)) +
        ' (' + info.level + ')  看多=' + info.bulls + ' 看空=' + info.bears +
        ' 风险=' + info.risk);
    say('  维度 ' + JSON.stringify(info.dims));
    say('  章节(' + info.secs.length + ') ' + JSON.stringify(info.secs));
    say('  阶梯 ' + JSON.stringify(info.ladder));
    say('  画布 ' + info.canvas + '  副条=' + info.legend + ' | ' + info.hint);
    if (info.err) { say('  !! 错误页: ' + info.err); }
    return info;
  }

  async function shot(name) {
    try {
      const s = await send('Page.captureScreenshot', { format: 'png' });
      const p = path.join(OUTDIR, name);
      fs.writeFileSync(p, Buffer.from(s.data, 'base64'));
      say('  截图 ' + name + ' (' + Math.round(fs.statSync(p).size / 1024) + ' KB)');
    } catch (e) { say('  截图失败 ' + e.message); }
  }

  const results = [];
  let info;

  const dayInfo = await scenario('1) 默认 A股 日K', 'window.__app && window.__app.state.analysis && !window.__app.state.busy', 50000);
  results.push(dayInfo);
  await shot('_shot_a_ashare.png');

  // 切周K：用来验证分时不会拿周线数据算分析（缓存键必须带周期）
  await evalJs(`document.querySelector('#segPeriod button[data-v="week"]').click(); 'ok'`);
  const weekInfo = await scenario('2) 周K', "window.__app.state.period==='week' && !window.__app.state.busy && window.__app.state.analysis", 40000);
  results.push(weekInfo);

  // 切分时：分析应等于日线口径，不能等于周线
  await evalJs(`document.querySelector('#segPeriod button[data-v="trend"]').click(); 'ok'`);
  info = await scenario('3) 分时（须沿用日线分析）',
    "window.__app.state.period==='trend' && !window.__app.state.busy && window.__app.state.bundle.trends", 40000);
  results.push(info);
  await shot('_shot_b_trend.png');

  let cacheOk = null;
  if (dayInfo.score !== null && weekInfo.score !== null && info.score !== null) {
    const sameAsDay = Math.abs(info.score - dayInfo.score) < 1e-6;
    const sameAsWeek = Math.abs(info.score - weekInfo.score) < 1e-6;
    cacheOk = sameAsDay && !sameAsWeek;
    say('  ★ 缓存口径检查: 日线=' + dayInfo.score.toFixed(3) +
        ' 周线=' + weekInfo.score.toFixed(3) +
        ' 分时=' + info.score.toFixed(3) +
        ' → ' + (cacheOk ? '分时沿用了日线（正确）' : '异常！'));
  }

  // 切回日K + 后复权
  await evalJs(`document.querySelector('#segPeriod button[data-v="day"]').click();
                document.querySelector('#segAdjust button[data-v="hfq"]').click(); 'ok'`);
  info = await scenario('4) 日K + 后复权', "window.__app.state.period==='day' && window.__app.state.adjust==='hfq' && !window.__app.state.busy", 40000);
  results.push(info);

  // 港股
  await evalJs(`document.getElementById('kw').value='00700';
                document.getElementById('go').click(); 'ok'`);
  info = await scenario('5) 港股 腾讯控股', "window.__app.state.secid==='116.00700' && !window.__app.state.busy && window.__app.state.analysis", 50000);
  results.push(info);
  await shot('_shot_c_hk.png');

  // 美股
  await evalJs(`document.getElementById('kw').value='AAPL';
                document.getElementById('go').click(); 'ok'`);
  info = await scenario('6) 美股 苹果', "window.__app.state.secid==='105.AAPL' && !window.__app.state.busy && window.__app.state.analysis", 50000);
  results.push(info);
  await shot('_shot_d_us.png');

  // 中文名搜索
  await evalJs(`document.getElementById('kw').value='宁德时代';
                document.getElementById('go').click(); 'ok'`);
  info = await scenario('7) 中文名 宁德时代', "window.__app.state.secid==='0.300750' && !window.__app.state.busy && window.__app.state.analysis", 50000);
  results.push(info);

  // 不存在的代码
  await evalJs(`document.getElementById('kw').value='zzz9999xxx';
                document.getElementById('go').click(); 'ok'`);
  await waitFor("window.__app.state.busy===false && (document.getElementById('panel').textContent.indexOf('获取失败')>=0 || document.getElementById('panel').textContent.indexOf('没有找到')>=0)", 'err', 25000);
  const bad = await evalJs(SNAP);
  say('');
  say('======== 8) 无效输入 ========');
  say('  错误提示: ' + (bad.err ? bad.err.replace(/\s+/g, ' ').slice(0, 200) : '（没有出现错误页）'));

  // 价位阶梯合理性：任何一档涨跌幅超过 60% 都说明口径串了
  say('');
  say('======== 9) 阶梯口径自检（|涨跌幅| > 60% 视为异常） ========');
  let ladderBad = 0;
  results.forEach(function (info, k) {
    (info.ladder || []).forEach(function (row) {
      const m = /([+-]?\d+(?:\.\d+)?)%/.exec(row);
      if (m && Math.abs(parseFloat(m[1])) > 60) {
        say('  !! 场景' + (k + 1) + ' ' + info.period + '/' + info.adjust +
            '  ' + row);
        ladderBad++;
      }
    });
  });
  say(ladderBad === 0 ? '  全部正常' : ('  异常 ' + ladderBad + ' 条'));

  // 自选股：加星 → 面板批量取价 → 点行加载 → 移出 → 持久化
  say('');
  say('======== 10) 自选股 ========');
  let favOk = false;
  try {
    await evalJs("localStorage.removeItem('sa_favs'); 'ok'");
    // 当前在宁德时代，点星收藏
    await evalJs("document.getElementById('favStar').click(); 'ok'");
    const f1 = await evalJs(
      "JSON.stringify({favs: JSON.parse(localStorage.getItem('sa_favs')||'[]')," +
      "star: document.getElementById('favStar').textContent})");
    // 切到茅台再收藏
    await evalJs("document.getElementById('kw').value='600519';" +
                 "document.getElementById('go').click(); 'ok'");
    await waitFor("window.__app.state.secid==='1.600519' && !window.__app.state.busy" +
                  " && window.__app.state.analysis", 'maotai', 50000);
    await evalJs("document.getElementById('favStar').click(); 'ok'");
    // 打开自选面板
    await evalJs("document.getElementById('favBtn').click(); 'ok'");
    await waitFor("document.querySelectorAll('#favSheet .fav-row').length >= 2" +
                  " && document.querySelector('#favSheet .fav-px').textContent !== '…'",
                  'favrows', 30000);
    const panel = await evalJs(`(function(){
      var rows = [];
      Array.prototype.forEach.call(document.querySelectorAll('#favSheet .fav-row'),
        function(r){ rows.push(Array.prototype.map.call(r.children,
          function(c){return c.textContent;}).join('|')); });
      return JSON.stringify({n: rows.length, rows: rows});
    })()`);
    const pv = JSON.parse(panel);
    say('  面板行数=' + pv.n);
    pv.rows.forEach(r => say('  ' + r));
    // 点第一行（茅台，最新加的在前）应加载茅台
    await evalJs("document.querySelectorAll('#favSheet .fav-row')[0].click(); 'ok'");
    await waitFor("window.__app.state.secid==='1.600519' && !window.__app.state.busy",
                  'favload', 50000);
    // 打开面板移出茅台
    await evalJs("document.getElementById('favBtn').click(); 'ok'");
    await waitFor("document.querySelectorAll('#favSheet .fav-row').length >= 1",
                  'favrows2', 15000);
    await evalJs("document.querySelector('#favSheet .fav-del').click(); 'ok'");
    await sleep(400);
    const f2 = await evalJs(
      "JSON.stringify({favs: JSON.parse(localStorage.getItem('sa_favs')||'[]')," +
      "star: document.getElementById('favStar').textContent})");
    const d1 = JSON.parse(f1), d2 = JSON.parse(f2);
    const hasPrice = pv.rows.some(r => /[0-9]+\.[0-9]+/.test(r));
    favOk = d1.favs.length === 1 && d1.favs[0].secid === '0.300750' &&
            d1.star === '★' && pv.n === 2 && hasPrice &&
            d2.favs.length === 1 && d2.favs[0].secid === '0.300750' &&
            d2.star === '☆';
    say('  收藏' + (d1.star === '★' ? '星标点亮' : '星标未亮') +
        '，面板取价' + (hasPrice ? '正常' : '异常') +
        '，移出后剩 ' + d2.favs.length + ' 只（应为 1 只宁德时代）' +
        '，星标' + (d2.star === '☆' ? '已熄灭' : '未熄灭'));
    say(favOk ? '  ==> 通过' : '  ==> 未通过');
    await evalJs("var w=document.getElementById('favSheet');" +
                 "if(w){w.parentNode.removeChild(w);} 'ok'");
  } catch (e) {
    say('  自选股场景异常: ' + (e && e.message ? e.message : e));
  }

  const errs = events.filter(e => e.method === 'Log.entryAdded' &&
                                  e.params.entry.level === 'error');
  say('');
  say('控制台错误 ' + errs.length + ' 条:');
  const uniq = {};
  errs.forEach(e => { uniq[e.params.entry.text.slice(0, 90)] = (uniq[e.params.entry.text.slice(0, 90)] || 0) + 1; });
  Object.keys(uniq).forEach(k => say('  x' + uniq[k] + '  ' + k));

  const good = results.filter(r => r && r.score !== null && r.secs &&
                                   r.secs.length >= 10 && r.err === null).length;
  say('');
  say('======== 汇总 ========');
  say('有效场景 ' + results.length + '，通过 ' + good);
  say('分时缓存口径: ' + (cacheOk === null ? '未测到' :
                        (cacheOk ? '正确' : '错误')));
  say('自选股: ' + (favOk ? '通过' : '未通过'));
  const allOk = good === results.length && ladderBad === 0 && cacheOk !== false &&
                favOk;
  say(allOk ? '==== 判定: 全部通过 ====' : '==== 判定: 有场景未通过 ====');

  try { ws.close(); } catch (e) { /* ignore */ }
  child.kill();
  await sleep(500);
  save();
  process.exit(allOk ? 0 : 2);
})().catch(err => {
  say('异常: ' + (err && err.stack ? err.stack : err));
  save();
  process.exit(1);
});
