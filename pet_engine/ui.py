# -*- coding: utf-8 -*-
"""ui.py —— 桌面宠物引擎 · 渲染层（PySide6）

⭐ 职责边界：只做「窗口 / 绘制 / 鼠标 / 定时器」，
   ⛔ 所有逻辑（状态机 / 物理 / 边界）都在 core.py，这里不判断业务。
   → 将来换 Godot / Electron，只重写本文件。
"""
from __future__ import annotations

import os
import sys
import time
from typing import Dict, Optional, Tuple

import numpy as np
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QImage, QPixmap, QTransform, QPainter, QColor, QAction, QIcon, QCursor, QPen
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import Pet, PetPack, load_pack   # noqa: E402

# ⭐ 按下后移动超过这个距离（px）才算"拖拽"，否则算"点击"
DRAG_THRESHOLD = 6.0
CLICK_MAX_SEC = 0.40


def load_frames(pack: PetPack) -> Dict[str, list]:
    """⭐ 全动作预加载进内存（不再逐帧读盘）"""
    cache: Dict[str, list] = {}
    for name, act in pack.actions.items():
        imgs = []
        for i in range(act.frames):
            p = pack.frame_path(name, i)
            if not os.path.exists(p):
                continue
            im = QImage(p)
            if not im.isNull():
                imgs.append(im)
        if imgs:
            cache[name] = imgs
    return cache


def silhouette_of(imgs: list, anchor: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """⭐ 由给定帧的 alpha 并集算出【角色实际轮廓】
    返回相对"贴地参考点"的 (左, 右, 上, 下) 偏移 —— 用于按真实轮廓限位。

    ⛔ DyberPet 的坑：它按【窗口半宽】限位 → 半个 sprite 能出屏。
    ✅ 我们按【轮廓】限位。

    ⭐⭐ 2026-09-27：改成【逐动作】调用。
       横画幅的趴姿宽度远大于站姿，如果沿用"全动作并集"算一个轮廓，
       趴姿会把限位框撑到整屏宽 → 站姿也能走到屏幕外。
       → 正确的做法：每个动作有自己的轮廓，切动作时换用对应轮廓。
    """
    if not imgs:
        ax, ay = anchor
        return (-ax, ax, -ay, 0)
    ax, ay = anchor
    left = top = 10 ** 9
    right = bottom = -10 ** 9
    for im in imgs:
        # ⭐ 为什么先转 Alpha8 再交给 numpy：
        #   ① 磁盘上的帧是 ARGB32（小端机上内存布局是 BGRA），直接按 RGBA8888 的
        #      第 4 通道取 alpha 会读错 —— Alpha8 只保留 1 字节 alpha，与像素一一对应，
        #      既避开通道/字节序分支，又省 3/4 内存。
        #   ② stride 是"每行字节数"，按 4 字节对齐，可能大于 w，所以必须先用
        #      reshape(h, stride) 还原行结构再切到 w 列，否则行尾填充字节会被当成像素。
        #   ③ 逐点 pixel() 是 512×512×帧数 次跨语言调用；向量化后一次算完。
        a8 = im.convertToFormat(QImage.Format_Alpha8)
        w, h = a8.width(), a8.height()
        stride = a8.bytesPerLine()
        buf = np.frombuffer(a8.constBits(), dtype=np.uint8, count=stride * h)
        alpha = buf.reshape(h, stride)[:, :w]
        ys, xs = np.nonzero(alpha > 16)      # 阈值 16 沿用原实现：极淡的描边不算轮廓
        if xs.size == 0:
            continue
        # ⭐ 语义不变：(left, right, top, bottom) 仍是相对 anchor 的四向极值
        left = min(left, int(xs.min()) - ax)
        right = max(right, int(xs.max()) - ax)
        top = min(top, int(ys.min()) - ay)
        bottom = max(bottom, int(ys.max()) - ay)
    if left > right:
        return (-ax, ax, -ay, 0)
    return (int(left), int(right), int(top), int(bottom))


def frame_stance(im, anchor: Tuple[int, int]) -> Tuple[float, float]:
    """⭐ 单帧的"站位偏移"：(中轴 − anchor.x, 最低点 − anchor.y)，画布像素，未乘 user_scale

    ⭐⭐ 2026-09-30 新增，用于切动作时的几何补偿。
    ⛔ 为什么不用 `silhouette_of`（整动作并集）：并集给的是"所有帧的极值"，
       而切换发生在**具体某一帧**上 —— 实测 sleep_out 末帧（站姿）与并集最低点
       差 15px，用并集补偿等于没补。
    """
    a8 = im.convertToFormat(QImage.Format_Alpha8)
    w, h = a8.width(), a8.height()
    stride = a8.bytesPerLine()
    buf = np.frombuffer(a8.constBits(), dtype=np.uint8, count=stride * h)
    alpha = buf.reshape(h, stride)[:, :w]
    ys, xs = np.nonzero(alpha > 16)
    if xs.size == 0:
        return 0.0, 0.0
    return (float(xs.min() + xs.max()) / 2.0 - anchor[0],
            float(ys.max()) - anchor[1])


class PetWindow(QWidget):
    def __init__(self, pack: PetPack):
        super().__init__()
        cw, ch = pack.canvas
        self.pack = pack
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(cw, ch)

        self.frames = load_frames(pack)
        if not self.frames:
            raise SystemExit(f"⛔ 没加载到任何帧：{pack.root}/action/")

        # ⭐⭐ 2026-09-27：逐动作轮廓（支持横画幅）
        #   横躺的趴姿宽度远大于站姿 —— 用"全动作并集"算一个轮廓的话，
        #   趴姿会把限位框撑到整屏宽，站姿就能走到屏幕外。
        #   → 每个动作各算自己的轮廓，切动作时换用对应轮廓。
        self.sils: Dict[str, Tuple[int, int, int, int]] = {}
        for name, imgs in self.frames.items():
            self.sils[name] = silhouette_of(imgs, pack.anchor_of(name))
        # ⭐⭐ 2026-09-30：逐帧"站位偏移"，供切动作的几何补偿用（见 _compensate_switch）
        self.frame_stance: Dict[str, list] = {}
        for name, imgs in self.frames.items():
            an = pack.anchor_of(name)
            self.frame_stance[name] = [frame_stance(im, an) for im in imgs]
        self._last_act: Optional[str] = None      # 上一帧画的动作（补偿要拿它的当前帧）
        self._last_idx: int = 0
        # 默认轮廓（当前动作没算出来时的兜底）＝ 所有动作的并集
        all_imgs = [im for v in self.frames.values() for im in v]
        self.sil = silhouette_of(all_imgs, pack.anchor)
        print(f"[轮廓·默认] 左{self.sil[0]} 右{self.sil[1]} 上{self.sil[2]} 下{self.sil[3]}")
        for k in sorted(self.sils):
            s = self.sils[k]
            c = pack.canvas_of(k)
            print(f"[轮廓·{k}] {c[0]}x{c[1]}  左{s[0]} 右{s[1]} 上{s[2]} 下{s[3]}")
        print(f"[帧] {', '.join(f'{k}:{len(v)}' for k, v in self.frames.items())}")

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = (scr.left(), scr.top(), scr.right(), scr.bottom())
        self.pet = Pet(pack, self.screen_rect)
        self.pet.body.x = scr.center().x()
        self.pet.body.y = scr.bottom()

        self._drag_off = QPoint(0, 0)
        self._dragging = False          # 左键正按着（不代表已经在拖）
        self._drag_started = False      # ⭐ 真的移动超阈值、已经进入拖拽
        # ⭐⭐ 2026-09-29 变小魔法棒：运行时缩放（1.0 = 原始）
        #   ⛔ 此前 pet.json 的 scale 从未接进渲染（只存在于配置里）
        # ⭐ Apple 2026-09-29 Ronny：默认大小 = 「从最小档往上放大 3 次」
        #   0.45 × (1/0.85)³ ≈ 0.733 —— 开箱就是小猫尺寸，往上 3 次回原始感，往下 3 次到最小
        # ⭐⭐ 2026-09-30：显示倍率改为从**角色包**读（pet.json `display_scale`），默认 1.0。
        #   ⛔ 旧写法硬编码 `0.45 * (1.0/0.85)**3 = 0.7328` ——
        #      那是「变小魔法棒」的**运行时状态**被写死进了代码：
        #        ① 从此所有 `anchor × s` 的算式都带非整数倍，成为"拖拽偏 136px"的温床
        #        ② 想调整体大小必须改代码，而它本质上是一条**角色设定**
        #      （这只猫在桌面上该多大）。
        #   ✅ 现在：pet.json 写 display_scale，代码里 user_scale 只是"当前倍率"，
        #      魔法棒仍可在它基础上左键变小 / 右键变大（0.45~1.60 夹取）。
        self.user_scale = float(getattr(pack, "display_scale", None) or 1.0)
        self._scale_anim = []          # 缓动队列：[(目标倍率)]
        self._fx_t = 0.0               # 魔法光效剩余时间（秒）
        self._fx_kind = 'shrink'
        self.magic_fx_t0 = 1.0
        # ⭐⭐ 2026-09-29 Ronny：手持式交互 —— 点工具「继承到鼠标上」，再拿鼠标点角色施法。
        #   从"点一下按钮"变成"手持道具去用"，多一个"指向"动作，因果关系清楚；
        #   ⭐ 所有工具共用这套流程（选中 → 指向 → 施用），后续加梳子/逗猫棒不用重新设计。
        self._held_tool = None          # None | "wand" | "pillow"
        self._cur_action: Optional[str] = None   # ⭐ 当前已应用的窗口尺寸/锚点对应的动作

        self._apply_pos()
        self._sync_action_geometry(force=True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._last_ms = 0
        self.timer.start(16)          # ~60fps 的推进（动画本身按 fps 走）
        self._make_tray()

    # ---------- 逐动作几何（⭐ 横画幅支持）----------
    def _sync_action_geometry(self, force: bool = False) -> bool:
        """⭐ 当前动作变了 → 同步窗口尺寸 + 锚点。返回是否发生了尺寸变更

        ⚠️ 为什么必须逐动作：不同动作的画布可以不一样（趴姿 1536×1024，其余 512×512）。
           `_apply_pos` 与 `paintEvent` 都按 anchor 定位，所以尺寸一换锚点也必须跟着换。

        ⛔⛔ 2026-09-27 实测踩坑：**切动作那一帧会有可见位移**
           原因：`setFixedSize` 是**异步生效**的（Qt 要重排窗口），但 `move()` 是立即的。
           原顺序 step → sync → apply_pos 会在切换帧出现「旧尺寸窗口 + 新 anchor 位置」的错位。
           ✅ 修法：resize 后**强制同步布局**（让尺寸立即生效）再定位，
              并且把「尺寸变更」这件事返回给 _tick，让它在这帧直接 return（跳过绘制），
              等下一帧尺寸稳定了再画 —— 宁可少画一帧，也不能画一帧错的。
        """
        act = self.pet.anim.act.name if self.pet.anim else None
        if act is None or (act == self._cur_action and not force):
            return False
        cw, ch = self.pack.canvas_of(act)
        # ⭐ 2026-09-29：窗口尺寸 = 画布 × 用户倍率（变小魔法棒）
        cw, ch = int(cw * self.user_scale), int(ch * self.user_scale)
        changed = False
        if self.width() != cw or self.height() != ch:
            self.setFixedSize(cw, ch)
            # ⭐ 强制让新尺寸立即生效（否则本帧仍是旧尺寸）
            self.layout() and self.layout().activate()
            changed = True
        self._cur_action = act
        return changed

    # ---------- 位置 ----------
    def _cur_anchor(self) -> Tuple[int, int]:
        """⭐ 当前动作的贴地参考点（趴姿与站姿可以不同）"""
        act = self.pet.anim.act.name if self.pet.anim else None
        return self.pack.anchor_of(act) if act else self.pack.anchor

    def _cur_sil(self) -> Tuple[int, int, int, int]:
        """⭐ 当前动作的轮廓（横画幅趴姿宽度大，必须用自己的）

        ⭐⭐ 2026-09-30 修：轮廓也要乘 user_scale。
           轮廓是**屏幕像素**口径（core 拿它做 clamp_to_screen 限位），
           若显示只有 73% 而轮廓仍是 100%，限位框就比实际大 36% →
           她能半个身子走出屏幕。同 `_apply_pos` / `paintEvent` 统一口径。
        """
        act = self.pet.anim.act.name if self.pet.anim else None
        sil = self.sils[act] if (act and act in self.sils) else self.sil
        s = self.user_scale
        if abs(s - 1.0) < 1e-3:
            return sil
        return (int(sil[0] * s), int(sil[1] * s), int(sil[2] * s), int(sil[3] * s))

    def _compensate_switch(self):
        """⭐⭐ 切动作时让【角色在屏幕上的位置】不跳（2026-09-30）

        ⭐ 屏幕坐标推导（W = 窗口左上，a = 本动作 anchor，s = user_scale）：
              W = body − a × s                            （`_apply_pos`）
              图像左上在窗口内 = (a.x×s − pw/2, a.y×s − ph)（`paintEvent`）
          ⇒ 图像内像素 (px, py) 的屏幕坐标
              = W + 图像左上 + (px×s, py×s)
              = (body.x + (px − a.x)×s,  body.y + (py − a.y)×s)
          ⭐⭐ 结论：**与 anchor 无关**！只取决于 body、user_scale、
             以及该像素在图像内的位置。

        ⛔ 所以 core 里原来的 `body += (a_new − a_old)` 是错的口径 —— anchor 差
           不等于"角色实际站位差"，而且跨画布时两个 anchor 根本不在一个坐标系里。

        ✅ 正确做法：让切换前后，角色的【中轴】与【最低点】屏幕坐标不变：
              body.x + cx_old×s = body'.x + cx_new×s   →  body.x += (cx_old − cx_new)×s
              body.y + bot_old×s = body'.y + bot_new×s →  body.y += (bot_old − bot_new)×s
           其中 (cx, bot) = 该帧的 (中轴 − anchor.x, 最低点 − anchor.y)，见 `frame_stance`。

        ⭐ 实测（未补偿时的屏幕跳变）：
              sleep_out 末帧 → idle 首帧    水平 +74.4px / 垂直 −9.5px
              sleep_out 末帧 → stretch 首帧  水平 +86.8px / 垂直 −9.5px
              idle 末帧 → sleep_in 首帧      水平 −55.0px
        """
        p = self.pet
        if not p.anim:
            return
        cur = p.anim.act.name
        idx = p.anim.seq[p.anim.i]
        prev, pi = self._last_act, self._last_idx
        self._last_act, self._last_idx = cur, idx
        if prev is None or prev == cur:
            return
        ob, nb = self.frame_stance.get(prev), self.frame_stance.get(cur)
        if not ob or not nb or pi >= len(ob) or idx >= len(nb):
            return
        s = self.user_scale
        ox, oy = ob[pi]
        nx, ny = nb[idx]
        p.body.x += (ox - nx) * s
        p.body.y += (oy - ny) * s

    def _apply_pos(self):
        """把「贴地参考点」换算成窗口左上角"""
        ax, ay = self._cur_anchor()
        s = self.user_scale
        self.move(int(self.pet.body.x - ax * s), int(self.pet.body.y - ay * s))

    def apply_scale(self, factor: float) -> bool:
        """⭐ 2026-09-29 变小魔法棒：改显示倍率。左键 factor=0.85（小一档）、右键 factor=0.85**-1（大一档）。

        ⭐ 设计取舍：**不做尺寸平滑过渡，直接跳档 + 0.45s 魔法光效**。
          理由：窗口尺寸每帧变会撞上 `_sync_action_geometry` 的"尺寸变更就跳过本帧"保护，
          反而会掉帧；而变身本来就是瞬间的事 —— 用光效掩盖突变，比缓动更像魔法。
        """
        lo, hi = 0.45, 1.60
        new = max(lo, min(hi, self.user_scale * factor))
        if abs(new - self.user_scale) < 1e-3:
            self._fx_t = 0.45                      # 已到边界也闪一下，给个"使不上劲"的反馈
            self._fx_kind = "limit"
            self.update()
            return False
        self.user_scale = new
        self._fx_t, self._fx_kind = 0.45, ("shrink" if factor < 1 else "grow")
        self.magic_fx_t0 = 1.0
        self._sync_action_geometry(force=True)
        self._apply_pos()
        self.update()
        return True

    def hold_tool(self, name: str):
        """拿起 / 放下工具（"继承到鼠标上"）。name=None 表示放下。"""
        if name == self._held_tool:
            name = None                                  # 再点一次 = 放下（toggle）
        # ⭐ 放下任何道具时，先停掉"激光笔追踪"（否则放下激光笔她还在追鼠标）
        was_laser = (self._held_tool == "laser")
        if name != "laser":
            self._laser_on = False
            try:
                self.pet.goal = None
            except Exception:
                pass
            # ⭐ 还原应用级光标（激光笔用的是 override cursor，必须显式还原）
            if was_laser:
                try:
                    QApplication.restoreOverrideCursor()
                except Exception:
                    pass
        self._held_tool = name
        if name is None:
            self.unsetCursor()
            print("[手持] 已放下工具")
            return
        if name == "laser":
            self._laser_on = True
            print("[激光笔] 红点已就位 —— 她会追过来跳起来抓；再点一次或按 ESC 放下")
        else:
            print(f"[手持] 拿起 {name} —— 点露娜施用；再点同个道具或按 ESC 放下")
        # ⭐⭐ 2026-09-29 激光笔必须用【应用级光标】：红点要全屏跟着鼠标走。
        #   ⛔ 若只用 self.setCursor()，鼠标一离开角色窗口就恢复系统箭头 → 红点消失。
        #   ✅ QApplication.setOverrideCursor 是全局的，整个桌面都显示红点。
        if name == "laser":
            try:
                QApplication.setOverrideCursor(self._make_tool_cursor(name))
            except Exception:
                self.setCursor(self._make_tool_cursor(name))
        else:
            self.setCursor(self._make_tool_cursor(name))

    def _make_tool_cursor(self, name: str):
        """把工具画成鼠标光标（P0 占位图形；正式素材到位后换成 QPixmap(图片)）。"""
        from PySide6.QtGui import QPixmap, QPainter as _P, QPen as _Pen, QBrush as _B, QCursor as _C
        pm = QPixmap(44, 44)
        pm.fill(Qt.transparent)
        g = _P(pm)
        g.setRenderHint(_P.Antialiasing)
        if name == "wand":
            g.setPen(_Pen(QColor(122, 82, 150), 6, Qt.SolidLine, Qt.RoundCap))
            g.drawLine(8, 38, 28, 12)
            g.setPen(Qt.NoPen); g.setBrush(_B(QColor(255, 228, 120)))
            g.drawEllipse(24, 4, 16, 16)
            g.setBrush(_B(QColor(255, 255, 240)))
            g.drawEllipse(28, 8, 8, 8)
        elif name == "laser":
            # ⭐⭐ 2026-09-29 激光笔：鼠标变成"小红点"（Ronny 构思）
            #   热区必须在【正中心】——她追的是红点本身，不能让光标带偏移，
            #   否则她会追到一个"红点看起来不在那儿"的位置。
            g.setPen(Qt.NoPen)
            g.setBrush(_B(QColor(255, 60, 60, 60)))         # 外光晕
            g.drawEllipse(6, 6, 32, 32)
            g.setBrush(_B(QColor(255, 45, 45, 130)))
            g.drawEllipse(11, 11, 22, 22)
            g.setBrush(_B(QColor(255, 30, 30)))             # 实心点
            g.drawEllipse(15, 15, 14, 14)
            g.setBrush(_B(QColor(255, 200, 200)))           # 高光
            g.drawEllipse(18, 18, 5, 5)
            g.end()
            return _C(pm, 22, 22)                            # ⭐ 正中心
        elif name == "teaser":
            # 逗猫棒光标：斜杆 + 羽毛
            g.setPen(_Pen(QColor(150, 110, 70), 5, Qt.SolidLine, Qt.RoundCap))
            g.drawLine(8, 40, 30, 12)
            g.setPen(Qt.NoPen); g.setBrush(_B(QColor(240, 200, 120)))
            g.drawEllipse(26, 2, 14, 14)
            g.setBrush(_B(QColor(200, 160, 90)))
            g.drawEllipse(24, 10, 10, 10)
            g.end()
            return _C(pm, 8, 40)
        else:
            g.setPen(_Pen(QColor(180, 180, 190), 2))
            g.setBrush(_B(QColor(246, 246, 250)))
            g.drawRoundedRect(4, 20, 36, 20, 8, 8)
        g.end()
        return _C(pm, 8, 38) if name == "wand" else _C(pm)

    def act_with_tool(self, right: bool) -> bool:
        """在角色身上施用当前手持的工具。返回是否消费了这次点击。"""
        if self._held_tool == "wand":
            self.apply_scale((1.0 / 0.85) if right else 0.85)
            return True
        if self._held_tool == "pillow":
            self._sleep_via_tool()
            self._held_tool = None
            self.unsetCursor()
            return True
        if self._held_tool == "laser":
            # ⭐⭐ 2026-09-29 激光笔（Ronny 构思）：
            #   「装备该道具后鼠标变为小红点，露娜会追到小红点下面然后跳起来抓小红点」
            #   ⛔ 这不是"点一下触发一次"，而是**持续追踪**：
            #     装备期间鼠标 = 红点，她一直朝红点走；走到附近 → 起跳抓（播 tease）。
            #   所以这里【不消费点击】——由 _laser_tick() 每帧驱动，点击只当"逗她一下"。
            self._laser_on = True
            self.pet.goal = "seek"
            self.pet._cursor_x = float(QCursor.pos().x())
            return False          # ⭐ 不吃掉点击 → 她还会照常被摸摸
        if self._held_tool == "teaser":
            # 逗猫棒：点一下 = 逗她一次（播 tease 动作）
            pet = self.pet
            if self._has_frames("tease") and not getattr(pet, "asleep", False):
                pet.play("tease")
                pet.state_timer = 2.5
            return True
        if self._held_tool == "bowl":
            # ⭐⭐ 2026-09-29 喂食（Ronny：「端起人类饭碗一口闷，吃完碗应该是空的」）
            #   ⛔ 旧的蹲着吃猫粮 = 非人类行为，整段重做。
            #   ✅ 新设计：她端起碗往嘴里倒 → 播 eat 动作 → 碗里的食物由
            #      `pet.json` 的 overlay（食物图层）按帧渐隐，吃完碗自然空。
            pet = self.pet
            if self._has_frames("eat") and not getattr(pet, "asleep", False):
                pet.play("eat")
                pet.state_timer = 3.0
                return True
            # ⛔ eat 素材还没出（在途派单）→ 告诉用户，不静默失败
            print("[饭碗] ⏳ eat 动作素材还没装机，先在等派单回传")
            return True
        return False

    def _has_frames(self, name: str) -> bool:
        """⭐ 动作【真的能播吗】：既要在 pet.json 里注册，也要真的有帧落在盘上。

        ⛔ 只查 `name in pack.actions` 不够 —— 占位注册（如 eat）会在 actions 里、
           但 action/ 目录还没素材。此时 play() 会把 anim 设成空帧列表，
           **anim.finished 永不触发 → 角色永久卡在该状态**（实测呆滞）。
        """
        try:
            return name in self.pet.pack.actions and bool(self.frames.get(name))
        except Exception:
            return False

    def _laser_tick(self, dt: float):
        """激光笔的每帧驱动：红点在哪，她就往哪追；追到了就跳起来抓。

        ⭐ 规则（Ronny 构思的落地）：
          ① 装备期间：红点 = 鼠标位置，她持续 `goal="seek"` 朝红点走
          ② 距离够近（进入抓取半径）→ 播 tease（跳起来抓）
          ③ 抓完歇一下（冷却）再继续追，⛔ 不能疯狂连扑
          ④ 放下激光笔 → 立刻停追、回常态
        """
        if not getattr(self, "_laser_on", False):
            return
        pet = self.pet
        # ⭐ 冷却【无条件】每帧递减（⛔ 原来只在"没追到"分支递减 →
        #    追到后立刻再满足 near 条件 → 12 秒连扑 96 次）
        if getattr(pet, "_laser_cool", 0.0) > 0:
            pet._laser_cool = max(0.0, pet._laser_cool - dt)
        if getattr(pet, "asleep", False) or pet.dragging:
            return
        try:
            cx = float(QCursor.pos().x())
        except Exception:
            return
        pet.set_cursor(cx)
        state = getattr(pet, "state", "")
        # ② 追到了 → 跳起来抓（但要过冷却）
        near = abs(cx - pet.body.x) <= float(getattr(self, "_laser_grab_r", 120.0))
        if near and getattr(pet, "_laser_cool", 0.0) <= 0.0 \
                and state in ("idle", "walk") and self._has_frames("tease"):
            pet.play("tease")
            pet.state_timer = 2.5
            pet._laser_cool = 2.8          # ⭐ 抓一次歇 2.8 秒（tease 约 2.4 秒 + 缓一下）
            return
        # ③ 还没追到 → 持续 seek
        if getattr(pet, "_laser_cool", 0.0) > 0:
            return
        # ⭐⭐ 2026-09-29 修：**每帧重新断言 seek**（⛔ 不能只在 goal is None 时才设）
        #   根因：她走路时 walk_duration 到点 → core._idle_pick() → _pick_goal()
        #        会把我们的 seek 目标**顶掉**成随机漫游点（实测 goal_x 2200 → 83），
        #        于是她掉头往反方向走，永远追不到红点。
        #   ✅ 激光笔在手期间，红点就是唯一目标，谁都不能覆盖。
        if state in ("idle", "walk"):
            pet.goal = "seek"
            pet.goal_x = cx

    def _sleep_via_tool(self):
        """⭐ 枕头工具：一键让她睡（sleep_in → sleep_loop）

        ⛔⛔ 2026-09-30 修（Ronny：「睡觉还是一键 sleep out 不是 sleep in」）：
           旧写法在这里自己设 `asleep=True` 再 `play("sleep_in")`，
           **跳过了 core.fall_asleep() 里的"预热光标位置"这一步** ——
           而"点枕头"这个动作必然让鼠标正压在她身上（距离 0px），
           于是入睡第一帧 `_wake_from_cursor` 就把"光标一直在附近"误判成
           "刚从外面进来" → 立刻 `wake()` → 播 **sleep_out**（她刚躺下又站起来）。
        ✅ 改为复用 `core.fall_asleep()`，预热 / 清 goal / 记时全部走同一条路。
        """
        try:
            self.pet.fall_asleep()
        except Exception:
            pass

    def _feed_cursor(self):
        """把全局光标位置喂给 core（用于"靠近就吵醒她"和"朝光标走过来"）"""
        if not hasattr(self.pet, "set_cursor"):
            return
        gp = QCursor.pos()
        self.pet.set_cursor(float(gp.x()))

    # ---------- 主循环 ----------
    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last_ms) if self._last_ms else 0.016
        self._last_ms = now
        # ⭐ 2026-09-29 魔法光效倒计时（变小魔法棒）
        if self._fx_t > 0:
            self._fx_t = max(0.0, self._fx_t - dt)
        # ⭐⭐ 全局光标轮询（2026-09-28 修）
        #   ⛔ 旧做法只在 mouseMoveEvent 里喂光标 —— 而那个事件【只有鼠标进入本窗口】才触发。
        #      结果：光标在她旁边 120px 内但没压到窗口上 → core 收不到坐标 → 永远吵不醒她。
        #   ✅ 直接问 Qt 要全局光标位置，鼠标在桌面任何地方她都知道。
        self._feed_cursor()
        # ⭐⭐ 2026-09-29 激光笔驱动（她追红点 / 追到就跳起来抓）
        self._laser_tick(dt)
        # ⭐ 先按【上一帧动作】的轮廓推进物理
        self.pet.step(dt, self._cur_sil())
        # ⭐⭐ 切动作 → 先按【真实画面位置】补偿，让角色在屏幕上不跳
        self._compensate_switch()
        # ⭐ 动作可能刚切换 → 换尺寸。
        #    ⛔⛔ 尺寸真的变了就【本帧不主动重绘】：此刻窗口尺寸与 anchor 还没对齐，
        #       画出来就是 Ronny 看到的那"一帧明显位移"。
        #    ✅ 跳过这一帧绘制（约 16ms，肉眼不可辨），下一帧尺寸已稳定，正常画。
        #
        # ⭐⭐ 2026-09-30 再修（Ronny：「sleepout 和 idle 之间不飞了，改为伸懒腰的时候飞」）：
        #   ⛔ 旧写法在尺寸变更时**直接 return，跳过了 `_apply_pos()`** ——
        #      而 `setFixedSize()` 不只是"我们下次不再 update"那么简单，
        #      它会让 Qt **立刻**重排并重绘一次。那一帧窗口还停在**旧位置**，
        #      于是"新尺寸 + 旧位置"被画了出来 = 肉眼可见的一次错位/闪飞。
        #   ✅ 顺序改成：先 resize，**再无条件 `_apply_pos()` 把窗口挪到新 anchor 位置**，
        #      最后才决定要不要主动重绘。这样即便 Qt 抢先重绘，位置也是对的。
        changed = self._sync_action_geometry()
        self._apply_pos()
        if changed:
            return
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        p = self.pet
        if not p.anim:
            return
        name = p.anim.act.name
        idx = p.anim.seq[p.anim.i]
        imgs = self.frames.get(name)
        if not imgs:
            return
        im = imgs[min(idx, len(imgs) - 1)]
        pm = QPixmap.fromImage(im)
        # ⭐ 2026-09-29 变小魔法棒：先按倍率缩放（镜像/倾斜在之后做，与尺寸无关）
        if abs(self.user_scale - 1.0) > 1e-3:
            pm = pm.scaled(max(1, int(pm.width() * self.user_scale)),
                           max(1, int(pm.height() * self.user_scale)),
                           Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        # ⭐ 镜像（左右走 + 转身三段，2026-09-28）
        #   实测依据（_看_转身头.png）：walk / turn_in尾帧 / turn_out首帧 素材原生都朝右 →
        #   三者共用 facing_right 镜像规则：朝右=原生，朝左=镜像。
        #   ⛔ turn 不镜像的话：朝左走会先播出"朝右转身"再接"朝左走路"，接缝硬切。
        # ⭐⭐ 2026-09-29 修（Ronny：从 turn 回 default 还是会闪和位移）：
        #   ⛔ 旧写法只有 walk/turn_in/turn_out 参与镜像，idle 不参与 ——
        #      实测 turn_out 末帧自身镜像差 **54.21%**（呆毛/尾巴偏向一侧，正面并不对称）。
        #      朝左走完 → turn_out 被镜像（末帧呆毛偏左）→ 切 idle 时【恢复不镜像】
        #      → 呆毛"啪"地跳到右侧 = Ronny 看到的"闪"，视觉重心跟着挪 = "位移"。
        #   ✅ 改法：**所有动作共用 facing_right 镜像**（她朝左站着就该镜像显示），
        #      这样 turn_out 末帧与 idle 首帧处在同一镜面里，接缝连续。
        #      语义上也更对：转向之后呆毛/尾巴本来就该跟着转到另一侧。
        if not p.facing_right:
            pm = pm.transformed(QTransform().scale(-1, 1))
        # ⭐ 拖拽倾斜（今天 issue #103 的诉求）
        if abs(p.body.tilt) > 0.1:
            pm = pm.transformed(QTransform().rotate(p.body.tilt), Qt.SmoothTransformation)
        painter = QPainter(self)
        ax, ay = self.pack.anchor_of(name)      # ⭐ 逐动作锚点（横画幅趴姿与站姿不同）
        s = self.user_scale
        painter.drawPixmap(int(ax * s) - pm.width() // 2, int(ay * s) - pm.height(), pm)
        # ⭐⭐ 2026-09-29 新增：道具叠加层（方案 B）
        #   用途（Ronny：「吃饭动作改为把人类用的饭碗拿起来一口闷了…饭吃完了饭碗应该是空的」）：
        #   角色帧里的碗**始终是空的**，碗里的食物由这里叠加，并可按帧隐藏 →
        #   "吃完碗空"变成【确定性的代码控制】，不指望 AI 把食物画消失。
        #   配置写在 pet.json 的 action.overlays（见 pack 层），每项：
        #       {image, anchor:[x,y], scale, show:[起帧,止帧], fade:[渐隐起,渐隐止]}
        self._draw_overlays(painter, name, idx, ax, ay, s)
        # ⭐ 2026-09-29：爱心优先用真素材（packs/<角色>/ui/heart_*.png）
        heart_pm = getattr(self, "_heart_pm", "?")
        if heart_pm == "?":
            import os
            # ⛔⛔ 2026-09-29 修复：此处原本写 `from PySide6.QtGui import QPixmap`。
            #   函数内 import 会把 `QPixmap` 变成 **本函数局部名** → 上面第 320 行
            #   `QPixmap.fromImage(im)` 在赋值前被引用 → UnboundLocalError 刷屏（Ronny 截图）。
            #   ✅ 全局(第17行)已 import，这里改用别名，不再遮蔽。
            heart_pm = None
            try:
                hp = os.path.join(self.pack.root, "ui", "heart_red.png")
                if os.path.exists(hp):
                    pm0 = QPixmap(hp)
                    if not pm0.isNull():
                        heart_pm = pm0
            except Exception:
                heart_pm = None
            self._heart_pm = heart_pm
        if heart_pm is not None and getattr(self.pet, "_hearts", []):
            for i, hh in enumerate(self.pet._hearts):
                tt = hh[0]
                if tt >= 1.1:
                    continue
                fade = max(0.0, 1.0 - tt / 1.1)
                sz = int(34 * s)
                pmh = heart_pm.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                hx = ax * s + (i - len(self.pet._hearts) / 2.0) * 30.0 * s + 70.0 * s
                hy = ay * s - 455.0 * s + tt * 25.0 * s
                painter.setOpacity(fade)
                painter.drawPixmap(int(hx - pmh.width() / 2), int(hy), pmh)
                painter.setOpacity(1.0)
        # ⭐ v0.2：被摸时冒爱心（无素材时的程序绘制兜底）
        for i, h in enumerate(getattr(self.pet, "_hearts", [])):
            t = h[0]
            if t >= 1.1:
                continue
            a = int(255 * max(0.0, 1.0 - t / 1.1))
            # ⭐ 用【归一化身高 488】定位头部，不用 pm.height()（那是整张画布，且倾斜时会变）
            # ⭐ 几何事实：角色头顶在 y≈9（轮廓上边界 -503），画布顶是 0 →
            #   "飘到头顶上方"会被裁掉，所以【往上飘改成往下沉一点 + 侧向排开】，
            #   并加白色描边，保证压在深色头发上也看得清。
            hx = ax * s + (i - len(self.pet._hearts) / 2.0) * 30.0 * s + 70.0 * s
            hy = ay * s - 455.0 * s + t * 25.0 * s
            r = 17.0 * s
            painter.setPen(QColor(255, 255, 255, a))
            painter.setBrush(QColor(232, 80, 120, a))
            painter.drawEllipse(int(hx - r * 0.75), int(hy), int(r), int(r))
            painter.drawEllipse(int(hx - r * 0.15), int(hy), int(r), int(r))
            painter.drawPolygon([QPoint(int(hx - r * 0.95), int(hy + r * 0.55)),
                                 QPoint(int(hx + r * 0.95), int(hy + r * 0.55)),
                                 QPoint(int(hx), int(hy + r * 1.9))])
        # ⭐ 2026-09-29 变小魔法棒的光效（纯绘制，无素材）
        #   构成：① 圆环扩散（脚下起，向上放大淡出）② 8 颗星绕角色旋转淡出
        if self._fx_t > 0:
            k = 1.0 - self._fx_t / 0.45                      # 0→1
            fade = max(0.0, 1.0 - k) ** 0.8
            a_ring = int(210 * fade)
            cx, cy = int(ax * s), int(ay * s) - int(pm.height() * 0.45)
            # 圆环：从角色中部向外扩散
            for j, (rk, aw) in enumerate(((0.30, 1.0), (0.42, 0.55))):
                r = int((pm.width() * 0.22 + pm.width() * 0.55 * k) * rk / 0.30)
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(170, 220, 255, int(a_ring * aw)), max(2, int(5 * fade))))
                painter.drawEllipse(cx - r, cy - r, r * 2, r * 2)
            # 星星：绕一圈旋转
            import math as _m
            col = QColor(255, 245, 170, a_ring) if self._fx_kind != "limit" else QColor(255, 170, 170, a_ring)
            painter.setPen(Qt.NoPen); painter.setBrush(col)
            for j in range(8):
                ang = _m.radians(j * 45 + k * 150)
                rr = pm.width() * (0.30 + 0.50 * k)
                px_, py_ = cx + rr * _m.cos(ang), cy + rr * _m.sin(ang) * 0.75
                sz = max(2, int(9 * fade))
                painter.drawEllipse(int(px_ - sz / 2), int(py_ - sz / 2), sz, sz)
        painter.end()

    # ---------- ⭐⭐ 叠加道具层（方案 B）----------
    def _draw_overlays(self, painter, name: str, idx: int, ax: float, ay: float, s: float):
        """在角色帧之上叠加道具图（按帧控制显隐）。

        ⭐ 用途（Ronny：「端起饭碗一口闷，吃完碗应该是空的」）：
          角色视频里碗画成空的，碗里的食物由这里叠 → "吃完碗空"是确定性代码控制。

        配置来源：pet.json 的 `actions.<name>.overlays`，每项：
            image    : ui/ 下的文件名
            anchor   : [dx, dy]  相对本动作 anchor 的偏移（画布 px，y 向下为正）
            scale    : 额外缩放（1.0 = 原像素）
            show     : [起帧, 止帧]  只在这段帧号内显示（含端点，缺省=全程）
            fade_out : [起帧, 止帧]  在这段内由全显渐隐到 0
        ⛔ 任何异常都静默跳过（叠加层是增强，不该让整个渲染崩）。
        """
        try:
            act = self.pet.pack.actions.get(name)
            if act is None or not getattr(act, "overlays", None):
                return
            for ov in act.overlays:
                fn = ov.get("image")
                if not fn:
                    continue
                pmov = self._overlay_pm(fn)
                if pmov is None:
                    continue
                # ① 帧窗过滤
                show = ov.get("show")
                if show and len(show) == 2:
                    if idx < int(show[0]) or idx > int(show[1]):
                        continue
                # ② 透明度（fade_out 优先）
                op = 1.0
                fo = ov.get("fade_out")
                if fo and len(fo) == 2:
                    f0, f1 = int(fo[0]), int(fo[1])
                    if idx >= f1:
                        continue                      # 渐隐结束 = 不画（碗空了）
                    if idx > f0:
                        op = max(0.0, 1.0 - (idx - f0) / float(max(1, f1 - f0)))
                if op <= 0.0:
                    continue
                # ③ 位置：相对 anchor 的偏移，再乘显示倍率
                dx, dy = (ov.get("anchor") or [0, 0])[:2]
                sc = float(ov.get("scale", 1.0))
                w = max(1, int(pmov.width() * sc * s))
                h = max(1, int(pmov.height() * sc * s))
                pms = pmov.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                px = int((ax + float(dx)) * s - pms.width() / 2)
                py = int((ay + float(dy)) * s - pms.height() / 2)
                # ④ 道具也跟随镜像（朝左时叠在另一侧）
                if not self.pet.facing_right:
                    pm2 = pms.transformed(QTransform().scale(-1, 1))
                    cw = self.pack.canvas_of(name)[0]
                    px = int((cw - (ax + float(dx))) * s - pm2.width() / 2)
                    painter.setOpacity(op)
                    painter.drawPixmap(px, py, pm2)
                else:
                    painter.setOpacity(op)
                    painter.drawPixmap(px, py, pms)
                painter.setOpacity(1.0)
        except Exception:
            return

    def _overlay_pm(self, filename: str):
        """叠加层用的 QPixmap（带缓存）。找不到返回 None。"""
        cache = getattr(self, "_overlay_cache", None)
        if cache is None:
            cache = {}
            self._overlay_cache = cache
        if filename in cache:
            return cache[filename]
        pm = None
        try:
            import os
            p = os.path.join(self.pack.root, "ui", filename)
            if os.path.exists(p):
                pm0 = QPixmap(p)
                if not pm0.isNull():
                    pm = pm0
        except Exception:
            pm = None
        cache[filename] = pm
        return pm

    # ---------- 鼠标：点一下 = 摸摸，拖动 = 拖拽 ----------
    def mousePressEvent(self, ev):
        # ⭐ 2026-09-29 手持工具时：点在角色身上 = 施法（⛔ 不触发拖拽/摸摸）
        if self._held_tool and self.act_with_tool(ev.button() == Qt.RightButton):
            ev.accept()
            return
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_started = False        # ⭐ 还没确定是"点"还是"拖"
            self._drag_off = ev.position().toPoint()
            self._press_pos = ev.position().toPoint()      # ⭐ 记按下点，用来分辨"点"还是"拖"
            self._press_t = time.perf_counter()
            self._moved = 0.0
            # ⛔⛔ 2026-09-28 修：这里【不再】无条件 begin_drag()。
            #   旧写法一按下就 begin_drag → 里面 self.asleep = False + play("drag")，
            #   等松手判定为"点击"再调 on_click() 时，asleep 早被清成 False、
            #   state 也变成 drag → on_click 的唤醒分支永远进不去 →
            #   睡着点一下 = 直接瞬移回 default，sleep_out 完全不播（Ronny 实测到的就是这个）。
            #   ✅ 改为：只有真正移动超过阈值才 begin_drag。

    def mouseMoveEvent(self, ev):
        # ⭐ v0.2：光标位置喂给 core（好感度高时她会主动朝光标走过来）
        gp = self.mapToGlobal(ev.position().toPoint())
        self.pet.set_cursor(float(gp.x()))
        if not self._dragging:
            return
        d = ev.position().toPoint() - self._press_pos
        self._moved = max(self._moved, (d.x() ** 2 + d.y() ** 2) ** 0.5)
        # ⭐ 移动超过阈值 → 此刻才真正进入拖拽（此前只是"按着没动"）
        if not self._drag_started and self._moved > DRAG_THRESHOLD:
            self._drag_started = True
            self.pet.begin_drag(self.pet.body.x, self.pet.body.y)
        if not self._drag_started:
            return
        # ⭐ 拖拽坐标推导（目标：按下时抓住的那个点，始终贴在光标下面不动）
        #
        #  记 G = 全局鼠标坐标，W = 窗口左上角，B = 脚底中点，anchor = (ax, ay)。
        #  渲染层恒等式：W = B - anchor   （因为 _apply_pos 就是 B - anchor）
        #  ⇒ B = W + anchor        ……(1)
        #
        #  按下瞬间记一次窗口内偏移：
        #      drag_off = 光标在窗口内的坐标 = G0 - W0
        #  拖动时要求该偏移保持不变（光标不"滑"出角色）：
        #      G - W = drag_off   ⇒   W = G - drag_off      ……(2)
        #
        #  把 (2) 代回 (1)：
        #      B = G - drag_off + anchor
        #  即：新脚底坐标 = 全局鼠标位置 - 按下时的窗口内偏移 + anchor 偏移。
        #
        #  ⛔ 旧写法还用 self.pos()（窗口当前位置）去凑修正项，等于把"窗口已经跟着
        #     动过多少"重复扣了一遍，且按 body.x - ax 还原窗口又多加/少加了一次 anchor，
        #     所以拖拽会持续偏移。这里直接从定义出发，不引用窗口当前坐标。
        #
        #  ⭐⭐ 2026-09-28 修：anchor 必须用【当前动作】的（横画幅 520×536 与 512 不同，
        #     用顶层 anchor 会在睡眠动作下把拖拽坐标算歪）。
        gp = self.mapToGlobal(ev.position().toPoint())
        ax, ay = self._cur_anchor()
        # ⭐⭐ 2026-09-30 修（Ronny：「拿起如果在露娜完全把手脚抬起来之前动鼠标
        #    就会变成鼠标和人物相差很远」）：
        #   ⛔ 旧写法这里用的是**没乘 user_scale 的 anchor**，而 `_apply_pos` 用的是
        #      `body − anchor×s`。两边口径不一致 → 每次拖拽恒定偏 `anchor.y×(s−1)`：
        #        实测 s=0.7328 时，y 方向每帧偏 512×0.2672 = **136px**，
        #        因为是 1:1 跟随、只是整体平移，看起来就是"人物挂在鼠标旁边很远"。
        #   ✅ 与 `_apply_pos` / `paintEvent` 统一口径：anchor 一律乘 s。
        sec = self.user_scale
        self.pet.move_drag(gp.x() - self._drag_off.x() + ax * sec,
                           gp.y() - self._drag_off.y() + ay * sec)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self._held_tool:
            self.hold_tool(self._held_tool)      # toggle 语义 = 放下
            ev.accept()
            return
        super().keyPressEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            dt = time.perf_counter() - self._press_t
            if self._drag_started:
                # 真的拖过 → 松手让她落下
                self._drag_started = False
                self.pet.end_drag()
            elif getattr(self, "_moved", 999) <= DRAG_THRESHOLD and dt <= CLICK_MAX_SEC:
                # ⭐ 短按且几乎没动 = 点了一下 → 摸摸（睡着时 = 叫醒，走 sleep_out）
                self.pet.on_click()
                if not self.pet.asleep:
                    print(f"[互动] 摸了一下　好感度 {self.pet.mood:.0f}")
                else:
                    print("[互动] 点了但她还睡着")
            # 其余情况（按住不动超时）：什么都不做

    # ---------- ⭐ 重新加载（不重启就能用上最新素材 / 参数）----------
    def reload_pack(self):
        """重读磁盘上的 pet.json 与全部帧，⚠ 保留当前位置与运动状态。

        ⭐ 用途：重新抠图 / 替换帧 / 调试台改了参数之后，**不用关掉重开**。
        ⛔ 只重载【素材与参数】，不重载 Python 代码 —— 代码改动仍需重启进程。
        """
        old_pos = (self.pet.body.x, self.pet.body.y)
        cur_action = self.pet.state
        try:
            pack = load_pack(self.pack.root)
            frames = load_frames(pack)
            if not frames:
                raise RuntimeError("没有加载到任何帧")
        except Exception as e:
            print(f"[重载] ⛔ 失败，保持原样：{e}")
            return False
        # ⭐ 换掉包与帧缓存
        self.pack = pack
        self.frames = frames
        all_imgs = [im for v in frames.values() for im in v]
        self.sil = silhouette_of(all_imgs, pack.anchor)
        # ⭐⭐ 2026-09-30：逐动作轮廓 + 逐帧站位也必须跟着重建 ——
        #   ⛔ 旧写法只重建了全局 self.sil，`self.sils`（逐动作限位轮廓）还指向**旧素材**：
        #      重新抠图 / 换帧之后，限位和切换补偿都在用过期数据。
        self.sils = {n: silhouette_of(v, pack.anchor_of(n)) for n, v in frames.items()}
        self.frame_stance = {n: [frame_stance(im, pack.anchor_of(n)) for im in v]
                             for n, v in frames.items()}
        self._last_act = None          # 素材换过了，切换补偿的基准清零
        self._last_idx = 0
        # ⭐ 宠物对象指向新的包/参数（保持位置与状态）
        self.pet.pack = pack
        self.pet.behaviour = pack.behaviour
        self.pet.anim = None
        self.pet.play(cur_action if cur_action in pack.actions else "idle")
        self.pet.body.x, self.pet.body.y = old_pos
        self._apply_pos()
        self.update()
        print(f"[重载] ✅ 已重载：{pack.name}　动作 "
              + ", ".join(f"{k}:{len(v)}" for k, v in frames.items()))
        return True

    # ---------- ⭐ 调试面板（托盘菜单入口，双击也能开）----------
    def open_tuner_once(self):
        from console import open_tuner
        if getattr(self, "tuner_win", None) is None:
            self.tuner_win = open_tuner(self)
        else:
            self.tuner_win.show()
            self.tuner_win.raise_()
            self.tuner_win.activateWindow()

    # ---------- 托盘 ----------
    def _tray_icon(self) -> QIcon:
        """托盘图标：优先用角色包里单独放的图标文件，没有再拿角色图兜底。

        ⭐ 为什么必须兜底：原写法 `self.windowIcon() or QIcon()` 是无效的 ——
           QIcon 没有"空即假"的真值语义，永远是真值，所以 `or` 后半段根本走不到，
           而本窗口从未 setWindowIcon，拿到的是空 QIcon，Windows 托盘区直接不显示图标。
        """
        for fname in ("icon.png", "icon.ico", "tray.png"):
            p = os.path.join(self.pack.root, fname)
            if os.path.exists(p):
                return QIcon(p)
        # 兜底：用第一帧角色图缩到 32x32（Windows 托盘建议尺寸，过大系统会硬缩导致糊）
        imgs = self.frames.get("idle") or next(iter(self.frames.values()))
        pm = QPixmap.fromImage(imgs[0]).scaled(
            32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QIcon(pm)

    def _make_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self._tray_icon())
        m = QMenu()
        a_toggle = QAction("显示 / 隐藏", self)
        a_toggle.triggered.connect(lambda: self.setVisible(not self.isVisible()))
        a_quit = QAction("退出", self)
        a_quit.triggered.connect(QApplication.quit)
        m.addAction(a_toggle)
        a_reload = QAction("⭐ 重新加载素材（不用重启）", self)
        a_reload.triggered.connect(self.reload_pack)
        m.addAction(a_reload)
        a_tuner = QAction("⭐ 手感调试面板", self)
        a_tuner.triggered.connect(self.open_tuner_once)
        m.addAction(a_tuner)
        m.addSeparator()
        m.addAction(a_quit)
        self.tray.setContextMenu(m)
        self.tray.show()


def run(pack_dir: str, tuner: bool = False):
    app = QApplication(sys.argv)
    pack = load_pack(pack_dir)
    w = PetWindow(pack)
    w.show()
    # ⭐⭐ 2026-09-29 生活容器工具栏（P0）：柜子贴屏幕左边缘，拉开抽屉取道具
    try:
        from ui_toolbar import ToolBar
        bar = ToolBar(w)
        bar.show()
        w._toolbar = bar            # 挂住引用，防被 GC
    except Exception as e:
        print(f"[工具栏] 未启用：{e}")
    if tuner:
        from console import open_tuner      # ⭐ 调试台（⛔ 成品默认不开）
        tw = open_tuner(w)
        tw.setWindowTitle(f"手感调试台 — {pack.name}")
    print(f"[引擎] 已启动：{pack.name}   （左键拖拽 / 托盘退出）")
    return app.exec()
