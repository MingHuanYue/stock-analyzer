# -*- coding: utf-8 -*-
"""在安卓模拟器上真装一遍 APK：建 AVD -> 启动 -> 安装 -> 运行 -> 截图 -> 抓日志。"""
import os
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                           # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, 'tools', 'android-sdk')
ADB = os.path.join(SDK, 'platform-tools', 'adb.exe')
EMU = os.path.join(SDK, 'emulator', 'emulator.exe')
AVDM = os.path.join(SDK, 'cmdline-tools', 'latest', 'bin', 'avdmanager.bat')
JDK = os.path.join(ROOT, 'tools', 'jdk')
IMG = 'system-images;android-30;google_apis;x86_64'
AVD = 'saTest'
APK = os.path.join(ROOT, '发布', '股票分析助手.apk')
PKG = 'com.mingyue.stockanalyzer'
OUT = os.path.join(ROOT, 'dev')
LOG = os.path.join(OUT, '_emu_report.txt')

env = dict(os.environ)
env['JAVA_HOME'] = JDK
env['PATH'] = os.path.join(JDK, 'bin') + os.pathsep + env.get('PATH', '')
env['ANDROID_SDK_ROOT'] = SDK
env['ANDROID_HOME'] = SDK
env['ANDROID_AVD_HOME'] = os.path.join(os.environ.get('USERPROFILE', ''), '.android', 'avd')

lines = []


def say(s):
    lines.append(str(s))
    print(s)
    try:
        with open(LOG, 'w', encoding='utf-8') as fp:
            fp.write('\n'.join(lines))
    except Exception:                                       # noqa: BLE001
        pass


def run(cmd, timeout=180, check=False):
    p = subprocess.run(cmd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT, timeout=timeout)
    out = p.stdout.decode('utf-8', 'replace')
    if check and p.returncode != 0:
        say('!! 失败: ' + ' '.join(cmd))
        say(out[-1500:])
        raise SystemExit(1)
    return p.returncode, out


def adb(*args, timeout=120):
    return run([ADB] + list(args), timeout=timeout)


def main():
    for p, n in ((ADB, 'adb'), (EMU, 'emulator'), (AVDM, 'avdmanager'), (APK, 'apk')):
        if not os.path.exists(p):
            say('缺少 %s: %s' % (n, p))
            return 1
    say('APK: %.1f KB' % (os.path.getsize(APK) / 1024.0))

    # 1) 建 AVD
    rc, out = run([AVDM, 'list', 'avd'], timeout=90)
    if (AVD + ' ') not in out and ('"' + AVD + '"') not in out and AVD not in out:
        say('创建 AVD %s …' % AVD)
        rc, out = run([AVDM, 'create', 'avd', '-n', AVD, '-k', IMG,
                       '-d', 'pixel_5', '--force'], timeout=180)
        say(out.strip()[-400:])
        if rc != 0:
            say('!! AVD 创建失败')
            return 1
    else:
        say('AVD %s 已存在' % AVD)

    # 2) 先起 adb 服务！顺序反了模拟器会报
    #    "Unable to connect to adb daemon on port: 5037"，设备永远停在 offline
    say('先启动 adb 服务…')
    adb('kill-server', timeout=60)
    rc, out = adb('start-server', timeout=120)
    say('  ' + out.strip()[:200])

    # 3) 启动模拟器
    say('启动模拟器（无窗口，软件渲染）…')
    logf = open(os.path.join(OUT, '_emu_stdout.txt'), 'w', encoding='utf-8')
    proc = subprocess.Popen([
        EMU, '-avd', AVD, '-no-window', '-no-audio', '-no-boot-anim',
        '-no-snapshot', '-gpu', 'swiftshader_indirect', '-no-metrics',
        '-netdelay', 'none', '-netspeed', 'full',
        '-port', '5554'
    ], env=env, stdout=logf, stderr=subprocess.STDOUT)

    # 4) 等设备上线 + 开机完成
    say('等待设备上线…')
    online = False
    for i in range(60):
        time.sleep(5)
        rc, out = adb('devices', timeout=30)
        if re.search(r'emulator-\d+\s+device', out):
            online = True
            say('设备已连接（%d 秒）' % ((i + 1) * 5))
            break
        if 'offline' in out and i and i % 6 == 5:
            adb('reconnect', 'offline', timeout=30)
    if not online:
        say('!! 设备未上线')
        say(open(os.path.join(OUT, '_emu_stdout.txt'), encoding='utf-8',
                 errors='replace').read()[-1500:])
        proc.kill()
        return 1

    booted = False
    for i in range(90):
        time.sleep(5)
        rc, out = adb('shell', 'getprop', 'sys.boot_completed', timeout=30)
        if '1' in out.strip():
            booted = True
            say('开机完成（等待 %d 秒）' % ((i + 1) * 5))
            break
        if i and i % 12 == 11:
            say('  仍在开机… %d 秒（bootanim=%s）'
                % ((i + 1) * 5, adb('shell', 'getprop', 'init.svc.bootanim',
                                    timeout=30)[1].strip()))
    if not booted:
        say('!! 开机超时')
        say(open(os.path.join(OUT, '_emu_stdout.txt'), encoding='utf-8',
                 errors='replace').read()[-1500:])
        proc.kill()
        return 1

    time.sleep(8)
    rc, out = adb('shell', 'getprop', 'ro.build.version.release')
    say('安卓版本: ' + out.strip())
    rc, out = adb('shell', 'dumpsys', 'package', 'com.google.android.webview',
                  timeout=60)
    m = re.search(r'versionName=(\S+)', out)
    say('系统 WebView 版本: ' + (m.group(1) if m else '未知'))

    # 4) 安装
    say('安装 APK …')
    rc, out = adb('install', '-r', '-g', APK, timeout=300)
    say(out.strip()[-500:])
    if 'Success' not in out:
        say('!! 安装失败')
        proc.kill()
        return 1
    say('安装成功')

    rc, out = adb('shell', 'pm', 'list', 'packages', PKG)
    say('包已注册: ' + ('是' if PKG in out else '否'))

    # 5) 清日志并启动
    adb('logcat', '-c', timeout=30)
    say('启动应用 …')
    rc, out = adb('shell', 'am', 'start', '-W', '-n',
                  PKG + '/.MainActivity', timeout=120)
    say(out.strip()[-400:])

    # 6) 等页面加载 + 联网取数
    for wait in (12, 14, 16, 18):
        time.sleep(wait)
        rc, out = adb('shell', 'dumpsys', 'window', 'windows', timeout=60)
        if PKG in out:
            break
    say('等待页面联网取数（约 60 秒）…')
    time.sleep(45)

    # 7) 截图
    for name in ('emu_1.png', 'emu_2.png'):
        rc, out = adb('exec-out', 'screencap', '-p', timeout=120)
        # exec-out 走二进制，需要重新取
        p = subprocess.run([ADB, 'exec-out', 'screencap', '-p'], env=env,
                           stdout=subprocess.PIPE)
        path = os.path.join(OUT, name)
        with open(path, 'wb') as fp:
            fp.write(p.stdout)
        say('截图 %s  %d KB' % (name, os.path.getsize(path) // 1024))
        time.sleep(6)

    # 8) 日志
    rc, out = adb('logcat', '-d', '-v', 'brief', timeout=120)
    with open(os.path.join(OUT, '_emu_logcat.txt'), 'w', encoding='utf-8') as fp:
        fp.write(out)
    keys = ('AndroidRuntime', 'chromium', 'WebView', 'stockanalyzer', 'crash',
            'FATAL', 'ANR', 'ResourceNotFound')
    hits = [l for l in out.splitlines() if any(k.lower() in l.lower() for k in keys)]
    say('---- 相关日志（%d 行，取前 40）----' % len(hits))
    for l in hits[:40]:
        say('  ' + l[:190])

    # 9) 进程还活着吗
    rc, out = adb('shell', 'pidof', PKG, timeout=30)
    alive = bool(out.strip())
    say('应用进程存活: ' + ('是 pid=' + out.strip() if alive else '否（可能已崩溃）'))

    # 10) 交互验证：输入代码查询
    if alive:
        say('---- 交互测试：输入 00700 并点查询 ----')
        adb('shell', 'input', 'tap', '180', '76', timeout=60)
        time.sleep(1)
        for ch in ('0', '0', '7', '0', '0'):
            adb('shell', 'input', 'text', ch, timeout=30)
            time.sleep(0.3)
        adb('shell', 'input', 'keyevent', '66', timeout=30)   # 回车
        time.sleep(40)
        p = subprocess.run([ADB, 'exec-out', 'screencap', '-p'], env=env,
                           stdout=subprocess.PIPE)
        path = os.path.join(OUT, 'emu_hk.png')
        with open(path, 'wb') as fp:
            fp.write(p.stdout)
        say('截图 emu_hk.png  %d KB' % (os.path.getsize(path) // 1024))
        rc, out = adb('shell', 'pidof', PKG, timeout=30)
        say('交互后进程存活: ' + ('是' if out.strip() else '否'))

    say('关闭模拟器')
    try:
        adb('emu', 'kill', timeout=30)
    except Exception:                                       # noqa: BLE001
        pass
    time.sleep(3)
    proc.kill()
    say('完成')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:                                # noqa: BLE001
        import traceback
        say('异常: ' + traceback.format_exc())
        sys.exit(1)
