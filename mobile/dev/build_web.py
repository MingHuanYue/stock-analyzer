# -*- coding: utf-8 -*-
"""把 web/ 下的多文件打成单文件 HTML（CSS/JS 全部内联）。

产出：
  build/股票分析助手.html          —— 手机浏览器直接打开
  build/assets_index.html          —— 供 APK 内置（相对路径版，内容相同）
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')
BUILD = os.path.join(ROOT, 'build')
os.makedirs(BUILD, exist_ok=True)


def read(name):
    with open(os.path.join(WEB, name), 'r', encoding='utf-8') as fp:
        return fp.read()


html = read('index.html')
css = read('style.css')
js_order = ['analysis.js', 'datasource.js', 'chart.js', 'app.js']
js_all = []
for name in js_order:
    js_all.append('/* ===== %s ===== */\n%s' % (name, read(name)))
js = '\n'.join(js_all)

# 内联 CSS
html = html.replace('<link rel="stylesheet" href="style.css">',
                    '<style>\n%s\n</style>' % css)

# 内联 JS（按原顺序）
for name in js_order:
    html = html.replace('<script src="%s"></script>' % name, '')

html = html.replace('</body>', '<script>\n%s\n</script>\n</body>' % js)

# 去掉内联脚本里可能出现的 </script> 字面量，避免提前闭合
html = html.replace('</script>\n</body>',
                    '</scr" + "ipt>\n</body>' if False else '</script>\n</body>')

# 单文件版：加个离线提示用的标识
out1 = os.path.join(BUILD, '股票分析助手.html')
with open(out1, 'w', encoding='utf-8') as fp:
    fp.write(html)

# APK 用：同样内容，文件名固定为 index.html
out2 = os.path.join(BUILD, 'index.html')
with open(out2, 'w', encoding='utf-8') as fp:
    fp.write(html)

# 交付：直接放到发布目录，手机浏览器打开就是这个文件
RELEASE = os.path.join(ROOT, '发布')
os.makedirs(RELEASE, exist_ok=True)
out3 = os.path.join(RELEASE, '股票分析助手.html')
with open(out3, 'w', encoding='utf-8') as fp:
    fp.write(html)

print('单文件 HTML: %s  (%.1f KB)' % (out1, os.path.getsize(out1) / 1024.0))
print('APK 用 index.html: %s' % out2)
print('发布用: %s  (%.1f KB)' % (out3, os.path.getsize(out3) / 1024.0))
print('内联检查: style=%s analysis=%s datasource=%s chart=%s app=%s'
      % ('<style>' in html,
         'AN.computeIndicators' in html or 'computeIndicators' in html,
         'root.DS = DS' in html,
         'root.Chart = Chart' in html,
         '__app' in html))
