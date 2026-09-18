# -*- coding: utf-8 -*-
"""生成安卓启动图标（各密度 mipmap）。整幅方形出血，交给系统自己裁形状。"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, 'android', 'res')

S = 192          # 基准尺寸
SS = 4           # 超采样
W = S * SS
BG1 = (14, 18, 24, 255)
BG2 = (26, 36, 52, 255)
UP = (240, 69, 58, 255)
DN = (18, 184, 134, 255)
MA1 = (245, 166, 35, 255)
MA2 = (76, 141, 255, 255)
MA3 = (176, 107, 217, 255)


def build():
    img = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    plate = Image.new('RGBA', (W, W), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    for y in range(W):
        t = y / float(W - 1)
        col = tuple(int(BG1[i] + (BG2[i] - BG1[i]) * t) for i in range(3)) + (255,)
        pd.line([(0, y), (W, y)], fill=col)
    img.paste(plate, (0, 0))
    d = ImageDraw.Draw(img)

    u = W / float(S)
    # 网格
    for k in (0.26, 0.5, 0.74):
        y = int(S * k * u)
        d.line([(int(S * 0.10 * u), y), (int(S * 0.90 * u), y)],
               fill=(70, 86, 110, 120), width=max(1, int(1.4 * u)))

    def candle(cx, y_hi, y_lo, y_top, y_bot, col):
        half = 12.5 * u
        d.line([(cx, y_hi * u), (cx, y_lo * u)], fill=col, width=max(2, int(2.6 * u)))
        d.rounded_rectangle([cx - half, y_top * u, cx + half, y_bot * u],
                            radius=int(4 * u), fill=col)

    # 五根蜡烛，整幅向上
    candle(46 * u, 92, 158, 106, 150, DN)
    candle(78 * u, 72, 134, 84, 120, UP)
    candle(110 * u, 52, 110, 62, 96, UP)
    candle(142 * u, 38, 94, 48, 80, UP)
    candle(172 * u, 26, 78, 36, 64, UP)

    # 三条均线
    def poly(pts, col, wid):
        d.line([(int(x * u), int(y * u)) for x, y in pts], fill=col,
               width=max(2, int(wid * u)), joint='curve')

    poly([(38, 150), (78, 128), (118, 104), (156, 84), (172, 72)], MA3, 2.4)
    poly([(38, 138), (78, 116), (118, 92), (156, 72), (172, 60)], MA2, 2.4)
    poly([(38, 126), (78, 104), (118, 80), (156, 58), (172, 46)], MA1, 2.4)

    return img


base = build()
SIZES = {'mdpi': 48, 'hdpi': 72, 'xhdpi': 96, 'xxhdpi': 144, 'xxxhdpi': 192}
out = []
for name, px in SIZES.items():
    folder = os.path.join(RES, 'mipmap-' + name)
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, 'ic_launcher.png')
    base.resize((px, px), Image.LANCZOS).convert('RGB').save(p, 'PNG')
    out.append('%s  %dx%d  %d B' % (p, px, px, os.path.getsize(p)))

# 圆角预览，方便肉眼检查
prev = Image.new('RGBA', (S, S), (0, 0, 0, 0))
prev.paste(base.resize((S, S), Image.LANCZOS), (0, 0))
mask = Image.new('L', (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22),
                                       fill=255)
prev.putalpha(mask)
prev.save(os.path.join(ROOT, 'dev', '_icon_preview.png'))

print('\n'.join(out))
print('预览: dev/_icon_preview.png')
