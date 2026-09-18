# -*- coding: utf-8 -*-
"""生成金标准：用桌面版 Python 引擎算一遍，把输入和输出都存成 JSON，
交给 Node 跑 JS 版逐字对拍。"""
import json
import os
import sys
import traceback

DESKTOP = r'D:\WorkBuddy各类缓存\工作空间默认存储\stock-analyzer'
sys.path.insert(0, DESKTOP)

import analysis as an                                          # noqa: E402
import datasource as ds                                        # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_golden.json')

CASES = [
    ('1.600519', 'day', 'qfq', '沪A 日线 前复权'),
    ('0.000001', 'day', 'qfq', '深A 日线 前复权'),
    ('0.300750', 'day', 'hfq', '深A 日线 后复权'),
    ('116.00700', 'day', 'qfq', '港股 日线 前复权'),
    ('105.AAPL', 'day', 'qfq', '美股 日线 前复权'),
    ('1.600519', 'week', 'qfq', '沪A 周线'),
    ('1.600519', 'month', 'none', '沪A 月线 不复权'),
]


def clean(o):
    """NaN/Infinity 换成 None，保证 JSON 可序列化。"""
    if isinstance(o, float):
        if o != o or o in (float('inf'), float('-inf')):
            return None
        return o
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    return o


cases = []
for secid, period, adjust, label in CASES:
    item = {'secid': secid, 'period': period, 'adjust': adjust, 'label': label}
    try:
        b = ds.load_all(secid, period, adjust)
        if not b or not b.get('bars'):
            item['error'] = '无 K 线数据'
            cases.append(item)
            continue
        bars = b['bars']
        ind = an.compute_indicators(bars)
        res = an.build_analysis(
            b['quote'], bars, ind, b.get('flow'), b.get('finance'),
            bench=b.get('bench_bars') or None,
            bench_name=b.get('bench_name') or '', period=period)
        item['quote'] = clean(b['quote'])
        item['bars'] = clean(bars)
        item['ind'] = clean(ind)
        item['flow'] = clean(b.get('flow') or [])
        item['finance'] = clean(b.get('finance') or {})
        item['bench'] = clean(b.get('bench_bars') or [])
        item['bench_name'] = b.get('bench_name') or ''
        item['expected'] = clean(res)
        item['ok'] = True
        print('OK  %-22s bars=%d score=%s' % (label, len(bars), res.get('score')))
    except Exception as exc:                                   # noqa: BLE001
        item['error'] = '%s: %s' % (type(exc).__name__, exc)
        item['trace'] = traceback.format_exc()
        print('ERR %-22s %s' % (label, item['error']))
    cases.append(item)

with open(OUT, 'w', encoding='utf-8') as fp:
    json.dump({'cases': cases}, fp, ensure_ascii=False)
print('写出 %s  (%d 个用例, 成功 %d)'
      % (OUT, len(cases), sum(1 for c in cases if c.get('ok'))))
