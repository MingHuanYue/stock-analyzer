# -*- coding: utf-8 -*-
"""APK 静态验收：
1) aapt2 dump badging —— 包名 / 版本 / 权限 / 图标 / SDK
2) apksigner verify   —— v1/v2/v3 签名
3) 抽出 APK 内置的 assets/index.html，与 build/index.html 逐字节比对，
   确保手机里跑的就是浏览器里验证过的那一版。
"""
import hashlib
import os
import subprocess
import sys
import zipfile

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BT = os.path.join(ROOT, 'tools', 'android-sdk', 'build-tools', '34.0.0')
AAPT2 = os.path.join(BT, 'aapt2.exe')
APKSIGNER = os.path.join(BT, 'apksigner.bat')
JDK = os.path.join(ROOT, 'tools', 'jdk', 'bin')
APK = os.path.join(ROOT, '发布', '股票分析助手.apk')
SRC = os.path.join(ROOT, 'build', 'index.html')
OUT = os.path.join(ROOT, 'dev', '_apk_verify.txt')

env = dict(os.environ)
env['JAVA_HOME'] = os.path.join(ROOT, 'tools', 'jdk')
env['PATH'] = JDK + os.pathsep + env.get('PATH', '')

lines = []


def run(cmd, desc):
    p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    out = p.stdout.decode('utf-8', 'replace')
    lines.append('--- %s (rc=%d) ---' % (desc, p.returncode))
    lines.append(out.strip())
    return out, p.returncode


lines.append('APK: %s' % APK)
if os.path.exists(APK):
    lines.append('大小: %.1f KB  修改时间: %s'
                 % (os.path.getsize(APK) / 1024.0,
                    __import__('time').strftime(
                        '%Y-%m-%d %H:%M:%S',
                        __import__('time').localtime(os.path.getmtime(APK)))))
lines.append('')

badging, rc1 = run([AAPT2, 'dump', 'badging', APK], 'aapt2 dump badging')
_, rc2 = run([APKSIGNER, 'verify', '-v', '--print-certs', APK],
             'apksigner verify')

# 内置网页逐字节比对
same = False
if os.path.exists(APK) and os.path.exists(SRC):
    with zipfile.ZipFile(APK) as z:
        inner = z.read('assets/index.html')
    with open(SRC, 'rb') as fp:
        disk = fp.read()
    h1 = hashlib.sha256(inner).hexdigest()
    h2 = hashlib.sha256(disk).hexdigest()
    same = (h1 == h2)
    lines.append('')
    lines.append('--- 内置网页一致性 ---')
    lines.append('APK 内 assets/index.html : %d 字节  sha256=%s'
                 % (len(inner), h1))
    lines.append('build/index.html         : %d 字节  sha256=%s'
                 % (len(disk), h2))
    lines.append('逐字节一致: %s' % same)
    for kw in ['computeIndicators', 'buildAnalysis', 'rebuildHfq',
               '股票分析助手', '免责声明']:
        lines.append('  含 %-20s %s' % (kw, kw.encode('utf-8') in inner))

ver_ok = ('package:' in badging and 'application-icon-480' in badging)
sign_ok = ('Verifies' in ''.join(lines) or rc2 == 0)
lines.append('')
lines.append('======== 判定 ========')
lines.append('aapt2 解析: %s' % ('通过' if rc1 == 0 and ver_ok else '失败'))
lines.append('签名验证  : %s' % ('通过' if rc2 == 0 else '失败'))
lines.append('内置网页  : %s' % ('与已验证版本一致' if same else '不一致'))
lines.append('==== %s ====' % ('全部通过' if (rc1 == 0 and ver_ok and rc2 == 0
                                          and same) else '有问题'))

with open(OUT, 'w', encoding='utf-8') as fp:
    fp.write('\n'.join(lines))
print('\n'.join(lines[-20:]))
