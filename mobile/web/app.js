/* 股票分析助手 · 手机版 —— 界面控制与渲染 */
(function () {
  'use strict';

  var DISCLAIMER = '免责声明：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。' +
    '市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标' +
    '独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。';

  var KIND_NAME = { A: 'A股', HK: '港股', US: '美股', OTHER: '' };
  var PERIOD_NAME = { trend: '分时', day: '日K', week: '周K', month: '月K' };
  var ADJUST_NAME = { qfq: '前复权', none: '不复权', hfq: '后复权' };
  var TONE = { up: 't-up', down: 't-down', warn: 't-warn', flat: 't-flat' };

  var UP = '#f0453a', DOWN = '#12b886', WARN = '#f2b544', DIM = '#94a1b5';

  var $ = function (id) { return document.getElementById(id); };

  var chart = null;
  var state = {
    secid: '1.600519',
    period: 'day',
    adjust: 'qfq',
    sub: 'MACD',
    bundle: null,
    analysis: null,
    ind: null,
    busy: false,
    reqId: 0
  };
  var CACHE = {};   // secid|period|adjust -> {bars, ind, analysis, quote, bundle}

  /* ---------------- 小工具 ---------------- */

  function fnum(v, dec) {
    if (v === null || v === undefined || isNaN(v)) { return '—'; }
    return Number(v).toFixed(dec === undefined ? 2 : dec);
  }

  function fsigned(v, dec, suffix) {
    if (v === null || v === undefined || isNaN(v)) { return '—'; }
    var s = Number(v).toFixed(dec === undefined ? 2 : dec);
    if (Number(v) > 0) { s = '+' + s; }
    return s + (suffix || '');
  }

  function big(v) {
    if (v === null || v === undefined || isNaN(v)) { return '—'; }
    var a = Math.abs(v);
    if (a >= 1e12) { return (v / 1e12).toFixed(2) + '万亿'; }
    if (a >= 1e8) { return (v / 1e8).toFixed(2) + '亿'; }
    if (a >= 1e4) { return (v / 1e4).toFixed(2) + '万'; }
    return String(Math.round(v));
  }

  function signMoney(v) {
    if (v === null || v === undefined || isNaN(v)) { return '—'; }
    return (v >= 0 ? '+' : '-') + big(Math.abs(v));
  }

  function toneColor(tone) {
    return tone === 'up' ? '#f08d85' : tone === 'down' ? '#6fd0b0'
         : tone === 'warn' ? WARN : DIM;
  }

  function cls(v, ref) {
    if (v === null || v === undefined || ref === null || ref === undefined) {
      return 'flat';
    }
    return v > ref ? 'up' : (v < ref ? 'down' : 'flat');
  }

  function el(tag, cls2, text) {
    var e = document.createElement(tag);
    if (cls2) { e.className = cls2; }
    if (text !== undefined && text !== null) { e.textContent = text; }
    return e;
  }

  function toast(msg, ms) {
    var t = $('toast');
    t.textContent = msg;
    t.classList.add('on');
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { t.classList.remove('on'); }, ms || 3200);
  }

  function marketStatus(kind) {
    var d = new Date();
    var wd = d.getDay();
    if (wd === 0 || wd === 6) { return '周末休市（显示最近收盘数据）'; }
    var hm = d.getHours() * 60 + d.getMinutes();
    if (kind === 'A') {
      if (hm >= 555 && hm < 570) { return '集合竞价中'; }
      if ((hm >= 570 && hm <= 690) || (hm >= 780 && hm <= 900)) { return '交易中'; }
      return (hm > 690 && hm < 780) ? '午间休市' : '已收盘';
    }
    if (kind === 'HK') {
      if ((hm >= 570 && hm <= 720) || (hm >= 780 && hm <= 960)) { return '交易中'; }
      return (hm > 720 && hm < 780) ? '午间休市' : '已收盘';
    }
    if (kind === 'US') {
      var et = (hm + 24 * 60 - 12 * 60) % (24 * 60);   // 北京时间 -12h ≈ 美东
      if (et >= 1290 || et <= 240) { return '交易中（美东盘）'; }
      return '休市（显示最近收盘数据）';
    }
    return '';
  }

  /* ---------------- 自选股 ---------------- */

  var FAV_KEY = 'sa_favs';
  var FAV_MAX = 50;

  function favs() {
    try {
      var v = JSON.parse(localStorage.getItem(FAV_KEY) || '[]');
      return Array.isArray(v) ? v : [];
    } catch (e) { return []; }
  }

  function saveFavs(list) {
    try { localStorage.setItem(FAV_KEY, JSON.stringify(list)); } catch (e) {}
  }

  function isFav(secid) {
    return favs().some(function (f) { return f.secid === secid; });
  }

  function syncFavStar() {
    var b = $('favStar');
    if (!b) { return; }
    var on = !!(state.quote && isFav(state.secid));
    b.textContent = on ? '★' : '☆';
    b.classList.toggle('on', on);
    b.disabled = !state.quote;
  }

  function toggleFav() {
    var q = state.quote;
    if (!q || !state.secid) { toast('先查一只股票再加自选'); return; }
    var list = favs();
    var idx = -1;
    list.forEach(function (f, k) { if (f.secid === state.secid) { idx = k; } });
    if (idx >= 0) {
      list.splice(idx, 1);
      toast('已移出自选：' + (q.name || q.code));
    } else {
      if (list.length >= FAV_MAX) { toast('自选最多 ' + FAV_MAX + ' 只'); return; }
      list.unshift({ secid: state.secid, name: q.name || '',
                     code: q.code || '', kind: q.kind || 'OTHER' });
      toast('已加入自选：' + (q.name || q.code));
    }
    saveFavs(list);
    syncFavStar();
  }

  function closeFavSheet() {
    var w = document.getElementById('favSheet');
    if (w && w.parentNode) { w.parentNode.removeChild(w); }
  }

  function openFavSheet() {
    closeFavSheet();
    var wrap = el('div', 'sheet');
    wrap.id = 'favSheet';
    var box = el('div', 'box');
    var head = el('h4');
    head.appendChild(el('span', null, '自选股（点一行查看，点 × 移出）'));
    var re = el('em', 'fav-refresh', '刷新');
    re.addEventListener('click', function () { renderFavRows(body); });
    head.appendChild(re);
    box.appendChild(head);
    var body = el('div', 'fav-list');
    box.appendChild(body);
    var cancel = el('div', 'cancel', '关闭');
    cancel.addEventListener('click', closeFavSheet);
    box.appendChild(cancel);
    wrap.appendChild(box);
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap) { closeFavSheet(); }
    });
    document.body.appendChild(wrap);
    renderFavRows(body);
  }

  function renderFavRows(body) {
    var list = favs();
    body.innerHTML = '';
    if (!list.length) {
      body.appendChild(el('div', 'fav-empty',
        '还没有自选股。查到一只股票后，点行情头右侧的 ☆ 加入。'));
      return;
    }
    var cells = {};
    list.forEach(function (f) {
      var row = el('div', 'fav-row');
      var nm = el('b', null, f.name || f.code || f.secid);
      row.appendChild(nm);
      row.appendChild(el('span', 'fav-code',
        (KIND_NAME[f.kind] || '') + ' ' + (f.code || '')));
      var px = el('span', 'fav-px flat', '…');
      var pc = el('span', 'fav-pct flat', '');
      row.appendChild(px);
      row.appendChild(pc);
      var del = el('span', 'fav-del', '×');
      del.addEventListener('click', function (e) {
        e.stopPropagation();
        saveFavs(favs().filter(function (x) { return x.secid !== f.secid; }));
        syncFavStar();
        renderFavRows(body);
        toast('已移出自选：' + (f.name || f.code));
      });
      row.appendChild(del);
      row.addEventListener('click', function () {
        closeFavSheet();
        $('kw').value = f.code || '';
        load(f.secid, state.period, state.adjust);
      });
      body.appendChild(row);
      cells[f.secid] = { px: px, pc: pc, nm: nm };
    });
    /* 批量取价：一次请求全部拿回来，单只失败不影响其他 */
    DS.batchQuotes(list.map(function (f) { return f.secid; }))
      .then(function (qs) {
        if (!document.body.contains(body)) { return; }
        var got = {};
        qs.forEach(function (x) { got[x.secid] = x.quote; });
        list.forEach(function (f) {
          var r = cells[f.secid];
          var q = got[f.secid];
          if (!r) { return; }
          if (q && q.price) {
            r.px.textContent = fnum(q.price, q.dec === undefined ? 2 : q.dec);
            var c = (q.pct || 0) > 0 ? 'up' : ((q.pct || 0) < 0 ? 'down' : 'flat');
            r.px.className = 'fav-px ' + c;
            r.pc.className = 'fav-pct ' + c;
            r.pc.textContent = fsigned(q.pct, 2, '%');
            if (q.name) { r.nm.textContent = q.name; }
          } else {
            r.px.textContent = '—';
            r.pc.textContent = '';
          }
        });
      });
  }

  /* ---------------- 行情头 ---------------- */

  function renderQuote(q) {
    if (!q) { return; }
    $('qcode').textContent = q.code || '';
    $('qtag').textContent = (KIND_NAME[q.kind] || '') +
      (q.adjustedPrice ? ' · 后复权价' : '');
    document.querySelector('.q-name').textContent = q.name || '';
    var last = $('qlast'), chg = $('qchg');
    last.textContent = fnum(q.price, q.dec === undefined ? 2 : q.dec);
    var c = (q.pct || 0) > 0 ? 'up' : ((q.pct || 0) < 0 ? 'down' : 'flat');
    last.className = 'q-last ' + c;
    chg.className = 'q-chg ' + c;
    chg.textContent = fsigned(q.change, q.dec === undefined ? 2 : q.dec) + '  ' +
                      fsigned(q.pct, 2, '%');
    $('qstatus').textContent = marketStatus(q.kind);
    document.title = (q.name || '股票分析助手') + ' ' + (q.code || '');
  }

  /* ---------------- 面板 ---------------- */

  function section(title) {
    var sec = el('div', 'sec');
    var h = el('div', 'sec-h');
    h.appendChild(el('i'));
    h.appendChild(el('b', null, title));
    sec.appendChild(h);
    var body = el('div');
    sec.appendChild(body);
    $('panel').appendChild(sec);
    return body;
  }

  function kv(parent, items) {
    var g = el('div', 'kv');
    items.forEach(function (it) {
      g.appendChild(el('div', 'k', it[0]));
      var v = el('div', 'v', it[1]);
      if (it[2]) { v.style.color = it[2]; }
      g.appendChild(v);
    });
    parent.appendChild(g);
  }

  function barTrack(parent, score, color, note) {
    var w = el('div', 'bar-wrap');
    var top = el('div', 'score-top');
    if (note) { top.appendChild(el('span', null, note)); }
    var num = el('span', null, Math.round(score) + ' 分');
    num.style.color = color;
    top.appendChild(num);
    w.appendChild(top);
    var t = el('div', 'track');
    var i = el('i');
    i.style.width = Math.max(2, Math.min(100, score)) + '%';
    i.style.background = color;
    t.appendChild(i);
    w.appendChild(t);
    parent.appendChild(w);
  }

  function renderPanel(q, res) {
    var p = $('panel');
    p.innerHTML = '';

    /* 盘口速览 */
    var b = section('盘口速览');
    kv(b, [
      ['今开', fnum(q.open, 2), toneColor(cls(q.open, q.preclose))],
      ['昨收', fnum(q.preclose, 2)],
      ['最高', fnum(q.high, 2), toneColor(cls(q.high, q.preclose))],
      ['最低', fnum(q.low, 2), toneColor(cls(q.low, q.preclose))],
      ['成交量', q.volume === null || q.volume === undefined ? '—'
                 : big(q.volume / 100) + '手'],
      ['成交额', big(q.amount)],
      ['振幅', q.amplitude === null || q.amplitude === undefined ? '—'
               : fnum(q.amplitude, 2) + '%'],
      ['换手率', q.turnover === null || q.turnover === undefined || !q.turnover
                 ? '—' : fnum(q.turnover, 2) + '%'],
      ['量比', q.volRatio === null || q.volRatio === undefined ? '—'
               : fnum(q.volRatio, 2), toneColor(cls(q.volRatio, 1))],
      ['涨停', q.limitUp ? fnum(q.limitUp, 2) : '—', UP],
      ['跌停', q.limitDown ? fnum(q.limitDown, 2) : '—', DOWN],
      ['均价', q.avg ? fnum(q.avg, 2) : '—', toneColor(cls(q.avg, q.preclose))]
    ]);

    /* 估值与规模 */
    b = section('估值与规模');
    kv(b, [
      ['总市值', big(q.totalCap)],
      ['流通市值', big(q.floatCap)],
      ['市盈率', q.pe === null || q.pe === undefined ? '—' : fnum(q.pe, 2)],
      ['市净率', q.pb === null || q.pb === undefined ? '—' : fnum(q.pb, 2)],
      ['更新时间', q.time || '—'],
      ['数据源', (q.source || '—') + (q.adjustedPrice ? '（后复权口径）' : ''), DIM]
    ]);

    /* 技术指标快照 */
    var ind = res._ind, i = res._bars.length - 1, px = q.price;
    function at(k) {
      var s = ind[k];
      if (!s) { return null; }
      var v = s[i];
      return (v === null || v === undefined || isNaN(v)) ? null : v;
    }
    b = section('技术指标快照');
    kv(b, [
      ['MA5', fnum(at('ma5'), 2), toneColor(cls(px, at('ma5')))],
      ['MA10', fnum(at('ma10'), 2), toneColor(cls(px, at('ma10')))],
      ['MA20', fnum(at('ma20'), 2), toneColor(cls(px, at('ma20')))],
      ['MA60', fnum(at('ma60'), 2), toneColor(cls(px, at('ma60')))],
      ['DIF', fnum(at('dif'), 3), toneColor(cls(at('dif'), 0))],
      ['DEA', fnum(at('dea'), 3), toneColor(cls(at('dea'), 0))],
      ['K', fnum(at('k'), 2)],
      ['D', fnum(at('d'), 2)],
      ['J', fnum(at('j'), 2)],
      ['RSI6', fnum(at('rsi6'), 2)],
      ['RSI12', fnum(at('rsi12'), 2)],
      ['RSI24', fnum(at('rsi24'), 2)],
      ['布林上轨', fnum(at('boll_up'), 2), DIM],
      ['布林中轨', fnum(at('boll_mid'), 2), DIM],
      ['布林下轨', fnum(at('boll_dn'), 2), DIM],
      ['ATR14', fnum(at('atr14'), 2), DIM]
    ]);

    /* 资金流向 */
    var flow = (state.bundle && state.bundle.flow) || [];
    b = section('资金流向');
    if (flow.length) {
      var f0 = flow[flow.length - 1];
      kv(b, [
        ['日期', f0.d || '—', DIM],
        ['主力净额', signMoney(f0.main), toneColor(cls(f0.main, 0))],
        ['超大单', signMoney(f0.huge), toneColor(cls(f0.huge, 0))],
        ['大单', signMoney(f0.big), toneColor(cls(f0.big, 0))],
        ['中单', signMoney(f0.mid), toneColor(cls(f0.mid, 0))],
        ['小单', signMoney(f0.small), toneColor(cls(f0.small, 0))]
      ]);
      if (flow.length >= 5) {
        var vals = flow.slice(-5).map(function (r2) { return r2.main; })
                       .filter(function (v) { return v !== null && !isNaN(v); });
        if (vals.length) {
          var tot = vals.reduce(function (a, c) { return a + c; }, 0);
          var lb = el('div', 'summary',
                      '近 5 日主力合计 ' + signMoney(tot));
          lb.style.color = toneColor(cls(tot, 0));
          b.appendChild(lb);
        }
      }
    } else {
      b.appendChild(el('div', 'summary',
        '资金流数据暂不可用（东方财富接口被限流或该市场无此数据）'));
    }

    /* 财务摘要 */
    var fin = (state.bundle && state.bundle.finance) || {};
    if (fin && Object.keys(fin).length) {
      b = section('财务摘要 (' + (fin._period || '—') + ')');
      kv(b, [
        ['营业总收入', big(fin['营业总收入(元)'])],
        ['营收同比', fin['营收同比(%)'] === null || fin['营收同比(%)'] === undefined
                       ? '—' : fnum(fin['营收同比(%)'], 2) + '%',
         toneColor(cls(fin['营收同比(%)'], 0))],
        ['归母净利润', big(fin['归母净利润(元)'])],
        ['净利同比', fin['净利同比(%)'] === null || fin['净利同比(%)'] === undefined
                       ? '—' : fnum(fin['净利同比(%)'], 2) + '%',
         toneColor(cls(fin['净利同比(%)'], 0))],
        ['净资产收益率', fin['净资产收益率(%)'] === null ? '—'
                           : fnum(fin['净资产收益率(%)'], 2) + '%'],
        ['销售毛利率', fin['销售毛利率(%)'] === null ? '—'
                         : fnum(fin['销售毛利率(%)'], 2) + '%'],
        ['销售净利率', fin['销售净利率(%)'] === null ? '—'
                         : fnum(fin['销售净利率(%)'], 2) + '%'],
        ['资产负债率', fin['资产负债率(%)'] === null ? '—'
                         : fnum(fin['资产负债率(%)'], 2) + '%'],
        ['每股收益', fin['每股收益(元)'] === null ? '—'
                       : fnum(fin['每股收益(元)'], 2)],
        ['每股净资产', fin['每股净资产(元)'] === null ? '—'
                         : fnum(fin['每股净资产(元)'], 2)]
      ]);
      var src = el('div', 'summary',
        '数据源：东方财富 F10，报告期 ' + (fin._period || '—') +
        '（公告日 ' + (fin._notice || '—') + '）');
      b.appendChild(src);
    }

    /* 综合诊断 */
    b = section('综合诊断');
    barTrack(b, res.score, res.score >= 58 ? UP : (res.score < 43 ? DOWN : WARN),
             '技术面综合评分（' + res.level + '）');
    var vd = el('div', 'verdict', res.verdict);
    vd.style.color = toneColor(res.level_tone);
    b.appendChild(vd);
    b.appendChild(el('div', 'plain', res.plain));
    b.appendChild(el('div', 'summary', res.summary));

    /* 多空信号对照 */
    b = section('多空信号对照（看多 ' + res.bulls.length + ' 项 / 看空 ' +
                res.bears.length + ' 项）');
    if (res.bulls.length) {
      var h1 = el('div', 'sig-h', '▲ 支撑价格的信号');
      h1.style.color = UP;
      b.appendChild(h1);
      res.bulls.forEach(function (t) {
        var d = el('div', 'sig sig-bull');
        d.appendChild(el('em', null, '·'));
        d.appendChild(el('span', null, t));
        b.appendChild(d);
      });
    }
    if (res.bears.length) {
      var h2 = el('div', 'sig-h', '▼ 压制价格的信号');
      h2.style.color = DOWN;
      b.appendChild(h2);
      res.bears.forEach(function (t) {
        var d = el('div', 'sig sig-bear');
        d.appendChild(el('em', null, '·'));
        d.appendChild(el('span', null, t));
        b.appendChild(d);
      });
    }
    if (!res.bulls.length && !res.bears.length) {
      b.appendChild(el('div', 'summary', '当前没有触发明确的多空信号，市场处于均衡状态。'));
    }

    /* 分维度评分 */
    b = section('分维度评分');
    res.dims.forEach(function (d) {
      var w = el('div', 'dim');
      var top = el('div', 'dim-top');
      top.appendChild(el('b', null, d.name));
      top.appendChild(el('em', null, d.note));
      var sc = el('span', null, Math.round(d.score));
      sc.style.color = toneColor(d.tone);
      top.appendChild(sc);
      w.appendChild(top);
      var t = el('div', 'track');
      var i2 = el('i');
      i2.style.width = Math.max(2, Math.min(100, d.score)) + '%';
      i2.style.background = toneColor(d.tone);
      t.appendChild(i2);
      w.appendChild(t);
      b.appendChild(w);
    });

    /* 波动与风险 */
    var rk = res.risk;
    b = section('波动与风险（' + rk.level + '）');
    var rkColor = rk.score >= 68 ? DOWN : (rk.score >= 45 ? WARN : UP);
    barTrack(b, rk.score, rkColor, '波动风险（数值越高风险越大）');
    rk.items.forEach(function (it) {
      var lb = el('div', 'sig');
      lb.style.color = toneColor(it[1]);
      lb.appendChild(el('em', null, '·'));
      lb.appendChild(el('span', null, it[0]));
      b.appendChild(lb);
    });

    /* 关键价位阶梯 */
    b = section('关键价位阶梯');
    var lad = el('div', 'ladder');
    var resists = (res.resists || []).slice();
    var supports = (res.supports || []).slice();
    var close = (q.price || 0);
    for (var r = resists.length - 1; r >= 0; r--) {
      lad.appendChild(ladderRow('压力' + (r + 1), resists[r], close, 'r-res'));
    }
    lad.appendChild(ladderRow('当前价', ['最新收盘', close], close, 'now'));
    for (var s = 0; s < supports.length; s++) {
      lad.appendChild(ladderRow('支撑' + (s + 1), supports[s], close, 'r-sup'));
    }
    b.appendChild(lad);

    /* 详细分析 */
    b = section('详细分析');
    var dl = el('div', 'seclist');
    res.sections.forEach(function (sec2, idx) {
      var d = document.createElement('details');
      if (idx === 0) { d.open = true; }
      var sm = document.createElement('summary');
      sm.textContent = sec2[0];
      d.appendChild(sm);
      var ul = el('ul');
      sec2[1].forEach(function (it) {
        var li = el('li', TONE[it[1]] || 't-flat', it[0]);
        ul.appendChild(li);
      });
      d.appendChild(ul);
      dl.appendChild(d);
    });
    b.appendChild(dl);

    /* 情景应对 */
    b = section('情景应对（条件化参考）');
    var cards = el('div', 'cards');
    res.scenarios.forEach(function (sc) {
      var c = el('div', 'card');
      var bb = el('b', null, sc[0]);
      bb.style.color = toneColor(sc[3]);
      c.appendChild(bb);
      c.appendChild(el('p', null, sc[1]));
      c.appendChild(el('p', null, sc[2]));
      cards.appendChild(c);
    });
    b.appendChild(cards);

    /* 免责声明 */
    var disc = el('div', 'disc', DISCLAIMER);
    p.appendChild(disc);
    var foot = el('div', 'foot',
      '股票分析助手 · 手机版  数据来自公开行情接口，需联网，仅供研究学习使用');
    p.appendChild(foot);
  }

  function ladderRow(tag, item, close, kindCls) {
    var row = el('div', 'row ' + (kindCls === 'now' ? 'now' : ''));
    var tg = el('span', 'tag', tag);
    tg.classList.add(kindCls);
    row.appendChild(tg);
    var price = item[1];
    row.appendChild(el('span', 'nm', item[0]));
    var px = el('span', 'px', fnum(price, 2));
    px.classList.add(kindCls);
    row.appendChild(px);
    var gap = (close && price) ? (price - close) / close * 100 : null;
    var gp = el('span', 'gp', gap === null ? '' : fsigned(gap, 2, '%'));
    gp.classList.add(kindCls);
    row.appendChild(gp);
    return row;
  }

  /* ---------------- 取数与渲染 ---------------- */

  function setBusy(on, text) {
    state.busy = on;
    $('go').disabled = on;
    if (on && text) {
      $('panel').innerHTML = '';
      var ld = el('div', 'loading');
      ld.appendChild(el('span', 'spin'));
      ld.appendChild(el('span', null, text));
      $('panel').appendChild(ld);
    }
  }

  function cacheKey(secid, period, adjust) {
    return secid + '|' + period + '|' + adjust;
  }

  function load(secid, period, adjust, sub) {
    state.secid = secid;
    state.period = period || state.period;
    state.adjust = adjust || state.adjust;
    if (sub) { state.sub = sub; }
    var my = ++state.reqId;
    setBusy(true, '正在联网获取数据…');

    // 分时本身不产出 K 线，分析要挂在「同标的同复权的日线」上，故用日线缓存槽
    var baseKey = cacheKey(secid, 'day', state.adjust);
    var jobs = [DS.loadAll(secid, state.period, state.adjust, 400)];
    if (state.period === 'trend' && !CACHE[baseKey]) {
      jobs.push(DS.loadAll(secid, 'day', state.adjust, 400));
    }

    Promise.all(jobs).then(function (all) {
      if (my !== state.reqId) { return; }
      var bundle = all[0];
      state.bundle = bundle;

      var bars, ind, analysis, quote;
      if (state.period === 'trend') {
        var base = CACHE[baseKey] || (all[1] ? buildBase(all[1], 'day') : null);
        if (!base) { throw new Error('缺少日线数据，无法生成分析'); }
        bars = base.bars; ind = base.ind; analysis = base.analysis;
        quote = bundle.quote || base.quote;
        // 分时接口只给分时点，资金流/财务/大盘沿用日线那次的结果
        bundle.flow = base.flow || [];
        bundle.finance = base.finance || {};
        bundle.bench_name = base.bench_name || '';
        bundle.bench_bars = base.bench_bars || [];
      } else {
        var r = buildBase(bundle);
        bars = r.bars; ind = r.ind; analysis = r.analysis; quote = bundle.quote;
      }
      if (!bars || !bars.length) { throw new Error('没有取到 K 线数据'); }

      state.quote = quote;
      state.ind = ind;
      state.analysis = analysis;
      analysis._ind = ind;
      analysis._bars = bars;

      renderQuote(quote);
      syncFavStar();
      chart.setData({
        period: state.period,
        sub: state.sub,
        dec: (quote && quote.dec) || 2,
        quote: quote,
        bars: bars,
        ind: ind,
        trends: bundle.trends || null
      });
      renderPanel(quote, analysis);
      $('panel').scrollTop = 0;
      setBusy(false);
      $('hint').textContent = bundle.kline_source ? ('K线：' + bundle.kline_source) : '';
      try {
        localStorage.setItem('sa_last', secid);
        localStorage.setItem('sa_period', state.period);
        localStorage.setItem('sa_adjust', state.adjust);
      } catch (e) { /* 隐私模式忽略 */ }
    }).catch(function (err) {
      if (my !== state.reqId) { return; }
      setBusy(false);
      renderError(err && err.message ? err.message : String(err));
    });
  }

  /* period 必须显式传入：缓存键 = secid|period|adjust。
   * 早前写死 'day'，导致切到周K时把周线结果写进了日线缓存槽，
   * 再切回分时就会用周线数据出分析。 */
  function buildBase(bundle, period) {
    var key = cacheKey(bundle.quote ? bundle.quote.secid : state.secid, period,
                       state.adjust);
    var bars = bundle.bars;
    if (!bars || !bars.length) { throw new Error('没有取到 K 线数据'); }
    var ind = AN.computeIndicators(bars);
    var analysis = AN.buildAnalysis(
      bundle.quote, bars, ind, bundle.flow || [], bundle.finance || {},
      bundle.bench_bars && bundle.bench_bars.length ? bundle.bench_bars : null,
      bundle.bench_name || '', period);
    CACHE[key] = {
      bars: bars, ind: ind, analysis: analysis, quote: bundle.quote,
      flow: bundle.flow || [], finance: bundle.finance || {},
      bench_name: bundle.bench_name || '', bench_bars: bundle.bench_bars || []
    };
    return { bars: bars, ind: ind, analysis: analysis,
             quote: bundle.quote, flow: bundle.flow || [],
             finance: bundle.finance || {},
             bench_name: bundle.bench_name || '',
             bench_bars: bundle.bench_bars || [] };
  }

  function renderError(msg) {
    var p = $('panel');
    p.innerHTML = '';
    var b = section('获取失败');
    var d = el('div', 'plain', msg);
    d.style.color = UP;
    b.appendChild(d);
    b.appendChild(el('div', 'summary',
      '建议：确认手机能上网；稍等十几秒再点「查询」。' +
      '也可以直接输入 6 位 A 股代码（600519）、5 位港股代码（00700）或美股代码（AAPL）。'));
  }

  /* ---------------- 搜索 ---------------- */

  function doSearch() {
    var kw = $('kw').value.trim();
    if (!kw) { toast('请输入股票代码或名称'); return; }
    // 点「查询」视为强制刷新：清掉缓存，否则会拿到会话内旧数据
    if (DS.clearExtraCache) { DS.clearExtraCache(); }
    setBusy(true, '正在搜索…');
    DS.resolve(kw).then(function (r) {
      if (r.candidates && r.candidates.length > 1) {
        setBusy(false);
        pickCandidate(r.candidates, kw);
      } else {
        load(r.secid, state.period, state.adjust);
      }
    }).catch(function (err) {
      setBusy(false);
      renderError(err && err.message ? err.message : String(err));
    });
  }

  function pickCandidate(list, kw) {
    var wrap = el('div', 'sheet');
    var box = el('div', 'box');
    box.appendChild(el('h4', null, '「' + kw + '」找到多个结果，请选择'));
    list.forEach(function (c) {
      var it = el('div', 'item');
      it.appendChild(el('b', null, c.name));
      it.appendChild(el('span', null, c.code));
      it.appendChild(el('em', null, c.market || ''));
      it.addEventListener('click', function () {
        document.body.removeChild(wrap);
        $('kw').value = c.code;
        load(c.secid, state.period, state.adjust);
      });
      box.appendChild(it);
    });
    var cancel = el('div', 'cancel', '取消');
    cancel.addEventListener('click', function () { document.body.removeChild(wrap); });
    box.appendChild(cancel);
    wrap.appendChild(box);
    wrap.addEventListener('click', function (e) {
      if (e.target === wrap) { document.body.removeChild(wrap); }
    });
    document.body.appendChild(wrap);
  }

  /* ---------------- 事件绑定 ---------------- */

  function bindSeg(id, key, cb) {
    var seg = $(id);
    seg.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) { return; }
      Array.prototype.forEach.call(seg.querySelectorAll('button'), function (b) {
        b.classList.toggle('on', b === btn);
      });
      cb(btn.getAttribute('data-v'));
    });
  }

  function boot() {
    chart = new Chart($('chart'));
    chart.onCross = function () {
      $('legend').textContent = chart.legendText();
    };
    window.addEventListener('resize', function () { chart.resize(); });
    window.addEventListener('orientationchange', function () {
      setTimeout(function () { chart.resize(); }, 260);
    });

    $('go').addEventListener('click', doSearch);
    $('favBtn').addEventListener('click', openFavSheet);
    $('favStar').addEventListener('click', toggleFav);
    $('kw').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); $('kw').blur(); doSearch(); }
    });

    bindSeg('segPeriod', 'period', function (v) {
      if (v === state.period) { return; }
      load(state.secid, v, state.adjust);
    });
    bindSeg('segAdjust', 'adjust', function (v) {
      if (v === state.adjust) { return; }
      load(state.secid, state.period, v);
    });
    bindSeg('segSub', 'sub', function (v) {
      state.sub = v;
      if (state.analysis) {
        chart.setData({
          period: state.period, sub: v,
          dec: (state.quote && state.quote.dec) || 2,
          quote: state.quote, bars: state.analysis._bars,
          ind: state.ind, trends: (state.bundle || {}).trends || null
        });
      }
    });

    var last = null, per = null, adj = null;
    try {
      last = localStorage.getItem('sa_last');
      per = localStorage.getItem('sa_period');
      adj = localStorage.getItem('sa_adjust');
    } catch (e) { /* ignore */ }
    if (per && PERIOD_NAME[per]) { state.period = per; syncSeg('segPeriod', per); }
    if (adj && ADJUST_NAME[adj]) { state.adjust = adj; syncSeg('segAdjust', adj); }

    $('kw').value = '';
    chart.resize();
    load(last || '1.600519', state.period, state.adjust);
  }

  function syncSeg(id, v) {
    Array.prototype.forEach.call($(id).querySelectorAll('button'), function (b) {
      b.classList.toggle('on', b.getAttribute('data-v') === v);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  /* 调试用 */
  window.__app = { state: state, load: load, chart: function () { return chart; },
                   favs: favs, toggleFav: toggleFav, openFavSheet: openFavSheet };
})();
