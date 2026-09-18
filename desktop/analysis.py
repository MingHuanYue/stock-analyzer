# -*- coding: utf-8 -*-
"""指标计算与规则化分析引擎（纯标准库）。

指标算法与国内主流行情软件（通达信口径）保持一致：
  MACD(12,26,9)  EMA 以首值为种子；柱 = 2 x (DIF - DEA)
  KDJ(9,3,3)     K/D 以 50 为种子，J = 3K - 2D
  RSI(N)         SMA(X, N, 1) 威尔德平滑
  BOLL(20, 2)    中轨 MA20 ± 2 倍标准差
  DMI/ADX(14)    威尔德平滑，衡量趋势强度（不辨方向）
  CCI(14) / WR(14) / BIAS(20) / OBV  常用辅助指标

分析输出面向「看得懂」：每个信号都带一句白话解释，并给出维度评分、
多空信号对照、关键价位阶梯与条件化情景应对。
"""
import math

# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------


def sma(values, n):
    out = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(values, n):
    out = [None] * len(values)
    if not values:
        return out
    k = 2.0 / (n + 1.0)
    prev = None
    for i, v in enumerate(values):
        prev = v if prev is None else v * k + prev * (1.0 - k)
        out[i] = prev
    return out


def wilder(values, n):
    """通达信 SMA(X, N, 1)：Y = (X + (N-1) * Y') / N，首值作种子。"""
    out = [None] * len(values)
    prev = None
    for i, v in enumerate(values):
        prev = v if prev is None else (v + (n - 1) * prev) / n
        out[i] = prev
    return out


def stddev(values, n):
    out = [None] * len(values)
    for i in range(len(values)):
        if i < n - 1:
            continue
        win = values[i - n + 1:i + 1]
        m = sum(win) / n
        out[i] = math.sqrt(sum((x - m) ** 2 for x in win) / n)
    return out


def rolling_max(values, n):
    out = [None] * len(values)
    for i in range(len(values)):
        if i >= n - 1:
            out[i] = max(values[i - n + 1:i + 1])
    return out


def rolling_min(values, n):
    out = [None] * len(values)
    for i in range(len(values)):
        if i >= n - 1:
            out[i] = min(values[i - n + 1:i + 1])
    return out


def cross_state(fast, slow, lookback=90):
    """最近一次交叉：返回 ('gold'|'dead', 距今 K 线根数) 或 (None, None)。"""
    n = len(fast)
    for i in range(n - 1, max(0, n - lookback) - 1, -1):
        a0, b0, a1, b1 = fast[i - 1], slow[i - 1], fast[i], slow[i]
        if None in (a0, b0, a1, b1):
            continue
        if a1 > b1 and a0 <= b0:
            return 'gold', n - 1 - i
        if a1 < b1 and a0 >= b0:
            return 'dead', n - 1 - i
    return None, None


def last(series):
    for v in reversed(series):
        if v is not None:
            return v
    return None


def value_at(series, idx):
    if 0 <= idx < len(series):
        return series[idx]
    return None


# --------------------------------------------------------------------------
# 指标组
# --------------------------------------------------------------------------

def macd(close, fast=12, slow=26, signal=9):
    ef, es = ema(close, fast), ema(close, slow)
    dif = [None if (a is None or b is None) else a - b for a, b in zip(ef, es)]
    dea = ema([d if d is not None else 0.0 for d in dif], signal)
    hist = [None if (a is None or b is None) else 2.0 * (a - b) for a, b in zip(dif, dea)]
    return dif, dea, hist


def kdj(high, low, close, n=9, m1=3, m2=3):
    ln = len(close)
    hh, ll = rolling_max(high, n), rolling_min(low, n)
    rsv = [None] * ln
    for i in range(ln):
        if hh[i] is None or ll[i] is None:
            continue
        rng = hh[i] - ll[i]
        rsv[i] = 50.0 if rng == 0 else (close[i] - ll[i]) / rng * 100.0
    k = [None] * ln
    d = [None] * ln
    pk = pd = 50.0
    for i in range(ln):
        if rsv[i] is None:
            continue
        pk = (rsv[i] + (m1 - 1) * pk) / m1
        pd = (pk + (m2 - 1) * pd) / m2
        k[i], d[i] = pk, pd
    j = [None if (k[i] is None or d[i] is None) else 3 * k[i] - 2 * d[i] for i in range(ln)]
    return k, d, j


def rsi(close, n=6):
    ln = len(close)
    up, dn = [0.0] * ln, [0.0] * ln
    for i in range(1, ln):
        diff = close[i] - close[i - 1]
        up[i] = max(diff, 0.0)
        dn[i] = abs(diff)
    su, sd = wilder(up, n), wilder(dn, n)
    out = [None] * ln
    for i in range(ln):
        if su[i] is None or sd[i] is None:
            continue
        out[i] = 50.0 if sd[i] == 0 else su[i] / sd[i] * 100.0
    return out


def boll(close, n=20, k=2.0):
    mid = sma(close, n)
    sd = stddev(close, n)
    up = [None if (mid[i] is None or sd[i] is None) else mid[i] + k * sd[i]
          for i in range(len(close))]
    dn = [None if (mid[i] is None or sd[i] is None) else mid[i] - k * sd[i]
          for i in range(len(close))]
    return up, mid, dn


def atr(high, low, close, n=14):
    ln = len(close)
    tr = [0.0] * ln
    for i in range(ln):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]),
                        abs(low[i] - close[i - 1]))
    return wilder(tr, n)


def dmi(high, low, close, n=14):
    """返回 (+DI, -DI, ADX)。ADX 越大趋势越强（不分方向）。"""
    ln = len(close)
    tr = [0.0] * ln
    pdm = [0.0] * ln
    ndm = [0.0] * ln
    for i in range(ln):
        if i == 0:
            tr[i] = high[i] - low[i]
            continue
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]))
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        if up > dn and up > 0:
            pdm[i] = up
        elif dn > up and dn > 0:
            ndm[i] = dn
    atr_ = wilder(tr, n)
    pdi, ndi, dx = [None] * ln, [None] * ln, [None] * ln
    for i in range(ln):
        if not atr_[i]:
            continue
        pdi[i] = 100.0 * wilder(pdm, n)[i] / atr_[i]
        ndi[i] = 100.0 * wilder(ndm, n)[i] / atr_[i]
        s = pdi[i] + ndi[i]
        dx[i] = 0.0 if s == 0 else 100.0 * abs(pdi[i] - ndi[i]) / s
    return pdi, ndi, wilder([v if v is not None else 0.0 for v in dx], n)


def cci(high, low, close, n=14):
    ln = len(close)
    tp = [(high[i] + low[i] + close[i]) / 3.0 for i in range(ln)]
    ma = sma(tp, n)
    out = [None] * ln
    for i in range(ln):
        if ma[i] is None:
            continue
        win = tp[i - n + 1:i + 1]
        md = sum(abs(x - ma[i]) for x in win) / n
        out[i] = 0.0 if md == 0 else (tp[i] - ma[i]) / (0.015 * md)
    return out


def wr(high, low, close, n=14):
    """威廉指标：0-20 超买，80-100 超卖（数值越小越强）。"""
    hh, ll = rolling_max(high, n), rolling_min(low, n)
    out = [None] * len(close)
    for i in range(len(close)):
        if hh[i] is None or ll[i] is None:
            continue
        rng = hh[i] - ll[i]
        out[i] = 50.0 if rng == 0 else (hh[i] - close[i]) / rng * 100.0
    return out


def obv(close, volume):
    """能量潮：涨日累加成交量，跌日累减，反映资金进出方向。"""
    out = [0.0] * len(close)
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out


def bias(close, n=20):
    ma = sma(close, n)
    return [None if ma[i] in (None, 0) else (close[i] - ma[i]) / ma[i] * 100.0
            for i in range(len(close))]


def vwap_cost(bars, n):
    """近 n 日成交量加权均价，近似市场平均持仓成本。"""
    win = bars[-n:] if len(bars) > n else bars
    tot = sum(b['v'] for b in win)
    if not tot:
        return None
    return sum(((b['h'] + b['l'] + b['c']) / 3.0) * b['v'] for b in win) / tot


def compute_indicators(bars):
    """对完整序列计算指标，返回与 bars 等长的各序列。"""
    close = [b['c'] for b in bars]
    high = [b['h'] for b in bars]
    low = [b['l'] for b in bars]
    vol = [b['v'] for b in bars]

    dif, dea, hist = macd(close)
    k, d, j = kdj(high, low, close)
    up, mid, dn = boll(close)
    pdi, ndi, adx = dmi(high, low, close)
    ob = obv(close, vol)

    return {
        'close': close, 'high': high, 'low': low, 'vol': vol,
        'ma5': sma(close, 5), 'ma10': sma(close, 10), 'ma20': sma(close, 20),
        'ma60': sma(close, 60), 'ma120': sma(close, 120), 'ma250': sma(close, 250),
        'vma5': sma(vol, 5), 'vma10': sma(vol, 10), 'vma20': sma(vol, 20),
        'dif': dif, 'dea': dea, 'hist': hist,
        'k': k, 'd': d, 'j': j,
        'rsi6': rsi(close, 6), 'rsi12': rsi(close, 12), 'rsi24': rsi(close, 24),
        'boll_up': up, 'boll_mid': mid, 'boll_dn': dn,
        'atr14': atr(high, low, close, 14),
        'pdi': pdi, 'ndi': ndi, 'adx': adx,
        'cci': cci(high, low, close), 'wr': wr(high, low, close),
        'bias20': bias(close, 20),
        'obv': ob, 'obv_ma': sma(ob, 30),
        'hi20': rolling_max(high, 20), 'lo20': rolling_min(low, 20),
        'hi60': rolling_max(high, 60), 'lo60': rolling_min(low, 60),
        'hi250': rolling_max(high, 250), 'lo250': rolling_min(low, 250),
    }


# --------------------------------------------------------------------------
# 格式化工具（界面与报告共用）
# --------------------------------------------------------------------------

TONE_UP = 'up'
TONE_DOWN = 'down'
TONE_WARN = 'warn'
TONE_FLAT = 'flat'


def _num(v, unit='', digits=2):
    if v is None:
        return '—'
    if unit == '%':
        return ('%.' + str(digits) + 'f%%') % v
    return ('%.' + str(digits) + 'f') % v


def _big(v):
    """金额自适应单位（元）。"""
    if v is None:
        return '—'
    a = abs(v)
    if a >= 1e12:
        return '%.2f 万亿' % (v / 1e12)
    if a >= 1e8:
        return '%.2f 亿' % (v / 1e8)
    if a >= 1e4:
        return '%.2f 万' % (v / 1e4)
    return '%.0f' % v


def _vol_hand(v):
    if v is None:
        return '—'
    if v >= 1e8:
        return '%.2f 亿手' % (v / 1e8)
    if v >= 1e4:
        return '%.2f 万手' % (v / 1e4)
    return '%.0f 手' % v


def _pct(a, b):
    if a in (None, 0) or b is None:
        return None
    return (b - a) / abs(a) * 100.0


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------
# 形态与结构识别
# --------------------------------------------------------------------------

def candle_pattern(bars, i):
    """识别单根 K 线形态与组合形态，返回 (名称, 含义, tone) 列表。"""
    res = []
    b = bars[i]
    body = abs(b['c'] - b['o'])
    rng = b['h'] - b['l']
    if rng <= 0:
        return res
    upper = b['h'] - max(b['o'], b['c'])
    lower = min(b['o'], b['c']) - b['l']
    up = b['c'] >= b['o']

    if body / rng < 0.12:
        res.append(('十字星', '开收盘几乎相同，多空暂时势均力敌，常出现在变盘前。', TONE_FLAT))
    elif lower > body * 2 and upper < body * 0.6:
        res.append(('锤子线' if up else '下影线较长',
                    '下方有承接资金把价格买回，短期下跌动能减弱。', TONE_UP))
    elif upper > body * 2 and lower < body * 0.6:
        res.append(('长上影线', '上方抛压明显，冲高被压回，短期上行受阻。', TONE_DOWN))

    if i >= 1:
        p = bars[i - 1]
        if up and p['c'] < p['o'] and b['c'] > p['o'] and b['o'] < p['c']:
            res.append(('看涨吞没', '今日阳线完全包住昨日阴线，是较强的反转向上信号。', TONE_UP))
        if (not up) and p['c'] > p['o'] and b['c'] < p['o'] and b['o'] > p['c']:
            res.append(('看跌吞没', '今日阴线完全包住昨日阳线，是较强的反转向下信号。', TONE_DOWN))
        if b['l'] > p['h']:
            res.append(('向上跳空缺口', '开盘直接跳过昨日最高价，说明买盘急切，缺口下沿常成为支撑。', TONE_UP))
        elif b['h'] < p['l']:
            res.append(('向下跳空缺口', '开盘直接低于昨日最低价，说明抛压急切，缺口上沿常成为压力。', TONE_DOWN))

    # 连续同向
    run = 1
    for t in range(i, 0, -1):
        if (bars[t]['c'] >= bars[t]['o']) == up:
            run += 1
        else:
            break
    if run >= 4:
        res.append(('%d 连%s' % (run - 1, '阳' if up else '阴'),
                    '连续同向运行，短线%s能量已有一定释放，注意节奏。'
                    % ('上涨' if up else '下跌'),
                    TONE_WARN))
    return res


def measure_gaps(bars, i):
    """统计近 60 根 K 线内的未回补缺口，作为潜在支撑/压力。"""
    out = []
    start = max(1, i - 59)
    for t in range(i, start - 1, -1):
        b, p = bars[t], bars[t - 1]
        if b['l'] > p['h']:
            low, high = p['h'], b['l']
            filled = any(bars[u]['l'] <= low for u in range(t + 1, len(bars)))
            if not filled:
                out.append(('向上缺口', low, high))
        elif b['h'] < p['l']:
            low, high = b['h'], p['l']
            filled = any(bars[u]['h'] >= high for u in range(t + 1, len(bars)))
            if not filled:
                out.append(('向下缺口', low, high))
    return out


# --------------------------------------------------------------------------
# 分析主体
# --------------------------------------------------------------------------

def _dim(name, note, deltas, weight=None):
    """维度评分：中性 50 分，按信号累加后截断。"""
    total = sum(d for _l, d in deltas)
    score = _clamp(50.0 + total * 1.4, 3.0, 97.0)
    if score >= 56:
        tone = TONE_UP
    elif score >= 44:
        tone = TONE_FLAT
    else:
        tone = TONE_DOWN
    return {'name': name, 'score': score, 'tone': tone, 'note': note,
            'weight': weight, 'items': deltas}


# 不同 K 线周期的口径换算（年化系数、量词、区间描述）
PERIOD_CONF = {
    'day': {'ann': 244, 'range': '近一年（250 个交易日）', 'bar': '单日',
            'hi250': '近 250 根高点（年内高点）', 'lo250': '近 250 根低点（年内低点）'},
    'week': {'ann': 52, 'range': '近 250 周（约 5 年）', 'bar': '单周',
             'hi250': '近 250 根高点（约 5 年高点）', 'lo250': '近 250 根低点（约 5 年低点）'},
    'month': {'ann': 12, 'range': '近 250 月（约 20 年）', 'bar': '单月',
              'hi250': '近 250 根高点（约 20 年高点）', 'lo250': '近 250 根低点（约 20 年低点）'},
}


def build_analysis(quote, bars, ind, flow, fin, bench=None, bench_name='', period='day'):
    """生成完整分析结果。

    bench: 大盘指数 K 线列表（可为 None），用于计算相对强弱。
    period: K 线周期（day/week/month），用于年化系数与文字口径。
    """
    cf = PERIOD_CONF.get(period, PERIOD_CONF['day'])
    n = len(bars)
    i = n - 1
    close = ind['close'][i]
    sections = []
    bulls, bears = [], []

    def bull(t):
        bulls.append(t)

    def bear(t):
        bears.append(t)

    # ================= 维度一：趋势 =================
    d_trend = []
    tr_items = []
    ma5, ma10 = ind['ma5'][i], ind['ma10'][i]
    ma20, ma60 = ind['ma20'][i], ind['ma60'][i]
    ma120, ma250 = ind['ma120'][i], ind['ma250'][i]

    above = [nm for nm, mv in (('MA5', ma5), ('MA10', ma10), ('MA20', ma20),
                               ('MA60', ma60)) if mv is not None and close >= mv]
    cnt_above = len(above)
    if cnt_above == 4:
        tr_items.append(('价格站在 5/10/20/60 日全部均线之上，属于标准的强势结构：'
                         '短中期买入者的平均成本都低于现价，抛压相对小。', TONE_UP))
        d_trend.append(('站上全部均线', 8))
        bull('价格站上 MA5/10/20/60 全部均线')
    elif cnt_above >= 3:
        tr_items.append(('价格位于 4 条主要均线中的 %d 条之上，趋势偏多但结构还不够干净。'
                         % cnt_above, TONE_UP))
        d_trend.append(('站上多数均线', 4))
        bull('价格站上多数均线')
    elif cnt_above == 0:
        tr_items.append(('价格跌破 5/10/20/60 日全部均线，属于弱势结构：'
                         '近期买入者大多处于浮亏，反弹到均线附近容易被卖压挡住。', TONE_DOWN))
        d_trend.append(('跌破全部均线', -8))
        bear('价格跌破 MA5/10/20/60 全部均线')
    elif cnt_above == 1:
        tr_items.append(('价格仅在 1 条均线之上，整体偏弱。', TONE_DOWN))
        d_trend.append(('仅站上 1 条均线', -4))
        bear('价格位于多数均线下方')
    else:
        tr_items.append(('价格与均线交织，方向不明，属于震荡格局。', TONE_FLAT))

    if None not in (ma5, ma10, ma20, ma60):
        if ma5 > ma10 > ma20 > ma60:
            tr_items.append(('均线从上到下依次为 MA5 > MA10 > MA20 > MA60，'
                             '呈「多头排列」，是趋势向上最直观的标志。', TONE_UP))
            d_trend.append(('均线多头排列', 7))
            bull('均线多头排列（MA5>MA10>MA20>MA60）')
        elif ma5 < ma10 < ma20 < ma60:
            tr_items.append(('均线从上到下依次为 MA5 < MA10 < MA20 < MA60，'
                             '呈「空头排列」，是趋势向下最直观的标志。', TONE_DOWN))
            d_trend.append(('均线空头排列', -7))
            bear('均线空头排列（MA5<MA10<MA20<MA60）')
        else:
            tr_items.append(('均线排列交错，趋势尚未形成。', TONE_FLAT))

    if ma20 is not None and i >= 6 and ind['ma20'][i - 5]:
        slope = (ma20 - ind['ma20'][i - 5]) / ind['ma20'][i - 5] * 100.0
        if slope > 1.0:
            tr_items.append(('20 日均线（中期成本线）近 5 根 K 线上移 %.2f%%，中期趋势向上。'
                             % slope, TONE_UP))
            d_trend.append(('MA20 上行', 4))
            bull('MA20 持续上移，中期趋势向上')
        elif slope < -1.0:
            tr_items.append(('20 日均线近 5 根 K 线下移 %.2f%%，中期趋势向下。' % slope, TONE_DOWN))
            d_trend.append(('MA20 下行', -4))
            bear('MA20 持续下移，中期趋势向下')

    pdi, ndi, adx = ind['pdi'][i], ind['ndi'][i], ind['adx'][i]
    if None not in (pdi, ndi, adx):
        if adx >= 25:
            strength = '趋势较强'
        elif adx >= 20:
            strength = '趋势初成'
        else:
            strength = '无明显趋势（震荡市）'
        direction = '多头占优' if pdi > ndi else '空头占优'
        tr_items.append(('ADX=%.1f，%s；+DI %.1f 与 -DI %.1f 相比%s。'
                         'ADX 只衡量趋势强弱，方向看 DI 的高低。'
                         % (adx, strength, pdi, ndi, direction),
                         TONE_UP if (adx >= 20 and pdi > ndi) else
                         (TONE_DOWN if (adx >= 20 and pdi < ndi) else TONE_FLAT)))
        if adx >= 22 and pdi > ndi:
            d_trend.append(('ADX 上行且多头占优', 4))
            bull('ADX 显示趋势明确且多头占优')
        elif adx >= 22 and pdi < ndi:
            d_trend.append(('ADX 上行且空头占优', -4))
            bear('ADX 显示趋势明确但空头占优')

    if len(bars) >= 61:
        r20 = _pct(bars[i - 20]['c'], close)
        r60 = _pct(bars[i - 60]['c'], close)
        tr_items.append(('近 20 根 K 线累计涨跌 %s，近 60 根累计涨跌 %s。'
                         % (_num(r20, '%'), _num(r60, '%')),
                         TONE_UP if (r20 or 0) >= 0 else TONE_DOWN))
    sections.append(('一、趋势结构（价格与均线的关系）', tr_items))

    # 相对大盘
    if bench and len(bench) >= 21 and len(bars) >= 21:
        try:
            s20 = bars[i - 20]['c']
            b20 = bench[-21]['c']
            b_now = bench[-1]['c']
            sr = (close - s20) / s20 * 100.0 if s20 else 0.0
            br = (b_now - b20) / b20 * 100.0 if b20 else 0.0
            diff = sr - br
            win_days = 0
            for k in range(1, 21):
                si, bi = i - 20 + k, len(bench) - 21 + k
                if si < 1 or bi < 1:
                    continue
                sc = bars[si]['c'] - bars[si - 1]['c']
                bc = bench[bi]['c'] - bench[bi - 1]['c']
                if sc > bc:
                    win_days += 1
            tone = TONE_UP if diff > 0 else TONE_DOWN
            vs = ('跑赢大盘 %.2f 个百分点' % diff) if diff >= 0 else \
                 ('跑输大盘 %.2f 个百分点' % abs(diff))
            tr_items.append(('相对强弱：近 20 根 K 线本标的 %s，%s %s，%s；'
                             '20 根里跑赢 %d 根。'
                             % (_num(sr, '%'), bench_name or '大盘', _num(br, '%'),
                                vs, win_days), tone))
            if diff > 3:
                d_trend.append(('跑赢大盘', 4))
                bull('近 20 日明显跑赢大盘（+%.1f 个百分点）' % diff)
            elif diff < -3:
                d_trend.append(('跑输大盘', -4))
                bear('近 20 日明显跑输大盘（%.1f 个百分点）' % diff)
        except Exception:                                 # noqa: BLE001
            pass

    # ================= 维度二：动量 =================
    d_mom = []
    mom_items = []
    dif, dea, hist = ind['dif'][i], ind['dea'][i], ind['hist'][i]
    if None not in (dif, dea):
        state = '多头状态（快线在慢线之上）' if dif > dea else '空头状态（快线在慢线之下）'
        mom_items.append(('MACD 处于%s：DIF=%.3f，DEA=%.3f。'
                          'MACD 是最常用的中期动能指标，红柱放大代表上涨动能在积累。'
                          % (state, dif, dea), TONE_UP if dif > dea else TONE_DOWN))
        d_mom.append(('MACD ' + ('多头' if dif > dea else '空头'), 5 if dif > dea else -5))
        (bull if dif > dea else bear)('MACD %s' % ('处于多头状态' if dif > dea else '处于空头状态'))

        zero = '零轴上方，属于强势区' if dif > 0 else '零轴下方，属于弱势区'
        mom_items.append(('DIF 位于%s。' % zero, TONE_UP if dif > 0 else TONE_DOWN))
        d_mom.append(('DIF 位置', 4 if dif > 0 else -4))
        (bull if dif > 0 else bear)(('MACD 快线在零轴上方' if dif > 0 else 'MACD 快线在零轴下方'))

        mx, mxago = cross_state(ind['dif'], ind['dea'])
        if mx == 'gold':
            mom_items.append(('MACD 上一次金叉发生在 %d 根 K 线之前%s。金叉指快线上穿慢线，'
                              '通常视为动能转强的偏多信号。'
                              % (mxago, '，属于刚发生的信号' if mxago <= 5 else ''), TONE_UP))
            d_mom.append(('MACD 金叉', 4))
            bull('MACD 出现金叉')
        elif mx == 'dead':
            mom_items.append(('MACD 上一次死叉发生在 %d 根 K 线之前%s。死叉指快线下穿慢线，'
                              '通常视为动能转弱的偏空信号。'
                              % (mxago, '，属于刚发生的信号' if mxago <= 5 else ''), TONE_DOWN))
            d_mom.append(('MACD 死叉', -4))
            bear('MACD 出现死叉')

        if i >= 2 and None not in (ind['hist'][i], ind['hist'][i - 1]):
            h_now, h_prev = ind['hist'][i], ind['hist'][i - 1]
            if h_now > h_prev and h_now > 0:
                mom_items.append(('MACD 红柱较上一根放大，上涨动能仍在增强。', TONE_UP))
                d_mom.append(('红柱放大', 3))
            elif h_now < h_prev and h_now < 0:
                mom_items.append(('MACD 绿柱较上一根放大，下跌动能仍在增强。', TONE_DOWN))
                d_mom.append(('绿柱放大', -3))
            elif h_now > 0 and h_now < h_prev:
                mom_items.append(('MACD 红柱开始缩短，上涨动能有所减弱。', TONE_WARN))
                d_mom.append(('红柱缩短', -2))
            elif h_now < 0 and h_now > h_prev:
                mom_items.append(('MACD 绿柱开始缩短，下跌动能有所减弱。', TONE_UP))
                d_mom.append(('绿柱缩短', 2))

    kk, dd, jj = ind['k'][i], ind['d'][i], ind['j'][i]
    if None not in (kk, dd):
        if kk > 80:
            mom_items.append(('KDJ 的 K=%.1f 进入超买区（>80）：短线涨得太快，'
                              '追高容易买在阶段高点。' % kk, TONE_WARN))
            d_mom.append(('KDJ 超买', -3))
        elif kk < 20:
            mom_items.append(('KDJ 的 K=%.1f 进入超卖区（<20）：短线跌得过多，'
                              '存在超跌反弹的条件。' % kk, TONE_UP))
            d_mom.append(('KDJ 超卖', 3))
            bull('KDJ 进入超卖区，具备超跌反弹条件')
        else:
            mom_items.append(('KDJ 的 K=%.1f 位于中性区间，短线没有极端信号。' % kk, TONE_FLAT))
        ks, kago = cross_state(ind['k'], ind['d'])
        if ks == 'gold' and kago <= 10:
            mom_items.append(('KDJ 在 %d 根 K 线前金叉，短线偏强。' % kago, TONE_UP))
            d_mom.append(('KDJ 金叉', 3))
            bull('KDJ 近期金叉')
        elif ks == 'dead' and kago <= 10:
            mom_items.append(('KDJ 在 %d 根 K 线前死叉，短线偏弱。' % kago, TONE_DOWN))
            d_mom.append(('KDJ 死叉', -3))
            bear('KDJ 近期死叉')

    r6, r12, r24 = ind['rsi6'][i], ind['rsi12'][i], ind['rsi24'][i]
    if r6 is not None:
        if r6 > 80:
            mom_items.append(('RSI6=%.1f 处于超买（>80），继续上行需要更多增量资金。' % r6,
                              TONE_WARN))
            d_mom.append(('RSI 超买', -4))
        elif r6 < 20:
            mom_items.append(('RSI6=%.1f 处于超卖（<20），短线跌势可能接近尾声。' % r6, TONE_UP))
            d_mom.append(('RSI 超卖', 4))
            bull('RSI6 进入超卖区')
        elif 45 <= r6 <= 65:
            mom_items.append(('RSI6=%.1f 位于 45-65 的良性区间，动能健康、不过热。' % r6,
                              TONE_UP))
            d_mom.append(('RSI 健康', 2))
        else:
            mom_items.append(('RSI6=%.1f 处于中性区间。' % r6, TONE_FLAT))
        mom_items.append(('RSI 6/12/24 日分别为 %s / %s / %s，'
                          '数值越大代表近期上涨力量占比越高。'
                          % (_num(r6, '', 1), _num(r12, '', 1), _num(r24, '', 1)), TONE_FLAT))

    cc = ind['cci'][i]
    if cc is not None:
        if cc > 100:
            mom_items.append(('CCI=%.0f 高于 100，属于强势区（但过高时也提示短线过热）。' % cc,
                              TONE_UP if cc < 200 else TONE_WARN))
            d_mom.append(('CCI 强势', 2))
        elif cc < -100:
            mom_items.append(('CCI=%.0f 低于 -100，属于弱势区，短线偏空。' % cc, TONE_DOWN))
            d_mom.append(('CCI 弱势', -2))
        else:
            mom_items.append(('CCI=%.0f 在 -100 到 100 之间，属常态波动。' % cc, TONE_FLAT))

    ww = ind['wr'][i]
    if ww is not None:
        if ww < 20:
            mom_items.append(('威廉指标 WR=%.1f（<20）说明价格贴近近期最高价，'
                              '强势但已偏热。' % ww, TONE_WARN))
        elif ww > 80:
            mom_items.append(('威廉指标 WR=%.1f（>80）说明价格贴近近期最低价，'
                              '弱势但已偏冷。' % ww, TONE_UP))
        else:
            mom_items.append(('威廉指标 WR=%.1f 处于中性区间。' % ww, TONE_FLAT))
    sections.append(('二、动量指标（MACD / KDJ / RSI / CCI / WR）', mom_items))

    # ================= 维度三：量能与资金 =================
    d_vol = []
    vol_items = []
    v_today = ind['vol'][i]
    v5, v20 = ind['vma5'][i], ind['vma20'][i]
    if v5 and v20:
        ratio = v5 / v20
        if ratio > 1.5:
            vol_items.append(('近 5 日均量是近 20 日均量的 %.2f 倍，属于明显放量，'
                              '说明参与资金在增加。' % ratio, TONE_WARN))
        elif ratio > 1.15:
            vol_items.append(('近 5 日均量是近 20 日均量的 %.2f 倍，温和放量，'
                              '资金关注度有所提升。' % ratio, TONE_FLAT))
        elif ratio < 0.7:
            vol_items.append(('近 5 日均量仅为近 20 日均量的 %.2f 倍，量能萎缩，'
                              '观望情绪较重。' % ratio, TONE_FLAT))
        elif ratio < 0.9:
            vol_items.append(('近 5 日均量是近 20 日均量的 %.2f 倍，量能小幅萎缩，'
                              '参与意愿一般。' % ratio, TONE_FLAT))
        else:
            vol_items.append(('近 5 日均量 / 近 20 日均量 = %.2f，量能平稳。' % ratio, TONE_FLAT))

    if v5 and v_today:
        tr = v_today / v5
        up_day = bars[i]['pct'] >= 0
        if tr > 1.5 and up_day:
            vol_items.append(('今日成交量为 5 日均量的 %.2f 倍且股价上涨，'
                              '「量价齐升」是最健康的状态。' % tr, TONE_UP))
            d_vol.append(('放量上涨', 5))
            bull('放量上涨，量价配合良好')
        elif tr > 1.5 and not up_day:
            vol_items.append(('今日放量下跌（为 5 日均量的 %.2f 倍），'
                              '说明卖盘主动出货，需要警惕。' % tr, TONE_DOWN))
            d_vol.append(('放量下跌', -5))
            bear('放量下跌，抛压较重')
        elif tr < 0.7 and not up_day:
            vol_items.append(('今日缩量下跌（为 5 日均量的 %.2f 倍），'
                              '抛压并不重，属于相对健康的回调。' % tr, TONE_UP))
            d_vol.append(('缩量回调', 3))
            bull('缩量回调，抛压有限')
        elif tr < 0.6 and up_day:
            vol_items.append(('今日缩量上涨，说明推动上涨的资金有限，'
                              '后续能否延续要看量能是否跟上。', TONE_WARN))
            d_vol.append(('缩量上涨', -1))
        else:
            vol_items.append(('今日成交量约为 5 日均量的 %.2f 倍，量能正常。' % tr, TONE_FLAT))

    ob, obma = ind['obv'][i], ind['obv_ma'][i]
    if ob is not None and obma is not None:
        if ob > obma:
            vol_items.append(('OBV 能量潮位于其 30 日均线之上，资金累计方向偏流入。', TONE_UP))
            d_vol.append(('OBV 走强', 3))
            bull('OBV 资金累计方向向上')
        else:
            vol_items.append(('OBV 能量潮位于其 30 日均线之下，资金累计方向偏流出。', TONE_DOWN))
            d_vol.append(('OBV 走弱', -3))
            bear('OBV 资金累计方向向下')

    if len(bars) >= 20:
        big_days = sum(1 for t in range(i - 19, i + 1)
                       if ind['vma20'][t] and ind['vol'][t] > ind['vma20'][t] * 1.3)
        vol_items.append(('近 20 根 K 线中有 %d 根明显放量（超 20 日均量 1.3 倍），'
                          '放量频率% s。' % (big_days, '偏高，波动可能较大' if big_days >= 8
                                          else '正常'), TONE_FLAT))

    turn = bars[i].get('turn')
    if turn:
        t60 = [b.get('turn') for b in bars[max(0, i - 59):i + 1] if b.get('turn')]
        if t60:
            avg_t = sum(t60) / len(t60)
            if avg_t:
                k = turn / avg_t
                vol_items.append(('今日换手率 %.2f%%，是近 60 日均值（%.2f%%）的 %.2f 倍，'
                                  '交投%s。' % (turn, avg_t, k,
                                             '明显活跃' if k > 1.6 else
                                             ('清淡' if k < 0.6 else '正常')),
                                 TONE_UP if k > 1.6 else TONE_FLAT))

    if flow:
        f0 = flow[-1]
        same_day = f0.get('d') == bars[i]['d']
        when = '今日' if same_day else '最近一个交易日（%s）' % f0.get('d', '')
        main = f0.get('main')
        if main is not None:
            vol_items.append(('%s主力资金（大单+超大单）净%s %s元。'
                              % (when, '流入' if main > 0 else '流出', _big(abs(main))),
                              TONE_UP if main > 0 else TONE_DOWN))
            if same_day:
                d_vol.append(('主力净流入' if main > 0 else '主力净流出',
                              3 if main > 0 else -3))
                (bull if main > 0 else bear)(
                    '主力资金净%s %s元' % ('流入' if main > 0 else '流出', _big(abs(main))))
        seg = [('超大单', f0.get('huge')), ('大单', f0.get('big')),
               ('中单', f0.get('mid')), ('小单', f0.get('small'))]
        seg_txt = '，'.join('%s %s%s' % (nm, '+' if (val or 0) >= 0 else '-',
                                        _big(abs(val or 0)))
                           for nm, val in seg if val is not None)
        if seg_txt:
            vol_items.append(('资金结构：%s。超大单和大单通常代表机构，'
                              '中小单更多代表散户。' % seg_txt, TONE_FLAT))
        if len(flow) >= 5:
            five = sum(r['main'] for r in flow[-5:] if r.get('main') is not None)
            vol_items.append(('近 5 个交易日主力资金合计净%s %s元。'
                              % ('流入' if five > 0 else '流出', _big(abs(five))),
                              TONE_UP if five > 0 else TONE_DOWN))
            d_vol.append(('5 日主力累计', 2 if five > 0 else -2))
            (bull if five > 0 else bear)(
                '近 5 日主力资金累计净%s' % ('流入' if five > 0 else '流出'))
            if len(flow) >= 20:
                twenty = sum(r['main'] for r in flow[-20:] if r.get('main') is not None)
                vol_items.append(('近 20 个交易日主力资金合计净%s %s元。'
                                  % ('流入' if twenty > 0 else '流出', _big(abs(twenty))),
                                  TONE_UP if twenty > 0 else TONE_DOWN))
    else:
        vol_items.append(('资金流数据暂不可用（该接口在部分网络环境下会被拦截），'
                          '下方结论未计入此项。', TONE_FLAT))
    sections.append(('三、量能与资金（成交量 / 换手 / 主力资金）', vol_items))

    # ================= 维度四：位置与成本 =================
    d_pos = []
    pos_items = []
    hi250, lo250 = ind['hi250'][i], ind['lo250'][i]
    hi60, lo60 = ind['hi60'][i], ind['lo60'][i]
    hi20, lo20 = ind['hi20'][i], ind['lo20'][i]

    pos = None
    if None not in (hi250, lo250) and hi250 > lo250:
        pos = (close - lo250) / (hi250 - lo250) * 100.0
        rng_word = cf['range']
        if pos > 85:
            pos_items.append(('现价处于%s区间的高位（%.0f%% 分位）：上方套牢盘少，'
                              '但获利盘丰厚，一旦转向容易引发获利了结。'
                              % (rng_word, pos), TONE_WARN))
            d_pos.append(('区间高位', -3))
        elif pos > 60:
            pos_items.append(('现价处于%s区间的 %.0f%% 分位，位置偏高但未极端。'
                              % (rng_word, pos), TONE_FLAT))
        elif pos > 40:
            pos_items.append(('现价处于%s区间的 %.0f%% 分位，位置居中。'
                              % (rng_word, pos), TONE_FLAT))
        elif pos > 20:
            pos_items.append(('现价处于%s区间的 %.0f%% 分位，位置偏低。'
                              % (rng_word, pos), TONE_UP))
            d_pos.append(('区间低位', 2))
        else:
            pos_items.append(('现价处于%s区间的低位（%.0f%% 分位）：'
                              '下跌空间相对有限，但也要注意是否属于弱势趋势股。'
                              % (rng_word, pos), TONE_UP))
            d_pos.append(('区间低位', 3))
            bull('价格处于长周期低位区间')
        pos_items.append(('%s区间：最高 %s，最低 %s，当前距高点 %s、距低点 %s。'
                          % (rng_word, _num(hi250), _num(lo250),
                             _num(_pct(close, hi250), '%'),
                             _num(_pct(close, lo250), '%')), TONE_FLAT))

    cost20 = vwap_cost(bars, 20)
    cost60 = vwap_cost(bars, 60)
    if cost20:
        dev = (close - cost20) / cost20 * 100.0
        pos_items.append(('近 20 根 K 线的成交量加权均价约 %s（可近似看作短线资金的'
                          '平均成本），现价在其%s %.2f%%。'
                          % (_num(cost20), '上方' if dev >= 0 else '下方', abs(dev)),
                          TONE_UP if dev >= 0 else TONE_DOWN))
        if dev > 12:
            pos_items.append(('现价明显高于短线平均成本，追高者占比大，'
                              '回撤时容易引发连锁止盈。', TONE_WARN))
            d_pos.append(('偏离短线成本过大', -3))
        elif dev < -8:
            pos_items.append(('现价明显低于短线平均成本，短期套牢盘较多，'
                              '反弹到成本区附近会遇到解套卖压。', TONE_WARN))
            d_pos.append(('低于短线成本较多', -2))
        else:
            d_pos.append(('贴近市场成本', 2))
    if cost60:
        pos_items.append(('近 60 根 K 线的成交量加权均价约 %s，可作为中期成本参考。'
                          % _num(cost60), TONE_FLAT))

    b20 = ind['bias20'][i]
    if b20 is not None:
        if b20 > 10:
            pos_items.append(('乖离率 BIAS20=%.2f%%（>10%%），价格偏离 20 日均线过远，'
                              '短期有回归均线的需求。' % b20, TONE_WARN))
            d_pos.append(('乖离率过高', -3))
        elif b20 < -10:
            pos_items.append(('乖离率 BIAS20=%.2f%%（<-10%%），超跌明显，'
                              '技术上有向均线靠拢的动能。' % b20, TONE_UP))
            d_pos.append(('乖离率超跌', 3))
            bull('乖离率显示超跌，存在向均线回归的动能')
        else:
            pos_items.append(('乖离率 BIAS20=%.2f%%，价格与 20 日均线的距离正常。' % b20,
                              TONE_FLAT))

    if hi60 and lo60:
        pos_items.append(('近 60 根 K 线区间：最高 %s，最低 %s。'
                          % (_num(hi60), _num(lo60)), TONE_FLAT))
    pos_items.append(('说明：以上「近 N 根 K 线」均按当前所选周期计算（%s）。'
                      % cf['range'], TONE_FLAT))
    sections.append(('四、位置与持仓成本', pos_items))

    # ================= 维度五：风险与波动 =================
    risk_items = []
    risk_score = 50.0
    atr14 = ind['atr14'][i]
    ann = None
    if atr14 is not None and close:
        atr_pct = atr14 / close * 100.0
        risk_items.append(('ATR(14)=%.2f，相当于股价的 %.2f%%：'
                           '这是%s平均波动的幅度参考，可用来估算止损距离。'
                           % (atr14, atr_pct, cf['bar']), TONE_FLAT))
    if len(bars) >= 21:
        rets = []
        for t in range(n - 20, n):
            if bars[t - 1]['c']:
                rets.append((bars[t]['c'] - bars[t - 1]['c']) / bars[t - 1]['c'])
        if len(rets) >= 10:
            m = sum(rets) / len(rets)
            sd = math.sqrt(sum((x - m) ** 2 for x in rets) / len(rets))
            ann = sd * math.sqrt(cf['ann']) * 100.0
            if ann > 50:
                vtxt = '波动较大，仓位不宜过重。'
            elif ann > 28:
                vtxt = '波动中等。'
            elif ann > 18:
                vtxt = '波动偏小，走势相对稳健。'
            else:
                vtxt = '波动很小，属于典型的低波动品种。'
            risk_items.append(('按最近 20 根 K 线折算，年化波动率约 %.1f%%。%s'
                               % (ann, vtxt),
                               TONE_WARN if ann > 50 else TONE_FLAT))
    if None not in (ind['boll_up'][i], ind['boll_dn'][i], ind['boll_mid'][i]):
        bu, bm, bd = ind['boll_up'][i], ind['boll_mid'][i], ind['boll_dn'][i]
        bw = (bu - bd) / bm * 100.0 if bm else 0.0
        prev_bw = None
        if i >= 20:
            u0, m0, d0 = ind['boll_up'][i - 20], ind['boll_mid'][i - 20], ind['boll_dn'][i - 20]
            if None not in (u0, m0, d0) and m0:
                prev_bw = (u0 - d0) / m0 * 100.0
        rngn = bu - bd
        pb = (close - bd) / rngn * 100.0 if rngn else 50.0
        if close > bu:
            risk_items.append(('价格已冲出布林上轨（布林位置 %.0f%%），短期偏热，'
                               '常见于强势股加速段，但也容易快速回落。' % pb, TONE_WARN))
            d_mom.append(('突破布林上轨', -2))
        elif close < bd:
            risk_items.append(('价格跌破布林下轨（布林位置 %.0f%%），极度弱势，'
                               '按均值回归思路存在修复机会，但需等企稳信号。' % pb, TONE_WARN))
        elif close >= bm:
            risk_items.append(('价格在布林中轨之上（布林位置 %.0f%%），处于强势半区，'
                               '中轨 %s 可视为短期支撑。' % (pb, _num(bm)), TONE_UP))
            d_mom.append(('布林中轨上方', 2))
        else:
            risk_items.append(('价格在布林中轨之下（布林位置 %.0f%%），处于弱势半区，'
                               '中轨 %s 是上方第一道压力。' % (pb, _num(bm)), TONE_DOWN))
            d_mom.append(('布林中轨下方', -2))
        band_txt = ''
        if prev_bw:
            if bw < prev_bw * 0.85:
                band_txt = '带宽由 %.1f%% 收窄至 %.1f%%，波动收敛，往往预示变盘临近（方向未知，' \
                           '通常等突破方向明确再动手更稳妥）。' % (prev_bw, bw)
            elif bw > prev_bw * 1.2:
                band_txt = '带宽由 %.1f%% 扩张至 %.1f%%，波动放大，趋势延续的概率提高。' \
                           % (prev_bw, bw)
        risk_items.append(('布林上轨 %s / 中轨 %s / 下轨 %s，带宽 %.2f%%。%s'
                           % (_num(bu), _num(bm), _num(bd), bw, band_txt), TONE_FLAT))

    max_dd = None
    if len(bars) >= 121:
        seg = [b['c'] for b in bars[i - 120:i + 1]]
        peak, dd = seg[0], 0.0
        for v in seg:
            peak = max(peak, v)
            if peak:
                dd = min(dd, (v - peak) / peak * 100.0)
        max_dd = dd
        risk_items.append(('近 120 根 K 线最大回撤 %.2f%%：'
                           '衡量这段时间里从最高点回落的幅度，可用于评估持有体验。'
                           % abs(max_dd), TONE_WARN if abs(max_dd) > 35 else TONE_FLAT))
        risk_score += (abs(max_dd) - 20.0) * 0.6
    if ann is not None:
        risk_score += (ann - 30.0) * 0.9
    risk_score = _clamp(risk_score, 3, 97)
    risk_level = ('风险偏高' if risk_score >= 68 else
                  ('风险中等' if risk_score >= 45 else '风险偏低'))
    sections.append(('五、波动与风险', risk_items))

    # ================= 六、K 线形态与缺口 =================
    pat_items = []
    pats = candle_pattern(bars, i)
    if pats:
        for name, desc, tone in pats:
            pat_items.append(('%s：%s' % (name, desc), tone))
    else:
        pat_items.append(('最新 K 线没有出现典型形态（十字星 / 锤子线 / 吞没等），'
                          '属于常规走势。', TONE_FLAT))
    gaps = measure_gaps(bars, i)
    if gaps:
        for kind, lo, hi in gaps[:3]:
            if lo <= close <= hi:
                pat_items.append(('%s %s ~ %s：现价正处于缺口区间内，'
                                  '该位置多空争夺会比较激烈。'
                                  % (kind, _num(lo), _num(hi)), TONE_WARN))
            elif hi < close:
                pat_items.append(('%s %s ~ %s：位于现价下方，'
                                  '缺口下沿常充当支撑。' % (kind, _num(lo), _num(hi)), TONE_UP))
            else:
                pat_items.append(('%s %s ~ %s：位于现价上方，'
                                  '缺口上沿常构成压力。' % (kind, _num(lo), _num(hi)), TONE_DOWN))
    else:
        pat_items.append(('近 60 根 K 线内没有未回补的跳空缺口。', TONE_FLAT))
    sections.append(('六、K 线形态与缺口', pat_items))

    # ================= 维度汇总 =================
    dims = [
        _dim('趋势', '看价格与均线、ADX 的关系', d_trend, 0.35),
        _dim('动量', '看 MACD / KDJ / RSI 等动能指标', d_mom, 0.25),
        _dim('量能', '看成交量、换手与主力资金', d_vol, 0.15),
        _dim('位置', '看年内分位与持仓成本偏离', d_pos, 0.25),
    ]
    overall = sum(d['score'] * d['weight'] for d in dims) / sum(d['weight'] for d in dims)
    overall = _clamp(overall, 1, 99)
    if overall >= 70:
        level, tone = '偏强', TONE_UP
    elif overall >= 58:
        level, tone = '中性偏强', TONE_UP
    elif overall >= 43:
        level, tone = '中性', TONE_FLAT
    elif overall >= 30:
        level, tone = '中性偏弱', TONE_DOWN
    else:
        level, tone = '偏弱', TONE_DOWN

    verdict = ('技术面综合判断：%s。%s'
               % (level, '多头结构较完整，回踩不破关键均线时趋势有望延续。'
                  if overall >= 70 else
                  ('结构偏多但仍有瑕疵，建议等回踩确认或突破确认再行动。'
                   if overall >= 58 else
                   ('多空力量接近均衡，方向未明，区间内高抛低吸或观望更稳妥。'
                    if overall >= 43 else
                    ('空头占据主动，反弹到压力位附近更容易受阻，'
                     '等待企稳信号比抢反弹更重要。' if overall >= 30 else
                     '趋势与动能均偏弱，不宜逆势介入，先以观察风险为主。')))))

    summary = ('技术面综合评分 %.0f / 100（%s）。看多信号 %d 项，看空信号 %d 项。'
               % (overall, level, len(bulls), len(bears)))
    if bulls:
        summary += '主要支撑：' + '；'.join(bulls[:3]) + '。'
    if bears:
        summary += '主要拖累：' + '；'.join(bears[:3]) + '。'

    # ================= 关键价位阶梯 =================
    raw_levels = []
    for name, val in (('MA5', ma5), ('MA10', ma10), ('MA20', ma20), ('MA60', ma60),
                      ('MA120', ma120), ('布林上轨', ind['boll_up'][i]),
                      ('布林中轨', ind['boll_mid'][i]), ('布林下轨', ind['boll_dn'][i]),
                      ('近 20 根高点', hi20), ('近 20 根低点', lo20),
                      ('近 60 根高点', hi60), ('近 60 根低点', lo60),
                      (cf['hi250'], hi250), (cf['lo250'], lo250),
                      ('近 20 根成本', cost20), ('近 60 根成本', cost60)):
        if val is None:
            continue
        raw_levels.append((name, val))
    for kind, lo, hi in gaps[:2]:
        raw_levels.append(('缺口上沿' if hi > close else '缺口下沿',
                           hi if hi > close else lo))

    # 同一价位往往被多个指标重复命中（如 60 根低点 = 250 根低点），合并显示
    merged = []
    tol = abs(close) * 0.004 if close else 0.0
    for name, val in raw_levels:
        hit = None
        for item in merged:
            if abs(item[1] - val) <= tol:
                hit = item
                break
        if hit is None:
            merged.append([name, val])
        elif name not in hit[0]:
            hit[0] = hit[0] + ' / ' + name
    levels = [(n, v) for n, v in merged]

    supports = sorted([x for x in levels if x[1] < close], key=lambda t: -t[1])[:4]
    resists = sorted([x for x in levels if x[1] > close], key=lambda t: t[1])[:4]

    plain = ('白话版：%s ' % verdict.split('：', 1)[-1])
    if supports:
        plain += '下方 %s 是最近的支撑（跌到那里容易有买盘），' % _num(supports[0][1])
    if resists:
        plain += '上方 %s 是最近的阻力（涨到那里容易有卖盘）。' % _num(resists[0][1])
    if risk_score >= 68:
        plain += '当前波动偏大，参与时更需要控制仓位。'
    elif risk_score >= 45:
        plain += '当前波动中等，操作前先想好止损位。'
    elif risk_score >= 30:
        plain += '当前波动偏小，走势相对平稳。'
    else:
        plain += '当前波动很小，属于低波动品种。'

    # ================= 情景应对 =================
    scenarios = []
    if resists:
        r0 = resists[0]
        scenarios.append((
            '向上突破',
            '若能放量站稳 %s（%s）之上' % (_num(r0[1]), r0[0]),
            '说明上方压力被有效消化，中期空间打开，可视为趋势延续的确认信号。',
            TONE_UP))
    if supports:
        s0 = supports[0]
        scenarios.append((
            '回踩确认',
            '若回踩 %s（%s）附近止跌企稳' % (_num(s0[1]), s0[0]),
            '这是趋势股常见的上车/加仓位置；若跌破且不能快速收回，则视为结构走坏。',
            TONE_UP))
        s_last = supports[-1]
        scenarios.append((
            '跌破关键位',
            '若有效跌破 %s（%s）' % (_num(s_last[1]), s_last[0]),
            '说明这一段上涨或震荡结构被破坏，应先降低仓位、控制风险，而不是继续摊薄成本。',
            TONE_DOWN))
    if risk_items:
        scenarios.append((
            '波动参考',
            '按 ATR 估算，单日正常波动约 %s（%.2f%%）'
            % (_num(atr14), (atr14 / close * 100.0) if (atr14 and close) else 0),
            '止损位可以放在关键支撑下方 1 个 ATR 左右，避免被正常波动扫掉。',
            TONE_FLAT))

    return {
        'score': overall,
        'level': level,
        'level_tone': tone,
        'verdict': verdict,
        'summary': summary,
        'plain': plain,
        'dims': dims,
        'risk': {'score': risk_score, 'level': risk_level, 'items': risk_items},
        'bulls': bulls,
        'bears': bears,
        'sections': sections,
        'supports': supports,
        'resists': resists,
        'scenarios': scenarios,
        'parts': [('+ ' + t, 1) for t in bulls] + [('- ' + t, -1) for t in bears],
        'meta': {
            'bars': n,
            'last_date': bars[i]['d'],
            'pos': pos,
            'max_dd': max_dd,
            'ann_vol': ann,
            'bench': bench_name,
        },
    }
