# -*- coding: utf-8 -*-
"""PDF 这一层：开文档、画页面、裁块、合并。

界面那边只管要图片、要文件，脏活都在这里。
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(HERE, "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

import pymupdf as fitz
from PIL import Image

# 素材册的纸：A4 纵向，四周留白
MENU_PW, MENU_PH = 595.0, 842.0
MENU_MARGIN = 42.0
MENU_GAP = 14.0


class Engine(object):
    """文档缓存。同一个文件反复开很慢，开一次记住就行。"""

    def __init__(self):
        self._docs = {}
        self._sizes = {}

    def _key(self, path):
        return os.path.normcase(os.path.abspath(path))

    def doc(self, path):
        key = self._key(path)
        d = self._docs.get(key)
        if d is None:
            d = fitz.open(path)
            self._docs[key] = d
        return d

    def close(self, path):
        key = self._key(path)
        d = self._docs.pop(key, None)
        self._sizes.pop(key, None)
        if d is not None:
            try:
                d.close()
            except Exception:
                pass

    def close_all(self):
        for d in list(self._docs.values()):
            try:
                d.close()
            except Exception:
                pass
        self._docs.clear()
        self._sizes.clear()

    def page_count(self, path):
        return self.doc(path).page_count

    def page_size(self, path, pno):
        """宽、高（pt）。"""
        key = self._key(path)
        sizes = self._sizes.setdefault(key, {})
        if pno not in sizes:
            r = self.doc(path).load_page(pno).rect
            sizes[pno] = (r.width, r.height)
        return sizes[pno]

    def render(self, path, pno, scale, clip=None):
        """画一页（或其中一块）成 PIL 图。"""
        page = self.doc(path).load_page(pno)
        m = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=m, clip=clip, alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def text_of(self, path, pno, clip=None):
        try:
            page = self.doc(path).load_page(pno)
            return page.get_text(clip=clip) if clip else page.get_text()
        except Exception:
            return ""


# ---------------------------------------------------------------- 合并

def merge_pages(items, out_path, progress=None):
    """把工作区里的整页合成一个 PDF。返回 (合了几页, 找不到的来源)。"""
    missing, real = [], []
    for it in items:
        (real if os.path.isfile(it["src"]) else missing).append(it)
    if not real:
        raise ValueError("工作区里的来源文件都找不到了")

    out = fitz.open()
    cache = {}
    added = 0
    try:
        for i, it in enumerate(real):
            key = os.path.normcase(os.path.abspath(it["src"]))
            doc = cache.get(key)
            if doc is None:
                doc = fitz.open(it["src"])
                cache[key] = doc
            pno = it["page"]
            if 0 <= pno < doc.page_count:
                out.insert_pdf(doc, from_page=pno, to_page=pno)
                added += 1
            if progress:
                progress(i + 1, len(real))
        if added == 0:
            raise ValueError("没有可用的页面")
        _save_new(out, out_path)
    finally:
        out.close()
        for d in cache.values():
            try:
                d.close()
            except Exception:
                pass
    return added, missing


def merge_materials(materials, out_path, layout="single", progress=None):
    """把裁下来的碎块排成册子。

    layout="single"：一行一张，素材放大到内容宽，一张张往下摞（适合大图）。
    layout="grid"  ：按素材原来的宽窄一行排满再换行，小碎块能挤一排（适合小碎片）。
    两种都是排满一页就换页，页数不封顶。
    """
    if not materials:
        raise ValueError("素材池是空的")
    if layout == "grid":
        return _merge_grid(materials, out_path, progress)

    out = fitz.open()
    cache = {}
    content_w = MENU_PW - 2 * MENU_MARGIN
    content_h = MENU_PH - 2 * MENU_MARGIN

    page = None
    y = MENU_MARGIN
    added = 0
    try:
        for i, m in enumerate(materials):
            key = os.path.normcase(os.path.abspath(m["src"]))
            doc = cache.get(key)
            if doc is None:
                if not os.path.isfile(m["src"]):
                    continue
                doc = fitz.open(m["src"])
                cache[key] = doc
            if not (0 <= m["page"] < doc.page_count):
                continue

            clip = fitz.Rect(*m["rect"])
            cw, ch = clip.width, clip.height
            if cw <= 0 or ch <= 0:
                continue

            # 统一宽度；太高的（细长条）就按高度压，免得超出纸面
            w = content_w
            h = ch * (content_w / cw)
            if h > content_h:
                h = content_h
                w = cw * (content_h / ch)

            if page is None or y + h > MENU_PH - MENU_MARGIN:
                page = out.new_page(width=MENU_PW, height=MENU_PH)
                y = MENU_MARGIN

            x = MENU_MARGIN + (content_w - w) / 2.0
            target = fitz.Rect(x, y, x + w, y + h)
            try:
                page.show_pdf_page(target, doc, m["page"], clip=clip)
                added += 1
            except Exception:
                pass
            y += h + MENU_GAP
            if progress:
                progress(i + 1, len(materials))

        if added == 0:
            raise ValueError("这些素材都没法用")
        _save_new(out, out_path)
    finally:
        out.close()
        for d in cache.values():
            try:
                d.close()
            except Exception:
                pass
    return added


def _merge_grid(materials, out_path, progress=None):
    """网格排法：按素材原来的宽窄，一行尽量塞满，塞不下换行，排满一页换页。

    一行里所有素材等比例缩放，让它们正好铺满内容宽度——所以一行里
    通常有好几个，小碎片能排得很密。
    """
    out = fitz.open()
    cache = {}
    content_w = MENU_PW - 2 * MENU_MARGIN
    content_h = MENU_PH - 2 * MENU_MARGIN

    # 先把素材的原始尺寸摸出来，排的时候才好算一行能放几个
    boxes = []
    for m in materials:
        key = os.path.normcase(os.path.abspath(m["src"]))
        doc = cache.get(key)
        if doc is None:
            if not os.path.isfile(m["src"]):
                continue
            try:
                doc = fitz.open(m["src"])
            except Exception:
                continue
            cache[key] = doc
        if not (0 <= m["page"] < doc.page_count):
            continue
        clip = fitz.Rect(*m["rect"])
        if clip.width <= 0 or clip.height <= 0:
            continue
        boxes.append((m, doc, clip))

    if not boxes:
        raise ValueError("这些素材都没法用")

    page = None
    y = MENU_MARGIN
    added = 0
    i = 0
    try:
        while i < len(boxes):
            # 挑出这一行：一直往里塞，直到再塞一个就超过内容宽
            row = []
            total_w = 0.0
            while i + len(row) < len(boxes):
                cand = boxes[i + len(row)]
                cw = cand[2].width
                if row and total_w + cw > content_w:
                    break
                row.append(cand)
                total_w += cw
                if total_w >= content_w:
                    break
            if not row:
                row = [boxes[i]]
                total_w = boxes[i][2].width
            if total_w <= 0:
                total_w = content_w

            # 这一行整体放到内容宽（留点间距）
            gaps = MENU_GAP * (len(row) - 1)
            scale = (content_w - gaps) / total_w
            row_w = [b[2].width * scale for b in row]
            row_h = [b[2].height * scale for b in row]
            line_h = max(row_h) if row_h else 0.0

            # 一行比一整页还高的话，整行再压一压
            if line_h > content_h:
                k = content_h / line_h
                row_w = [w * k for w in row_w]
                row_h = [h * k for h in row_h]
                line_h = content_h

            if page is None or y + line_h > MENU_PH - MENU_MARGIN:
                page = out.new_page(width=MENU_PW, height=MENU_PH)
                y = MENU_MARGIN

            x = MENU_MARGIN
            for (m, doc, clip), w, h in zip(row, row_w, row_h):
                target = fitz.Rect(x, y, x + w, y + h)
                try:
                    page.show_pdf_page(target, doc, m["page"], clip=clip)
                    added += 1
                except Exception:
                    pass
                x += w + MENU_GAP

            y += line_h + MENU_GAP
            i += len(row)
            if progress:
                progress(i, len(boxes))

        if added == 0:
            raise ValueError("这些素材都没法用")
        _save_new(out, out_path)
    finally:
        out.close()
        for d in cache.values():
            try:
                d.close()
            except Exception:
                pass
    return added


def _save_new(doc, out_path):
    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except Exception:
            pass
    doc.save(out_path, deflate=True, garbage=3)


def make_test_pdf(path, count=3, tag="Doc"):
    """造一个测试用的 PDF。"""
    doc = fitz.open()
    for i in range(count):
        page = doc.new_page(width=595, height=842)
        page.insert_text((70, 110), "%s page %d" % (tag, i + 1), fontsize=26)
        for k in range(14):
            page.insert_text((70, 170 + k * 28),
                             "line %02d ............................................" % (k + 1),
                             fontsize=11)
    doc.save(path)
    doc.close()
