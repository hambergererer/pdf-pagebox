# -*- coding: utf-8 -*-
"""开一次真窗口、截一张图，用来核对界面长相。跑完自己关掉。

跑法：python tests/visual.py
产物：tests/_shot.png
"""

from __future__ import annotations

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import pymupdf as fitz  # noqa: E402
from PIL import ImageGrab  # noqa: E402

import app as pagebox  # noqa: E402

SAMPLE = os.path.join(HERE, "_sample.pdf")
SHOT = os.path.join(HERE, "_shot.png")

CN_FONT = "C:/Windows/Fonts/msyh.ttc"


def make_sample(path):
    doc = fitz.open()
    titles = ["第一季度运营报告", "附：渠道数据明细", "附录：术语表", "预算与排期", "签字页"]
    for i, title in enumerate(titles):
        page = doc.new_page(width=595, height=842)
        kwargs = {}
        if os.path.isfile(CN_FONT):
            kwargs = {"fontname": "msyh", "fontfile": CN_FONT}
        page.insert_text((64, 96), title, fontsize=22, **kwargs)
        page.insert_text((64, 140), "Page %d of 5" % (i + 1), fontsize=13)
        for k in range(12):
            page.insert_text((64, 190 + k * 26),
                             "· line %02d ................................................" % (k + 1),
                             fontsize=11)
        page.draw_rect(fitz.Rect(64, 560, 531, 700), color=(0.6, 0.6, 0.6))
    doc.save(path)
    doc.close()


def main():
    make_sample(SAMPLE)
    pagebox.WS_FILE = os.path.join(HERE, "_ws.json")
    if os.path.exists(pagebox.WS_FILE):
        os.remove(pagebox.WS_FILE)
    pagebox.enable_dpi_awareness()

    win = pagebox.App()
    win.geometry("1180x790+40+20")
    win.attributes("-topmost", True)
    win.update()
    win.deiconify()
    win.lift()

    def shot(name):
        for _ in range(30):
            win.update()
            time.sleep(0.02)
        x, y = win.winfo_rootx(), win.winfo_rooty()
        w, h = win.winfo_width(), win.winfo_height()
        path = os.path.join(HERE, name)
        ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(path)
        print("saved:", path)

    win.open_pdf(SAMPLE)
    for _ in range(60):
        win.update()
        time.sleep(0.02)
    win.toggle_page(0)
    win.toggle_page(1)
    win.toggle_page(3)
    for _ in range(80):
        win.update()
        time.sleep(0.02)
    win.add_selection()
    # 再选两页，保持选中状态截图，好核对选中样式和按钮状态
    win.toggle_page(1)
    win.toggle_page(4)
    for _ in range(100):
        win.update()
        time.sleep(0.02)
    win.jump_to_page(1)

    # 再开两个工作区，好看出标签栏和切换的样子
    win.shelves[0]["name"] = "正文"
    win.add_shelf()
    win.shelves[1]["name"] = "附录"
    win.add_shelf()
    win.shelves[2]["name"] = "备选"
    win.switch_shelf(0)
    for _ in range(40):
        win.update()
        time.sleep(0.02)

    # 一张：文件拖进窗口时浮出的提示牌
    win._show_drop_hint(True)
    shot("_shot_drop.png")
    win._show_drop_hint(False)

    # 一张：平时的样子
    shot("_shot.png")

    win.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
