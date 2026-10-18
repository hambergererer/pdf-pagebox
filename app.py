# -*- coding: utf-8 -*-
"""PageBox —— 一个挑页、裁块、攒册子的轻工具。

界面照 VS Code 的样子搭：
    最左一列活动栏（换侧栏内容）
    侧栏：打开的 PDF / 标签 / 工作区
    中间：看 PDF 的地方
    下面：素材池，裁下来的碎块都落这儿
    右边：工具（选择 / 裁切）
    顶上：工具栏 + 打开的 PDF 的标签页

运行：python app.py [某个.pdf]
"""

from __future__ import annotations

import datetime
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    HERE = os.path.dirname(os.path.abspath(sys.executable))
else:
    VENDOR = os.path.join(HERE, "vendor")
    if os.path.isdir(VENDOR) and VENDOR not in sys.path:
        sys.path.insert(0, VENDOR)

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk

import theme as T
import store as S
import pdflib as P

try:
    from tkinterdnd2 import TkinterDnD as _tkdnd
    from tkinterdnd2 import DND_FILES as _DND_FILES
    from tkinterdnd2 import COPY as _DND_COPY
    from tkinterdnd2 import REFUSE_DROP as _DND_REFUSE
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.LANCZOS

APP_TITLE = "PageBox"
ACTIVITY_W = 44
SIDEBAR_W = 214
RIGHTBAR_W = 40
PANEL_H = 172


def short_name(path, limit=26):
    name = os.path.basename(path)
    if len(name) <= limit:
        return name
    stem, ext = os.path.splitext(name)
    keep = max(4, limit - len(ext) - 1)
    return stem[:keep] + "…" + ext


def enable_dpi_awareness():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def ui_scale(root):
    try:
        dpi = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        dpi = 96.0
    return max(1.0, min(2.2, dpi / 96.0))


# ---------------------------------------------------------------- 一页

class PageView(object):
    __slots__ = ("pno", "w", "h", "x", "y", "photo", "img_id", "base_id",
                 "edge_id", "badge_id", "label_id")

    def __init__(self, pno, x, y, w, h):
        self.pno = pno
        self.x, self.y, self.w, self.h = x, y, w, h
        self.photo = None
        self.img_id = None
        self.base_id = None
        self.edge_id = None
        self.badge_id = None
        self.label_id = None

    @property
    def y0(self):
        return self.y

    @property
    def y1(self):
        return self.y + self.h


# ---------------------------------------------------------------- 主程序

class App(tk.Tk):

    def __init__(self, initial=None):
        super().__init__()
        T.pick_font(self)
        self.ui = ui_scale(self)
        self.dpi = self.winfo_fpixels("1i") or 96.0
        s = self.ui

        self.title(APP_TITLE)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(int(1280 * s), int(sw * 0.95))
        h = min(int(820 * s), int(sh * 0.92))
        self.geometry("%dx%d+%d+%d" % (w, h, max(0, (sw - w) // 2), max(0, (sh - h) // 2 - 18)))
        self.minsize(min(int(940 * s), int(sw * 0.62)), min(int(600 * s), int(sh * 0.55)))
        self.configure(bg=T.BG_APP)

        self.store = S.Store(os.path.join(S.data_dir(HERE), "workspace.json"))
        T.apply(getattr(self.store, "theme", "dark"))
        self.engine = P.Engine()
        self._sidebar_hidden = False

        self.doc_path = None
        self.pages = []
        self.selected = set()
        self.zoom = 1.0

        self.tool = "select"
        self._crop_start = None
        self._crop_item = None
        self._crop_rect = None
        self._crop_items = []
        self._crop_win = None
        self._crop_mode = None
        self._crop_handle = None
        self._crop_start_pt = None
        self._crop_from = None
        self._crop_origin = None
        self._pen_page = None
        self._pen_points = []
        self._pen_item = None
        self._last_pen_page = None
        self._erasing = False
        self._moving_anno = None
        self._move_from = None
        self._panel_collapsed = False
        self._text_entry = None
        self._text_item = None
        self._text_at = None

        self.view = "docs"
        self.tag_filter = None
        self.mode = "doc"          # doc = 看 PDF，shelf = 看工作区卡片墙
        self._shelf_cards = []
        self._drag_from = None
        self._drop_mark = None
        self._thumb_cache = {}

        self._render_queue = []
        self._render_scheduled = False
        self._relayout_job = None
        self._recenter_job = None
        self._note_job = None
        self._dnd_ok = False
        self._dnd_targets = 0

        self._build_styles()
        self._build_ui()
        self._setup_dnd()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-e>", lambda e: self.merge_material())
        self.bind("<Control-z>", lambda e: self.undo_stroke())
        self.bind("<Control-b>", lambda e: self.toggle_sidebar())
        self.bind("<Control-g>", lambda e: self._focus_page_entry())
        self.bind("<Escape>", lambda e: self._escape())

        self.show_view("docs")
        self.show_empty()
        self.refresh_top_tabs()
        self.refresh_panel()
        self._sync_tools()

        if initial and os.path.isfile(initial):
            self.after(80, lambda: self.open_path(initial))

    # ------------------------------------------------------------ 样式

    def _build_styles(self):
        s = self.ui
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        for name in ("Side.Vertical.TScrollbar", "Panel.Vertical.TScrollbar",
                     "View.Vertical.TScrollbar", "Panel.Horizontal.TScrollbar"):
            st.configure(
                name, gripcount=0,
                background="#4c4c4c", darkcolor="#4c4c4c", lightcolor="#4c4c4c",
                troughcolor=T.BG_PANEL, bordercolor=T.BG_PANEL,
                arrowcolor="#8b8b8b", arrowsize=int(10 * s), width=int(9 * s),
            )
            st.map(name, background=[("active", "#5f5f5f")])

    # ------------------------------------------------------------ 骨架

    def _build_ui(self):
        self._build_topbar()
        self._build_body()
        self._build_statusbar()

    def _flat_btn(self, parent, text, cmd, fg=None, bg=None, hover=None,
                  font=None, padx=10, pady=3, anchor="center"):
        fg = fg or T.TEXT
        bg = bg or T.BG_TOP
        hover = hover or T.BG_HOVER
        btn = tk.Button(
            parent, text=text, command=cmd,
            font=font or T.font(9),
            bg=bg, fg=fg,
            activebackground=hover, activeforeground=fg,
            relief="flat", bd=0, highlightthickness=0,
            cursor="hand2", padx=int(padx * self.ui), pady=int(pady * self.ui),
            anchor=anchor,
        )
        btn._fg = fg
        btn._bg = bg
        btn._hover = hover
        return btn

    def _enabled(self, btn, on):
        if on:
            btn.configure(state="normal", bg=btn._bg, fg=btn._fg, cursor="hand2")
        else:
            btn.configure(state="disabled", bg=btn._bg, fg=T.TEXT_FAINT, cursor="arrow")

    # ---- 顶栏

    def _build_topbar(self):
        s = self.ui
        top = tk.Frame(self, bg=T.BG_TOP)
        top.pack(side="top", fill="x")

        bar = tk.Frame(top, bg=T.BG_TOP, height=int(38 * s))
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)

        def sep():
            tk.Frame(bar, bg=T.LINE, width=1).pack(side="left", fill="y",
                                                   pady=int(9 * s), padx=int(6 * s))

        self.btn_open = self._flat_btn(bar, "打开 PDF", self.open_file,
                                       fg="#ffffff", bg=T.ACCENT, hover=T.ACCENT_D, padx=12)
        self.btn_open.pack(side="left", padx=(int(10 * s), 0), pady=int(6 * s))

        self.btn_addpage = self._flat_btn(bar, "整页入工作区", self.add_selection)
        self.btn_addpage.pack(side="left", padx=(int(6 * s), 0), pady=int(6 * s))

        self.btn_merge_ws = self._flat_btn(bar, "合并工作区", self.merge_workspace)
        self.btn_merge_ws.pack(side="left", padx=(int(4 * s), 0), pady=int(6 * s))

        sep()

        self._flat_btn(bar, "全选", self.select_all).pack(side="left", pady=int(6 * s))
        self._flat_btn(bar, "清除选择", self.clear_selection).pack(side="left", pady=int(6 * s))

        self.lbl_zoom = tk.Label(bar, text="100%", bg=T.BG_TOP, fg=T.TEXT_DIM,
                                 font=T.font(9), width=5)
        self.lbl_zoom.pack(side="right", padx=(0, int(10 * s)))
        self._flat_btn(bar, "＋", self.zoom_in, padx=6).pack(side="right", pady=int(6 * s))
        self._flat_btn(bar, "－", self.zoom_out, padx=6).pack(side="right", pady=int(6 * s))
        self._flat_btn(bar, "整页", self.fit_page).pack(side="right", pady=int(6 * s))
        self._flat_btn(bar, "适宽", self.fit_width).pack(side="right", pady=int(6 * s))

        # 页码跳转：输个数字回车就过去
        self.lbl_pages = tk.Label(bar, text="/ 0", bg=T.BG_TOP, fg=T.TEXT_FAINT,
                                  font=T.font(8))
        self.lbl_pages.pack(side="right", padx=(0, int(12 * s)))
        self.page_var = tk.StringVar()
        self.page_entry = tk.Entry(bar, textvariable=self.page_var, width=4,
                                   bg=T.BG_INPUT, fg=T.TEXT, insertbackground=T.TEXT,
                                   relief="flat", bd=0, highlightthickness=1,
                                   highlightbackground=T.LINE, justify="center",
                                   font=T.font(9))
        self.page_entry.pack(side="right", pady=int(9 * s))
        self.page_entry.bind("<Return>", self.goto_page)
        self.page_entry.bind("<Escape>", lambda e: self._sync_page_label())
        self._flat_btn(bar, "跳转", lambda: self.goto_page()).pack(
            side="right", padx=(0, int(5 * s)), pady=int(6 * s))

        self._flat_btn(bar, "◐", self.set_theme, padx=8,
                       font=(T.FONT, int(11 * s))).pack(side="right", pady=int(6 * s))

        tk.Frame(top, bg=T.LINE, height=1).pack(side="top", fill="x")

        self.tabbar = tk.Frame(top, bg=T.BG_TOP, height=int(32 * s))
        self.tabbar.pack(side="top", fill="x")
        self.tabbar.pack_propagate(False)
        self._tabs = []

        tk.Frame(self, bg=T.LINE, height=1).pack(side="top", fill="x")

    def refresh_top_tabs(self):
        for w in self.tabbar.winfo_children():
            w.destroy()
        self._tabs = []
        s = self.ui

        # 顶上只摆最近打开的几个，其余的都在左栏里
        docs = self.store.recent_docs(8)
        if not docs:
            tk.Label(self.tabbar, text="还没有打开过文件", bg=T.BG_TOP, fg=T.TEXT_FAINT,
                     font=T.font(9)).pack(side="left", padx=int(14 * s))
            return

        for d in docs:
            path = d["path"]
            cur = bool(self.doc_path) and os.path.normcase(self.doc_path) == os.path.normcase(path)
            bg = T.BG_EDITOR if cur else T.BG_TOP
            color = self.store.tag_color(self.store.doc_tag(path))

            tab = tk.Frame(self.tabbar, bg=bg)
            tab.pack(side="left", fill="y")
            inner = tk.Frame(tab, bg=bg)
            inner.pack(fill="both", expand=True, padx=int(9 * s))

            cbar = tk.Frame(inner, bg=color, width=int(5 * s), height=int(16 * s),
                            cursor="hand2")
            cbar.pack(side="left", pady=int(8 * s))
            cbar.bind("<Button-1>", lambda e, p=path: self._doc_menu(e, p))
            lbl = tk.Label(inner, text=short_name(path, 20), bg=bg,
                           fg=T.TEXT if cur else T.TEXT_DIM, font=T.font(9), cursor="hand2")
            lbl.pack(side="left", padx=(int(6 * s), int(6 * s)))
            close = tk.Label(inner, text="✕", bg=bg, fg=T.TEXT_FAINT, font=T.font(8),
                             cursor="hand2", padx=int(3 * s))
            close.pack(side="left")

            for w in (tab, inner, lbl):
                w.bind("<Button-1>", lambda e, p=path: self.open_path(p))
            close.bind("<Button-1>", lambda e, p=path: self.close_path(p))
            lbl.bind("<Button-3>", lambda e, p=path: self._doc_menu(e, p))
            tab.bind("<Button-3>", lambda e, p=path: self._doc_menu(e, p))

            if cur:
                tk.Frame(tab, bg=T.ACCENT, height=int(2 * s)).pack(side="bottom", fill="x")
            self._tabs.append(tab)

    def _doc_menu(self, event, path):
        m = tk.Menu(self, tearoff=0, bg=T.MENU_BG, fg=T.TEXT,
                    activebackground=T.ACCENT, activeforeground="#ffffff", bd=0)
        m.add_command(label="给它挂个标签：", state="disabled")
        for t in self.store.tags:
            same = (self.store.doc_tag(path) == t["id"])
            m.add_command(label=("● " if same else "　") + t["name"],
                          command=lambda tid=t["id"]: self.set_doc_tag(path, tid))
        m.add_separator()
        m.add_command(label="关闭这个文件（记录保留）", command=lambda: self.close_path(path))
        m.add_command(label="从记录里删掉", command=lambda: self.forget_doc(path))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # ---- 主体

    def _build_body(self):
        s = self.ui
        body = tk.Frame(self, bg=T.BG_APP)
        body.pack(side="top", fill="both", expand=True)

        self.paned = tk.PanedWindow(body, orient="horizontal", bg=T.LINE,
                                    sashwidth=int(3 * s), sashrelief="flat", bd=0)
        self.paned.pack(fill="both", expand=True)

        left = tk.Frame(self.paned, bg=T.BG_SIDE)
        self.left_pane = left
        self.paned.add(left, minsize=int(180 * s), width=int((ACTIVITY_W + SIDEBAR_W) * s))

        activity = tk.Frame(left, bg=T.BG_ACTIVITY, width=int(ACTIVITY_W * s))
        activity.pack(side="left", fill="y")
        activity.pack_propagate(False)

        self._act_btns = {}
        self._act_bars = {}
        for key, glyph in (("docs", "▤"), ("shelves", "⊞"), ("tags", "◈")):
            holder = tk.Frame(activity, bg=T.BG_ACTIVITY)
            holder.pack(fill="x")
            bar = tk.Frame(holder, bg=T.BG_ACTIVITY, width=int(2 * s))
            bar.pack(side="left", fill="y")
            b = tk.Button(holder, text=glyph, command=lambda k=key: self.show_view(k),
                          font=(T.FONT, int(13 * s)), bg=T.BG_ACTIVITY, fg=T.TEXT_DIM,
                          activebackground=T.BG_HOVER, activeforeground=T.TEXT,
                          relief="flat", bd=0, highlightthickness=0, cursor="hand2")
            b.pack(side="left", fill="x", expand=True, ipady=int(5 * s))
            self._act_btns[key] = b
            self._act_bars[key] = bar

        self.btn_side = tk.Button(activity, text="«", command=self.toggle_sidebar,
                                  font=(T.FONT, int(13 * s), "bold"), bg=T.BG_ACTIVITY,
                                  fg=T.TEXT_DIM, activebackground=T.BG_HOVER,
                                  activeforeground=T.TEXT, relief="flat", bd=0,
                                  highlightthickness=0, cursor="hand2")
        self.btn_side.pack(side="bottom", fill="x", ipady=int(6 * s), pady=int(6 * s))

        tk.Frame(left, bg=T.LINE, width=1).pack(side="left", fill="y")

        self.sidebar = tk.Frame(left, bg=T.BG_SIDE)
        self.sidebar.pack(side="left", fill="both", expand=True)

        head = tk.Frame(self.sidebar, bg=T.BG_SIDE, height=int(30 * s))
        head.pack(side="top", fill="x")
        head.pack_propagate(False)
        self.side_title = tk.Label(head, text="打开的 PDF", bg=T.BG_SIDE, fg=T.TEXT_DIM,
                                   font=T.font(8, bold=True), anchor="w")
        self.side_title.pack(side="left", padx=int(14 * s))
        self.side_action = self._flat_btn(head, "＋", self._side_action, bg=T.BG_SIDE,
                                          fg=T.TEXT_DIM, padx=7, pady=0)
        self.side_action.pack(side="right", padx=int(8 * s))

        self.side_canvas = tk.Canvas(self.sidebar, bg=T.BG_SIDE, highlightthickness=0, bd=0)
        self.side_canvas.pack(side="left", fill="both", expand=True)
        side_sb = ttk.Scrollbar(self.sidebar, orient="vertical", command=self.side_canvas.yview,
                                style="Side.Vertical.TScrollbar")
        side_sb.pack(side="right", fill="y")
        self.side_canvas.configure(yscrollcommand=side_sb.set, yscrollincrement=0)

        self.side_inner = tk.Frame(self.side_canvas, bg=T.BG_SIDE)
        self._side_win = self.side_canvas.create_window((0, 0), window=self.side_inner, anchor="nw")
        self.side_inner.bind("<Configure>", self._side_scroll_fix)
        self.side_canvas.bind("<Configure>", lambda e: self._side_width_fix(e))
        self.side_canvas.bind("<MouseWheel>", lambda e: self.side_canvas.yview_scroll(
            -1 if e.delta > 0 else 1, "units"))

        center = tk.Frame(self.paned, bg=T.BG_EDITOR)
        self.paned.add(center, minsize=int(420 * s), stretch="always")

        self.vpaned = tk.PanedWindow(center, orient="vertical", bg=T.LINE,
                                     sashwidth=int(3 * s), sashrelief="flat", bd=0)
        self.vpaned.pack(fill="both", expand=True)

        view_wrap = tk.Frame(self.vpaned, bg=T.BG_EDITOR)
        self.vpaned.add(view_wrap, minsize=int(200 * s), stretch="always")

        self.canvas = tk.Canvas(view_wrap, bg=T.BG_EDITOR, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(view_wrap, orient="vertical", command=self.canvas.yview,
                            style="View.Vertical.TScrollbar")
        vsb.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=vsb.set, yscrollincrement=0)

        self._build_panel()

        right = tk.Frame(self.paned, bg=T.BG_ACTIVITY, width=int(RIGHTBAR_W * s))
        # stretch="never" 很关键：PanedWindow 默认会把最后一个分栏拉伸吃掉
        # 多余宽度，所以工具条老是被撑得比设定的宽。
        self.paned.add(right, minsize=int(RIGHTBAR_W * s), width=int(RIGHTBAR_W * s),
                       stretch="never")
        right.pack_propagate(False)

        tk.Label(right, text="工具", bg=T.BG_ACTIVITY, fg=T.TEXT_FAINT,
                 font=T.font(7)).pack(pady=(int(8 * s), int(2 * s)))

        self._tool_btns = {}
        for key, glyph in (("select", "↖"), ("crop", "✂"), ("pen", "✎"),
                           ("mark", "▭"), ("eraser", "◯"), ("text", "T")):
            b = tk.Button(right, text=glyph, command=lambda k=key: self.set_tool(k),
                          font=(T.FONT, int(13 * s)), bg=T.BG_ACTIVITY, fg=T.TEXT_DIM,
                          activebackground=T.BG_HOVER, activeforeground=T.TEXT,
                          relief="flat", bd=0, highlightthickness=0, cursor="hand2")
            b.pack(fill="x", padx=int(6 * s), pady=int(4 * s), ipady=int(2 * s))
            self._tool_btns[key] = b

        tk.Frame(right, bg=T.LINE, height=1).pack(fill="x", pady=int(8 * s), padx=int(8 * s))
        self.tool_hint = tk.Label(right, text="", bg=T.BG_ACTIVITY, fg=T.TEXT_FAINT,
                                  font=T.font(7), wraplength=int(40 * s), justify="center")
        self.tool_hint.pack(padx=int(2 * s))

        tk.Frame(right, bg=T.LINE, height=1).pack(fill="x", pady=int(8 * s), padx=int(8 * s))
        tk.Label(right, text="颜色", bg=T.BG_ACTIVITY, fg=T.TEXT_FAINT,
                 font=T.font(7)).pack()
        colors = tk.Frame(right, bg=T.BG_ACTIVITY)
        colors.pack(pady=int(3 * s))
        self._color_chips = {}
        for i, col in enumerate(T.TAG_COLORS):
            chip = tk.Frame(colors, bg=col, width=int(11 * s), height=int(11 * s),
                            cursor="hand2", highlightthickness=1,
                            highlightbackground=T.BG_ACTIVITY)
            chip.grid(row=i // 2, column=i % 2, padx=int(2 * s), pady=int(2 * s))
            chip.pack_propagate(False)
            chip.bind("<Button-1>", lambda e, c=col: self.set_pen_color(c))
            self._color_chips[col] = chip

        tk.Button(right, text="自定", font=T.font(7), command=self.pick_pen_color,
                  bg=T.BG_ACTIVITY, fg=T.TEXT_DIM, activebackground=T.BG_HOVER,
                  activeforeground=T.TEXT, relief="flat", bd=0, highlightthickness=0,
                  cursor="hand2", padx=0, pady=int(1 * s)).pack(fill="x", padx=int(2 * s))

        # 自己存下来的颜色，栏窄就只露前几个
        mine_cols = self.store.custom_colors[:4]
        if mine_cols:
            mine = tk.Frame(right, bg=T.BG_ACTIVITY)
            mine.pack(pady=(int(3 * s), 0))
            for i, col in enumerate(mine_cols):
                chip = tk.Frame(mine, bg=col, width=int(11 * s), height=int(11 * s),
                                cursor="hand2", highlightthickness=1,
                                highlightbackground=T.BG_ACTIVITY)
                chip.grid(row=i // 2, column=i % 2, padx=int(2 * s), pady=int(2 * s))
                chip.pack_propagate(False)
                chip.bind("<Button-1>", lambda e, c=col: self.set_pen_color(c))
                self._color_chips[col] = chip

        tk.Label(right, text="粗细", bg=T.BG_ACTIVITY, fg=T.TEXT_FAINT,
                 font=T.font(7)).pack(pady=(int(8 * s), 0))
        widths = tk.Frame(right, bg=T.BG_ACTIVITY)
        widths.pack(pady=int(2 * s))
        self._width_btns = {}
        for w_val, label in ((1.0, "细"), (2.0, "中"), (4.0, "粗")):
            b = tk.Button(widths, text=label, font=T.font(7),
                          command=lambda v=w_val: self.set_pen_width(v),
                          bg=T.BG_ACTIVITY, fg=T.TEXT_DIM, activebackground=T.BG_HOVER,
                          activeforeground=T.TEXT, relief="flat", bd=0,
                          highlightthickness=0, cursor="hand2",
                          padx=0, pady=0, width=2)
            b.pack(pady=1)
            self._width_btns[w_val] = b

        self.btn_settings = tk.Button(right, text="⚙", command=self.open_settings,
                                      font=(T.FONT, int(12 * s)), bg=T.BG_ACTIVITY,
                                      fg=T.TEXT_DIM, activebackground=T.BG_HOVER,
                                      activeforeground=T.TEXT, relief="flat", bd=0,
                                      highlightthickness=0, cursor="hand2",
                                      padx=0, pady=0)
        self.btn_settings.pack(side="bottom", fill="x", pady=int(10 * s))

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-2>", self._pan_start)        # 中键拖着平移
        self.canvas.bind("<B2-Motion>", self._pan_move)

    def _build_panel(self):
        s = self.ui
        panel = tk.Frame(self.vpaned, bg=T.BG_PANEL)
        self.panel = panel
        self.panel_h = int(PANEL_H * s)
        self.vpaned.add(panel, minsize=int(96 * s), height=self.panel_h)

        head = tk.Frame(panel, bg=T.BG_PANEL, height=int(28 * s))
        head.pack(side="top", fill="x")
        head.pack_propagate(False)

        self.btn_panel = tk.Button(head, text="▾", command=self.toggle_panel,
                                   font=T.font(8), bg=T.BG_PANEL, fg=T.TEXT_FAINT,
                                   activebackground=T.BG_HOVER, activeforeground=T.TEXT,
                                   relief="flat", bd=0, highlightthickness=0,
                                   cursor="hand2", padx=int(4 * s), pady=0)
        self.btn_panel.pack(side="left", padx=(int(8 * s), 0))

        tk.Label(head, text="素材池", bg=T.BG_PANEL, fg=T.TEXT_DIM,
                 font=T.font(8, bold=True)).pack(side="left", padx=(int(2 * s), int(6 * s)))
        self.panel_count = tk.Label(head, text="0", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=T.font(8))
        self.panel_count.pack(side="left")

        self.btn_merge_mat = self._flat_btn(head, "合并素材", self.merge_material,
                                            fg="#ffffff", bg=T.ACCENT, hover=T.ACCENT_D,
                                            padx=10, pady=1)
        self.btn_merge_mat.pack(side="right", padx=(int(4 * s), int(10 * s)))
        self._flat_btn(head, "清空", self.clear_materials, bg=T.BG_PANEL,
                       fg=T.TEXT_DIM, padx=8, pady=1).pack(side="right", padx=int(2 * s))

        self.panel_body = tk.Frame(panel, bg=T.BG_PANEL)
        self.panel_body.pack(fill="both", expand=True)

        tk.Frame(self.panel_body, bg=T.LINE, height=1).pack(side="top", fill="x")

        wrap = tk.Frame(self.panel_body, bg=T.BG_PANEL)
        wrap.pack(fill="both", expand=True)

        self.mat_canvas = tk.Canvas(wrap, bg=T.BG_PANEL, highlightthickness=0, bd=0)
        self.mat_canvas.pack(side="left", fill="both", expand=True)
        hsb = ttk.Scrollbar(wrap, orient="horizontal", command=self.mat_canvas.xview,
                            style="Panel.Horizontal.TScrollbar")
        hsb.pack(side="bottom", fill="x")
        self.mat_canvas.configure(xscrollcommand=hsb.set, yscrollincrement=0)

        self.mat_inner = tk.Frame(self.mat_canvas, bg=T.BG_PANEL)
        self._mat_win = self.mat_canvas.create_window((0, 0), window=self.mat_inner, anchor="nw")
        self.mat_inner.bind("<Configure>", lambda e: self.mat_canvas.configure(
            scrollregion=self.mat_canvas.bbox("all")))
        self.mat_canvas.bind("<MouseWheel>", lambda e: self.mat_canvas.xview_scroll(
            -1 if e.delta > 0 else 1, "units"))

    def _build_statusbar(self):
        s = self.ui
        tk.Frame(self, bg=T.LINE, height=1).pack(side="bottom", fill="x")
        bar = tk.Frame(self, bg=T.BG_TOP, height=int(24 * s))
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.lbl_status = tk.Label(bar, text="", bg=T.BG_TOP, fg=T.TEXT_DIM,
                                   font=T.font(8), anchor="w")
        self.lbl_status.pack(side="left", padx=int(12 * s))
        self.lbl_hint = tk.Label(bar, text="Ctrl+O 打开 · Ctrl+E 合并素材 · Esc 取消",
                                 bg=T.BG_TOP, fg=T.TEXT_FAINT, font=T.font(8), anchor="e")
        self.lbl_hint.pack(side="right", padx=int(12 * s))

    # ------------------------------------------------------------ 侧栏

    def show_view(self, key):
        self.view = key
        titles = {"docs": "打开的 PDF", "tags": "标签", "shelves": "工作区"}
        self.side_title.configure(text=titles.get(key, ""))
        for k, b in self._act_btns.items():
            active = (k == key)
            b.configure(fg=T.TEXT if active else T.TEXT_DIM)
            self._act_bars[k].configure(bg=T.ACCENT if active else T.BG_ACTIVITY)
        self.side_action.configure(text="打开" if key == "docs" else "＋")
        if self._sidebar_hidden:
            self.toggle_sidebar()
        self.refresh_sidebar()

    def toggle_sidebar(self):
        """收起=把分隔条拖到活动栏边上，光藏控件是不够的，那块地方还占着。"""
        s = self.ui
        if self._sidebar_hidden:
            self.sidebar.pack(side="left", fill="both", expand=True)
            self._sidebar_hidden = False
            self.btn_side.configure(text="«")
            self.paned.paneconfigure(self.left_pane, minsize=int(180 * s))
            self.after(20, lambda: self._place_hsash(int((ACTIVITY_W + SIDEBAR_W) * s)))
            self.refresh_sidebar()
            self.set_status("侧栏回来了")
        else:
            self.sidebar.pack_forget()
            self._sidebar_hidden = True
            self.btn_side.configure(text="»")
            self.paned.paneconfigure(self.left_pane, minsize=int(ACTIVITY_W * s))
            self.after(20, lambda: self._place_hsash(int((ACTIVITY_W + 2) * s)))
            self.set_status("侧栏收起来了（Ctrl+B 叫回来）")

    def _place_hsash(self, left_w):
        try:
            self.paned.sash_place(0, int(left_w), 0)
        except Exception:
            pass

    def set_theme(self, name=None):
        name = name or ("light" if self.store.theme == "dark" else "dark")
        if name == self.store.theme:
            return
        self.store.theme = name
        self.store.save()
        T.apply(name)
        self.rebuild_ui()
        self.set_status("换成%s主题了" % ("浅色" if name == "light" else "深色"))

    def rebuild_ui(self):
        """换主题之后整棵界面推倒重建——比重刷每个控件的颜色靠谱。"""
        doc = self.doc_path
        view_mode = self.mode
        shelf = self.store.active
        side_view = self.view
        was_collapsed = self._panel_collapsed
        for w in self.winfo_children():
            w.destroy()
        self.configure(bg=T.BG_APP)
        self.pages = []
        self.selected = set()
        self.doc_path = None
        self._dnd_targets = 0
        self._panel_collapsed = False
        self._build_styles()
        self._build_ui()
        self._setup_dnd()
        self._sync_tools()
        if was_collapsed:
            self.toggle_panel()
        self.show_view(side_view)
        self.refresh_top_tabs()
        self.refresh_panel()
        self.mode = view_mode
        if view_mode == "shelf":
            self.open_shelf(shelf)
        elif doc:
            self.open_path(doc)
        else:
            self.show_empty()

    def _side_action(self):
        if self.view == "docs":
            self.open_file()
        elif self.view == "tags":
            self.add_tag()
        else:
            self.add_shelf()

    def _side_width_fix(self, event):
        self.side_canvas.itemconfigure(self._side_win, width=event.width)
        self._side_scroll_fix()

    def _side_scroll_fix(self, event=None):
        """滚动范围至少铺满可视区。不然内容比窗口小时也能滑，一滑内容就飘出去。"""
        bbox = self.side_canvas.bbox("all")
        if not bbox:
            return
        w = max(bbox[2], self.side_canvas.winfo_width())
        h = max(bbox[3], self.side_canvas.winfo_height())
        self.side_canvas.configure(scrollregion=(0, 0, w, h))

    def refresh_sidebar(self):
        for w in self.side_inner.winfo_children():
            w.destroy()
        if self.view == "docs":
            self._sidebar_docs()
        elif self.view == "tags":
            self._sidebar_tags()
        else:
            self._sidebar_shelves()
        self.side_inner.update_idletasks()
        self._side_scroll_fix()
        self.side_canvas.yview_moveto(0)
        self.side_canvas.xview_moveto(0)

    def _row(self, padx=8):
        s = self.ui
        row = tk.Frame(self.side_inner, bg=T.BG_SIDE, cursor="hand2")
        row.pack(fill="x", padx=int(padx * s), pady=1)
        return row

    def _flat(self, widget):
        out = [widget]
        for c in widget.winfo_children():
            out.extend(self._flat(c))
        return out

    def _hover(self, widget, base, on_color=T.BG_HOVER):
        def enter(e):
            for w in self._flat(widget):
                w.configure(bg=on_color)
        def leave(e):
            for w in self._flat(widget):
                w.configure(bg=base)
        for w in self._flat(widget):
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")

    def _sidebar_docs(self):
        s = self.ui
        docs = self.store.recent_docs()
        if not docs:
            tk.Label(self.side_inner,
                     text="还没有打开过文件\n\n拖个 PDF 进来，或者点上面的「打开 PDF」。\n打开过的都会留在这儿。",
                     bg=T.BG_SIDE, fg=T.TEXT_FAINT, font=T.font(9),
                     justify="left", anchor="w",
                     wraplength=int(SIDEBAR_W * self.ui * 0.78)).pack(
                anchor="w", fill="x", padx=int(12 * s), pady=int(16 * s))
            return

        for d in docs:
            path = d["path"]
            cur = bool(self.doc_path) and os.path.normcase(self.doc_path) == os.path.normcase(path)
            here = os.path.isfile(path)
            base = T.ACCENT_SOFT if cur else T.BG_SIDE
            color = self.store.tag_color(self.store.doc_tag(path))

            row = self._row()
            row.configure(bg=base)
            tk.Frame(row, bg=color, width=int(3 * s)).pack(side="left", fill="y", pady=int(4 * s))

            # 右边这两样先占位。它们排在可伸缩的 box 后面 pack 的话，
            # 侧栏一拖窄就被挤没了，✕ 点不到，文件关不掉。
            x = tk.Label(row, text="✕", bg=base, fg=T.TEXT_FAINT, font=T.font(8), cursor="hand2")
            x.pack(side="right", padx=(int(4 * s), int(6 * s)))
            tag = tk.Label(row, text=self.store.tag_name(self.store.doc_tag(path)),
                           bg=base, fg=color, font=T.font(7), cursor="hand2")
            tag.pack(side="right", padx=(int(2 * s), 0))

            box = tk.Frame(row, bg=base)
            box.pack(side="left", fill="x", expand=True, padx=(int(7 * s), 0), pady=int(3 * s))
            name = tk.Label(box, text=short_name(path, 16), bg=base, anchor="w",
                            fg=(T.TEXT if cur else T.TEXT_DIM) if here else T.TEXT_FAINT,
                            font=T.font(9))
            name.pack(anchor="w", fill="x")
            sub = tk.Label(box, bg=base, anchor="w", font=T.font(7),
                           text=(("%s · %s" % (d.get("last", "")[5:16],
                                               self.store.tag_name(self.store.doc_tag(path))))
                                 if here else "文件不在了"),
                           fg=T.TEXT_FAINT if here else T.DANGER)
            sub.pack(anchor="w", fill="x")

            for w in (row, box, name, sub):
                w.bind("<Button-1>", lambda e, p=path: self.open_path(p))
                w.bind("<Button-3>", lambda e, p=path: self._doc_row_menu(e, p))
            x.bind("<Button-1>", lambda e, p=path: self.forget_doc(p))
            tag.bind("<Button-1>", lambda e, p=path: self._doc_menu(e, p))
            if not cur:
                self._hover(row, base)

    def _doc_row_menu(self, event, path):
        m = tk.Menu(self, tearoff=0, bg=T.MENU_BG, fg=T.TEXT,
                    activebackground=T.ACCENT, activeforeground="#ffffff", bd=0)
        m.add_command(label="打开", command=lambda: self.open_path(path))
        m.add_command(label="给它挂个标签：", state="disabled")
        for t in self.store.tags:
            same = (self.store.doc_tag(path) == t["id"])
            m.add_command(label=("● " if same else "　") + t["name"],
                          command=lambda tid=t["id"]: self.set_doc_tag(path, tid))
        m.add_separator()
        m.add_command(label="从记录里删掉", command=lambda: self.forget_doc(path))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _sidebar_tags(self):
        s = self.ui
        for t in self.store.tags:
            tid = t["id"]
            count = len([m for m in self.store.materials if m["tag_id"] == tid])
            cur = (self.tag_filter == tid)
            base = T.ACCENT_SOFT if cur else T.BG_SIDE

            row = self._row()
            row.configure(bg=base)
            cnt = tk.Label(row, text=str(count), bg=base, fg=T.TEXT_FAINT, font=T.font(8))
            cnt.pack(side="right", padx=int(8 * s))
            dot = tk.Label(row, text="●", bg=base, fg=t["color"], font=T.font(9))
            dot.pack(side="left", padx=(int(8 * s), int(6 * s)), pady=int(5 * s))
            name = tk.Label(row, text=t["name"], bg=base, fg=T.TEXT, font=T.font(9), anchor="w")
            name.pack(side="left", fill="x", expand=True)

            for w in (row, dot, name, cnt):
                w.bind("<Button-1>", lambda e, x=tid: self.filter_tag(None if self.tag_filter == x else x))
                w.bind("<Double-Button-1>", lambda e, x=tid: self.rename_tag(x))
                w.bind("<Button-3>", lambda e, x=tid: self._tag_menu(e, x))
            if not cur:
                self._hover(row, base)

    def _tag_menu(self, event, tid):
        m = tk.Menu(self, tearoff=0, bg="#252526", fg=T.TEXT,
                    activebackground=T.ACCENT, activeforeground="#ffffff", bd=0)
        m.add_command(label="改名", command=lambda: self.rename_tag(tid))
        m.add_command(label="只看这个标签", command=lambda: self.filter_tag(tid))
        m.add_command(label="显示全部", command=lambda: self.filter_tag(None))
        m.add_separator()
        m.add_command(label="删掉这个标签", command=lambda: self.remove_tag(tid))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _sidebar_shelves(self):
        s = self.ui
        for i, sh in enumerate(self.store.shelves):
            cur = (i == self.store.active)
            base = T.ACCENT_SOFT if cur else T.BG_SIDE
            row = self._row()
            row.configure(bg=base)
            cnt = tk.Label(row, text=str(len(sh["items"])), bg=base, fg=T.TEXT_FAINT, font=T.font(8))
            cnt.pack(side="right", padx=int(8 * s))
            name = tk.Label(row, text=sh["name"], bg=base,
                            fg=T.TEXT if cur else T.TEXT_DIM, font=T.font(9), anchor="w")
            name.pack(side="left", fill="x", expand=True, padx=(int(9 * s), 0), pady=int(5 * s))

            for w in (row, name, cnt):
                w.bind("<Button-1>", lambda e, x=i: self.open_shelf(x))
                w.bind("<Double-Button-1>", lambda e, x=i: self.rename_shelf(x))
            if not cur:
                self._hover(row, base)

        # 下面把这个工作区里攒的页列出来——不然加进去就看不见了，只能看到个数字
        tk.Frame(self.side_inner, bg=T.LINE, height=1).pack(fill="x", pady=(int(8 * s), int(4 * s)))
        items = self.store.ws_items
        tk.Label(self.side_inner, text="  %d 页" % len(items), bg=T.BG_SIDE,
                 fg=T.TEXT_FAINT, font=T.font(8), anchor="w").pack(fill="x",
                                                                  padx=int(8 * s),
                                                                  pady=(0, int(2 * s)))
        if not items:
            tk.Label(self.side_inner, text="  这个工作区还是空的", bg=T.BG_SIDE,
                     fg=T.TEXT_FAINT, font=T.font(8), anchor="w").pack(
                fill="x", padx=int(12 * s), pady=int(4 * s))
            return

        for idx, it in enumerate(items):
            row = self._row(padx=6)
            num = tk.Label(row, text="%d" % (idx + 1), bg=T.BG_SIDE, fg=T.ACCENT,
                           font=T.font(8, True), width=2)
            x = tk.Label(row, text="✕", bg=T.BG_SIDE, fg=T.TEXT_FAINT, font=T.font(7),
                         cursor="hand2")
            x.pack(side="right", padx=int(5 * s))
            num.pack(side="left", padx=(int(5 * s), int(3 * s)))
            name = tk.Label(row, text="%s · %d" % (short_name(it["title"], 11), it["page"] + 1),
                            bg=T.BG_SIDE, fg=T.TEXT_DIM, font=T.font(8), anchor="w")
            name.pack(side="left", fill="x", expand=True, pady=int(3 * s))

            for w in (row, num, name):
                w.bind("<Button-1>", lambda e, i2=idx: self.goto_ws_item(i2))
                w.bind("<Button-3>", lambda e, i2=idx: self._ws_item_menu(e, i2))
            x.bind("<Button-1>", lambda e, i2=idx: self.remove_ws_item(i2))
            self._hover(row, T.BG_SIDE)

    def _ws_item_menu(self, event, index):
        m = tk.Menu(self, tearoff=0, bg="#252526", fg=T.TEXT,
                    activebackground=T.ACCENT, activeforeground="#ffffff", bd=0)
        m.add_command(label="上移", command=lambda: self.move_ws_item(index, -1))
        m.add_command(label="下移", command=lambda: self.move_ws_item(index, 1))
        m.add_separator()
        m.add_command(label="从工作区移走", command=lambda: self.remove_ws_item(index))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def goto_ws_item(self, index):
        items = self.store.ws_items
        if not (0 <= index < len(items)):
            return
        it = items[index]
        if not os.path.isfile(it["src"]):
            self.set_status("这一页的来源文件不在了")
            return
        if not self.doc_path or os.path.normcase(self.doc_path) != os.path.normcase(it["src"]):
            self.open_path(it["src"])
        self.jump_to_page(it["page"])

    def jump_to_page(self, pno):
        if not self.pages or not (0 <= pno < len(self.pages)):
            return
        pv = self.pages[pno]
        region = str(self.canvas.cget("scrollregion")).split()
        total = float(region[3]) if len(region) == 4 else 1.0
        self.canvas.yview_moveto(max(0.0, (pv.y0 - 10) / max(total, 1)))
        self._schedule_render()
        self._sync_page_label()

    def goto_page(self, event=None):
        """顶栏那个页码格子，回车就跳。"""
        if not self.pages:
            self.set_status("还没打开文件")
            return
        raw = (self.page_var.get() or "").strip()
        try:
            n = int(raw)
        except ValueError:
            self.set_status("输个 1 到 %d 之间的页码" % len(self.pages))
            self._sync_page_label()
            return
        n = max(1, min(n, len(self.pages)))
        self.jump_to_page(n - 1)
        self.set_status("跳到第 %d 页" % n)
        self.canvas.focus_set()

    def _focus_page_entry(self):
        """Ctrl+G：光标直接进页码格子，全选，敲数字就行。"""
        if not hasattr(self, "page_entry"):
            return
        self.page_entry.focus_set()
        self.page_entry.selection_range(0, "end")

    def _sync_page_label(self):
        """顶栏永远显示“你在第几页 / 一共几页”。"""
        if not hasattr(self, "lbl_pages"):
            return
        if self.mode == "shelf" or not self.doc_path or not self.pages:
            self.lbl_pages.configure(text="/ 0")
            if hasattr(self, "page_var"):
                self.page_var.set("")
            return
        a = self._anchor()
        cur = (a[0] + 1) if a else 1
        self.lbl_pages.configure(text="/ %d" % len(self.pages))
        self.page_var.set(str(cur))

    def remove_ws_item(self, index):
        items = self.store.ws_items
        if not (0 <= index < len(items)):
            return
        items.pop(index)
        self.store.save()
        self.refresh_sidebar()
        self._update_buttons()

    def move_ws_item(self, index, delta):
        items = self.store.ws_items
        j = index + delta
        if not (0 <= index < len(items)) or not (0 <= j < len(items)):
            return
        items[index], items[j] = items[j], items[index]
        self.store.save()
        self.refresh_sidebar()

    # ------------------------------------------------------------ 打开 / 关闭

    def open_file(self):
        path = filedialog.askopenfilename(
            title="打开 PDF",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")])
        if path:
            self.open_path(path)

    def open_path(self, path):
        path = os.path.abspath(path)
        try:
            doc = self.engine.doc(path)
        except Exception as exc:
            messagebox.showerror("打不开", "%s\n\n%s" % (short_name(path), exc))
            return
        if doc.needs_pass:
            pwd = simpledialog.askstring("需要密码", "这个 PDF 有密码：", show="*", parent=self)
            if not pwd or not doc.authenticate(pwd):
                self.set_status("密码不对")
                return

        self.store.open_doc(path)
        self.store.save()
        self.mode = "doc"
        self.doc_path = path
        self.selected = set()
        self.pages = []
        self._render_queue = []
        self._clear_canvas()
        self.refresh_top_tabs()
        self.refresh_sidebar()
        self.zoom = self._fit_zoom()
        self.lbl_zoom.configure(text="%d%%" % round(self.zoom * 100))
        self._relayout()
        self._sync_page_label()
        page = self.store.last_page(path)
        if page:
            self.after(80, lambda: self.jump_to_page(page))
        else:
            self.canvas.yview_moveto(0.0)
        self.set_status("打开 %s · %d 页 · 标签「%s」"
                        % (short_name(path, 26), self.engine.page_count(path),
                           self.store.tag_name(self.store.doc_tag(path))))
        self._update_buttons()

    def close_path(self, path):
        """关掉当前的视图而已——历史记录、标签、画笔都留着。"""
        path = os.path.abspath(path)
        if self.doc_path and os.path.normcase(self.doc_path) == os.path.normcase(path):
            self._note_page()
            self.doc_path = None
            self.pages = []
            self.selected = set()
            self.mode = "doc"
            self.canvas.delete("all")
            self.show_empty()
        self.engine.close(path)
        self.store.save()
        self.refresh_top_tabs()
        self.refresh_sidebar()
        self._update_buttons()
        self.set_status("关掉了 %s · 记录和画笔还留着，左边点一下就能回来" % short_name(path, 22))

    def forget_doc(self, path):
        """从历史记录里彻底删掉一条。"""
        path = os.path.abspath(path)
        was_current = bool(self.doc_path) and os.path.normcase(self.doc_path) == os.path.normcase(path)
        if was_current:
            self.doc_path = None
            self.pages = []
            self.selected = set()
            self.mode = "doc"
            self.canvas.delete("all")
            self.show_empty()
        self.store.forget_doc(path)
        self.store.save()
        self.engine.close(path)
        self.refresh_top_tabs()
        self.refresh_sidebar()
        self._update_buttons()
        self.set_status("把 %s 从记录里删掉了" % short_name(path, 24))

    def _note_page(self):
        """记下这个文件看到第几页，下次打开直接跳回来。"""
        if not self.doc_path or not self.pages:
            return
        a = self._anchor()
        if a:
            self.store.save_page(self.doc_path, a[0])
        self._sync_page_label()

    def _drop_canvas_window(self, item):
        """canvas 上嵌的 widget 要自己 destroy——删 item 不会带走它，会变成幽灵浮在窗口上。"""
        if not item:
            return
        try:
            path = self.canvas.itemcget(item, "window")
            if path:
                self.nametowidget(path).destroy()
        except Exception:
            pass
        try:
            self.canvas.delete(item)
        except Exception:
            pass

    def show_empty(self):
        """没打开文件的时候，中间铺一块「最近打开」，不是干巴巴一行提示。"""
        s = self.ui
        c = self.canvas
        c.delete("all")
        self._welcome_frame = None
        w = max(c.winfo_width(), 260)
        h = max(c.winfo_height(), 260)
        c.configure(scrollregion=(0, 0, w, h))
        self.lbl_zoom.configure(text="")
        self._sync_page_label()

        docs = self.store.recent_docs(12)
        if not docs:
            c.create_text(w / 2, h / 2 - int(24 * s),
                          text="把 PDF 拖进来，或者点上面的「打开 PDF」",
                          fill=T.EMPTY_TEXT, font=T.font(int(13 * s)))
            c.create_text(w / 2, h / 2 + int(12 * s),
                          text="点页面可以整页攒进工作区；用右边的裁切工具，能框出想要的一块",
                          fill=T.EMPTY_SUB, font=T.font(9))
            return

        frame = tk.Frame(c, bg=T.BG_EDITOR)
        head = tk.Frame(frame, bg=T.BG_EDITOR)
        head.pack(fill="x", padx=int(34 * s), pady=(int(26 * s), int(8 * s)))
        tk.Label(head, text="最近打开", bg=T.BG_EDITOR, fg=T.TEXT,
                 font=T.font(12, True)).pack(side="left")
        tk.Label(head, text="点一行就打开 · 关掉文件它也不会从这儿消失",
                 bg=T.BG_EDITOR, fg=T.TEXT_FAINT, font=T.font(8)).pack(
            side="left", padx=(int(12 * s), 0))

        for d in docs:
            self._welcome_row(frame, d)

        self._welcome_item = c.create_window(w / 2, 0, window=frame, anchor="n")
        self._welcome_frame = frame

    def _welcome_row(self, parent, d):
        s = self.ui
        path = d["path"]
        here = os.path.isfile(path)
        row = tk.Frame(parent, bg=T.BG_EDITOR, cursor="hand2")
        row.pack(fill="x", padx=int(34 * s), pady=int(1 * s))

        color = self.store.tag_color(self.store.doc_tag(path))
        tk.Frame(row, bg=color, width=int(3 * s), height=int(28 * s)).pack(
            side="left", fill="y", pady=int(5 * s))

        size = ""
        if here:
            try:
                n = os.path.getsize(path)
                size = "%.1f MB" % (n / 1048576.0) if n >= 1048576 else "%d KB" % (n // 1024)
            except Exception:
                size = ""
        meta = "    ".join(x for x in [d.get("last", "")[5:16], size,
                                       self.store.tag_name(self.store.doc_tag(path))] if x)
        tk.Label(row, text=meta, bg=T.BG_EDITOR, fg=T.TEXT_FAINT,
                 font=T.font(8)).pack(side="right", padx=(int(10 * s), 0))

        name = tk.Label(row, text=short_name(path, 40), bg=T.BG_EDITOR,
                        fg=T.TEXT if here else T.TEXT_FAINT, font=T.font(10), anchor="w")
        name.pack(side="left", padx=(int(10 * s), 0), pady=int(6 * s))

        for w in [row, name] + list(row.winfo_children()):
            w.bind("<Button-1>", lambda e, p=path: self.open_path(p))
        self._hover(row, T.BG_EDITOR, T.BG_HOVER)

    # ------------------------------------------------------------ 查看器

    def _fit_zoom(self):
        if not self.doc_path:
            return 1.0
        s = self.ui
        vw = max(self.canvas.winfo_width(), int(160 * s)) - int(56 * s)
        pw, _ = self.engine.page_size(self.doc_path, 0)
        return max(0.15, min(5.0, vw / max(pw * self.dpi / 72.0, 1.0)))

    def fit_width(self):
        if not self.doc_path:
            return
        self.zoom = self._fit_zoom()
        self.lbl_zoom.configure(text="%d%%" % round(self.zoom * 100))
        self._relayout()

    def fit_page(self):
        if not self.doc_path:
            return
        s = self.ui
        vw = max(self.canvas.winfo_width(), int(160 * s)) - int(56 * s)
        vh = max(self.canvas.winfo_height(), int(160 * s)) - int(56 * s)
        pw, ph = self.engine.page_size(self.doc_path, 0)
        k = self.dpi / 72.0
        self.zoom = max(0.15, min(5.0, min(vw / max(pw * k, 1), vh / max(ph * k, 1))))
        self.lbl_zoom.configure(text="%d%%" % round(self.zoom * 100))
        self._relayout()

    def zoom_in(self):
        self._zoom(self.zoom * 1.15)

    def zoom_out(self):
        self._zoom(self.zoom / 1.15)

    def _zoom(self, v):
        if not self.doc_path:
            return
        self.zoom = max(0.15, min(5.0, v))
        self.lbl_zoom.configure(text="%d%%" % round(self.zoom * 100))
        self._relayout()

    def _on_canvas_configure(self, event=None):
        if self.mode == "shelf":
            if self._recenter_job:
                self.after_cancel(self._recenter_job)
            self._recenter_job = self.after(130, self.shelf_relayout)
            return
        if not self.doc_path:
            self.show_empty()
            return
        # 拖分栏时不跟着重排，等手停下来再摆一次。拖动时只让窗口裁切内容，
        # 这样不会有重绘残影，也不会一卡一卡。
        if self._recenter_job:
            self.after_cancel(self._recenter_job)
        self._recenter_job = self.after(130, self._recenter)

    def _recenter(self):
        self._recenter_job = None
        if not self.doc_path or not self.pages:
            return
        c = self.canvas
        s = self.ui
        vw = max(c.winfo_width(), int(160 * s))
        pad = int(24 * s)
        for pv in self.pages:
            nx = max(pad, (vw - pv.w) / 2.0)
            if abs(nx - pv.x) > 0.5:
                c.move("pg:%d" % pv.pno, nx - pv.x, 0)
                pv.x = nx
        region = str(c.cget("scrollregion")).split()
        total = float(region[3]) if len(region) == 4 else 0.0
        max_w = max([pv.w for pv in self.pages], default=0)
        c.configure(scrollregion=(0, 0, max(vw, max_w + 2 * pad), total))

    def _clear_canvas(self):
        """清画布，连带把嵌在上面的 widget 一起送走。"""
        if getattr(self, "_welcome_frame", None) is not None:
            try:
                self._welcome_frame.destroy()
            except Exception:
                pass
            self._welcome_frame = None
        self._clear_crop_chrome()
        self.canvas.delete("all")

    def _relayout(self):
        self._relayout_job = None
        if not self.doc_path:
            self.show_empty()
            return
        c = self.canvas
        s = self.ui
        vw = max(c.winfo_width(), int(160 * s))
        pad = int(24 * s)
        gap = int(20 * s)

        anchor = self._anchor()
        for pv in self.pages:
            pv.photo = None
        self._clear_canvas()
        self.pages = []
        self._render_queue = []

        factor = self.zoom * self.dpi / 72.0
        y = float(pad)
        n = self.engine.page_count(self.doc_path)
        for i in range(n):
            pw, ph = self.engine.page_size(self.doc_path, i)
            w, h = pw * factor, ph * factor
            x = max(pad, (vw - w) / 2.0)
            pv = PageView(i, x, y, w, h)
            self.pages.append(pv)
            c.create_rectangle(x + 2 * s, y + 3 * s, x + w + 2 * s, y + h + 3 * s,
                               fill=T.PAGE_SHADOW, outline="", tags=("pg:%d" % i,))
            pv.base_id = c.create_rectangle(x, y, x + w, y + h, fill=T.PAGE_BG,
                                            outline=T.PAGE_EDGE, width=1, tags=("pg:%d" % i,))
            pv.edge_id = c.create_rectangle(x - 1, y - 1, x + w + 1, y + h + 1,
                                            fill="", outline="", width=int(2 * s),
                                            tags=("pg:%d" % i,))
            pv.label_id = c.create_text(x + w / 2, y + h + int(10 * s),
                                        text="%d / %d" % (i + 1, n),
                                        fill="#5f5f5f", font=T.font(8), tags=("pg:%d" % i,))
            y += h + gap

        total = y - gap + pad
        max_w = max([pv.w for pv in self.pages], default=0)
        c.configure(scrollregion=(0, 0, max(vw, max_w + 2 * pad), total))
        for pv in self.pages:
            self._paint(pv)
            self._paint_annots(pv)
        if anchor and anchor[0] < len(self.pages):
            pv = self.pages[anchor[0]]
            c.yview_moveto(max(0.0, (pv.y0 + anchor[1] * pv.h) / max(total, 1)))
        self._schedule_render()

    def _paint_annots(self, pv):
        """把这一页上的笔画按当前缩放重画一遍。"""
        c = self.canvas
        tag_anno = "anno:%d" % pv.pno
        c.delete(tag_anno)
        if not self.doc_path:
            return
        factor = self.zoom * self.dpi / 72.0
        tag_pg = "pg:%d" % pv.pno
        for a in self.store.annots_of(self.doc_path, pv.pno):
            pts = a["points"]
            kind = a.get("kind")
            if kind == "mark" and len(pts) >= 2:
                x0, y0 = pts[0]
                x1, y1 = pts[-1]
                if self.store.mark_fill:
                    c.create_rectangle(pv.x + min(x0, x1) * factor, pv.y0 + min(y0, y1) * factor,
                                       pv.x + max(x0, x1) * factor, pv.y0 + max(y0, y1) * factor,
                                       fill=a["color"], outline=a["color"], stipple="gray50",
                                       width=max(1, int(a["width"] * self.ui * 0.5)),
                                       tags=(tag_pg, tag_anno))
                else:
                    c.create_rectangle(pv.x + min(x0, x1) * factor, pv.y0 + min(y0, y1) * factor,
                                       pv.x + max(x0, x1) * factor, pv.y0 + max(y0, y1) * factor,
                                       fill="", outline=a["color"],
                                       width=max(2, int(a["width"] * self.ui)),
                                       tags=(tag_pg, tag_anno))
            elif kind == "text":
                self._paint_one_text(pv, a, factor, tag_pg, tag_anno)
            else:
                flat = []
                for x, y in pts:
                    flat.extend([pv.x + x * factor, pv.y0 + y * factor])
                if len(flat) >= 4:
                    c.create_line(*flat, fill=a["color"],
                                  width=max(1, int(a["width"] * self.ui)),
                                  capstyle="round", joinstyle="round", smooth=True,
                                  tags=(tag_pg, tag_anno))

    def _anchor(self):
        if not self.pages:
            return None
        top = self.canvas.canvasy(0)
        for pv in self.pages:
            if pv.y0 <= top <= pv.y1:
                return pv.pno, (top - pv.y0) / max(pv.h, 1)
        return None

    def _schedule_render(self):
        if self._render_scheduled:
            return
        self._render_scheduled = True
        self.after(16, self._pump)

    def _pump(self):
        self._render_scheduled = False
        if not self.doc_path or not self.pages:
            return
        c = self.canvas
        top = c.canvasy(0)
        h = max(c.winfo_height(), 1)
        bot = top + h
        margin = h * 0.8
        need = []
        for pv in self.pages:
            if not (pv.y1 < top - margin or pv.y0 > bot + margin):
                if pv.photo is None:
                    need.append(pv)
            elif pv.photo is not None:
                if pv.img_id:
                    c.delete(pv.img_id)
                pv.img_id = None
                pv.photo = None
        if not need:
            return
        mid = (top + bot) / 2
        need.sort(key=lambda pv: abs((pv.y0 + pv.y1) / 2 - mid))
        self._render_queue = need
        self._next()

    def _next(self):
        if not self._render_queue:
            return
        pv = self._render_queue.pop(0)
        if pv.photo is None and self.doc_path:
            try:
                self._draw_page(pv)
            except Exception:
                if sys.stderr is not None:
                    traceback.print_exc()
        if self._render_queue:
            self.after(1, self._next)

    def _draw_page(self, pv):
        factor = self.zoom * self.dpi / 72.0
        img = self.engine.render(self.doc_path, pv.pno, factor)
        tw, th = max(1, int(round(pv.w))), max(1, int(round(pv.h)))
        if (img.width, img.height) != (tw, th):
            img = img.resize((tw, th), RESAMPLE)
        pv.photo = ImageTk.PhotoImage(img)
        pv.img_id = self.canvas.create_image(pv.x, pv.y, anchor="nw", image=pv.photo,
                                             tags=("pg:%d" % pv.pno,))
        self._paint(pv)
        self._paint_annots(pv)

    def _paint(self, pv):
        c = self.canvas
        s = self.ui
        on = pv.pno in self.selected
        if pv.edge_id:
            if on:
                c.itemconfigure(pv.edge_id, outline=T.ACCENT, width=int(2 * s))
                c.tag_raise(pv.edge_id)
            else:
                c.itemconfigure(pv.edge_id, outline="", width=1)
        if pv.badge_id:
            c.delete(pv.badge_id)
            pv.badge_id = None
        if on:
            rank = sorted(self.selected).index(pv.pno) + 1
            r = int(10 * s)
            cx, cy = pv.x + int(14 * s), pv.y + int(14 * s)
            pv.badge_id = c.create_oval(cx - r, cy - r, cx + r, cy + r,
                                        fill=T.ACCENT, outline=T.PAGE_BG,
                                        width=int(1.5 * s), tags=("pg:%d" % pv.pno,))
            c.create_text(cx, cy, text=str(rank), fill="#ffffff",
                          font=T.font(max(7, int(7 * s)), True), tags=("pg:%d" % pv.pno,))

    def _on_wheel(self, event):
        if event.state & 0x0004:                      # Ctrl + 滚轮 = 缩放
            self._zoom(self.zoom * (1.12 if event.delta > 0 else 1 / 1.12))
            return
        if event.state & 0x0001:
            self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")
        else:
            self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            self._schedule_render()
            self._schedule_note_page()

    def _schedule_note_page(self):
        if self._note_job:
            self.after_cancel(self._note_job)
        self._note_job = self.after(600, self._note_page)

    def _pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self._schedule_render()

    # ------------------------------------------------------------ 鼠标 / 裁切

    def _on_press(self, event):
        if self.mode == "shelf":
            self._shelf_press(event)
            return
        if self.tool == "crop":
            self._crop_press(event)
            return
        if self.tool == "eraser":
            self._erasing = True
            self._erase_at(event.x, event.y)
            return
        if self.tool == "text":
            self._start_text(event.x, event.y)
            return
        if self.tool in ("pen", "mark"):
            pno = self._hit_page(event.x, event.y)
            if pno is None:
                return
            cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            self._pen_page = pno
            self._pen_points = [(cx, cy)]
            self._pen_item = None
            return
        if not self.doc_path:
            return
        aid = self._hit_text(event.x, event.y)
        if aid:
            self._moving_anno = aid
            self._move_from = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
            return
        pno = self._hit_page(event.x, event.y)
        if pno is not None:
            self.toggle_page(pno)

    def _hit_text(self, sx, sy):
        """点到的字儿是哪一个（用来拖动）。"""
        cx, cy = self.canvas.canvasx(sx), self.canvas.canvasy(sy)
        for item in self.canvas.find_overlapping(cx - 2, cy - 2, cx + 2, cy + 2):
            for tag in self.canvas.gettags(item):
                if tag.startswith("tx:"):
                    return tag[3:]
        return None

    def _move_text(self, event):
        aid = getattr(self, "_moving_anno", None)
        if not aid or not self.pages:
            return
        a = None
        for pv in self.pages:
            for cand in self.store.annots_of(self.doc_path, pv.pno):
                if cand["id"] == aid:
                    a = cand
                    break
            if a:
                break
        if a is None:
            self._moving_anno = None
            return
        factor = self.zoom * self.dpi / 72.0
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        dx = (cx - self._move_from[0]) / factor
        dy = (cy - self._move_from[1]) / factor
        ox, oy = a["points"][0]
        a["points"] = [[ox + dx, oy + dy], [ox + dx + 1, oy + dy]]
        self._paint_annots(self.pages[a["page"]])
        self._move_from = (cx, cy)

    def _finish_move(self):
        if getattr(self, "_moving_anno", None):
            self.store.save()
            self.set_status("挪好了")
        self._moving_anno = None

    def toggle_page(self, pno):
        if not self.doc_path or not (0 <= pno < len(self.pages)):
            return
        if pno in self.selected:
            self.selected.discard(pno)
        else:
            self.selected.add(pno)
        for pv in self.pages:
            if pv.pno in self.selected or pv.pno == pno:
                self._paint(pv)
        self._update_buttons()

    def _on_drag(self, event):
        if self.mode == "shelf":
            self._shelf_motion(event)
            return
        if self.tool == "crop":
            self._crop_drag(event)
            return
        if getattr(self, "_moving_anno", None):
            self._move_text(event)
            return
        if self.tool == "eraser" and getattr(self, "_erasing", False):
            self._erase_at(event.x, event.y)
            return
        if self.tool in ("pen", "mark"):
            if not getattr(self, "_pen_page", None) and self._pen_page != 0:
                return
            if not self._pen_points:
                return
            cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            if self.tool == "pen":
                self._pen_points.append((cx, cy))
                flat = []
                for x, y in self._pen_points:
                    flat.extend([x, y])
                if len(flat) >= 4:
                    if self._pen_item is None:
                        self._pen_item = self.canvas.create_line(
                            *flat, fill=self.store.pen_color,
                            width=max(1, int(self.store.pen_width * self.ui)),
                            capstyle="round", joinstyle="round", smooth=True)
                    else:
                        self.canvas.coords(self._pen_item, *flat)
            else:
                self._pen_points = [self._pen_points[0], (cx, cy)]
                x0, y0 = self._pen_points[0]
                if self._crop_item:
                    self.canvas.coords(self._crop_item, x0, y0, cx, cy)
                else:
                    self._crop_item = self.canvas.create_rectangle(
                        x0, y0, cx, cy, outline=self.store.pen_color, width=2, dash=(4, 3))
            return

    def _on_release(self, event):
        if self.mode == "shelf":
            self._shelf_release(event)
            return
        if getattr(self, "_moving_anno", None):
            self._finish_move()
            return
        if self.tool == "eraser":
            self._erasing = False
            return
        if self.tool in ("pen", "mark") and self._pen_points and self._pen_page is not None:
            self._finish_stroke()
            return
        if self.tool == "crop":
            self._crop_release(event)
            return

    # ---- 裁切：拖出框 → 拖角调大小 → √ 收进素材池 / × 放弃

    def _crop_press(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        s = self.ui
        # 已经有一个框：先看按在哪儿
        if self._crop_rect:
            x0, y0, x1, y1 = self._crop_rect
            r = int(9 * s)
            for i, (hx, hy) in enumerate(self._crop_handles_pos()):
                if abs(cx - hx) <= r and abs(cy - hy) <= r:
                    self._crop_mode = "resize"
                    self._crop_handle = i
                    return
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                self._crop_mode = "move"
                self._crop_from = (cx, cy)
                self._crop_origin = (x0, y0, x1, y1)
                return
            # 点在框外 = 重新框一个
        self._crop_rect = [cx, cy, cx, cy]
        self._crop_start_pt = (cx, cy)
        self._crop_mode = "new"
        self._clear_crop_chrome()
        self._draw_crop()

    def _crop_drag(self, event):
        if not self._crop_rect or not self._crop_mode:
            return
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self._apply_crop_drag(cx, cy)

    def _apply_crop_drag(self, cx, cy):
        if self._crop_mode == "new":
            ox, oy = self._crop_start_pt
            self._crop_rect = [min(ox, cx), min(oy, cy), max(ox, cx), max(oy, cy)]
        elif self._crop_mode == "move":
            fx, fy = self._crop_from
            dx, dy = cx - fx, cy - fy
            ox0, oy0, ox1, oy1 = self._crop_origin
            self._crop_rect = [ox0 + dx, oy0 + dy, ox1 + dx, oy1 + dy]
        elif self._crop_mode == "resize":
            x0, y0, x1, y1 = self._crop_rect
            i = self._crop_handle
            if i in (0, 6, 7):
                x0 = cx
            if i in (2, 3, 4):
                x1 = cx
            if i in (0, 1, 2):
                y0 = cy
            if i in (4, 5, 6):
                y1 = cy
            self._crop_rect = [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        self._draw_crop()

    def _crop_release(self, event):
        if not self._crop_rect:
            self._crop_mode = None
            return
        self._crop_mode = None
        x0, y0, x1, y1 = self._crop_rect
        if x1 - x0 < 8 or y1 - y0 < 8:
            self._cancel_crop()
            return
        self._draw_crop()

    def _crop_handles_pos(self):
        x0, y0, x1, y1 = self._crop_rect
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        return [(x0, y0), (mx, y0), (x1, y0), (x1, my),
                (x1, y1), (mx, y1), (x0, y1), (x0, my)]

    def _clear_crop_chrome(self):
        for item in self._crop_items:
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self._crop_items = []
        if self._crop_win:
            self._drop_canvas_window(self._crop_win)
            self._crop_win = None

    def _draw_crop(self):
        s = self.ui
        c = self.canvas
        for item in self._crop_items:
            try:
                c.delete(item)
            except Exception:
                pass
        self._crop_items = []
        if not self._crop_rect:
            return
        x0, y0, x1, y1 = self._crop_rect
        self._crop_items.append(c.create_rectangle(
            x0, y0, x1, y1, outline=T.ACCENT, width=2, dash=(5, 3)))
        r = max(2, int(3 * s))
        for hx, hy in self._crop_handles_pos():
            self._crop_items.append(c.create_rectangle(
                hx - r, hy - r, hx + r, hy + r, fill=T.ACCENT,
                outline=T.PAGE_BG, width=1))

        if self._crop_win:
            self._drop_canvas_window(self._crop_win)
        bx, by = x1 + int(6 * s), y1 + int(6 * s)
        frame = tk.Frame(c, bg=T.BG_APP, highlightthickness=1, highlightbackground=T.LINE)
        ok = tk.Button(frame, text="确定", command=self._commit_crop, font=T.font(8),
                       bg=T.ACCENT, fg="#ffffff", activebackground=T.ACCENT_D,
                       activeforeground="#ffffff", relief="flat", bd=0,
                       highlightthickness=0, cursor="hand2", padx=int(10 * s),
                       pady=int(1 * s))
        ok.pack(side="left")
        no = tk.Button(frame, text="取消", command=self._cancel_crop, font=T.font(8),
                       bg=T.BG_APP, fg=T.TEXT_DIM, activebackground=T.BG_HOVER,
                       activeforeground=T.TEXT, relief="flat", bd=0,
                       highlightthickness=0, cursor="hand2", padx=int(10 * s),
                       pady=int(1 * s))
        no.pack(side="left", padx=(int(3 * s), 0))
        self._crop_win = c.create_window(bx, by, window=frame, anchor="nw")

    def _commit_crop(self):
        if not self._crop_rect:
            return
        x0, y0, x1, y1 = self._crop_rect
        self._cancel_crop()
        self._take_clip(x0, y0, x1, y1)

    def _cancel_crop(self):
        self._clear_crop_chrome()
        self._crop_rect = None
        self._crop_mode = None
        self._crop_handle = None
        self.set_status("放弃这个框")

    def _finish_stroke(self):
        pno = self._pen_page
        pts = self._pen_points or []
        self._pen_points = []
        self._pen_page = None
        for item in (self._crop_item, self._pen_item):
            if item:
                self.canvas.delete(item)
        self._crop_item = None
        self._pen_item = None
        if not self.doc_path or not (0 <= pno < len(self.pages)) or len(pts) < 2:
            return
        pv = self.pages[pno]
        factor = self.zoom * self.dpi / 72.0
        pdf_pts = [((x - pv.x) / factor, (y - pv.y0) / factor) for x, y in pts]
        kind = "mark" if self.tool == "mark" else "ink"
        if abs(pdf_pts[-1][0] - pdf_pts[0][0]) < 3 and abs(pdf_pts[-1][1] - pdf_pts[0][1]) < 3:
            return
        if kind == "ink":
            pdf_pts = _simplify(pdf_pts, 0.8)          # 抽稀，线更顺，存的也少
        self.store.add_annotation(self.doc_path, pno, pdf_pts,
                                  color=self.store.pen_color,
                                  width=self.store.pen_width, kind=kind)
        self.store.save()
        self._paint_annots(pv)
        self._last_pen_page = pno
        self.set_status("画了一笔（%s，%s）· Ctrl+Z 撤销"
                        % (self.store.pen_color,
                           {1.0: "细", 2.0: "中", 4.0: "粗"}.get(self.store.pen_width, "")))

    def _erase_at(self, sx, sy):
        """橡皮：按住拖，碰到哪儿擦哪儿——把笔画在橡皮圈内的那段切掉，剩下的留着。"""
        if not self.doc_path:
            return
        pno = self._hit_page(sx, sy)
        if pno is None or not (0 <= pno < len(self.pages)):
            return
        pv = self.pages[pno]
        factor = self.zoom * self.dpi / 72.0
        px = (self.canvas.canvasx(sx) - pv.x) / factor
        py = (self.canvas.canvasy(sy) - pv.y0) / factor
        r = max(7.0, 11.0 * self.ui) / factor

        changed = False
        for a in list(self.store.annots_of(self.doc_path, pno)):
            pts = a["points"]
            if a.get("kind") == "mark":
                if len(pts) >= 2:
                    x0, y0 = pts[0]
                    x1, y1 = pts[-1]
                    if (min(x0, x1) - r <= px <= max(x0, x1) + r
                            and min(y0, y1) - r <= py <= max(y0, y1) + r):
                        self.store.annotations.remove(a)
                        changed = True
                continue
            segs = _split_stroke(pts, px, py, r)
            if len(segs) == 1 and len(segs[0]) == len(pts):
                continue                                # 没碰上
            self.store.annotations.remove(a)
            for seg in segs:
                self.store.add_annotation(self.doc_path, pno, seg,
                                          color=a["color"], width=a["width"], kind="ink")
            changed = True

        if changed:
            self.store.save()
            self._paint_annots(pv)

    def _start_text(self, sx, sy):
        """在点的地方摆一个输入框，打完回车就印在页面上。"""
        if not self.doc_path:
            return
        pno = self._hit_page(sx, sy)
        if pno is None:
            return
        self._commit_text()
        cx, cy = self.canvas.canvasx(sx), self.canvas.canvasy(sy)
        ent = tk.Entry(self.canvas, font=T.font(int(11 * self.ui)),
                       bg=T.PAGE_BG, fg=self.store.pen_color, relief="solid", bd=1,
                       insertbackground=self.store.pen_color)
        self._text_item = self.canvas.create_window(cx, cy, window=ent, anchor="nw",
                                                    width=int(180 * self.ui))
        self._text_entry = ent
        self._text_at = (pno, cx, cy)
        ent.focus_set()
        ent.bind("<Return>", lambda e: self._commit_text())
        ent.bind("<Escape>", lambda e: self._cancel_text())
        self.set_status("打字，回车放到页面上 · Esc 取消")

    def _commit_text(self):
        ent = getattr(self, "_text_entry", None)
        if ent is None:
            return
        text = ent.get().strip()
        pos = self._text_at
        self._cancel_text(keep_status=True)
        if not text or not pos:
            return
        pno, cx, cy = pos
        if not (0 <= pno < len(self.pages)):
            return
        pv = self.pages[pno]
        factor = self.zoom * self.dpi / 72.0
        px = (cx - pv.x) / factor
        py = (cy - pv.y0) / factor
        self.store.add_annotation(self.doc_path, pno, [[px, py], [px + 1, py]],
                                  color=self.store.pen_color, width=11.0, kind="text",
                                  text=text)
        self.store.save()
        self._paint_annots(pv)
        self.set_status("文字放到第 %d 页了" % (pno + 1))

    def _cancel_text(self, keep_status=False):
        ent = getattr(self, "_text_entry", None)
        if ent is not None:
            try:
                ent.destroy()
            except Exception:
                pass
        if getattr(self, "_text_item", None):
            try:
                self.canvas.delete(self._text_item)
            except Exception:
                pass
        self._text_entry = None
        self._text_item = None
        self._text_at = None
        if not keep_status:
            self.set_status("取消输入")

    def _paint_one_text(self, pv, a, factor, tag_pg, tag_anno):
        x, y = a["points"][0]
        c = self.canvas
        c.create_text(pv.x + x * factor, pv.y0 + y * factor, anchor="nw",
                      text=a.get("text", ""), fill=a["color"],
                      font=T.font(max(6, int(a["width"] * self.ui))),
                      tags=(tag_pg, tag_anno, "tx:%s" % a["id"]))

    def set_pen_color(self, color):
        self.store.pen_color = color
        self.store.save()
        for col, chip in self._color_chips.items():
            same = (col == color)
            chip.configure(highlightbackground=T.TEXT if same else T.BG_ACTIVITY,
                           highlightthickness=2 if same else 1)

    def pick_pen_color(self, after=None):
        """调色板。挑完顺手存一个自定义色槽。"""
        from tkinter import colorchooser
        rgb, hexcol = colorchooser.askcolor(color=self.store.pen_color, parent=self,
                                            title="挑个颜色")
        if hexcol:
            self.store.save_color_slot(hexcol)
            self.set_pen_color(hexcol)
            self.store.save()
            if after:
                after()

    def _forget_color(self, color, after=None):
        """把某个自定义色从槽里涂掉。"""
        if color in self.store.custom_colors:
            self.store.custom_colors.remove(color)
            self.store.save()
        if after:
            after()

    def _paint_all_annots(self):
        for pv in self.pages:
            self._paint_annots(pv)

    def open_settings(self):
        """设置面板：左边说是什么，右边直接改。"""
        s = self.ui
        top = tk.Toplevel(self)
        top.title("设置")
        top.configure(bg=T.BG_PANEL)
        top.transient(self)
        top.resizable(False, False)

        W = int(430 * s)
        body = tk.Frame(top, bg=T.BG_PANEL)
        body.pack(fill="both", expand=True)
        tk.Frame(body, bg=T.BG_PANEL, width=W, height=1).pack()   # 撑住宽度，高度交给内容

        def divider():
            tk.Frame(body, bg=T.LINE, height=1).pack(fill="x", padx=int(20 * s),
                                                     pady=int(12 * s))

        def row(title, sub=""):
            """一行：左边标题+小字说明，右边留给你放控件。"""
            line = tk.Frame(body, bg=T.BG_PANEL)
            line.pack(fill="x", padx=int(20 * s))
            left = tk.Frame(line, bg=T.BG_PANEL)
            left.pack(side="left", fill="x", expand=True)
            tk.Label(left, text=title, bg=T.BG_PANEL, fg=T.TEXT, font=T.font(10),
                     anchor="w").pack(anchor="w")
            if sub:
                tk.Label(left, text=sub, bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=T.font(8),
                         anchor="w", justify="left",
                         wraplength=int(W * 0.55)).pack(anchor="w")
            right = tk.Frame(line, bg=T.BG_PANEL)
            right.pack(side="right")
            return right

        def segmented(parent, options, var):
            """一排小按钮，选中的是蓝底——比小圆点好看，也更好点。"""
            box = tk.Frame(parent, bg=T.BG_INPUT)
            box.pack()
            btns = {}

            def pick(val):
                var.set(val)
                for v, b in btns.items():
                    on = (v == val)
                    b.configure(bg=T.ACCENT if on else T.BG_INPUT,
                                fg="#ffffff" if on else T.TEXT_DIM)

            for val, text in options:
                b = tk.Button(box, text=text, font=T.font(8),
                              command=lambda v=val: pick(v),
                              bg=T.BG_INPUT, fg=T.TEXT_DIM, relief="flat", bd=0,
                              highlightthickness=0, cursor="hand2",
                              padx=int(11 * s), pady=int(4 * s))
                b.pack(side="left")
                btns[val] = b
            pick(var.get())
            return box

        # ---- 画笔粗细
        var_w = tk.DoubleVar(value=self.store.pen_width)
        box = row("画笔粗细", "0.5 到 8，拖着画线的时候按这个来")
        ctl = tk.Frame(box, bg=T.BG_PANEL)
        ctl.pack()
        lbl_w = tk.Label(ctl, text="%.1f" % var_w.get(), bg=T.BG_PANEL, fg=T.TEXT,
                         font=T.font(9), width=4)

        def bump(d):
            v = max(0.5, min(8.0, var_w.get() + d))
            var_w.set(round(v, 1))
            lbl_w.configure(text="%.1f" % var_w.get())

        for text, d in (("−", -0.5), ("＋", 0.5)):
            tk.Button(ctl, text=text, font=T.font(9), command=lambda x=d: bump(x),
                      bg=T.BG_INPUT, fg=T.TEXT_DIM, activebackground=T.BG_HOVER,
                      activeforeground=T.TEXT, relief="flat", bd=0,
                      highlightthickness=0, cursor="hand2", padx=int(7 * s),
                      pady=0).pack(side=("left" if text == "−" else "right"))
        lbl_w.pack(side="left")

        divider()

        # ---- 画笔颜色
        row("画笔颜色", "点色块直接用；空格子存自己挑的，最多 6 个")
        colors_box = tk.Frame(body, bg=T.BG_PANEL)
        colors_box.pack(fill="x", padx=int(20 * s), pady=(int(8 * s), 0))

        def build_colors():
            for w in colors_box.winfo_children():
                w.destroy()
            sys_row = tk.Frame(colors_box, bg=T.BG_PANEL)
            sys_row.pack(anchor="w")
            for col in T.TAG_COLORS:
                chip = tk.Frame(sys_row, bg=col, width=int(22 * s), height=int(22 * s),
                                cursor="hand2",
                                highlightthickness=2 if col == self.store.pen_color else 1,
                                highlightbackground=T.TEXT if col == self.store.pen_color
                                else T.LINE)
                chip.pack(side="left", padx=(0, int(5 * s)))
                chip.pack_propagate(False)
                chip.bind("<Button-1>", lambda e, c=col: (self.set_pen_color(c),
                                                          build_colors()))

            mine = tk.Frame(colors_box, bg=T.BG_PANEL)
            mine.pack(anchor="w", pady=(int(6 * s), 0))
            slots = list(self.store.custom_colors[:S.CUSTOM_SLOTS])
            while len(slots) < S.CUSTOM_SLOTS:
                slots.append(None)
            for i, col in enumerate(slots):
                if col:
                    chip = tk.Frame(mine, bg=col, width=int(22 * s), height=int(22 * s),
                                    cursor="hand2",
                                    highlightthickness=2 if col == self.store.pen_color else 1,
                                    highlightbackground=T.TEXT if col == self.store.pen_color
                                    else T.LINE)
                    chip.pack(side="left", padx=(0, int(5 * s)))
                    chip.pack_propagate(False)
                    chip.bind("<Button-1>", lambda e, c=col: (self.set_pen_color(c),
                                                              build_colors()))
                    chip.bind("<Button-3>", lambda e, c=col: self._forget_color(c, build_colors))
                else:
                    chip = tk.Frame(mine, bg=T.BG_INPUT, width=int(22 * s),
                                    height=int(22 * s), cursor="hand2",
                                    highlightthickness=1, highlightbackground=T.LINE)
                    chip.pack(side="left", padx=(0, int(5 * s)))
                    chip.pack_propagate(False)
                    tk.Label(chip, text="+", bg=T.BG_INPUT, fg=T.TEXT_FAINT,
                             font=T.font(9)).pack(expand=True)
                    for w in [chip] + list(chip.winfo_children()):
                        w.bind("<Button-1>", lambda e: self.pick_pen_color(build_colors))
            tk.Label(mine, text="  右键色块可以涂掉", bg=T.BG_PANEL, fg=T.TEXT_FAINT,
                     font=T.font(7)).pack(side="left")

        build_colors()
        tk.Frame(body, bg=T.BG_PANEL, height=int(4 * s)).pack()

        divider()

        # ---- 高亮框
        var_fill = tk.BooleanVar(value=self.store.mark_fill)
        segmented(row("高亮框", "空心只描边，不挡字；实心是半透明填充"),
                  ((False, "空心"), (True, "实心")), var_fill)

        divider()

        # ---- 素材合并
        var_layout = tk.StringVar(value=self.store.merge_layout)
        segmented(row("素材合并默认排法", "点「合并素材」时会预选这个"),
                  (("single", "每行一张"), ("grid", "占满一行")), var_layout)

        divider()

        # ---- 主题
        var_theme = tk.StringVar(value=self.store.theme)
        segmented(row("主题", "深色看着沉，浅色看着亮"),
                  (("light", "浅色"), ("dark", "深色")), var_theme)

        # ---- 底部按钮
        tk.Frame(body, bg=T.LINE, height=1).pack(fill="x", pady=(int(16 * s), 0))
        pad = tk.Frame(body, bg=T.BG_PANEL)
        pad.pack(fill="x", padx=int(20 * s), pady=int(12 * s))

        def save():
            self.store.pen_width = float(var_w.get())
            self.store.mark_fill = bool(var_fill.get())
            self.store.merge_layout = var_layout.get()
            new_theme = var_theme.get()
            self.store.save()
            top.destroy()
            self.set_pen_width(self.store.pen_width)
            if new_theme != self.store.theme:
                self.set_theme(new_theme)
            else:
                self._paint_all_annots()
            self.set_status("设置存下了")

        tk.Button(pad, text="保存", command=save, font=T.font(9), bg=T.ACCENT,
                  fg="#ffffff", activebackground=T.ACCENT_D, activeforeground="#ffffff",
                  relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                  padx=int(18 * s), pady=int(4 * s)).pack(side="right")
        tk.Button(pad, text="取消", command=top.destroy, font=T.font(9), bg=T.BG_INPUT,
                  fg=T.TEXT_DIM, activebackground=T.BG_HOVER, activeforeground=T.TEXT,
                  relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                  padx=int(12 * s), pady=int(4 * s)).pack(side="right",
                                                          padx=(0, int(8 * s)))

        top.bind("<Escape>", lambda e: top.destroy())
        top.update_idletasks()
        px = self.winfo_rootx() + max(0, (self.winfo_width() - top.winfo_width()) // 2)
        py = self.winfo_rooty() + max(0, (self.winfo_height() - top.winfo_height()) // 5)
        top.geometry("+%d+%d" % (px, py))
        try:
            top.grab_set()
        except Exception:
            pass

    def set_pen_width(self, value):
        self.store.pen_width = value
        self.store.save()
        for w_val, btn in self._width_btns.items():
            same = (abs(w_val - value) < 0.01)
            btn.configure(fg=T.ACCENT if same else T.TEXT_DIM,
                          font=T.font(7, True) if same else T.font(7))

    def undo_stroke(self):
        if not self.doc_path:
            return
        gone = self.store.undo_annotation(self.doc_path,
                                          self._last_pen_page
                                          if self._last_pen_page is not None else 0)
        if gone is None:
            key = os.path.normcase(os.path.abspath(self.doc_path))
            for i in range(len(self.store.annotations) - 1, -1, -1):
                a = self.store.annotations[i]
                if os.path.normcase(os.path.abspath(a["src"])) == key:
                    gone = self.store.annotations.pop(i)
                    break
        if gone is None:
            self.set_status("没有可撤的笔画")
            return
        self.store.save()
        if 0 <= gone["page"] < len(self.pages):
            self._paint_annots(self.pages[gone["page"]])
        self.set_status("撤掉一笔")

    def _hit_page(self, sx, sy):
        cx, cy = self.canvas.canvasx(sx), self.canvas.canvasy(sy)
        for pv in self.pages:
            if pv.x <= cx <= pv.x + pv.w and pv.y0 <= cy <= pv.y1:
                return pv.pno
        return None

    def _take_clip(self, cx0, cy0, cx1, cy1):
        """屏幕上的框 → PDF 里的坐标，存成一个素材。"""
        if not self.doc_path:
            return
        mid_x, mid_y = (cx0 + cx1) / 2, (cy0 + cy1) / 2
        pv = None
        for p in self.pages:
            if p.x <= mid_x <= p.x + p.w and p.y0 <= mid_y <= p.y1:
                pv = p
                break
        if pv is None:
            if self._crop_item:
                self.canvas.delete(self._crop_item)
                self._crop_item = None
            return

        factor = self.zoom * self.dpi / 72.0
        cx0 = max(cx0, pv.x)
        cy0 = max(cy0, pv.y0)
        cx1 = min(cx1, pv.x + pv.w)
        cy1 = min(cy1, pv.y1)
        rect = [(cx0 - pv.x) / factor, (cy0 - pv.y0) / factor,
                (cx1 - pv.x) / factor, (cy1 - pv.y0) / factor]
        if rect[2] - rect[0] < 4 or rect[3] - rect[1] < 4:
            if self._crop_item:
                self.canvas.delete(self._crop_item)
                self._crop_item = None
            return

        mat = self.store.add_material(self.doc_path, pv.pno, rect)
        self.store.save()
        if self._crop_item:
            self.canvas.delete(self._crop_item)
            self._crop_item = None
        self.refresh_panel()
        self.refresh_sidebar()
        self.set_status("裁下一块（第 %d 页）· 进了素材池 · 标签「%s」"
                        % (pv.pno + 1, self.store.tag_name(mat["tag_id"])))

    def set_tool(self, key):
        if key != "text":
            self._cancel_text(keep_status=True)   # 换工具就把没提交的输入框收走
        self.tool = key
        self._pen_page = None
        self._pen_points = []
        if self._crop_item:
            self.canvas.delete(self._crop_item)
            self._crop_item = None
        for k, b in self._tool_btns.items():
            on = (k == key)
            b.configure(bg=T.ACCENT if on else T.BG_ACTIVITY,
                        fg="#ffffff" if on else T.TEXT_DIM)
        self.tool_hint.configure(text={
            "select": "点页面\n选中整页",
            "crop": "拖一个框\n裁进素材池",
            "pen": "按住拖\n画线",
            "mark": "拖一个框\n高亮那块",
            "eraser": "按住拖\n擦掉笔画",
            "text": "点哪儿\n在哪打字",
        }.get(key, ""))
        self.canvas.configure(cursor="arrow" if key == "select" else "crosshair")

    def _sync_tools(self):
        self.set_tool("select")

    def _escape(self):
        if self.tool != "select":
            if self._crop_item:
                self.canvas.delete(self._crop_item)
                self._crop_item = None
            self._crop_start = None
            self._pen_page = None
            self._pen_points = []
            self.set_tool("select")
        else:
            self.clear_selection()

    # ------------------------------------------------------------ 工作区

    def select_all(self):
        if not self.doc_path:
            return
        self.selected = set(range(len(self.pages)))
        for pv in self.pages:
            self._paint(pv)
        self._update_buttons()

    def clear_selection(self):
        if not self.selected:
            return
        self.selected = set()
        for pv in self.pages:
            self._paint(pv)
        self._update_buttons()

    def add_selection(self):
        if not self.doc_path or not self.selected:
            self.set_status("先在页面上点选几页")
            return
        title = os.path.basename(self.doc_path)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for pno in sorted(self.selected):
            self.store.ws_items.append({"src": self.doc_path, "page": pno,
                                        "title": title, "added": now})
        n = len(self.selected)
        self.store.save()
        self.selected = set()
        for pv in self.pages:
            self._paint(pv)
        self._update_buttons()
        self.refresh_sidebar()
        self.set_status("加了 %d 页到「%s」，现在共 %d 页"
                        % (n, self.store.ws["name"], len(self.store.ws_items)))

    def switch_shelf(self, index):
        if not (0 <= index < len(self.store.shelves)) or index == self.store.active:
            return
        self.store.active = index
        self.store.save()
        self.refresh_sidebar()
        self.set_status("切到「%s」· %d 页" % (self.store.ws["name"], len(self.store.ws_items)))

    def open_shelf(self, index):
        """把工作区当成一个能打开的东西，在中间铺开来看。"""
        if not (0 <= index < len(self.store.shelves)):
            return
        self.store.active = index
        self.store.save()
        self.mode = "shelf"
        self.refresh_sidebar()
        self.refresh_top_tabs()
        self._sync_page_label()
        self.shelf_relayout()
        self.set_status("工作区「%s」· %d 页 · 按住卡片拖动可以改合并顺序"
                        % (self.store.ws["name"], len(self.store.ws_items)))

    def show_doc_view(self):
        if self.mode == "doc":
            return
        self.mode = "doc"
        if self.doc_path and self.pages:
            self._relayout()
        else:
            self.show_empty()

    # ---- 工作区视图：卡片墙 + 拖动排序

    def shelf_card_size(self):
        s = self.ui
        return int(126 * s), int(178 * s)

    def shelf_metrics(self):
        cw, ch = self.shelf_card_size()
        gap = int(14 * self.ui)
        pad = int(22 * self.ui)
        vw = max(self.canvas.winfo_width(), int(200 * self.ui))
        cols = max(1, (vw - 2 * pad + gap) // (cw + gap))
        return cw, ch, gap, pad, cols

    def _shelf_pos(self, index):
        cw, ch, gap, pad, cols = self.shelf_metrics()
        row, col = divmod(index, cols)
        return pad + col * (cw + gap), pad + row * (ch + gap), cw, ch

    def shelf_relayout(self):
        c = self.canvas
        s = self.ui
        c.delete("all")
        self._shelf_cards = []
        items = self.store.ws_items
        cw, ch, gap, pad, cols = self.shelf_metrics()
        vw = max(c.winfo_width(), int(200 * s))

        if not items:
            c.configure(scrollregion=(0, 0, vw, max(c.winfo_height(), 240)))
            c.create_text(vw / 2, max(c.winfo_height(), 240) / 2 - int(20 * s),
                          text="「%s」还是空的" % self.store.ws["name"],
                          fill="#5a5a5a", font=T.font(int(13 * s)))
            c.create_text(vw / 2, max(c.winfo_height(), 240) / 2 + int(12 * s),
                          text="打开 PDF，点几页，按上面的「整页入工作区」",
                          fill="#4a4a4a", font=T.font(9))
            return

        total_h = pad
        for i, it in enumerate(items):
            x, y, w, h = self._shelf_pos(i)
            total_h = max(total_h, y + h)
            self._draw_shelf_card(i, it, x, y, w, h)

        total_h += pad
        c.configure(scrollregion=(0, 0, max(vw, pad * 2 + cols * (cw + gap)), total_h))
        region = str(c.cget("scrollregion")).split()
        if len(region) == 4:
            c.yview_moveto(0)

    def _draw_shelf_card(self, index, it, x, y, w, h):
        c = self.canvas
        s = self.ui
        missing = not os.path.isfile(it["src"])
        thumb_h = int(h - 34 * s)
        thumb_w = int(w - 24 * s)
        tag = "card:%d" % index

        c.create_rectangle(x, y, x + w, y + h, fill="#262626",
                           outline=T.LINE, width=1, tags=(tag, "card"))
        # 缩略图
        photo = self._shelf_thumb(it, thumb_w, thumb_h)
        if photo is not None:
            c.create_image(x + w / 2, y + thumb_h / 2 + 4 * s, image=photo,
                           tags=(tag, "card"))
        elif missing:
            c.create_text(x + w / 2, y + thumb_h / 2, text="源文件\n不在了",
                          fill=T.DANGER, font=T.font(8), justify="center", tags=(tag, "card"))
        # 序号
        c.create_rectangle(x, y, x + int(22 * s), y + int(18 * s),
                           fill=T.ACCENT, outline="", tags=(tag, "card"))
        c.create_text(x + int(11 * s), y + int(9 * s), text=str(index + 1),
                      fill="#ffffff", font=T.font(max(7, int(7 * s)), True), tags=(tag, "card"))
        # 来源
        c.create_text(x + 6 * s, y + h - 13 * s, anchor="w",
                      text="%s · %d" % (short_name(it["title"], 13), it["page"] + 1),
                      fill=T.TEXT_DIM, font=T.font(7), tags=(tag, "card"))
        self._shelf_cards.append((x, y, w, h))

    def _shelf_thumb(self, it, box_w, box_h):
        key = (it["src"], it["page"], box_w, box_h)
        cache = self._thumb_cache
        if key in cache:
            return cache[key]
        try:
            if not os.path.isfile(it["src"]):
                return None
            pw, ph = self.engine.page_size(it["src"], it["page"])
            scale = min(box_w / max(pw, 1.0), box_h / max(ph, 1.0)) * self.dpi / 72.0
            img = self.engine.render(it["src"], it["page"], max(scale, 0.05))
            photo = ImageTk.PhotoImage(img)
            cache[key] = photo
            return photo
        except Exception:
            return None

    def _card_at(self, sx, sy):
        cx, cy = self.canvas.canvasx(sx), self.canvas.canvasy(sy)
        for i, (x, y, w, h) in enumerate(self._shelf_cards):
            if x <= cx <= x + w and y <= cy <= y + h:
                return i
        return None

    def _shelf_press(self, event):
        self._drag_from = self._card_at(event.x, event.y)

    def _shelf_motion(self, event):
        if self._drag_from is None or not self._shelf_cards:
            return
        to = self._card_at(event.x, event.y)
        if to is None:
            return
        if self._drop_mark:
            self.canvas.delete(self._drop_mark)
            self._drop_mark = None
        x, y, w, h = self._shelf_cards[to]
        self._drop_mark = self.canvas.create_rectangle(
            x, y, x + w, y + h, outline=T.ACCENT, width=3, dash=(6, 4))

    def _shelf_release(self, event):
        src, self._drag_from = self._drag_from, None
        if self._drop_mark:
            self.canvas.delete(self._drop_mark)
            self._drop_mark = None
        if src is None:
            return
        to = self._card_at(event.x, event.y)
        if to is None or to == src:
            return
        items = self.store.ws_items
        if not (0 <= src < len(items)):
            return
        it = items.pop(src)
        items.insert(max(0, min(to, len(items))), it)
        self.store.save()
        self.shelf_relayout()
        self.refresh_sidebar()
        self.set_status("挪到第 %d 位" % (to + 1))

    def add_shelf(self):
        if not self.store.add_shelf():
            self.set_status("最多 4 个工作区")
            return
        self.store.save()
        self.refresh_sidebar()
        self.set_status("新建了「%s」" % self.store.ws["name"])

    def rename_shelf(self, index):
        if not (0 <= index < len(self.store.shelves)):
            return
        cur = self.store.shelves[index]
        name = simpledialog.askstring("改个名字", "叫什么？", initialvalue=cur["name"], parent=self)
        if not name or not name.strip():
            return
        cur["name"] = name.strip()[:10]
        self.store.save()
        self.refresh_sidebar()

    def merge_workspace(self):
        items = self.store.ws_items
        if not items:
            self.set_status("这个工作区还是空的")
            return
        default = "合并_%s.pdf" % datetime.datetime.now().strftime("%Y%m%d_%H%M")
        out = filedialog.asksaveasfilename(title="合并成哪个 PDF", defaultextension=".pdf",
                                           initialfile=default,
                                           filetypes=[("PDF 文件", "*.pdf")])
        if not out:
            return
        try:
            added, missing = P.merge_pages(items, os.path.abspath(out))
        except Exception as exc:
            messagebox.showerror("合并失败", str(exc))
            return
        self.set_status("合并完成：%s（%d 页）" % (short_name(out, 30), added))
        if missing:
            messagebox.showwarning("有页没合上", "有 %d 页的来源文件找不到了，已跳过。" % len(missing))

    # ------------------------------------------------------------ 标签

    def add_tag(self):
        name = simpledialog.askstring("新标签", "叫什么？", parent=self)
        if not name or not name.strip():
            return
        tag = self.store.add_tag(name)
        if tag:
            self.store.save()
            self.refresh_sidebar()
            self.refresh_panel()
            self.set_status("加了标签「%s」" % tag["name"])

    def rename_tag(self, tid):
        tag = self.store.tag(tid)
        if not tag:
            return
        name = simpledialog.askstring("改标签", "叫什么？", initialvalue=tag["name"], parent=self)
        if not name or not name.strip():
            return
        tag["name"] = name.strip()[:8]
        self.store.save()
        self.refresh_sidebar()
        self.refresh_panel()
        self.refresh_top_tabs()

    def remove_tag(self, tid):
        tag = self.store.tag(tid)
        if not tag:
            return
        n = len([m for m in self.store.materials if m["tag_id"] == tid])
        if not messagebox.askyesno("删掉标签",
                                   "「%s」下面有 %d 个素材，它们会退回「未分类」。继续吗？"
                                   % (tag["name"], n)):
            return
        self.store.remove_tag(tid)
        if self.tag_filter == tid:
            self.tag_filter = None
        self.store.save()
        self.refresh_sidebar()
        self.refresh_panel()
        self.refresh_top_tabs()

    def set_doc_tag(self, path, tid):
        self.store.set_doc_tag(path, tid)
        self.store.save()
        self.refresh_top_tabs()
        self.refresh_sidebar()
        self.set_status("「%s」挂到了「%s」"
                        % (short_name(path, 20), self.store.tag_name(tid)))

    def filter_tag(self, tid):
        self.tag_filter = tid
        self.refresh_sidebar()
        self.refresh_panel()
        self.set_status("素材池：%s" % ("全部" if tid is None else "只看「%s」" % self.store.tag_name(tid)))

    # ------------------------------------------------------------ 素材池

    def visible_materials(self):
        if self.tag_filter:
            return [m for m in self.store.materials if m["tag_id"] == self.tag_filter]
        return list(self.store.materials)

    def refresh_panel(self):
        for w in self.mat_inner.winfo_children():
            w.destroy()
        s = self.ui
        mats = self.visible_materials()
        self.panel_count.configure(text=str(len(mats)))
        self._enabled(self.btn_merge_mat, bool(mats))

        if not mats:
            tk.Label(self.mat_inner,
                     text="  裁下来的块会落在这里 —— 右边的裁切工具，在页面上拖一个框就行",
                     bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=T.font(9)).pack(
                side="left", padx=int(16 * s), pady=int(26 * s))
            self._mat_scroll_fix()
            return

        for m in mats:
            self._material_card(m)
        self._mat_scroll_fix()

    def toggle_panel(self):
        """素材池收成一条。同样得拖分隔条——只藏内容的话那条地方还占着高度。"""
        s = self.ui
        if self._panel_collapsed:
            self.panel_body.pack(fill="both", expand=True)
            self.vpaned.paneconfigure(self.panel, minsize=int(96 * s))
            self._panel_collapsed = False
            self.btn_panel.configure(text="▾")
            self.after(20, lambda: self._place_vsash(self.panel_h))
            self.set_status("素材池展开了")
        else:
            self.panel_body.pack_forget()
            self.vpaned.paneconfigure(self.panel, minsize=int(26 * s))
            self._panel_collapsed = True
            self.btn_panel.configure(text="▴")
            self.after(20, lambda: self._place_vsash(int(26 * s)))
            self.set_status("素材池收起来了")

    def _place_vsash(self, bottom_h):
        try:
            total = self.vpaned.winfo_height()
            self.vpaned.sash_place(0, 0, max(0, int(total) - int(bottom_h)))
        except Exception:
            pass

    def _mat_scroll_fix(self):
        self.mat_inner.update_idletasks()
        bbox = self.mat_canvas.bbox("all")
        if not bbox:
            return
        w = max(bbox[2], self.mat_canvas.winfo_width())
        h = max(bbox[3], self.mat_canvas.winfo_height())
        self.mat_canvas.configure(scrollregion=(0, 0, w, h))
        self.mat_canvas.xview_moveto(0)

    def _material_card(self, m):
        s = self.ui
        card = tk.Frame(self.mat_inner, bg=T.BG_PANEL)
        card.pack(side="left", padx=int(6 * s), pady=int(8 * s))

        color = self.store.tag_color(m["tag_id"])
        thumb = tk.Frame(card, bg=T.BG_INPUT, highlightthickness=1,
                         highlightbackground=color, width=int(84 * s), height=int(62 * s))
        thumb.pack()
        thumb.pack_propagate(False)

        photo = self._material_thumb(m, int(78 * s), int(56 * s))
        if photo is not None:
            lbl = tk.Label(thumb, image=photo, bg=T.BG_INPUT, bd=0, cursor="hand2")
            lbl.image = photo
            lbl.pack(expand=True)
            lbl.bind("<Double-Button-1>",
                     lambda e, mid=m["id"]: self.preview_material(mid))
        thumb.bind("<Double-Button-1>", lambda e, mid=m["id"]: self.preview_material(mid))

        meta = tk.Frame(card, bg=T.BG_PANEL)
        meta.pack(fill="x", pady=(int(2 * s), 0))
        x = tk.Label(meta, text="✕", bg=T.BG_PANEL, fg=T.TEXT_FAINT, font=T.font(7),
                     cursor="hand2")
        x.pack(side="right")
        x.bind("<Button-1>", lambda e, mid=m["id"]: self.remove_material(mid))
        dot = tk.Label(meta, text="●", bg=T.BG_PANEL, fg=color, font=T.font(7),
                       cursor="hand2")
        dot.pack(side="left")
        dot.bind("<Button-1>", lambda e, mid=m["id"]: self._material_menu(e, mid))
        tk.Label(meta, text=short_name(m["src"], 7), bg=T.BG_PANEL, fg=T.TEXT_FAINT,
                 font=T.font(7)).pack(side="left", padx=(int(2 * s), 0))

        for w in (thumb, meta):
            w.bind("<Button-3>", lambda e, mid=m["id"]: self._material_menu(e, mid))

    def preview_material(self, mid):
        """双击素材，弹个大图。"""
        m = self.store.material(mid)
        if not m:
            return
        try:
            import pymupdf as fitz
            clip = fitz.Rect(*m["rect"])
            cw = max(clip.width, 1.0)
            ch = max(clip.height, 1.0)
            scale = max(0.3, min(1100.0 / cw, 780.0 / ch)) * self.dpi / 72.0
            img = self.engine.render(m["src"], m["page"], scale, clip=clip)
            photo = ImageTk.PhotoImage(img)
        except Exception as exc:
            messagebox.showerror("预览不出来", str(exc), parent=self)
            return

        s = self.ui
        top = tk.Toplevel(self)
        top.title("素材 · %s 第 %d 页" % (short_name(m["src"], 22), m["page"] + 1))
        top.configure(bg=T.BG_APP)
        top.transient(self)

        lbl = tk.Label(top, image=photo, bg=T.BG_APP, bd=0, cursor="hand2")
        lbl.image = photo
        lbl.pack(padx=int(12 * s), pady=(int(12 * s), int(4 * s)))

        info = "「%s」· 第 %d 页 · %.0f × %.0f pt  ·  点一下关掉" % (
            self.store.tag_name(m["tag_id"]), m["page"] + 1, clip.width, clip.height)
        tk.Label(top, text=info, bg=T.BG_APP, fg=T.TEXT_DIM,
                 font=T.font(8)).pack(pady=(0, int(10 * s)))

        for w in (top, lbl):
            w.bind("<Button-1>", lambda e: top.destroy())
        top.bind("<Escape>", lambda e: top.destroy())
        # 摆到主窗口中间，别让它飞到屏幕别处去
        top.update_idletasks()
        px = self.winfo_rootx() + max(0, (self.winfo_width() - top.winfo_width()) // 2)
        py = self.winfo_rooty() + max(0, (self.winfo_height() - top.winfo_height()) // 3)
        top.geometry("+%d+%d" % (px, py))
        top.lift()
        top.focus_set()

    def _material_thumb(self, m, box_w, box_h):
        try:
            import pymupdf as fitz
            clip = m["rect"]
            cw = max(clip[2] - clip[0], 1.0)
            ch = max(clip[3] - clip[1], 1.0)
            scale = min(box_w / cw, box_h / ch) * self.dpi / 72.0
            img = self.engine.render(m["src"], m["page"], scale, clip=fitz.Rect(*clip))
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _material_menu(self, event, mid):
        m = self.store.material(mid)
        if not m:
            return
        menu = tk.Menu(self, tearoff=0, bg="#252526", fg=T.TEXT,
                       activebackground=T.ACCENT, activeforeground="#ffffff", bd=0)
        menu.add_command(label="改成标签：", state="disabled")
        for t in self.store.tags:
            same = (m["tag_id"] == t["id"])
            menu.add_command(label=("● " if same else "　") + t["name"],
                             command=lambda tid=t["id"]: self.set_material_tag(mid, tid))
        menu.add_separator()
        menu.add_command(label="从素材池删掉", command=lambda: self.remove_material(mid))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def set_material_tag(self, mid, tid):
        m = self.store.material(mid)
        if not m:
            return
        m["tag_id"] = tid
        self.store.save()
        self.refresh_panel()
        self.refresh_sidebar()

    def remove_material(self, mid):
        self.store.remove_material(mid)
        self.store.save()
        self.refresh_panel()
        self.refresh_sidebar()

    def clear_materials(self):
        mats = self.visible_materials()
        if not mats:
            return
        if not messagebox.askyesno("清空素材池", "这 %d 个素材会被删掉，确定吗？" % len(mats)):
            return
        drop = set(id(m) for m in mats)
        self.store.materials = [m for m in self.store.materials if id(m) not in drop]
        self.store.save()
        self.refresh_panel()
        self.refresh_sidebar()

    def _ask_layout(self):
        """问一句怎么排。返回 "single" / "grid"，取消返回 None。"""
        s = self.ui
        top = tk.Toplevel(self)
        top.title("素材怎么排")
        top.configure(bg=T.BG_APP)
        top.transient(self)
        top.resizable(False, False)
        var = tk.StringVar(value=self.store.merge_layout)

        tk.Label(top, text="排到纸上，一行放几张？", bg=T.BG_APP, fg=T.TEXT,
                 font=T.font(10, True)).pack(anchor="w", padx=int(20 * s),
                                             pady=(int(14 * s), int(8 * s)))
        for val, title, desc in (
            ("single", "每行一张", "素材放大到整行宽，一张张往下摞 —— 适合大图"),
            ("grid", "占满一行", "按原来的宽窄一行塞满再换行 —— 小碎片能挤一排"),
        ):
            box = tk.Frame(top, bg=T.BG_APP)
            box.pack(fill="x", padx=int(20 * s), pady=int(3 * s))
            tk.Radiobutton(box, text=title, variable=var, value=val,
                           bg=T.BG_APP, fg=T.TEXT, selectcolor=T.BG_APP,
                           activebackground=T.BG_APP, activeforeground=T.TEXT,
                           font=T.font(9), anchor="w", cursor="hand2").pack(anchor="w")
            tk.Label(box, text="      " + desc, bg=T.BG_APP, fg=T.TEXT_FAINT,
                     font=T.font(8), anchor="w").pack(anchor="w")

        result = {"v": None}

        def ok():
            result["v"] = var.get()
            top.destroy()

        pad = tk.Frame(top, bg=T.BG_APP)
        pad.pack(fill="x", padx=int(20 * s), pady=int(14 * s))
        tk.Button(pad, text="开始合并", command=ok, font=T.font(9),
                  bg=T.ACCENT, fg="#ffffff", activebackground=T.ACCENT_D,
                  activeforeground="#ffffff", relief="flat", bd=0,
                  highlightthickness=0, cursor="hand2", padx=int(14 * s),
                  pady=int(3 * s)).pack(side="right")
        tk.Button(pad, text="取消", command=top.destroy, font=T.font(9),
                  bg=T.BG_APP, fg=T.TEXT_DIM, activebackground=T.BG_HOVER,
                  activeforeground=T.TEXT, relief="flat", bd=0, highlightthickness=0,
                  cursor="hand2", padx=int(10 * s), pady=int(3 * s)).pack(
            side="right", padx=(0, int(6 * s)))

        top.bind("<Escape>", lambda e: top.destroy())
        top.update_idletasks()
        px = self.winfo_rootx() + max(0, (self.winfo_width() - top.winfo_width()) // 2)
        py = self.winfo_rooty() + max(0, (self.winfo_height() - top.winfo_height()) // 3)
        top.geometry("+%d+%d" % (px, py))
        try:
            top.grab_set()
        except Exception:
            pass
        self.wait_window(top)
        return result["v"]

    def merge_material(self):
        mats = self.visible_materials()
        if not mats:
            self.set_status("素材池是空的")
            return

        layout = self._ask_layout()
        if not layout:
            return

        groups = {}
        for m in mats:
            groups.setdefault(m["tag_id"], []).append(m)

        if len(groups) == 1:
            default = "素材_%s.pdf" % datetime.datetime.now().strftime("%Y%m%d_%H%M")
            out = filedialog.asksaveasfilename(title="合成为 PDF", defaultextension=".pdf",
                                               initialfile=default,
                                               filetypes=[("PDF 文件", "*.pdf")])
            if not out:
                return
            try:
                n = P.merge_materials(list(groups.values())[0], os.path.abspath(out),
                                      layout=layout)
            except Exception as exc:
                messagebox.showerror("合成失败", str(exc))
                return
            self.set_status("合成好了：%s（%d 个素材）" % (short_name(out, 30), n))
            return

        folder = filedialog.askdirectory(title="按标签分组，每组存一个 PDF —— 选个文件夹")
        if not folder:
            return
        made = []
        for tid, group in groups.items():
            path = os.path.join(folder, "%s.pdf" % _safe_name(self.store.tag_name(tid)))
            try:
                n = P.merge_materials(group, path, layout=layout)
                made.append((self.store.tag_name(tid), n))
            except Exception:
                pass
        if made:
            self.set_status("按标签合成了 %d 个：%s"
                            % (len(made), "、".join("%s(%d块)" % (a, b) for a, b in made)))
        else:
            self.set_status("一个都没合成出来")

    # ------------------------------------------------------------ 收尾

    def _update_buttons(self):
        self._enabled(self.btn_addpage, bool(self.selected))

    def set_status(self, text):
        self.lbl_status.configure(text=text)

    def _on_close(self):
        self._note_page()
        self.store.save()
        self.engine.close_all()
        self.destroy()

    # ------------------------------------------------------------ 拖放

    def _setup_dnd(self):
        if not DND_AVAILABLE:
            return
        try:
            _tkdnd.require(self)
        except Exception:
            return
        self._dnd_ok = True
        for child in self.winfo_children():
            self._dnd_targets += self._register_drop(child)

    def _register_drop(self, widget):
        try:
            widget.drop_target_register(_DND_FILES)
            widget.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            widget.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            widget.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            return 0
        n = 1
        for c in widget.winfo_children():
            n += self._register_drop(c)
        return n

    def _on_drop_enter(self, event):
        self.canvas.configure(bg="#24384a")
        self.set_status("松手就打开这个 PDF")
        return _DND_COPY

    def _on_drop_leave(self, event):
        self.canvas.configure(bg=T.BG_EDITOR)
        return _DND_REFUSE

    def _on_drop(self, event):
        self.canvas.configure(bg=T.BG_EDITOR)
        for path in self._parse_drop(event.data):
            if path.lower().endswith(".pdf") and os.path.isfile(path):
                self.open_path(path)
                return _DND_COPY
        self.set_status("拖进来的不是 PDF")
        return _DND_COPY

    def _parse_drop(self, data):
        if not data:
            return []
        try:
            parts = self.tk.splitlist(data)
        except Exception:
            parts = [data]
        out = []
        for raw in parts:
            p = str(raw).strip()
            if p.lower().startswith("file://"):
                p = p[7:]
                try:
                    from urllib.parse import unquote
                    p = unquote(p)
                except Exception:
                    pass
                if len(p) > 2 and p[0] == "/" and p[2] == ":":
                    p = p[1:]
            if p:
                out.append(os.path.normpath(p))
        return out


def _safe_name(name):
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, "_")
    return name or "未分类"


def _simplify(points, min_dist):
    """把靠得太近的点扔掉——手抖的那点小抖动就没了，线反而更顺。"""
    if len(points) <= 2:
        return points
    out = [points[0]]
    d2 = min_dist * min_dist
    for p in points[1:-1]:
        if (p[0] - out[-1][0]) ** 2 + (p[1] - out[-1][1]) ** 2 >= d2:
            out.append(p)
    out.append(points[-1])
    return out


def _split_stroke(points, px, py, r):
    segs, cur = [], []
    r2 = r * r
    for x, y in points:
        if (x - px) ** 2 + (y - py) ** 2 <= r2:
            if len(cur) >= 2:
                segs.append(cur)
            cur = []
        else:
            cur.append([x, y])
    if len(cur) >= 2:
        segs.append(cur)
    return segs


# ---------------------------------------------------------------- 自检

def run_selftest():
    lines = ["PageBox 自检",
             "时间: %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "Python: %s" % sys.version.split()[0],
             "打包运行: %s" % FROZEN,
             "程序目录: %s" % HERE,
             "拖放组件: %s" % ("装上" if DND_AVAILABLE else "没装上")]
    # 自检用的是假的程序目录，别往你真实的工作区里塞东西
    sandbox = tempfile.mkdtemp(prefix="pagebox_selfcheck_")
    real_data_dir = S.data_dir
    S.data_dir = lambda here: os.path.join(sandbox, "data")
    win = None
    try:
        win = App()
        win.withdraw()
        win.update()
        lines.append("拖放已挂上: %s（%d 个控件）" % (win._dnd_ok, win._dnd_targets))
        tmp = tempfile.mkdtemp(prefix="pagebox_selftest_")
        try:
            src = os.path.join(tmp, "s.pdf")
            P.make_test_pdf(src, 3)
            win.open_path(src)
            win.update()
            lines.append("打开与排版: %s（%d 页）" % ("正常" if win.pages else "失败", len(win.pages)))
            if win.pages:
                win._draw_page(win.pages[0])
                lines.append("页面渲染: %s" % ("正常" if win.pages[0].photo else "失败"))
                pv = win.pages[0]
                win._take_clip(pv.x + 10, pv.y0 + 10, pv.x + 200, pv.y0 + 120)
                lines.append("裁切取块: %s（%d 个素材）"
                             % ("正常" if win.store.materials else "失败",
                                len(win.store.materials)))
                if win.store.materials:
                    out = os.path.join(tmp, "m.pdf")
                    n = P.merge_materials(win.store.materials, out)
                    lines.append("素材合成: 正常（%d 块 → %d 页）" % (n, n))
                ws_out = os.path.join(tmp, "w.pdf")
                added, _ = P.merge_pages([{"src": src, "page": 0, "title": "s.pdf"}], ws_out)
                lines.append("工作区合并: %s（%d 页）" % ("正常" if added == 1 else "失败", added))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as exc:
        lines.append("自检出错: %s: %s" % (type(exc).__name__, exc))
    finally:
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        S.data_dir = real_data_dir
        shutil.rmtree(sandbox, ignore_errors=True)
    path = os.path.join(HERE, "自检报告.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main():
    enable_dpi_awareness()
    args = sys.argv[1:]
    if "--selftest" in args:
        run_selftest()
        return
    pdfs = [a for a in args if a.lower().endswith(".pdf")]
    app = App(initial=pdfs[0] if pdfs else None)
    app.mainloop()


if __name__ == "__main__":
    main()
