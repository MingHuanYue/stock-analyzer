# -*- coding: utf-8 -*-
"""数据层：行情、K线、分时、资金流、财务、搜索。

双数据源设计：
  主源  东方财富公开接口（字段最全：快照 / K线 / 分时 / 资金流 / 财务）
  备源  腾讯财经公开接口（快照 / K线，主源被限流或网络不通时自动接管）

全部使用标准库实现，便于打包为单文件 exe。

实测踩坑记录（勿随意改动）：
  1. K 线只有 push2his 节点返回完整数据，push2delay / push2 返回空 klines，
     必须按接口分别指定主机优先级，并对空结果做校验后回退。
  2. 请求必须使用「校验证书」的默认 SSL 上下文。跳过证书校验（CERT_NONE）
     会被 CDN 判定为异常客户端并路由到另一套后端，搜索接口会返回无关的 JSONP 数据。
  3. 搜索接口对请求头敏感，必须用最小请求头才能拿到 QuotationCodeTable。
  4. 东方财富对高频请求会短时阻断（RemoteDisconnected），因此需要备源兜底。
"""
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36')

HIS = 'https://push2his.eastmoney.com'
DELAY = 'https://push2delay.eastmoney.com'
LIVE = 'https://push2.eastmoney.com'

HOST_ORDER = {
    '/api/qt/stock/kline/get': (HIS, DELAY, LIVE),
    '/api/qt/stock/trends2/get': (DELAY, HIS, LIVE),
}
DEFAULT_HOSTS = (DELAY, LIVE, HIS)

SEARCH_TOKEN = 'D43BF722C8E33BDC906FB84D85E326E8'
DATACENTER = 'https://datacenter-web.eastmoney.com'

SRC_EM = '东方财富'
SRC_TX = '腾讯财经'


class DataError(Exception):
    """数据获取失败。"""


_SSL_INSECURE = ssl.create_default_context()
_SSL_INSECURE.check_hostname = False
_SSL_INSECURE.verify_mode = ssl.CERT_NONE


def _open(req, timeout):
    """优先使用校验证书的默认上下文，仅在校验失败时降级（见模块说明第 2 条）。"""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except Exception as exc:                              # noqa: BLE001
        reason = getattr(exc, 'reason', exc)
        if isinstance(reason, ssl.SSLError) or 'certificate' in str(reason).lower():
            return urllib.request.urlopen(req, timeout=timeout, context=_SSL_INSECURE)
        raise


def http_get(url, referer=None, minimal=False, encoding='utf-8', timeout=8):
    if minimal:
        headers = {'User-Agent': 'Mozilla/5.0'}
    else:
        headers = {
            'User-Agent': UA,
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        if referer:
            headers['Referer'] = referer
    req = urllib.request.Request(url, headers=headers)
    with _open(req, timeout) as resp:
        return resp.read().decode(encoding, 'ignore')


def _strip_jsonp(txt):
    s = txt.strip()
    i = s.find('(')
    if s[:6] == 'jQuery' or (i > 0 and s[:1] not in '{['):
        s = s[i + 1:].rstrip()
        if s.endswith(')'):
            s = s[:-1]
    return s


def em_get(path, params, validate=None, referer='https://quote.eastmoney.com/', hosts=None):
    qs = urllib.parse.urlencode(params)
    hosts = hosts or HOST_ORDER.get(path, DEFAULT_HOSTS)
    errs = []
    for rnd in range(2):
        for host in hosts:
            try:
                data = json.loads(http_get(host + path + '?' + qs, referer=referer))
            except Exception as exc:                       # noqa: BLE001
                errs.append(type(exc).__name__)
                continue
            if validate is not None and not validate(data):
                errs.append('空')
                continue
            return data
        if rnd == 0:
            time.sleep(0.35)
    raise DataError('东方财富接口不可用（%s）' % '，'.join(errs[:4]))


def _has_klines(d):
    return bool(isinstance(d, dict) and (d.get('data') or {}).get('klines'))


def _has_trends(d):
    return bool(isinstance(d, dict) and (d.get('data') or {}).get('trends'))


def _has_data(d):
    return bool(isinstance(d, dict) and d.get('data'))


# --------------------------------------------------------------------------
# 代码解析
# --------------------------------------------------------------------------

def guess_secid(text):
    t = (text or '').strip().upper()
    if not t:
        return None
    if re.match(r'^\d+\.[A-Za-z0-9._]+$', t):
        return t
    if re.match(r'^\d{6}$', t):
        return ('1.' if t[0] in '69' else '0.') + t
    if re.match(r'^\d{5}$', t):
        return '116.' + t
    return None


def code_of(secid):
    return secid.split('.', 1)[1] if '.' in secid else secid


def market_kind(secid):
    m = secid.split('.', 1)[0]
    if m in ('0', '1'):
        return 'A'
    if m == '116':
        return 'HK'
    if m in ('105', '106', '107'):
        return 'US'
    return 'OTHER'


def secucode(secid):
    code, m = code_of(secid), secid.split('.', 1)[0]
    if m == '1':
        return code + '.SH'
    if m == '0':
        return code + ('.BJ' if code[:1] in '48' else '.SZ')
    if m == '116':
        return code + '.HK'
    return code


def tx_symbol(secid):
    """东方财富 secid -> 腾讯行情代码。

    美股必须带交易所后缀：105=纳斯达克(.OQ) / 106=纽交所(.N) / 107=美交所(.A)，
    不带后缀的 usAAPL 只会返回 2 条 K 线。
    """
    m, code = secid.split('.', 1)[0], code_of(secid)
    if m == '1':
        return 'sh' + code
    if m == '0':
        return ('bj' if code[:1] in '48' else 'sz') + code
    if m == '116':
        return 'hk' + code.zfill(5)
    if m in ('105', '106', '107'):
        suffix = {'105': '.OQ', '106': '.N', '107': '.A'}[m]
        return 'us' + code.upper() + suffix
    return code


# --------------------------------------------------------------------------
# 搜索
# --------------------------------------------------------------------------

def _parse_sina_suggest(txt):
    out = []
    parts = txt.split('"', 2)
    if len(parts) < 2:
        return out
    for row in parts[1].split(';'):
        p = row.split(',')
        if len(p) < 4:
            continue
        name, code, sym = p[0], p[2], p[3].lower()
        if sym.startswith('sh'):
            secid = '1.' + code
        elif sym.startswith('sz') or sym.startswith('bj'):
            secid = '0.' + code
        elif sym.startswith('hk'):
            secid = '116.' + code.zfill(5)
        elif sym.startswith('gb_'):
            secid = '105.' + code.upper()
        else:
            continue
        out.append({'secid': secid, 'code': code, 'name': name, 'market': '新浪'})
    return out


def search_stock(keyword):
    """搜索代码 / 名称 / 拼音。东财为主，新浪兜底。"""
    errs = []
    try:
        url = ('https://searchapi.eastmoney.com/api/suggest/get?input=%s&type=14&token=%s&count=12'
               % (urllib.parse.quote(keyword), SEARCH_TOKEN))
        data = json.loads(_strip_jsonp(http_get(url, minimal=True)))
        table = (data or {}).get('QuotationCodeTable') or {}
        out = []
        for item in (table.get('Data') or []):
            secid = item.get('QuoteID') or ''
            if not secid or '.' not in secid:
                continue
            out.append({
                'secid': secid,
                'code': item.get('Code', ''),
                'name': item.get('Name', ''),
                'market': item.get('SecurityTypeName') or item.get('Classify') or '',
            })
        if out:
            return out
        errs.append('东财空')
    except Exception as exc:                              # noqa: BLE001
        errs.append('东财%s' % type(exc).__name__)

    try:
        url = ('https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15,21,22,23,24,25,26,31,32,33,41'
               '&key=%s&name=sd' % urllib.parse.quote(keyword))
        txt = http_get(url, referer='https://finance.sina.com.cn', encoding='gbk')
        out = _parse_sina_suggest(txt)
        if out:
            return out
        errs.append('新浪空')
    except Exception as exc:                              # noqa: BLE001
        errs.append('新浪%s' % type(exc).__name__)

    raise DataError('没有找到「%s」，请改用 6 位股票代码重试。\n（%s）' % (keyword, '，'.join(errs)))


def resolve(keyword):
    """解析用户输入 -> (secid, 候选列表)。

    优先精确命中，避免「腾讯控股」这类查询多出一个「腾讯控股-R」而弹出选择框：
      1) 输入本身是代码（6 位 / 5 位 / secid）
      2) 候选里有代码与输入完全一致的（如 AAPL -> 105.AAPL）
      3) 候选里有名称与输入完全一致的
      4) 只有一个候选
    以上都不满足才把候选交给界面，让用户挑。
    """
    secid = guess_secid(keyword)
    if secid:
        return secid, []

    cands = search_stock(keyword)
    if not cands:
        raise DataError('没有找到「%s」。' % keyword)

    kw = keyword.strip()
    kwu = kw.upper()
    for c in cands:
        if c['code'].upper() == kwu:
            return c['secid'], []
    for c in cands:
        if c['name'].strip().replace(' ', '') == kw.replace(' ', ''):
            return c['secid'], []
    if len(cands) == 1:
        return cands[0]['secid'], []
    return cands[0]['secid'], cands


# --------------------------------------------------------------------------
# 行情快照：东财主源 + 腾讯备源
# --------------------------------------------------------------------------

QUOTE_FIELDS = ('f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f59,f60,'
                'f84,f85,f92,f116,f117,f162,f167,f168,f169,f170,f171')


def _em_quote(secid):
    data = em_get('/api/qt/stock/get', {'secid': secid, 'fields': QUOTE_FIELDS},
                  validate=_has_data)
    d = (data or {}).get('data')
    if not d:
        raise DataError('未获取到行情快照')

    dec = d.get('f59')
    dec = 2 if dec in (None, '-') else int(dec)
    scale = float(10 ** dec)

    def px(k):
        v = d.get(k)
        return None if v in (None, '-', '') else float(v) / scale

    def r100(k):
        v = d.get(k)
        return None if v in (None, '-', '') else float(v) / 100.0

    def raw(k):
        v = d.get(k)
        return None if v in (None, '-', '') else float(v)

    def ratio(k):
        """估值类字段：0 表示无数据，统一转成 None。"""
        v = r100(k)
        return v if v else None

    return {
        'secid': secid, 'code': d.get('f57') or code_of(secid), 'name': d.get('f58') or '',
        'kind': market_kind(secid), 'dec': dec, 'source': SRC_EM,
        'price': px('f43'), 'high': px('f44'), 'low': px('f45'), 'open': px('f46'),
        'preclose': px('f60'), 'change': px('f169'), 'pct': r100('f170'),
        'amplitude': r100('f171'), 'volume': raw('f47'), 'amount': raw('f48'),
        'vol_ratio': r100('f50'), 'limit_up': px('f51'), 'limit_down': px('f52'),
        'turnover': r100('f168'), 'pe': ratio('f162'), 'pb': ratio('f167'),
        'bps': raw('f92'),
        'total_cap': raw('f116'), 'float_cap': raw('f117'),
        'total_share': raw('f84'), 'float_share': raw('f85'),
    }


def _tx_quote(secid):
    sym = tx_symbol(secid)
    txt = http_get('https://qt.gtimg.cn/q=%s' % sym, referer='https://gu.qq.com/',
                   encoding='gbk')
    if '="' not in txt:
        raise DataError('腾讯行情返回格式异常')
    f = txt.split('="', 1)[1].rstrip('";\n\r ').split('~')
    if len(f) < 50:
        raise DataError('腾讯行情字段不足')

    kind = market_kind(secid)

    def num(i):
        """只在数值合理时返回，避免不同市场字段错位导致的假数据。"""
        try:
            v = float(f[i])
        except (ValueError, IndexError):
            return None
        return v

    def bounded(i, lo, hi):
        v = num(i)
        return v if (v is not None and lo < v < hi) else None

    pre = num(4)
    high, low = num(33), num(34)
    amp = None
    if None not in (high, low, pre) and pre:
        amp = (high - low) / pre * 100.0

    is_a = kind == 'A'
    return {
        'secid': secid, 'code': (f[2] if len(f) > 2 else code_of(secid)),
        'name': f[1] if len(f) > 1 else '', 'kind': kind,
        'dec': 2 if is_a else 3, 'source': SRC_TX,
        'price': num(3), 'high': high, 'low': low, 'open': num(5),
        'preclose': pre, 'change': num(31), 'pct': num(32), 'amplitude': amp,
        'volume': num(36),
        'amount': (num(37) * 1e4) if num(37) is not None else None,
        # 以下字段各市场字段位不一致，仅在 A 股（或取值明显合理）时采用
        'vol_ratio': bounded(49, 0, 60) if is_a else None,
        'limit_up': num(47) if is_a else None,
        'limit_down': num(48) if is_a else None,
        'turnover': bounded(38, 0, 100),
        'pe': bounded(39, 0.01, 20000),
        'pb': bounded(46, 0.01, 1000),
        'bps': None,
        'total_cap': (num(45) * 1e8) if (num(45) or 0) > 0 else None,
        'float_cap': (num(44) * 1e8) if (num(44) or 0) > 0 else None,
        'total_share': None, 'float_share': None,
    }


def fetch_quote(secid):
    try:
        return _em_quote(secid)
    except Exception:                                     # noqa: BLE001
        return _tx_quote(secid)


# --------------------------------------------------------------------------
# K 线：东财主源 + 腾讯备源
# --------------------------------------------------------------------------

KLT = {'day': 101, 'week': 102, 'month': 103}
FQT = {'qfq': 1, 'none': 0, 'hfq': 2}
TX_PERIOD = {'day': 'day', 'week': 'week', 'month': 'month'}


def _em_kline(secid, period, adjust, limit):
    params = {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': KLT.get(period, 101), 'fqt': FQT.get(adjust, 1),
        'beg': 0, 'end': 20500101,
    }
    data = em_get('/api/qt/stock/kline/get', params, validate=_has_klines)
    d = (data or {}).get('data') or {}
    bars = []
    for line in d.get('klines') or []:
        p = line.split(',')
        if len(p) < 11:
            continue
        try:
            bars.append({
                'd': p[0], 'o': float(p[1]), 'c': float(p[2]), 'h': float(p[3]),
                'l': float(p[4]), 'v': float(p[5]), 'amt': float(p[6]),
                'amp': float(p[7]), 'pct': float(p[8]), 'chg': float(p[9]),
                'turn': float(p[10]),
            })
        except ValueError:
            continue
    if not bars:
        raise DataError('东财 K 线为空')
    return d.get('name') or '', (bars[-limit:] if limit and len(bars) > limit else bars)


def _tx_kline(secid, period, adjust, limit, sym=None):
    sym = sym or tx_symbol(secid)
    per = TX_PERIOD.get(period, 'day')
    fq = '' if adjust == 'none' else adjust
    cnt = max(60, min(limit or 600, 800))
    url = ('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,%s,,,%d,%s'
           % (sym, per, cnt, fq))
    data = json.loads(http_get(url, referer='https://gu.qq.com/'))
    node = ((data or {}).get('data') or {}).get(sym) or {}
    arr = node.get(fq + per) or node.get(per)
    if not arr:
        for key, val in node.items():
            if isinstance(val, list) and val and key.endswith(per):
                arr = val
                break
    if not arr:
        raise DataError('腾讯 K 线为空')

    kfmt = market_kind(secid) != 'A'
    lots = 1.0 if kfmt else 100.0      # A 股成交量单位为手
    bars = []
    for row in arr:
        if not isinstance(row, list) or len(row) < 6:
            continue
        try:
            o, c, h, l, v = (float(row[1]), float(row[2]), float(row[3]),
                             float(row[4]), float(row[5]))
        except (ValueError, TypeError):
            continue
        if not o:
            continue
        bars.append({'d': row[0], 'o': o, 'c': c, 'h': h, 'l': l, 'v': v,
                     'amt': v * lots * (h + l + c + o) / 4.0,
                     'amp': None, 'pct': None, 'chg': None, 'turn': None})
    if not bars:
        raise DataError('腾讯 K 线解析失败')

    # 腾讯不返回涨跌幅 / 振幅，用相邻收盘价补齐
    for i in range(len(bars) - 1, -1, -1):
        prev = bars[i - 1]['c'] if i > 0 else bars[i]['o']
        b = bars[i]
        if prev:
            b['pct'] = (b['c'] - prev) / prev * 100.0
            b['chg'] = b['c'] - prev
            b['amp'] = (b['h'] - b['l']) / prev * 100.0
        else:
            b['pct'], b['chg'], b['amp'] = 0.0, 0.0, 0.0
    bars = bars[-limit:] if limit and len(bars) > limit else bars

    name = ''
    try:
        name = ((node.get('qt') or {}).get(sym) or [''])[1] or ''
    except Exception:                                     # noqa: BLE001
        pass
    return name, bars


def fetch_kline(secid, period='day', adjust='qfq', limit=760):
    """返回 (名称, K线列表, 数据源名)。东财失败自动切腾讯。"""
    try:
        name, bars = _em_kline(secid, period, adjust, limit)
        return name, bars, SRC_EM
    except Exception:                                     # noqa: BLE001
        name, bars = _tx_kline(secid, period, adjust, limit)
        return name, bars, SRC_TX


# 各市场的大盘基准（用于计算相对强弱）；前面的是首选，失败自动换下一个。
BENCHMARKS = {
    'A': (('1.000300', '沪深300'), ('1.000001', '上证指数')),
    'HK': (('116.HSCEI', '恒生国企指数'), ('116.HSI', '恒生指数')),
    'US': (('107.SPY', '标普500ETF'), ('105.QQQ', '纳斯达克100ETF')),
}
# 指数在腾讯行情里的代码（东财取不到时的兜底）
TX_INDEX = {'1.000300': 'sh000300', '1.000001': 'sh000001',
            '116.HSCEI': 'hkHSCEI', '116.HSI': 'hkHSI',
            '105.QQQ': 'usQQQ.OQ'}


def fetch_benchmark(secid, period='day', limit=160):
    """取对应市场的大盘基准 K 线，用于计算相对强弱。取不到就返回 ('', [])。"""
    kind = market_kind(secid)
    for sid, name in BENCHMARKS.get(kind, ()):
        try:
            _n, bars = _em_kline(sid, period, 'qfq', limit)
            if len(bars) >= 30:
                return name, bars
        except Exception:                                 # noqa: BLE001
            pass
    for sid, name in BENCHMARKS.get(kind, ()):
        sym = TX_INDEX.get(sid)
        if not sym:
            continue
        try:
            _n, bars = _tx_kline(sid, period,
                                 'none' if kind == 'US' else 'qfq', limit, sym=sym)
            if len(bars) >= 30:
                return name, bars
        except Exception:                                 # noqa: BLE001
            continue
    return '', []


# --------------------------------------------------------------------------
# 分时（仅东财）
# --------------------------------------------------------------------------

def fetch_trends(secid, ndays=1):
    params = {
        'secid': secid,
        'fields1': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
        'iscr': 0, 'ndays': ndays,
    }
    data = em_get('/api/qt/stock/trends2/get', params, validate=_has_trends)
    d = (data or {}).get('data') or {}
    pts = []
    for line in d.get('trends') or []:
        p = line.split(',')
        if len(p) < 8:
            continue
        try:
            pts.append({'t': p[0][-5:], 'd': p[0][:10], 'o': float(p[1]), 'c': float(p[2]),
                        'h': float(p[3]), 'l': float(p[4]), 'v': float(p[5]),
                        'amt': float(p[6]), 'avg': float(p[7])})
        except ValueError:
            continue
    if not pts:
        raise DataError('分时数据为空')
    return d.get('preClose'), d.get('name') or '', pts


# --------------------------------------------------------------------------
# 资金流（仅东财）
# --------------------------------------------------------------------------

def fetch_fundflow(secid, days=20):
    """资金流历史。

    daykline 接口只有 push2his 返回完整历史，其余节点只给当日一条，
    因此先单独指定 push2his，失败后再退回通用主机轮询。
    """
    fields2 = 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'
    params = {'secid': secid, 'lmt': days, 'klt': 101,
              'fields1': 'f1,f2,f3,f7', 'fields2': fields2}
    data = None
    for path, hosts in (('/api/qt/stock/fflow/daykline/get', (HIS,)),
                        ('/api/qt/stock/fflow/daykline/get', None),
                        ('/api/qt/stock/fflow/kline/get', None)):
        try:
            data = em_get(path, params, validate=_has_data, hosts=hosts)
            break
        except Exception:                                 # noqa: BLE001
            continue
    if not data:
        return []
    d = (data or {}).get('data') or {}
    rows = []
    for line in (d.get('klines') or []):
        p = line.split(',')
        if len(p) < 6:
            continue

        def f(i):
            try:
                return float(p[i])
            except (ValueError, IndexError):
                return None

        rows.append({'d': p[0], 'main': f(1), 'small': f(2), 'mid': f(3),
                     'big': f(4), 'huge': f(5)})
    return rows[-days:]


# --------------------------------------------------------------------------
# 财务（仅 A 股，仅东财）
# --------------------------------------------------------------------------

FIN_FIELDS = {
    'EPSJB': '每股收益(元)',
    'BPS': '每股净资产(元)',
    'TOTALOPERATEREVE': '营业总收入(元)',
    'TOTALOPERATEREVETZ': '营收同比(%)',
    'PARENTNETPROFIT': '归母净利润(元)',
    'PARENTNETPROFITTZ': '净利同比(%)',
    'ROEJQ': '净资产收益率(%)',
    'XSMLL': '销售毛利率(%)',
    'XSJLL': '销售净利率(%)',
    'ZCFZL': '资产负债率(%)',
    'MGJYXJJE': '每股经营现金流(元)',
}


def fetch_finance(secid):
    if market_kind(secid) != 'A':
        return {}
    url = (DATACENTER + '/api/data/v1/get?reportName=RPT_F10_FINANCE_MAINFINADATA'
           '&columns=' + ','.join(FIN_FIELDS.keys()) + ',REPORT_DATE_NAME,NOTICE_DATE,REPORT_DATE'
           '&filter=' + urllib.parse.quote('(SECUCODE="%s")' % secucode(secid)) +
           '&pageSize=2&sortColumns=REPORT_DATE&sortTypes=-1')
    try:
        data = json.loads(http_get(url, referer='https://data.eastmoney.com/'))
    except Exception:                                     # noqa: BLE001
        return {}
    rows = ((data or {}).get('result') or {}).get('data') or []
    if not rows:
        return {}
    r = rows[0]
    out = {'_period': r.get('REPORT_DATE_NAME') or (r.get('REPORT_DATE') or '')[:10],
           '_notice': (r.get('NOTICE_DATE') or '')[:10],
           '_source': SRC_EM}
    for key, label in FIN_FIELDS.items():
        out[label] = r.get(key)
    return out


# --------------------------------------------------------------------------
# 组合抓取
# --------------------------------------------------------------------------

def load_all(secid, period='day', adjust='qfq', limit=760, with_extra=True):
    """一次性取齐界面所需的全部数据。资金流/财务/大盘失败不影响主流程。"""
    quote = fetch_quote(secid)
    name, bars, ksrc = fetch_kline(secid, period, adjust, limit)
    if not quote.get('name'):
        quote['name'] = name
    flow, fin, bench = [], {}, ('', [])
    if with_extra:
        flow = fetch_fundflow(secid)
        fin = fetch_finance(secid)
        bench = fetch_benchmark(secid, period)
    return {'quote': quote, 'bars': bars, 'kline_source': ksrc, 'flow': flow,
            'finance': fin, 'bench_name': bench[0], 'bench_bars': bench[1]}
