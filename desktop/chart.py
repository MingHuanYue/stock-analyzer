# -*- coding: utf-8 -*-
"""图表引擎：K 线与分时图，纯 tkinter Canvas 绘制（无第三方绘图库依赖）。

K 线图：蜡烛 + MA5/10/20/60 + 布林带 + 成交量 + MACD/KDJ/RSI 副图
        滚轮缩放、拖拽平移、十字光标联动数据
分时图：价格线 + 均价线 + 昨收基准 + 成交量 + 左右双轴（价格 / 涨跌幅）
"""
import tkinter as tk
import tkinter.font as tkfont

import analysis as an

BG = '#0e1218'
PANEL = '#151a23'
PANEL2 = '#1c2330'
PANEL3 = '#222a38'
BORDER = '#2a3345'
GRID = '#1e2532'
TEXT = '#e2e8f2'
TEXT_DIM = '#94a1b5'
TEXT_MUTE = '#5f6b7d'
UP = '#f0453a'
DOWN = '#12b886'
FLAT = '#8b96a8'
ACCENT = '#4c8dff'
WARN = '#f2b544'

FONT = 'Microsoft YaHei UI'
FONT_NUM = 'Consolas'

MA_STYLE = (('ma5', 'MA5', '#f5a623'), ('ma10', 'MA10', '#4c8dff'),
            ('ma20', 'MA20', '#b06bd9'), ('ma60', 'MA60', '#3fbfa0'))


def pick_font(root, cands, fallback='TkDefaultFont'):
    try:
        fams = set(tkfont.families(root))
    except Exception:                                     # noqa: BLE001
        return fallback
    for c in cands:
        if c in fams:
            return c
    return fallback


def fmt(v, digits=2, suffix=''):
    if v is None:
        return '—'
    try:
        return ('%.' + str(digits) + 'f%s') % (v, suffix)
    except (TypeError, ValueError):
        return str(v)


def fmt_signed(v, digits=2, suffix=''):
    if v is None:
        return '—'
    try:
        return ('%+.' + str(digits) + 'f%s') % (v, suffix)
    except (TypeError, ValueError):
        return str(v)


class KLineChart(tk.Canvas):
    def __init__(self, master, **kw):
        super().__init__(master, bg=PANEL, highlightthickness=0, bd=0, **kw)
        self.mode = 'kline'          # kline | trend
        self.bars = []
        self.ind = None
        self.trend = None
        self.title = ''
        self.sub = 'MACD'
        self.view_start = 0
        self.view_count = 120
        self.hover = None
        self._drag = None
        self._fonts_cache = None

        self.bind('<Configure>', lambda _e: self.redraw())
        self.bind('<Motion>', self._on_motion)
        self.bind('<Leave>', self._on_leave)
        self.bind('<MouseWheel>', self._on_wheel)
        self.bind('<Button-1>', self._on_press)
        self.bind('<B1-Motion>', self._on_drag)
        self.bind('<ButtonRelease-1>', self._on_release)

    # ---------------- 字体与几何 ----------------
    def _fonts(self):
        if self._fonts_cache is None:
            fam = pick_font(self, [FONT, 'Microsoft YaHei', 'SimHei', 'Segoe UI'])
            mono = pick_font(self, [FONT_NUM, 'Courier New'], 'TkFixedFont')
            self._fonts_cache = (
                tkfont.Font(family=fam, size=9),                       # f9 标签
                tkfont.Font(family=mono, size=9),                      # fm 数字
                tkfont.Font(family=fam, size=10, weight='bold'),       # fb 标题
            )
        return self._fonts_cache

    @property
    def axis_w(self):
        return self._fonts()[1].measure('8888.88') + 20

    # ---------------- 数据入口 ----------------
    def set_kline(self, bars, ind, title=''):
        self.mode = 'kline'
        self.bars = bars
        self.ind = ind
        self.title = title
        self.hover = None
        self.view_count = max(30, min(120, len(bars)))
        self.view_start = max(0, len(bars) - self.view_count)
        self.redraw()

    def set_trend(self, preclose, pts, title=''):
        self.mode = 'trend'
        self.trend = (preclose, pts)
        self.title = title
        self.hover = None
        self.redraw()

    def set_sub(self, which):
        self.sub = which
        self.redraw()

    def latest_zoom(self):
        return self.view_count

    # ---------------- 交互 ----------------
    def _on_leave(self, _e):
        if self.hover is not None:
            self.hover = None
            self.redraw()

    def _on_wheel(self, e):
        if self.mode != 'kline' or not self.bars:
            return
        total = len(self.bars)
        old = self.view_count
        step = max(1, int(old * 0.15))
        new = max(20, min(old - step if e.delta > 0 else old + step, total))
        if new == old:
            return
        anchor = self.hover if self.hover is not None else self.view_start + old // 2
        ratio = (anchor - self.view_start) / float(old)
        self.view_count = new
        self.view_start = int(anchor - ratio * new)
        self._clamp()
        self.redraw()

    def _on_press(self, e):
        self._drag = (e.x, self.view_start)

    def _on_release(self, _e):
        self._drag = None

    def _on_drag(self, e):
        if self.mode != 'kline' or not self._drag or not self.bars:
            return
        x0, x1, step, _ = self._plot()
        if step <= 0:
            return
        px, vs = self._drag
        shift = int(round((px - e.x) / step))
        if shift:
            self.view_start = vs + shift
            self._clamp()
            self._drag = (e.x, vs)
            self.hover = None
            self.redraw()

    def _on_motion(self, e):
        if self.winfo_width() < 80 or self.winfo_height() < 80:
            return
        idx = None
        if self.mode == 'trend':
            pre, pts = self.trend
            x0, x1, step, _ = self._trend_geom()
            if step > 0 and x0 - step <= e.x <= x1 + step:
                idx = max(0, min(len(pts) - 1, int((e.x - x0) / step + 0.5)))
        elif self.bars:
            x0, x1, step, _top = self._plot()
            if step > 0 and x0 - step <= e.x <= x1 + step:
                idx = max(0, min(len(self.bars) - 1,
                                 self.view_start + int((e.x - x0) / step)))
        if idx != self.hover:
            self.hover = idx
            self.redraw()

    def _clamp(self):
        total = len(self.bars)
        self.view_count = max(1, min(self.view_count, total))
        self.view_start = max(0, min(self.view_start, total - self.view_count))

    def _plot(self):
        w = self.winfo_width()
        x0, x1 = 10, w - self.axis_w
        step = (x1 - x0) / float(max(1, self.view_count))
        return x0, x1, step, 26

    def _trend_geom(self):
        w = self.winfo_width()
        pre, pts = self.trend
        x0, x1 = 60, w - self.axis_w
        step = (x1 - x0) / float(max(1, len(pts) - 1))
        return x0, x1, step, pre

    # ---------------- 绘制入口 ----------------
    def redraw(self):
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 90 or h < 90:
            return
        try:
            if self.mode == 'trend':
                self._draw_trend(w, h)
            else:
                self._draw_kline(w, h)
        except Exception as exc:                          # noqa: BLE001
            self.create_text(w / 2, h / 2, text='绘图异常：%s' % exc,
                             fill='#f0453a', font=self._fonts()[0])

    # ---------------- K 线 ----------------
    def _draw_kline(self, w, h):
        bars, ind = self.bars, self.ind
        f9, fm, fb = self._fonts()
        if not bars or not ind:
            self.create_text(w / 2, h / 2, text='暂无数据', fill=TEXT_MUTE, font=f9)
            return

        x0, x1, step, top = self._plot()
        bottom = h - 20
        avail = bottom - top
        mh = int(avail * 0.58)
        vh = int(avail * 0.14)
        sh = avail - mh - vh - 16
        my0, my1 = top, top + mh
        vy0, vy1 = my1 + 8, my1 + 8 + vh
        sy0, sy1 = vy1 + 8, vy1 + 8 + sh

        s = self.view_start
        e = min(len(bars), s + self.view_count)
        vis = bars[s:e]
        if not vis:
            return
        n = len(vis)
        self.view_count = n
        step = (x1 - x0) / float(n)

        def xc(i):
            return x0 + step * (i - s + 0.5)

        # 价格区间（含均线与布林带）
        lo = min(b['l'] for b in vis)
        hi = max(b['h'] for b in vis)
        for key, _n, _c in MA_STYLE:
            for i in range(s, e):
                v = ind[key][i]
                if v is not None:
                    lo, hi = min(lo, v), max(hi, v)
        for v in (ind['boll_up'][e - 1], ind['boll_dn'][e - 1]):
            if v is not None:
                lo, hi = min(lo, v), max(hi, v)
        if hi <= lo:
            hi = lo + 1.0
        pad = (hi - lo) * 0.06
        lo, hi = lo - pad, hi + pad

        def ym(p):
            return my1 - (p - lo) / (hi - lo) * (my1 - my0)

        # 横向网格 + 右侧价格刻度
        for k in range(5):
            y = my0 + (my1 - my0) * k / 4.0
            self.create_line(x0, y, x1, y, fill=GRID)
            self.create_text(x1 + 6, y, text=fmt(hi - (hi - lo) * k / 4.0, 2),
                             anchor='w', fill=TEXT_MUTE, font=fm)

        vmax = (max(b['v'] for b in vis) or 1) * 1.15

        def yv(v):
            return vy1 - v / vmax * (vy1 - vy0)

        # 蜡烛 + 成交量
        bw = max(1.0, min(step * 0.72, 18))
        for i in range(s, e):
            b = bars[i]
            col = UP if b['pct'] >= 0 else DOWN
            x = xc(i)
            self.create_line(x, ym(b['h']), x, ym(b['l']), fill=col)
            yo, yc = ym(b['o']), ym(b['c'])
            t_, b_ = min(yo, yc), max(yo, yc)
            if b_ - t_ < 1.0:
                b_ = t_ + 1.0
            self.create_rectangle(x - bw / 2, t_, x + bw / 2, b_, fill=col, outline=col)
            self.create_rectangle(x - bw / 2, yv(0), x + bw / 2, yv(b['v']),
                                  fill=col, outline=col)

        # 布林带（虚线，先画，避免压住均线）
        for key in ('boll_up', 'boll_dn'):
            pts = []
            for i in range(s, e):
                v = ind[key][i]
                if v is not None:
                    pts.extend((xc(i), ym(v)))
            if len(pts) >= 4:
                self.create_line(*pts, fill='#39435a', dash=(3, 3))

        # 均线
        for key, _n, col in MA_STYLE:
            pts = []
            for i in range(s, e):
                v = ind[key][i]
                if v is not None:
                    pts.extend((xc(i), ym(v)))
            if len(pts) >= 4:
                self.create_line(*pts, fill=col, width=1)

        # 量能均线
        pts = []
        for i in range(s, e):
            v = ind['vma5'][i]
            if v is not None:
                pts.extend((xc(i), yv(v)))
        if len(pts) >= 4:
            self.create_line(*pts, fill='#c9a227', width=1)

        # 成交量刻度与标题
        self.create_line(x0, vy0, x1, vy0, fill=BORDER)
        self.create_text(x0 + 2, vy0 - 9, text='成交量', anchor='w',
                         fill=TEXT_MUTE, font=f9)
        self.create_text(x1 + 6, vy1, text=an._vol_hand(vmax), anchor='w',
                         fill=TEXT_MUTE, font=fm)

        # 副图
        self.create_line(x0, sy0, x1, sy0, fill=BORDER)
        self._draw_sub(s, e, xc, sy0, sy1, x0, x1, fm, f9)

        # 日期刻度
        cnt = max(2, min(7, int((x1 - x0) / 95)))
        for k in range(cnt):
            i = s + int((n - 1) * k / float(cnt - 1))
            i = max(s, min(e - 1, i))
            label = bars[i]['d']
            if len(label) == 10 and self.view_count > 70:
                label = label[2:]
            self.create_text(xc(i), bottom + 9, text=label, anchor='center',
                             fill=TEXT_MUTE, font=fm)

        # 图例 + 标题
        self._draw_legend(x0, x1, my0, s, e, fm, fb)

        # 十字光标
        if self.hover is not None and s <= self.hover < e:
            self._draw_cross_kline(self.hover, xc(self.hover), my0, my1, vy0, vy1,
                                   sy0, sy1, x0, x1, bottom, ym, fm, f9)

    def _draw_legend(self, x0, x1, my0, s, e, fm, fb):
        ind = self.ind
        i = self.hover if (self.hover is not None and s <= self.hover < e) else e - 1
        y = my0 - 13
        x = x0 + 2
        for key, name, col in MA_STYLE:
            t = '%s:%s' % (name, fmt(an.value_at(ind[key], i), 2))
            self.create_text(x, y, text=t, anchor='w', fill=col, font=fm)
            x += fm.measure(t) + 12
        if self.title:
            self.create_text(x1, y, text=self.title, anchor='e', fill=TEXT_DIM, font=fb)

    def _draw_cross_kline(self, i, x, my0, my1, vy0, vy1, sy0, sy1, x0, x1,
                          bottom, ym, fm, f9):
        b = self.bars[i]
        f9 = f9
        self.create_line(x, my0, x, sy1, fill='#8794a8', dash=(4, 3))
        yc = ym(b['c'])
        self.create_line(x0, yc, x1, yc, fill='#8794a8', dash=(4, 3))

        col = UP if b['pct'] >= 0 else DOWN
        txt = fmt(b['c'], 2)
        tw = fm.measure(txt) + 14
        self.create_rectangle(x1, yc - 9, x1 + tw, yc + 9, fill=PANEL3, outline=BORDER)
        self.create_text(x1 + 7, yc, text=txt, anchor='w', fill=col, font=fm)

        txt = b['d']
        tw = fm.measure(txt) + 16
        cx = min(max(x, x0 + tw / 2), x1 - tw / 2)
        self.create_rectangle(cx - tw / 2, bottom + 1, cx + tw / 2, bottom + 18,
                              fill=PANEL3, outline=BORDER)
        self.create_text(cx, bottom + 9, text=txt, fill=TEXT, font=fm)

        ind = self.ind
        rows = [
            ('日期', b['d'], TEXT),
            ('开盘', fmt(b['o'], 2), UP if b['pct'] >= 0 else DOWN),
            ('最高', fmt(b['h'], 2), UP),
            ('最低', fmt(b['l'], 2), DOWN),
            ('收盘', fmt(b['c'], 2), col),
            ('涨跌', fmt_signed(b['pct'], 2, '%'), col),
            ('振幅', fmt(b['amp'], 2, '%'), TEXT_DIM),
            ('成交量', an._vol_hand(b['v']), TEXT),
            ('成交额', an._big(b['amt']), TEXT),
            ('换手率', fmt(b['turn'], 2, '%'), TEXT_DIM),
        ]
        lw = max(fm.measure(k) for k, _v, _c in rows) + 10
        vw = max(fm.measure(str(v)) for _k, v, _c in rows)
        bw = lw + vw + 18
        bh = 16 * (len(rows) + 1) + 12
        bx, by = x0 + 6, my0 + 6
        self.create_rectangle(bx, by, bx + bw, by + bh, fill='#0b0f15', outline=BORDER)
        ty = by + 10
        for k, v, c in rows:
            self.create_text(bx + 9, ty, text=k, anchor='w', fill=TEXT_MUTE, font=f9)
            self.create_text(bx + 9 + lw, ty, text=str(v), anchor='w', fill=c, font=fm)
            ty += 16
        ma_txt = '  '.join('%s %s' % (n, fmt(an.value_at(ind[k], i), 2))
                           for k, n, _c in MA_STYLE)
        self.create_text(bx + 9, ty, text=ma_txt, anchor='w', fill=TEXT_DIM, font=fm)

    def _draw_sub(self, s, e, xc, sy0, sy1, x0, x1, fm, f9):
        ind = self.ind
        title = {'MACD': 'MACD(12,26,9)', 'KDJ': 'KDJ(9,3,3)', 'RSI': 'RSI(6,12,24)'}[self.sub]
        self.create_text(x0 + 2, sy0 - 9, text=title, anchor='w', fill=TEXT_MUTE, font=f9)
        i = self.hover if (self.hover is not None and s <= self.hover < e) else e - 1

        if self.sub == 'MACD':
            vals = [ind[k][j] for j in range(s, e) for k in ('dif', 'dea', 'hist')
                    if ind[k][j] is not None]
            if not vals:
                return
            m = (max(abs(v) for v in vals) or 1) * 1.15
            zero = (sy0 + sy1) / 2.0

            def y(v):
                return zero - v / m * ((sy1 - sy0) / 2.0)

            self.create_line(x0, y(0), x1, y(0), fill=GRID)
            bw = max(1.0, min((xc(1) - xc(0)) * 0.5, 9)) if e - s > 1 else 3
            for j in range(s, e):
                h = ind['hist'][j]
                if h is None:
                    continue
                col = UP if h >= 0 else DOWN
                self.create_rectangle(xc(j) - bw / 2, min(y(h), y(0)),
                                      xc(j) + bw / 2, max(y(h), y(0)),
                                      fill=col, outline=col)
            for key, col in (('dif', '#f5a623'), ('dea', '#4c8dff')):
                pts = []
                for j in range(s, e):
                    v = ind[key][j]
                    if v is not None:
                        pts.extend((xc(j), y(v)))
                if len(pts) >= 4:
                    self.create_line(*pts, fill=col, width=1)
            self.create_text(x1, sy0 - 9,
                             text='DIF %s   DEA %s   MACD %s'
                                  % (fmt(an.value_at(ind['dif'], i), 3),
                                     fmt(an.value_at(ind['dea'], i), 3),
                                     fmt(an.value_at(ind['hist'], i), 3)),
                             anchor='e', fill=TEXT_DIM, font=fm)

        elif self.sub == 'KDJ':
            vals = [ind[k][j] for j in range(s, e) for k in ('k', 'd', 'j')
                    if ind[k][j] is not None]
            if not vals:
                return
            lo = min(min(vals), -10.0)
            hi = max(max(vals), 110.0)
            rng = (hi - lo) or 1

            def y(v):
                return sy1 - (v - lo) / rng * (sy1 - sy0)

            for lv in (20, 50, 80):
                self.create_line(x0, y(lv), x1, y(lv), fill=GRID)
            for key, col in (('k', '#f5a623'), ('d', '#4c8dff'), ('j', '#b06bd9')):
                pts = []
                for j in range(s, e):
                    v = ind[key][j]
                    if v is not None:
                        pts.extend((xc(j), y(v)))
                if len(pts) >= 4:
                    self.create_line(*pts, fill=col, width=1)
            self.create_text(x1, sy0 - 9,
                             text='K %s   D %s   J %s'
                                  % (fmt(an.value_at(ind['k'], i), 2),
                                     fmt(an.value_at(ind['d'], i), 2),
                                     fmt(an.value_at(ind['j'], i), 2)),
                             anchor='e', fill=TEXT_DIM, font=fm)

        else:
            vals = [ind[k][j] for j in range(s, e) for k in ('rsi6', 'rsi12', 'rsi24')
                    if ind[k][j] is not None]
            if not vals:
                return
            lo, hi = 0.0, 100.0

            def y(v):
                return sy1 - (v - lo) / (hi - lo) * (sy1 - sy0)

            for lv in (30, 50, 70):
                self.create_line(x0, y(lv), x1, y(lv), fill=GRID)
            for key, col in (('rsi6', '#f5a623'), ('rsi12', '#4c8dff'), ('rsi24', '#3fbfa0')):
                pts = []
                for j in range(s, e):
                    v = ind[key][j]
                    if v is not None:
                        pts.extend((xc(j), y(v)))
                if len(pts) >= 4:
                    self.create_line(*pts, fill=col, width=1)
            self.create_text(x1, sy0 - 9,
                             text='RSI6 %s   RSI12 %s   RSI24 %s'
                                  % (fmt(an.value_at(ind['rsi6'], i), 2),
                                     fmt(an.value_at(ind['rsi12'], i), 2),
                                     fmt(an.value_at(ind['rsi24'], i), 2)),
                             anchor='e', fill=TEXT_DIM, font=fm)

    # ---------------- 分时 ----------------
    def _draw_trend(self, w, h):
        f9, fm, fb = self._fonts()
        if not self.trend:
            self.create_text(w / 2, h / 2, text='暂无分时数据', fill=TEXT_MUTE, font=f9)
            return
        pre, pts = self.trend
        if not pts or not pre:
            self.create_text(w / 2, h / 2, text='暂无分时数据', fill=TEXT_MUTE, font=f9)
            return
        x0, x1, step, _ = self._trend_geom()
        top, bottom = 26, h - 20
        avail = bottom - top
        mh = int(avail * 0.70)
        my0, my1 = top, top + mh
        vy0, vy1 = my1 + 8, bottom

        prices = [p['c'] for p in pts] + [p['avg'] for p in pts]
        dev = max(abs(max(prices) - pre), abs(pre - min(prices))) * 1.08
        dev = max(dev, pre * 0.003)
        hi, lo = pre + dev, pre - dev

        def ym(p):
            return my1 - (p - lo) / (hi - lo) * (my1 - my0)

        def xc(i):
            return x0 + step * i

        # 网格 + 左右刻度（右价格 / 左涨跌幅）
        for k in range(5):
            y = my0 + (my1 - my0) * k / 4.0
            price = hi - (hi - lo) * k / 4.0
            self.create_line(x0, y, x1, y, fill=GRID)
            self.create_text(x1 + 6, y, text=fmt(price, 2), anchor='w',
                             fill=TEXT_MUTE, font=fm)
            pct = (price - pre) / pre * 100.0
            self.create_text(x0 - 6, y, text=fmt_signed(pct, 2, '%'), anchor='e',
                             fill=UP if pct > 0 else (DOWN if pct < 0 else TEXT_MUTE),
                             font=fm)
        # 昨收基准线
        self.create_line(x0, ym(pre), x1, ym(pre), fill='#5f6b7d', dash=(5, 4))

        vmax = (max(p['v'] for p in pts) or 1) * 1.15

        def yv(v):
            return vy1 - v / vmax * (vy1 - vy0)

        for i, p in enumerate(pts):
            col = UP if p['c'] >= pre else DOWN
            self.create_line(xc(i), yv(0), xc(i), yv(p['v']), fill=col)

        col_line = UP if pts[-1]['c'] >= pre else DOWN
        px_pts, avg_pts = [], []
        for i, p in enumerate(pts):
            px_pts.extend((xc(i), ym(p['c'])))
            avg_pts.extend((xc(i), ym(p['avg'])))
        if len(px_pts) >= 4:
            self.create_line(*px_pts, fill=col_line, width=1)
            self.create_line(*avg_pts, fill='#f5a623', width=1)

        self.create_line(x0, vy0, x1, vy0, fill=BORDER)
        self.create_text(x0 + 2, vy0 - 9, text='成交量', anchor='w',
                         fill=TEXT_MUTE, font=f9)

        idxs = sorted({0, len(pts) // 4, len(pts) // 2, 3 * len(pts) // 4, len(pts) - 1})
        for i in idxs:
            self.create_text(xc(i), bottom + 9, text=pts[i]['t'], anchor='center',
                             fill=TEXT_MUTE, font=fm)

        chg = (pts[-1]['c'] - pre) / pre * 100.0
        self.create_text(x0 + 2, my0 - 13,
                         text='分时  %s（%s）  均价 %s  昨收 %s'
                              % (fmt(pts[-1]['c'], 2), fmt_signed(chg, 2, '%'),
                                 fmt(pts[-1]['avg'], 2), fmt(pre, 2)),
                         anchor='w', fill=col_line, font=fb)
        if self.title:
            self.create_text(x1, my0 - 13, text=self.title, anchor='e',
                             fill=TEXT_DIM, font=f9)

        if self.hover is not None and 0 <= self.hover < len(pts):
            p = pts[self.hover]
            x = xc(self.hover)
            self.create_line(x, my0, x, vy1, fill='#8794a8', dash=(4, 3))
            yc = ym(p['c'])
            self.create_line(x0, yc, x1, yc, fill='#8794a8', dash=(4, 3))
            txt = fmt(p['c'], 2)
            tw = fm.measure(txt) + 14
            self.create_rectangle(x1, yc - 9, x1 + tw, yc + 9, fill=PANEL3, outline=BORDER)
            self.create_text(x1 + 7, yc, text=txt, anchor='w', fill=TEXT, font=fm)

            rows = [('时间', p['t']), ('价格', fmt(p['c'], 2)), ('均价', fmt(p['avg'], 2)),
                    ('涨跌', fmt_signed((p['c'] - pre) / pre * 100.0, 2, '%')),
                    ('成交量', an._vol_hand(p['v'])), ('成交额', an._big(p['amt']))]
            lw = max(fm.measure(k) for k, _v in rows) + 10
            vw = max(fm.measure(str(v)) for _k, v in rows)
            bw = lw + vw + 18
            bh = 16 * len(rows) + 12
            bx, by = x0 + 6, my0 + 6
            self.create_rectangle(bx, by, bx + bw, by + bh, fill='#0b0f15', outline=BORDER)
            ty = by + 10
            for k, v in rows:
                self.create_text(bx + 9, ty, text=k, anchor='w', fill=TEXT_MUTE, font=f9)
                self.create_text(bx + 9 + lw, ty, text=str(v), anchor='w',
                                 fill=TEXT, font=fm)
                ty += 16
