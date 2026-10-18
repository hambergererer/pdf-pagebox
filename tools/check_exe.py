# -*- coding: utf-8 -*-
"""等 PageBox 的窗口出现，截一张图，然后把它关掉。

先自己起一个：dist\\PageBox\\PageBox.exe，再跑 python tools/check_exe.py

跑法：python tools/check_exe.py [窗口标题里的关键词] [产物文件名]
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes

from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

try:                        # 和被测程序站在同一套坐标里，否则截图会错位
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

user32 = ctypes.windll.user32
WM_CLOSE = 0x0010

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def find_window(keyword, timeout=40.0):
    found = []

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if keyword in buf.value:
                    found.append(hwnd)
        return True

    cb = WNDENUMPROC(_cb)
    end = time.time() + timeout
    while time.time() < end:
        found[:] = []
        user32.EnumWindows(cb, 0)
        if found:
            return found[0]
        time.sleep(0.25)
    return None


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else "PageBox"
    name = sys.argv[2] if len(sys.argv) > 2 else "_exe_shot.png"

    t0 = time.time()
    hwnd = find_window(keyword)
    if not hwnd:
        print("FAIL: 等不到窗口（关键词 %r）" % keyword)
        return 1
    shown = time.time() - t0
    # 抬到最前面，否则抓到的会是压在它上面的别的窗口
    user32.ShowWindow(hwnd, 9)                      # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)   # HWND_TOPMOST, 不动位置和尺寸
    # 窗口出现后再等一会儿，让它把页面渲染出来
    time.sleep(3.0)

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    x, y = max(rect.left, 0), max(rect.top, 0)
    w, h = rect.right - rect.left, rect.bottom - rect.top
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    out = os.path.join(ROOT, name)
    img.save(out)
    print("窗口出现用了 %.1f 秒，尺寸 %dx%d" % (shown, w, h))
    print("saved:", out)

    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)   # 取消置顶 HWND_NOTOPMOST
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
    time.sleep(1.0)
    print("已请求关闭，窗口还在:", bool(user32.IsWindow(hwnd)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
