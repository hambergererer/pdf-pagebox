# -*- coding: utf-8 -*-
"""PageBox 验收：从打开、选页、裁块到按标签合成。

跑法：python tests/smoke.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "vendor"))

import pymupdf as fitz  # noqa: E402

import pdflib as P  # noqa: E402
import store as S  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                        ("  -- " + str(detail)) if detail != "" else ""))
    if not ok:
        FAILS.append(name)


def pump(root, rounds=40):
    for _ in range(rounds):
        root.update()
        time.sleep(0.004)


def main():
    tmp = tempfile.mkdtemp(prefix="pagebox_test_")
    try:
        a = os.path.join(tmp, "报告 A.pdf")
        b = os.path.join(tmp, "附录 B.pdf")
        P.make_test_pdf(a, 3, "A")
        P.make_test_pdf(b, 2, "B")

        # ---------- 纯逻辑：合并整页
        items = [
            {"src": a, "page": 0, "title": "报告 A.pdf"},
            {"src": a, "page": 2, "title": "报告 A.pdf"},
            {"src": b, "page": 1, "title": "附录 B.pdf"},
        ]
        out = os.path.join(tmp, "merged.pdf")
        added, missing = P.merge_pages(items, out)
        check("合并整页：页数", added == 3, added)
        check("合并整页：没有丢文件", missing == [], missing)
        doc = fitz.open(out)
        texts = [doc.load_page(i).get_text().strip().split("\n")[0] for i in range(doc.page_count)]
        doc.close()
        check("合并整页：顺序对", texts == ["A page 1", "A page 3", "B page 2"], texts)

        # ---------- 数据层
        store_path = os.path.join(tmp, "data", "workspace.json")
        st = S.Store(store_path)
        check("默认有一个工作区", len(st.shelves) == 1, len(st.shelves))
        check("默认有一个标签", len(st.tags) == 1, st.tags)
        tag_b = st.add_tag("附录")
        check("能加标签", len(st.tags) == 2 and tag_b["name"] == "附录")
        check("标签颜色分开了", st.tags[0]["color"] != st.tags[1]["color"],
              [t["color"] for t in st.tags])

        st.open_doc(a)
        st.set_doc_tag(a, tag_b["id"])
        check("能给 PDF 挂标签", st.doc_tag(a) == tag_b["id"])

        m = st.add_material(a, 1, [60, 100, 400, 300])
        check("素材继承来源 PDF 的标签", m["tag_id"] == tag_b["id"], m["tag_id"])
        check("素材记下了区域", m["rect"] == [60.0, 100.0, 400.0, 300.0], m["rect"])

        st.save()
        st2 = S.Store(store_path)
        check("标签存得下来", len(st2.tags) == 2, len(st2.tags))
        check("素材存得下来", len(st2.materials) == 1, len(st2.materials))
        check("PDF 的标签存得下来", st2.doc_tag(a) == tag_b["id"])

        old = os.path.join(tmp, "old.json")
        with open(old, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "items": [
                {"src": a, "page": 0, "title": "报告 A.pdf", "added": ""}]}, fh)
        st3 = S.Store(old)
        check("老存档能读进来", len(st3.ws_items) == 1, st3.ws_items)
        check("老存档进来后有标签可用", len(st3.tags) >= 1)

        # ---------- 素材合成
        mats = [
            {"src": a, "page": 0, "rect": [60, 80, 500, 200], "tag_id": tag_b["id"]},
            {"src": a, "page": 1, "rect": [60, 80, 500, 400], "tag_id": tag_b["id"]},
            {"src": b, "page": 0, "rect": [60, 80, 500, 160], "tag_id": tag_b["id"]},
        ]
        mat_out = os.path.join(tmp, "mats.pdf")
        n = P.merge_materials(mats, mat_out)
        check("素材合成：块数", n == 3, n)
        doc = fitz.open(mat_out)
        check("素材合成：生成了页", doc.page_count >= 1, doc.page_count)
        pg = doc.load_page(0)
        check("素材合成：纸面是 A4",
              int(pg.rect.width) == 595 and int(pg.rect.height) == 842,
              (pg.rect.width, pg.rect.height))
        doc.close()

        # ---------- 两种排法：每行一张 vs 占满一行
        small = [
            {"src": a, "page": 0, "rect": [60, 80, 260, 160], "tag_id": tag_b["id"]},
            {"src": a, "page": 0, "rect": [60, 200, 260, 280], "tag_id": tag_b["id"]},
            {"src": a, "page": 0, "rect": [60, 320, 260, 400], "tag_id": tag_b["id"]},
            {"src": a, "page": 0, "rect": [60, 440, 260, 520], "tag_id": tag_b["id"]},
        ]
        g_out = os.path.join(tmp, "grid.pdf")
        n_g = P.merge_materials(small, g_out, layout="grid")
        d1 = fitz.open(g_out)
        p_grid = d1.page_count
        d1.close()
        s_out = os.path.join(tmp, "single4.pdf")
        n_s = P.merge_materials(small, s_out, layout="single")
        d2 = fitz.open(s_out)
        p_single = d2.page_count
        d2.close()
        check("两种排法都合得出来", n_g == 4 and n_s == 4, (n_g, n_s))
        check("素材多的时候都会自动分页", p_single >= 1 and p_grid >= 1, (p_grid, p_single))
        check("占满一行比每行一张省页数", p_grid <= p_single, (p_grid, p_single))

        # ---------- 界面流程
        import app as A
        S.data_dir = lambda here: os.path.join(tmp, "uidata")
        A.enable_dpi_awareness()
        win = A.App()
        win.withdraw()
        pump(win)

        win.open_path(a)
        pump(win)
        check("打开 PDF：排出了页", len(win.pages) == 3, len(win.pages))

        win.toggle_page(0)
        win.toggle_page(2)
        pump(win)
        check("能选页", win.selected == {0, 2}, sorted(win.selected))

        win.add_selection()
        pump(win)
        check("整页进了工作区", len(win.store.ws_items) == 2, len(win.store.ws_items))
        check("加入后清空选择", win.selected == set())

        pv = win.pages[1]
        win._take_clip(pv.x + 20, pv.y0 + 30, pv.x + 260, pv.y0 + 150)
        pump(win)
        check("裁切能取块", len(win.store.materials) == 1, len(win.store.materials))
        mat = win.store.materials[0]
        check("裁的块落在对的页上", mat["page"] == 1, mat["page"])
        check("裁的块范围合理",
              0 < mat["rect"][2] - mat["rect"][0] < 600
              and 0 < mat["rect"][3] - mat["rect"][1] < 850, mat["rect"])

        tag2 = win.store.add_tag("渠道")
        win.set_material_tag(mat["id"], tag2["id"])
        pump(win)
        check("能给素材改标签", win.store.material(mat["id"])["tag_id"] == tag2["id"])

        win.filter_tag(tag2["id"])
        pump(win)
        check("按标签筛选素材", len(win.visible_materials()) == 1, len(win.visible_materials()))
        win.filter_tag(None)
        pump(win)

        win.add_shelf()
        pump(win)
        check("能新建工作区", len(win.store.shelves) == 2, len(win.store.shelves))
        win.add_shelf()
        win.add_shelf()
        win.add_shelf()
        pump(win)
        check("工作区最多 4 个", len(win.store.shelves) == 4, len(win.store.shelves))

        before = len(win.tabbar.winfo_children())
        for _ in range(10):
            win.refresh_top_tabs()
        pump(win, 3)
        check("标签页反复重绘不堆控件", len(win.tabbar.winfo_children()) == before,
              (before, len(win.tabbar.winfo_children())))

        before = len(win.mat_inner.winfo_children())
        for _ in range(10):
            win.refresh_panel()
        pump(win, 3)
        check("素材池反复重绘不堆控件", len(win.mat_inner.winfo_children()) == before,
              (before, len(win.mat_inner.winfo_children())))

        mat_out2 = os.path.join(tmp, "ui_mats.pdf")
        n2 = P.merge_materials(win.visible_materials(), mat_out2)
        check("界面里攒的素材能合成", n2 == 1 and os.path.isfile(mat_out2), n2)

        # ---------- 画笔
        win.open_path(a)
        pump(win)
        win.set_tool("pen")
        win.set_pen_color("#98c379")
        pv = win.pages[0]
        win._pen_page = 0
        win._pen_points = [(pv.x + 30, pv.y0 + 40), (pv.x + 90, pv.y0 + 70),
                           (pv.x + 140, pv.y0 + 45)]
        win._finish_stroke()
        pump(win)
        check("画笔能画一笔", len(win.store.annots_of(a, 0)) == 1,
              len(win.store.annotations))
        if win.store.annots_of(a, 0):
            a0 = win.store.annots_of(a, 0)[0]
            check("笔画用的是选的颜色", a0["color"] == "#98c379", a0["color"])
            check("笔画存成了 PDF 坐标",
                  all(0 <= x <= 700 and 0 <= y <= 900 for x, y in a0["points"]),
                  a0["points"][:2])
        win.undo_stroke()
        pump(win)
        check("能撤销一笔", len(win.store.annots_of(a, 0)) == 0)

        # 高亮是矩形，存成 mark
        win.set_tool("mark")
        pv = win.pages[0]
        win._pen_page = 0
        win._pen_points = [(pv.x + 20, pv.y0 + 20), (pv.x + 200, pv.y0 + 120)]
        win._finish_stroke()
        pump(win)
        marks = [x for x in win.store.annots_of(a, 0) if x.get("kind") == "mark"]
        check("高亮能画一块", len(marks) == 1, len(marks))

        # ---------- 工作区能看见内容
        win.switch_shelf(0)          # 前面建了 4 个工作区，切回第一个
        win.show_view("shelves")
        pump(win)
        check("工作区里有页", len(win.store.ws_items) == 2, len(win.store.ws_items))
        win.jump_to_page(0)
        pump(win, 3)
        check("能跳到工作区里的页", True)
        win.remove_ws_item(0)
        pump(win)
        check("能从工作区移走一页", len(win.store.ws_items) == 1,
              len(win.store.ws_items))
        win.move_ws_item(0, 1)
        pump(win)

        # ---------- 拖动分栏时不该重建页面
        first = win.pages[0] if win.pages else None
        win._recenter()
        pump(win, 2)
        check("重摆位置时页面对象没被重建", win.pages and win.pages[0] is first)

        # ---------- 橡皮擦
        win.set_tool("pen")
        win.set_pen_color("#61afef")
        pv = win.pages[0]
        win._pen_page = 0
        y_line = pv.y0 + pv.h * 0.35
        win._pen_points = [(pv.x + 30 + i * 9, y_line) for i in range(20)]
        win._finish_stroke()
        pump(win)
        ink_before = sum(len(x["points"]) for x in win.store.annots_of(a, 0)
                         if x.get("kind") == "ink")
        check("画了一条长线", ink_before >= 15, ink_before)

        win.set_tool("eraser")
        # _erase_at 收的是窗口坐标，得先把画布坐标折算回去
        ox, oy = win.canvas.canvasx(0), win.canvas.canvasy(0)
        win._erase_at(pv.x + 120 - ox, y_line - oy)
        pump(win, 3)
        ink_after = sum(len(x["points"]) for x in win.store.annots_of(a, 0)
                        if x.get("kind") == "ink")
        check("橡皮擦掉了一截", ink_after < ink_before, (ink_before, ink_after))

        # ---------- 素材预览
        import tkinter as tk
        if win.store.materials:
            before_tops = len([w for w in win.winfo_children() if isinstance(w, tk.Toplevel)])
            win.preview_material(win.store.materials[0]["id"])
            pump(win, 3)
            tops = [w for w in win.winfo_children() if isinstance(w, tk.Toplevel)]
            check("双击素材能弹出预览", len(tops) > before_tops, len(tops))
            for t in tops:
                t.destroy()
            pump(win, 2)

        # ---------- 工作区视图：卡片墙 + 拖动排序
        ws = win.store.ws_items
        ws.append({"src": a, "page": 1, "title": "报告 A.pdf", "added": ""})
        ws.append({"src": b, "page": 0, "title": "附录 B.pdf", "added": ""})
        win.store.save()
        win.open_shelf(0)
        pump(win, 5)
        check("能把工作区打开成视图", win.mode == "shelf", win.mode)
        check("卡片都画出来了", len(win._shelf_cards) == len(win.store.ws_items),
              (len(win._shelf_cards), len(win.store.ws_items)))
        if len(win._shelf_cards) >= 2:
            before = [it["page"] for it in win.store.ws_items]
            x2, y2, w2, h2 = win._shelf_cards[1]
            ox, oy = win.canvas.canvasx(0), win.canvas.canvasy(0)
            win._drag_from = 0
            ev = type("Ev", (), {"x": x2 + 6 - ox, "y": y2 + 6 - oy})()
            win._shelf_release(ev)
            pump(win, 5)
            after = [it["page"] for it in win.store.ws_items]
            check("拖动卡片能改顺序", before != after, (before, after))
        win.show_doc_view()
        pump(win, 3)
        check("能切回看 PDF", win.mode == "doc", win.mode)

        # ---------- 换主题 / 收侧栏
        import theme as Th
        win.set_theme("light")
        pump(win, 6)
        check("能换成浅色主题", Th.mode == "light" and win.store.theme == "light", Th.mode)
        check("换完界面还活着", win.winfo_exists() and len(win.winfo_children()) > 0)
        win.set_theme("dark")
        pump(win, 6)
        check("能换回深色", Th.mode == "dark", Th.mode)
        win.toggle_sidebar()
        pump(win, 3)
        check("侧栏能收起来", win._sidebar_hidden is True)
        win.toggle_sidebar()
        pump(win, 3)
        check("侧栏能叫回来", win._sidebar_hidden is False)

        # ---------- 历史记录：关掉文件，记录和画笔都留着
        win.open_path(a)
        pump(win, 5)
        win.close_path(a)
        pump(win, 3)
        check("关掉文件后记录还在", win.store.doc_entry(a) is not None)
        left = [os.path.normcase(d["path"]) for d in win.store.recent_docs()]
        check("左栏列表里还有它", os.path.normcase(a) in left, len(left))

        win.open_path(a)
        pump(win, 6)
        check("重新打开，之前的画笔还在", len(win.store.annots_of(a, 0)) >= 1,
              len(win.store.annots_of(a, 0)))
        win.store.save_page(a, 2)
        check("记得上次看到第几页", win.store.last_page(a) == 2, win.store.last_page(a))
        win.store.forget_doc(a)
        check("能从记录里删掉", win.store.doc_entry(a) is None)
        win.open_path(a)
        pump(win, 3)

        # ---------- 打字
        win.open_path(a)
        pump(win, 5)
        win.set_tool("text")
        pv = win.pages[0]
        ox, oy = win.canvas.canvasx(0), win.canvas.canvasy(0)
        win._start_text(pv.x + 30 - ox, pv.y0 + 30 - oy)
        pump(win, 2)
        ok_entry = win._text_entry is not None
        if ok_entry:
            win._text_entry.insert(0, "测试文字")
            win._commit_text()
            pump(win, 2)
        texts = [x for x in win.store.annots_of(a, 0) if x.get("kind") == "text"]
        check("点页面能弹出输入框", ok_entry)
        check("打字能留在页面上",
              len(texts) == 1 and texts[0].get("text") == "测试文字",
              [t.get("text") for t in texts])
        check("文字存的是 PDF 坐标",
              texts and 0 <= texts[0]["points"][0][0] <= 700, texts and texts[0]["points"][0])

        # ---------- 欢迎页：关掉文件后中间显示「最近打开」
        win.close_path(a)
        pump(win, 5)
        kids = win.canvas.winfo_children()
        check("空状态显示最近打开列表", len(kids) > 0, len(kids))

        # ---------- 换工具要收走没提交的输入框
        win.open_path(a)
        pump(win, 5)
        win.set_tool("text")
        pv = win.pages[0]
        ox, oy = win.canvas.canvasx(0), win.canvas.canvasy(0)
        win._start_text(pv.x + 50 - ox, pv.y0 + 90 - oy)
        pump(win, 2)
        had = win._text_entry is not None
        win.set_tool("select")
        pump(win, 2)
        check("换工具会收走输入框", had and win._text_entry is None,
              (had, win._text_entry))

        # ---------- 已输入的字能拖走
        texts = [x for x in win.store.annots_of(a, 0) if x.get("kind") == "text"]
        if texts:
            tid = texts[0]["id"]
            before = list(texts[0]["points"][0])
            win._moving_anno = tid
            win._move_from = (0, 0)
            win._move_text(type("Ev", (), {"x": 60, "y": 40})())
            win._finish_move()
            after = win.store.annots_of(a, 0)[0]["points"][0]
            check("文字能拖动换位置", before != after, (before, after))
        else:
            check("文字能拖动换位置", False, "没有文字可拖")

        # ---------- 素材池能收起来
        win.open_path(a)
        pump(win, 5)
        check("素材池默认展开", win._panel_collapsed is False)
        win.toggle_panel()
        pump(win, 3)
        check("能收成一条", win._panel_collapsed is True)
        win.toggle_panel()
        pump(win, 3)
        check("能再展开", win._panel_collapsed is False)

        # ---------- 裁切：框 → 调 → 确认，不再一拖就收
        win.open_path(a)
        pump(win, 5)
        win.set_tool("crop")
        pv = win.pages[0]
        ox, oy = win.canvas.canvasx(0), win.canvas.canvasy(0)

        def ev_at(cx, cy):
            return type("Ev", (), {"x": cx - ox, "y": cy - oy})()

        before = len(win.store.materials)
        win._crop_press(ev_at(pv.x + 20, pv.y0 + 20))
        win._crop_drag(ev_at(pv.x + 200, pv.y0 + 150))
        win._crop_release(ev_at(pv.x + 200, pv.y0 + 150))
        pump(win, 2)
        check("拖完框不立刻进素材池", len(win.store.materials) == before,
              len(win.store.materials))
        check("框还留着可以调", win._crop_rect is not None, win._crop_rect)

        rect0 = list(win._crop_rect)
        hx, hy = win._crop_handles_pos()[4]        # 右下角那个手柄
        win._crop_press(ev_at(hx, hy))
        win._crop_drag(ev_at(hx + 60, hy + 40))
        win._crop_release(ev_at(hx + 60, hy + 40))
        pump(win, 2)
        check("拖角能把框改大", win._crop_rect[:2] == rect0[:2]
              and win._crop_rect[3] > rect0[3], (rect0, win._crop_rect))

        win._cancel_crop()
        pump(win, 2)
        check("取消就什么都不留",
              win._crop_rect is None and len(win.store.materials) == before)

        win._crop_press(ev_at(pv.x + 20, pv.y0 + 20))
        win._crop_drag(ev_at(pv.x + 220, pv.y0 + 160))
        win._crop_release(ev_at(pv.x + 220, pv.y0 + 160))
        pump(win, 2)
        win._commit_crop()
        pump(win, 3)
        check("点确认才真收进素材池", len(win.store.materials) == before + 1,
              len(win.store.materials))
        check("确认后框自己消失", win._crop_rect is None)

        # ---------- 收起 / 展开的状态切换（像素得靠真窗口看，隐藏状态下量的都是 1）
        win.toggle_sidebar()
        pump(win, 20)
        check("侧栏收起了", win._sidebar_hidden is True)
        win.toggle_sidebar()
        pump(win, 20)
        check("侧栏回来了", win._sidebar_hidden is False)

        win.toggle_panel()
        pump(win, 20)
        check("素材池收起来了", win._panel_collapsed is True)
        win.toggle_panel()
        pump(win, 20)
        check("素材池展开了", win._panel_collapsed is False)

        # ---------- 设置项能存住
        win.store.mark_fill = True
        win.store.merge_layout = "grid"
        win.store.pen_width = 5.5
        win.store.save()
        st4 = S.Store(win.store.path)
        check("高亮样式存下来了", st4.mark_fill is True, st4.mark_fill)
        check("默认排法存下来了", st4.merge_layout == "grid", st4.merge_layout)
        check("自定义笔宽存下来了", abs(st4.pen_width - 5.5) < 0.01, st4.pen_width)
        win.store.mark_fill = False
        win.store.merge_layout = "single"
        win.store.pen_width = 2.0
        win.store.save()

        # ---------- 自定义色槽
        win.store.custom_colors = []
        for i, c in enumerate(["#112233", "#445566", "#778899"]):
            win.store.save_color_slot(c)
        check("自定义色能存槽", win.store.custom_colors[0] == "#778899",
              win.store.custom_colors)
        for i in range(10):
            win.store.save_color_slot("#%06d" % i)
        check("自定义色最多留 6 个", len(win.store.custom_colors) == 6,
              len(win.store.custom_colors))
        win.store.save()
        st5 = S.Store(win.store.path)
        check("自定义色存得下来", len(st5.custom_colors) == 6, st5.custom_colors)
        st5.custom_colors = []
        st5.save()

        # ---------- 跳转到第几页（隐藏窗口滚不动，所以盯的是“算出来的页码对不对”）
        win.open_path(a)
        pump(win, 6)
        calls = []
        real_jump = win.jump_to_page
        win.jump_to_page = lambda p: calls.append(p)
        win.page_var.set("3")
        win.goto_page()
        check("输 3 会跳第 3 页（内部 0 起算）", calls == [2], calls)
        win.page_var.set("999")
        win.goto_page()
        check("超范围夹到最后一页", calls[-1] == len(win.pages) - 1, calls)
        win.page_var.set("abc")
        win.goto_page()
        check("乱输不跳", len(calls) == 2, calls)
        win.jump_to_page = real_jump
        win.page_var.set("1")
        win.goto_page()
        pump(win, 4)

        win.destroy()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print("有 %d 项没过：%s" % (len(FAILS), "、".join(FAILS)))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
