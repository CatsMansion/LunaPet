# -*- coding: utf-8 -*-
"""gamehub.py —— 游戏主界面（Ronny 2026-10-05）

=====================================================================
桌宠「游戏机」槽位的落地页。之前点一下直接开「深夜厨房」，
现在先过这一层：选游戏。
=====================================================================

## 为什么要有这一层
桌宠抽屉里只有一个入口槽（gamepad）。直接开游戏有两个问题：
  ① 加第二个游戏时，玩家没有"选"的余地；
  ② 游戏和桌宠同时在跑，两套 QTimer 抢同一个 Qt 事件循环，
     掉帧时互相拖累，而且玩家看不到"我刚才在玩什么"。

⭐ 所以这一层同时是**游戏选择器**和**窗口仲裁器**：
  它保证同一时刻最多只有一个游戏窗口活着。

## ⛔ 职责边界（别把游戏逻辑写进来）
  本文件只做三件事：列游戏、点进去、关掉上一个。
  ⛔ 不含任何玩法数值、不含任何绘制玩法元素。
     玩法归各自模块（hundred.py / night.py）。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (QColor, QPainter, QPen, QBrush, QLinearGradient,
                           QFont, QFontDatabase, QPolygonF)
from PySide6.QtWidgets import QWidget, QApplication

VW, VH = 1280, 720

# ---------------------------------------------------------------------------
# ⭐ 字体注册（offscreen / 精简系统上 QFontDatabase 会返回 0 条）
# ---------------------------------------------------------------------------
# ⛔⛔⛔ 不做这一步 = **满屏豆腐块**，而且程序不报任何错。
#   实测：offscreen 平台下 `QFontDatabase.families()` 返回 0，
#   `QFont("Microsoft YaHei UI")` 静默降级成方块，界面看着"画完了"全是 □。
#   ⛔ 这类坑**必须配判据**（自测里 dump 一个中文字形的实际像素宽度，
#     方块宽度会明显小于真实汉字），否则只能靠肉眼发现。
_FONT_READY = False
UI_FAMILY = "Microsoft YaHei UI"
MONO_FAMILY = "Consolas"


def _ensure_font() -> str:
    """注册中文字体，返回可用的 family 名。失败则退回系统默认。"""
    global _FONT_READY, UI_FAMILY
    if _FONT_READY:
        return UI_FAMILY
    _FONT_READY = True
    # ⭐ 按优先级试：雅黑 → 黑体 → 宋体。
    #   ⛔ 别只写死 msyh.ttc：精简版 Windows / 别的机器上可能没有。
    for path in (r"C:\Windows\Fonts\msyh.ttc",
                 r"C:\Windows\Fonts\simhei.ttf",
                 r"C:\Windows\Fonts\simsun.ttc"):
        try:
            fid = QFontDatabase.addApplicationFont(path)
        except Exception:
            continue
        if fid < 0:
            continue
        try:
            fams = QFontDatabase.applicationFontFamilies(fid)
        except Exception:
            continue
        if fams:
            UI_FAMILY = fams[0]
            return UI_FAMILY
    return UI_FAMILY


def _ui_font(px, bold=False):
    return QFont(_ensure_font(), px, QFont.Bold if bold else QFont.Normal)


def _mono_font(px):
    return QFont(MONO_FAMILY, px)

# ---------------------------------------------------------------------------
# 配色（与 night.py 同一套暖色夜间基调，别另起一套）
# ---------------------------------------------------------------------------
BG_TOP     = QColor(28, 26, 38)
BG_BOT     = QColor(46, 38, 44)
CARD_BG    = QColor(58, 52, 64, 235)
CARD_HOVER = QColor(76, 68, 82, 245)
CARD_LINE  = QColor(120, 108, 126, 140)
TXT_MAIN   = QColor(242, 236, 227)
TXT_SUB    = QColor(168, 158, 150)
ACCENT     = QColor(206, 168, 132)
ACCENT_DIM = QColor(140, 112, 88)
LOCKED     = QColor(96, 90, 96)


# ============================================================================
# 游戏清单
# ============================================================================
# ⭐ 每项 = 一个可从桌宠打开的独立游戏。
#   module/cls  ⛔ 别用 import 语句写在文件头 —— hundred / night 都会
#                反过来 import ui_toolbar，成环。必须在函数里延迟 import。
#   available    False = 看得到但点不动（素材/玩法未完工），灰显 + 标注。
#   为什么灰显而不是藏起来：
#     藏起来玩家会以为没这个功能；灰显能让人知道"在这儿，等着"。
class GameEntry:
    def __init__(self, key, name, desc, module, cls, available=True,
                 badge="", keys=""):
        self.key = key
        self.name = name
        self.desc = desc
        self.module = module
        self.cls = cls
        self.available = available
        self.badge = badge
        self.keys = keys


# ⛔ 顺序 = 显示顺序，第一个默认选中。
GAMES = [
    GameEntry(
        "hundred", "是露娜就下一百层",
        "往下掉一百层。左右键调落点，平台只会越来越窄。",
        "hundred", "HundredWindow",
        available=True, badge="新",
        keys="← → 移动　空格 跳　E 买东西　R 重开",
    ),
    GameEntry(
        "night", "深夜厨房",
        "在厨房里偷罐子。潜行、破罐、别被微波炉看见。",
        "night", "NightWindow",
        available=True, badge="",
        keys="← → 移动　空格 跳　J 攻击",
    ),
]


# ============================================================================
# 窗口
# ============================================================================
class GameHubWindow(QWidget):

    def __init__(self, pack=None):
        super().__init__()
        self.pack = pack
        self.setWindowTitle("猫猫公寓 · 游戏")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)

        self.sel = 0
        self.child = None              # ⭐ 当前打开的游戏窗口
        self._child_key = None
        self._t = 0.0

        self._fit()
        self.resize(int(VW * self._s), int(VH * self._s))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._last = None

    def _fit(self):
        """按屏幕高度缩放（与 night.py / hundred.py 同一套）。"""
        try:
            sh = QApplication.primaryScreen().availableGeometry().height()
        except Exception:
            sh = 1080
        self._s = max(0.4, min(1.0, (sh - 90) / float(VH)))
        self.setMinimumSize(640, 400)

    # ------------------------------------------------------------ 生命周期
    def _tick(self):
        import time
        now = time.perf_counter()
        if self._last is None:
            self._last = now
        dt = min(now - self._last, 1.0 / 20.0)
        self._last = now
        self._t += dt
        self.update()

    def closeEvent(self, ev):
        # ⭐ 关主界面时**必须**把子游戏一起关掉。
        #   漏了这一步会出：主界面关了、游戏还开着、工具栏以为全关了，
        #   玩家在屏幕上看不到任何东西但游戏还在跑。
        self._close_child()
        ev.accept()

    def _close_child(self):
        c = self.child
        self.child = None
        self._child_key = None
        if c is None:
            return
        try:
            c.close()
        except RuntimeError:
            pass                          # 已被 C++ 析构

    def _on_child_closed(self, *_):
        self.child = None
        self._child_key = None
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------ 输入
    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            if self.child is not None:
                self._close_child()      # 先退游戏，再退主界面
            else:
                self.close()
            return
        if k in (Qt.Key_Left, Qt.Key_A, Qt.Key_Up, Qt.Key_W):
            self.sel = (self.sel - 1) % len(GAMES)
            return
        if k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_S):
            self.sel = (self.sel + 1) % len(GAMES)
            return
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._launch(GAMES[self.sel])
            return

    def mousePressEvent(self, ev):
        p = ev.position() if hasattr(ev, "position") else QPointF(ev.pos())
        for i, r in enumerate(self._cards()):
            if r.contains(p):
                self.sel = i
                if GAMES[i].available:
                    self._launch(GAMES[i])
                return
        if p.y() > VH - 86:
            self.close()

    # ------------------------------------------------------------ 启动游戏
    def _launch(self, g: GameEntry):
        if not g.available:
            return
        # ⭐ 换游戏 = 先关掉上一个。同一时刻只有一个游戏窗口。
        self._close_child()

        # ⛔ 延迟 import + 双通道（night / pet_engine.night）。
        #   run.py 与打包后的 exe 都把 pet_engine 当顶层模块目录，
        #   测试脚本才走 `from pet_engine import ...`。顺序：先顶层后包内。
        import importlib
        W = None
        for name in (g.module, "pet_engine." + g.module):
            m = sys.modules.get(name)
            if m is not None and hasattr(m, g.cls):
                W = getattr(m, g.cls)
                break
        if W is None:
            try:
                m = importlib.import_module(g.module)
            except ImportError:
                try:
                    m = importlib.import_module("pet_engine." + g.module)
                except Exception as e:
                    print("[游戏] %s 模块加载失败：%s: %s"
                          % (g.name, type(e).__name__, e))
                    return
            W = getattr(m, g.cls, None)
        if W is None:
            print("[游戏] %s 里找不到 %s" % (g.module, g.cls))
            return

        try:
            # ⭐ 两个游戏构造签名一致（都收 pack），⛔ 别按 key 分支写两遍。
            w = W(self.pack)
            w.setAttribute(Qt.WA_DeleteOnClose, True)
            w.destroyed.connect(self._on_child_closed)
            w.show()
        except Exception as e:
            print("[游戏] 打开 %s 失败：%s: %s" % (g.name, type(e).__name__, e))
            return
        self.child = w
        self._child_key = g.key
        self.hide()

    # ------------------------------------------------------------ 布局
    def _cards(self):
        """卡片矩形（逻辑坐标）。⛔ 别在别处重算同一组数。"""
        n = len(GAMES)
        cw, ch = 380.0, 208.0
        gap = 32.0
        total = n * cw + (n - 1) * gap
        x0 = (VW - total) / 2.0
        out = []
        for i in range(n):
            x = x0 + i * (cw + gap)
            out.append(QRectF(x, 276.0, cw, ch))
        return out

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(self._s, self._s)

        # --- 背景 ---
        g = QLinearGradient(0, 0, 0, VH)
        g.setColorAt(0.0, BG_TOP)
        g.setColorAt(1.0, BG_BOT)
        p.fillRect(QRectF(0, 0, VW, VH), g)

        # --- 标题 ---
        p.setFont(_ui_font(30, bold=True))
        p.setPen(QPen(TXT_MAIN))
        p.drawText(QRectF(0, 92, VW, 48), Qt.AlignHCenter, "游戏")
        p.setFont(_ui_font(12))
        p.setPen(QPen(TXT_SUB))
        p.drawText(QRectF(0, 146, VW, 26), Qt.AlignHCenter,
                   "选一个，露娜就坐下了")

        # --- 卡片 ---
        for i, r in enumerate(self._cards()):
            self._card(p, GAMES[i], r, i == self.sel)

        # --- 底部提示 ---
        p.setFont(_mono_font(11))
        p.setPen(QPen(TXT_SUB))
        p.drawText(QRectF(0, VH - 78, VW, 26), Qt.AlignHCenter,
                   "← → 选择　回车 开始　Esc 返回")
        p.setPen(QPen(QColor(120, 112, 108)))
        p.drawText(QRectF(0, VH - 46, VW, 24), Qt.AlignHCenter,
                   "关掉这一页会同时退出正在玩的游戏")
        p.end()

    def _card(self, p, g: GameEntry, r: QRectF, sel: bool):
        # ⭐ 呼吸感：未选中的卡片轻微起伏，避免静态界面显得死。
        lift = 0.0
        if sel:
            lift = 6.0 * (0.5 + 0.5 * _sin(self._t * 2.0))
        rr = QRectF(r.x(), r.y() - lift, r.width(), r.height())

        p.setPen(QPen(ACCENT if sel else CARD_LINE, 2.4 if sel else 1.2))
        p.setBrush(QBrush(CARD_HOVER if sel else CARD_BG))
        p.drawRoundedRect(rr, 16.0, 16.0)

        if not g.available:
            p.setBrush(QBrush(QColor(40, 38, 44, 200)))
            p.drawRoundedRect(rr, 16.0, 16.0)

        col = TXT_MAIN if g.available else LOCKED
        p.setFont(_ui_font(21, bold=True))
        p.setPen(QPen(col))
        p.drawText(QRectF(rr.x() + 26, rr.y() + 28, rr.width() - 52, 34),
                   Qt.AlignLeft | Qt.AlignVCenter, g.name)

        if g.badge:
            bw = 46.0
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(ACCENT if g.available else LOCKED))
            p.drawRoundedRect(
                QRectF(rr.right() - bw - 22, rr.y() + 30, bw, 24), 12.0, 12.0)
            p.setFont(_ui_font(12))
            p.setPen(QPen(BG_TOP if g.available else TXT_SUB))
            p.drawText(QRectF(rr.right() - bw - 22, rr.y() + 30, bw, 24),
                       Qt.AlignCenter, g.badge)

        p.setFont(_ui_font(12))
        p.setPen(QPen(TXT_SUB if g.available else LOCKED))
        p.drawText(QRectF(rr.x() + 26, rr.y() + 76, rr.width() - 52, 52),
                   Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, g.desc)

        p.setFont(_mono_font(11))
        p.setPen(QPen(ACCENT_DIM if g.available else LOCKED))
        foot = g.keys if g.available else "施工中"
        p.drawText(QRectF(rr.x() + 26, rr.bottom() - 46, rr.width() - 52, 28),
                   Qt.AlignLeft | Qt.AlignVCenter, foot)


def _sin(x):
    import math
    return math.sin(x)
