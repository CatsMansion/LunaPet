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
from typing import Dict, Tuple

import numpy as np
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QImage, QPixmap, QTransform, QPainter, QColor, QAction, QIcon
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import Pet, PetPack, load_pack   # noqa: E402


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
    """⭐ 由所有帧的 alpha 并集算出【角色实际轮廓】
    返回相对"脚底中点"的 (左, 右, 上, 下) 偏移 —— 用于按真实轮廓限位。

    ⛔ DyberPet 的坑：它按【窗口半宽】限位 → 半个 sprite 能出屏。
    ✅ 我们按【轮廓】限位。
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
        # ⭐ 屏幕限位用的"实际轮廓"（所有动作的并集）
        all_imgs = [im for v in self.frames.values() for im in v]
        self.sil = silhouette_of(all_imgs, pack.anchor)
        print(f"[轮廓] 相对脚底中点  左{self.sil[0]}  右{self.sil[1]}  上{self.sil[2]}  下{self.sil[3]}")
        print(f"[帧] {', '.join(f'{k}:{len(v)}' for k, v in self.frames.items())}")

        scr = QApplication.primaryScreen().availableGeometry()
        self.screen_rect = (scr.left(), scr.top(), scr.right(), scr.bottom())
        self.pet = Pet(pack, self.screen_rect)
        self.pet.body.x = scr.center().x()
        self.pet.body.y = scr.bottom()

        self._drag_off = QPoint(0, 0)
        self._dragging = False

        self._apply_pos()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._last_ms = 0
        self.timer.start(16)          # ~60fps 的推进（动画本身按 fps 走）
        self._make_tray()

    # ---------- 位置 ----------
    def _apply_pos(self):
        """把「脚底中点」换算成窗口左上角"""
        ax, ay = self.pack.anchor
        self.move(int(self.pet.body.x - ax), int(self.pet.body.y - ay))

    # ---------- 主循环 ----------
    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last_ms) if self._last_ms else 0.016
        self._last_ms = now
        self.pet.step(dt, self.sil)
        self._apply_pos()
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
        # ⭐ 镜像（左右走）
        if name == "walk" and not p.facing_right:
            pm = pm.transformed(QTransform().scale(-1, 1))
        # ⭐ 拖拽倾斜（今天 issue #103 的诉求）
        if abs(p.body.tilt) > 0.1:
            pm = pm.transformed(QTransform().rotate(p.body.tilt), Qt.SmoothTransformation)
        painter = QPainter(self)
        ax, ay = self.pack.anchor
        painter.drawPixmap(ax - pm.width() // 2, ay - pm.height(), pm)
        # ⭐ v0.2：被摸时冒爱心（纯绘制，不需要素材）
        for i, h in enumerate(getattr(self.pet, "_hearts", [])):
            t = h[0]
            if t >= 1.1:
                continue
            a = int(255 * max(0.0, 1.0 - t / 1.1))
            # ⭐ 用【归一化身高 488】定位头部，不用 pm.height()（那是整张画布，且倾斜时会变）
            # ⭐ 几何事实：角色头顶在 y≈9（轮廓上边界 -503），画布顶是 0 →
            #   "飘到头顶上方"会被裁掉，所以【往上飘改成往下沉一点 + 侧向排开】，
            #   并加白色描边，保证压在深色头发上也看得清。
            hx = ax + (i - len(self.pet._hearts) / 2.0) * 30.0 + 70.0
            hy = ay - 455.0 + t * 25.0
            r = 17.0
            painter.setPen(QColor(255, 255, 255, a))
            painter.setBrush(QColor(232, 80, 120, a))
            painter.drawEllipse(int(hx - r * 0.75), int(hy), int(r), int(r))
            painter.drawEllipse(int(hx - r * 0.15), int(hy), int(r), int(r))
            painter.drawPolygon([QPoint(int(hx - r * 0.95), int(hy + r * 0.55)),
                                 QPoint(int(hx + r * 0.95), int(hy + r * 0.55)),
                                 QPoint(int(hx), int(hy + r * 1.9))])
        painter.end()

    # ---------- 鼠标：点一下 = 摸摸，拖动 = 拖拽 ----------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_off = ev.position().toPoint()
            self._press_pos = ev.position().toPoint()      # ⭐ 记按下点，用来分辨"点"还是"拖"
            self._press_t = time.perf_counter()
            self._moved = 0.0
            self.pet.begin_drag(self.pet.body.x, self.pet.body.y)

    def mouseMoveEvent(self, ev):
        # ⭐ v0.2：光标位置喂给 core（好感度高时她会主动朝光标走过来）
        gp = self.mapToGlobal(ev.position().toPoint())
        self.pet.set_cursor(float(gp.x()))
        if self._dragging:
            d = ev.position().toPoint() - self._press_pos
            self._moved = max(self._moved, (d.x() ** 2 + d.y() ** 2) ** 0.5)
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
            gp = self.mapToGlobal(ev.position().toPoint())
            ax, ay = self.pack.anchor
            self.pet.move_drag(gp.x() - self._drag_off.x() + ax,
                               gp.y() - self._drag_off.y() + ay)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            dt = time.perf_counter() - self._press_t
            # ⭐ 短按且几乎没动 = 点了一下 → 摸摸（否则算拖拽）
            if getattr(self, "_moved", 999) <= 6.0 and dt <= 0.40:
                self.pet.on_click()
                print(f"[互动] 摸了一下　好感度 {self.pet.mood:.0f}")
            else:
                self.pet.end_drag()

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
    if tuner:
        from console import open_tuner      # ⭐ 调试台（⛔ 成品默认不开）
        tw = open_tuner(w)
        tw.setWindowTitle(f"手感调试台 — {pack.name}")
    print(f"[引擎] 已启动：{pack.name}   （左键拖拽 / 托盘退出）")
    return app.exec()
