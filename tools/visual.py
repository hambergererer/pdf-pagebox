# -*- coding: utf-8 -*-
"""开一次真窗口、造点内容、截图。跑完自己关掉。

跑法：python tools/visual.py
产物：tests/_ui.png
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import pymupdf as fitz  # noqa: E402
from PIL import ImageGrab  # noqa: E402

CN_FONT = "C:/Windows/Fonts/msyh.ttc"


def make_pdf(path, title, pages, tag):
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        kw = {"fontname": "msyh", "fontfile": CN_FONT} if os.path.isfile(CN_FONT) else {}
        page.insert_text((64, 92), title, fontsize=20, **kw)
        page.insert_text((64, 130), "第 %d 页 / 共 %d 页" % (i + 1, pages), fontsize=12, **kw)
        for k in range(10):
            page.insert_text((64, 180 + k * 30),
                             "%s 数据 %02d ................................" % (tag, k + 1),
                             fontsize=11, **kw)
        page.draw_rect(fitz.Rect(64, 520, 530, 650), color=(0.62, 0.62, 0.62))
        page.insert_text((80, 560), "这是一块区域，适合裁下来当素材", fontsize=13, **kw)
    doc.save(path)
    doc.close()


def main():
    tmp = tempfile.mkdtemp(prefix="pagebox_ui_")
    import store as S
    S.data_dir = lambda here: os.path.join(tmp, "data")

    import app as A
    A.enable_dpi_awareness()

    a = os.path.join(tmp, "季度运营报告.pdf")
    b = os.path.join(tmp, "渠道数据附录.pdf")
    make_pdf(a, "第一季度运营报告", 4, "营收")
    make_pdf(b, "渠道数据附录", 3, "渠道")

    win = A.App()
    win.geometry("1320x840+30+20")
    win.attributes("-topmost", True)
    win.update()
    win.deiconify()
    win.lift()
    for _ in range(30):
        win.update()
        time.sleep(0.02)

    win.open_path(a)
    for _ in range(60):
        win.update()
        time.sleep(0.02)

    # 第二个文件也开着，标签页才有东西看
    win.open_path(b)
    for _ in range(40):
        win.update()
        time.sleep(0.02)

    # 加两个标签，把第二个文件挂到「渠道」
    tag2 = win.store.add_tag("渠道")
    win.store.save()
    win.set_doc_tag(b, tag2["id"])

    win.open_path(a)
    for _ in range(40):
        win.update()
        time.sleep(0.02)

    # 裁几块下来
    pv = win.pages[0]
    win._take_clip(pv.x + 40, pv.y0 + 150, pv.x + pv.w - 40, pv.y0 + 260)
    win._take_clip(pv.x + 60, pv.y0 + 500, pv.x + pv.w - 60, pv.y0 + 660)
    pv2 = win.pages[1]
    win._take_clip(pv2.x + 50, pv.y0 + 160, pv2.x + pv.w - 50, pv.y0 + 300)
    for _ in range(40):
        win.update()
        time.sleep(0.02)

    # 选中两页，让工作区那栏也有东西
    win.toggle_page(0)
    win.toggle_page(2)
    win.add_selection()
    for _ in range(30):
        win.update()
        time.sleep(0.02)

    # 画几笔，红的一条、绿的一条，再高亮一块
    pv = win.pages[0]
    win.set_tool("pen")
    win.set_pen_color("#e06c75")
    win._pen_page = 0
    win._pen_points = [(pv.x + 40, pv.y0 + 250), (pv.x + 130, pv.y0 + 290),
                       (pv.x + 230, pv.y0 + 250), (pv.x + 320, pv.y0 + 320)]
    win._finish_stroke()
    win.set_pen_color("#98c379")
    win.set_pen_width(6.0)
    win._pen_page = 0
    win._pen_points = [(pv.x + 40, pv.y0 + 400), (pv.x + 180, pv.y0 + 420),
                       (pv.x + 330, pv.y0 + 390)]
    win._finish_stroke()
    win.set_tool("mark")
    win.set_pen_color("#e5c07b")
    win._pen_page = 0
    win._pen_points = [(pv.x + 60, pv.y0 + 520), (pv.x + 460, pv.y0 + 640)]
    win._finish_stroke()
    win.set_tool("pen")
    for _ in range(40):
        win.update()
        time.sleep(0.02)

    win.show_view("shelves")
    for _ in range(30):
        win.update()
        time.sleep(0.02)

    # 打开工作区视图：卡片墙
    win.open_shelf(0)
    for _ in range(60):
        win.update()
        time.sleep(0.02)

    # 裁切：拖出一个框，让它停在可调整状态
    win.set_tool("crop")
    pv = win.pages[0]
    ox, oy = win.canvas.canvasx(0), win.canvas.canvasy(0)

    def ev_at(cx, cy):
        return type("Ev", (), {"x": cx - ox, "y": cy - oy})()

    win._crop_press(ev_at(pv.x + 40, pv.y0 + 170))
    win._crop_drag(ev_at(pv.x + 420, pv.y0 + 420))
    win._crop_release(ev_at(pv.x + 420, pv.y0 + 420))
    for _ in range(30):
        win.update()
        time.sleep(0.02)

    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()

    # 浅色主题来一张
    win.set_theme("light")
    for _ in range(50):
        win.update()
        time.sleep(0.02)
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(
        os.path.join(ROOT, "示例-浅色.png"))

    win.set_theme("dark")
    for _ in range(50):
        win.update()
        time.sleep(0.02)

    # 两条都收起来，看看空间是不是真让出来了
    win.set_tool("select")
    win.toggle_sidebar()
    win.toggle_panel()
    for _ in range(60):
        win.update()
        time.sleep(0.02)
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(
        os.path.join(ROOT, "示例-收起.png"))
    win.toggle_sidebar()
    win.toggle_panel()
    for _ in range(40):
        win.update()
        time.sleep(0.02)

    # 设置面板
    win.open_settings()
    for _ in range(40):
        win.update()
        time.sleep(0.02)
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(
        os.path.join(ROOT, "示例-设置.png"))

    # 欢迎页：关掉文件之后中间那块「最近打开」
    if win.doc_path:
        win.close_path(win.doc_path)
    out = os.path.join(ROOT, "tests", "_ui.png")
    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(out)
    print("saved:", out, (w, h))

    win.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
