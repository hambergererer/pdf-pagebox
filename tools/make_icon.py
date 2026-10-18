# -*- coding: utf-8 -*-
"""画一个 PageBox 的图标：蓝底、白纸、页脚一个小方块（选中的那一页）。

跑法：python tools/make_icon.py
产物：pagebox.ico
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "pagebox.ico")

BLUE = (31, 111, 235, 255)
BLUE_D = (20, 84, 186, 255)
WHITE = (255, 255, 255, 255)


def draw(size):
    ss = size * 4                      # 先画大四倍再缩，边缘就顺了
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    r = int(ss * 0.22)
    d.rounded_rectangle([0, 0, ss - 1, ss - 1], radius=r, fill=BLUE)

    # 纸张
    m = int(ss * 0.24)
    w = ss - 2 * m
    h = int(ss * 0.52)
    top = int(ss * 0.18)
    fold = int(w * 0.30)
    d.rounded_rectangle([m, top, m + w, top + h], radius=int(ss * 0.05), fill=WHITE)
    d.polygon([(m + w - fold, top), (m + w, top + fold), (m + w - fold, top + fold)], fill=(214, 226, 245, 255))

    # 纸上的几行字
    lx = m + int(w * 0.16)
    lw = int(w * 0.68)
    for i in range(3):
        ly = top + int(h * (0.42 + i * 0.14))
        d.rounded_rectangle([lx, ly, lx + int(lw * (1.0 if i < 2 else 0.6)), ly + max(2, int(ss * 0.022))],
                            radius=max(1, int(ss * 0.011)), fill=(188, 202, 224, 255))

    # 选中的那一页：右下角一个实心小方块
    side = int(ss * 0.26)
    bx = ss - m - side
    by = top + h - int(side * 0.42)
    d.rounded_rectangle([bx, by, bx + side, by + side], radius=int(side * 0.26), fill=BLUE_D,
                        outline=WHITE, width=max(2, int(ss * 0.022)))
    tick = int(side * 0.26)
    d.line([(bx + tick, by + side * 0.52), (bx + side * 0.44, by + side * 0.74),
            (bx + side - tick, by + side * 0.28)],
           fill=WHITE, width=max(3, int(ss * 0.032)), joint="curve")

    return img.resize((size, size), Image.Resampling.LANCZOS)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [draw(s) for s in sizes]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print("saved:", OUT, os.path.getsize(OUT), "bytes")
    prev = os.path.join(ROOT, "示例-图标.png")
    frames[-1].save(prev)
    print("saved:", prev)


if __name__ == "__main__":
    main()
