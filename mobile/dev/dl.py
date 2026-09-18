# -*- coding: utf-8 -*-
"""带断点续传和进度日志的下载器。用法：dl.py <url> <目标文件> [日志文件]"""
import os
import ssl
import sys
import time
import urllib.request

url = sys.argv[1]
dest = sys.argv[2]
logf = sys.argv[3] if len(sys.argv) > 3 else dest + '.log'
os.makedirs(os.path.dirname(dest), exist_ok=True)

ctx = ssl.create_default_context()
pos = os.path.getsize(dest) if os.path.exists(dest) else 0
headers = {'User-Agent': 'Mozilla/5.0'}
if pos:
    headers['Range'] = 'bytes=%d-' % pos

req = urllib.request.Request(url, headers=headers)
t0 = time.time()
with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
    total = int(r.headers.get('Content-Length') or 0) + pos
    mode = 'ab' if pos and r.status == 206 else 'wb'
    if mode == 'wb':
        pos = 0
    done = pos
    with open(dest, mode) as fp, open(logf, 'w', encoding='utf-8') as lg:
        lg.write('url=%s\ntotal=%s\n' % (url, total))
        lg.flush()
        while True:
            chunk = r.read(262144)
            if not chunk:
                break
            fp.write(chunk)
            done += len(chunk)
            if done % (4 * 1048576) < 262144:
                pct = (done * 100.0 / total) if total else 0
                sp = done / max(0.001, time.time() - t0) / 1048576.0
                lg.write('%.1f%% %.1f/%.1fMB %.2fMB/s\n'
                         % (pct, done / 1048576.0, total / 1048576.0, sp))
                lg.flush()
with open(logf, 'a', encoding='utf-8') as lg:
    lg.write('DONE size=%d elapsed=%.1fs\n' % (os.path.getsize(dest),
                                               time.time() - t0))
print('done', dest, os.path.getsize(dest))
