# -*- coding: utf-8 -*-
"""console.py —— 手感调试控制台（给创作者自己拧参数用的，⛔ 不进成品）

⭐ 为什么需要它：
   手感是主观的。我替你猜一个数，不如给你一个面板自己拧 ——
   **改完立刻生效，不用重启，还能存成预设、A/B 秒切对比。**

⭐ 怎么用：
   python run.py --tuner

⭐ 三块：
   ① 滑杆区 —— 拖一下马上生效（直接改内存里的 behaviour，不写盘）
   ② 预设区 —— 存 / 取 / 删；存下来自选名字，下次直接调用
   ③ ⭐ A/B 对比 —— 把手感存成 A 和 B，一键来回切，专治"记不住刚才那个好"
   ④ 设为默认 —— 把当前值写回 pet.json（这样 exe 启动就是它）
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QSlider, QPushButton, QComboBox,
                               QLineEdit, QGroupBox, QMessageBox, QDoubleSpinBox, QCheckBox)

# ---- 滑杆定义：(参数名, 显示名, 最小, 最大, 步进, 小数位, 提示) ----
PARAMS = [
    ("tilt_zeta",      "阻尼 ζ",        0.05, 1.20,  1, 2, "越小越晃（欠阻尼）；越大越快停"),
    ("tilt_drive",     "力（鼠标速度→力）", 200, 20000, 1, 0, "同样的鼠标速度，给多大的力"),
    ("tilt_drive_exp", "力的指数曲线",    0.5,  4.0,  1, 2, "⭐ >1：慢移几乎不倾、快甩才猛涨（解开矛盾的关键）"),
    ("tilt_vref",      "参考速度（多快算快甩）", 400, 5000, 1, 0, "越小 → 普通速度就算快甩 → 45° 更容易到"),
    ("tilt_omega0",    "固有频率 ω₀",    2.0, 10.0,  1, 2, "越小摆得越慢 = 越重"),
    ("drag_tilt_max",  "最大倾角（0=关掉）", 0,  60,   1, 0, "⭐ 拉到底 0 = 完全不做倾斜旋转（平面图旋转会产生「光影感」）"),
    ("tilt_force_tau", "换向惯性（秒）",  0.0,  3.0,  1, 2, "越大 → 左右换向越拖、不会被立刻甩过去"),
    ("walk_speed",     "走速（倍率）",    0.0,  3.0,  1, 2, "1.0 = 默认速度；0 = 不走"),
    ("gravity",        "重力",           300, 5000, 1, 0, "下落加速度 px/s²"),

    ("turn_chance",    "换向概率",        0,   100,  1, 0, "百分比；越低越少左右变换方向（防闪烁）"),
]


def _to_slider(v, lo, hi, step, dp):
    if dp == 0:
        return int(round(v))
    scale = 10 ** dp
    if "force_tau" in "":
        pass
    return int(round(v * scale))


from PySide6.QtWidgets import QApplication


class TunerWindow(QWidget):
    """调试控制台 —— 直接改 pet_window.pet.behaviour，实时生效"""

    def __init__(self, pet_window):
        super().__init__()
        self.pw = pet_window
        self.pack = pet_window.pack
        self.beh = pet_window.pet.behaviour
        self.preset_dir = os.path.join(self.pack.root, "presets")
        os.makedirs(self.preset_dir, exist_ok=True)
        self.sliders = {}
        self._ab = {"A": None, "B": None}

        self.setWindowTitle(f"手感调试台 — {self.pack.name}")
        self.resize(560, 720)
        root = QVBoxLayout(self)

        # ---------- ① 滑杆 ----------
        g = QGroupBox("手感参数（拖动即时生效，不写盘）")
        grid = QGridLayout(g)
        grid.addWidget(QLabel("参数"), 0, 0)
        grid.addWidget(QLabel("调节"), 0, 1, 1, 3)
        grid.addWidget(QLabel("当前值"), 0, 4)
        grid.addWidget(QLabel("自填"), 0, 5)
        r = 1
        for key, label, lo, hi, step, dp, tip in PARAMS:
            cur = getattr(self.beh, key, lo)
            # ⭐ 元组类参数（如 idle_duration=[min,max]）滑杆表达不了，跳过
            if isinstance(cur, (tuple, list)):
                continue
            grid.addWidget(QLabel(label), r, 0)
            s = QSlider(Qt.Horizontal)
            s.setRange(lo if dp == 0 else int(lo * 10 ** dp),
                       hi if dp == 0 else int(hi * 10 ** dp))
            s.setToolTip(tip)
            val = QLabel()
            val.setMinimumWidth(70)
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            def mk(k=s, key=key, dp=dp, lbl=val, lab=label):
                def on(v):
                    real = float(v) if dp else float(v)
                    if dp:
                        real = v / (10 ** dp)
                    setattr(self.beh, key, real)
                    lbl.setText(f"{real:.{dp}f}".rstrip("0").rstrip("."))
                return on

            s.valueChanged.connect(mk())
            # ⭐ 自填框：可直接键入精确数值（滑杆调粗、输入框调精）
            spin = QDoubleSpinBox()
            spin.setRange(lo, hi)
            spin.setDecimals(dp)
            spin.setSingleStep(0.01 if dp else 1.0)
            spin.setMinimumWidth(84)
            spin.setToolTip("可直接键入精确数值，回车即生效")

            def on_spin(v, s=s, key=key, dp=dp, lbl=val):
                real = float(v)
                setattr(self.beh, key, real)
                lbl.setText(f"{real:.{dp}f}".rstrip("0").rstrip("."))
                iv = int(round(real)) if dp == 0 else int(round(real * 10 ** dp))
                s.blockSignals(True)
                s.setValue(iv)
                s.blockSignals(False)

            spin.valueChanged.connect(on_spin)
            grid.addWidget(s, r, 1, 1, 3)
            grid.addWidget(val, r, 4)
            grid.addWidget(spin, r, 5)
            self.sliders[key] = (s, val, dp, spin)
            r += 1
        root.addWidget(g, 4)
        self._sync()

        # ---------- ⭐ 动作台：手动切换 / 暂停 / 播放 / 重置 / 帧信息 ----------
        ga = QGroupBox("⭐ 动作台（手动切换 · 演示用）")
        va = QVBoxLayout(ga)
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("动作"))
        self.act_cb = QComboBox()
        self.act_cb.setMinimumWidth(140)
        h1.addWidget(self.act_cb)
        b_play_act = QPushButton("▶ 播放这个动作")
        b_play_act.clicked.connect(self.play_selected_action)
        h1.addWidget(b_play_act)
        self.cb_loop = QCheckBox("循环播")
        self.cb_loop.setChecked(True)
        h1.addWidget(self.cb_loop)
        va.addLayout(h1)

        h2 = QHBoxLayout()
        # ⭐ 一个按钮来回切：文案随状态变（停着显示"播放"，动着显示"暂停"）
        self.b_toggle = QPushButton("⏸ 暂停")
        self.b_toggle.setMinimumWidth(110)
        self.b_toggle.setToolTip("同一个按钮：点一下暂停，再点一下继续")
        b_reset = QPushButton("⟲ 重置位置")
        b_step = QPushButton("◀ 退一帧")
        b_step2 = QPushButton("进一帧 ▶")
        self.b_toggle.clicked.connect(self.toggle_play)
        b_reset.clicked.connect(self.do_reset)
        b_step.clicked.connect(lambda: self.step_frame(-1))
        b_step2.clicked.connect(lambda: self.step_frame(+1))
        h2.addWidget(self.b_toggle)
        h2.addWidget(b_step); h2.addWidget(b_step2); h2.addWidget(b_reset)
        va.addLayout(h2)

        h3 = QHBoxLayout()
        self.frame_lbl = QLabel("当前帧：—")
        self.frame_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b_copy = QPushButton("复制路径")
        b_copy.setToolTip("把当前帧的完整文件路径复制到剪贴板 —— 方便把「哪一帧不对」告诉我")
        b_copy.clicked.connect(self.copy_frame_path)
        h3.addWidget(self.frame_lbl, 1); h3.addWidget(b_copy)
        va.addLayout(h3)
        root.addWidget(ga)
        self.refresh_actions()

        # ---------- ② 预设 ----------
        p = QGroupBox("预设（存 / 取 / 删）")
        hb = QHBoxLayout(p)
        self.cb = QComboBox()
        self.cb.setMinimumWidth(160)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("预设名，如「中-偏重」")
        b_save = QPushButton("保存为…")
        b_load = QPushButton("载入")
        b_del = QPushButton("删除")
        b_save.clicked.connect(self.save_preset)
        b_load.clicked.connect(self.load_preset)
        b_del.clicked.connect(self.del_preset)
        hb.addWidget(QLabel("已存"))
        hb.addWidget(self.cb)
        hb.addWidget(self.name_edit)
        hb.addWidget(b_save)
        hb.addWidget(b_load)
        hb.addWidget(b_del)
        root.addWidget(p)
        self.refresh_presets()

        # ---------- ③ A/B ----------
        ab = QGroupBox("⭐ A / B 对比（存两个手感，一键来回切）")
        hb2 = QHBoxLayout(ab)
        self.lab_ab = QLabel("A: —    B: —")
        for t in ("A", "B"):
            QPushButton  # noqa
            b1 = QPushButton(f"存为 {t}")
            b2 = QPushButton(f"切到 {t}")
            b1.clicked.connect(lambda _=False, t=t: self.store_ab(t))
            b2.clicked.connect(lambda _=False, t=t: self.apply_ab(t))
            hb2.addWidget(b1)
            hb2.addWidget(b2)
        hb2.addWidget(self.lab_ab)
        root.addWidget(ab)

        # ---------- ④ 写盘 / 重置 ----------
        hb3 = QHBoxLayout()
        b_def = QPushButton("⭐ 设为默认（写回 pet.json）")
        b_def.clicked.connect(self.set_default)
        b_reset = QPushButton("重新读取 pet.json")
        b_reset.clicked.connect(self.reload)
        b_reload = QPushButton("⭐ 重新加载素材")
        b_reload.setToolTip("重读磁盘上的 pet.json 与全部帧 —— 改完素材/参数不用重启")
        b_reload.clicked.connect(self.do_reload)
        b_pause = QPushButton("暂停 / 继续 宠物")
        b_pause.setCheckable(True)
        b_pause.toggled.connect(self.toggle_pause)
        hb3.addWidget(b_reload)
        hb3.addWidget(b_def)
        hb3.addWidget(b_reset)
        hb3.addWidget(b_pause)
        root.addLayout(hb3)

        self.status = QLabel("")
        root.addWidget(self.status)

        # ⭐ 每 200ms 刷新"当前帧"显示（暂停时也能看到停在哪一帧）
        self._ftimer = QTimer(self)
        self._ftimer.timeout.connect(self._update_frame_label)
        self._ftimer.start(200)

    # ---------- 同步 ----------
    def _sync(self):
        for key, item in self.sliders.items():
            s, val, dp = item[0], item[1], item[2]
            spin = item[3] if len(item) > 3 else None
            cur = getattr(self.beh, key, 0)
            iv = int(round(cur)) if dp == 0 else int(round(cur * 10 ** dp))
            s.blockSignals(True)
            s.setValue(iv)
            s.blockSignals(False)
            if spin is not None:
                spin.blockSignals(True)
                spin.setValue(float(cur))
                spin.blockSignals(False)
            val.setText(f"{cur:.{dp}f}".rstrip("0").rstrip("."))

    def _snapshot(self):
        return {k: getattr(self.beh, k) for k, *_ in PARAMS
                if hasattr(self.beh, k)}

    # ---------- ⭐ 动作台 ----------
    def refresh_actions(self):
        self.act_cb.clear()
        self.act_cb.addItems(list(self.pw.frames.keys()))

    def play_selected_action(self):
        name = self.act_cb.currentText()
        if not name:
            return
        pet = self.pw.pet
        pet.goal = None
        pet._pat_t = 0.0
        # ⭐ 不循环的话把动作临时改成 once（演示单次）
        if not self.cb_loop.isChecked():
            pet.anim = None
        pet.play(name)
        if not self.cb_loop.isChecked():
            pet.anim.seq = pet.anim.seq          # 保持原样；once 动作本来就不循环
        if not self.pw.timer.isActive():
            self.pw.timer.start(16)
        self.status.setText(f"▶ 正在播「{name}」")
        self._update_frame_label()

    def toggle_play(self):
        """⭐ 一个按钮切换暂停/播放（文案跟着变）"""
        if self.pw.timer.isActive():
            self.pw.timer.stop()
            self.b_toggle.setText("▶ 播放")
            self._update_frame_label()
            self.status.setText("⏸ 已暂停 —— 可退/进一帧，或复制路径告诉我")
        else:
            self.pw.timer.start(16)
            self.b_toggle.setText("⏸ 暂停")
            self.status.setText("▶ 已继续")
        self._sync_toggle_text()

    def _sync_toggle_text(self):
        self.b_toggle.setText("⏸ 暂停" if self.pw.timer.isActive() else "▶ 播放")

    def step_frame(self, d):
        """⭐ 暂停时逐帧前后翻 —— 找坏帧用"""
        if self.pw.timer.isActive():
            self.pw.timer.stop()
            self._sync_toggle_text()
        pet = self.pw.pet
        if not pet.anim:
            return
        a = pet.anim
        a.i = max(0, min(len(a.seq) - 1, a.i + d))
        a.t = 0.0
        self.pw.update()
        self._update_frame_label()
        self.status.setText(f"⏸ 第 {a.i + 1}/{len(a.seq)} 帧（{a.act.name}）")

    def do_pause(self):
        self.pw.timer.stop()
        self._update_frame_label()
        self.status.setText("⏸ 已暂停（帧信息见下方，可复制路径）")

    def do_resume(self):
        self.pw.timer.start(16)
        self.status.setText("▶ 已继续")

    def do_reset(self):
        """把她放回屏幕底部中间，并回到 idle"""
        pet = self.pw.pet
        pet.goal = None; pet._pat_t = 0.0; pet.mood = 50.0
        pet._walk_v = 0.0; pet.body.vx = pet.body.vy = 0.0
        pet.body.tilt = 0.0; pet._theta = 0.0; pet._omega = 0.0
        sl, st, sr, sb = self.pw.screen_rect
        pet.body.x = (sl + sr) / 2.0; pet.body.y = float(sb)
        pet.body.on_ground = True
        pet.play("idle")
        self.pw._apply_pos()
        self.pw.update()
        self.status.setText("⟲ 已重置到屏幕底部中间")

    def _update_frame_label(self):
        p = self.pw.pet.current_frame_path()
        if not p:
            self.frame_lbl.setText("当前帧：—"); return
        self.frame_lbl.setText(f"当前帧：{os.path.basename(p)}　（{os.path.basename(os.path.dirname(p))}/）")

    def copy_frame_path(self):
        p = self.pw.pet.current_frame_path()
        if not p:
            self.status.setText("⚠ 当前没有帧"); return
        QApplication.clipboard().setText(os.path.abspath(p))
        self.status.setText(f"✅ 已复制路径：{os.path.basename(p)}")

    # ---------- 预设 ----------
    def refresh_presets(self):
        self.cb.clear()
        fs = sorted(f[:-5] for f in os.listdir(self.preset_dir) if f.endswith(".json"))
        self.cb.addItems(fs)

    def save_preset(self):
        n = self.name_edit.text().strip()
        if not n:
            QMessageBox.warning(self, "缺名字", "先给这个手感起个名字")
            return
        with open(os.path.join(self.preset_dir, f"{n}.json"), "w", encoding="utf-8") as f:
            json.dump(self._snapshot(), f, ensure_ascii=False, indent=2)
        self.refresh_presets()
        self.cb.setCurrentText(n)
        self.status.setText(f"✅ 已保存「{n}」")

    def load_preset(self):
        n = self.cb.currentText()
        if not n:
            return
        self._apply(json.load(open(os.path.join(self.preset_dir, f"{n}.json"), encoding="utf-8")))
        self.status.setText(f"✅ 已载入「{n}」")

    def del_preset(self):
        n = self.cb.currentText()
        if not n:
            return
        os.remove(os.path.join(self.preset_dir, f"{n}.json"))
        self.refresh_presets()
        self.status.setText(f"已删除「{n}」")

    def _apply(self, d):
        for k, v in d.items():
            if hasattr(self.beh, k):
                setattr(self.beh, k, v)
        self._sync()

    # ---------- A/B ----------
    def store_ab(self, t):
        self._ab[t] = self._snapshot()
        self.lab_ab.setText(f"A: {'已存' if self._ab['A'] else '—'}    B: {'已存' if self._ab['B'] else '—'}")
        self.status.setText(f"✅ 当前手感已存为 {t}")

    def apply_ab(self, t):
        if not self._ab[t]:
            self.status.setText(f"⚠ {t} 还没存过")
            return
        self._apply(self._ab[t])
        self.status.setText(f"✅ 已切到 {t}（拖一下鼠标感受差别）")

    # ---------- 默认 / 重置 / 暂停 ----------
    def set_default(self):
        cfg = json.load(open(os.path.join(self.pack.root, "pet.json"), encoding="utf-8"))
        cfg["behaviour"].update(self._snapshot())
        cfg["behaviour"]["_已选定档位"] = "自定义（调试台写入）"
        json.dump(cfg, open(os.path.join(self.pack.root, "pet.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        self.status.setText("✅ 已写回 pet.json —— 下次启动（含 exe）就是这个手感")

    def do_reload(self):
        """⭐ 重读磁盘素材（帧 + 参数）—— 不用关掉重开"""
        ok = self.pw.reload_pack()
        self.beh = self.pw.pet.behaviour          # ⭐ 重新绑定（对象换了）
        self.pack = self.pw.pack
        self._sync()
        self.status.setText("✅ 已重新加载素材" if ok else "⛔ 重载失败，看日志")

    def reload(self):
        cfg = json.load(open(os.path.join(self.pack.root, "pet.json"), encoding="utf-8"))
        self._apply(cfg.get("behaviour", {}))
        self.status.setText("已重新读取 pet.json")

    def toggle_pause(self, on):
        if on:
            self.pw.timer.stop()
        else:
            self.pw.timer.start(16)


def open_tuner(pet_window):
    w = TunerWindow(pet_window)
    w.show()
    return w
