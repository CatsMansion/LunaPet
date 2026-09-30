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
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
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
]
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
        # 贴屏幕左侧、垂直居中偏下
        scr = pet_window.screen().availableGeometry()
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

    def leaveEvent(self, ev):
        self._hover_slot, self._hover_body = -1, False
        self.update()

    def mousePressEvent(self, ev):
        pos = ev.position().toPoint()
        if not self.open:
            self._toggle()                      # 点柜体 → 拉开抽屉
            return
        i = self._slot_at(pos)
        if i < 0:
            # 点到抽屉外（柜体那一块）→ 收回去
            if pos.y() < H_CLOSED:
                self._toggle()
            return
        key = SLOTS[i][0]
        # ⭐⭐ 2026-09-29 改为「手持式」：点道具 = 继承到鼠标上（光标变成道具），
        #   拿鼠标去点露娜才施法。比"点一下直接生效"多一个指向动作，沉浸感更强，
        #   且所有工具共用同一套流程。再点同个道具 / 按 ESC = 放下。
        self.pet.hold_tool(key)


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
                self._draw_slot(p, self._slot_rect(i), key, i == self._hover_slot)
        p.end()

    def _draw_cabinet(self, p: QPainter, w: int, h: int, hover: bool):
        """柜体：⭐ 有 cabinet 素材优先用，否则程序绘制（占位）"""
        pm = self.icons.get("cabinet") or self.icons.get("抽屉") or self.icons.get("柜子")
        if pm is not None:
            s = min(w - 4, min(h, H_CLOSED) - 4)
            pm2 = pm.scaled(s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((w - pm2.width()) // 2, 2, pm2)
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

    def _draw_slot(self, p: QPainter, r: QRect, key: str, hover: bool):
        """道具槽：底板 + 图标（⭐ 优先用角色包里的真素材，没有才退回程序绘制）"""
        p.setPen(QPen(QColor(120, 90, 66), 1))
        p.setBrush(QBrush(QColor(232, 214, 190) if not hover else QColor(255, 240, 214)))
        p.drawRoundedRect(r, 8, 8)
        cx, cy = r.center().x(), r.center().y()

        # ⛔⛔ 2026-09-29 Ronny 目检：「枕头有点看着不像枕头」
        #   查明：packs/luna/ui/pillow.png 画的其实是**派/馅饼**（棕饼皮 + 奶油馅 +
        #        中央核 + 放射纹），不是枕头。⚠️ pillow 的素材还在派单队列里没重出，
        #        重出之前**必须屏蔽这张错素材**，否则程序绘制的真枕头永远不生效。
        #   ✅ 等新 pillow.png 装机后，把 "pillow" 从本集合里删掉即可。
        _BAD_ASSET = {"pillow"}
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
        elif key == "bowl":
            # 饭碗：敞口碗 + 碗口食团 + 碗足 + 高光
            from PySide6.QtGui import QPainterPath, QLinearGradient
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
        ev.accept()
