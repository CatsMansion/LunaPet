# -*- coding: utf-8 -*-
"""ui_toolbar.py —— 「生活容器」工具栏（P0 占位版）

Ronny 2026-09-29 的想法：UI 做成厨房抽屉 / 卫生间柜子这类生活里能摸到的容器，
从里面取魔法棒（工具）和露娜互动。⭐ 界面即内容，不是浮在屏上的功能菜单。

P0 阶段先用**程序绘制的占位图形**把链路跑通（收纳柜 → 抽屉 → 取道具 → 露娜反应），
正式美术素材（柜子/抽屉/道具图标）另行派单，届时只需替换 `_draw_*` 三个函数。

用法（由 run.py 创建，绑在主窗口上）：
    bar = ToolBar(pet_window)
    bar.show()
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QPoint, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QLinearGradient
from PySide6.QtWidgets import QWidget

# 收起 / 展开 两种尺寸（贴屏幕左边缘，垂直居中）
W_CLOSED, H_CLOSED = 68, 78

# 道具槽（相对窗口左上角）
SLOT_H = 68
SLOTS = [
    ("wand", "变小魔法棒"),     # 左键变小一档 / 右键变大一档
    ("pillow", "枕头"),         # 一键让她睡
    ("laser", "激光笔"),        # ⭐ 鼠标变小红点，她会追过来跳起来抓
    ("teaser", "逗猫棒"),       # 用逗猫棒逗她（播 tease 动作）
    ("bowl", "饭碗"),           # ⭐ 递碗喂食：端起来一口闷，吃完碗空
    ("brush", "梳子"),          # ⭐ 2026-10-02 梳毛：点一下她会闭眼笑着往梳子上顶
    ("gamepad", "游戏机"),      # ⭐⭐ 2026-10-03 入口：点一下打开「夜间冒险」
    ("sneak", "潜行"),          # ⭐ 2026-10-03：点一下 = 她自己蹑手蹑脚走一段（素材在途，先用 walk 顶）
]

# ⭐⭐ 入口类槽位 vs 道具槽位（2026-10-03）
#   道具 = 拿在手上、光标变成它、去点露娜才施法（wand/pillow/laser/teaser/bowl/brush）
#   入口 = 点了直接开窗口，不占光标（gamepad）
#   ⛔ 混为一谈的下场：点游戏机会先把光标变成手柄，还得再点一次露娜才开 —— 多此一举。
#      ️同理，入口类不该画成"被拿走的空槽"（它没被拿走，它就在那儿）。
_ENTRY_SLOTS = {"gamepad"}
# ⭐ 展开高度按槽位数量自适应（⛔ 不要写死 236，加槽位会溢出）
W_OPEN = 68
H_OPEN = H_CLOSED + SLOT_H * len(SLOTS) + 6


class ToolBar(QWidget):
    def __init__(self, pet_window):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.pet = pet_window
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.open = False
        # ⭐ 2026-09-29：加载角色包里的真素材（派单 23 的 27 个图标）
        #   有素材就用素材，⛔ 没有就退回程序绘制（兜底，保证不崩）
        self.icons = {}
        try:
            from PySide6.QtGui import QPixmap
            import os
            udir = os.path.join(pet_window.pack.root, "ui")
            if os.path.isdir(udir):
                for fn in os.listdir(udir):
                    if fn.lower().endswith(".png"):
                        pm = QPixmap(os.path.join(udir, fn))
                        if not pm.isNull():
                            self.icons[os.path.splitext(fn)[0]] = pm
        except Exception as e:
            print(f"[工具栏] 素材加载失败，退回程序绘制：{e}")
        self._hover_slot = -1
        self._hover_body = False
        # ⭐⭐ 2026-10-02 Ronny：「我还想要**工具箱可以被拖动**」
        #   → 拖动状态机：按下柜体后，鼠标移动超过阈值才算"拖"，否则算"点击（展开/收起）"。
        #   ⛔ 不能只靠 mouseMoveEvent 判断 —— 那样轻点一下柜体也会被当成拖动（她就不展开了）。
        self._drag_origin = None      # 按下时的全局鼠标位置
        self._drag_win = None         # 按下时的窗口左上角
        self._dragging = False
        self._DRAG_START = 5          # 超过这么多像素才算拖动（px）
        # 贴屏幕左侧、垂直居中偏下
        scr = pet_window.screen().availableGeometry()
        self._screen = scr
        self._home = QPoint(scr.left() + 4, scr.top() + int(scr.height() * 0.42))
        self.setGeometry(self._home.x(), self._home.y(), W_CLOSED, H_CLOSED)

    # ---------- 几何 ----------
    def _toggle(self):
        self.open = not self.open
        w, h = (W_OPEN, H_OPEN) if self.open else (W_CLOSED, H_CLOSED)
        self.setGeometry(self._home.x(), self._home.y(), w, h)
        # ⭐⭐ 2026-09-29 修（Ronny：「点击关闭抽屉之后应该直接鼠标就复原了才对」）
        #   关抽屉 = 收起全部操作状态 ⇒ 放下手里的道具、光标复原。
        #   ⛔ 原来只做 setGeometry，手里握着的枕头不被清 → 光标一直是枕头形状。
        #   注意：只在【关闭】时清，展开时不动（否则拿完道具收抽屉会把刚拿的也丢了）。
        if not self.open:
            self._drop_held_tool()
        self.update()

    def _drop_held_tool(self):
        """放下当前手持的道具（光标复原）。

        ⭐ 走 PetWindow.hold_tool(None) 而不是直接改 _held_tool：
           hold_tool 内部 handle 了 unsetCursor，且是唯一的光标出口。
        ⛔ 不能用 hold_tool(self._held_tool) —— 那是 toggle，会二次翻转。
        """
        pet = self.pet
        if getattr(pet, "_held_tool", None) is None:
            return
        try:
            pet.hold_tool(None)          # name=None → 放下 + unsetCursor
        except Exception:
            pet._held_tool = None
            try:
                pet.unsetCursor()
            except Exception:
                pass
        # ⭐ 角色窗口的光标要在鼠标已经悬在它上面时才看得到 ——
        #   主动 refresh 一次，避免"改了就改了但画面没更新"。
        try:
            pet.update()
        except Exception:
            pass
        print("[手持] 关闭抽屉 → 自动放下道具")

    # ---------- 入口类槽位 ----------
    def _open_entry(self, key: str):
        """点入口类槽位 → 打开对应的独立窗口。

        ⭐ 三个必须处理对的细节：
          ① **延迟 import**：`ui → ui_toolbar → night → ui` 会成环，
             顶层 import night 直接 ModuleNotFoundError。
          ② **重复点**：复用同一个窗口（raise + activate），⛔ 不然每点一次开一个。
          ③ **C++ 侧已析构**：窗口被关掉后 Python 引用还在，直接 .show() 抛
             RuntimeError("Internal C++ object already deleted")，要重新建。
        """
        if key != "gamepad":
            return
        # ⭐ 双通道 import，且**优先复用已加载的模块**：
        #   run.py 和打包后的 exe 都把 pet_engine 当作顶层模块目录（`from night import`
        #   才是那条一直成立的路），`.night` 只在测试脚本用 `from pet_engine import …` 时才成立。
        #   → 顺序是 night → .night。反过来写的话，exe 每次都要先撞一次 ImportError。
        #   ⛔ 无论哪条路，night 都必须写进 spec 的 hiddenimports —— 它是函数内 import，
        #      静态分析不保证扫到（工具箱 ui_toolbar 当初也没在清单里，属于运气好）。
        import sys as _sys
        NightWindow = None
        for _name in ("night", "pet_engine.night"):
            _m = _sys.modules.get(_name)
            if _m is not None and hasattr(_m, "NightWindow"):
                NightWindow = _m.NightWindow
                break
        if NightWindow is None:
            try:
                from night import NightWindow         # type: ignore
            except ImportError:
                try:
                    from .night import NightWindow    # type: ignore
                except Exception as e:
                    print(f"[夜间] 模块加载失败：{type(e).__name__}: {e}")
                    return
        if NightWindow is None:
            return

        w = getattr(self, "_night", None)
        if w is not None:
            try:
                w.show()
                w.raise_()
                w.activateWindow()
                return
            except RuntimeError:
                w = None                     # 已被 C++ 析构 → 重建

        try:
            self._night = NightWindow(self.pet.pack)
        except Exception as e:
            print(f"[夜间] 打不开：{type(e).__name__}: {e}")
            return
        # ⭐ 关掉即销毁，好让 destroyed 信号把工具栏放回来
        self._night.setAttribute(Qt.WA_DeleteOnClose, True)
        self._night.destroyed.connect(self._on_night_closed)
        self._night.show()
        # ⭐ 抽屉是 WindowStaysOnTopHint，会一直压在游戏窗口上面挡住画面。
        #   进游戏期间先藏起来，退出游戏再放回来。
        self._drop_held_tool()
        self.hide()
        print("[夜间] 已进入：深夜厨房")

    def _on_night_closed(self, *_):
        self._night = None
        try:
            self.show()
            self._home = self.pos()          # 期间可能没动，保险同步一次
        except Exception:
            pass
        print("[夜间] 已退出")

    def _slot_rect(self, i: int) -> QRect:
        """展开后第 i 个道具的矩形（从顶部往下排，顶部留出柜体）"""
        top = H_CLOSED - 6
        return QRect(6, top + i * SLOT_H, self.width() - 12, SLOT_H - 6)

    def _slot_at(self, pos) -> int:
        if not self.open:
            return -1
        for i in range(len(SLOTS)):
            if self._slot_rect(i).contains(pos):
                return i
        return -1

    # ---------- 交互 ----------
    def mouseMoveEvent(self, ev):
        # ⭐⭐ 2026-10-02 Ronny：「工具箱**可以被拖动**」
        #   按下柜体后移动超过阈值 → 进入拖动；否则原地不动（留给"点击展开/收起"）。
        if self._drag_origin is not None:
            gp = ev.globalPosition().toPoint()
            if not self._dragging:
                if (gp - self._drag_origin).manhattanLength() > self._DRAG_START:
                    self._dragging = True
            if self._dragging:
                nw = self._drag_win + (gp - self._drag_origin)
                self.move(self._clamp(nw))
                self._hover_slot, self._hover_body = -1, False
                return
        if self.open:
            i = self._slot_at(ev.position().toPoint())
        else:
            i = -1
        if i != self._hover_slot:
            self._hover_slot = i
            self.update()
        inside = self.rect().contains(ev.position().toPoint())
        if inside != self._hover_body:
            self._hover_body = inside
            self.update()

    def _clamp(self, pt: QPoint) -> QPoint:
        """拖出屏幕就贴边（⛔ 别让她把工具箱丢到看不见的地方找不回来）"""
        s = self._screen
        x = max(s.left(), min(pt.x(), s.right() - self.width()))
        y = max(s.top(), min(pt.y(), s.bottom() - self.height()))
        return QPoint(x, y)

    def mouseReleaseEvent(self, ev):
        if self._drag_origin is None:
            return
        was_drag = self._dragging
        self._drag_origin = None
        self._drag_win = None
        self._dragging = False
        if not was_drag:
            # 没拖动 → 当成点击：收起态点柜体 = 拉开抽屉；展开态点柜体那一块 = 收回去
            pos = ev.position().toPoint()
            if not self.open:
                self._toggle()
            elif pos.y() < H_CLOSED:
                self._toggle()
            return
        # 拖完了 → 记住新位置，之后展开/收起都围绕它
        self._home = self.pos()
        print("[工具栏] 已拖到 %d,%d" % (self._home.x(), self._home.y()))

    def leaveEvent(self, ev):
        self._hover_slot, self._hover_body = -1, False
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position().toPoint()
        # ⭐ 点道具槽 = 取道具（这个不启动拖动）
        if self.open:
            i = self._slot_at(pos)
            if i >= 0:
                key = SLOTS[i][0]
                if key in _ENTRY_SLOTS:
                    # ⭐ 入口类：直接开窗口，不进"手持"状态（它不施法，它是个入口）
                    self._open_entry(key)
                    self.update()
                    return
                # ⭐⭐ 2026-09-29 改为「手持式」：点道具 = 继承到鼠标上（光标变成道具），
                #   拿鼠标去点露娜才施法。再点同个道具 / 按 ESC = 放下。
                self.pet.hold_tool(key)
                self.update()
                return
        # ⭐ 其余位置（柜体 / 抽屉空白处）→ 启动拖动状态机，松手时再决定是点击还是拖动
        self._drag_origin = ev.globalPosition().toPoint()
        self._drag_win = self.pos()
        self._dragging = False


    # ---------- 绘制（P0 占位图形；正式素材到位后只换这三个函数） ----------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        if not self.open:
            self._draw_cabinet(p, w, h, self._hover_body)
        else:
            self._draw_cabinet(p, w, h, False)
            for i, (key, label) in enumerate(SLOTS):
                self._draw_slot(p, self._slot_rect(i), key, i == self._hover_slot,
                                taken=self._slot_taken(key))
        p.end()

    def _draw_cabinet(self, p: QPainter, w: int, h: int, hover: bool):
        """柜体：⭐ 有 cabinet 素材优先用，否则程序绘制（占位）"""
        pm = self.icons.get("cabinet") or self.icons.get("抽屉") or self.icons.get("柜子")
        if pm is not None:
            # ⭐ 2026-10-02：素材是 136×156（= 68×78 的精确 2x），按**柜体区域**铺满，
            #   不要缩进 min(w,h) 的方框 —— 那会把 68×78 压成 56×64，两侧空 6px。
            body = QRect(2, 2, w - 4, min(h, H_CLOSED) - 4)
            pm2 = pm.scaled(body.width(), body.height(),
                            Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(body.left() + (body.width() - pm2.width()) // 2,
                         body.top() + (body.height() - pm2.height()) // 2, pm2)
            return
        # 兜底：程序绘制
        body = QRect(2, 2, w - 4, min(h, H_CLOSED) - 4)
        p.setPen(QPen(QColor(90, 66, 48), 2))
        p.setBrush(QBrush(QColor(198, 158, 116) if not hover else QColor(216, 178, 136)))
        p.drawRoundedRect(body, 10, 10)
        p.setPen(QPen(QColor(120, 90, 66), 2))
        for k in (1, 2):
            y = body.top() + body.height() * k // 3
            p.drawLine(body.left() + 8, y, body.right() - 8, y)
        # 拉手
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(120, 90, 66)))
        hy = body.center().y()
        p.drawRoundedRect(body.center().x() - 9, hy - 3, 18, 6, 3, 3)

    def _slot_taken(self, key: str) -> bool:
        """这个道具是不是**正被拿在手上**（→ 槽位要画成空的）。

        ⭐⭐ 2026-10-02 Ronny：「鼠标点击工具箱里的东西之后鼠标会变成该东西，
        **然后原来的图标变成一个被拿走之后空的槽位**」

        ⛔ 入口类槽位（gamepad）**永远不画成空槽** —— 它没被拿走，它就在那儿。
        """
        key = str(key)
        if key in _ENTRY_SLOTS:
            return False
        return getattr(self.pet, "_held_tool", None) == key

    def _draw_slot(self, p: QPainter, r: QRect, key: str, hover: bool, taken: bool = False):
        """道具槽：底板 + 图标（⭐ 优先用角色包里的真素材，没有才退回程序绘制）

        `taken=True` → 画成**空槽**（道具已被拿在手上）。
        """
        # ⭐⭐ 2026-10-02 派单 33 素材装机：slot.png / slot_taken.png 是**精确 2x**
        #   （112×124 → 槽位 56×62），所以直接按槽位尺寸 1:2 画，不做二次缩放
        #   ——二次缩放会糊掉 2px 描边。两张素材 alpha 轮廓 XOR 仅 0.205%，
        #   拿起/放回时底板不会跳。
        _plate = self.icons.get("slot_taken" if taken else "slot")
        if _plate is not None:
            p.drawPixmap(r, _plate, QRect(0, 0, _plate.width(), _plate.height()))
            if hover and not taken:
                # 悬停高亮：素材是静态的，用一层暖色叠加代替程序版的换色
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(255, 226, 170, 70)))
                p.drawRoundedRect(r, 16, 16)
        elif taken:
            # 兜底：程序绘制的空槽（内凹暗底 + 虚线边 + 中央凹点）
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(196, 176, 152)))          # 凹槽底色（比底板暗）
            p.drawRoundedRect(r, 8, 8)
            p.setPen(QPen(QColor(150, 122, 96), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 6, 6)
            # 虚线外框（"这个位置是空的"）
            pen = QPen(QColor(168, 140, 112), 1.4, Qt.DashLine)
            pen.setDashPattern([3, 3])
            p.setPen(pen)
            p.drawRoundedRect(r.adjusted(4, 4, -4, -4), 5, 5)
            # 中央一个小凹点
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(176, 156, 132)))
            p.drawEllipse(r.center(), 3, 3)
            return
        else:
            # 兜底：程序绘制的普通底板
            p.setPen(QPen(QColor(120, 90, 66), 1))
            p.setBrush(QBrush(QColor(232, 214, 190) if not hover else QColor(255, 240, 214)))
            p.drawRoundedRect(r, 8, 8)
        cx, cy = r.center().x(), r.center().y()

        # ✅✅ 2026-10-02 派单 34：新 pillow.png 已重出并装机（1/3 一次过），
        #   素面米白长方形软枕、四角圆、边上一圈缝线，**不再是派**。
        #   ⛔ 本屏蔽名单与 ui.py `_make_tool_cursor` 里的是**同一份规则的两个副本** ——
        #   当初只改了这里、漏了光标那边（Ronny 反馈"点了没变化"）。
        #   ⭐ **下次往里加/删任何 key，必须两处一起改**（全局搜 `_BAD_ASSET`）。
        #   ✅ 目前为空 —— 六个道具全部使用真素材。
        _BAD_ASSET: set = set()
        pm = None if key in _BAD_ASSET else self.icons.get(key)
        if pm is not None:
            # 等比缩到槽内（留 8px 内边距），居中绘制
            s = min(r.width() - 16, r.height() - 16)
            pm2 = pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(r.center().x() - pm2.width() // 2,
                         r.center().y() - pm2.height() // 2, pm2)
            return

        if key == "wand":
            # 魔法棒：斜杖 + 顶端四芒星
            p.setPen(QPen(QColor(120, 80, 150), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(cx - 13, cy + 16, cx + 10, cy - 8)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 226, 120)))
            p.drawEllipse(cx + 8, cy - 16, 16, 16)
            p.setBrush(QBrush(QColor(255, 255, 230)))
            p.drawEllipse(cx + 12, cy - 12, 8, 8)
        elif key == "laser":
            # 激光笔：黑色笔杆 + 头部 + 射出的一小段红线 + 末端红点
            p.setPen(QPen(QColor(50, 52, 60), 1.4))
            p.setBrush(QBrush(QColor(58, 60, 70)))
            p.drawRoundedRect(cx - 20, cy - 12, 26, 24, 6, 6)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(120, 124, 138)))
            p.drawRoundedRect(cx - 24, cy - 9, 6, 18, 2, 2)
            # 射出的红线（斜向右上）
            p.setPen(QPen(QColor(255, 70, 70, 200), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(cx - 1, cy - 3, cx + 15, cy - 15)
            # 末端红点（带光晕）
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 60, 60, 70)))
            p.drawEllipse(cx + 10, cy - 20, 14, 14)
            p.setBrush(QBrush(QColor(255, 40, 40)))
            p.drawEllipse(cx + 13, cy - 17, 8, 8)
            p.setBrush(QBrush(QColor(255, 210, 210)))
            p.drawEllipse(cx + 15, cy - 15, 4, 4)
        elif key == "pillow":
            # 枕头：蓬松的四角鼓包 + 中间睡痕凹窝 + 柔和阴影
            #   ⛔ 旧画法是"白色圆角矩形 + 一条横线" —— 读起来像药片/胶囊，不像枕头。
            #   ✅ 枕头的识别特征是【软】：四角鼓起、中间被头压出一个窝、下缘有阴影。
            from PySide6.QtGui import QPainterPath, QRadialGradient
            from PySide6.QtCore import QPointF
            # ① 投影（让她看起来是"放着的"，不是在贴纸）
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(180, 180, 195, 90)))
            p.drawRoundedRect(cx - 21, cy - 8, 42, 24, 12, 12)
            # ② 枕体：用四段贝塞尔画出"两头鼓、中间束"的软枕轮廓
            path = QPainterPath()
            L, R, T, Bt = cx - 21.0, cx + 21.0, cy - 13.0, cy + 11.0
            mx = float(cx)
            path.moveTo(L, cy)
            # 左上鼓包
            path.cubicTo(L, T, L + 5, T - 3, mx - 7, T - 2)
            # 上方中间微微下凹（头的压痕）
            path.cubicTo(mx - 2, T + 1, mx + 2, T + 1, mx + 7, T - 2)
            # 右上鼓包
            path.cubicTo(R - 5, T - 3, R, T, R, cy)
            # 右下鼓包
            path.cubicTo(R, Bt, R - 5, Bt + 3, mx + 7, Bt + 2)
            # 下方中间（比上方平一些，压在地面上）
            path.cubicTo(mx + 2, Bt, mx - 2, Bt, mx - 7, Bt + 2)
            # 左下鼓包
            path.cubicTo(L + 5, Bt + 3, L, Bt, L, cy)
            path.closeSubpath()
            # ③ 填充：左上受光、右下背光
            grad = QRadialGradient(QPointF(cx - 8, cy - 7), 34)
            grad.setColorAt(0.0, QColor(255, 255, 255))
            grad.setColorAt(0.6, QColor(247, 247, 252))
            grad.setColorAt(1.0, QColor(226, 227, 236))
            p.setPen(QPen(QColor(176, 177, 190), 1.6))
            p.setBrush(QBrush(grad))
            p.drawPath(path)
            # ④ 中间睡痕：一条柔和的凹陷弧（提示"有人睡过"）
            p.setPen(QPen(QColor(208, 209, 222), 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(cx - 13, cy - 3, 26, 11, 200 * 16, 140 * 16)
            # ⑤ 高光小点（软材质的反光）
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 210)))
            p.drawEllipse(cx - 13, cy - 8, 7, 5)
        elif key == "gamepad":
            # ⭐ 2026-10-03「游戏机」入口（⛔ packs/luna/ui 里还没有 gamepad.png，先程序绘制）
            #   识别特征 = 手柄剪影：左右两个握把 + 左侧十字键 + 右侧两颗圆按钮。
            #   不要画成电视/街机 —— 那是"机"，手柄才像"能拿去玩的东西"。
            from PySide6.QtGui import QPainterPath
            from PySide6.QtCore import QPointF
            p.setPen(Qt.NoPen)
            # ① 投影
            p.setBrush(QBrush(QColor(20, 22, 34, 70)))
            p.drawRoundedRect(cx - 20, cy - 6, 40, 22, 11, 11)
            # ② 手柄主体：中间窄、两端鼓的蝴蝶形
            path = QPainterPath()
            T, Bt = cy - 11.0, cy + 11.0
            path.moveTo(cx - 20, cy - 2)
            path.cubicTo(cx - 21, T, cx - 13, T - 2, cx - 6, T)
            path.cubicTo(cx - 2, T - 3, cx + 2, T - 3, cx + 6, T)
            path.cubicTo(cx + 13, T - 2, cx + 21, T, cx + 20, cy - 2)
            path.cubicTo(cx + 20, Bt, cx + 12, Bt + 3, cx + 7, Bt - 1)
            path.cubicTo(cx + 4, Bt - 5, cx - 4, Bt - 5, cx - 7, Bt - 1)
            path.cubicTo(cx - 12, Bt + 3, cx - 20, Bt, cx - 20, cy - 2)
            path.closeSubpath()
            grad = QLinearGradient(QPointF(0, T), QPointF(0, Bt))
            grad.setColorAt(0.0, QColor(126, 132, 152))
            grad.setColorAt(1.0, QColor(74, 78, 98))
            p.setPen(QPen(QColor(46, 48, 64), 1.6))
            p.setBrush(QBrush(grad))
            p.drawPath(path)
            # ③ 左侧十字方向键
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(40, 44, 58)))
            p.drawRoundedRect(cx - 16, cy - 4, 11, 4, 1.5, 1.5)
            p.drawRoundedRect(cx - 12.5, cy - 8, 4, 11, 1.5, 1.5)
            # ④ 右侧两颗圆按钮（红 / 黄）
            p.setBrush(QBrush(QColor(232, 92, 92)))
            p.drawEllipse(QPointF(cx + 9, cy - 2), 3.6, 3.6)
            p.setBrush(QBrush(QColor(246, 200, 92)))
            p.drawEllipse(QPointF(cx + 15, cy + 2), 3.6, 3.6)
            # ⑤ 中间两颗小键 + 顶部高光
            p.setBrush(QBrush(QColor(56, 60, 76)))
            p.drawEllipse(QPointF(cx - 3, cy + 1), 2.2, 2.2)
            p.drawEllipse(QPointF(cx + 3, cy + 1), 2.2, 2.2)
            p.setPen(QPen(QColor(255, 255, 255, 120), 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(cx - 13, cy - 8, cx - 4, cy - 9)
            return
        elif key == "sneak":
            # 潜行：两道"静音"波纹（左上）+ 一串渐淡的猫脚印（斜向右下）
            #   ⭐ 与 ui.py `_make_tool_cursor` 里的潜行光标是**同一套图形语言**
            #   （波纹开口方向 / 脚印渐隐都一致）—— 槽位图标和光标长得不一样会被当成两个东西
            #   ⛔ 不画投影底 —— 40px 里一块灰底会把波纹和脚印全吃掉（实测像一团污渍）
            from PySide6.QtCore import QPointF
            p.setPen(QPen(QColor(150, 165, 200), 2))
            p.setBrush(Qt.NoBrush)
            p.drawArc(cx - 18, cy - 20, 20, 20, 200 * 16, 140 * 16)   # 外波纹
            p.drawArc(cx - 11, cy - 13, 6, 6, 200 * 16, 140 * 16)     # 内波纹
            p.setPen(Qt.NoPen)
            for dx, dy, a in [(-4, 8, 235), (4, 0, 150), (12, -8, 80)]:
                p.setBrush(QBrush(QColor(140, 158, 198, a)))          # 越走越轻
                p.drawEllipse(QPointF(cx + dx - 2, cy + dy - 2), 3.8, 2.8)
        elif key == "bowl":
            # 饭碗：敞口碗 + 碗口食团 + 碗足 + 高光
            # ⛔ QLinearGradient 已在模块级导入，这里⛔⛔ 不要重复 `from ... import` ——
            #    函数内 import 会把它降级成【局部变量】，只有走到这一行才有值，
            #    排在这一行之前的分支（gamepad）会 UnboundLocalError。
            from PySide6.QtGui import QPainterPath
            from PySide6.QtCore import QPointF
            # ① 碗身：上宽下窄的梯形，底圆
            path = QPainterPath()
            path.moveTo(cx - 19, cy - 5)
            path.lineTo(cx - 13, cy + 14)
            path.quadTo(cx, cy + 20, cx + 13, cy + 14)
            path.lineTo(cx + 19, cy - 5)
            path.closeSubpath()
            grad = QLinearGradient(QPointF(0, cy - 5), QPointF(0, cy + 18))
            grad.setColorAt(0.0, QColor(245, 246, 250))
            grad.setColorAt(1.0, QColor(205, 208, 218))
            p.setPen(QPen(QColor(150, 152, 165), 1.6))
            p.setBrush(QBrush(grad))
            p.drawPath(path)
            # ② 碗口椭圆（食物面）
            p.setPen(QPen(QColor(150, 152, 165), 1.6))
            p.setBrush(QBrush(QColor(232, 234, 242)))
            p.drawEllipse(cx - 19, cy - 12, 38, 14)
            # ③ 碗里的猫粮（几颗深色小粒）
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(QColor(150, 105, 66)))
            for dx, dy, r in [(-8, -7, 3), (-1, -9, 3.4), (6, -7, 2.8),
                              (-5, -4, 2.4), (4, -4, 2.6)]:
                p.drawEllipse(QPointF(cx + dx, cy + dy), r, r)
            # ④ 碗足（小圆台）
            p.setPen(QPen(QColor(150, 152, 165), 1.4))
            p.setBrush(QBrush(QColor(216, 219, 228)))
            p.drawRoundedRect(cx - 8, cy + 16, 16, 5, 2, 2)
            # ⑤ 高光
            p.setPen(QPen(QColor(255, 255, 255, 190), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(cx - 15, cy - 2, 12, 12, 120 * 16, 70 * 16)

    # ---------- 托盘/退出时清掉 ----------
    def closeEvent(self, ev):
        # ⭐ 2026-10-03：工具栏没了（= 退出桌宠）时，游戏窗口不该继续飘在那儿
        w = getattr(self, "_night", None)
        if w is not None:
            try:
                w.close()
            except RuntimeError:
                pass
            self._night = None
        ev.accept()
