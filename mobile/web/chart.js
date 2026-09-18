/* 手机版 K 线图：Canvas 手绘，触屏缩放 / 拖动 / 十字光标
 * 配色与桌面版一致（涨红跌绿，中国习惯）
 * 布局：价格区 58% · 成交量 16% · 副图 26%
 */
(function (root) {
  'use strict';

  var C = {
    bg: '#0e1218', grid: '#1e2532', border: '#2a3345',
    text: '#e2e8f2', dim: '#94a1b5', mute: '#5f6b7d',
    up: '#f0453a', down: '#12b886', flat: '#8b96a8',
    accent: '#4c8dff', warn: '#f2b544'
  };

  var MA = [
    ['ma5', 'MA5', '#f5a623'],
    ['ma10', 'MA10', '#4c8dff'],
    ['ma20', 'MA20', '#b06bd9'],
    ['ma60', 'MA60', '#3fbfa0']
  ];

  var FONT = '-apple-system,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif';
  var MONO = '"SF Mono",Consolas,Menlo,monospace';

  function fmt(v, dec) {
    if (v === null || v === undefined || isNaN(v)) { return '—'; }
    return Number(v).toFixed(dec === undefined ? 2 : dec);
  }

  function big(v) {
    if (v === null || v === undefined || isNaN(v)) { return '—'; }
    var a = Math.abs(v);
    if (a >= 1e12) { return (v / 1e12).toFixed(2) + '万亿'; }
    if (a >= 1e8) { return (v / 1e8).toFixed(2) + '亿'; }
    if (a >= 1e4) { return (v / 1e4).toFixed(2) + '万'; }
    return String(Math.round(v));
  }

  function Chart(canvas) {
    this.cv = canvas;
    this.ctx = canvas.getContext('2d');
    this.bars = [];
    this.ind = null;
    this.sub = 'MACD';
    this.dec = 2;
    this.quote = null;
    this.trends = null;
    this.period = 'day';
    this.view = { end: 0, count: 60 };
    this.cross = null;          // {i, x, y}
    this.onCross = null;        // 回调：十字光标移动时回报明细
    this._dpr = 1;
    this._bindTouch();
  }

  Chart.prototype.setData = function (opt) {
    this.period = opt.period || 'day';
    this.sub = opt.sub || this.sub;
    this.dec = opt.dec === undefined ? 2 : opt.dec;
    this.quote = opt.quote || null;
    this.trends = opt.trends || null;
    this.bars = opt.bars || [];
    this.ind = opt.ind || null;
    if (this.period === 'trend') {
      this.view = { end: (this.trends || []).length, count: (this.trends || []).length };
    } else {
      var n = this.bars.length;
      var keep = this.view.count;
      var show = Math.max(20, Math.min(keep || 60, n || 60));
      this.view = { end: n, count: show };
    }
    this.cross = null;
    this.draw();
  };

  Chart.prototype.resize = function () {
    var dpr = window.devicePixelRatio || 1;
    var w = this.cv.clientWidth || 320;
    var h = this.cv.clientHeight || 300;
    this._dpr = dpr;
    if (this.cv.width !== Math.round(w * dpr) ||
        this.cv.height !== Math.round(h * dpr)) {
      this.cv.width = Math.round(w * dpr);
      this.cv.height = Math.round(h * dpr);
    }
    this.W = w;
    this.H = h;
    this.draw();
  };

  /* ---------------- 布局 ---------------- */

  Chart.prototype._layout = function () {
    var H = this.H;
    var padL = 4, padR = 52, padT = 32;
    var hPrice = Math.round((H - padT) * 0.55);
    var gap = 7;
    var hVol = Math.round((H - padT) * 0.15);
    var hSub = H - padT - hPrice - hVol - gap * 2;
    return {
      padL: padL, padR: padR, padT: padT,
      price: { top: padT, bot: padT + hPrice },
      vol: { top: padT + hPrice + gap, bot: padT + hPrice + gap + hVol },
      sub: { top: padT + hPrice + gap + hVol + gap, bot: H },
      plotW: this.W - padL - padR
    };
  };

  /* ---------------- 主绘制 ---------------- */

  Chart.prototype.draw = function () {
    if (!this.W) { this.resize(); return; }
    var ctx = this.ctx;
    ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
    ctx.clearRect(0, 0, this.W, this.H);
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, this.W, this.H);
    if (this.period === 'trend') {
      this._drawTrend();
    } else {
      if (!this.bars.length) { return; }
      this._drawKline();
    }
    if (this.cross) { this._drawCross(); }
  };

  Chart.prototype._visible = function () {
    var n = this.bars.length;
    var count = Math.max(15, Math.min(this.view.count, n));
    var end = Math.max(count, Math.min(this.view.end, n));
    var start = end - count;
    return { start: start, end: end, count: count };
  };

  Chart.prototype._x = function (k, v, L) {
    var bw = L.plotW / v.count;
    return {
      x: L.padL + (k - v.start + 0.5) * bw,
      bw: bw * 0.68,
      step: bw
    };
  };

  Chart.prototype._drawKline = function () {
    var L = this._layout();
    var v = this._visible();
    var ctx = this.ctx;
    var bars = this.bars;

    /* --- 价格区间 --- */
    var hi = -Infinity, lo = Infinity;
    for (var i = v.start; i < v.end; i++) {
      var b = bars[i];
      if (!b) { continue; }
      hi = Math.max(hi, b.h, b.l);
      lo = Math.min(lo, b.l, b.h);
      var ind = this.ind;
      if (ind) {
        var mm = [ind.ma5, ind.ma20, ind.boll_up, ind.boll_dn];
        for (var q = 0; q < mm.length; q++) {
          var ser = mm[q];
          var val = ser ? ser[i] : null;
          if (val !== null && val !== undefined) {
            hi = Math.max(hi, val);
            lo = Math.min(lo, val);
          }
        }
      }
    }
    if (!isFinite(hi) || !isFinite(lo) || hi === lo) { hi = lo + 1; }
    var padY = (hi - lo) * 0.05;
    hi += padY; lo -= padY;
    var toY = function (p) {
      return L.price.bot - (p - lo) / (hi - lo) * (L.price.bot - L.price.top);
    };

    /* 网格 + 右侧价格轴 */
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    ctx.font = '10px ' + MONO;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (var g = 0; g <= 4; g++) {
      var yy = L.price.top + (L.price.bot - L.price.top) * g / 4;
      ctx.beginPath();
      ctx.moveTo(L.padL, yy + 0.5);
      ctx.lineTo(L.padL + L.plotW, yy + 0.5);
      ctx.stroke();
      var pv = hi - (hi - lo) * g / 4;
      ctx.fillStyle = C.mute;
      ctx.fillText(this._axisNum(pv), L.padL + L.plotW + 4, yy);
    }

    /* 蜡烛 + 均线 */
    for (var k = v.start; k < v.end; k++) {
      var bar = bars[k];
      if (!bar) { continue; }
      var pos = this._x(k, v, L);
      var up = bar.c >= bar.o;
      var col = up ? C.up : C.down;
      ctx.strokeStyle = col;
      ctx.fillStyle = col;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(Math.round(pos.x) + 0.5, toY(bar.h));
      ctx.lineTo(Math.round(pos.x) + 0.5, toY(bar.l));
      ctx.stroke();
      var y1 = toY(Math.max(bar.o, bar.c));
      var y2 = toY(Math.min(bar.o, bar.c));
      var bh = Math.max(1, y2 - y1);
      var bwid = Math.max(1.5, pos.bw);
      if (up) {
        /* 空心阳线，和桌面版一致 */
        ctx.fillStyle = C.bg;
        ctx.fillRect(Math.round(pos.x - bwid / 2), Math.round(y1), Math.round(bwid), Math.round(bh));
        ctx.strokeRect(Math.round(pos.x - bwid / 2) + 0.5, Math.round(y1) + 0.5,
                       Math.round(bwid) - 1, Math.round(bh) - 1);
      } else {
        ctx.fillRect(Math.round(pos.x - bwid / 2), Math.round(y1), Math.round(bwid), Math.round(bh));
      }
    }

    /* 均线 + 布林 */
    var self = this;
    if (this.ind) {
      MA.forEach(function (m) {
        var ser = self.ind[m[0]];
        if (!ser) { return; }
        self._line(ser, v, toY, m[2], L, 1.1);
      });
      var bu = this.ind.boll_up, bd = this.ind.boll_dn;
      if (bu && bd) {
        ctx.save();
        ctx.strokeStyle = 'rgba(148,161,181,0.55)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        this._line(bu, v, toY, null, L, 1, true);
        this._line(bd, v, toY, null, L, 1, true);
        ctx.restore();
      }
    }

    /* --- 成交量 --- */
    var vmax = 0;
    for (var vi = v.start; vi < v.end; vi++) {
      if (bars[vi]) { vmax = Math.max(vmax, bars[vi].v || 0); }
    }
    if (vmax <= 0) { vmax = 1; }
    var vToY = function (vol) {
      return L.vol.bot - (vol / vmax) * (L.vol.bot - L.vol.top);
    };
    ctx.strokeStyle = C.grid;
    ctx.beginPath();
    ctx.moveTo(L.padL, L.vol.bot + 0.5);
    ctx.lineTo(L.padL + L.plotW, L.vol.bot + 0.5);
    ctx.stroke();
    for (var vk = v.start; vk < v.end; vk++) {
      var vb = bars[vk];
      if (!vb) { continue; }
      var vp = this._x(vk, v, L);
      var vup = vb.c >= vb.o;
      ctx.fillStyle = vup ? 'rgba(240,69,58,0.75)' : 'rgba(18,184,134,0.75)';
      var vy = vToY(vb.v || 0);
      ctx.fillRect(Math.round(vp.x - vp.bw / 2), Math.round(vy),
                   Math.max(1, Math.round(vp.bw)), Math.round(L.vol.bot - vy));
    }
    ctx.fillStyle = C.mute;
    ctx.font = '10px ' + MONO;
    ctx.textAlign = 'left';
    ctx.fillText(big(vmax), L.padL + L.plotW + 4, L.vol.top + 6);

    /* --- 副图 --- */
    this._drawSub(L, v);

    /* --- 顶部图例 --- */
    this._legend(L, v);

    /* --- 底部时间轴 --- */
    ctx.fillStyle = C.mute;
    ctx.font = '10px ' + MONO;
    ctx.textAlign = 'center';
    var ticks = 4;
    for (var t = 0; t <= ticks; t++) {
      var idx = Math.round(v.start + (v.count - 1) * t / ticks);
      var tb = bars[idx];
      if (!tb) { continue; }
      var tx = L.padL + L.plotW * t / ticks;
      ctx.textAlign = t === 0 ? 'left' : (t === ticks ? 'right' : 'center');
      ctx.fillText(String(tb.d).slice(2), Math.min(Math.max(tx, L.padL), L.padL + L.plotW),
                   this.H - 3);
    }
  };

  Chart.prototype._axisNum = function (v) {
    return this.dec >= 3 ? Number(v).toFixed(2) : Number(v).toFixed(2);
  };

  Chart.prototype._line = function (ser, v, toY, color, L, lw, keepDash) {
    var ctx = this.ctx;
    ctx.save();
    if (color) { ctx.strokeStyle = color; } else { ctx.strokeStyle = ctx.strokeStyle; }
    ctx.lineWidth = lw || 1;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    var started = false;
    for (var i = v.start; i < v.end; i++) {
      var val = ser[i];
      if (val === null || val === undefined || isNaN(val)) { started = false; continue; }
      var p = this._x(i, v, L);
      var y = toY(val);
      if (!started) { ctx.moveTo(p.x, y); started = true; }
      else { ctx.lineTo(p.x, y); }
    }
    ctx.stroke();
    ctx.restore();
  };

  Chart.prototype._drawSub = function (L, v) {
    var ctx = this.ctx;
    var ind = this.ind;
    if (!ind) { return; }
    var top = L.sub.top, bot = L.sub.bot;
    var vals = [];
    var i;
    if (this.sub === 'MACD') {
      for (i = v.start; i < v.end; i++) {
        if (ind.dif[i] !== null) { vals.push(ind.dif[i]); }
        if (ind.dea[i] !== null) { vals.push(ind.dea[i]); }
        if (ind.hist[i] !== null) { vals.push(ind.hist[i]); }
      }
    } else if (this.sub === 'KDJ') {
      for (i = v.start; i < v.end; i++) {
        ['k', 'd', 'j'].forEach(function (kk) {
          if (ind[kk][i] !== null) { vals.push(ind[kk][i]); }
        });
      }
    } else {
      for (i = v.start; i < v.end; i++) {
        ['rsi6', 'rsi12', 'rsi24'].forEach(function (kk) {
          if (ind[kk][i] !== null) { vals.push(ind[kk][i]); }
        });
      }
    }
    if (!vals.length) { return; }
    var hi = Math.max.apply(null, vals);
    var lo = Math.min.apply(null, vals);
    if (this.sub === 'RSI') { hi = Math.max(hi, 80); lo = Math.min(lo, 20); }
    if (hi === lo) { hi = lo + 1; }
    var pad = (hi - lo) * 0.08;
    hi += pad; lo -= pad;
    var toY = function (p2) {
      return bot - (p2 - lo) / (hi - lo) * (bot - top);
    };
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(L.padL, top + 0.5);
    ctx.lineTo(L.padL + L.plotW, top + 0.5);
    ctx.stroke();

    if (this.sub === 'MACD') {
      var zero = toY(0);
      ctx.strokeStyle = 'rgba(148,161,181,0.35)';
      ctx.beginPath();
      ctx.moveTo(L.padL, zero + 0.5);
      ctx.lineTo(L.padL + L.plotW, zero + 0.5);
      ctx.stroke();
      for (i = v.start; i < v.end; i++) {
        var h = ind.hist[i];
        if (h === null || h === undefined) { continue; }
        var p = this._x(i, v, L);
        ctx.fillStyle = h >= 0 ? 'rgba(240,69,58,0.85)' : 'rgba(18,184,134,0.85)';
        var y0 = toY(h), yz = toY(0);
        ctx.fillRect(Math.round(p.x - p.bw / 2), Math.round(Math.min(y0, yz)),
                     Math.max(1, Math.round(p.bw)), Math.max(1, Math.abs(yz - y0)));
      }
      this._line(ind.dif, v, toY, '#f5a623', L, 1.1);
      this._line(ind.dea, v, toY, '#4c8dff', L, 1.1);
    } else if (this.sub === 'KDJ') {
      this._line(ind.k, v, toY, '#f5a623', L, 1.1);
      this._line(ind.d, v, toY, '#4c8dff', L, 1.1);
      this._line(ind.j, v, toY, '#b06bd9', L, 1.1);
    } else {
      this._line(ind.rsi6, v, toY, '#f5a623', L, 1.1);
      this._line(ind.rsi12, v, toY, '#4c8dff', L, 1.1);
      this._line(ind.rsi24, v, toY, '#b06bd9', L, 1.1);
    }

    ctx.font = '10px ' + MONO;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = C.mute;
    ctx.fillText(this._subAxis(hi), L.padL + L.plotW + 4, top + 6);
    ctx.fillText(this._subAxis(lo), L.padL + L.plotW + 4, bot - 6);
  };

  Chart.prototype._subAxis = function (v) {
    if (this.sub === 'RSI') { return Number(v).toFixed(0); }
    if (this.sub === 'MACD') {
      var a = Math.abs(v);
      if (a >= 1) { return Number(v).toFixed(2); }
      return Number(v).toFixed(3);
    }
    return Number(v).toFixed(1);
  };

  /* 顶部两行图例：第一行 K 线信息，第二行均线数值，互不重叠 */
  Chart.prototype._legend = function (L, v) {
    var ctx = this.ctx;
    var i = this.cross ? this.cross.i : v.end - 1;
    var bar = this.bars[i];
    if (!bar) { return; }
    ctx.font = '10px ' + FONT;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillStyle = bar.c >= bar.o ? C.up : C.down;
    ctx.fillText(bar.d + '  开' + fmt(bar.o, this.dec) + '  高' + fmt(bar.h, this.dec) +
                 '  低' + fmt(bar.l, this.dec) + '  收' + fmt(bar.c, this.dec),
                 L.padL + 2, 4);

    if (!this.ind) { return; }
    var self = this;
    var lx = L.padL + 2;
    var right = L.padL + L.plotW;
    MA.forEach(function (m) {
      var ser = self.ind[m[0]];
      var val = ser ? ser[i] : null;
      var t = m[1] + ' ' + (val === null || val === undefined ? '—' : fmt(val, 2));
      var w = ctx.measureText(t).width;
      if (lx + w > right) { return; }
      ctx.fillStyle = m[2];
      ctx.fillText(t, lx, 18);
      lx += w + 9;
    });
  };

  /* ---------------- 分时 ---------------- */

  Chart.prototype._drawTrend = function () {
    var L = this._layout();
    var ctx = this.ctx;
    var pts = this.trends || [];
    if (!pts.length) { return; }
    var pre = (this.quote && this.quote.preclose) || pts[0].c;
    var hi = pre, lo = pre;
    pts.forEach(function (p) {
      hi = Math.max(hi, p.c);
      lo = Math.min(lo, p.c);
    });
    var span = Math.max(hi - pre, pre - lo) * 1.08;
    if (!span) { span = pre * 0.01 || 1; }
    hi = pre + span; lo = pre - span;
    var toY = function (p) {
      return L.price.bot - (p - lo) / (hi - lo) * (L.price.bot - L.price.top);
    };
    var n = pts.length;
    var toX = function (k) { return L.padL + L.plotW * (k + 0.5) / n; };

    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    ctx.font = '10px ' + MONO;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (var g = 0; g <= 4; g++) {
      var yy = L.price.top + (L.price.bot - L.price.top) * g / 4;
      ctx.beginPath();
      ctx.moveTo(L.padL, yy + 0.5);
      ctx.lineTo(L.padL + L.plotW, yy + 0.5);
      ctx.stroke();
      var pv = hi - (hi - lo) * g / 4;
      var pct = (pv - pre) / pre * 100;
      ctx.fillStyle = C.mute;
      ctx.fillText(fmt(pv, this.dec), L.padL + L.plotW + 4, yy);
      ctx.textAlign = 'left';
      ctx.fillStyle = pct > 0 ? C.up : (pct < 0 ? C.down : C.mute);
      ctx.fillText((pct >= 0 ? '+' : '') + pct.toFixed(2) + '%',
                   L.padL + L.plotW + 4, yy + 11);
    }
    // 昨收线
    ctx.strokeStyle = 'rgba(148,161,181,0.5)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(L.padL, toY(pre));
    ctx.lineTo(L.padL + L.plotW, toY(pre));
    ctx.stroke();
    ctx.setLineDash([]);

    // 价格线 + 填充
    var lastX = toX(0), lastY = toY(pts[0].c);
    ctx.beginPath();
    ctx.moveTo(lastX, lastY);
    for (var i = 1; i < n; i++) {
      var x = toX(i), y = toY(pts[i].c);
      ctx.lineTo(x, y);
      lastX = x; lastY = y;
    }
    ctx.strokeStyle = C.accent;
    ctx.lineWidth = 1.4;
    ctx.stroke();
    ctx.lineTo(lastX, L.price.bot);
    ctx.lineTo(toX(0), L.price.bot);
    ctx.closePath();
    var grd = ctx.createLinearGradient(0, L.price.top, 0, L.price.bot);
    grd.addColorStop(0, 'rgba(76,141,255,0.28)');
    grd.addColorStop(1, 'rgba(76,141,255,0.02)');
    ctx.fillStyle = grd;
    ctx.fill();

    // 均价线
    ctx.beginPath();
    var started = false;
    for (var j = 0; j < n; j++) {
      var avg = pts[j].avg;
      if (avg === null || avg === undefined) { continue; }
      var ax = toX(j), ay = toY(avg);
      if (!started) { ctx.moveTo(ax, ay); started = true; } else { ctx.lineTo(ax, ay); }
    }
    ctx.strokeStyle = C.warn;
    ctx.lineWidth = 1.1;
    ctx.stroke();

    // 成交量
    var vmax = 0;
    pts.forEach(function (p) { vmax = Math.max(vmax, p.v || 0); });
    if (vmax <= 0) { vmax = 1; }
    var bw = Math.max(1, L.plotW / n * 0.7);
    for (var k = 0; k < n; k++) {
      var vv = pts[k].v || 0;
      var vh = (vv / vmax) * (L.vol.bot - L.vol.top);
      ctx.fillStyle = pts[k].c >= pre ? 'rgba(240,69,58,0.75)' : 'rgba(18,184,134,0.75)';
      ctx.fillRect(toX(k) - bw / 2, L.vol.bot - vh, bw, vh);
    }

    ctx.fillStyle = C.mute;
    ctx.font = '10px ' + MONO;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(big(vmax), L.padL + L.plotW + 4, L.vol.top + 6);

    // 顶部图例
    var last = pts[n - 1];
    var avgLast = null;
    for (var a = n - 1; a >= 0; a--) {
      if (pts[a].avg !== null && pts[a].avg !== undefined) { avgLast = pts[a].avg; break; }
    }
    ctx.font = '10px ' + FONT;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillStyle = last.c >= pre ? C.up : C.down;
    ctx.fillText('现价 ' + fmt(last.c, this.dec) +
                 '  均价 ' + (avgLast === null ? '—' : fmt(avgLast, this.dec)) +
                 '  昨收 ' + fmt(pre, this.dec) +
                 '  ' + (last.c >= pre ? '+' : '') +
                 ((last.c - pre) / pre * 100).toFixed(2) + '%',
                 L.padL + 2, 5);

    // 时间刻度
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor(n * 3 / 4), n - 1]
      .forEach(function (idx) {
        if (!pts[idx]) { return; }
        var tx = toX(idx);
        ctx.textAlign = idx === 0 ? 'left' : (idx === n - 1 ? 'right' : 'center');
        ctx.fillText(pts[idx].t, Math.min(Math.max(tx, L.padL), L.padL + L.plotW),
                     this.H - 3);
      }, this);
  };

  /* ---------------- 十字光标 ---------------- */

  Chart.prototype._drawCross = function () {
    var L = this._layout();
    var ctx = this.ctx;
    var c = this.cross;
    ctx.save();
    ctx.strokeStyle = 'rgba(226,232,242,0.45)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(c.x + 0.5, L.padT);
    ctx.lineTo(c.x + 0.5, this.H - 14);
    ctx.moveTo(L.padL, c.y + 0.5);
    ctx.lineTo(L.padL + L.plotW, c.y + 0.5);
    ctx.stroke();
    ctx.restore();
  };

  Chart.prototype.pickIndex = function (clientX) {
    var rect = this.cv.getBoundingClientRect();
    var x = clientX - rect.left;
    var L = this._layout();
    if (this.period === 'trend') {
      var n = (this.trends || []).length;
      if (!n) { return -1; }
      var k = Math.round((x - L.padL) / (L.plotW / n) - 0.5);
      return Math.max(0, Math.min(n - 1, k));
    }
    var v = this._visible();
    var step = L.plotW / v.count;
    var idx = Math.floor((x - L.padL) / step) + v.start;
    return Math.max(v.start, Math.min(v.end - 1, idx));
  };

  Chart.prototype.zoom = function (factor) {
    if (this.period === 'trend') { return; }
    var n = this.bars.length;
    var next = Math.round(this.view.count * factor);
    next = Math.max(20, Math.min(n, next));
    var anchor = this.view.end;
    this.view.count = next;
    this.view.end = Math.max(next, Math.min(anchor, n));
    this.draw();
  };

  Chart.prototype.pan = function (dpx) {
    if (this.period === 'trend') { return; }
    var L = this._layout();
    var v = this._visible();
    var step = L.plotW / v.count;
    var dn = Math.round(dpx / step);
    if (!dn) { return; }
    var n = this.bars.length;
    var end = Math.max(v.count, Math.min(this.view.end + dn, n));
    this.view.end = end;
    this.cross = null;
    this.draw();
  };

  /* ---------------- 触屏 ---------------- */

  Chart.prototype._bindTouch = function () {
    var self = this;
    var mode = null;      // 'pan' | 'zoom' | 'cross'
    var lastX = 0, lastDist = 0, moved = 0, startT = 0;

    function dist(t) {
      var dx = t[0].clientX - t[1].clientX;
      var dy = t[0].clientY - t[1].clientY;
      return Math.sqrt(dx * dx + dy * dy);
    }

    this.cv.addEventListener('touchstart', function (e) {
      startT = Date.now();
      moved = 0;
      if (e.touches.length === 2) {
        mode = 'zoom';
        lastDist = dist(e.touches);
      } else {
        mode = 'cross';
        lastX = e.touches[0].clientX;
        self._setCross(lastX, e.touches[0].clientY);
      }
      e.preventDefault();
    }, { passive: false });

    this.cv.addEventListener('touchmove', function (e) {
      if (mode === 'zoom' && e.touches.length === 2) {
        var d = dist(e.touches);
        if (lastDist > 0) {
          var f = lastDist / d;
          if (Math.abs(1 - f) > 0.02) { self.zoom(f); lastDist = d; }
        }
        e.preventDefault();
        return;
      }
      if (e.touches.length === 1) {
        var x = e.touches[0].clientX;
        var dx = x - lastX;
        moved += Math.abs(dx);
        if (moved > 14 && mode === 'cross' && Math.abs(dx) > 0) {
          mode = 'pan';
        }
        if (mode === 'pan') {
          self.pan(-dx);
          lastX = x;
        } else {
          lastX = x;
          self._setCross(x, e.touches[0].clientY);
        }
        e.preventDefault();
      }
    }, { passive: false });

    this.cv.addEventListener('touchend', function (e) {
      if (Date.now() - startT < 250 && moved < 14 && mode === 'cross') {
        // 轻点：切换十字光标
        if (self.cross) { self.cross = null; } else { self._setCross(lastX, 0); }
        self.draw();
      }
      mode = null;
      e.preventDefault();
    }, { passive: false });

    /* 桌面调试用 */
    this.cv.addEventListener('mousemove', function (e) {
      if (e.buttons) { return; }
      self._setCross(e.clientX, e.clientY);
    });
    this.cv.addEventListener('mouseleave', function () {
      if (self.cross) { self.cross = null; self.draw(); }
    });
    this.cv.addEventListener('wheel', function (e) {
      self.zoom(e.deltaY > 0 ? 1.15 : 0.87);
      e.preventDefault();
    }, { passive: false });
  };

  Chart.prototype._setCross = function (cx, cy) {
    var i = this.pickIndex(cx);
    if (i < 0) { return; }
    var rect = this.cv.getBoundingClientRect();
    this.cross = { i: i, x: cx - rect.left, y: cy - rect.top };
    this.draw();
    if (this.onCross) {
      var src = this.period === 'trend' ? (this.trends || [])[i] : this.bars[i];
      this.onCross(i, src);
    }
  };

  Chart.prototype.legendText = function () {
    var i = this.cross ? this.cross.i : (this.bars.length - 1);
    var b = this.bars[i];
    if (!b) { return ''; }
    return b.d + '  开' + fmt(b.o, this.dec) + '  高' + fmt(b.h, this.dec) +
           '  低' + fmt(b.l, this.dec) + '  收' + fmt(b.c, this.dec) +
           '  量' + big(b.v);
  };

  root.Chart = Chart;
  root.CHART_COLORS = C;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { Chart: Chart, colors: C, fmt: fmt, big: big };
  }
})(typeof window !== 'undefined' ? window : globalThis);
