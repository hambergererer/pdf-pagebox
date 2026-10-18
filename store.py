# -*- coding: utf-8 -*-
"""PageBox 的数据：打开的 PDF、分类标签、素材、工作区。

只做存取，不碰界面，也不碰 PDF 渲染。全部塞在一个 json 里，
小得能随手备份。
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import uuid

SHELF_LIMIT = 4
CUSTOM_SLOTS = 6

SCHEMA = 3


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def _new_id(prefix):
    return "%s%s" % (prefix, uuid.uuid4().hex[:8])


class Store(object):
    """所有需要记住的东西。改完记得 save()。"""

    def __init__(self, path):
        self.path = path
        self.tags = []        # [{"id","name","color"}]
        self.docs = []        # [{"path","tags":[id...]}]  打开过的 PDF
        self.materials = []   # [{"id","src","page","rect","tag_id","added"}]
        self.shelves = []     # [{"name","items":[{src,page,title,added}]}]
        self.annotations = [] # [{"id","src","page","points","color","width","kind"}]
        self.pen_color = "#e06c75"
        self.pen_width = 2.0
        self.custom_colors = []         # 自己挑的颜色，最多 CUSTOM_SLOTS 个
        self.mark_fill = False          # 高亮框：空心还是实心
        self.merge_layout = "single"    # 素材合并默认排法
        self.theme = "light"
        self.active = 0
        self.load()

    # ------------------------------------------------------------ 存取

    def load(self):
        raw = None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception:
            raw = None

        if isinstance(raw, dict) and isinstance(raw.get("shelves"), list):
            self._load_v3(raw)
        elif isinstance(raw, dict) and isinstance(raw.get("items"), list):
            # 最老的那版：整个文件就是一个工作区
            self.shelves = [{"name": "工作区 1", "items": _clean_pages(raw.get("items"))}]
            self.active = 0
        if not self.shelves:
            self.shelves = [{"name": "工作区 1", "items": []}]

        if not self.tags:
            self.tags.append({"id": _new_id("t"), "name": "未分类", "color": TAG_FALLBACK})
        self.active = max(0, min(self.active, len(self.shelves) - 1))

    def _load_v3(self, raw):
        for s in raw["shelves"][:SHELF_LIMIT]:
            if isinstance(s, dict):
                self.shelves.append({
                    "name": str(s.get("name") or "工作区"),
                    "items": _clean_pages(s.get("items")),
                })
        try:
            self.active = int(raw.get("active", 0))
        except Exception:
            self.active = 0
        for t in raw.get("tags") or []:
            if isinstance(t, dict) and t.get("id"):
                self.tags.append({
                    "id": str(t["id"]),
                    "name": str(t.get("name") or "标签"),
                    "color": str(t.get("color") or TAG_FALLBACK),
                })
        for d in raw.get("docs") or []:
            if isinstance(d, dict) and d.get("path"):
                self.docs.append({
                    "path": str(d["path"]),
                    "tags": [str(x) for x in (d.get("tags") or [])],
                    "last": str(d.get("last") or ""),
                    "page": int(d.get("page", 0) or 0),
                })
        for m in raw.get("materials") or []:
            rect = _clean_rect(m.get("rect") if isinstance(m, dict) else None)
            if isinstance(m, dict) and m.get("src") and rect:
                self.materials.append({
                    "id": str(m.get("id") or _new_id("m")),
                    "src": str(m["src"]),
                    "page": int(m.get("page", 0)),
                    "rect": rect,
                    "tag_id": str(m.get("tag_id") or ""),
                    "added": str(m.get("added") or _now()),
                })
        for a in raw.get("annotations") or []:
            if not isinstance(a, dict) or not a.get("src"):
                continue
            pts = _clean_points(a.get("points"))
            if pts:
                anno = {
                    "id": str(a.get("id") or _new_id("a")),
                    "src": str(a["src"]),
                    "page": int(a.get("page", 0)),
                    "points": pts,
                    "color": str(a.get("color") or "#e06c75"),
                    "width": float(a.get("width") or 2.0),
                    "kind": str(a.get("kind") or "ink"),
                }
                if a.get("text"):
                    anno["text"] = str(a["text"])
                self.annotations.append(anno)
        self.pen_color = str(raw.get("pen_color") or self.pen_color)
        self.theme = "dark" if str(raw.get("theme")) == "dark" else "light"
        self.mark_fill = bool(raw.get("mark_fill", False))
        self.merge_layout = "grid" if str(raw.get("merge_layout")) == "grid" else "single"
        self.custom_colors = [str(c) for c in (raw.get("custom_colors") or [])
                              if isinstance(c, str)][:CUSTOM_SLOTS]
        try:
            self.pen_width = float(raw.get("pen_width") or self.pen_width)
        except Exception:
            pass

    def save_color_slot(self, color):
        """存一个自定义色，满了就顶掉最旧的那个。"""
        color = str(color)
        if color in self.custom_colors:
            self.custom_colors.remove(color)
        self.custom_colors.insert(0, color)
        del self.custom_colors[CUSTOM_SLOTS:]

    def save(self):
        data = {
            "version": SCHEMA,
            "active": int(self.active),
            "shelves": self.shelves,
            "tags": self.tags,
            "docs": self.docs,
            "materials": self.materials,
            "annotations": self.annotations,
            "pen_color": self.pen_color,
            "pen_width": self.pen_width,
            "custom_colors": self.custom_colors,
            "mark_fill": self.mark_fill,
            "merge_layout": self.merge_layout,
            "theme": self.theme,
        }
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            pass

    # ------------------------------------------------------------ 标签

    def tag(self, tag_id):
        for t in self.tags:
            if t["id"] == tag_id:
                return t
        return None

    def tag_name(self, tag_id):
        t = self.tag(tag_id)
        return t["name"] if t else "未分类"

    def tag_color(self, tag_id):
        t = self.tag(tag_id)
        return t["color"] if t else TAG_FALLBACK

    def default_tag_id(self):
        return self.tags[0]["id"] if self.tags else ""

    def add_tag(self, name):
        name = (name or "").strip()[:8]
        if not name:
            return None
        color = TAG_COLORS[len(self.tags) % len(TAG_COLORS)]
        tag = {"id": _new_id("t"), "name": name, "color": color}
        self.tags.append(tag)
        return tag

    def remove_tag(self, tag_id):
        self.tags = [t for t in self.tags if t["id"] != tag_id]
        fallback = self.default_tag_id()
        for m in self.materials:
            if m["tag_id"] == tag_id:
                m["tag_id"] = fallback
        for d in self.docs:
            d["tags"] = [x for x in d["tags"] if x != tag_id]
        if not self.tags:
            self.tags.append({"id": _new_id("t"), "name": "未分类", "color": TAG_FALLBACK})

    # ------------------------------------------------------------ 打开的 PDF

    def doc_entry(self, path):
        path = os.path.abspath(path)
        for d in self.docs:
            if os.path.normcase(d["path"]) == os.path.normcase(path):
                return d
        return None

    def open_doc(self, path):
        """打开=记一笔。历史记录不会因为关掉文件就消失。"""
        path = os.path.abspath(path)
        d = self.doc_entry(path)
        if d is None:
            d = {"path": path, "tags": [self.default_tag_id()], "last": _now(), "page": 0}
            self.docs.append(d)
        else:
            d["last"] = _now()
        return d

    def forget_doc(self, path):
        """从历史里彻底删掉这一条（连标签记录一起）。"""
        path = os.path.abspath(path)
        self.docs = [d for d in self.docs
                     if os.path.normcase(d["path"]) != os.path.normcase(path)]

    def recent_docs(self, limit=None):
        """按最近打开时间倒序。"""
        out = sorted(self.docs, key=lambda d: str(d.get("last", "")), reverse=True)
        return out[:limit] if limit else out

    def save_page(self, path, page):
        d = self.doc_entry(path)
        if d is not None:
            d["page"] = int(page)

    def last_page(self, path):
        d = self.doc_entry(path)
        return int(d.get("page", 0)) if d else 0

    def doc_tag(self, path):
        """一个 PDF 只挂一个标签，取第一个。"""
        d = self.doc_entry(path)
        if d and d["tags"]:
            return d["tags"][0]
        return self.default_tag_id()

    def set_doc_tag(self, path, tag_id):
        d = self.open_doc(path)
        d["tags"] = [tag_id]

    # ------------------------------------------------------------ 素材

    def add_material(self, src, page, rect, tag_id=None):
        src = os.path.abspath(src)
        tag_id = tag_id or self.doc_tag(src) or self.default_tag_id()
        m = {
            "id": _new_id("m"),
            "src": src,
            "page": int(page),
            "rect": [float(v) for v in rect],
            "tag_id": tag_id,
            "added": _now(),
        }
        self.materials.append(m)
        return m

    def remove_material(self, mat_id):
        self.materials = [m for m in self.materials if m["id"] != mat_id]

    def material(self, mat_id):
        for m in self.materials:
            if m["id"] == mat_id:
                return m
        return None

    def materials_by_tag(self):
        """{tag_id: [material...]}，保持标签顺序。"""
        out = {}
        for t in self.tags:
            out[t["id"]] = [m for m in self.materials if m["tag_id"] == t["id"]]
        return out

    # ------------------------------------------------------------ 工作区

    @property
    def ws(self):
        return self.shelves[self.active]

    @property
    def ws_items(self):
        return self.shelves[self.active]["items"]

    def add_shelf(self):
        if len(self.shelves) >= SHELF_LIMIT:
            return None
        self.shelves.append({"name": "工作区 %d" % (len(self.shelves) + 1), "items": []})
        self.active = len(self.shelves) - 1
        return self.shelves[-1]

    # ------------------------------------------------------------ 标注（画笔）

    def annots_of(self, src, page):
        key = os.path.normcase(os.path.abspath(src))
        return [a for a in self.annotations
                if a["page"] == page
                and os.path.normcase(os.path.abspath(a["src"])) == key]

    def add_annotation(self, src, page, points, color=None, width=2.0, kind="ink", text=None):
        pts = _clean_points(points)
        if len(pts) < 2:
            return None
        a = {
            "id": _new_id("a"),
            "src": os.path.abspath(src),
            "page": int(page),
            "points": pts,
            "color": color or self.pen_color,
            "width": float(width),
            "kind": kind,
        }
        if text:
            a["text"] = str(text)
        self.annotations.append(a)
        return a

    def undo_annotation(self, src, page):
        key = os.path.normcase(os.path.abspath(src))
        for i in range(len(self.annotations) - 1, -1, -1):
            a = self.annotations[i]
            if a["page"] == page and os.path.normcase(os.path.abspath(a["src"])) == key:
                return self.annotations.pop(i)
        return None

    def clear_annotations(self, src, page=None):
        key = os.path.normcase(os.path.abspath(src))
        if page is None:
            self.annotations = [a for a in self.annotations
                                if os.path.normcase(os.path.abspath(a["src"])) != key]
        else:
            self.annotations = [a for a in self.annotations
                                if not (a["page"] == page
                                        and os.path.normcase(os.path.abspath(a["src"])) == key)]


TAG_FALLBACK = "#8b8b8b"
TAG_COLORS = ["#e06c75", "#e5c07b", "#98c379", "#56b6c2", "#61afef", "#c678dd"]


def _clean_points(points):
    out = []
    for p in points or []:
        try:
            out.append([float(p[0]), float(p[1])])
        except Exception:
            continue
    return out


def _clean_rect(rect):
    try:
        x0, y0, x1, y1 = [float(v) for v in rect]
    except Exception:
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def _clean_pages(raw_items):
    items = []
    for it in raw_items or []:
        if isinstance(it, dict) and "src" in it and "page" in it:
            try:
                page = int(it["page"])
            except Exception:
                continue
            items.append({
                "src": str(it["src"]),
                "page": page,
                "title": str(it.get("title") or os.path.basename(str(it["src"]))),
                "added": str(it.get("added", "")),
            })
    return items


def data_dir(here):
    """优先把数据存在程序目录下，目录不可写就退回 %APPDATA%。"""
    cand = os.path.join(here, "data")
    try:
        os.makedirs(cand, exist_ok=True)
        probe = os.path.join(cand, ".writable")
        with open(probe, "w") as fh:
            fh.write("1")
        os.remove(probe)
        return cand
    except Exception:
        fallback = os.path.join(os.environ.get("APPDATA") or tempfile.gettempdir(), "PageBox")
        os.makedirs(fallback, exist_ok=True)
        return fallback
