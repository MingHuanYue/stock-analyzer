# -*- coding: utf-8 -*-
"""不依赖 Gradle 的 APK 构建：aapt2 -> javac -> d8 -> 组装 -> zipalign -> apksigner

产出 发布/股票分析助手.apk
"""
import os
import shutil
import subprocess
import sys
import zipfile

# 中文 Windows 控制台是 GBK，工具链输出里混着各种字符，容错一下别再崩
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                           # noqa: BLE001
    pass


def dec(b):
    """javac / keytool 在中文系统上输出 GBK，aapt2 输出 UTF-8，两种都兜住。"""
    for enc in ('utf-8', 'gbk', 'cp936'):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode('utf-8', 'replace')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# aapt2 / zipalign 这些 Windows 命令行工具打不开含中文的路径（实测报
# "failed to open directory"，路径里有中文就挂）。这里在本机用户目录下建一个
# ASCII 目录联接（junction）指向项目根，全程用联接路径调用工具。
LINK = os.path.join(os.environ.get('USERPROFILE') or 'C:\\', 'sabuild')


def ensure_link():
    """建立 ASCII 联接。已存在但不是指向本项目的联接时直接报错，绝不自动删。"""
    if os.path.exists(LINK):
        try:
            if os.path.samefile(LINK, ROOT):
                print('ASCII 联接已就绪: %s -> %s' % (LINK, ROOT))
                return
        except OSError:
            pass
        raise SystemExit(
            '!! %s 已存在且不是指向本项目的联接。\n'
            '   请手动确认后删除该目录，或改用别的路径。' % LINK)
    r = subprocess.run(['cmd', '/c', 'mklink', '/J', LINK, ROOT],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        print(r.stdout.decode('gbk', 'replace'))
        raise SystemExit('!! 创建目录联接失败')
    print('已创建 ASCII 联接: %s -> %s' % (LINK, ROOT))


ensure_link()

SDK = os.path.join(LINK, 'tools', 'android-sdk')
BT = os.path.join(SDK, 'build-tools', '34.0.0')
PLATFORM = os.path.join(SDK, 'platforms', 'android-34', 'android.jar')
JDK = os.path.join(LINK, 'tools', 'jdk', 'bin')
AAPT2 = os.path.join(BT, 'aapt2.exe')
ZIPALIGN = os.path.join(BT, 'zipalign.exe')
APKSIGNER = os.path.join(BT, 'apksigner.bat')
JAVAC = os.path.join(JDK, 'javac.exe')
KEYTOOL = os.path.join(JDK, 'keytool.exe')

AND = os.path.join(LINK, 'android')
WORK = os.path.join(LINK, 'build', 'apk')
RELEASE = os.path.join(LINK, '发布')
KS = os.path.join(LINK, 'android', 'stockanalyzer.keystore')
# 签名密码走环境变量，别写死在公开仓库里；keystore 文件本身不随仓库分发
KS_PASS = os.environ.get('STOCK_KS_PASS', '')
KS_ALIAS = os.environ.get('STOCK_KS_ALIAS', 'stockanalyzer')
if not KS_PASS:
    raise SystemExit('!! 请先设置签名密码环境变量 STOCK_KS_PASS'
                     '（keystore 文件放在 android/stockanalyzer.keystore，'
                     '不随仓库分发）')

PKG = 'com.mingyue.stockanalyzer'
APK_NAME = '股票分析助手.apk'

env = dict(os.environ)
env['JAVA_HOME'] = os.path.join(LINK, 'tools', 'jdk')
env['PATH'] = JDK + os.pathsep + env.get('PATH', '')


def run(cmd, desc, cwd=None):
    print('>>> %s' % desc)
    print('    ' + ' '.join(cmd))
    p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT)
    out = dec(p.stdout)
    if p.returncode != 0:
        print(out[-4000:])
        raise SystemExit('!! 失败(%d): %s' % (p.returncode, desc))
    if out.strip():
        tail = out.strip()[-1200:].replace('\n', '\n    ')
        try:
            print('    ' + tail)
        except UnicodeEncodeError:
            print('    ' + tail.encode('ascii', 'replace').decode('ascii'))
    return out


def check_env():
    missing = []
    for p in (AAPT2, ZIPALIGN, APKSIGNER, JAVAC, KEYTOOL, PLATFORM):
        if not os.path.exists(p):
            missing.append(p)
    if missing:
        print('缺少工具：')
        for m in missing:
            print('  ' + m)
        raise SystemExit(2)
    print('工具链就绪')


def clean():
    if os.path.exists(WORK):
        shutil.rmtree(WORK)
    os.makedirs(WORK)
    os.makedirs(os.path.join(WORK, 'gen'))
    os.makedirs(os.path.join(WORK, 'classes'))
    os.makedirs(os.path.join(WORK, 'dex'))
    os.makedirs(RELEASE, exist_ok=True)


def build():
    # 0) 网页资源
    idx = os.path.join(ROOT, 'build', 'index.html')
    if not os.path.exists(idx):
        raise SystemExit('!! 缺少 build/index.html，请先跑 dev/build_web.py')
    assets = os.path.join(WORK, 'assets')
    os.makedirs(assets, exist_ok=True)
    shutil.copy2(idx, os.path.join(assets, 'index.html'))
    print('assets: %.1f KB' % (os.path.getsize(os.path.join(assets, 'index.html'))
                               / 1024.0))

    # 1) 编译资源
    res_zip = os.path.join(WORK, 'res.zip')
    run([AAPT2, 'compile', '--dir', os.path.join(AND, 'res'), '-o', res_zip],
        'aapt2 compile')

    # 2) 链接资源 + 生成 R.java（同时把 assets 打进去）
    base_apk = os.path.join(WORK, 'base.apk')
    run([AAPT2, 'link',
         '-o', base_apk,
         '-I', PLATFORM,
         '--manifest', os.path.join(AND, 'AndroidManifest.xml'),
         '-A', assets,
         '--java', os.path.join(WORK, 'gen'),
         '--min-sdk-version', '21',
         '--target-sdk-version', '34',
         '--version-code', '1',
         '--version-name', '1.0',
         '--auto-add-overlay',
         res_zip],
        'aapt2 link')

    # 3) 编译 Java
    rjava = os.path.join(WORK, 'gen', *PKG.split('.'), 'R.java')
    main_java = os.path.join(AND, 'java', *PKG.split('.'), 'MainActivity.java')
    for p in (rjava, main_java):
        if not os.path.exists(p):
            raise SystemExit('!! 缺少源文件 ' + p)
    run([JAVAC, '-source', '8', '-target', '8', '-nowarn', '-encoding', 'UTF-8',
         '-bootclasspath', PLATFORM, '-cp', PLATFORM,
         '-d', os.path.join(WORK, 'classes'), rjava, main_java],
        'javac')

    # 4) dex
    classes = []
    for base, _dirs, files in os.walk(os.path.join(WORK, 'classes')):
        for f in files:
            if f.endswith('.class'):
                classes.append(os.path.join(base, f))
    if not classes:
        raise SystemExit('!! 没有生成任何 .class')
    run([os.path.join(BT, 'd8.bat'), '--release', '--lib', PLATFORM,
         '--min-api', '21', '--output', os.path.join(WORK, 'dex')] + classes,
        'd8')

    dex = os.path.join(WORK, 'dex', 'classes.dex')
    if not os.path.exists(dex):
        cands = [f for f in os.listdir(os.path.join(WORK, 'dex'))
                 if f.endswith('.dex')]
        if cands:
            dex = os.path.join(WORK, 'dex', cands[0])
        else:
            raise SystemExit('!! d8 没有产出 dex')
    print('    dex: %s (%.1f KB)' % (os.path.basename(dex),
                                     os.path.getsize(dex) / 1024.0))

    # 5) 组装：把 classes.dex 塞进 base.apk，并保证 resources.arsc 不压缩
    unsign = os.path.join(WORK, 'unsigned.apk')
    with zipfile.ZipFile(base_apk, 'r') as zin, \
            zipfile.ZipFile(unsign, 'w', zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            zi = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            zi.external_attr = item.external_attr
            if item.filename in ('resources.arsc',) or \
                    item.filename.startswith('res/') and item.filename.endswith('.png'):
                zi.compress_type = zipfile.ZIP_STORED
            else:
                zi.compress_type = zipfile.ZIP_DEFLATED
            zout.writestr(zi, data)
        zi = zipfile.ZipInfo('classes.dex', date_time=(2026, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        with open(dex, 'rb') as fp:
            zout.writestr(zi, fp.read())

    with zipfile.ZipFile(unsign, 'r') as z:
        names = z.namelist()
        arc = [i for i in z.infolist() if i.filename == 'resources.arsc']
        print('    APK 条目 %d，含 classes.dex=%s，resources.arsc 存储方式=%s'
              % (len(names), 'classes.dex' in names,
                 'STORED' if arc and arc[0].compress_type == zipfile.ZIP_STORED
                 else 'DEFLATED'))

    # 6) 对齐
    aligned = os.path.join(WORK, 'aligned.apk')
    run([ZIPALIGN, '-f', '-p', '4', unsign, aligned], 'zipalign')

    # 7) 签名（首次自动生成 keystore）
    if not os.path.exists(KS):
        run([KEYTOOL, '-genkeypair', '-keystore', KS, '-alias', KS_ALIAS,
             '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000',
             '-storepass', KS_PASS, '-keypass', KS_PASS,
             '-dname', 'CN=StockAnalyzer, OU=Mobile, O=Mingyue, L=Beijing, C=CN'],
            'keytool 生成签名证书')

    out_apk = os.path.join(RELEASE, APK_NAME)
    if os.path.exists(out_apk):
        os.remove(out_apk)
    run([APKSIGNER, 'sign', '--ks', KS, '--ks-key-alias', KS_ALIAS,
         '--ks-pass', 'pass:' + KS_PASS, '--key-pass', 'pass:' + KS_PASS,
         '--v1-signing-enabled', 'true', '--v2-signing-enabled', 'true',
         '--v3-signing-enabled', 'true',
         '--v4-signing-enabled', 'false',      # 关了就不生成多余的 .idsig 文件
         '--out', out_apk, aligned],
        'apksigner sign')

    print('\n==== 产物 ====')
    print('%s  %.2f MB' % (out_apk, os.path.getsize(out_apk) / 1048576.0))
    return out_apk


def verify(apk):
    print('\n==== 校验 ====')
    txt = run([AAPT2, 'dump', 'badging', apk], 'aapt2 dump badging')
    keep = []
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith(('package:', 'application-label', 'sdkVersion',
                         'targetSdkVersion', 'launchable-activity',
                         'uses-permission', 'application-icon-')):
            keep.append(s)
    for k in keep[:14]:
        print('    ' + k)

    v = run([APKSIGNER, 'verify', '--verbose', '--print-certs', apk],
            'apksigner verify')
    for line in v.splitlines():
        s = line.strip()
        if 'Verified using' in s or 'Signer #1 certificate DN' in s or \
                'Number of signers' in s or 'SHA-256 digest' in s:
            print('    ' + s)

    with zipfile.ZipFile(apk, 'r') as z:
        names = z.namelist()
        must = ['AndroidManifest.xml', 'classes.dex', 'resources.arsc',
                'assets/index.html']
        print('    必需条目: ' + ', '.join(
            '%s=%s' % (m, m in names) for m in must))
        print('    文件总数 %d' % len(names))
        html = z.read('assets/index.html').decode('utf-8')
        print('    assets/index.html 大小 %.1f KB，含 computeIndicators=%s'
              % (len(html) / 1024.0, 'computeIndicators' in html))
    return True


if __name__ == '__main__':
    check_env()
    clean()
    apk = build()
    verify(apk)
    print('\n完成')
