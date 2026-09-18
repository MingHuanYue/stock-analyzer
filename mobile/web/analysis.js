// -*- coding: utf-8 -*-
// 指标计算与规则化分析引擎（纯标准库）的 JavaScript 移植版。
//
// 指标算法与国内主流行情软件（通达信口径）保持一致：
//   MACD(12,26,9)  EMA 以首值为种子；柱 = 2 x (DIF - DEA)
//   KDJ(9,3,3)     K/D 以 50 为种子，J = 3K - 2D
//   RSI(N)         SMA(X, N, 1) 威尔德平滑
//   BOLL(20, 2)    中轨 MA20 ± 2 倍标准差
//   DMI/ADX(14)    威尔德平滑，衡量趋势强度（不辨方向）
//   CCI(14) / WR(14) / BIAS(20) / OBV  常用辅助指标
//
// 分析输出面向「看得懂」：每个信号都带一句白话解释，并给出维度评分、
// 多空信号对照、关键价位阶梯与条件化情景应对。

// --------------------------------------------------------------------------
// 数值格式化（与 Python 的 %.Nf 一致，四舍五入采用 round-half-even）
// --------------------------------------------------------------------------

// 银行家舍入：_roundHalfEven(x, digits)，按 Python 的 round-half-even 规则。
function _roundHalfEven(x, digits) {
  const p = Math.pow(10, digits);
  const y = x * p;
  const sign = y < 0 ? -1 : 1;
  const ay = Math.abs(y);
  const ip = Math.floor(ay);
  const frac = ay - ip;
  let res;
  if (frac > 0.5) {
    res = ip + 1;
  } else if (frac < 0.5) {
    res = ip;
  } else {
    // 恰为 .5：取最接近的偶数
    res = (ip % 2 === 0) ? ip : ip + 1;
  }
  return sign * res / p;
}

// 把数字格式化为固定小数位的字符串（与 Python %f 一致）。
function _fmt(v, digits) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  const r = _roundHalfEven(v, digits === undefined ? 2 : digits);
  const rr = (r === 0) ? 0 : r; // 归并 -0
  return rr.toFixed(digits === undefined ? 2 : digits);
}

// --------------------------------------------------------------------------
// 基础工具
// --------------------------------------------------------------------------

function _sma(values, n) {
  const out = new Array(values.length).fill(null);
  let s = 0.0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    s += v;
    if (i >= n) s -= values[i - n];
    if (i >= n - 1) out[i] = s / n;
  }
  return out;
}

function _ema(values, n) {
  const out = new Array(values.length).fill(null);
  if (!values.length) return out;
  const k = 2.0 / (n + 1.0);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    prev = prev === null ? v : v * k + prev * (1.0 - k);
    out[i] = prev;
  }
  return out;
}

function _wilder(values, n) {
  // 通达信 SMA(X, N, 1)：Y = (X + (N-1) * Y') / N，首值作种子。
  const out = new Array(values.length).fill(null);
  let prev = null;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    prev = prev === null ? v : (v + (n - 1) * prev) / n;
    out[i] = prev;
  }
  return out;
}

function _stddev(values, n) {
  const out = new Array(values.length).fill(null);
  for (let i = 0; i < values.length; i++) {
    if (i < n - 1) continue;
    const win = values.slice(i - n + 1, i + 1);
    const m = win.reduce((a, b) => a + b, 0) / n;
    let ss = 0;
    for (let x = 0; x < win.length; x++) ss += (win[x] - m) * (win[x] - m);
    out[i] = Math.sqrt(ss / n);
  }
  return out;
}

function _rollingMax(values, n) {
  const out = new Array(values.length).fill(null);
  for (let i = 0; i < values.length; i++) {
    if (i >= n - 1) {
      let mx = values[i - n + 1];
      for (let t = i - n + 2; t <= i; t++) if (values[t] > mx) mx = values[t];
      out[i] = mx;
    }
  }
  return out;
}

function _rollingMin(values, n) {
  const out = new Array(values.length).fill(null);
  for (let i = 0; i < values.length; i++) {
    if (i >= n - 1) {
      let mn = values[i - n + 1];
      for (let t = i - n + 2; t <= i; t++) if (values[t] < mn) mn = values[t];
      out[i] = mn;
    }
  }
  return out;
}

function _crossState(fast, slow, lookback) {
  // 最近一次交叉：返回 ('gold'|'dead', 距今 K 线根数) 或 (null, null)。
  lookback = lookback === undefined ? 90 : lookback;
  const n = fast.length;
  const lo = Math.max(0, n - lookback);
  for (let i = n - 1; i >= lo; i--) {
    const a0 = fast[i - 1], b0 = slow[i - 1], a1 = fast[i], b1 = slow[i];
    if (a0 === null || b0 === null || a1 === null || b1 === null) continue;
    if (a1 > b1 && a0 <= b0) return ['gold', n - 1 - i];
    if (a1 < b1 && a0 >= b0) return ['dead', n - 1 - i];
  }
  return [null, null];
}

function _last(series) {
  for (let j = series.length - 1; j >= 0; j--) {
    if (series[j] !== null && series[j] !== undefined) return series[j];
  }
  return null;
}

function _valueAt(series, idx) {
  if (idx >= 0 && idx < series.length) return series[idx];
  return null;
}

// --------------------------------------------------------------------------
// 指标组
// --------------------------------------------------------------------------

function _macd(close, fast, slow, signal) {
  fast = fast === undefined ? 12 : fast;
  slow = slow === undefined ? 26 : slow;
  signal = signal === undefined ? 9 : signal;
  const ef = _ema(close, fast), es = _ema(close, slow);
  const dif = ef.map((a, k) => (a === null || es[k] === null) ? null : a - es[k]);
  const dea = _ema(dif.map(d => d === null ? 0.0 : d), signal);
  const hist = dif.map((a, k) => (a === null || dea[k] === null) ? null : 2.0 * (a - dea[k]));
  return [dif, dea, hist];
}

function _kdj(high, low, close, n, m1, m2) {
  n = n === undefined ? 9 : n;
  m1 = m1 === undefined ? 3 : m1;
  m2 = m2 === undefined ? 3 : m2;
  const ln = close.length;
  const hh = _rollingMax(high, n), ll = _rollingMin(low, n);
  const rsv = new Array(ln).fill(null);
  for (let i = 0; i < ln; i++) {
    if (hh[i] === null || ll[i] === null) continue;
    const rng = hh[i] - ll[i];
    rsv[i] = rng === 0 ? 50.0 : (close[i] - ll[i]) / rng * 100.0;
  }
  const k = new Array(ln).fill(null);
  const d = new Array(ln).fill(null);
  let pk = 50.0, pd = 50.0;
  for (let i = 0; i < ln; i++) {
    if (rsv[i] === null) continue;
    pk = (rsv[i] + (m1 - 1) * pk) / m1;
    pd = (pk + (m2 - 1) * pd) / m2;
    k[i] = pk; d[i] = pd;
  }
  const j = new Array(ln).fill(null);
  for (let i = 0; i < ln; i++) {
    j[i] = (k[i] === null || d[i] === null) ? null : 3 * k[i] - 2 * d[i];
  }
  return [k, d, j];
}

function _rsi(close, n) {
  n = n === undefined ? 6 : n;
  const ln = close.length;
  const up = new Array(ln).fill(0.0);
  const dn = new Array(ln).fill(0.0);
  for (let i = 1; i < ln; i++) {
    const diff = close[i] - close[i - 1];
    up[i] = Math.max(diff, 0.0);
    dn[i] = Math.abs(diff);
  }
  const su = _wilder(up, n), sd = _wilder(dn, n);
  const out = new Array(ln).fill(null);
  for (let i = 0; i < ln; i++) {
    if (su[i] === null || sd[i] === null) continue;
    out[i] = sd[i] === 0 ? 50.0 : su[i] / sd[i] * 100.0;
  }
  return out;
}

function _boll(close, n, k) {
  n = n === undefined ? 20 : n;
  k = k === undefined ? 2.0 : k;
  const mid = _sma(close, n);
  const sd = _stddev(close, n);
  const up = [], dn = [];
  for (let i = 0; i < close.length; i++) {
    up.push((mid[i] === null || sd[i] === null) ? null : mid[i] + k * sd[i]);
    dn.push((mid[i] === null || sd[i] === null) ? null : mid[i] - k * sd[i]);
  }
  return [up, mid, dn];
}

function _atr(high, low, close, n) {
  n = n === undefined ? 14 : n;
  const ln = close.length;
  const tr = new Array(ln).fill(0.0);
  for (let i = 0; i < ln; i++) {
    if (i === 0) tr[i] = high[i] - low[i];
    else tr[i] = Math.max(high[i] - low[i], Math.abs(high[i] - close[i - 1]),
                           Math.abs(low[i] - close[i - 1]));
  }
  return _wilder(tr, n);
}

function _dmi(high, low, close, n) {
  // 返回 (+DI, -DI, ADX)。ADX 越大趋势越强（不分方向）。
  n = n === undefined ? 14 : n;
  const ln = close.length;
  const tr = new Array(ln).fill(0.0);
  const pdm = new Array(ln).fill(0.0);
  const ndm = new Array(ln).fill(0.0);
  for (let i = 0; i < ln; i++) {
    if (i === 0) {
      tr[i] = high[i] - low[i];
      continue;
    }
    tr[i] = Math.max(high[i] - low[i], Math.abs(high[i] - close[i - 1]),
                     Math.abs(low[i] - close[i - 1]));
    const up = high[i] - high[i - 1];
    const dn = low[i - 1] - low[i];
    if (up > dn && up > 0) pdm[i] = up;
    else if (dn > up && dn > 0) ndm[i] = dn;
  }
  const atr_ = _wilder(tr, n);
  const wpdm = _wilder(pdm, n);
  const wndm = _wilder(ndm, n);
  const pdi = new Array(ln).fill(null);
  const ndi = new Array(ln).fill(null);
  const dx = new Array(ln).fill(null);
  for (let i = 0; i < ln; i++) {
    if (!atr_[i]) continue;
    pdi[i] = 100.0 * wpdm[i] / atr_[i];
    ndi[i] = 100.0 * wndm[i] / atr_[i];
    const s = pdi[i] + ndi[i];
    dx[i] = s === 0 ? 0.0 : 100.0 * Math.abs(pdi[i] - ndi[i]) / s;
  }
  const adx = _wilder(dx.map(v => v === null ? 0.0 : v), n);
  return [pdi, ndi, adx];
}

function _cci(high, low, close, n) {
  n = n === undefined ? 14 : n;
  const ln = close.length;
  const tp = [];
  for (let i = 0; i < ln; i++) tp.push((high[i] + low[i] + close[i]) / 3.0);
  const ma = _sma(tp, n);
  const out = new Array(ln).fill(null);
  for (let i = 0; i < ln; i++) {
    if (ma[i] === null) continue;
    const win = tp.slice(i - n + 1, i + 1);
    let md = 0;
    for (let x = 0; x < win.length; x++) md += Math.abs(win[x] - ma[i]);
    md = md / n;
    out[i] = md === 0 ? 0.0 : (tp[i] - ma[i]) / (0.015 * md);
  }
  return out;
}

function _wr(high, low, close, n) {
  // 威廉指标：0-20 超买，80-100 超卖（数值越小越强）。
  n = n === undefined ? 14 : n;
  const hh = _rollingMax(high, n), ll = _rollingMin(low, n);
  const out = new Array(close.length).fill(null);
  for (let i = 0; i < close.length; i++) {
    if (hh[i] === null || ll[i] === null) continue;
    const rng = hh[i] - ll[i];
    out[i] = rng === 0 ? 50.0 : (hh[i] - close[i]) / rng * 100.0;
  }
  return out;
}

function _obv(close, volume) {
  // 能量潮：涨日累加成交量，跌日累减，反映资金进出方向。
  const out = new Array(close.length).fill(0.0);
  for (let i = 1; i < close.length; i++) {
    if (close[i] > close[i - 1]) out[i] = out[i - 1] + volume[i];
    else if (close[i] < close[i - 1]) out[i] = out[i - 1] - volume[i];
    else out[i] = out[i - 1];
  }
  return out;
}

function _bias(close, n) {
  n = n === undefined ? 20 : n;
  const ma = _sma(close, n);
  const out = [];
  for (let i = 0; i < close.length; i++) {
    out.push((ma[i] === null || ma[i] === 0) ? null : (close[i] - ma[i]) / ma[i] * 100.0);
  }
  return out;
}

function _vwapCost(bars, n) {
  // 近 n 日成交量加权均价，近似市场平均持仓成本。
  const win = bars.length > n ? bars.slice(bars.length - n) : bars;
  let tot = 0;
  for (let t = 0; t < win.length; t++) tot += win[t]['v'];
  if (!tot) return null;
  let s = 0;
  for (let t = 0; t < win.length; t++) {
    const b = win[t];
    s += ((b['h'] + b['l'] + b['c']) / 3.0) * b['v'];
  }
  return s / tot;
}

function _computeIndicators(bars) {
  // 对完整序列计算指标，返回与 bars 等长的各序列。
  const close = bars.map(b => b['c']);
  const high = bars.map(b => b['h']);
  const low = bars.map(b => b['l']);
  const vol = bars.map(b => b['v']);

  const [dif, dea, hist] = _macd(close);
  const [k, d, j] = _kdj(high, low, close);
  const [up, mid, dn] = _boll(close);
  const [pdi, ndi, adx] = _dmi(high, low, close);
  const ob = _obv(close, vol);

  return {
    'close': close, 'high': high, 'low': low, 'vol': vol,
    'ma5': _sma(close, 5), 'ma10': _sma(close, 10), 'ma20': _sma(close, 20),
    'ma60': _sma(close, 60), 'ma120': _sma(close, 120), 'ma250': _sma(close, 250),
    'vma5': _sma(vol, 5), 'vma10': _sma(vol, 10), 'vma20': _sma(vol, 20),
    'dif': dif, 'dea': dea, 'hist': hist,
    'k': k, 'd': d, 'j': j,
    'rsi6': _rsi(close, 6), 'rsi12': _rsi(close, 12), 'rsi24': _rsi(close, 24),
    'boll_up': up, 'boll_mid': mid, 'boll_dn': dn,
    'atr14': _atr(high, low, close, 14),
    'pdi': pdi, 'ndi': ndi, 'adx': adx,
    'cci': _cci(high, low, close), 'wr': _wr(high, low, close),
    'bias20': _bias(close, 20),
    'obv': ob, 'obv_ma': _sma(ob, 30),
    'hi20': _rollingMax(high, 20), 'lo20': _rollingMin(low, 20),
    'hi60': _rollingMax(high, 60), 'lo60': _rollingMin(low, 60),
    'hi250': _rollingMax(high, 250), 'lo250': _rollingMin(low, 250),
  };
}

// --------------------------------------------------------------------------
// 格式化工具（界面与报告共用）
// --------------------------------------------------------------------------

const TONE_UP = 'up';
const TONE_DOWN = 'down';
const TONE_WARN = 'warn';
const TONE_FLAT = 'flat';

function _num(v, unit, digits) {
  if (digits === undefined) digits = 2;
  if (v === null || v === undefined) return '—';
  if (unit === '%') return _fmt(v, digits) + '%';
  return _fmt(v, digits);
}

function _big(v) {
  // 金额自适应单位（元）。
  if (v === null || v === undefined) return '—';
  const a = Math.abs(v);
  if (a >= 1e12) return _fmt(v / 1e12, 2) + ' 万亿';
  if (a >= 1e8) return _fmt(v / 1e8, 2) + ' 亿';
  if (a >= 1e4) return _fmt(v / 1e4, 2) + ' 万';
  return _fmt(v, 0);
}

function _vol_hand(v) {
  if (v === null || v === undefined) return '—';
  const a = Math.abs(v);
  if (a >= 1e8) return _fmt(v / 1e8, 2) + ' 亿手';
  if (a >= 1e4) return _fmt(v / 1e4, 2) + ' 万手';
  return _fmt(v, 0) + ' 手';
}

function _pct(a, b) {
  if (a === null || a === undefined || a === 0 || b === null || b === undefined) return null;
  return (b - a) / Math.abs(a) * 100.0;
}

function _clamp(v, lo, hi) {
  if (lo === undefined) lo = 0.0;
  if (hi === undefined) hi = 100.0;
  return Math.max(lo, Math.min(hi, v));
}

// --------------------------------------------------------------------------
// 形态与结构识别
// --------------------------------------------------------------------------

function _candlePattern(bars, i) {
  // 识别单根 K 线形态与组合形态，返回 (名称, 含义, tone) 列表。
  const res = [];
  const b = bars[i];
  const body = Math.abs(b['c'] - b['o']);
  const rng = b['h'] - b['l'];
  if (rng <= 0) return res;
  const upper = b['h'] - Math.max(b['o'], b['c']);
  const lower = Math.min(b['o'], b['c']) - b['l'];
  const up = b['c'] >= b['o'];

  if (body / rng < 0.12) {
    res.push(['十字星', '开收盘几乎相同，多空暂时势均力敌，常出现在变盘前。', TONE_FLAT]);
  } else if (lower > body * 2 && upper < body * 0.6) {
    res.push([up ? '锤子线' : '下影线较长',
              '下方有承接资金把价格买回，短期下跌动能减弱。', TONE_UP]);
  } else if (upper > body * 2 && lower < body * 0.6) {
    res.push(['长上影线', '上方抛压明显，冲高被压回，短期上行受阻。', TONE_DOWN]);
  }

  if (i >= 1) {
    const p = bars[i - 1];
    if (up && p['c'] < p['o'] && b['c'] > p['o'] && b['o'] < p['c']) {
      res.push(['看涨吞没', '今日阳线完全包住昨日阴线，是较强的反转向上信号。', TONE_UP]);
    }
    if ((!up) && p['c'] > p['o'] && b['c'] < p['o'] && b['o'] > p['c']) {
      res.push(['看跌吞没', '今日阴线完全包住昨日阳线，是较强的反转向下信号。', TONE_DOWN]);
    }
    if (b['l'] > p['h']) {
      res.push(['向上跳空缺口', '开盘直接跳过昨日最高价，说明买盘急切，缺口下沿常成为支撑。', TONE_UP]);
    } else if (b['h'] < p['l']) {
      res.push(['向下跳空缺口', '开盘直接低于昨日最低价，说明抛压急切，缺口上沿常成为压力。', TONE_DOWN]);
    }
  }

  // 连续同向
  let run = 1;
  for (let t = i; t > 0; t--) {
    if ((bars[t]['c'] >= bars[t]['o']) === up) run++;
    else break;
  }
  if (run >= 4) {
    res.push([(run - 1) + ' 连' + (up ? '阳' : '阴'),
              '连续同向运行，短线' + (up ? '上涨' : '下跌') + '能量已有一定释放，注意节奏。',
              TONE_WARN]);
  }
  return res;
}

function _measureGaps(bars, i) {
  // 统计近 60 根 K 线内的未回补缺口，作为潜在支撑/压力。
  const out = [];
  const start = Math.max(1, i - 59);
  for (let t = i; t >= start; t--) {
    const b = bars[t], p = bars[t - 1];
    if (b['l'] > p['h']) {
      const low = p['h'], high = b['l'];
      let filled = false;
      for (let u = t + 1; u < bars.length; u++) {
        if (bars[u]['l'] <= low) { filled = true; break; }
      }
      if (!filled) out.push(['向上缺口', low, high]);
    } else if (b['h'] < p['l']) {
      const low = b['h'], high = p['l'];
      let filled = false;
      for (let u = t + 1; u < bars.length; u++) {
        if (bars[u]['h'] >= high) { filled = true; break; }
      }
      if (!filled) out.push(['向下缺口', low, high]);
    }
  }
  return out;
}

// --------------------------------------------------------------------------
// 分析主体
// --------------------------------------------------------------------------

function _dim(name, note, deltas, weight) {
  // 维度评分：中性 50 分，按信号累加后截断。
  let total = 0;
  for (let x = 0; x < deltas.length; x++) total += deltas[x][1];
  let score = _clamp(50.0 + total * 1.4, 3.0, 97.0);
  let tone;
  if (score >= 56) tone = TONE_UP;
  else if (score >= 44) tone = TONE_FLAT;
  else tone = TONE_DOWN;
  return { 'name': name, 'score': score, 'tone': tone, 'note': note,
           'weight': weight, 'items': deltas };
}

// 不同 K 线周期的口径换算（年化系数、量词、区间描述）
const PERIOD_CONF = {
  'day': { 'ann': 244, 'range': '近一年（250 个交易日）', 'bar': '单日',
           'hi250': '近 250 根高点（年内高点）', 'lo250': '近 250 根低点（年内低点）' },
  'week': { 'ann': 52, 'range': '近 250 周（约 5 年）', 'bar': '单周',
            'hi250': '近 250 根高点（约 5 年高点）', 'lo250': '近 250 根低点（约 5 年低点）' },
  'month': { 'ann': 12, 'range': '近 250 月（约 20 年）', 'bar': '单月',
             'hi250': '近 250 根高点（约 20 年高点）', 'lo250': '近 250 根低点（约 20 年低点）' },
};

function _buildAnalysis(quote, bars, ind, flow, fin, bench, benchName, period) {
  // 生成完整分析结果。
  // bench: 大盘指数 K 线列表（可为 null），用于计算相对强弱。
  // period: K 线周期（day/week/month），用于年化系数与文字口径。
  if (bench === undefined) bench = null;
  if (benchName === undefined) benchName = '';
  if (period === undefined) period = 'day';
  const cf = PERIOD_CONF[period] || PERIOD_CONF['day'];
  const n = bars.length;
  const i = n - 1;
  const close = ind['close'][i];
  const sections = [];
  const bulls = [], bears = [];

  const bull = (t) => { bulls.push(t); };
  const bear = (t) => { bears.push(t); };

  // ================= 维度一：趋势 =================
  const d_trend = [];
  const tr_items = [];
  const ma5 = ind['ma5'][i], ma10 = ind['ma10'][i];
  const ma20 = ind['ma20'][i], ma60 = ind['ma60'][i];
  const ma120 = ind['ma120'][i], ma250 = ind['ma250'][i];

  const above = [];
  [['MA5', ma5], ['MA10', ma10], ['MA20', ma20], ['MA60', ma60]].forEach(([nm, mv]) => {
    if (mv !== null && mv !== undefined && close >= mv) above.push(nm);
  });
  const cnt_above = above.length;
  if (cnt_above === 4) {
    tr_items.push(['价格站在 5/10/20/60 日全部均线之上，属于标准的强势结构：短中期买入者的平均成本都低于现价，抛压相对小。', TONE_UP]);
    d_trend.push(['站上全部均线', 8]);
    bull('价格站上 MA5/10/20/60 全部均线');
  } else if (cnt_above >= 3) {
    tr_items.push(['价格位于 4 条主要均线中的 ' + cnt_above + ' 条之上，趋势偏多但结构还不够干净。', TONE_UP]);
    d_trend.push(['站上多数均线', 4]);
    bull('价格站上多数均线');
  } else if (cnt_above === 0) {
    tr_items.push(['价格跌破 5/10/20/60 日全部均线，属于弱势结构：近期买入者大多处于浮亏，反弹到均线附近容易被卖压挡住。', TONE_DOWN]);
    d_trend.push(['跌破全部均线', -8]);
    bear('价格跌破 MA5/10/20/60 全部均线');
  } else if (cnt_above === 1) {
    tr_items.push(['价格仅在 1 条均线之上，整体偏弱。', TONE_DOWN]);
    d_trend.push(['仅站上 1 条均线', -4]);
    bear('价格位于多数均线下方');
  } else {
    tr_items.push(['价格与均线交织，方向不明，属于震荡格局。', TONE_FLAT]);
  }

  if (ma5 !== null && ma10 !== null && ma20 !== null && ma60 !== null) {
    if (ma5 > ma10 && ma10 > ma20 && ma20 > ma60) {
      tr_items.push(['均线从上到下依次为 MA5 > MA10 > MA20 > MA60，呈「多头排列」，是趋势向上最直观的标志。', TONE_UP]);
      d_trend.push(['均线多头排列', 7]);
      bull('均线多头排列（MA5>MA10>MA20>MA60）');
    } else if (ma5 < ma10 && ma10 < ma20 && ma20 < ma60) {
      tr_items.push(['均线从上到下依次为 MA5 < MA10 < MA20 < MA60，呈「空头排列」，是趋势向下最直观的标志。', TONE_DOWN]);
      d_trend.push(['均线空头排列', -7]);
      bear('均线空头排列（MA5<MA10<MA20<MA60）');
    } else {
      tr_items.push(['均线排列交错，趋势尚未形成。', TONE_FLAT]);
    }
  }

  if (ma20 !== null && i >= 6 && ind['ma20'][i - 5]) {
    const slope = (ma20 - ind['ma20'][i - 5]) / ind['ma20'][i - 5] * 100.0;
    if (slope > 1.0) {
      tr_items.push(['20 日均线（中期成本线）近 5 根 K 线上移 ' + _fmt(slope, 2) + '%，中期趋势向上。', TONE_UP]);
      d_trend.push(['MA20 上行', 4]);
      bull('MA20 持续上移，中期趋势向上');
    } else if (slope < -1.0) {
      tr_items.push(['20 日均线近 5 根 K 线下移 ' + _fmt(slope, 2) + '%，中期趋势向下。', TONE_DOWN]);
      d_trend.push(['MA20 下行', -4]);
      bear('MA20 持续下移，中期趋势向下');
    }
  }

  const pdi = ind['pdi'][i], ndi = ind['ndi'][i], adx = ind['adx'][i];
  if (pdi !== null && ndi !== null && adx !== null) {
    let strength;
    if (adx >= 25) strength = '趋势较强';
    else if (adx >= 20) strength = '趋势初成';
    else strength = '无明显趋势（震荡市）';
    const direction = pdi > ndi ? '多头占优' : '空头占优';
    tr_items.push(['ADX=' + _fmt(adx, 1) + '，' + strength + '；+DI ' + _fmt(pdi, 1) + ' 与 -DI ' + _fmt(ndi, 1) + ' 相比' + direction + '。ADX 只衡量趋势强弱，方向看 DI 的高低。',
                  (adx >= 20 && pdi > ndi) ? TONE_UP :
                  ((adx >= 20 && pdi < ndi) ? TONE_DOWN : TONE_FLAT)]);
    if (adx >= 22 && pdi > ndi) {
      d_trend.push(['ADX 上行且多头占优', 4]);
      bull('ADX 显示趋势明确且多头占优');
    } else if (adx >= 22 && pdi < ndi) {
      d_trend.push(['ADX 上行且空头占优', -4]);
      bear('ADX 显示趋势明确但空头占优');
    }
  }

  if (bars.length >= 61) {
    const r20 = _pct(bars[i - 20]['c'], close);
    const r60 = _pct(bars[i - 60]['c'], close);
    tr_items.push(['近 20 根 K 线累计涨跌 ' + _num(r20, '%') + '，近 60 根累计涨跌 ' + _num(r60, '%') + '。',
                   ((r20 || 0) >= 0) ? TONE_UP : TONE_DOWN]);
  }
  sections.push(['一、趋势结构（价格与均线的关系）', tr_items]);

  // 相对大盘
  if (bench && bench.length >= 21 && bars.length >= 21) {
    try {
      const s20 = bars[i - 20]['c'];
      const b20 = bench[bench.length - 21]['c'];
      const b_now = bench[bench.length - 1]['c'];
      const sr = s20 ? (close - s20) / s20 * 100.0 : 0.0;
      const br = b20 ? (b_now - b20) / b20 * 100.0 : 0.0;
      const diff = sr - br;
      let win_days = 0;
      for (let k = 1; k <= 20; k++) {
        const si = i - 20 + k, bi = bench.length - 21 + k;
        if (si < 1 || bi < 1) continue;
        const sc = bars[si]['c'] - bars[si - 1]['c'];
        const bc = bench[bi]['c'] - bench[bi - 1]['c'];
        if (sc > bc) win_days++;
      }
      const tone = diff > 0 ? TONE_UP : TONE_DOWN;
      const vs = diff >= 0 ? ('跑赢大盘 ' + _fmt(diff, 2) + ' 个百分点') :
                 ('跑输大盘 ' + _fmt(Math.abs(diff), 2) + ' 个百分点');
      tr_items.push(['相对强弱：近 20 根 K 线本标的 ' + _num(sr, '%') + '，' + (benchName || '大盘') + ' ' + _num(br, '%') + '，' + vs + '；20 根里跑赢 ' + win_days + ' 根。', tone]);
      if (diff > 3) {
        d_trend.push(['跑赢大盘', 4]);
        bull('近 20 日明显跑赢大盘（+' + _fmt(diff, 1) + ' 个百分点）');
      } else if (diff < -3) {
        d_trend.push(['跑输大盘', -4]);
        bear('近 20 日明显跑输大盘（' + _fmt(diff, 1) + ' 个百分点）');
      }
    } catch (e) { // noqa
      // 忽略异常
    }
  }

  // ================= 维度二：动量 =================
  const d_mom = [];
  const mom_items = [];
  const dif = ind['dif'][i], dea = ind['dea'][i], hist = ind['hist'][i];
  if (dif !== null && dea !== null) {
    const state = dif > dea ? '多头状态（快线在慢线之上）' : '空头状态（快线在慢线之下）';
    mom_items.push(['MACD 处于' + state + '：DIF=' + _fmt(dif, 3) + '，DEA=' + _fmt(dea, 3) + '。MACD 是最常用的中期动能指标，红柱放大代表上涨动能在积累。',
                    dif > dea ? TONE_UP : TONE_DOWN]);
    d_mom.push(['MACD ' + (dif > dea ? '多头' : '空头'), dif > dea ? 5 : -5]);
    (dif > dea ? bull : bear)('MACD ' + (dif > dea ? '处于多头状态' : '处于空头状态'));

    const zero = dif > 0 ? '零轴上方，属于强势区' : '零轴下方，属于弱势区';
    mom_items.push(['DIF 位于' + zero + '。', dif > 0 ? TONE_UP : TONE_DOWN]);
    d_mom.push(['DIF 位置', dif > 0 ? 4 : -4]);
    (dif > 0 ? bull : bear)(dif > 0 ? 'MACD 快线在零轴上方' : 'MACD 快线在零轴下方');

    const [mx, mxago] = _crossState(ind['dif'], ind['dea']);
    if (mx === 'gold') {
      mom_items.push(['MACD 上一次金叉发生在 ' + mxago + ' 根 K 线之前' + (mxago <= 5 ? '，属于刚发生的信号' : '') + '。金叉指快线上穿慢线，通常视为动能转强的偏多信号。', TONE_UP]);
      d_mom.push(['MACD 金叉', 4]);
      bull('MACD 出现金叉');
    } else if (mx === 'dead') {
      mom_items.push(['MACD 上一次死叉发生在 ' + mxago + ' 根 K 线之前' + (mxago <= 5 ? '，属于刚发生的信号' : '') + '。死叉指快线下穿慢线，通常视为动能转弱的偏空信号。', TONE_DOWN]);
      d_mom.push(['MACD 死叉', -4]);
      bear('MACD 出现死叉');
    }

    if (i >= 2 && ind['hist'][i] !== null && ind['hist'][i - 1] !== null) {
      const h_now = ind['hist'][i], h_prev = ind['hist'][i - 1];
      if (h_now > h_prev && h_now > 0) {
        mom_items.push(['MACD 红柱较上一根放大，上涨动能仍在增强。', TONE_UP]);
        d_mom.push(['红柱放大', 3]);
      } else if (h_now < h_prev && h_now < 0) {
        mom_items.push(['MACD 绿柱较上一根放大，下跌动能仍在增强。', TONE_DOWN]);
        d_mom.push(['绿柱放大', -3]);
      } else if (h_now > 0 && h_now < h_prev) {
        mom_items.push(['MACD 红柱开始缩短，上涨动能有所减弱。', TONE_WARN]);
        d_mom.push(['红柱缩短', -2]);
      } else if (h_now < 0 && h_now > h_prev) {
        mom_items.push(['MACD 绿柱开始缩短，下跌动能有所减弱。', TONE_UP]);
        d_mom.push(['绿柱缩短', 2]);
      }
    }
  }

  const kk = ind['k'][i], dd = ind['d'][i], jj = ind['j'][i];
  if (kk !== null && dd !== null) {
    if (kk > 80) {
      mom_items.push(['KDJ 的 K=' + _fmt(kk, 1) + ' 进入超买区（>80）：短线涨得太快，追高容易买在阶段高点。', TONE_WARN]);
      d_mom.push(['KDJ 超买', -3]);
    } else if (kk < 20) {
      mom_items.push(['KDJ 的 K=' + _fmt(kk, 1) + ' 进入超卖区（<20）：短线跌得过多，存在超跌反弹的条件。', TONE_UP]);
      d_mom.push(['KDJ 超卖', 3]);
      bull('KDJ 进入超卖区，具备超跌反弹条件');
    } else {
      mom_items.push(['KDJ 的 K=' + _fmt(kk, 1) + ' 位于中性区间，短线没有极端信号。', TONE_FLAT]);
    }
    const [ks, kago] = _crossState(ind['k'], ind['d']);
    if (ks === 'gold' && kago <= 10) {
      mom_items.push(['KDJ 在 ' + kago + ' 根 K 线前金叉，短线偏强。', TONE_UP]);
      d_mom.push(['KDJ 金叉', 3]);
      bull('KDJ 近期金叉');
    } else if (ks === 'dead' && kago <= 10) {
      mom_items.push(['KDJ 在 ' + kago + ' 根 K 线前死叉，短线偏弱。', TONE_DOWN]);
      d_mom.push(['KDJ 死叉', -3]);
      bear('KDJ 近期死叉');
    }
  }

  const r6 = ind['rsi6'][i], r12 = ind['rsi12'][i], r24 = ind['rsi24'][i];
  if (r6 !== null) {
    if (r6 > 80) {
      mom_items.push(['RSI6=' + _fmt(r6, 1) + ' 处于超买（>80），继续上行需要更多增量资金。', TONE_WARN]);
      d_mom.push(['RSI 超买', -4]);
    } else if (r6 < 20) {
      mom_items.push(['RSI6=' + _fmt(r6, 1) + ' 处于超卖（<20），短线跌势可能接近尾声。', TONE_UP]);
      d_mom.push(['RSI 超卖', 4]);
      bull('RSI6 进入超卖区');
    } else if (r6 >= 45 && r6 <= 65) {
      mom_items.push(['RSI6=' + _fmt(r6, 1) + ' 位于 45-65 的良性区间，动能健康、不过热。', TONE_UP]);
      d_mom.push(['RSI 健康', 2]);
    } else {
      mom_items.push(['RSI6=' + _fmt(r6, 1) + ' 处于中性区间。', TONE_FLAT]);
    }
    mom_items.push(['RSI 6/12/24 日分别为 ' + _num(r6, '', 1) + ' / ' + _num(r12, '', 1) + ' / ' + _num(r24, '', 1) + '，数值越大代表近期上涨力量占比越高。', TONE_FLAT]);
  }

  const cc = ind['cci'][i];
  if (cc !== null) {
    if (cc > 100) {
      mom_items.push(['CCI=' + _fmt(cc, 0) + ' 高于 100，属于强势区（但过高时也提示短线过热）。', cc < 200 ? TONE_UP : TONE_WARN]);
      d_mom.push(['CCI 强势', 2]);
    } else if (cc < -100) {
      mom_items.push(['CCI=' + _fmt(cc, 0) + ' 低于 -100，属于弱势区，短线偏空。', TONE_DOWN]);
      d_mom.push(['CCI 弱势', -2]);
    } else {
      mom_items.push(['CCI=' + _fmt(cc, 0) + ' 在 -100 到 100 之间，属常态波动。', TONE_FLAT]);
    }
  }

  const ww = ind['wr'][i];
  if (ww !== null) {
    if (ww < 20) {
      mom_items.push(['威廉指标 WR=' + _fmt(ww, 1) + '（<20）说明价格贴近近期最高价，强势但已偏热。', TONE_WARN]);
    } else if (ww > 80) {
      mom_items.push(['威廉指标 WR=' + _fmt(ww, 1) + '（>80）说明价格贴近近期最低价，弱势但已偏冷。', TONE_UP]);
    } else {
      mom_items.push(['威廉指标 WR=' + _fmt(ww, 1) + ' 处于中性区间。', TONE_FLAT]);
    }
  }
  sections.push(['二、动量指标（MACD / KDJ / RSI / CCI / WR）', mom_items]);

  // ================= 维度三：量能与资金 =================
  const d_vol = [];
  const vol_items = [];
  const v_today = ind['vol'][i];
  const v5 = ind['vma5'][i], v20 = ind['vma20'][i];
  if (v5 && v20) {
    const ratio = v5 / v20;
    if (ratio > 1.5) {
      vol_items.push(['近 5 日均量是近 20 日均量的 ' + _fmt(ratio, 2) + ' 倍，属于明显放量，说明参与资金在增加。', TONE_WARN]);
    } else if (ratio > 1.15) {
      vol_items.push(['近 5 日均量是近 20 日均量的 ' + _fmt(ratio, 2) + ' 倍，温和放量，资金关注度有所提升。', TONE_FLAT]);
    } else if (ratio < 0.7) {
      vol_items.push(['近 5 日均量仅为近 20 日均量的 ' + _fmt(ratio, 2) + ' 倍，量能萎缩，观望情绪较重。', TONE_FLAT]);
    } else if (ratio < 0.9) {
      vol_items.push(['近 5 日均量是近 20 日均量的 ' + _fmt(ratio, 2) + ' 倍，量能小幅萎缩，参与意愿一般。', TONE_FLAT]);
    } else {
      vol_items.push(['近 5 日均量 / 近 20 日均量 = ' + _fmt(ratio, 2) + '，量能平稳。', TONE_FLAT]);
    }
  }

  if (v5 && v_today) {
    const tr = v_today / v5;
    const up_day = bars[i]['pct'] !== null && bars[i]['pct'] !== undefined && bars[i]['pct'] >= 0;
    if (tr > 1.5 && up_day) {
      vol_items.push(['今日成交量为 5 日均量的 ' + _fmt(tr, 2) + ' 倍且股价上涨，「量价齐升」是最健康的状态。', TONE_UP]);
      d_vol.push(['放量上涨', 5]);
      bull('放量上涨，量价配合良好');
    } else if (tr > 1.5 && !up_day) {
      vol_items.push(['今日放量下跌（为 5 日均量的 ' + _fmt(tr, 2) + ' 倍），说明卖盘主动出货，需要警惕。', TONE_DOWN]);
      d_vol.push(['放量下跌', -5]);
      bear('放量下跌，抛压较重');
    } else if (tr < 0.7 && !up_day) {
      vol_items.push(['今日缩量下跌（为 5 日均量的 ' + _fmt(tr, 2) + ' 倍），抛压并不重，属于相对健康的回调。', TONE_UP]);
      d_vol.push(['缩量回调', 3]);
      bull('缩量回调，抛压有限');
    } else if (tr < 0.6 && up_day) {
      vol_items.push(['今日缩量上涨，说明推动上涨的资金有限，后续能否延续要看量能是否跟上。', TONE_WARN]);
      d_vol.push(['缩量上涨', -1]);
    } else {
      vol_items.push(['今日成交量约为 5 日均量的 ' + _fmt(tr, 2) + ' 倍，量能正常。', TONE_FLAT]);
    }
  }

  const ob = ind['obv'][i], obma = ind['obv_ma'][i];
  if (ob !== null && obma !== null) {
    if (ob > obma) {
      vol_items.push(['OBV 能量潮位于其 30 日均线之上，资金累计方向偏流入。', TONE_UP]);
      d_vol.push(['OBV 走强', 3]);
      bull('OBV 资金累计方向向上');
    } else {
      vol_items.push(['OBV 能量潮位于其 30 日均线之下，资金累计方向偏流出。', TONE_DOWN]);
      d_vol.push(['OBV 走弱', -3]);
      bear('OBV 资金累计方向向下');
    }
  }

  if (bars.length >= 20) {
    let big_days = 0;
    for (let t = i - 19; t <= i; t++) {
      if (ind['vma20'][t] && ind['vol'][t] > ind['vma20'][t] * 1.3) big_days++;
    }
    vol_items.push(['近 20 根 K 线中有 ' + big_days + ' 根明显放量（超 20 日均量 1.3 倍），放量频率' + (big_days >= 8 ? '偏高，波动可能较大' : '正常') + '。', TONE_FLAT]);
  }

  const turn = bars[i]['turn'];
  if (turn) {
    const t60 = [];
    for (let t = Math.max(0, i - 59); t <= i; t++) {
      const tv = bars[t]['turn'];
      if (tv) t60.push(tv);
    }
    if (t60.length) {
      const avg_t = t60.reduce((a, b) => a + b, 0) / t60.length;
      if (avg_t) {
        const k = turn / avg_t;
        vol_items.push(['今日换手率 ' + _fmt(turn, 2) + '%，是近 60 日均值（' + _fmt(avg_t, 2) + '%）的 ' + _fmt(k, 2) + ' 倍，交投' + (k > 1.6 ? '明显活跃' : (k < 0.6 ? '清淡' : '正常')) + '。',
                        k > 1.6 ? TONE_UP : TONE_FLAT]);
      }
    }
  }

  if (flow && flow.length) {
    const f0 = flow[flow.length - 1];
    const same_day = f0['d'] === bars[i]['d'];
    const when = same_day ? '今日' : ('最近一个交易日（' + (f0['d'] || '') + '）');
    const main = f0['main'];
    if (main !== null && main !== undefined) {
      vol_items.push([when + '主力资金（大单+超大单）净' + (main > 0 ? '流入' : '流出') + ' ' + _big(Math.abs(main)) + '元。',
                      main > 0 ? TONE_UP : TONE_DOWN]);
      if (same_day) {
        d_vol.push([main > 0 ? '主力净流入' : '主力净流出', main > 0 ? 3 : -3]);
        (main > 0 ? bull : bear)('主力资金净' + (main > 0 ? '流入' : '流出') + ' ' + _big(Math.abs(main)) + '元');
      }
    }
    const seg = [['超大单', f0['huge']], ['大单', f0['big']],
                 ['中单', f0['mid']], ['小单', f0['small']]];
    const seg_txt = seg.filter(([nm, val]) => val !== null && val !== undefined)
      .map(([nm, val]) => nm + ' ' + ((val || 0) >= 0 ? '+' : '-') + _big(Math.abs(val || 0))).join('，');
    if (seg_txt) {
      vol_items.push(['资金结构：' + seg_txt + '。超大单和大单通常代表机构，中小单更多代表散户。', TONE_FLAT]);
    }
    if (flow.length >= 5) {
      let five = 0;
      for (let r = Math.max(0, flow.length - 5); r < flow.length; r++) {
        const mv = flow[r]['main'];
        if (mv !== null && mv !== undefined) five += mv;
      }
      vol_items.push(['近 5 个交易日主力资金合计净' + (five > 0 ? '流入' : '流出') + ' ' + _big(Math.abs(five)) + '元。',
                      five > 0 ? TONE_UP : TONE_DOWN]);
      d_vol.push(['5 日主力累计', five > 0 ? 2 : -2]);
      (five > 0 ? bull : bear)('近 5 日主力资金累计净' + (five > 0 ? '流入' : '流出'));
      if (flow.length >= 20) {
        let twenty = 0;
        for (let r = Math.max(0, flow.length - 20); r < flow.length; r++) {
          const mv = flow[r]['main'];
          if (mv !== null && mv !== undefined) twenty += mv;
        }
        vol_items.push(['近 20 个交易日主力资金合计净' + (twenty > 0 ? '流入' : '流出') + ' ' + _big(Math.abs(twenty)) + '元。',
                        twenty > 0 ? TONE_UP : TONE_DOWN]);
      }
    }
  } else {
    vol_items.push(['资金流数据暂不可用（该接口在部分网络环境下会被拦截），下方结论未计入此项。', TONE_FLAT]);
  }
  sections.push(['三、量能与资金（成交量 / 换手 / 主力资金）', vol_items]);

  // ================= 维度四：位置与成本 =================
  const d_pos = [];
  const pos_items = [];
  const hi250 = ind['hi250'][i], lo250 = ind['lo250'][i];
  const hi60 = ind['hi60'][i], lo60 = ind['lo60'][i];
  const hi20 = ind['hi20'][i], lo20 = ind['lo20'][i];

  let pos = null;
  if (hi250 !== null && lo250 !== null && hi250 > lo250) {
    pos = (close - lo250) / (hi250 - lo250) * 100.0;
    const rng_word = cf['range'];
    if (pos > 85) {
      pos_items.push(['现价处于' + rng_word + '区间的高位（' + _fmt(pos, 0) + '% 分位）：上方套牢盘少，但获利盘丰厚，一旦转向容易引发获利了结。', TONE_WARN]);
      d_pos.push(['区间高位', -3]);
    } else if (pos > 60) {
      pos_items.push(['现价处于' + rng_word + '区间的 ' + _fmt(pos, 0) + '% 分位，位置偏高但未极端。', TONE_FLAT]);
    } else if (pos > 40) {
      pos_items.push(['现价处于' + rng_word + '区间的 ' + _fmt(pos, 0) + '% 分位，位置居中。', TONE_FLAT]);
    } else if (pos > 20) {
      pos_items.push(['现价处于' + rng_word + '区间的 ' + _fmt(pos, 0) + '% 分位，位置偏低。', TONE_UP]);
      d_pos.push(['区间低位', 2]);
    } else {
      pos_items.push(['现价处于' + rng_word + '区间的低位（' + _fmt(pos, 0) + '% 分位）：下跌空间相对有限，但也要注意是否属于弱势趋势股。', TONE_UP]);
      d_pos.push(['区间低位', 3]);
      bull('价格处于长周期低位区间');
    }
    pos_items.push([rng_word + '区间：最高 ' + _num(hi250) + '，最低 ' + _num(lo250) + '，当前距高点 ' + _num(_pct(close, hi250), '%') + '、距低点 ' + _num(_pct(close, lo250), '%') + '。', TONE_FLAT]);
  }

  const cost20 = _vwapCost(bars, 20);
  const cost60 = _vwapCost(bars, 60);
  if (cost20) {
    const dev = (close - cost20) / cost20 * 100.0;
    pos_items.push(['近 20 根 K 线的成交量加权均价约 ' + _num(cost20) + '（可近似看作短线资金的平均成本），现价在其' + (dev >= 0 ? '上方' : '下方') + ' ' + _fmt(Math.abs(dev), 2) + '%。',
                    dev >= 0 ? TONE_UP : TONE_DOWN]);
    if (dev > 12) {
      pos_items.push(['现价明显高于短线平均成本，追高者占比大，回撤时容易引发连锁止盈。', TONE_WARN]);
      d_pos.push(['偏离短线成本过大', -3]);
    } else if (dev < -8) {
      pos_items.push(['现价明显低于短线平均成本，短期套牢盘较多，反弹到成本区附近会遇到解套卖压。', TONE_WARN]);
      d_pos.push(['低于短线成本较多', -2]);
    } else {
      d_pos.push(['贴近市场成本', 2]);
    }
  }
  if (cost60) {
    pos_items.push(['近 60 根 K 线的成交量加权均价约 ' + _num(cost60) + '，可作为中期成本参考。', TONE_FLAT]);
  }

  const b20 = ind['bias20'][i];
  if (b20 !== null) {
    if (b20 > 10) {
      pos_items.push(['乖离率 BIAS20=' + _fmt(b20, 2) + '%（>10%），价格偏离 20 日均线过远，短期有回归均线的需求。', TONE_WARN]);
      d_pos.push(['乖离率过高', -3]);
    } else if (b20 < -10) {
      pos_items.push(['乖离率 BIAS20=' + _fmt(b20, 2) + '%（<-10%），超跌明显，技术上有向均线靠拢的动能。', TONE_UP]);
      d_pos.push(['乖离率超跌', 3]);
      bull('乖离率显示超跌，存在向均线回归的动能');
    } else {
      pos_items.push(['乖离率 BIAS20=' + _fmt(b20, 2) + '%，价格与 20 日均线的距离正常。', TONE_FLAT]);
    }
  }

  if (hi60 && lo60) {
    pos_items.push(['近 60 根 K 线区间：最高 ' + _num(hi60) + '，最低 ' + _num(lo60) + '。', TONE_FLAT]);
  }
  pos_items.push(['说明：以上「近 N 根 K 线」均按当前所选周期计算（' + cf['range'] + '）。', TONE_FLAT]);
  sections.push(['四、位置与持仓成本', pos_items]);

  // ================= 维度五：风险与波动 =================
  const risk_items = [];
  let risk_score = 50.0;
  const atr14 = ind['atr14'][i];
  let ann = null;
  if (atr14 !== null && close) {
    const atr_pct = atr14 / close * 100.0;
    risk_items.push(['ATR(14)=' + _fmt(atr14, 2) + '，相当于股价的 ' + _fmt(atr_pct, 2) + '%：这是' + cf['bar'] + '平均波动的幅度参考，可用来估算止损距离。', TONE_FLAT]);
  }
  if (bars.length >= 21) {
    const rets = [];
    for (let t = n - 20; t < n; t++) {
      if (bars[t - 1]['c']) {
        rets.push((bars[t]['c'] - bars[t - 1]['c']) / bars[t - 1]['c']);
      }
    }
    if (rets.length >= 10) {
      let m = 0;
      for (let x = 0; x < rets.length; x++) m += rets[x];
      m = m / rets.length;
      let ss = 0;
      for (let x = 0; x < rets.length; x++) ss += (rets[x] - m) * (rets[x] - m);
      const sd = Math.sqrt(ss / rets.length);
      ann = sd * Math.sqrt(cf['ann']) * 100.0;
      let vtxt;
      if (ann > 50) vtxt = '波动较大，仓位不宜过重。';
      else if (ann > 28) vtxt = '波动中等。';
      else if (ann > 18) vtxt = '波动偏小，走势相对稳健。';
      else vtxt = '波动很小，属于典型的低波动品种。';
      risk_items.push(['按最近 20 根 K 线折算，年化波动率约 ' + _fmt(ann, 1) + '%。' + vtxt,
                       ann > 50 ? TONE_WARN : TONE_FLAT]);
    }
  }
  if (ind['boll_up'][i] !== null && ind['boll_dn'][i] !== null && ind['boll_mid'][i] !== null) {
    const bu = ind['boll_up'][i], bm = ind['boll_mid'][i], bd = ind['boll_dn'][i];
    const bw = bm ? (bu - bd) / bm * 100.0 : 0.0;
    let prev_bw = null;
    if (i >= 20) {
      const u0 = ind['boll_up'][i - 20], m0 = ind['boll_mid'][i - 20], d0 = ind['boll_dn'][i - 20];
      if (u0 !== null && m0 !== null && d0 !== null && m0) {
        prev_bw = (u0 - d0) / m0 * 100.0;
      }
    }
    const rngn = bu - bd;
    const pb = rngn ? (close - bd) / rngn * 100.0 : 50.0;
    if (close > bu) {
      risk_items.push(['价格已冲出布林上轨（布林位置 ' + _fmt(pb, 0) + '%），短期偏热，常见于强势股加速段，但也容易快速回落。', TONE_WARN]);
      d_mom.push(['突破布林上轨', -2]);
    } else if (close < bd) {
      risk_items.push(['价格跌破布林下轨（布林位置 ' + _fmt(pb, 0) + '%），极度弱势，按均值回归思路存在修复机会，但需等企稳信号。', TONE_WARN]);
    } else if (close >= bm) {
      risk_items.push(['价格在布林中轨之上（布林位置 ' + _fmt(pb, 0) + '%），处于强势半区，中轨 ' + _num(bm) + ' 可视为短期支撑。', TONE_UP]);
      d_mom.push(['布林中轨上方', 2]);
    } else {
      risk_items.push(['价格在布林中轨之下（布林位置 ' + _fmt(pb, 0) + '%），处于弱势半区，中轨 ' + _num(bm) + ' 是上方第一道压力。', TONE_DOWN]);
      d_mom.push(['布林中轨下方', -2]);
    }
    let band_txt = '';
    if (prev_bw) {
      if (bw < prev_bw * 0.85) {
        band_txt = '带宽由 ' + _fmt(prev_bw, 1) + '% 收窄至 ' + _fmt(bw, 1) + '%，波动收敛，往往预示变盘临近（方向未知，通常等突破方向明确再动手更稳妥）。';
      } else if (bw > prev_bw * 1.2) {
        band_txt = '带宽由 ' + _fmt(prev_bw, 1) + '% 扩张至 ' + _fmt(bw, 1) + '%，波动放大，趋势延续的概率提高。';
      }
    }
    risk_items.push(['布林上轨 ' + _num(bu) + ' / 中轨 ' + _num(bm) + ' / 下轨 ' + _num(bd) + '，带宽 ' + _fmt(bw, 2) + '%。' + band_txt, TONE_FLAT]);
  }

  let max_dd = null;
  if (bars.length >= 121) {
    const seg = [];
    for (let t = i - 120; t <= i; t++) seg.push(bars[t]['c']);
    let peak = seg[0], dd = 0.0;
    for (let x = 0; x < seg.length; x++) {
      const v = seg[x];
      peak = Math.max(peak, v);
      if (peak) dd = Math.min(dd, (v - peak) / peak * 100.0);
    }
    max_dd = dd;
    risk_items.push(['近 120 根 K 线最大回撤 ' + _fmt(Math.abs(max_dd), 2) + '%：衡量这段时间里从最高点回落的幅度，可用于评估持有体验。',
                     Math.abs(max_dd) > 35 ? TONE_WARN : TONE_FLAT]);
    risk_score += (Math.abs(max_dd) - 20.0) * 0.6;
  }
  if (ann !== null) {
    risk_score += (ann - 30.0) * 0.9;
  }
  risk_score = _clamp(risk_score, 3, 97);
  const risk_level = (risk_score >= 68) ? '风险偏高' : (risk_score >= 45 ? '风险中等' : '风险偏低');
  sections.push(['五、波动与风险', risk_items]);

  // ================= 六、K 线形态与缺口 =================
  const pat_items = [];
  const pats = _candlePattern(bars, i);
  if (pats.length) {
    for (let x = 0; x < pats.length; x++) {
      const name = pats[x][0], desc = pats[x][1];
      pat_items.push([name + '：' + desc, pats[x][2]]);
    }
  } else {
    pat_items.push(['最新 K 线没有出现典型形态（十字星 / 锤子线 / 吞没等），属于常规走势。', TONE_FLAT]);
  }
  const gaps = _measureGaps(bars, i);
  if (gaps.length) {
    for (let x = 0; x < Math.min(3, gaps.length); x++) {
      const kind = gaps[x][0], lo = gaps[x][1], hi = gaps[x][2];
      if (lo <= close && close <= hi) {
        pat_items.push([kind + ' ' + _num(lo) + ' ~ ' + _num(hi) + '：现价正处于缺口区间内，该位置多空争夺会比较激烈。', TONE_WARN]);
      } else if (hi < close) {
        pat_items.push([kind + ' ' + _num(lo) + ' ~ ' + _num(hi) + '：位于现价下方，缺口下沿常充当支撑。', TONE_UP]);
      } else {
        pat_items.push([kind + ' ' + _num(lo) + ' ~ ' + _num(hi) + '：位于现价上方，缺口上沿常构成压力。', TONE_DOWN]);
      }
    }
  } else {
    pat_items.push(['近 60 根 K 线内没有未回补的跳空缺口。', TONE_FLAT]);
  }
  sections.push(['六、K 线形态与缺口', pat_items]);

  // ================= 维度汇总 =================
  const dims = [
    _dim('趋势', '看价格与均线、ADX 的关系', d_trend, 0.35),
    _dim('动量', '看 MACD / KDJ / RSI 等动能指标', d_mom, 0.25),
    _dim('量能', '看成交量、换手与主力资金', d_vol, 0.15),
    _dim('位置', '看年内分位与持仓成本偏离', d_pos, 0.25),
  ];
  let overall = 0, wsum = 0;
  for (let x = 0; x < dims.length; x++) {
    overall += dims[x]['score'] * dims[x]['weight'];
    wsum += dims[x]['weight'];
  }
  overall = overall / wsum;
  overall = _clamp(overall, 1, 99);
  let level, tone;
  if (overall >= 70) { level = '偏强'; tone = TONE_UP; }
  else if (overall >= 58) { level = '中性偏强'; tone = TONE_UP; }
  else if (overall >= 43) { level = '中性'; tone = TONE_FLAT; }
  else if (overall >= 30) { level = '中性偏弱'; tone = TONE_DOWN; }
  else { level = '偏弱'; tone = TONE_DOWN; }

  const verdict = '技术面综合判断：' + level + '。' + (
    overall >= 70 ? '多头结构较完整，回踩不破关键均线时趋势有望延续。' :
    overall >= 58 ? '结构偏多但仍有瑕疵，建议等回踩确认或突破确认再行动。' :
    overall >= 43 ? '多空力量接近均衡，方向未明，区间内高抛低吸或观望更稳妥。' :
    overall >= 30 ? '空头占据主动，反弹到压力位附近更容易受阻，等待企稳信号比抢反弹更重要。' :
    '趋势与动能均偏弱，不宜逆势介入，先以观察风险为主。');

  let summary = '技术面综合评分 ' + _fmt(overall, 0) + ' / 100（' + level + '）。看多信号 ' + bulls.length + ' 项，看空信号 ' + bears.length + ' 项。';
  if (bulls.length) summary += '主要支撑：' + bulls.slice(0, 3).join('；') + '。';
  if (bears.length) summary += '主要拖累：' + bears.slice(0, 3).join('；') + '。';

  // ================= 关键价位阶梯 =================
  const raw_levels = [];
  [['MA5', ma5], ['MA10', ma10], ['MA20', ma20], ['MA60', ma60], ['MA120', ma120],
   ['布林上轨', ind['boll_up'][i]], ['布林中轨', ind['boll_mid'][i]], ['布林下轨', ind['boll_dn'][i]],
   ['近 20 根高点', hi20], ['近 20 根低点', lo20], ['近 60 根高点', hi60], ['近 60 根低点', lo60],
   [cf['hi250'], hi250], [cf['lo250'], lo250], ['近 20 根成本', cost20], ['近 60 根成本', cost60]
  ].forEach(([name, val]) => {
    if (val === null || val === undefined) return;
    raw_levels.push([name, val]);
  });
  for (let x = 0; x < Math.min(2, gaps.length); x++) {
    const kind = gaps[x][0], lo = gaps[x][1], hi = gaps[x][2];
    raw_levels.push([hi > close ? '缺口上沿' : '缺口下沿', hi > close ? hi : lo]);
  }

  // 同一价位往往被多个指标重复命中（如 60 根低点 = 250 根低点），合并显示
  const merged = [];
  const tol = close ? Math.abs(close) * 0.004 : 0.0;
  for (let x = 0; x < raw_levels.length; x++) {
    const name = raw_levels[x][0], val = raw_levels[x][1];
    let hit = null;
    for (let y = 0; y < merged.length; y++) {
      if (Math.abs(merged[y][1] - val) <= tol) { hit = merged[y]; break; }
    }
    if (hit === null) merged.push([name, val]);
    else if (hit[0].indexOf(name) === -1) hit[0] = hit[0] + ' / ' + name;
  }
  const levels = merged.map(([nm, v]) => [nm, v]);

  const supports = levels.filter(x => x[1] < close).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const resists = levels.filter(x => x[1] > close).sort((a, b) => a[1] - b[1]).slice(0, 4);

  let plain = '白话版：' + verdict.slice(verdict.indexOf('：') + 1) + ' ';
  if (supports.length) {
    plain += '下方 ' + _num(supports[0][1]) + ' 是最近的支撑（跌到那里容易有买盘），';
  }
  if (resists.length) {
    plain += '上方 ' + _num(resists[0][1]) + ' 是最近的阻力（涨到那里容易有卖盘）。';
  }
  if (risk_score >= 68) {
    plain += '当前波动偏大，参与时更需要控制仓位。';
  } else if (risk_score >= 45) {
    plain += '当前波动中等，操作前先想好止损位。';
  } else if (risk_score >= 30) {
    plain += '当前波动偏小，走势相对平稳。';
  } else {
    plain += '当前波动很小，属于低波动品种。';
  }

  // ================= 情景应对 =================
  const scenarios = [];
  if (resists.length) {
    const r0 = resists[0];
    scenarios.push(['向上突破', '若能放量站稳 ' + _num(r0[1]) + '（' + r0[0] + '）之上',
                    '说明上方压力被有效消化，中期空间打开，可视为趋势延续的确认信号。', TONE_UP]);
  }
  if (supports.length) {
    const s0 = supports[0];
    scenarios.push(['回踩确认', '若回踩 ' + _num(s0[1]) + '（' + s0[0] + '）附近止跌企稳',
                    '这是趋势股常见的上车/加仓位置；若跌破且不能快速收回，则视为结构走坏。', TONE_UP]);
    const s_last = supports[supports.length - 1];
    scenarios.push(['跌破关键位', '若有效跌破 ' + _num(s_last[1]) + '（' + s_last[0] + '）',
                    '说明这一段上涨或震荡结构被破坏，应先降低仓位、控制风险，而不是继续摊薄成本。', TONE_DOWN]);
  }
  if (risk_items.length) {
    scenarios.push(['波动参考', '按 ATR 估算，单日正常波动约 ' + _num(atr14) + '（' + _fmt((atr14 && close) ? atr14 / close * 100.0 : 0, 2) + '%）',
                    '止损位可以放在关键支撑下方 1 个 ATR 左右，避免被正常波动扫掉。', TONE_FLAT]);
  }

  return {
    'score': overall,
    'level': level,
    'level_tone': tone,
    'verdict': verdict,
    'summary': summary,
    'plain': plain,
    'dims': dims,
    'risk': { 'score': risk_score, 'level': risk_level, 'items': risk_items },
    'bulls': bulls,
    'bears': bears,
    'sections': sections,
    'supports': supports,
    'resists': resists,
    'scenarios': scenarios,
    'parts': bulls.map(t => ['+ ' + t, 1]).concat(bears.map(t => ['- ' + t, -1])),
    'meta': {
      'bars': n,
      'last_date': bars[i]['d'],
      'pos': pos,
      'max_dd': max_dd,
      'ann_vol': ann,
      'bench': benchName,
    },
  };
}

// --------------------------------------------------------------------------
// 导出
// --------------------------------------------------------------------------

var AN = {
  computeIndicators: _computeIndicators,
  buildAnalysis: _buildAnalysis,
  // 辅助函数（保留原名称，便于移动端复用/核对）
  _num: _num,
  _big: _big,
  _vol_hand: _vol_hand,
  value_at: _valueAt,
  candle_pattern: _candlePattern,
  measure_gaps: _measureGaps,
  _dim: _dim,
  _clamp: _clamp,
  _pct: _pct,
};

if (typeof module !== 'undefined' && module.exports) { module.exports = AN; }
