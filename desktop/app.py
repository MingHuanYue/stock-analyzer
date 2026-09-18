# -*- coding: utf-8 -*-
"""股票分析助手 —— 联网 K 线与数据分析桌面工具。

界面结构：
  工具栏    代码/名称搜索 · 周期切换 · 复权切换 · 刷新 · 自选 · 导出
  图表区    分时图 / K线图（蜡烛+均线+布林+成交量+MACD/KDJ/RSI副图，滚轮缩放·拖拽平移·十字光标）
  数据区    实时快照 · 估值规模 · 技术指标 · 资金流 · 财务摘要 · 智能分析
  状态栏    数据来源 · 更新时间 · 交易状态
"""
import csv
import datetime
import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import font as tkfont

import analysis as an
import datasource as ds
from chart import (ACCENT, BG, BORDER, DOWN, FLAT, FONT, FONT_NUM, GRID, KLineChart,
                   PANEL, PANEL2, PANEL3, TEXT, TEXT_DIM, TEXT_MUTE, UP, WARN,
                   fmt, fmt_signed, pick_font)

APP_NAME = '股票分析助手'
APP_VER = 'v1.0'

DISCLAIMER = ('免责声明：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。'
              '市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标'
              '独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。')

PERIODS = (('分时', 'trend'), ('日K', 'day'), ('周K', 'week'), ('月K', 'month'))
ADJUSTS = (('前复权', 'qfq'), ('不复权', 'none'), ('后复权', 'hfq'))
SUBS = (('MACD', 'MACD'), ('KDJ', 'KDJ'), ('RSI', 'RSI'))
PERIOD_NAME = {v: k for k, v in PERIODS}
ADJUST_NAME = {v: k for k, v in ADJUSTS}
KIND_NAME = {'A': 'A股', 'HK': '港股', 'US': '美股'}
TONE_COLOR = {'up': UP, 'down': DOWN, 'warn': WARN, 'flat': TEXT_DIM}


def enable_dpi():
    """开启 Windows DPI 感知，避免高分屏下界面模糊。"""
    try:
        from ctypes import windll
        try:
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:                                 # noqa: BLE001
            windll.user32.SetProcessDPIAware()
        return windll.user32.GetDpiForSystem() / 96.0
    except Exception:                                     # noqa: BLE001
        return 1.0


def cfg_path():
    base = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'),
                        'StockAnalyzer')
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:                                     # noqa: BLE001
        base = os.path.expanduser('~')
    return os.path.join(base, 'config.json')


def now_text():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def market_status(kind):
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return '周末休市（显示最近收盘数据）'
    hm = now.hour * 60 + now.minute
    if kind == 'A':
        if 555 <= hm < 570:
            return '集合竞价中'
        if 570 <= hm <= 690 or 780 <= hm <= 900:
            return '交易中'
        return '午间休市' if 690 < hm < 780 else '已收盘'
    if kind == 'HK':
        if 570 <= hm <= 720 or 780 <= hm <= 960:
            return '交易中'
        return '午间休市' if 720 < hm < 780 else '已收盘'
    if kind == 'US':
        if hm >= 1290 or hm <= 240:
            return '交易中（美东盘）'
        return '休市（显示最近收盘数据）'
    return ''


class ScrollPanel(tk.Frame):
    """竖向可滚动面板：滚轮只在面板内部生效，不影响图表缩放。"""

    def __init__(self, master, bg=PANEL, **kw):
        super().__init__(master, bg=bg, **kw)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vsb = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                bg=PANEL2, troughcolor=PANEL, activebackground=ACCENT,
                                bd=0, width=10, relief='flat')
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', self._on_inner)
        self.canvas.bind('<Configure>', self._on_canvas)

    def _on_inner(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _wheel(self, e):
        self.canvas.yview_scroll(-1 if e.delta > 0 else 1, 'units')
        return 'break'

    def bind_wheel(self):
        """递归绑定滚轮：新渲染出来的子控件也要能滚动。"""
        def walk(w):
            for c in w.winfo_children():
                c.bind('<MouseWheel>', self._wheel)
                walk(c)
        self.inner.bind('<MouseWheel>', self._wheel)
        walk(self.inner)

    def scroll_top(self):
        self.canvas.yview_moveto(0)


class LevelLadder(tk.Canvas):
    """关键价位阶梯：把上方压力 / 当前价 / 下方支撑排成一列，一眼看清位置。"""

    ROW = 25

    def __init__(self, master, dec=2, bg=PANEL, **kw):
        super().__init__(master, bg=bg, highlightthickness=0, **kw)
        self.dec = dec
        self.current = None
        self.supports = []
        self.resists = []
        self._fonts = {}
        self.bind('<Configure>', lambda _e: self.redraw())

    def _text_w(self, text, font):
        f = self._fonts.get(font)
        if f is None:
            f = tkfont.Font(font=font)
            self._fonts[font] = f
        return f.measure(text)

    def set_data(self, current, supports, resists):
        self.current = current
        self.supports = supports or []
        self.resists = resists or []
        rows = len(self.supports) + len(self.resists) + 1
        self.configure(height=self.ROW * rows + 8)
        self.redraw()

    def _rows(self):
        """自上而下：压力（由远及近）、当前价、支撑（由近及远）。"""
        rows = []
        for i in range(len(self.resists) - 1, -1, -1):
            name, price = self.resists[i][0], self.resists[i][1]
            rows.append(('压力%d' % (i + 1), name, price, 'resist'))
        rows.append(('当前价', '最新收盘', self.current, 'now'))
        for i, item in enumerate(self.supports):
            rows.append(('支撑%d' % (i + 1), item[0], item[1], 'support'))
        return rows

    def _fit(self, item, text, limit):
        """把过长的价位名称截断成「前半…」，避免压到右侧价格列。"""
        bb = self.bbox(item)
        if not bb or bb[2] <= limit:
            return
        cut = text
        while cut:
            cut = cut[:-1]
            self.itemconfigure(item, text=cut + '…')
            bb = self.bbox(item)
            if bb and bb[2] <= limit:
                return
        self.itemconfigure(item, text='')

    def redraw(self):
        self.delete('all')
        w = self.winfo_width()
        if w < 80 or self.current in (None, 0):
            return
        fm = (FONT_NUM, 9)
        rows = self._rows()
        spine = 64
        # 先量出右侧「价格」「涨跌幅」两列的真实宽度，名称列据此留白
        pw = 0
        for _t, _n, price, _k in rows:
            try:
                pw = max(pw, self._text_w(fmt(price, self.dec), fm))
            except Exception:                             # noqa: BLE001
                pass
        limit = max(spine + 24, w - 62 - pw - 8)
        cur_y = None
        for k, (tag, name, price, kind) in enumerate(rows):
            y = 4 + self.ROW * k + self.ROW / 2.0
            if kind == 'now':
                cur_y = y
            gap = None
            try:
                gap = (price - self.current) / self.current * 100.0
            except TypeError:
                pass
            if kind == 'resist':
                col, dot = '#c96a63', '#7a423e'
            elif kind == 'support':
                col, dot = '#4fb894', '#2f6b58'
            else:
                col, dot = ACCENT, ACCENT
            body_col = TEXT if kind == 'now' else TEXT_DIM

            self.create_text(4, y, text=tag, anchor='w', fill=col,
                             font=(FONT, 9, 'bold') if kind == 'now' else (FONT, 9))
            self.create_line(spine, y, spine + 8, y, fill=dot)
            self.create_oval(spine - 3, y - 3, spine + 3, y + 3, fill=col, outline='')
            nid = self.create_text(spine + 16, y, text=name, anchor='w',
                                   fill=body_col,
                                   font=(FONT, 9 if kind == 'now' else 8))
            self._fit(nid, name, limit)
            self.create_text(w - 62, y, text=fmt(price, self.dec), anchor='e',
                             fill=col, font=fm)
            if gap is not None:
                self.create_text(w, y, text=fmt_signed(gap, 2, '%'), anchor='e',
                                 fill=col if kind != 'now' else TEXT_DIM, font=fm)

        # 主脊线：现价上方偏暖、下方偏冷
        if cur_y is not None:
            top, bottom = 4 + self.ROW / 2.0, 4 + self.ROW * (len(rows) - 1) + self.ROW / 2.0
            self.create_line(spine, top, spine, cur_y - 6, fill='#5a3a37', width=2)
            self.create_line(spine, cur_y + 6, spine, bottom, fill='#2f5a4c', width=2)
            self.create_line(0, cur_y + self.ROW / 2.0 - 1, w, cur_y + self.ROW / 2.0 - 1,
                             fill='#2f3a4d')


class StockApp:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.secid = None
        self.period = 'day'
        self.adjust = 'qfq'
        self.bundle = None
        self.analysis = None
        self.cfg = self._load_cfg()

        self.f_title = (FONT, 11, 'bold')
        self.f_body = (FONT, 9)
        self.f_small = (FONT, 9)
        self.f_num = (FONT_NUM, 9)
        self.f_price = (FONT_NUM, 25, 'bold')
        self.f_big = (FONT, 13, 'bold')

        root.title('%s %s — 联网K线与数据分析' % (APP_NAME, APP_VER))
        root.configure(bg=BG)
        root.geometry('1520x920')
        root.minsize(1180, 720)
        self._center(1520, 920)

        self._build_toolbar()
        self._build_body()
        self._build_status()

        root.bind('<F5>', lambda _e: self.reload())
        root.bind('<Return>', self._on_enter)
        root.after(80, self._poll)

        last = self.cfg.get('last') or '600519'
        self.entry_var.set(last)
        self._start_from_keyword(last)

    # ---------------- 配置 ----------------
    def _load_cfg(self):
        try:
            with open(cfg_path(), 'r', encoding='utf-8') as fp:
                cfg = json.load(fp)
            if isinstance(cfg, dict):
                return cfg
        except Exception:                                 # noqa: BLE001
            pass
        return {}

    def _save_cfg(self):
        try:
            with open(cfg_path(), 'w', encoding='utf-8') as fp:
                json.dump(self.cfg, fp, ensure_ascii=False, indent=1)
        except Exception:                                 # noqa: BLE001
            pass

    def _center(self, w, h):
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry('%dx%d+%d+%d' % (w, h, max(0, (sw - w) // 2),
                                            max(0, (sh - h) // 3)))

    # ---------------- 控件工厂 ----------------
    def _btn(self, parent, text, cmd, kind='normal', width=None):
        styles = {
            'normal': (PANEL2, TEXT, PANEL3),
            'primary': ('#24405f', '#cfe3ff', '#2f5f95'),
        }
        bg, fg, hover = styles.get(kind, styles['normal'])
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=hover, activeforeground=fg,
                      relief='flat', bd=0, highlightthickness=0,
                      font=self.f_body, cursor='hand2', padx=12, pady=5)
        if width:
            b.configure(width=width)
        b.bind('<Enter>', lambda _e: b.configure(bg=hover) if b['state'] != 'disabled' else None)
        b.bind('<Leave>', lambda _e, c=bg: b.configure(bg=c) if b['state'] != 'disabled' else None)
        return b

    def _toggle(self, parent, text, value, on_click):
        b = self._btn(parent, text, lambda: on_click(value))
        b._value = value
        return b

    # ---------------- 工具栏 ----------------
    def _build_toolbar(self):
        bar = tk.Frame(self.root, bg=PANEL, height=52)
        bar.pack(side='top', fill='x')
        tk.Frame(self.root, bg=BORDER, height=1).pack(side='top', fill='x')

        left = tk.Frame(bar, bg=PANEL)
        left.pack(side='left', padx=12, pady=9)

        tk.Label(left, text='代码/名称', bg=PANEL, fg=TEXT_DIM,
                 font=self.f_body).pack(side='left', padx=(0, 6))
        self.entry_var = tk.StringVar()
        self.entry = tk.Entry(left, textvariable=self.entry_var, width=16,
                              bg=PANEL3, fg=TEXT, insertbackground=TEXT,
                              relief='flat', bd=0, font=(FONT_NUM, 11),
                              highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=ACCENT)
        self.entry.pack(side='left', ipady=5, padx=(0, 6))
        self.entry.bind('<FocusIn>', lambda _e: self.entry.select_range(0, 'end'))
        self._btn(left, '查询', self._on_search, 'primary').pack(side='left')

        mid = tk.Frame(bar, bg=PANEL)
        mid.pack(side='left', padx=16)
        self.period_btns = {}
        for label, val in PERIODS:
            b = self._toggle(mid, label, val, self._on_period)
            b.pack(side='left', padx=2)
            self.period_btns[val] = b
        tk.Label(mid, text='│', bg=PANEL, fg=BORDER).pack(side='left', padx=6)
        self.adjust_btns = {}
        for label, val in ADJUSTS:
            b = self._toggle(mid, label, val, self._on_adjust)
            b.pack(side='left', padx=2)
            self.adjust_btns[val] = b
        tk.Label(mid, text='│', bg=PANEL, fg=BORDER).pack(side='left', padx=6)
        self.sub_btns = {}
        for label, val in SUBS:
            b = self._toggle(mid, label, val, self._on_sub)
            b.pack(side='left', padx=2)
            self.sub_btns[val] = b

        right = tk.Frame(bar, bg=PANEL)
        right.pack(side='right', padx=12, pady=9)
        self.star_btn = self._btn(right, '★ 加自选', self._on_star)
        self.star_btn.pack(side='right', padx=3)
        self.watch_btn = tk.Menubutton(right, text='自选股 ▾', bg=PANEL2, fg=TEXT,
                                       activebackground=PANEL3, activeforeground=TEXT,
                                       relief='flat', bd=0, highlightthickness=0,
                                       font=self.f_body, cursor='hand2', padx=12, pady=5)
        self.watch_menu = tk.Menu(self.watch_btn, tearoff=0, bg=PANEL2, fg=TEXT,
                                  activebackground=ACCENT, activeforeground='#fff')
        self.watch_btn.configure(menu=self.watch_menu)
        self.watch_btn.pack(side='right', padx=3)
        self.export_btn = tk.Menubutton(right, text='导出 ▾', bg=PANEL2, fg=TEXT,
                                        activebackground=PANEL3, activeforeground=TEXT,
                                        relief='flat', bd=0, highlightthickness=0,
                                        font=self.f_body, cursor='hand2', padx=12, pady=5)
        self.export_menu = tk.Menu(self.export_btn, tearoff=0, bg=PANEL2, fg=TEXT,
                                   activebackground=ACCENT, activeforeground='#fff')
        self.export_menu.add_command(label='导出 K 线数据 (CSV)', command=self._export_csv)
        self.export_menu.add_command(label='导出分析报告 (TXT)', command=self._export_report)
        self.export_btn.configure(menu=self.export_menu)
        self.export_btn.pack(side='right', padx=3)
        self.refresh_btn = self._btn(right, '刷新', self.reload)
        self.refresh_btn.pack(side='right', padx=3)

        self._sync_toolbar()

    def _sync_toolbar(self):
        for val, b in self.period_btns.items():
            on = (val == self.period)
            b.configure(bg='#1f4a7a' if on else PANEL2, fg='#ffffff' if on else TEXT)
        for val, b in self.adjust_btns.items():
            on = (val == self.adjust)
            b.configure(bg='#1f4a7a' if on else PANEL2, fg='#ffffff' if on else TEXT)
            b.configure(state='normal' if self.period != 'trend' else 'disabled')
        for val, b in self.sub_btns.items():
            on = (val == self.chart.sub if hasattr(self, 'chart') else val == 'MACD')
            b.configure(bg='#1f4a7a' if on else PANEL2, fg='#ffffff' if on else TEXT)
            b.configure(state='normal' if self.period != 'trend' else 'disabled')

    # ---------------- 主体 ----------------
    def _build_body(self):
        body = tk.Frame(self.root, bg=BG)
        body.pack(side='top', fill='both', expand=True)

        left = tk.Frame(body, bg=BG)
        left.pack(side='left', fill='both', expand=True, padx=(8, 0), pady=8)
        tk.Frame(body, bg=BORDER, width=1).pack(side='left', fill='y', pady=8)

        self.chart = KLineChart(left)
        self.chart.pack(fill='both', expand=True)

        hint = tk.Label(left, text='提示：滚轮缩放 · 按住左键拖拽平移 · 鼠标移动查看十字光标数据',
                        bg=BG, fg=TEXT_MUTE, font=self.f_small, anchor='w')
        hint.pack(fill='x', pady=(2, 0))

        right = tk.Frame(body, bg=PANEL, width=418)
        right.pack(side='left', fill='y', pady=8, padx=(0, 8))
        right.pack_propagate(False)
        self.panel = ScrollPanel(right, bg=PANEL)
        self.panel.pack(fill='both', expand=True)
        self.pcontent = self.panel.inner

    def _build_status(self):
        tk.Frame(self.root, bg=BORDER, height=1).pack(side='bottom', fill='x')
        bar = tk.Frame(self.root, bg=PANEL, height=26)
        bar.pack(side='bottom', fill='x')
        self.status_var = tk.StringVar(value='就绪')
        self.status_lbl = tk.Label(bar, textvariable=self.status_var, bg=PANEL,
                                   fg=TEXT_DIM, font=self.f_small, anchor='w')
        self.status_lbl.pack(side='left', padx=12, pady=3)
        self.src_var = tk.StringVar(value='')
        tk.Label(bar, textvariable=self.src_var, bg=PANEL, fg=TEXT_MUTE,
                 font=self.f_small, anchor='e').pack(side='right', padx=12)

    # ---------------- 交互 ----------------
    def _on_enter(self, _e):
        self._on_search()

    def _on_search(self):
        kw = self.entry_var.get().strip()
        if kw:
            self._start_from_keyword(kw)

    def _on_period(self, val):
        if val == self.period:
            return
        self.period = val
        self._sync_toolbar()
        if self.secid:
            self._start_load(self.secid, val, self.adjust, is_secid=True)

    def _on_adjust(self, val):
        if val == self.adjust or self.period == 'trend':
            return
        self.adjust = val
        self._sync_toolbar()
        if self.secid:
            self._start_load(self.secid, self.period, val, is_secid=True)

    def _on_sub(self, val):
        self.chart.set_sub(val)
        self._sync_toolbar()

    def reload(self):
        if self.secid:
            self._start_load(self.secid, self.period, self.adjust, is_secid=True)

    def _on_star(self):
        if not self.secid or not self.bundle:
            return
        watch = self.cfg.setdefault('watchlist', [])
        code = self.bundle['quote'].get('code') or ds.code_of(self.secid)
        if any(w.get('secid') == self.secid for w in watch):
            watch[:] = [w for w in watch if w.get('secid') != self.secid]
            self.status('已从自选移除 %s' % code)
        else:
            watch.append({'secid': self.secid, 'name': self.bundle['quote'].get('name', ''),
                          'code': code})
            self.status('已加入自选 %s' % code)
        self._save_cfg()
        self._render_panel()

    def _open_watch(self, secid):
        self.entry_var.set(secid)
        self._start_load(secid, self.period, self.adjust, is_secid=True)

    def _clear_watch(self):
        self.cfg['watchlist'] = []
        self._save_cfg()
        self._render_panel()

    # ---------------- 数据加载 ----------------
    def _start_from_keyword(self, kw):
        self._start_load(kw, self.period, self.adjust, is_secid=False)

    def _start_load(self, key, period, adjust, is_secid):
        if self.busy:
            self.pending = (key, period, adjust, is_secid)   # 排队，等当前请求结束
            return
        self.pending = None
        self.busy = True
        self.refresh_btn.configure(state='disabled', text='加载中')
        self.status('正在获取数据…', ACCENT)
        t = threading.Thread(target=self._work, args=(key, period, adjust, is_secid),
                             daemon=True)
        t.start()

    def _work(self, key, period, adjust, is_secid):
        try:
            if is_secid:
                secid = key
            else:
                secid, cands = ds.resolve(key)
                if cands:
                    self.q.put(('choose', cands, period, adjust))
                    return
            if period == 'trend':
                pre, name, pts = ds.fetch_trends(secid)
                quote = ds.fetch_quote(secid)
                if not quote.get('name'):
                    quote['name'] = name
                _, bars, ksrc = ds.fetch_kline(secid, 'day', adjust)
                bname, bench = ds.fetch_benchmark(secid, 'day')
                payload = {'secid': secid, 'quote': quote, 'bars': bars,
                           'kline_source': ksrc, 'flow': ds.fetch_fundflow(secid),
                           'finance': ds.fetch_finance(secid),
                           'bench_name': bname, 'bench_bars': bench,
                           '_pre': pre, '_pts': pts}
            else:
                payload = ds.load_all(secid, period, adjust)
                payload['secid'] = secid
            self.q.put(('ok', payload, period, adjust))
        except Exception as exc:                          # noqa: BLE001
            self.q.put(('error', str(exc)))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.root.after(90, self._poll)

    def _handle(self, msg):
        self.busy = False
        self.refresh_btn.configure(state='normal', text='刷新')
        kind = msg[0]
        if kind == 'error':
            self.status('获取失败', UP)
            self._render_error(msg[1])
            self._run_pending()
            return
        if kind == 'choose':
            cands, period, adjust = msg[1], msg[2], msg[3]
            secid = self._choose_dialog(cands)
            if secid:
                self._start_load(secid, period, adjust, is_secid=True)
            else:
                self.status('已取消', TEXT_DIM)
                self._run_pending()
            return

        _tag, bundle, period, adjust = msg
        self.bundle = bundle
        self.secid = bundle['secid']
        self.period = period
        self.adjust = adjust
        self.cfg['last'] = self.secid
        self._save_cfg()
        self._sync_toolbar()

        q = bundle['quote']
        title = '%s %s · %s%s' % (q.get('name', ''), q.get('code', ''),
                                  PERIOD_NAME.get(period, period),
                                  '' if period == 'trend' else ADJUST_NAME.get(adjust, ''))
        if period == 'trend' and bundle.get('_pts'):
            self.chart.set_trend(bundle['_pre'], bundle['_pts'], title)
        else:
            bars = bundle['bars']
            ind = an.compute_indicators(bars)
            self.chart.set_kline(bars, ind, title)
            self.bundle['ind'] = ind

        # 分时模式下，分析结论仍基于日线
        bars_for = bundle['bars']
        ind_for = (bundle.get('ind') if period != 'trend' else None) \
            or an.compute_indicators(bars_for)
        self.analysis = an.build_analysis(
            q, bars_for, ind_for, bundle.get('flow') or [],
            bundle.get('finance') or {},
            bench=bundle.get('bench_bars') or None,
            bench_name=bundle.get('bench_name') or '',
            period='day' if period == 'trend' else period)
        self.analysis['_bars'] = bars_for
        self.analysis['_ind'] = ind_for
        self._render_panel()

        stat = market_status(q.get('kind', 'A'))
        self.status('已更新 %s' % now_text(), TEXT)
        self.src_var.set('数据源 %s · K线 %s · %s · 仅供研究参考，不构成投资建议'
                         % (q.get('source', '—'), bundle.get('kline_source', '—'), stat))
        self._run_pending()

    def _run_pending(self):
        if self.pending:
            p = self.pending
            self.pending = None
            self._start_load(*p)

    def status(self, text, color=TEXT_DIM):
        self.status_var.set(text)
        self.status_lbl.configure(fg=color)

    def _choose_dialog(self, cands):
        dlg = tk.Toplevel(self.root)
        dlg.title('选择标的')
        dlg.configure(bg=PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        tk.Label(dlg, text='找到多个匹配结果，请选择：', bg=PANEL, fg=TEXT,
                 font=self.f_body).pack(anchor='w', padx=14, pady=(12, 6))
        lb = tk.Listbox(dlg, bg=PANEL3, fg=TEXT, selectbackground=ACCENT,
                        selectforeground='#fff', font=self.f_num, relief='flat',
                        bd=0, highlightthickness=0, width=44, height=min(12, len(cands)),
                        activestyle='none')
        for c in cands:
            lb.insert('end', '  %-10s %-14s %s' % (c['code'], c['name'], c['market']))
        lb.pack(padx=14)
        lb.selection_set(0)
        result = {'secid': None}

        def ok(_e=None):
            sel = lb.curselection()
            if sel:
                result['secid'] = cands[sel[0]]['secid']
            dlg.destroy()

        btns = tk.Frame(dlg, bg=PANEL)
        btns.pack(fill='x', padx=14, pady=12)
        self._btn(btns, '确定', ok, 'primary').pack(side='right')
        self._btn(btns, '取消', dlg.destroy).pack(side='right', padx=6)
        lb.bind('<Double-Button-1>', ok)
        dlg.bind('<Return>', ok)
        dlg.bind('<Escape>', lambda _e: dlg.destroy())
        dlg.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dlg.winfo_width()) // 2
        y = self.root.winfo_rooty() + 160
        dlg.geometry('+%d+%d' % (max(0, x), max(0, y)))
        self.root.wait_window(dlg)
        return result['secid']

    # ---------------- 右侧面板 ----------------
    def _clear_panel(self):
        for w in self.pcontent.winfo_children():
            w.destroy()

    def _section(self, title, first=False):
        wrap = tk.Frame(self.pcontent, bg=PANEL)
        wrap.pack(fill='x', padx=12, pady=(6 if first else 12, 0))
        head = tk.Frame(wrap, bg=PANEL)
        head.pack(fill='x')
        tk.Frame(head, bg=ACCENT, width=3, height=13).pack(side='left')
        tk.Label(head, text=title, bg=PANEL, fg=TEXT, font=self.f_title,
                 anchor='w').pack(side='left', padx=7)
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill='x', pady=(5, 7))
        body = tk.Frame(wrap, bg=PANEL)
        body.pack(fill='x')
        return body

    def _kv(self, parent, items, cols=2):
        grid = tk.Frame(parent, bg=PANEL)
        grid.pack(fill='x')
        for c in (1, 3):
            grid.grid_columnconfigure(c, weight=1)
        for i, item in enumerate(items):
            k, v = item[0], item[1]
            col = item[2] if len(item) > 2 else TEXT
            r, cc = divmod(i, cols)
            tk.Label(grid, text=k, bg=PANEL, fg=TEXT_MUTE, font=self.f_small,
                     anchor='w').grid(row=r, column=cc * 2, sticky='w', pady=1)
            tk.Label(grid, text=v, bg=PANEL, fg=col, font=self.f_num,
                     anchor='e').grid(row=r, column=cc * 2 + 1, sticky='e',
                                      padx=(0, 12), pady=1)

    def _render_error(self, text):
        self._clear_panel()
        box = self._section('获取失败', first=True)
        tk.Label(box, text=text, bg=PANEL, fg=UP, font=self.f_body, justify='left',
                 wraplength=370, anchor='w').pack(fill='x')
        tk.Label(box, text='建议：检查网络连接，或用 6 位股票代码重试（如 600519、300750、00700）。',
                 bg=PANEL, fg=TEXT_MUTE, font=self.f_small, justify='left',
                 wraplength=370, anchor='w').pack(fill='x', pady=(8, 0))
        self.panel.bind_wheel()

    def _render_panel(self):
        if not self.bundle or not self.analysis:
            return
        q = self.bundle['quote']
        res = self.analysis
        self._clear_panel()

        # ---- 头部报价 ----
        head = tk.Frame(self.pcontent, bg=PANEL)
        head.pack(fill='x', padx=12, pady=(12, 0))
        top = tk.Frame(head, bg=PANEL)
        top.pack(fill='x')
        tk.Label(top, text=q.get('name', ''), bg=PANEL, fg=TEXT, font=self.f_big,
                 anchor='w').pack(side='left')
        tk.Label(top, text=' ' + str(q.get('code', '')), bg=PANEL, fg=TEXT_MUTE,
                 font=self.f_num, anchor='w').pack(side='left')
        tag = KIND_NAME.get(q.get('kind'), '')
        tk.Label(top, text=tag, bg=PANEL3, fg=TEXT_DIM, font=self.f_small,
                 padx=6).pack(side='left', padx=6)
        tk.Label(top, text='★' if any(w.get('secid') == self.secid
                                      for w in self.cfg.get('watchlist', [])) else '',
                 bg=PANEL, fg=WARN, font=self.f_big).pack(side='right')

        pct = q.get('pct')
        pc = UP if (pct or 0) > 0 else (DOWN if (pct or 0) < 0 else FLAT)
        prow = tk.Frame(head, bg=PANEL)
        prow.pack(fill='x', pady=(2, 0))
        tk.Label(prow, text=fmt(q.get('price'), 2), bg=PANEL, fg=pc,
                 font=self.f_price, anchor='w').pack(side='left')
        tk.Label(prow, text='  %s  %s' % (fmt_signed(q.get('change'), 2),
                                          fmt_signed(pct, 2, '%')),
                 bg=PANEL, fg=pc, font=(FONT_NUM, 12, 'bold'),
                 anchor='w').pack(side='left', pady=(6, 0))
        stat = market_status(q.get('kind', 'A'))
        tk.Label(prow, text=stat, bg=PANEL, fg=TEXT_MUTE, font=self.f_small,
                 anchor='e').pack(side='right', pady=(8, 0))

        # ---- 盘口速览 ----
        body = self._section('盘口速览')
        items = [('今开', fmt(q.get('open'), 2), _c(q.get('open'), q.get('preclose'))),
                 ('昨收', fmt(q.get('preclose'), 2), TEXT),
                 ('最高', fmt(q.get('high'), 2), _c(q.get('high'), q.get('preclose'))),
                 ('最低', fmt(q.get('low'), 2), _c(q.get('low'), q.get('preclose'))),
                 ('成交量', an._vol_hand(q.get('volume')), TEXT),
                 ('成交额', an._big(q.get('amount')), TEXT),
                 ('振幅', fmt(q.get('amplitude'), 2, '%'), TEXT),
                 ('换手率', fmt(q.get('turnover'), 2, '%'), TEXT),
                 ('量比', fmt(q.get('vol_ratio'), 2), _c(q.get('vol_ratio'), 1.0)),
                 ('涨停', fmt(q.get('limit_up'), 2), UP),
                 ('跌停', fmt(q.get('limit_down'), 2), DOWN),
                 ('均价', fmt(_avg_price(q), 2),
                  _c(_avg_price(q), q.get('preclose')))]
        self._kv(body, items)

        # ---- 估值与规模 ----
        body = self._section('估值与规模')
        items = [('总市值', an._big(q.get('total_cap')), TEXT),
                 ('流通市值', an._big(q.get('float_cap')), TEXT),
                 ('市盈率(动)', fmt(q.get('pe'), 2), TEXT),
                 ('市净率', fmt(q.get('pb'), 2), TEXT),
                 ('每股净资产', fmt(q.get('bps'), 2), TEXT),
                 ('总股本', an._big(q.get('total_share')), TEXT)]
        self._kv(body, items)

        # ---- 技术指标 ----
        ind, i = res['_ind'], len(res['_bars']) - 1
        px_now = q.get('price')
        body = self._section('技术指标快照')
        items = [('MA5', fmt(an.value_at(ind['ma5'], i), 2), _c(px_now, an.value_at(ind['ma5'], i))),
                 ('MA10', fmt(an.value_at(ind['ma10'], i), 2), _c(px_now, an.value_at(ind['ma10'], i))),
                 ('MA20', fmt(an.value_at(ind['ma20'], i), 2), _c(px_now, an.value_at(ind['ma20'], i))),
                 ('MA60', fmt(an.value_at(ind['ma60'], i), 2), _c(px_now, an.value_at(ind['ma60'], i))),
                 ('DIF', fmt(an.value_at(ind['dif'], i), 3), _c(an.value_at(ind['dif'], i), 0)),
                 ('DEA', fmt(an.value_at(ind['dea'], i), 3), _c(an.value_at(ind['dea'], i), 0)),
                 ('K', fmt(an.value_at(ind['k'], i), 2), TEXT),
                 ('D', fmt(an.value_at(ind['d'], i), 2), TEXT),
                 ('J', fmt(an.value_at(ind['j'], i), 2), TEXT),
                 ('RSI6', fmt(an.value_at(ind['rsi6'], i), 2), TEXT),
                 ('RSI12', fmt(an.value_at(ind['rsi12'], i), 2), TEXT),
                 ('RSI24', fmt(an.value_at(ind['rsi24'], i), 2), TEXT),
                 ('布林上轨', fmt(an.value_at(ind['boll_up'], i), 2), TEXT_DIM),
                 ('布林中轨', fmt(an.value_at(ind['boll_mid'], i), 2), TEXT_DIM),
                 ('布林下轨', fmt(an.value_at(ind['boll_dn'], i), 2), TEXT_DIM),
                 ('ATR14', fmt(an.value_at(ind['atr14'], i), 2), TEXT_DIM)]
        self._kv(body, items)

        # ---- 资金流 ----
        flow = self.bundle.get('flow') or []
        body = self._section('资金流向')
        if flow:
            f0 = flow[-1]
            items = [('日期', f0.get('d', '—'), TEXT_DIM),
                     ('主力净额', _sign_money(f0.get('main')), _c(f0.get('main'), 0)),
                     ('超大单', _sign_money(f0.get('huge')), _c(f0.get('huge'), 0)),
                     ('大单', _sign_money(f0.get('big')), _c(f0.get('big'), 0)),
                     ('中单', _sign_money(f0.get('mid')), _c(f0.get('mid'), 0)),
                     ('小单', _sign_money(f0.get('small')), _c(f0.get('small'), 0))]
            self._kv(body, items)
            if len(flow) >= 5:
                vals = [r['main'] for r in flow[-5:] if r.get('main') is not None]
                if vals:
                    tot = sum(vals)
                    tk.Label(body, text='近 5 日主力合计 %s' % _sign_money(tot),
                             bg=PANEL, fg=_c(tot, 0), font=self.f_body,
                             anchor='w').pack(fill='x', pady=(6, 0))
        else:
            tk.Label(body, text='资金流数据暂不可用（部分网络环境下该接口被拦截）',
                     bg=PANEL, fg=TEXT_MUTE, font=self.f_small, anchor='w').pack(fill='x')

        # ---- 财务摘要 ----
        fin = self.bundle.get('finance') or {}
        if fin:
            body = self._section('财务摘要 (%s)' % fin.get('_period', '—'))
            items = [('营业总收入', an._big(fin.get('营业总收入(元)')), TEXT),
                     ('营收同比', fmt(fin.get('营收同比(%)'), 2, '%'),
                      _c(fin.get('营收同比(%)'), 0)),
                     ('归母净利润', an._big(fin.get('归母净利润(元)')), TEXT),
                     ('净利同比', fmt(fin.get('净利同比(%)'), 2, '%'),
                      _c(fin.get('净利同比(%)'), 0)),
                     ('净资产收益率', fmt(fin.get('净资产收益率(%)'), 2, '%'), TEXT),
                     ('销售毛利率', fmt(fin.get('销售毛利率(%)'), 2, '%'), TEXT),
                     ('销售净利率', fmt(fin.get('销售净利率(%)'), 2, '%'), TEXT),
                     ('资产负债率', fmt(fin.get('资产负债率(%)'), 2, '%'), TEXT),
                     ('每股收益', fmt(fin.get('每股收益(元)'), 2), TEXT),
                     ('每股净资产', fmt(fin.get('每股净资产(元)'), 2), TEXT)]
            self._kv(body, items)
            tk.Label(body, text='数据源：东方财富 F10，报告期 %s（公告日 %s）'
                                % (fin.get('_period', '—'), fin.get('_notice', '—')),
                     bg=PANEL, fg=TEXT_MUTE, font=self.f_small, anchor='w',
                     wraplength=372, justify='left').pack(fill='x', pady=(6, 0))

        # ---- 综合诊断 ----
        body = self._section('综合诊断')
        bar = tk.Canvas(body, bg=PANEL, height=30, highlightthickness=0)
        bar.pack(fill='x')
        bar.bind('<Configure>', lambda _e, c=bar: self._draw_score(c, res['score'],
                                                                   res['level']))
        tk.Label(body, text=res['verdict'], bg=PANEL,
                 fg=TONE_COLOR.get(res['level_tone'], TEXT), font=(FONT, 9, 'bold'),
                 wraplength=372, justify='left', anchor='w').pack(fill='x', pady=(6, 3))
        tk.Label(body, text=res['plain'], bg=PANEL, fg=TEXT, font=self.f_body,
                 wraplength=372, justify='left', anchor='w').pack(fill='x', pady=(0, 3))
        tk.Label(body, text=res['summary'], bg=PANEL, fg=TEXT_MUTE, font=self.f_small,
                 wraplength=372, justify='left', anchor='w').pack(fill='x')

        # ---- 多空信号对照 ----
        body = self._section('多空信号对照（看多 %d 项 / 看空 %d 项）'
                             % (len(res['bulls']), len(res['bears'])))
        if res['bulls']:
            tk.Label(body, text='▲ 支撑价格的信号', bg=PANEL, fg=UP,
                     font=(FONT, 9, 'bold'), anchor='w').pack(fill='x', pady=(0, 2))
            for t in res['bulls']:
                tk.Label(body, text='· ' + t, bg=PANEL, fg='#e08a83', font=self.f_body,
                         wraplength=366, justify='left', anchor='w').pack(fill='x')
        if res['bears']:
            tk.Label(body, text='▼ 压制价格的信号', bg=PANEL, fg=DOWN,
                     font=(FONT, 9, 'bold'), anchor='w').pack(fill='x', pady=(8, 2))
            for t in res['bears']:
                tk.Label(body, text='· ' + t, bg=PANEL, fg='#68c9a8', font=self.f_body,
                         wraplength=366, justify='left', anchor='w').pack(fill='x')
        if not res['bulls'] and not res['bears']:
            tk.Label(body, text='当前没有触发明确的多空信号，市场处于均衡状态。',
                     bg=PANEL, fg=TEXT_MUTE, font=self.f_body, anchor='w').pack(fill='x')

        # ---- 分维度评分 ----
        body = self._section('分维度评分')
        for dim in res['dims']:
            cv = tk.Canvas(body, bg=PANEL, height=34, highlightthickness=0)
            cv.pack(fill='x', pady=(0, 4))
            cv.bind('<Configure>', lambda _e, c=cv, d=dim: self._draw_dim(c, d))

        # ---- 波动与风险 ----
        body = self._section('波动与风险（%s）' % res['risk']['level'])
        rk = res['risk']
        rcv = tk.Canvas(body, bg=PANEL, height=34, highlightthickness=0)
        rcv.pack(fill='x', pady=(0, 4))
        rcv.bind('<Configure>', lambda _e, c=rcv, d={'name': '波动风险',
                                                     'score': rk['score'],
                                                     'note': '数值越高代表波动越大、风险越高',
                                                     'tone': DOWN if rk['score'] >= 68
                                                     else (WARN if rk['score'] >= 45
                                                           else UP)}:
                 self._draw_dim(c, d, invert=True))
        for text, tone in rk['items']:
            tk.Label(body, text='· ' + text, bg=PANEL, fg=TONE_COLOR.get(tone, TEXT_DIM),
                     font=self.f_body, wraplength=366, justify='left',
                     anchor='w').pack(fill='x', pady=1)

        # ---- 关键价位阶梯 ----
        body = self._section('关键价位阶梯')
        ladder = LevelLadder(body, dec=q.get('dec', 2))
        ladder.pack(fill='x')
        ladder.set_data(q.get('price'), res['supports'], res['resists'])

        # ---- 详细分析 ----
        body = self._section('详细分析')
        for title, lines in res['sections']:
            tk.Label(body, text=title, bg=PANEL, fg=TEXT, font=(FONT, 9, 'bold'),
                     anchor='w').pack(fill='x', pady=(9, 3))
            for text, tone in lines:
                tk.Label(body, text='· ' + text, bg=PANEL, fg=TONE_COLOR.get(tone, TEXT_DIM),
                         font=self.f_body, wraplength=366, justify='left',
                         anchor='w').pack(fill='x', pady=1)

        # ---- 情景应对 ----
        body = self._section('情景应对（条件化参考）')
        for name, cond, mean, tone in res['scenarios']:
            card = tk.Frame(body, bg=PANEL2)
            card.pack(fill='x', pady=3)
            tk.Label(card, text=name, bg=PANEL2, fg=TONE_COLOR.get(tone, TEXT),
                     font=(FONT, 9, 'bold'), anchor='w').pack(fill='x', padx=8, pady=(5, 0))
            tk.Label(card, text=cond, bg=PANEL2, fg=TEXT, font=self.f_small,
                     wraplength=352, justify='left', anchor='w').pack(fill='x', padx=8)
            tk.Label(card, text=mean, bg=PANEL2, fg=TEXT_MUTE, font=self.f_small,
                     wraplength=352, justify='left', anchor='w').pack(fill='x', padx=8,
                                                                      pady=(0, 5))

        # ---- 免责声明 ----
        wrap = tk.Frame(self.pcontent, bg=PANEL)
        wrap.pack(fill='x', padx=12, pady=(14, 16))
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill='x', pady=(0, 8))
        tk.Label(wrap, text=DISCLAIMER, bg=PANEL, fg=TEXT_MUTE, font=self.f_small,
                 wraplength=374, justify='left', anchor='w').pack(fill='x')
        tk.Label(wrap, text='%s %s · 数据来自公开行情接口，需联网，仅供研究学习使用'
                            % (APP_NAME, APP_VER),
                 bg=PANEL, fg='#3f4859', font=self.f_small, anchor='w',
                 wraplength=374, justify='left').pack(fill='x', pady=(6, 0))

        self.panel.bind_wheel()
        self.panel.scroll_top()
        self._render_watch_menu()

    def _draw_score(self, canvas, score, level):
        canvas.delete('all')
        w = canvas.winfo_width()
        if w < 20:
            return
        y0, y1 = 17, 26
        canvas.create_rectangle(0, y0, w, y1, fill=PANEL3, outline='')
        col = UP if score >= 58 else (DOWN if score < 43 else WARN)
        fw = int(w * score / 100.0)
        if fw > 0:
            canvas.create_rectangle(0, y0, fw, y1, fill=col, outline='')
        canvas.create_text(0, 4, text='技术面综合评分', anchor='w', fill=TEXT_DIM,
                           font=(FONT, 9))
        canvas.create_text(w, 2, text='%.0f / 100  %s' % (score, level), anchor='ne',
                           fill=col, font=(FONT, 13, 'bold'))

    def _draw_dim(self, canvas, dim, invert=False):
        canvas.delete('all')
        w = canvas.winfo_width()
        if w < 40:
            return
        score = dim['score']
        if invert:
            col = '#3fbfa0' if score < 45 else (WARN if score < 68 else '#ff8a3d')
        else:
            col = UP if score >= 56 else (DOWN if score < 44 else WARN)
        canvas.create_text(0, 8, text=dim['name'], anchor='w', fill=TEXT,
                           font=(FONT, 9, 'bold'))
        canvas.create_text(w, 8, text='%.0f' % score, anchor='e', fill=col,
                           font=(FONT_NUM, 10, 'bold'))
        y0, y1 = 24, 32
        canvas.create_rectangle(0, y0, w, y1, fill=PANEL3, outline='')
        fw = int(w * score / 100.0)
        if fw > 0:
            canvas.create_rectangle(0, y0, fw, y1, fill=col, outline='')
        canvas.create_text(0, 41, text=dim['note'], anchor='w', fill=TEXT_MUTE,
                           font=(FONT, 8))

    def _render_watch_menu(self):
        self.watch_menu.delete(0, 'end')
        watch = self.cfg.get('watchlist', [])
        if not watch:
            self.watch_menu.add_command(label='（暂无自选股）', state='disabled')
        for item in watch:
            self.watch_menu.add_command(
                label='%s  %s' % (item.get('code', ''), item.get('name', '')),
                command=lambda s=item['secid']: self._open_watch(s))
        if watch:
            self.watch_menu.add_separator()
            self.watch_menu.add_command(label='清空自选股', command=self._clear_watch)
        starred = any(w.get('secid') == self.secid for w in watch)
        self.star_btn.configure(text='★ 取消自选' if starred else '☆ 加自选')

    # ---------------- 导出 ----------------
    def _export_csv(self):
        if not self.bundle or not self.bundle.get('bars'):
            messagebox.showinfo(APP_NAME, '暂无可导出的数据。')
            return
        q = self.bundle['quote']
        default = '%s_%s_%s.csv' % (q.get('code', 'stock'), self.period,
                                    datetime.date.today().isoformat())
        path = filedialog.asksaveasfilename(
            title='导出 K 线数据', defaultextension='.csv',
            initialfile=default, filetypes=[('CSV 文件', '*.csv')])
        if not path:
            return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as fp:
                w = csv.writer(fp)
                w.writerow(['日期', '开盘', '最高', '最低', '收盘', '涨跌额', '涨跌幅%',
                            '振幅%', '成交量', '成交额', '换手率%'])
                for b in self.bundle['bars']:
                    w.writerow([b['d'], b['o'], b['h'], b['l'], b['c'], b['chg'],
                                b['pct'], b['amp'], b['v'], b['amt'], b['turn']])
            self.status('已导出 %s' % path, TEXT)
        except Exception as exc:                          # noqa: BLE001
            messagebox.showerror(APP_NAME, '导出失败：%s' % exc)

    def _export_report(self):
        if not self.bundle or not self.analysis:
            messagebox.showinfo(APP_NAME, '暂无可导出的分析。')
            return
        q = self.bundle['quote']
        default = '%s_分析报告_%s.txt' % (q.get('code', 'stock'),
                                          datetime.date.today().isoformat())
        path = filedialog.asksaveasfilename(
            title='导出分析报告', defaultextension='.txt',
            initialfile=default, filetypes=[('文本文件', '*.txt')])
        if not path:
            return
        lines = report_lines(self.bundle, self.analysis, self.period, self.adjust)
        try:
            with open(path, 'w', encoding='utf-8') as fp:
                fp.write('\n'.join(lines))
            self.status('已导出 %s' % path, TEXT)
        except Exception as exc:                          # noqa: BLE001
            messagebox.showerror(APP_NAME, '导出失败：%s' % exc)


def _c(value, ref):
    """相对参考值着色（大于参考=红，小于=绿）。"""
    if value is None or ref is None:
        return TEXT
    try:
        if value > ref:
            return UP
        if value < ref:
            return DOWN
    except TypeError:
        return TEXT
    return FLAT


def _avg_price(q):
    amt, vol = q.get('amount'), q.get('volume')
    if not amt or not vol:
        return None
    lots = 100.0 if q.get('kind') == 'A' else 1.0
    return amt / (vol * lots)


def _sign_money(v):
    if v is None:
        return '—'
    return ('+' if v >= 0 else '-') + an._big(abs(v))


def report_lines(bundle, res, period, adjust):
    """把一次分析渲染成纯文本报告（界面导出与命令行自检共用）。"""
    q = bundle['quote']
    lines = []
    lines.append('%s 技术分析报告' % APP_NAME)
    lines.append('生成时间：%s' % datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    lines.append('标的：%s（%s）' % (q.get('name', ''), q.get('code', '')))
    lines.append('周期：%s    复权：%s' % (PERIOD_NAME.get(period, period),
                                        ADJUST_NAME.get(adjust, adjust)))
    lines.append('数据源：%s（K线：%s）' % (q.get('source', '—'),
                                        bundle.get('kline_source', '—')))
    lines.append('')
    lines.append('最新价 %s   涨跌幅 %s   换手率 %s   量比 %s'
                 % (fmt(q.get('price'), 2), fmt_signed(q.get('pct'), 2, '%'),
                    fmt(q.get('turnover'), 2, '%'), fmt(q.get('vol_ratio'), 2)))
    lines.append('')
    lines.append('技术面综合评分：%.0f / 100（%s）' % (res['score'], res['level']))
    lines.append(res['verdict'])
    lines.append(res['plain'])
    lines.append(res['summary'])
    lines.append('')
    lines.append('【分维度评分】')
    for d in res['dims']:
        lines.append('  %-4s %.0f 分 —— %s' % (d['name'], d['score'], d['note']))
    lines.append('  波动风险 %.0f 分（%s）' % (res['risk']['score'],
                                          res['risk']['level']))
    lines.append('')
    lines.append('【多空信号对照】')
    for t in res['bulls']:
        lines.append('  ▲ ' + t)
    for t in res['bears']:
        lines.append('  ▼ ' + t)
    lines.append('')
    lines.append('【关键价位】')
    for name, price in res['resists']:
        lines.append('  压力  %-10s %s' % (name, fmt(price, 2)))
    lines.append('  当前  %-10s %s' % ('现价', fmt(q.get('price'), 2)))
    for name, price in res['supports']:
        lines.append('  支撑  %-10s %s' % (name, fmt(price, 2)))
    lines.append('')
    for title, items in res['sections']:
        lines.append('【%s】' % title)
        for text, _tone in items:
            lines.append('  · ' + text)
        lines.append('')
    lines.append('【情景应对】')
    for name, cond, mean, _t in res['scenarios']:
        lines.append('  %s：%s —— %s' % (name, cond, mean))
    lines.append('')
    fin = bundle.get('finance') or {}
    if fin:
        lines.append('【财务摘要 %s】' % fin.get('_period', '—'))
        for k in ('营业总收入(元)', '营收同比(%)', '归母净利润(元)', '净利同比(%)',
                  '净资产收益率(%)', '销售毛利率(%)', '销售净利率(%)',
                  '资产负债率(%)', '每股收益(元)', '每股净资产(元)'):
            if fin.get(k) is not None:
                lines.append('  %s：%s' % (k, fin.get(k)))
        lines.append('')
    lines.append('-' * 60)
    lines.append(DISCLAIMER)
    return lines


def headless_report(targets, out_path, period='day', adjust='qfq'):
    """命令行自检：不开窗口，联网取数并输出分析报告（用于验证打包后的 exe）。"""
    chunks = []
    for code in targets:
        chunks.append('=' * 60)
        chunks.append('标的输入：%s' % code)
        try:
            secid = ds.resolve(code)[0]
            bundle = ds.load_all(secid, period, adjust)
            if not bundle or not bundle.get('bars'):
                chunks.append('  × 未取到 K 线数据')
                continue
            bars = bundle['bars']
            ind = an.compute_indicators(bars)
            res = an.build_analysis(bundle['quote'], bars, ind,
                                    bundle.get('flow'), bundle.get('finance'),
                                    bench=bundle.get('bench_bars') or None,
                                    bench_name=bundle.get('bench_name') or '',
                                    period=period)
            chunks.extend(report_lines(bundle, res, period, adjust))
        except Exception as exc:                            # noqa: BLE001
            import traceback
            chunks.append('  × 失败：%s' % exc)
            chunks.append(traceback.format_exc())
        chunks.append('')
    text = '\n'.join(chunks)
    with open(out_path, 'w', encoding='utf-8') as fp:
        fp.write(text)
    return text


def main():
    if '--selftest' in sys.argv:
        i = sys.argv.index('--selftest')
        rest = [x for x in sys.argv[i + 1:] if not x.startswith('--')]
        out = rest[0] if rest else os.path.join(
            os.path.dirname(os.path.abspath(sys.argv[0])), 'selftest_report.txt')
        codes = rest[1:] or ['600519', '000001', '00700', 'AAPL']
        text = headless_report(codes, out)
        try:
            sys.__stdout__ and sys.__stdout__.write('OK -> %s (%d chars)\n'
                                                    % (out, len(text)))
        except Exception:                                   # noqa: BLE001
            pass
        return

    scale = enable_dpi()
    root = tk.Tk()
    try:
        root.tk.call('tk', 'scaling', scale * 1.3333)
    except Exception:                                     # noqa: BLE001
        pass

    def on_error(exc, val, tb):
        import traceback
        detail = ''.join(traceback.format_exception(exc, val, tb))
        try:
            messagebox.showerror(APP_NAME, '程序出现异常：\n%s' % val)
        except Exception:                                 # noqa: BLE001
            pass
        sys.__stderr__ and sys.__stderr__.write(detail)
    root.report_callback_exception = on_error

    StockApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
