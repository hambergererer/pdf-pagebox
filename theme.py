# -*- coding: utf-8 -*-
"""配色和字体。两套：深色照 VS Code Dark Modern，浅色照 Light Modern。

界面上的颜色全部从这里取，所以切主题只需要调 apply()，不用改别处。
"""

DARK = {
    "BG_APP":      "#181818",
    "BG_SIDE":     "#181818",
    "BG_ACTIVITY": "#181818",
    "BG_TOP":      "#181818",
    "BG_PANEL":    "#181818",
    "BG_EDITOR":   "#1f1f1f",
    "BG_HOVER":    "#2a2d2e",
    "BG_INPUT":    "#313131",
    "LINE":        "#2b2b2b",
    "LINE_SOFT":   "#232323",
    "TEXT":        "#cccccc",
    "TEXT_DIM":    "#9d9d9d",
    "TEXT_FAINT":  "#6e6e6e",
    "ACCENT":      "#0078d4",
    "ACCENT_D":    "#026ec1",
    "ACCENT_SOFT": "#04395e",
    "DANGER":      "#f14c4c",
    "OK":          "#89d185",
    "PAGE_BG":     "#ffffff",
    "PAGE_EDGE":   "#3c3c3c",
    "PAGE_SHADOW": "#101010",
    "CARD_BG":     "#262626",
    "EMPTY_TEXT":  "#5a5a5a",
    "EMPTY_SUB":   "#4a4a4a",
    "MENU_BG":     "#252526",
}

LIGHT = {
    "BG_APP":      "#f3f3f3",
    "BG_SIDE":     "#f8f8f8",
    "BG_ACTIVITY": "#f8f8f8",
    "BG_TOP":      "#f8f8f8",
    "BG_PANEL":    "#f8f8f8",
    "BG_EDITOR":   "#e9e9e9",     # 查看区比纸暗一点，白页才浮得出来
    "BG_HOVER":    "#e8e8e8",
    "BG_INPUT":    "#ffffff",
    "LINE":        "#e0e0e0",
    "LINE_SOFT":   "#ececec",
    "TEXT":        "#3b3b3b",
    "TEXT_DIM":    "#616161",
    "TEXT_FAINT":  "#9a9a9a",
    "ACCENT":      "#005fb8",
    "ACCENT_D":    "#004a94",
    "ACCENT_SOFT": "#e6f0fa",
    "DANGER":      "#c72e2e",
    "OK":          "#2e7d32",
    "PAGE_BG":     "#ffffff",
    "PAGE_EDGE":   "#d0d0d0",
    "PAGE_SHADOW": "#cfcfcf",
    "CARD_BG":     "#ffffff",
    "EMPTY_TEXT":  "#9a9a9a",
    "EMPTY_SUB":   "#b0b0b0",
    "MENU_BG":     "#ffffff",
}

mode = "dark"

# 标签用的几个色，两套主题共用（都够低饱和，白底深底都压得住）
TAG_COLORS = ["#e06c75", "#e5c07b", "#98c379", "#56b6c2", "#61afef", "#c678dd"]


def apply(name):
    """把某个主题的值铺到模块变量上。"""
    global mode
    mode = "light" if name == "light" else "dark"
    values = LIGHT if mode == "light" else DARK
    g = globals()
    for k, v in values.items():
        g[k] = v


apply("dark")


# ---- 字体
FONT = "Microsoft YaHei UI"

def font(size=9, bold=False):
    return (FONT, size, "bold") if bold else (FONT, size)


def pick_font(root):
    """别人机器上不一定有雅黑，挑一个装了的。"""
    global FONT
    try:
        from tkinter import font as tkfont
        have = set(tkfont.families(root))
    except Exception:
        return
    for name in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑",
                 "Segoe UI", "SimHei", "SimSun", "Arial"):
        if name in have:
            FONT = name
            return
