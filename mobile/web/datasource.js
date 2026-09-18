/* 数据层：行情 / K线 / 分时 / 资金流 / 财务 / 搜索
 *
 * 与桌面版（datasource.py）保持同一套 secid 体系：
 *   secid = "市场.代码"，如 1.600519（沪）/ 0.000001（深）/ 116.00700（港）/ 105.AAPL（美）
 *
 * 主源：腾讯财经（qt.gtimg.cn / web.ifzq.gtimg.cn）
 *   - 实测全部带 Access-Control-Allow-Origin，手机浏览器可直接 fetch
 *   - K线接口的 qt 节点同时返回行情快照，一次请求拿到 K线 + 快照
 * 备源：东方财富（资金流 / 财务 / 指数 K线）
 *   - push2 回显 Origin，datacenter 返回 *，同样可 fetch
 *   - 高频会被限流（RemoteDisconnected），必须重试 + 优雅降级
 *
 * 字段偏移踩坑（勿改）：
 *   A股 88 段、港股 78 段、美股 73 段，涨停/跌停/量比/均价的下标都不同，
 *   必须按市场分别映射（见 QTMAP）。成交额单位：A股为万元，港美股为元。
 */
(function (root) {
  'use strict';

  var DS = {};

  var QT = 'https://qt.gtimg.cn';
  var IFZQ = 'https://web.ifzq.gtimg.cn';
  var SMARTBOX = 'https://smartbox.gtimg.cn/s3/';
  var HIS = 'https://push2his.eastmoney.com';
  var LIVE = 'https://push2.eastmoney.com';
  var DATACENTER = 'https://datacenter-web.eastmoney.com';

  var SRC_TX = '腾讯财经';
  var SRC_EM = '东方财富';

  /* ---------------- 代码解析 ---------------- */

  // 各市场行情字段下标
  var QTMAP = {
    A: { name: 1, code: 2, price: 3, preclose: 4, open: 5, volume: 6, time: 30,
         change: 31, pct: 32, high: 33, low: 34, amount: 37, amountUnit: 1e4,
         turnover: 38, pe: 39, amplitude: 43, floatCap: 44, totalCap: 45,
         pb: 46, limitUp: 47, limitDown: 48, volRatio: 49, avg: 51,
         peTTM: 52, peStatic: 53, dec: 2 },
    HK: { name: 1, code: 2, price: 3, preclose: 4, open: 5, volume: 6, time: 30,
          change: 31, pct: 32, high: 33, low: 34, amount: 37, amountUnit: 1,
          turnover: null, pe: 39, amplitude: 43, floatCap: 44, totalCap: 45,
          pb: null, limitUp: 48, limitDown: 49, volRatio: 50, avg: null,
          peTTM: 51, peStatic: null, dec: 3 },
    US: { name: 1, code: 2, price: 3, preclose: 4, open: 5, volume: 6, time: 30,
          change: 31, pct: 32, high: 33, low: 34, amount: 37, amountUnit: 1,
          turnover: 38, pe: 39, amplitude: 43, floatCap: 44, totalCap: 45,
          pb: null, limitUp: null, limitDown: null, volRatio: 50, avg: null,
          peTTM: 51, peStatic: null, dec: 2 }
  };

  function marketOf(secid) {
    var m = String(secid || '').split('.', 1)[0];
    if (m === '0' || m === '1') { return 'A'; }
    if (m === '116') { return 'HK'; }
    if (m === '105' || m === '106' || m === '107') { return 'US'; }
    return 'OTHER';
  }

  function codeOf(secid) {
    var i = String(secid || '').indexOf('.');
    return i < 0 ? String(secid || '') : secid.slice(i + 1);
  }

  function secuCode(secid) {
    var code = codeOf(secid);
    var m = String(secid).split('.', 1)[0];
    if (m === '1') { return code + '.SH'; }
    if (m === '0') { return code + (/^[48]/.test(code) ? '.BJ' : '.SZ'); }
    if (m === '116') { return code + '.HK'; }
    return code;
  }

  /* 腾讯代码（行情用，美股不带交易所后缀） */
  function txQuoteSymbol(secid) {
    var m = String(secid).split('.', 1)[0];
    var code = codeOf(secid);
    if (m === '1') { return 'sh' + code; }
    if (m === '0') { return (/^[48]/.test(code) ? 'bj' : 'sz') + code; }
    if (m === '116') { return 'hk' + pad(code, 5); }
    if (m === '105' || m === '106' || m === '107') { return 'us' + code.toUpperCase(); }
    return code.toLowerCase();
  }

  /* 腾讯代码（K线用，美股必须带交易所后缀，否则只返回 1~2 根） */
  function txKlineSymbol(secid) {
    var m = String(secid).split('.', 1)[0];
    var code = codeOf(secid);
    if (m === '105' || m === '106' || m === '107') {
      var suf = { '105': '.OQ', '106': '.N', '107': '.A' }[m];
      return 'us' + code.toUpperCase() + suf;
    }
    return txQuoteSymbol(secid);
  }

  function pad(s, n) {
    s = String(s);
    while (s.length < n) { s = '0' + s; }
    return s;
  }

  /* 纯代码直接构造 secid，免联网 */
  DS.guessSecid = function (text) {
    var t = String(text || '').trim().toUpperCase();
    if (!t) { return null; }
    if (/^\d+\.[A-Z0-9._]+$/.test(t)) { return t; }
    if (/^\d{6}$/.test(t)) { return (/^[69]/.test(t) ? '1.' : '0.') + t; }
    if (/^\d{5}$/.test(t)) { return '116.' + t; }
    return null;
  };

  /* ---------------- 网络 ---------------- */

  function sleep(ms) {
    return new Promise(function (res) { setTimeout(res, ms); });
  }

  function fetchText(url, encoding, timeout) {
    var ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, timeout || 12000) : null;
    return fetch(url, {
      method: 'GET',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      signal: ctrl ? ctrl.signal : undefined
    }).then(function (res) {
      if (timer) { clearTimeout(timer); }
      if (!res.ok) { throw new Error('HTTP ' + res.status); }
      return res.arrayBuffer();
    }).then(function (buf) {
      if (timer) { clearTimeout(timer); }
      if (encoding && encoding !== 'utf-8' && typeof TextDecoder !== 'undefined') {
        try { return new TextDecoder(encoding).decode(buf); }
        catch (e) { /* 不支持该编码时按 utf-8 兜底 */ }
      }
      return new TextDecoder('utf-8').decode(buf);
    }).catch(function (err) {
      if (timer) { clearTimeout(timer); }
      throw err;
    });
  }

  function fetchJson(url, timeout) {
    return fetchText(url, 'utf-8', timeout).then(function (t) {
      return JSON.parse(t);
    });
  }

  /* 带重试的取数：腾讯稳定，2 次足够；东财限流重，多给几次 */
  function retry(fn, tries, delayMs) {
    var last = null;
    var chain = Promise.reject();
    for (var i = 0; i < tries; i++) {
      (function (k) {
        chain = chain.catch(function () {
          if (k > 0) { return sleep(delayMs * k); }
        }).then(function () {
          return fn();
        });
      })(i);
    }
    return chain.catch(function (e) { last = e; throw (last || e); });
  }

  /* 把 v_hint="..." 这类 JS 赋值串里的内容取出来 */
  function pickAssign(text, name) {
    var re = new RegExp(name + '\\s*=\\s*"([\\s\\S]*?)"\\s*;?\\s*$');
    var m = re.exec(text.trim());
    if (!m) { return null; }
    try {
      return JSON.parse('"' + m[1] + '"');
    } catch (e) {
      return m[1];
    }
  }

  /* ---------------- 搜索 ---------------- */

  /* 腾讯 smartbox：返回 v_hint="市场~代码~名称~拼音~类型^..."，无 CORS 头，必须走 script 标签 */
  function smartboxSearch(keyword) {
    return new Promise(function (resolve) {
      var s = document.createElement('script');
      var done = false;
      var finish = function (val) {
        if (done) { return; }
        done = true;
        try { if (s.parentNode) { s.parentNode.removeChild(s); } } catch (e) { /* ignore */ }
        resolve(val);
      };
      var timer = setTimeout(function () { finish([]); }, 8000);
      s.onload = function () {
        clearTimeout(timer);
        var raw = root.v_hint;
        try { delete root.v_hint; } catch (e) { root.v_hint = undefined; }
        if (typeof raw !== 'string' || !raw || raw === 'N') { finish([]); return; }
        var out = [];
        raw.split('^').forEach(function (row) {
          var p = row.split('~');
          if (p.length < 3) { return; }
          var mk = p[0], code = p[1], name = p[2];
          var secid = null;
          if (mk === 'sh') { secid = '1.' + code; }
          else if (mk === 'sz' || mk === 'bj') { secid = '0.' + code; }
          else if (mk === 'hk') { secid = '116.' + pad(code, 5); }
          else if (mk === 'us') {
            var c = code.split('.')[0].toUpperCase();
            var sfx = (code.split('.')[1] || '').toUpperCase();
            secid = ({ 'OQ': '105', 'N': '106', 'A': '107' }[sfx] || '105') + '.' + c;
          }
          if (secid) {
            out.push({ secid: secid, code: code, name: name, market: '腾讯' });
          }
        });
        finish(out);
      };
      s.onerror = function () { clearTimeout(timer); finish([]); };
      s.src = SMARTBOX + '?q=' + encodeURIComponent(keyword) + '&t=all&_=' +
              Date.now();
      document.head.appendChild(s);
    });
  }

  /* 输入解析：优先纯代码，其次搜索。返回 {secid, candidates} */
  DS.resolve = function (keyword) {
    var direct = DS.guessSecid(keyword);
    if (direct) { return Promise.resolve({ secid: direct, candidates: [] }); }
    return smartboxSearch(keyword).then(function (cands) {
      if (!cands.length) {
        throw new Error('没有找到「' + keyword + '」。试试直接输入 6 位代码（如 600519）'
                        + '、5 位港股代码（如 00700）或美股代码（如 AAPL）。');
      }
      var kw = String(keyword).trim();
      var kwu = kw.toUpperCase();
      var i;
      for (i = 0; i < cands.length; i++) {
        if (cands[i].code.toUpperCase() === kwu) {
          return { secid: cands[i].secid, candidates: [] };
        }
      }
      for (i = 0; i < cands.length; i++) {
        if (cands[i].name.replace(/\s/g, '') === kw.replace(/\s/g, '')) {
          return { secid: cands[i].secid, candidates: [] };
        }
      }
      if (cands.length === 1) {
        return { secid: cands[0].secid, candidates: [] };
      }
      return { secid: cands[0].secid, candidates: cands };
    });
  };

  /* ---------------- 行情快照 ---------------- */

  function num(v) {
    if (v === null || v === undefined || v === '') { return null; }
    var f = parseFloat(v);
    return isNaN(f) ? null : f;
  }

  /* 把腾讯 qt 数组（~ 分隔）转成统一 quote 结构 */
  function parseQt(arr, secid) {
    var kind = marketOf(secid);
    var m = QTMAP[kind];
    if (!arr || arr.length < 40 || !m) { return null; }
    var g = function (idx) { return (idx === null || idx === undefined) ? null : num(arr[idx]); };
    var price = g(m.price);
    if (!price) { return null; }
    var preclose = g(m.preclose);
    var amount = g(m.amount);
    if (amount !== null && m.amountUnit) { amount = amount * m.amountUnit; }
    var totalCap = g(m.totalCap);
    var floatCap = g(m.floatCap);
    var q = {
      secid: secid,
      kind: kind,
      name: String(arr[m.name] || '').trim(),
      code: String(arr[m.code] || '').trim(),
      price: price,
      preclose: preclose,
      open: g(m.open),
      high: g(m.high),
      low: g(m.low),
      change: g(m.change),
      pct: g(m.pct),
      volume: g(m.volume),
      amount: amount,
      amplitude: g(m.amplitude),
      turnover: g(m.turnover),
      volRatio: g(m.volRatio),
      limitUp: g(m.limitUp),
      limitDown: g(m.limitDown),
      avg: g(m.avg),
      pe: g(m.peTTM) !== null ? g(m.peTTM) : g(m.pe),
      pb: g(m.pb),
      bps: null,
      totalCap: totalCap === null ? null : totalCap * 1e8,
      floatCap: floatCap === null ? null : floatCap * 1e8,
      time: String(arr[m.time] || '').trim(),
      dec: m.dec,
      source: SRC_TX
    };
    // 成交量单位：A股为手，港美股为股 → 统一换算成「股」
    if (q.volume !== null && kind === 'A') { q.volume = q.volume * 100; }
    if (q.limitUp !== null && (!q.limitUp || q.limitUp <= 0)) { q.limitUp = null; }
    if (q.limitDown !== null && (!q.limitDown || q.limitDown <= 0)) { q.limitDown = null; }
    if (q.volRatio !== null && (!q.volRatio || q.volRatio <= 0)) { q.volRatio = null; }
    if (!q.change && q.preclose && q.price) { q.change = q.price - q.preclose; }
    if ((q.pct === null || q.pct === 0) && q.preclose && q.price) {
      q.pct = (q.price - q.preclose) / q.preclose * 100.0;
    }
    return q;
  }

  function quoteFromSym(sym, secid) {
    var url = QT + '/q=' + sym + '&_=' + Date.now();
    return fetchText(url, 'gbk').then(function (txt) {
      var i = txt.indexOf('="');
      if (i < 0) { return null; }
      var body = txt.slice(i + 2);
      var j = body.lastIndexOf('"');
      if (j >= 0) { body = body.slice(0, j); }
      return parseQt(body.split('~'), secid);
    });
  }

  /* 批量快照（自选股用）：qt.gtimg.cn 支持逗号分隔多只，一次请求全拿回来。
   * 返回 [{secid, quote}]，单只取不到时 quote 为 null，不让整批失败。 */
  DS.batchQuotes = function (secids) {
    if (!secids || !secids.length) { return Promise.resolve([]); }
    var map = {};
    var syms = [];
    secids.forEach(function (s) {
      var sym = txQuoteSymbol(s);
      map[sym.toLowerCase()] = s;
      syms.push(sym);
    });
    var url = QT + '/q=' + syms.join(',') + '&_=' + Date.now();
    return fetchText(url, 'gbk', 15000).then(function (txt) {
      var out = [];
      var re = /v_([A-Za-z0-9.]+)="([^"]*)";/g, m;
      while ((m = re.exec(txt)) !== null) {
        var secid = map[m[1].toLowerCase()];
        if (!secid) { continue; }
        out.push({ secid: secid, quote: parseQt(m[2].split('~'), secid) });
      }
      return out;
    }).catch(function () { return []; });
  };

  /* ---------------- K 线 ---------------- */

  var TX_PERIOD = { day: 'day', week: 'week', month: 'month' };

  function parseTxRows(rows, kind) {
    var lots = kind === 'A' ? 100.0 : 1.0;
    var bars = [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (!r || r.length < 6) { continue; }
      var o = num(r[1]), c = num(r[2]), h = num(r[3]), l = num(r[4]), v = num(r[5]);
      if (o === null || c === null || !o) { continue; }
      bars.push({
        d: String(r[0]),
        o: o, c: c, h: h, l: l, v: v,
        amt: v * lots * (h + l + c + o) / 4.0,
        amp: null, pct: null, chg: null, turn: null
      });
    }
    for (var k = bars.length - 1; k >= 0; k--) {
      var prev = k > 0 ? bars[k - 1].c : bars[k].o;
      var b = bars[k];
      if (prev) {
        b.pct = (b.c - prev) / prev * 100.0;
        b.chg = b.c - prev;
        b.amp = (b.h - b.l) / prev * 100.0;
      } else {
        b.pct = 0.0; b.chg = 0.0; b.amp = 0.0;
      }
    }
    return bars;
  }

  var KLINE_CACHE = {};

  /* 腾讯后复权的「最新一根」（当日盘中那根）复权因子经常是错的：
   * 该根实际是「原始价 × 错误因子」，跟前一根之间会出现假的大跌/大涨
   * （实测茅台 8933→8076、宁德时代 587→301，后者因子干脆是 1.0）。
   * 前复权的末根恒等于真实价，且 hfq/qfq 在完整 K 线上是常数比
   * （实测 7.0457 / 7.0614 / 7.0513），所以取完整 K 线比值中位数 K，
   * 整条序列按 qfq × K 重建，末根就跟着被修正了。 */
  function _median(a) {
    if (!a || !a.length) { return null; }
    var s = a.slice().sort(function (x, y) { return x - y; });
    var m = s.length >> 1;
    return (s.length % 2) ? s[m] : (s[m - 1] + s[m]) / 2.0;
  }

  function rebuildHfq(hfqBars, baseBars) {
    if (!hfqBars || !baseBars || hfqBars.length < 3 || baseBars.length < 3) {
      return false;
    }
    var map = {};
    for (var i = 0; i < baseBars.length; i++) { map[baseBars[i].d] = baseBars[i]; }
    var ratios = [];
    var pairs = [];
    for (var j = 0; j < hfqBars.length; j++) {
      var b = map[hfqBars[j].d];
      if (b && b.c && hfqBars[j].c) {
        pairs.push([hfqBars[j], b]);
        /* 末根可能带错误因子，不参与 K 的计算 */
        if (j < hfqBars.length - 1) { ratios.push(hfqBars[j].c / b.c); }
      }
    }
    if (pairs.length < 3 || ratios.length < 3) { return false; }
    var K = _median(ratios);
    if (!K || !(K > 0)) { return false; }
    for (var k = 0; k < pairs.length; k++) {
      var hb = pairs[k][0], bb = pairs[k][1];
      hb.o = bb.o * K;
      hb.h = bb.h * K;
      hb.l = bb.l * K;
      hb.c = bb.c * K;
      hb.amt = bb.amt * K;          /* 后复权下成交额同样按价格比例放大 */
    }
    /* 价格变了，涨跌幅/振幅要跟着重算 */
    for (var m = hfqBars.length - 1; m >= 0; m--) {
      var cur = hfqBars[m];
      var pv = m > 0 ? hfqBars[m - 1].c : cur.o;
      if (pv) {
        cur.pct = (cur.c - pv) / pv * 100.0;
        cur.chg = cur.c - pv;
        cur.amp = (cur.h - cur.l) / pv * 100.0;
      } else {
        cur.pct = 0.0; cur.chg = 0.0; cur.amp = 0.0;
      }
    }
    return true;
  }

  /* 取 K线；顺带把 qt 节点里的行情快照带出来，省一次请求 */
  function fetchKlineRaw(secid, period, adjust, limit) {
    var sym = txKlineSymbol(secid);
    var kind = marketOf(secid);
    var per = TX_PERIOD[period] || 'day';
    var fq = adjust === 'none' ? '' : adjust;
    var cnt = Math.max(60, Math.min(limit || 400, 800));
    var key = [sym, per, fq, cnt].join('|');
    if (KLINE_CACHE[key]) { return Promise.resolve(KLINE_CACHE[key]); }

    var url = IFZQ + '/appstock/app/fqkline/get?param=' +
              encodeURIComponent(sym + ',' + per + ',,,' + cnt + ',' + fq) +
              '&_=' + Date.now();
    return fetchJson(url).then(function (data) {
      var node = ((data || {}).data || {})[sym];
      if (!node) { throw new Error('腾讯未返回该标的的数据'); }
      var arr = node[fq + per] || node[per];
      if (!arr) {
        Object.keys(node).forEach(function (k) {
          if (!arr && Array.isArray(node[k]) && node[k].length &&
              k.indexOf(per) >= 0 && k.indexOf('qt') < 0) {
            arr = node[k];
          }
        });
      }
      if (!arr || !arr.length) { throw new Error('腾讯 K 线为空'); }
      var bars = parseTxRows(arr, kind);
      if (!bars.length) { throw new Error('腾讯 K 线解析失败'); }
      if (limit && bars.length > limit) { bars = bars.slice(bars.length - limit); }
      var qt = ((node.qt || {})[sym]) || null;
      var name = '';
      try { name = String((qt || [])[1] || '').trim(); } catch (e) { name = ''; }
      var res = { name: name, bars: bars, qt: qt, sym: sym };
      KLINE_CACHE[key] = res;
      if (fq !== 'hfq') { return res; }
      /* 后复权：再取一条末根准确的序列做基准，修正末根的复权因子 */
      function withBase(adj2) {
        return fetchKlineRaw(secid, period, adj2, limit).then(function (b) {
          if (b && b.bars && rebuildHfq(res.bars, b.bars)) {
            res.hfq_repaired = true;
            return true;
          }
          return false;
        }).catch(function () { return false; });
      }
      return withBase('qfq').then(function (ok) {
        if (ok) { return res; }
        return withBase('none').then(function () { return res; });
      });
    });
  }

  DS.clearCache = function () { KLINE_CACHE = {}; };
  DS._rebuildHfq = rebuildHfq;   /* 供离线单测 */

  /* ---------------- 分时 ---------------- */

  function fetchTrends(secid) {
    var sym = txKlineSymbol(secid);
    var url = IFZQ + '/appstock/app/minute/query?code=' +
              encodeURIComponent(sym) + '&_=' + Date.now();
    return fetchJson(url).then(function (data) {
      var node = ((data || {}).data || {})[sym];
      if (!node || !node.data) { throw new Error('分时数据为空'); }
      var inner = node.data;
      var preClose = null;
      var rows = inner.data || [];
      var pts = [];
      /* 腾讯分时的第 3/4 字段是「当日累计量 / 累计额」，不是每分钟增量。
       * 均价 = 累计额 / 累计量（这才是真正的 VWAP）；
       * 画柱状图要的是每分钟增量，所以这里做差分。跨日时重置。 */
      var prevV = 0, prevAmt = 0, prevHhmm = '';
      for (var i = 0; i < rows.length; i++) {
        // 必须 trim：有的行前面带空格，不 trim 会让 split 多出空段，整列错位
        var p = String(rows[i]).trim().split(/\s+/);
        if (p.length < 3 || !/^\d{4}$/.test(p[0])) { continue; }
        var hhmm = p[0];
        var c = num(p[1]);
        var cv = num(p[2]) || 0;
        var ca = p.length > 3 ? (num(p[3]) || 0) : 0;
        if (c === null) { continue; }
        if (hhmm <= prevHhmm) { prevV = 0; prevAmt = 0; }
        var dv = Math.max(0, cv - prevV);
        var da = Math.max(0, ca - prevAmt);
        pts.push({
          t: hhmm.slice(0, 2) + ':' + hhmm.slice(2),
          c: c,
          v: dv,
          cv: cv,
          amt: da,
          avg: cv ? (ca / cv) : null
        });
        prevV = cv; prevAmt = ca; prevHhmm = hhmm;
      }
      if (!pts.length) { throw new Error('分时数据为空'); }
      var qt = ((node.qt || {})[sym]) || null;
      if (qt) { preClose = num(qt[4]); }
      var nm = qt ? String(qt[1] || '') : '';
      return { name: nm, preclose: preClose, points: pts, qt: qt };
    });
  }

  /* ---------------- 资金流（东财） ---------------- */

  /* 附加数据（资金流 / 财务 / 大盘）都是「按标的、当天有效」的，
   * 而东财频控很凶。这里做会话内缓存 + 只缓存成功结果，
   * 切周期、切复权、切分时都不再重复打接口，请求量能降一个数量级。 */
  var EXTRA = {};
  var EXTRA_TTL = 10 * 60 * 1000;

  function cachedExtra(key, fetcher, isGood) {
    var e = EXTRA[key];
    if (e && Date.now() - e.t < EXTRA_TTL) { return Promise.resolve(e.v); }
    return fetcher().then(function (v) {
      if (isGood(v)) { EXTRA[key] = { t: Date.now(), v: v }; }
      return v;
    });
  }

  DS.clearExtraCache = function () { EXTRA = {}; KLINE_CACHE = {}; };

  function fetchFlow(secid, days) {
    days = days || 20;
    var f2 = 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61';
    var qs = 'secid=' + secid + '&lmt=' + days + '&klt=101' +
             '&fields1=f1,f2,f3,f7&fields2=' + f2 +
             '&ut=b2884a393a59ad64002292a3e90d46a5';
    var paths = ['/api/qt/stock/fflow/daykline/get',
                 '/api/qt/stock/fflow/kline/get'];
    var hosts = [HIS, LIVE];
    var attempts = [];
    hosts.forEach(function (h) {
      paths.forEach(function (p) { attempts.push(h + p + '?' + qs); });
    });

    // 逐次退避：东财是短时限流，连着打只会一直失败
    var waits = [0, 500, 1200, 2500];
    var chain = Promise.reject();
    attempts.forEach(function (u, i) {
      chain = chain.catch(function () {
        var w = waits[Math.min(i, waits.length - 1)];
        return w ? sleep(w) : null;
      }).then(function () {
        return fetchJson(u + '&_=' + Date.now(), 9000).then(function (d) {
          var k = ((d || {}).data || {}).klines;
          if (!k || !k.length) { throw new Error('空'); }
          return k;
        });
      });
    });
    return chain.then(function (klines) {
      var out = [];
      klines.forEach(function (line) {
        var p = String(line).split(',');
        if (p.length < 6) { return; }
        var f = function (i) { var v = num(p[i]); return v; };
        out.push({ d: p[0], main: f(1), small: f(2), mid: f(3),
                   big: f(4), huge: f(5) });
      });
      return out.slice(-days);
    }).catch(function () { return []; });
  }

  /* ---------------- 财务（东财，仅 A 股） ---------------- */

  var FIN_FIELDS = {
    EPSJB: '每股收益(元)',
    BPS: '每股净资产(元)',
    TOTALOPERATEREVE: '营业总收入(元)',
    TOTALOPERATEREVETZ: '营收同比(%)',
    PARENTNETPROFIT: '归母净利润(元)',
    PARENTNETPROFITTZ: '净利同比(%)',
    ROEJQ: '净资产收益率(%)',
    XSMLL: '销售毛利率(%)',
    XSJLL: '销售净利率(%)',
    ZCFZL: '资产负债率(%)',
    MGJYXJJE: '每股经营现金流(元)'
  };

  function fetchFinance(secid) {
    if (marketOf(secid) !== 'A') { return Promise.resolve({}); }
    var cols = Object.keys(FIN_FIELDS).join(',') +
               ',REPORT_DATE_NAME,NOTICE_DATE,REPORT_DATE';
    var url = DATACENTER + '/api/data/v1/get' +
              '?reportName=RPT_F10_FINANCE_MAINFINADATA' +
              '&columns=' + cols +
              '&filter=' + encodeURIComponent('(SECUCODE="' + secuCode(secid) + '")') +
              '&pageSize=2&sortColumns=REPORT_DATE&sortTypes=-1&_=' + Date.now();
    return fetchJson(url, 10000).then(function (data) {
      var rows = (((data || {}).result || {}).data) || [];
      if (!rows.length) { return {}; }
      var r = rows[0];
      var out = {
        _period: r.REPORT_DATE_NAME || String(r.REPORT_DATE || '').slice(0, 10),
        _notice: String(r.NOTICE_DATE || '').slice(0, 10),
        _source: SRC_EM
      };
      Object.keys(FIN_FIELDS).forEach(function (k) {
        out[FIN_FIELDS[k]] = (r[k] === undefined ? null : r[k]);
      });
      return out;
    }).catch(function () { return {}; });
  }

  /* ---------------- 大盘基准 ---------------- */

  var BENCH = {
    A: [['sh000300', '沪深300'], ['sh000001', '上证指数']],
    HK: [['hkHSI', '恒生指数'], ['hkHSCEI', '恒生国企指数']],
    US: [['usSPY.N', '标普500ETF'], ['usQQQ.OQ', '纳斯达克100ETF'],
         ['usAAPL.OQ', '苹果（代基准）']]
  };

  function benchBars(sym, period, adjust, limit) {
    var per = TX_PERIOD[period] || 'day';
    var fq = adjust || '';
    var url = IFZQ + '/appstock/app/fqkline/get?param=' +
              encodeURIComponent(sym + ',' + per + ',,,' + limit + ',' + fq) +
              '&_=' + Date.now();
    return fetchJson(url, 10000).then(function (data) {
      var node = ((data || {}).data || {})[sym];
      if (!node) { throw new Error('无基准数据'); }
      var arr = node[fq + per] || node[per];
      if (!arr) {
        Object.keys(node).forEach(function (k) {
          if (!arr && Array.isArray(node[k]) && node[k].length &&
              k.indexOf(per) >= 0 && k.indexOf('qt') < 0) { arr = node[k]; }
        });
      }
      if (!arr || arr.length < 30) { throw new Error('基准数据不足'); }
      var bars = [];
      for (var i = 0; i < arr.length; i++) {
        var r = arr[i];
        if (!r || r.length < 5) { continue; }
        var o = num(r[1]), c = num(r[2]), h = num(r[3]), l = num(r[4]);
        if (o === null || c === null || !o) { continue; }
        bars.push({ d: String(r[0]), o: o, c: c, h: h, l: l, v: num(r[5]) || 0,
                    amt: 0, amp: null, pct: null, chg: null, turn: null });
      }
      for (var k = bars.length - 1; k >= 0; k--) {
        var prev = k > 0 ? bars[k - 1].c : bars[k].o;
        if (prev) {
          bars[k].pct = (bars[k].c - prev) / prev * 100.0;
          bars[k].chg = bars[k].c - prev;
        } else {
          bars[k].pct = 0.0; bars[k].chg = 0.0;
        }
      }
      return bars;
    });
  }

  function fetchBenchmark(secid, period) {
    var kind = marketOf(secid);
    var list = BENCH[kind] || [];
    var adj = (kind === 'A' || kind === 'HK') ? 'qfq' : '';
    var idx = 0;
    function next() {
      if (idx >= list.length) { return Promise.resolve({ name: '', bars: [] }); }
      var item = list[idx++];
      return benchBars(item[0], period, adj, 200).then(function (bars) {
        return { name: item[1], bars: bars };
      }).catch(function () { return next(); });
    }
    return next();
  }

  /* 后复权对齐：K线是后复权序列（价格被放大），行情快照却是不复权价，
   * 两者混用会让价格阶梯的涨跌幅变成天文数字。这里统一用 K线口径重建报价。
   * 前复权 / 不复权最后一根就等于真实价，不需要处理。 */
  function alignToAdjusted(out, adjust) {
    if (adjust !== 'hfq') { return; }
    var bars = out.bars;
    if (!bars || bars.length < 2 || !out.quote) { return; }
    var last = bars[bars.length - 1];
    var prev = bars[bars.length - 2];
    var q = out.quote;
    q.price = last.c;
    q.open = last.o;
    q.high = last.h;
    q.low = last.l;
    q.preclose = prev.c;
    q.change = last.c - prev.c;
    q.pct = prev.c ? (last.c - prev.c) / prev.c * 100.0 : 0.0;
    q.volume = last.v;
    q.amount = last.amt;
    q.avg = last.v ? (last.amt / last.v) : null;
    /* 涨跌停是不复权口径，后复权下没有意义 */
    q.limitUp = null;
    q.limitDown = null;
    q.adjustedPrice = true;
    if (last.h && last.l && prev.c) {
      q.amplitude = (last.h - last.l) / prev.c * 100.0;
    }
  }

  /* ---------------- 组合抓取 ---------------- */

  DS.loadAll = function (secid, period, adjust, limit) {
    period = period || 'day';
    adjust = adjust || 'qfq';
    limit = limit || 400;
    var kind = marketOf(secid);
    var out = { quote: null, bars: [], kline_source: '', flow: [],
                finance: {}, bench_name: '', bench_bars: [] };

    if (period === 'trend') {
      return fetchTrends(secid).then(function (tr) {
        out.kline_source = SRC_TX;
        out.trends = tr.points;
        out.quote = parseQt(tr.qt, secid) ||
                    { secid: secid, kind: kind, name: tr.name, code: codeOf(secid),
                      price: tr.points[tr.points.length - 1].c,
                      preclose: tr.preclose, dec: kind === 'HK' ? 3 : 2,
                      source: SRC_TX };
        if (out.quote && !out.quote.name) { out.quote.name = tr.name; }
        return out;
      });
    }

    return fetchKlineRaw(secid, period, adjust, limit).then(function (kl) {
      out.bars = kl.bars;
      out.kline_source = SRC_TX;
      var q = parseQt(kl.qt, secid);
      if (!q) {
        return quoteFromSym(txQuoteSymbol(secid), secid).then(function (q2) {
          out.quote = q2 || { secid: secid, kind: kind, name: kl.name,
                              code: codeOf(secid),
                              price: kl.bars[kl.bars.length - 1].c,
                              preclose: null, dec: kind === 'HK' ? 3 : 2,
                              source: SRC_TX };
          if (!out.quote.name) { out.quote.name = kl.name; }
          return afterQuote();
        });
      }
      out.quote = q;
      if (!out.quote.name) { out.quote.name = kl.name; }
      return afterQuote();

      function afterQuote() {
        var jobs = [
          cachedExtra('flow|' + secid,
                      function () { return fetchFlow(secid, 20); },
                      function (v) { return v && v.length; })
            .then(function (f) { out.flow = f || []; }),
          cachedExtra('fin|' + secid,
                      function () { return fetchFinance(secid); },
                      function (v) { return v && Object.keys(v).length; })
            .then(function (f) { out.finance = f || {}; }),
          cachedExtra('bench|' + secid + '|' + period,
                      function () { return fetchBenchmark(secid, period); },
                      function (v) { return v && v.bars && v.bars.length; })
            .then(function (b) {
              out.bench_name = b.name;
              out.bench_bars = b.bars;
            })];
        return Promise.all(jobs).then(function () {
          alignToAdjusted(out, adjust);
          return out;
        });
      }
    });
  };

  DS.marketOf = marketOf;
  DS.codeOf = codeOf;
  DS.secuCode = secuCode;
  DS.txQuoteSymbol = txQuoteSymbol;
  DS.txKlineSymbol = txKlineSymbol;
  DS._parseQt = parseQt;
  DS._parseTxRows = parseTxRows;
  DS._retry = retry;
  DS.SRC_TX = SRC_TX;
  DS.SRC_EM = SRC_EM;

  root.DS = DS;
  if (typeof module !== 'undefined' && module.exports) { module.exports = DS; }
})(typeof window !== 'undefined' ? window : globalThis);
