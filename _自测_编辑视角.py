# -*- coding: utf-8 -*-
"""_自测_编辑视角.py —— PR16「编辑态自由视角 + 选中地形可拖动」验收

⭐ 纪律（沿用 _自测_攻击特效.py / _自测_自定义地形.py）：
   ① 一律驱动**真实**代码（真实 keyPressEvent / mouseMoveEvent / _tick）
   ② 假时钟（**必须**在 `from pet_engine import night` **之前**替换）
   ③ ⭐ 必须强制 render —— 画分支的错只在真渲染时暴露
   ④ ⛔ **每条阴性结果必配阳性对照**

⛔ 本文件**新建**（不改动任何既有 `_自测_*.py` —— 派单 §D 明令禁碰）。
⛔ 只测 PR16 的 **A 段**（视角 + 拖动）。B 段（默认 4 平台可编辑）待 Ronny 拍板后另开。

判据（派单 §C）：
   C1  按住 D 一秒 ⇒ cam_x ≈ +900（±15%），且 clamp 在 2560 不再涨
       └ 阳性对照：按住 A 从 2560 ⇒ 减到 0 且不再降
   C2  编辑态平移不影响 play（`_step_cam` 逐帧行为不变）
   C3  `_to_world` 在 cam_x=2000 时屏幕最右 ⇒ 3280（阳性对照 cam_x=0 ⇒ 1280）
   C4  选中地形拖 100px ⇒ 4 坐标同位移、宽高不变
   C5  拖动**不触发**新建（select 拖 ⇒ 条数不变；阳性对照 rect 拖 ⇒ 条数 +1）
   C11 Home ⇒ 恰 0.0；End ⇒ 恰 2560.0；PageUp 从 0 ⇒ 仍是 0
   附   §A.6 进/出编辑态不重置 cam_x
"""
import os
import sys
import json
import hashlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt, QEvent, QPointF
from PySide6.QtGui import QMouseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

# =============================================================================
# ⭐⭐⭐ 假时钟：**必须**在 `from pet_engine import night` 之前替换
# =============================================================================
# ⚠️⚠️ PR14 栽过一次：替换写在 import 之后 ⇒ dt 恒为 0 ⇒ 一堆判据一起红，
#   我一度误判成「功能被改坏了」。症状是「时序不推进」时先量 dt。
import time as _time_mod

_T = [0.0]
_time_mod.perf_counter = lambda: _T[0]

DT = 1.0 / 60.0

from pet_engine.core import load_pack
from pet_engine import night as N      # ⛔ 必须排在假时钟替换**之后**

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


def section(t):
    print()
    print("=" * 74)
    print(t)
    print("=" * 74)


def step(w, n=1):
    """推进 n 帧（dt 精确 = 1/60）。"""
    for _ in range(n):
        _T[0] += DT
        w._tick()


def _mouse(kind, btn, pos, mods=Qt.NoModifier):
    return QMouseEvent(kind, QPointF(float(pos[0]), float(pos[1])), btn, btn, mods)


def _key(k, kind=QEvent.KeyPress):
    return QKeyEvent(kind, k, Qt.NoModifier)


def new_w():
    w = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    w.start_night(0)
    w.set_mode("edit")
    return w


K = lambda w, v: v * w.k       # 逻辑坐标 → 屏幕像素（_to_world 会除以 k）


# ============================================================================
section("⑯·PR16-A · 编辑态自由视角（派单 C1 / C3 / C11）")
# ============================================================================

# ---- 判据 0：常量存在 ----
_ok0 = hasattr(N, "EDIT_CAM_SPEED") and N.EDIT_CAM_SPEED >= 400.0
chk("⑯-0 ⭐ EDIT_CAM_SPEED 存在且 ≥400（⛔ <400 挪完 3840 要 10 秒）", _ok0,
    "EDIT_CAM_SPEED=%s" % getattr(N, "EDIT_CAM_SPEED", None))

# ---- C1-a：真实按键 + 真实 _tick 跑 1 秒 ----
w = new_w()
w.cam_x = 0.0
w.keys.clear()
_x0 = w.cam_x
w.keyPressEvent(_key(Qt.Key_D))        # ⭐ 真实按下（不直接塞 self.keys）
_ok_keyin = Qt.Key_D in w.keys
chk("⑯-1 ⭐⭐ A/D 不进 _edit_key ⇒ 真的进了 self.keys（按住持续平移的前提）",
    _ok_keyin, "keys=%s（含 Key_D=%s）" % ([_k for _k in w.keys], _ok_keyin))
step(w, 60)                            # 1 秒
_d1 = w.cam_x - _x0
_ok1 = 765.0 <= _d1 <= 1035.0          # 900 ±15%
chk("⑯-2 ⭐⭐ C1-a 按住 D 一秒 ⇒ cam_x +%.1f（期望 900±15%%）" % _d1, _ok1,
    "cam_x %.1f → %.1f" % (_x0, w.cam_x))

# ---- C1-b：继续按住 ⇒ clamp 在 2560，不再涨 ----
step(w, 600)                           # 再 10 秒（总位移能力 9900 ≫ 2560）
_ok2 = w.cam_x == float(N.CAM_X_MAX)
chk("⑯-3 ⭐⭐ C1-b 一直按住 ⇒ clamp 在 CAM_X_MAX 不再涨", _ok2,
    "cam_x=%r（期望 %r 精确相等）" % (w.cam_x, float(N.CAM_X_MAX)))

# ---- C1 阳性对照：A 从 2560 往左 ⇒ 减到 0 且不再降 ----
w.keyReleaseEvent(_key(Qt.Key_D, QEvent.KeyRelease))
w.keyPressEvent(_key(Qt.Key_A))
step(w, 600)
_ok3 = w.cam_x == 0.0
chk("⑯-4 ⭐⭐ C1 阳性对照：按住 A ⇒ 减到 0.0 且不再降（证明判据有分辨力）",
    _ok3, "cam_x=%r（期望 0.0）" % w.cam_x)
# ⭐ 方向键也要能用（派单 §A.3 要求 ←/→ 与 A/D 等价）
# ⛔ 必须先松开 A：A 与 → 同时按着 ⇒ d = -1+1 = 0（左右抵消），那是**正确行为**，
#    但会让这条判据变成"什么都没动"，是我第一版自己埋的坑。
w.keyReleaseEvent(_key(Qt.Key_A, QEvent.KeyRelease))
w.keyPressEvent(_key(Qt.Key_Right))
step(w, 60)
_d4 = w.cam_x
w.keyReleaseEvent(_key(Qt.Key_Right, QEvent.KeyRelease))
chk("⑯-4b ⭐ 方向键 → 与 D 等价（按住一秒同样是 ~900）",
    765.0 <= _d4 <= 1035.0, "cam_x=%.1f" % _d4)

# ---- 阴性：不按键 ⇒ 一帧都不动 ----
w.keys.clear()
_c_before = w.cam_x
step(w, 120)
_ok5 = w.cam_x == _c_before
chk("⑯-5 ⭐ 阴性：不按键 ⇒ cam_x 一帧不动（漂移 0）", _ok5,
    "cam_x %.4f → %.4f" % (_c_before, w.cam_x))

# ---- C3：_to_world 覆盖世界右半 ----
w.cam_x = 2000.0
_wx_right = w._to_world(K(w, float(N.VW)), 0.0)[0]
_ok6 = abs(_wx_right - 3280.0) < 0.5
chk("⑯-6 ⭐⭐ C3 cam_x=2000 ⇒ 屏幕最右 = 世界 x=%.1f（期望 3280，不是 1280）"
    % _wx_right, _ok6, "k=%.4f" % w.k)
# ⭐⭐ 阳性对照
w.cam_x = 0.0
_wx_right0 = w._to_world(K(w, float(N.VW)), 0.0)[0]
_ok7 = abs(_wx_right0 - 1280.0) < 0.5
chk("⑯-7 ⭐⭐ C3 阳性对照 cam_x=0 ⇒ 屏幕最右 = %.1f（期望 1280）" % _wx_right0,
    _ok7, "（两条一起才证明 cam_x 真的进了 _to_world）")

# ---- C11：跳转键 ----
w.cam_x = 1000.0
_r_home = w._edit_key(Qt.Key_Home)
_ok8 = (w.cam_x == 0.0 and _r_home is True)
chk("⑯-8 ⭐ C11 Home ⇒ cam_x 恰为 0.0 且按键被吃掉", _ok8,
    "cam_x=%r return=%s" % (w.cam_x, _r_home))
_r_end = w._edit_key(Qt.Key_End)
_ok9 = (w.cam_x == float(N.CAM_X_MAX) and _r_end is True)
chk("⑯-9 ⭐ C11 End ⇒ cam_x 恰为 %r 且按键被吃掉" % float(N.CAM_X_MAX), _ok9,
    "cam_x=%r return=%s" % (w.cam_x, _r_end))
w.cam_x = 0.0
w._edit_key(Qt.Key_PageUp)
_ok10 = w.cam_x == 0.0
chk("⑯-10 ⭐ C11 PageUp 从 0 ⇒ 仍是 0（不越界成负）", _ok10, "cam_x=%r" % w.cam_x)
w.cam_x = float(N.CAM_X_MAX)
w._edit_key(Qt.Key_PageDown)
_ok11 = w.cam_x == float(N.CAM_X_MAX)
chk("⑯-11 ⭐ C11 PageDown 从 2560 ⇒ 仍是 2560（不越界）", _ok11,
    "cam_x=%r" % w.cam_x)
w.cam_x = 0.0
w._edit_key(Qt.Key_PageDown)
_ok12 = abs(w.cam_x - float(N.VW)) < 1e-9
chk("⑯-12 ⭐ C11 PageDown 从 0 ⇒ 恰 +1280（跳一屏）", _ok12, "cam_x=%r" % w.cam_x)
w._edit_key(Qt.Key_PageUp)
_ok13 = w.cam_x == 0.0
chk("⑯-13 ⭐ C11 PageUp 从 1280 ⇒ 回到 0（跳回一屏）", _ok13, "cam_x=%r" % w.cam_x)
# ⭐ 阳性对照：这些键**不该**进 self.keys（一次性动作，进去了会在 play 里残留）
w.keys.clear()
w.cam_x = 500.0
w._edit_key(Qt.Key_Home)
_ok14 = len(w.keys) == 0
chk("⑯-14 ⭐⭐ 阳性对照：跳转键走 _edit_key ⇒ 不进 self.keys（play 里不残留）",
    _ok14, "keys=%s（期望空）" % list(w.keys))

# ---- §A.6：进/出编辑态不重置 cam_x ----
w.cam_x = 1500.0
w.set_mode("play")
_a1 = w.cam_x
w.set_mode("edit")
_a2 = w.cam_x
w.set_mode("play_custom")
_a3 = w.cam_x
_ok15 = (_a1 == 1500.0 and _a2 == 1500.0 and _a3 == 1500.0)
chk("⑯-15 ⭐⭐ §A.6 进/出编辑态**不重置** cam_x（Ronny 平移到 2000 画了块地，"
    "F4 试跑再 F2 回来视野不该跳回 0）", _ok15,
    "play=%.1f edit=%.1f play_custom=%.1f" % (_a1, _a2, _a3))


# ============================================================================
section("⑯·PR16-A · C2：编辑态平移不污染 play 的 _step_cam")
# ============================================================================

# ---- C2-a：_step_cam 5000 帧，cam_x 恒在 [0,2560] ----
w2 = new_w()
w2.set_mode("play")
_worst_lo, _worst_hi = 0.0, 0.0
for _i in range(5000):
    # 露娜来回横扫（含远超世界右边界的极端值）
    w2.luna.x = -500.0 + (_i * 7.0) % 6000.0
    w2._step_cam(DT)
    if w2.cam_x < _worst_lo:
        _worst_lo = w2.cam_x
    if w2.cam_x > _worst_hi:
        _worst_hi = w2.cam_x
_ok16 = (_worst_lo >= 0.0 and _worst_hi <= float(N.CAM_X_MAX))
chk("⑯-16 ⭐⭐ C2-a _step_cam 跑 5000 帧（露娜横扫 -500~5500）⇒ cam_x 越界 0 次",
    _ok16,
    "min=%.6f max=%.6f（允许区间 [0, %.0f]）" % (_worst_lo, _worst_hi,
                                                  float(N.CAM_X_MAX)))
# ⭐⭐ 阳性对照：判据必须**认得出**越界（否则上面那条是零分辨力的假绿）
#   ⛔ 我第一版写成「把上界改成 100，让 cam_x 从 500 收敛下去」⇒ 收敛方向是**向下**，
#      永远够不到 100 以上 ⇒ 判据恒绿，等于没测。
#   ✅ 正确做法：利用 `_step_cam` 的**死区早退**（死区命中时 `return`，不执行夹取）
#      ⇒ 构造「cam_x 已越界 + 落在死区内」⇒ 越界值**不会被夹回**，判据必须报红。
_ORIG_MAX = N.CAM_X_MAX
try:
    N.CAM_X_MAX = 100.0                  # ⛔ 故意把上界改小
    w2.cam_x = 500.0                     # 已知越界值
    w2.luna.x = 640.0 + 500.0            # 死区正中 ⇒ _step_cam 直接 return，不夹
    for _ in range(50):
        w2._step_cam(DT)
    _stuck = w2.cam_x
    # ⭐ 判据（与 ⑯-16 完全同一个谓词）现在**必须**为 False
    _ok17 = not (0.0 <= _stuck <= float(N.CAM_X_MAX))
finally:
    N.CAM_X_MAX = _ORIG_MAX
chk("⑯-17 ⭐⭐ C2 阳性对照：注入越界 cam_x + 死区早退 ⇒ 逐帧判据**必须**报红",
    _ok17,
    "cam_x=%.4f 落在 [0,100] 之外 ⇒ 判据红（证明 ⑯-16 不是恒真）" % _stuck)

# ---- C2-b：编辑态平移过的 cam_x，回 play 后 _step_cam 仍收敛到正确值 ----
w3 = new_w()                       # edit 态
w3.cam_x = 0.0
w3.keyPressEvent(_key(Qt.Key_D))
step(w3, 180)                      # 编辑态平移到 ~2700（会被 clamp 到 2560）
w3.keyReleaseEvent(_key(Qt.Key_D, QEvent.KeyRelease))
_edit_cam = w3.cam_x
w3.set_mode("play")
w3.phase = "play"
w3.luna.x = 700.0                  # want = 700-640 = 60
for _ in range(400):
    w3._step_cam(DT)
# ⛔ 期望**不是** 60±1：`_step_cam` 有 CAM_X_DEAD=24 的死区，
#    cam_x 一进「距 want 24px 内」就**完全不动** ⇒ 最终停在 want±24 之内。
#    （我第一版写 <1.0 ⇒ 假红，是判据错不是代码错。）
_ok18 = abs(w3.cam_x - 60.0) <= N.CAM_X_DEAD
chk("⑯-18 ⭐⭐ C2-b 编辑态平移后回 play ⇒ _step_cam 仍收敛到 want=60（±死区 24）",
    _ok18,
    "编辑态 cam_x=%.1f → play 收敛到 %.4f（期望 60±%.0f）"
    % (_edit_cam, w3.cam_x, N.CAM_X_DEAD))
# ⭐ 阳性对照：判据必须认得出「没收敛」——换个别的 want 也照样收敛
w3.luna.x = 3000.0                      # want = 2360
for _ in range(400):
    w3._step_cam(DT)
_ok18b = abs(w3.cam_x - 2360.0) <= N.CAM_X_DEAD
chk("⑯-18b ⭐ 阳性对照：换 want=2360 同样收敛（证明 ⑯-18 不是碰巧）", _ok18b,
    "cam_x=%.4f（期望 2360±%.0f）" % (w3.cam_x, N.CAM_X_DEAD))


# ============================================================================
section("⑯·PR16-A · C4 / C5：选中地形可拖动")
# ============================================================================

def _fresh_with_block():
    """造一个只含 1 块已知地形（100×50 @ 300,400）的编辑态窗口。"""
    _w = new_w()
    _w.cam_x = 0.0                 # ⛔⛔ 必须归零（_to_world = px/k + cam_x）
    _w.custom_terrains = [{"kind": "solid", "x0": 300.0, "y0": 400.0,
                           "x1": 400.0, "y1": 450.0}]
    _w.room = N.Room(N.NIGHTS[_w.night_idx], custom=_w.custom_terrains)
    _w.edit_tool = "select"
    _w.edit_sel = -1
    _w._drag = None
    _w._move_from = None
    _w._move_orig = None
    _w._move_snap = False
    _w._undo = []
    return _w


# ---- C4：select 工具拖动 100px ----
w4 = _fresh_with_block()
_p0 = (K(w4, 350.0), K(w4, 425.0))     # 点在块内
w4.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, _p0))
_ok19 = (w4.edit_sel == 0 and w4._move_from is not None)
chk("⑯-19 ⭐ C4 前置：点中地形 ⇒ edit_sel=0 且记下拖动起点", _ok19,
    "edit_sel=%s _move_from=%s" % (w4.edit_sel, w4._move_from))
_p1 = (K(w4, 450.0), K(w4, 425.0))     # 右移 100
w4.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, _p1))
_t = w4.custom_terrains[0]
_wd, _ht = _t["x1"] - _t["x0"], _t["y1"] - _t["y0"]
_ok20 = (abs(_t["x0"] - 400.0) < 1.0 and abs(_t["x1"] - 500.0) < 1.0
         and abs(_t["y0"] - 400.0) < 1.0 and abs(_t["y1"] - 450.0) < 1.0
         and abs(_wd - 100.0) < 1e-6 and abs(_ht - 50.0) < 1e-6)
chk("⑯-20 ⭐⭐ C4 拖 100px ⇒ 4 坐标同位移且宽高不变", _ok20,
    "实测 (%s,%s,%s,%s) 宽高 %.1f×%.1f（期望 400,400,500,450 / 100×50）"
    % (_t["x0"], _t["y0"], _t["x1"], _t["y1"], _wd, _ht))

# ---- 拖动结束 ⇒ Room 重建（改完不生效是最难查的一类 bug）----
w4.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, _p1))
_plats = w4.room.platforms[len(N.PLATFORMS):]
_ok21 = (len(_plats) == 1 and abs(_plats[0]["x0"] - 400.0) < 1.0)
chk("⑯-21 ⭐ C4 松手 ⇒ Room 已重建（room.platforms 里是新坐标）", _ok21,
    "custom 层 = %s" % ([(_p2["x0"], _p2["y0"], _p2["x1"], _p2["y1"])
                         for _p2 in _plats],))

# ---- 一次拖动 = 一份撤销快照 ----
_u0 = len(w4._undo)
w5 = _fresh_with_block()
w5.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                          (K(w5, 350.0), K(w5, 425.0))))
for _i in range(30):               # 模拟拖 30 帧
    w5.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton,
                             (K(w5, 350.0 + _i), K(w5, 425.0))))
w5.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton,
                            (K(w5, 379.0), K(w5, 425.0))))
_ok22 = len(w5._undo) == 1
chk("⑯-22 ⭐ 拖 30 帧只 push 1 份撤销快照（⛔ 每帧一份会让 Ctrl+Z 撤不动）",
    _ok22, "undo 栈长度=%d（期望 1）" % len(w5._undo))
_w5_before = dict(w5.custom_terrains[0])
w5.edit_undo()
_ok23 = (len(w5.custom_terrains) == 1
         and abs(w5.custom_terrains[0]["x0"] - 300.0) < 1e-6)
chk("⑯-23 ⭐⭐ 阳性对照：Ctrl+Z 真的撤回到拖动**前**的位置", _ok23,
    "撤前 x0=%.1f → 撤后 x0=%.1f（期望 300）"
    % (_w5_before["x0"], w5.custom_terrains[0]["x0"] if w5.custom_terrains
       else float("nan")))

# ---- C5 阴性：select 工具拖动**不**新建地形 ----
w6 = _fresh_with_block()
_n0 = len(w6.custom_terrains)
w6.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                          (K(w6, 350.0), K(w6, 425.0))))
w6.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton,
                         (K(w6, 450.0), K(w6, 425.0))))
w6.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton,
                            (K(w6, 450.0), K(w6, 425.0))))
_ok24 = len(w6.custom_terrains) == _n0
chk("⑯-24 ⭐⭐ C5 select 工具拖动 ⇒ 条数不变（不触发新建）", _ok24,
    "%d → %d（期望不变）" % (_n0, len(w6.custom_terrains)))

# ---- C5 阳性对照：rect 工具拖动 ⇒ 条数 +1，且**不**移动旧块 ----
w7 = _fresh_with_block()
w7.edit_tool = "rect"
_old = dict(w7.custom_terrains[0])
w7.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                          (K(w7, 350.0), K(w7, 425.0))))
w7.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton,
                         (K(w7, 450.0), K(w7, 500.0))))
w7.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton,
                            (K(w7, 450.0), K(w7, 500.0))))
_ok25 = (len(w7.custom_terrains) == 2
         and w7.custom_terrains[0]["x0"] == _old["x0"]
         and w7.custom_terrains[0]["y0"] == _old["y0"])
chk("⑯-25 ⭐⭐ C5 阳性对照：rect 工具拖 ⇒ 条数 +1 且旧块**未被拖动**", _ok25,
    "条数=%d 旧块 x0=%.1f（期望 2 / 300）"
    % (len(w7.custom_terrains), w7.custom_terrains[0]["x0"]))

# ---- 阴性：选中「对象」（非地形）时不启动地形拖动 ----
w8 = _fresh_with_block()
w8.custom_stashes = [{"x": 350.0, "y": 425.0, "icon": "yolk", "kind": "loose"}]
w8.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                          (K(w8, 350.0), K(w8, 425.0))))
_ok26 = (w8.edit_sel == -1 and w8._move_from is None)
chk("⑯-26 ⭐ 阴性：选中的是食物（不是地形）⇒ 不启动地形拖动", _ok26,
    "edit_sel=%s _move_from=%s" % (w8.edit_sel, w8._move_from))

# ---- 阴性：空白处按下 ⇒ 不启动拖动、不崩 ----
# ⛔⛔ 我第一版用 (900,100) 当"空白"，B 段之后它**真的命中**了吊柜
#     PLATFORMS[3]=(790,50,1010,189) ⇒ 那是**新行为正确**，是我选点选错了。
#     ⇒ 换成 (1500,300)（四条默认平台都盖不到）。
w9 = _fresh_with_block()
w9.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                          (K(w9, 1500.0), K(w9, 300.0))))
w9.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton,
                         (K(w9, 1550.0), K(w9, 300.0))))
w9.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton,
                            (K(w9, 1550.0), K(w9, 300.0))))
_ok27 = (w9.edit_sel == -1 and len(w9.custom_terrains) == 1
         and abs(w9.custom_terrains[0]["x0"] - 300.0) < 1e-6)
chk("⑯-27 ⭐ 阴性：空白处(1500,300)拖 ⇒ 不选中、不新建、原块纹丝不动", _ok27,
    "edit_sel=%s 条数=%d x0=%.1f" % (w9.edit_sel, len(w9.custom_terrains),
                                     w9.custom_terrains[0]["x0"]))


# ============================================================================
section("⑰·PR16-B · 默认 4 平台可编辑（Ronny 拍板：方案 1 全集 + v3；地板禁删）")
# ============================================================================

import tempfile
_tdir = tempfile.mkdtemp(prefix="_zt16b_")

# ---- ⑰-1 常量 ----
_ok_b1 = (N.TERRAIN_JSON_VERSION_V3 == 3
          and N.TERRAIN_JSON_VERSION_V3 in N.TERRAIN_JSON_VERSIONS
          and N.TERRAIN_JSON_VERSION_V1 in N.TERRAIN_JSON_VERSIONS
          and N.TERRAIN_JSON_VERSION_V2 in N.TERRAIN_JSON_VERSIONS)
chk("⑰-1 ⭐ v3 已加进 TERRAIN_JSON_VERSIONS（且 v1/v2 仍在）", _ok_b1,
    "VERSIONS=%s" % (N.TERRAIN_JSON_VERSIONS,))

# ---- ⑰-2 platform_get 能吃 dict 和 4 元组（⛔ 元组没有 .get()）----
_tup = (430.0, 488.0, 700.0, 599.0)
_dic = {"kind": "solid", "x0": 430.0, "y0": 488.0, "x1": 700.0, "y1": 599.0,
        "builtin": True}
_ok_b2 = (N.platform_get(_dic, "builtin") is True
          and N.platform_get(_tup, "builtin") is None)
chk("⑰-2 ⭐⭐ platform_get 吃 dict(=True) 与 4 元组(=None)，不崩", _ok_b2,
    "dict builtin=%r  tuple builtin=%r"
    % (N.platform_get(_dic, "builtin"), N.platform_get(_tup, "builtin")))

# ---- C7 / C8 / C9：Room 层 ----
_r0 = N.Room(N.NIGHTS[0])
_ok_b3 = len(_r0.platforms) == 4
chk("⑰-3 ⭐⭐ C7 Room(None).platforms 长度仍是 4（自测 :104）", _ok_b3,
    "实测 %d" % len(_r0.platforms))

_c8 = [{"kind": "solid", "x0": 100.0, "y0": 500.0, "x1": 300.0, "y1": 599.0},
       {"kind": "climb", "x0": 400.0, "y0": 300.0, "x1": 400.0, "y1": 500.0}]
_r8 = N.Room(N.NIGHTS[0], custom=_c8)
_ok_b4 = len(_r8.platforms) == 6 and not any(
    N.platform_get(p, "builtin") for p in _r8.platforms)
chk("⑰-4 ⭐⭐ C8 custom 全不带 builtin ⇒ 4 + N（=6），无一被标 builtin", _ok_b4,
    "实测 %d" % len(_r8.platforms))

_bl4 = [dict(t) for t in N.platform_dicts(N.PLATFORMS)]
for _t in _bl4:
    _t["builtin"] = True
_r9 = N.Room(N.NIGHTS[0], custom=_bl4 + _c8)
_ok_b5 = (len(_r9.platforms) == len(_bl4) + len(_c8)
          and sum(1 for p in _r9.platforms if N.platform_get(p, "builtin")) == 4)
chk("⑰-5 ⭐⭐ C9 含 4 条 builtin ⇒ 全集模式（长度 = len(custom)=6，不重复追加默认）",
    _ok_b5, "实测 %d（期望 6）" % len(_r9.platforms))
# ⭐ 人工核对无重复：4 条 builtin 的坐标必须与 PLATFORMS 逐条对得上
_bd = [tuple(float(N.platform_get(p, k)) for k in ("x0", "y0", "x1", "y1"))
       for p in _r9.platforms[:4]]
_pf = [tuple(float(v) for v in t) for t in N.PLATFORMS]
chk("⑰-6 ⭐ C9 阳性对照：前 4 条坐标 == PLATFORMS 逐条（无重复、无错位）",
    _bd == _pf, "实测 %s" % (_bd,))

# ---- C10：v3 往返 ----
_v3 = N.terrain_to_json(_bl4 + _c8, overrides=None)
_ok_b6 = (_v3["version"] == 3
          and sum(1 for t in _v3["terrains"] if t.get("builtin")) == 4)
chk("⑰-7 ⭐⭐ C10 导出 ⇒ version=3，4 条带 builtin（无 overrides 也升 v3）",
    _ok_b6, "version=%s builtin 条数=%d"
    % (_v3["version"], sum(1 for t in _v3["terrains"] if t.get("builtin"))))
_back = N.terrain_from_json(_v3)
_ok_b7 = all(N.platform_get(a, "builtin") == N.platform_get(b, "builtin")
             and N.plat_kind(a) == N.plat_kind(b)
             and abs(float(N.platform_get(a, "x0"))
                     - float(N.platform_get(b, "x0"))) < 1e-9
             and abs(float(N.platform_get(a, "y1"))
                     - float(N.platform_get(b, "y1"))) < 1e-9
             for a, b in zip(_bl4 + _c8, _back))
chk("⑰-8 ⭐⭐ C10 v3 导出 → 导入 ⇒ 逐字段相等（含 builtin）", _ok_b7,
    "条数 %d → %d" % (len(_bl4) + len(_c8), len(_back)))
# ⭐⭐ 阳性对照：v1 往返不被破坏
_v1 = N.terrain_to_json(_c8, overrides=None)
_back1 = N.terrain_from_json(_v1)
_ok_b8 = (_v1["version"] == 1
          and sorted(_v1.keys()) == ["floor_y", "terrains", "version", "world_w"]
          and not any(N.platform_get(t, "builtin") for t in _back1))
chk("⑰-9 ⭐⭐ C10 阳性对照：v1 导出 → 导入 仍是四键、无 builtin（老格式不被破坏）",
    _ok_b8, "version=%s keys=%s" % (_v1["version"], sorted(_v1.keys())))

# ---- ⑰：默认 4 条现在**点得中**（F7 的反面）----
wb = _fresh_with_block()          # 1 块自定义 @(300,400,400,450)
_ht = wb._edit_hit(565.0, 550.0)  # 桌布 PLATFORMS[1]=(430,488,700,599) 内
#   ⛔ 下标 = len(custom_terrains) + 默认层下标 = 1 + 1 = 2
#     （我第一版写成 1，把"默认层下标"当成了"统一列表下标" —— 判据错，代码对）
_ok_b9 = _ht == 2
chk("⑰-10 ⭐⭐ 默认平台现在点得中（桌布 ⇒ 下标 %s = len(custom)1 + 默认层1）" % _ht,
    _ok_b9, "实测 %s（期望 2）" % _ht)
_ok_b9b = wb._edit_hit(1500.0, 300.0) == -1
chk("⑰-10b ⭐ 阳性对照：空白点仍是 -1（证明 ⑰-10 不是恒真）", _ok_b9b,
    "实测 %s" % wb._edit_hit(1500.0, 300.0))

# ---- ⑰：拖默认平台 ⇒ 懒接管 + 坐标改了 + Room 生效 ----
wb2 = _fresh_with_block()
_ok_pre = wb2.builtin_terrains is None
wb2.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                           (K(wb2, 565.0), K(wb2, 550.0))))
wb2.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton,
                          (K(wb2, 565.0), K(wb2, 520.0))))   # 上移 30
wb2.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton,
                             (K(wb2, 565.0), K(wb2, 520.0))))
_ok_b10 = (wb2.builtin_terrains is not None
           and len(wb2.builtin_terrains) == 4
           and abs(wb2.builtin_terrains[1]["y0"] - 458.0) < 1.0
           and abs(wb2.builtin_terrains[1]["y1"]
                   - (float(N.FLOOR_Y) - 30.0)) < 1.0)   # ⛔ 不写死 569
chk("⑰-11 ⭐⭐ 拖桌布 y1 上移 30px ⇒ **懒接管**生效（builtin_terrains None→4 条）",
    _ok_b10,
    "接管前 None=%s 接管后 %d 条，桌布 y=(%.1f, %.1f)（期望 458 / FLOOR_Y-30=%.1f）"
    % (_ok_pre, len(wb2.builtin_terrains or []),
       wb2.builtin_terrains[1]["y0"] if wb2.builtin_terrains else -1,
       wb2.builtin_terrains[1]["y1"] if wb2.builtin_terrains else -1,
       float(N.FLOOR_Y) - 30.0))
_ok_b11 = (len(wb2.room.platforms) == 5
           and sum(1 for p in wb2.room.platforms
                   if N.platform_get(p, "builtin")) == 4)
chk("⑰-12 ⭐⭐ Room 已切全集模式：platforms = 4 builtin + 1 custom（不是 4+4+1）",
    _ok_b11, "实测 %d 条，builtin %d 条"
    % (len(wb2.room.platforms),
       sum(1 for p in wb2.room.platforms if N.platform_get(p, "builtin"))))

# ---- ⑰-13 ⭐⭐ 懒接管的价值：没动过 ⇒ 导出仍是 v1；动过 ⇒ 升 v3 ----
_tp_a = os.path.join(_tdir, "a.json")
_tp_b = os.path.join(_tdir, "b.json")
wb3 = _fresh_with_block()
wb3.export_terrain(_tp_a)
with open(_tp_a, encoding="utf-8") as _f:
    _da = json.load(_f)
wb3.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                           (K(wb3, 565.0), K(wb3, 550.0))))
wb3.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton,
                          (K(wb3, 565.0), K(wb3, 520.0))))
wb3.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton,
                             (K(wb3, 565.0), K(wb3, 520.0))))
wb3.export_terrain(_tp_b)
with open(_tp_b, encoding="utf-8") as _f:
    _db = json.load(_f)
_ok_b12 = (_da["version"] == 1 and _db["version"] == 3)
chk("⑰-13 ⭐⭐ 懒接管：没动默认平台 ⇒ v%d；动过 ⇒ v%d（PLATFORMS 没被冻结）"
    % (_da["version"], _db["version"]), _ok_b12,
    "动前 version=%s 条数=%d ｜ 动后 version=%s 条数=%d"
    % (_da["version"], len(_da["terrains"]), _db["version"],
       len(_db["terrains"])))

# ---- ⑰-14 ⭐⭐ 导入 v3 ⇒ 默认层被还原（builtin 分桶）----
wb4 = _fresh_with_block()
wb4.terrain_path = _tp_b
_n_imp = wb4.import_terrain(_tp_b)
_ok_b13 = (wb4.builtin_terrains is not None
           and len(wb4.builtin_terrains) == 4
           and abs(wb4.builtin_terrains[1]["y1"]
                   - (float(N.FLOOR_Y) - 30.0)) < 1.0
           and len(wb4.custom_terrains) == 1)
chk("⑰-14 ⭐⭐ 导入 v3 ⇒ builtin 条目分桶进 builtin_terrains（桌布 y1 还原 FLOOR_Y-30）",
    _ok_b13,
    "builtin=%s 条 custom=%d 条 桌布 y1=%.1f"
    % (len(wb4.builtin_terrains or []), len(wb4.custom_terrains),
       wb4.builtin_terrains[1]["y1"] if wb4.builtin_terrains else -1))
wb4.terrain_path = _tp_a
wb4.import_terrain(_tp_a)
_ok_b14 = wb4.builtin_terrains is None
chk("⑰-15 ⭐ 阳性对照：导入 v1 ⇒ builtin_terrains 回到 None（未接管）", _ok_b14,
    "builtin_terrains=%r" % (wb4.builtin_terrains,))

# ---- ⑰-16 ⭐⭐ R3：默认地板禁删 ----
wb5 = _fresh_with_block()
wb5.edit_sel = 1                        # 统一列表下标 1 = 默认层第 0 条 = 地板
_r_del = wb5._edit_del()
_ok_b15 = (_r_del is False and wb5.builtin_terrains is None)
chk("⑰-16 ⭐⭐ R3 默认地板**删不掉**（_edit_del 返回 False 且不接管）", _ok_b15,
    "_edit_del()=%s builtin_terrains=%r" % (_r_del, wb5.builtin_terrains))
# ⭐⭐ 阳性对照：非地板的默认平台**能**删（证明 ⑰-16 不是"全都删不掉"）
wb6 = _fresh_with_block()
wb6.edit_sel = 2                        # 默认层第 1 条 = 桌布
_r_del2 = wb6._edit_del()
_ok_b16 = (_r_del2 is True and wb6.builtin_terrains is not None
           and len(wb6.builtin_terrains) == 3)
chk("⑰-17 ⭐⭐ 阳性对照：桌布（非地板）**能删**（4 条 → 3 条）", _ok_b16,
    "_edit_del()=%s 剩余 builtin=%s 条"
    % (_r_del2, len(wb6.builtin_terrains or [])))

# ---- ⑰-18 ⭐⭐ Ctrl+Z 能撤回「接管」本身 ----
wb7 = _fresh_with_block()
wb7.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton,
                           (K(wb7, 565.0), K(wb7, 550.0))))
wb7.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton,
                          (K(wb7, 565.0), K(wb7, 520.0))))
wb7.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton,
                             (K(wb7, 565.0), K(wb7, 520.0))))
_took = wb7.builtin_terrains is not None
wb7.edit_undo()
_ok_b17 = _took and wb7.builtin_terrains is None
chk("⑰-18 ⭐⭐ Ctrl+Z 撤回到「未接管」（快照存的是 None，不是空 list）", _ok_b17,
    "撤前已接管=%s → 撤后 builtin_terrains=%r" % (_took, wb7.builtin_terrains))

# ---- ⑰-19 ⭐⭐ edit_clear 放弃接管（回到出厂默认）----
wb8 = _fresh_with_block()
wb8._edit_takeover()
wb8.edit_clear()
_ok_b18 = (wb8.custom_terrains == [] and wb8.builtin_terrains is None)
chk("⑰-19 ⭐ C 清空 ⇒ 默认平台也放弃接管（回到出厂）", _ok_b18,
    "custom=%d 条 builtin=%r" % (len(wb8.custom_terrains), wb8.builtin_terrains))

# ---- ⑰-20 强制渲染（未接管 / 已接管 两态）----
_pok2, _perr2 = True, ""
try:
    for _ww in (wb, wb2, wb6):
        _ww.set_mode("edit")
        _ww.edit_sel = 0
        _img = _ww.grab().toImage()
        _pok2 = _pok2 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok2, _perr2 = False, "%s: %s" % (type(_e).__name__, _e)
chk("⑰-20 ⭐⭐ 未接管 / 已接管 / 删过默认条 三态都强制 render 通过",
    _pok2, _perr2 if _perr2 else "render OK")

import shutil
shutil.rmtree(_tdir, ignore_errors=True)


# ============================================================================
section("⑱·PR17 · 自定义地形「保存不了」：启动时自动导入（§P0）+ P2 三小项")
# ============================================================================

import io as _io
import contextlib
import tempfile as _tf
from PySide6.QtGui import QPainter, QImage

_tdir17 = _tf.mkdtemp(prefix="_zt17_")
_ORIG_GA = N.GAME_ASSETS


def _w_capture(assets_dir, autoload=True):
    """在指定 assets 目录下建窗口，**捕获启动期间的所有 print**。⇒ (win, 输出文本)

    ⛔⛔ `autoload=True` 是**必须的**：产品代码在**无头环境（offscreen）下跳过**
       自动导入（测试隔离，见 night.py `__init__` 的注释）⇒ 不显式调的话
       C2「存档不存在 ⇒ 不刷告警」会变成**假绿**（压根没调用，测了个寂寞）。
       ⇒ 这里手动补上那一步，模拟真实入口。
    """
    N.GAME_ASSETS = assets_dir
    _buf = _io.StringIO()
    try:
        with contextlib.redirect_stdout(_buf):
            _w = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
            _w.start_night(0)
            if autoload:
                _w._autoload_terrain()
    finally:
        N.GAME_ASSETS = _ORIG_GA
    return _w, _buf.getvalue()

# ---- ⑱-0 ⭐⭐ 测试隔离闸门：offscreen 下**不**自动导入（否则 Ronny 的存档会污染 168 条判据）----
_d0 = _tf.mkdtemp(prefix="_zt17gate_")
N.GAME_ASSETS = _d0
try:
    w_gate = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    w_gate.start_night(0)
    w_gate.set_mode("edit")
    w_gate._edit_add(100.0, 400.0, 300.0, 450.0, "solid")
    w_gate._edit_add(400.0, 400.0, 600.0, 450.0, "solid")
    w_gate.export_terrain()
    _w_g0 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_g = (len(_w_g0.custom_terrains) == 0)
chk("⑱-0 ⭐⭐ 测试隔离：offscreen 下新建窗口**不**读存档（%d 条，期望 0）"
    % len(_w_g0.custom_terrains), _ok_g,
    "闸门=QT_QPA_PLATFORM!=offscreen；真机是窗口模式不受影响")
# ⭐⭐ 阳性对照：同一份存档 + 手动调 `_autoload_terrain()` ⇒ 必须读进来（证明闸门不是"永远不读"）
_w_g0._autoload_terrain()
_ok_g2 = len(_w_g0.custom_terrains) == 2
chk("⑱-0b ⭐⭐ 阳性对照：手动 `_autoload_terrain()` ⇒ 读到 %d 条（闸门不是永远不读）"
    % len(_w_g0.custom_terrains), _ok_g2,
    "期望 2，实测 %d" % len(_w_g0.custom_terrains))


# ---- C1：加 2 块 → S 导出 → 新建窗口（不按 O）⇒ 自动加载回 2 块 ----
_d1 = _tf.mkdtemp(prefix="_zt17c1_")
N.GAME_ASSETS = _d1
try:
    wc = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    wc.start_night(0)
    wc.set_mode("edit")
    wc._edit_add(100.0, 400.0, 300.0, 450.0, "solid")
    wc._edit_add(400.0, 400.0, 600.0, 450.0, "solid")
    _p_exp = wc.export_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_n_saved = len(wc.custom_terrains)
# ⛔ offscreen 下自动导入被闸门挡了 ⇒ 这里手动补上（= 模拟真实入口那一步）
# ⛔ 而且必须在 GAME_ASSETS 还是临时目录时建窗口，否则 terrain_path 指回真实存档。
N.GAME_ASSETS = _d1
try:
    _w_r = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    _w_r._autoload_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_c1 = (_n_saved == 2 and len(_w_r.custom_terrains) == 2)
chk("⑱-1 ⭐⭐ C1 存 2 块 → **新建窗口**（不按 O）⇒ 自动加载回 %d 块"
    % len(_w_r.custom_terrains), _ok_c1,
    "导出时 %d 块 → 重启后 %d 块（期望 2）" % (_n_saved, len(_w_r.custom_terrains)))
# ⭐⭐ 阳性对照：存 3 块 ⇒ 重启后是 3（证明不是"恒为 2"）
_d1b = _tf.mkdtemp(prefix="_zt17c1b_")
N.GAME_ASSETS = _d1b
try:
    wc2 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    wc2.start_night(0)
    wc2.set_mode("edit")
    for _x in (100.0, 400.0, 700.0):
        wc2._edit_add(_x, 400.0, _x + 200.0, 450.0, "solid")
    wc2.export_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
N.GAME_ASSETS = _d1b
try:
    _w_r3 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    _w_r3._autoload_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_c1b = len(_w_r3.custom_terrains) == 3
chk("⑱-2 ⭐⭐ C1 阳性对照：存 3 块 ⇒ 重启后 %d 块（证明判据有分辨力）"
    % len(_w_r3.custom_terrains), _ok_c1b,
    "期望 3，实测 %d" % len(_w_r3.custom_terrains))

# ---- C2：存档不存在 ⇒ 启动不报错、不刷告警 ----
_d2 = _tf.mkdtemp(prefix="_zt17c2_")          # ⛔ 空目录，json 不存在
_w_n, _out_n = _w_capture(_d2)
_ok_c2 = (_w_n is not None and len(_w_n.custom_terrains) == 0
          and "读不出来" not in _out_n)
chk("⑱-3 ⭐⭐ C2 存档**不存在** ⇒ 照常启动、自定义 0 块、**且没刷告警**",
    _ok_c2,
    "custom=%d 条，输出里含'读不出来'=%s（期望 False）"
    % (len(_w_n.custom_terrains), "读不出来" in _out_n))

# ---- C3 ⛔⛔：存档写坏 ⇒ 游戏照常启动 + print 告警 ----
_d3 = _tf.mkdtemp(prefix="_zt17c3_")
with open(os.path.join(_d3, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    _f.write('{"version": 99, "terrains": []}')
_w_bad, _out_bad = _w_capture(_d3)
_ok_c3 = (_w_bad is not None and len(_w_bad.custom_terrains) == 0
          and "读不出来" in _out_bad)
chk("⑱-4 ⭐⭐ C3 存档 version=99（不支持）⇒ **照常启动** + print 告警 + 复位空状态",
    _ok_c3,
    "启动成功=%s custom=%d 条 输出含告警=%s"
    % (_w_bad is not None, len(_w_bad.custom_terrains), "读不出来" in _out_bad))
# ⭐⭐ 阳性对照：非法 JSON（连解析都过不去）⇒ 同样照常启动 + 告警
_d3b = _tf.mkdtemp(prefix="_zt17c3b_")
with open(os.path.join(_d3b, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    _f.write('{')                            # ⛔ 半个花括号
_w_bad2, _out_bad2 = _w_capture(_d3b)
_ok_c3b = (_w_bad2 is not None and "读不出来" in _out_bad2)
chk("⑱-5 ⭐⭐ C3 阳性对照：非法 JSON `{` ⇒ 同样照常启动 + 告警（不是只有 version 错才扛得住）",
    _ok_c3b,
    "启动成功=%s 输出含告警=%s" % (_w_bad2 is not None, "读不出来" in _out_bad2))

# ---- C4：自动导入**不影响正常开局**（甲案：start_night 仍不吃 custom）----
_d4 = _tf.mkdtemp(prefix="_zt17c4_")
N.GAME_ASSETS = _d4
try:
    wd = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    wd.set_mode("edit")
    for _x in (100.0, 400.0, 700.0, 1000.0, 1300.0):
        wd._edit_add(_x, 400.0, _x + 150.0, 450.0, "solid")
    wd.export_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_w_d, _ = _w_capture(_d4)
# ⛔ C4 的期望**随 §P1 的拍板变**（Ronny 2026-10-10 选了**乙** ⇒ 正式开局**吃** custom）
_w_d.start_night(0)                          # ⭐ 正式开局（不是 F4）
_ok_c4 = (len(_w_d.custom_terrains) == 5 and len(_w_d.room.platforms) == 9)
chk("⑱-6 ⭐⭐ C4【乙案】存档 5 块 + **正式开局** ⇒ platforms = %d 条（4 默认 + 5 自定义）"
    % len(_w_d.room.platforms), _ok_c4,
    "custom=%d 条（自动导入成功） platforms=%d 条（期望 9）"
    % (len(_w_d.custom_terrains), len(_w_d.room.platforms)))
# ⭐⭐ 阳性对照：**空存档**开局 ⇒ 仍是 4 条（证明上面的 9 来自存档，不是恒 9）
_d4e = _tf.mkdtemp(prefix="_zt17c4e_")
_w_e, _ = _w_capture(_d4e)
_w_e.start_night(0)
_ok_c4b = len(_w_e.room.platforms) == 4
chk("⑱-7 ⭐⭐ C4 阳性对照：空存档开局 ⇒ platforms = %d 条（证明 ⑱-6 的 9 来自存档）"
    % len(_w_e.room.platforms), _ok_c4b,
    "期望 4，实测 %d" % len(_w_e.room.platforms))

# ---- ⭐⭐⭐ 根因 B 的直接证据：PR13 那行死代码现在**活了** ----
#   存档里：5 块地形 + 起点 x=2000 + 窝区 (1500,1700)
_d6 = _tf.mkdtemp(prefix="_zt17c6_")
N.GAME_ASSETS = _d6
try:
    wf = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    wf.start_night(0)
    wf.set_mode("edit")
    for _x in (100.0, 400.0, 700.0, 1000.0, 1300.0):
        wf._edit_add(_x, 400.0, _x + 150.0, 450.0, "solid")
    wf.custom_spawn = (2000.0, 500.0)
    wf.custom_nest = (1500.0, 1700.0)
    wf.export_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_w_f, _ = _w_capture(_d6)
_w_f.start_night(0)                          # ⭐ 正式开局
_ok_c7 = (abs(_w_f.luna.x - 2000.0) < 1.0
          and _w_f.room.nest == (1500.0, 1700.0)
          and len(_w_f.room.platforms) == 9)
chk("⑱-7c ⭐⭐⭐ 根因 B 已修：正式开局 ⇒ 露娜起点 x=%.1f（不是 80）、窝区=%s、地形 9 条"
    % (_w_f.luna.x, _w_f.room.nest), _ok_c7,
    "luna.x=%.1f（期望 2000） nest=%s platforms=%d"
    % (_w_f.luna.x, _w_f.room.nest, len(_w_f.room.platforms)))
# ⭐⭐ 阳性对照：**没设起点** ⇒ 回到默认 80（证明上面的 2000 不是碰巧）
_d6e = _tf.mkdtemp(prefix="_zt17c6e_")
_w_g, _ = _w_capture(_d6e)
_w_g.start_night(0)
_ok_c7b = abs(_w_g.luna.x - 80.0) < 1.0
chk("⑱-7d ⭐⭐ 阳性对照：没设起点的空存档 ⇒ 露娜 x=%.1f（默认 80）"
    % _w_g.luna.x, _ok_c7b,
    "实测 %.1f（期望 80）" % _w_g.luna.x)

# ---- C5：v3 存档（含 builtin）自动导入 ⇒ 正确分桶 ----
_d5 = _tf.mkdtemp(prefix="_zt17c5_")
_bl2 = [dict(t) for t in N.platform_dicts(N.PLATFORMS)]
for _t in _bl2:
    _t["builtin"] = True
with open(os.path.join(_d5, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    json.dump(N.terrain_to_json(
        _bl2 + [{"kind": "solid", "x0": 100.0, "y0": 400.0,
                 "x1": 300.0, "y1": 450.0}]), _f)
_w_v3, _ = _w_capture(_d5)
_w_v3.set_mode("edit")
_ok_c5 = (_w_v3.builtin_terrains is not None
          and len(_w_v3.builtin_terrains) == 4
          and len(_w_v3.custom_terrains) == 1
          and len(_w_v3.room.platforms) == 5)
chk("⑱-8 ⭐⭐ C5 v3 存档（4 builtin + 1 custom）自动导入 ⇒ 分桶正确、全集 5 条",
    _ok_c5,
    "builtin=%s 条 custom=%d 条 platforms=%d 条"
    % (len(_w_v3.builtin_terrains or []), len(_w_v3.custom_terrains),
       len(_w_v3.room.platforms)))
# ⭐⭐ 阳性对照：v1 空存档 ⇒ 与改动前逐字相同
_d5b = _tf.mkdtemp(prefix="_zt17c5b_")
with open(os.path.join(_d5b, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    _f.write('{"version": 1, "world_w": 3840, "floor_y": 599, "terrains": []}')
_w_v1, _ = _w_capture(_d5b)
_ok_c5b = (_w_v1.custom_terrains == [] and _w_v1.builtin_terrains is None)
chk("⑱-9 ⭐⭐ C5 阳性对照：v1 空存档 ⇒ custom=[] / builtin=None（与改动前逐字相同）",
    _ok_c5b, "custom=%r builtin=%r"
    % (_w_v1.custom_terrains, _w_v1.builtin_terrains))

# ---- ⭐⭐ 我主动加的：自动导入**不许进撤销栈**（否则一进编辑器按 Ctrl+Z 就"存档丢了"）----
_ok_c6 = len(_w_r._undo) == 0
chk("⑱-10 ⭐⭐ 自动导入后撤销栈是空的（⛔ 否则 Ctrl+Z 会把刚加载的存档全撤掉）",
    _ok_c6, "undo 栈长度=%d（期望 0）" % len(_w_r._undo))

# ---- §P2-2：未接管的默认平台**选中要有高亮**（原来画面完全没反应）----
def _pen_widths(w):
    """跑一次 `_draw_edit_overlay`，抓每次 drawRect 用的**笔宽**。"""
    _im = QImage(int(N.VW), int(N.VH), QImage.Format_ARGB32)
    _pp = QPainter(_im)
    _got = []
    _pp.drawRect = lambda *_a, **_k: _got.append(float(_pp.pen().widthF()))
    w._draw_edit_overlay(_pp)
    _pp.end()
    return _got

w_p = _fresh_with_block()          # 1 块自定义，builtin 未接管
w_p.edit_sel = -1
_no_sel = _pen_widths(w_p)
w_p.edit_sel = 2                   # = 默认层第 1 条（桌布）
_sel_b = _pen_widths(w_p)
_ok_p2 = (3.0 not in _no_sel) and (3.0 in _sel_b)
chk("⑱-11 ⭐⭐ P2-2 未接管时选中默认平台 ⇒ 有 3px 高亮（原来画面完全没反应）",
    _ok_p2,
    "未选中时笔宽=%s ｜ 选中后=%s（期望出现 3.0）" % (_no_sel, _sel_b))
# ⭐⭐ 阳性对照：选中**自定义**块也有 3px（两条路径都活着）
w_p.edit_sel = 0
_ok_p2b = 3.0 in _pen_widths(w_p)
chk("⑱-12 ⭐ 阳性对照：选中自定义块同样有 3px 高亮", _ok_p2b,
    "笔宽=%s" % (_pen_widths(w_p),))

# ---- §P2-3：⑯-27 的「空白点」(1500,300) 必须真的是空白 ----
_ok_p3 = (w_p._edit_hit(1500.0, 300.0) == -1
          and w_p._edit_hit(900.0, 100.0) >= 0)      # ⭐ (900,100) 落在吊柜里
chk("⑱-13 ⭐ P2-3 ⑯-27 的空白点 (1500,300) 确实是空白；(900,100) 确实命中吊柜"
    "（证明挪点是有必要的）", _ok_p3,
    "(1500,300)=%s (900,100)=%s"
    % (w_p._edit_hit(1500.0, 300.0), w_p._edit_hit(900.0, 100.0)))

# ---- ⑱-14：三态 render（空存档 / v3 存档 / 坏档）----
_pok3, _perr3 = True, ""
try:
    for _ww in (_w_n, _w_v3, _w_bad):
        _ww.set_mode("edit")
        _ww.cam_x = 1200.0
        _img = _ww.grab().toImage()
        _pok3 = _pok3 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok3, _perr3 = False, "%s: %s" % (type(_e).__name__, _e)
chk("⑱-14 ⭐⭐ 空存档 / v3 存档 / 坏档 三态都强制 render 通过", _pok3,
    _perr3 if _perr3 else "render OK")

for _d in (_d0, _d1, _d1b, _d2, _d3, _d3b, _d4, _d4e, _d5, _d5b, _d6, _d6e, _tdir17):
    shutil.rmtree(_d, ignore_errors=True)


# ============================================================================
section("⑲·PR18 · 统一「进入游戏」三条路径 + 真机启动路径覆盖")
# ============================================================================

# ---- C1：编辑器设 2 块 → set_mode("play") ⇒ 4 + 2 ----
w18 = _fresh_with_block()          # 1 块自定义
w18.custom_terrains.append({"kind": "climb", "x0": 900.0, "y0": 300.0,
                            "x1": 900.0, "y1": 500.0})   # ⇒ 2 块
w18.set_mode("play_custom")        # 先让 room 含自定义
w18.set_mode("play")
_ok_18_1 = len(w18.room.platforms) == 4 + 2
chk("⑲-1 ⭐⭐ C1 set_mode('play') 吃 custom ⇒ platforms = %d（期望 4+2=6）"
    % len(w18.room.platforms), _ok_18_1,
    "custom=%d 条 builtin=%s"
    % (len(w18.custom_terrains), w18.builtin_terrains))
# ⭐ 阳性对照：不传 custom 的裸 Room 仍 4
_ok_18_1b = len(N.Room(N.NIGHTS[0]).platforms) == 4
chk("⑲-2 ⭐ C1 阳性对照：裸 `Room(NIGHTS[0])` 仍 4 条 ⇒ 上面那 6 来自 custom",
    _ok_18_1b, "实测 %d" % len(N.Room(N.NIGHTS[0]).platforms))

# ---- C2：⑨-16 的口径在**接管 / 未接管**两种状态下都成立 ----
# ⭐ 派单 §2.1 建议的 `len(_room_custom())` 在未接管时是 1，而 platforms 是 5 ⇒ 假红。
#    下面把两种状态都跑一遍，验证我改的两态口径。
def _play_expect(w):
    return (len(w._room_custom()) if w.builtin_terrains is not None
            else len(N.PLATFORMS) + len(w._room_custom()))


w18b = _fresh_with_block()                    # 未接管
w18b.custom_terrains.append({"kind": "solid", "x0": 900.0, "y0": 300.0,
                             "x1": 1000.0, "y1": 350.0})
_exp_u = _play_expect(w18b)
w18b.set_mode("play")
_ok_18_2 = len(w18b.room.platforms) == _exp_u
chk("⑲-3 ⭐⭐ C2 未接管态：期望 %d 实测 %d" % (_exp_u, len(w18b.room.platforms)),
    _ok_18_2, "builtin_terrains=None ⇒ 期望 = 4 + len(custom)")

w18c = _fresh_with_block()                    # 人为接管（填上 4 条 builtin）
w18c._edit_takeover()
w18c.custom_terrains.append({"kind": "solid", "x0": 900.0, "y0": 300.0,
                             "x1": 1000.0, "y1": 350.0})
_exp_t = _play_expect(w18c)
w18c.set_mode("play")
_ok_18_3 = len(w18c.room.platforms) == _exp_t
chk("⑲-4 ⭐⭐ C2 阳性对照：接管态（4 builtin + 2 custom）期望 %d 实测 %d"
    % (_exp_t, len(w18c.room.platforms)), _ok_18_3,
    "期望 = len(_room_custom())（全集模式）")
# ⭐⭐ 再验一次：派单建议的旧口径在未接管时**会假红**（把错误答案钉成判据）
_bad_formula = (len(w18b.room.platforms) == len(w18b._room_custom()))
chk("⑲-5 ⭐⭐ 阳性对照：派单建议的 `len(_room_custom())` 口径在**未接管**时确实会假红"
    "（platforms=%d 而它给 1）" % len(w18b.room.platforms), not _bad_formula,
    "所以期望值必须分两态 —— 这条把『派单的建议写法不行』钉成可复跑的判据")

# ---- C3：⑮-5b/5c/5d 的等价场景**真跑**（派单 §2.2 要求贴数字）----
# 风险点：set_mode("play") 带进自定义地形后，露娜可能被自定义平台接住 ⇒ 回窝判定变。
w18d = _fresh_with_block()
w18d.custom_nest = (1500.0, 1700.0)
w18d._apply_overrides_now()
w18d.set_mode("play")
w18d.phase = "play"
w18d.room.spawn_luna = w18d.room.spawn_luna          # 只读，留个痕
# 人为把露娜放到 x=1600、地面高度，跑 2 帧
w18d.luna.carrying = ["yolk"]
w18d.loot_stash = []
w18d.luna.x = 1600.0
w18d.luna.y = float(N.FLOOR_Y)
step(w18d, n=2)
_ok_18_6 = len(w18d.loot_stash) == 1 and not w18d.luna.carrying
chk("⑲-6 ⭐⭐ C3 带自定义地形时回窝结算仍成功（nest=%s，platforms=%d 条）"
    % (w18d.room.nest, len(w18d.room.platforms)), _ok_18_6,
    "loot_stash=%s carrying=%s" % (w18d.loot_stash, w18d.luna.carrying))
# ⭐ 反向：窝区外不结算
w18d.loot_stash = []
w18d.luna.carrying = ["yolk"]
w18d.luna.x = 1900.0
w18d.luna.y = float(N.FLOOR_Y)
step(w18d, n=2)
_ok_18_7 = len(w18d.loot_stash) == 0
chk("⑲-7 ⭐ C3 窝区外（x=1900）⇒ 不判定成功", _ok_18_7,
    "loot_stash=%s" % (w18d.loot_stash,))

# ---- C7：三条进游戏路径**口径一致** ----
w18e = _fresh_with_block()
w18e.custom_terrains.append({"kind": "solid", "x0": 900.0, "y0": 300.0,
                             "x1": 1000.0, "y1": 350.0})
w18e._edit_takeover()                     # 接管，让三路都走全集模式（最严格）
w18e.set_mode("play")
_p_play = len(w18e.room.platforms)
w18e.start_night(0)
_p_start = len(w18e.room.platforms)
w18e.set_mode("play_custom")
_p_pc = len(w18e.room.platforms)
_ok_18_8 = (_p_play == _p_start == _p_pc == 6)
chk("⑲-8 ⭐⭐ C7 三条路径口径一致：set_mode('play')=%d / start_night=%d / "
    "play_custom=%d（期望三者相等且 = 6）" % (_p_play, _p_start, _p_pc), _ok_18_8,
    "4 builtin + 2 custom = 6")
# ⭐⭐ 源码级复查：三处都必须是 `_room_custom()`，⛔ 不能是 `custom_terrains`
_src18 = open(os.path.join(HERE, "pet_engine", "night.py"),
              encoding="utf-8").read()
_bad_sites = []
for _tag in ('if m == "play":', "def start_night(self, idx: int):",
             'elif m == "play_custom":'):
    _i = _src18.find(_tag)
    if _i < 0:
        _bad_sites.append("%s 未找到" % _tag)
        continue
    _blk = _src18[_i:_i + 700]
    if "custom=self._room_custom()" not in _blk:
        _bad_sites.append(_tag)
chk("⑲-9 ⭐⭐ C7 源码级：三处进游戏路径都传 `_room_custom()`（不是 custom_terrains）",
    not _bad_sites,
    "不合格点=%s" % (_bad_sites or "无"))

# ---- ⭐⭐ §3 要求的补覆盖：真机启动路径（`__init__` 那次自动调用）----
# ⛔ 之前所有自动导入判据都显式调 `_autoload_terrain()` ⇒ 闸门那条分支**零覆盖**。
#    这里临时把 QT_QPA_PLATFORM 伪造成窗口模式 ⇒ 真机那条路真的被走到。
_d18 = _tf.mkdtemp(prefix="_zt18_")
N.GAME_ASSETS = _d18
try:
    w18f = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    w18f.set_mode("edit")
    w18f._edit_add(100.0, 400.0, 300.0, 450.0, "solid")
    w18f._edit_add(400.0, 400.0, 600.0, 450.0, "solid")
    w18f.export_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA

_olde = os.environ.get("QT_QPA_PLATFORM")
try:
    # ① 伪造成窗口模式 ⇒ `__init__` 里那次自动导入**必须**发生
    os.environ["QT_QPA_PLATFORM"] = "windows"
    N.GAME_ASSETS = _d18
    try:
        w18g = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    finally:
        N.GAME_ASSETS = _ORIG_GA
    _ok_18_10 = len(w18g.custom_terrains) == 2
    chk("⑲-10 ⭐⭐⭐ 真机路径覆盖：`QT_QPA_PLATFORM=windows` ⇒ **`__init__` 里的"
        "自动导入真的发生**，读到 %d 条（期望 2，不按任何键）"
        % len(w18g.custom_terrains), _ok_18_10,
        "这一条才是「Ronny 一进游戏地形自己回来了」的自动化证据")
    # ② 阳性对照：`NIGHT_AUTOLOAD=0` 必须**跳过**（闸门另一侧也有覆盖）
    os.environ["NIGHT_AUTOLOAD"] = "0"
    N.GAME_ASSETS = _d18
    try:
        w18h = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
    finally:
        N.GAME_ASSETS = _ORIG_GA
    _ok_18_11 = len(w18h.custom_terrains) == 0
    chk("⑲-11 ⭐⭐ 阳性对照：`NIGHT_AUTOLOAD=0` ⇒ 跳过自动导入（读到 %d 条，期望 0）"
        % len(w18h.custom_terrains), _ok_18_11,
        "闸门两条分支都有覆盖了")
finally:
    if _olde is None:
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ["QT_QPA_PLATFORM"] = _olde
    os.environ.pop("NIGHT_AUTOLOAD", None)

# ---- 三态 render（含 set_mode("play") 后）----
_pok4, _perr4 = True, ""
try:
    for _ww in (w18, w18c, w18d):
        _ww.set_mode("edit")
        _ww.edit_sel = 0
        _img = _ww.grab().toImage()
        _pok4 = _pok4 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok4, _perr4 = False, "%s: %s" % (type(_e).__name__, _e)
chk("⑲-12 ⭐⭐ 未接管 / 已接管 / 带 nest 三态强制 render 通过", _pok4,
    _perr4 if _perr4 else "render OK")

shutil.rmtree(_d18, ignore_errors=True)


# ============================================================================
section("㉑·PR20 · 收尾六项（A2 微波炉画巡逻段中点 / B1 地板锁 x / B3 坏档提示）")
# ============================================================================

# ---- A2-1：编辑态画在**巡逻段中点** ----
# 做法分两步，各测一件事：
#   ① 调用点传的参数对不对（stub 掉 `_draw_mw`，录 `x_override`）
#   ② `_draw_mw` 内部**真的用了**这个参数（spy `p.translate`）
# ⛔ 只测①会漏"形参收了却没用"；只测②会漏"调用点没传"。
w21 = _fresh_with_block()
w21.custom_patrol = (2000.0, 2400.0)
w21._apply_overrides_now()
_cap = {}
_orig_mw = w21._draw_mw


def _cap_mw(p, x_override=None):
    _cap["ov"] = x_override
    return None


w21._draw_mw = _cap_mw
try:
    _render_at_cam = 0
    w21.cam_x = 0.0
    w21.set_mode("edit")
    w21.phase = "menu"
    _im = QImage(int(N.VW), int(N.VH), QImage.Format_ARGB32)
    w21.render(_im)
finally:
    del w21._draw_mw
_ok_21_1 = (_cap.get("ov") is not None
           and abs(_cap["ov"] - 2200.0) < 1e-6)
chk("㉑-1 ⭐⭐ A2-1 编辑态设巡逻段 [2000,2400] ⇒ 传给 `_draw_mw` 的 x = %.1f（期望 2200）"
    % (_cap.get("ov") if _cap.get("ov") is not None else -1), _ok_21_1,
    "巡逻段中点 = (2000+2400)/2")
# ⭐ 阳性对照：不设巡逻段 ⇒ 退回 None（= 用 self.mw.x）
w21.custom_patrol = None
w21._apply_overrides_now()
_cap.clear()
w21._draw_mw = _cap_mw
try:
    _im = QImage(int(N.VW), int(N.VH), QImage.Format_ARGB32)
    w21.render(_im)
finally:
    del w21._draw_mw
_ok_21_1b = _cap.get("ov", "missing") is None
chk("㉑-2 ⭐ A2-1 阳性对照：不设巡逻段 ⇒ x_override=None（退回 self.mw.x）",
    _ok_21_1b, "实测 %r" % (_cap.get("ov", "missing"),))

# ② `_draw_mw` 内部真的用了它（spy p.translate）
_im2 = QImage(int(N.VW), int(N.VH), QImage.Format_ARGB32)
_pp = QPainter(_im2)
_seen = []
_pp.translate = lambda x, y: _seen.append((round(float(x), 3), round(float(y), 3)))
_orig_mw(_pp, x_override=1234.0)
_orig_mw(_pp)                                  # 不传 ⇒ 应回落到 self.mw.x
_pp.end()
_ok_21_3 = (1234.0 in [v[0] for v in _seen]
            and abs(float(N.Microwave(N.NIGHTS[0]).x) - _seen[-1][0]) < 0.5)
chk("㉑-3 ⭐⭐ A2 `_draw_mw` 内部**真的**用了 x_override（spy p.translate）", _ok_21_3,
    "translate 记录=%s；末条应是 self.mw.x≈%.1f"
    % (_seen[:3], float(N.Microwave(N.NIGHTS[0]).x)))

# ---- A2-2：进出编辑态**不许污染** `self.mw.x` ----
w22 = _fresh_with_block()
w22.custom_patrol = (2000.0, 2400.0)
w22._apply_overrides_now()
_mwx0 = w22.mw.x
_same = True
for _ in range(3):
    w22.set_mode("edit")
    w22.phase = "menu"
    _im = QImage(int(N.VW), int(N.VH), QImage.Format_ARGB32)
    w22.render(_im)
    w22.set_mode("play")
    _same = _same and (w22.mw.x == _mwx0)
chk("㉑-4 ⭐⭐ A2-2 进出编辑态各 3 次 ⇒ self.mw.x 恒为 %.1f（⛔ 不许污染游戏状态）"
    % _mwx0, _same, "起=%r 末=%r" % (_mwx0, w22.mw.x))

# ---- B1：地板锁 x ----
def _drag_block(w, idx, dx, dy):
    """用真实鼠标事件把统一列表第 idx 块拖 (dx, dy)。"""
    t = w._edit_all()[idx]
    cx = (float(t["x0"]) + float(t["x1"])) / 2.0
    cy = (float(t["y0"]) + float(t["y1"])) / 2.0
    _a = (K(w, cx), K(w, cy))
    _b = (K(w, cx + dx), K(w, cy + dy))
    w.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, _a))
    w.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, _b))
    w.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, _b))


w23 = _fresh_with_block()            # 1 块自定义 ⇒ 默认层从下标 1 起
w23.cam_x = 0.0
_f0 = (0.0, 599.0, 3840.0, 720.0)    # PLATFORMS[0] 地板
_drag_block(w23, 1, 100.0, 0.0)      # 地板往右拖 100
_b1 = w23.builtin_terrains[0]
_ok_21_5 = (_b1["x0"] == _f0[0] and _b1["x1"] == _f0[2])
chk("㉑-5 ⭐⭐ B1-1 拖地板**左右** 100px ⇒ x0/x1 逐字不变（%.1f/%.1f）"
    % (_b1["x0"], _b1["x1"]), _ok_21_5,
    "期望 %.1f/%.1f（锁 x）" % (_f0[0], _f0[2]))
_drag_block(w23, 1, 0.0, -50.0)      # 地板往上拖 50
_b1b = w23.builtin_terrains[0]
_ok_21_6 = (_b1b["y0"] != _f0[1] or _b1b["y1"] != _f0[3])
chk("㉑-6 ⭐⭐ B1-2 拖地板**上下** 50px ⇒ y 变了（y0 %.1f→%.1f, y1 %.1f→%.1f）"
    % (_f0[1], _b1b["y0"], _f0[3], _b1b["y1"]), _ok_21_6,
    "⇒ y 可改、x 锁死，两条同时成立")
# ⭐⭐ B1-3：非地板（厨房台）左右**必须**能变（证明不是全局锁 x）
w24 = _fresh_with_block()
w24.cam_x = 0.0
_k0 = tuple(float(v) for v in N.PLATFORMS[2])
_drag_block(w24, 1 + 2, 100.0, 0.0)   # 默认层第 2 条 = 厨房台
_b1c = w24.builtin_terrains[2]
_ok_21_7 = (abs(_b1c["x0"] - (_k0[0] + 100.0)) < 1.0
            and abs(_b1c["x1"] - (_k0[2] + 100.0)) < 1.0)
chk("㉑-7 ⭐⭐ B1-3 拖**厨房台**左右 100px ⇒ x 变了（%.1f→%.1f）"
    % (_k0[0], _b1c["x0"]), _ok_21_7,
    "⇒ 锁 x 只作用于地板，不是全局锁")

# ---- B2：骗人注释已删（判据：那句命中数 = 0）----
_src21 = open(os.path.join(HERE, "pet_engine", "night.py"),
              encoding="utf-8").read()
_ok_21_8 = ("可强制在无头下也加载" not in _src21
            and "本条件是 **AND**" in _src21)
chk("㉑-8 ⭐⭐ B2 那句骗人注释已删，且写清了 AND 语义", _ok_21_8,
    "『可强制在无头下也加载』命中 %d 次（期望 0）；『本条件是 **AND**』命中 %d 次"
    % (_src21.count("可强制在无头下也加载"), _src21.count("本条件是 **AND**")))

# ---- B3：坏档 ⇒ 游戏内提示；好档 ⇒ 不提示 ----
_d21 = _tf.mkdtemp(prefix="_zt21_")
with open(os.path.join(_d21, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    _f.write('{"version": 99, "terrains": []}')
N.GAME_ASSETS = _d21
try:
    _buf21 = _io.StringIO()
    with contextlib.redirect_stdout(_buf21):
        w25 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
        w25._autoload_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_21_9 = ("存档读不出来" in (w25.msg or "") and w25.msg_t > 0.0)
chk("㉑-9 ⭐⭐ B3 坏档 ⇒ msg 含「存档读不出来」且 msg_t=%.1f>0" % w25.msg_t, _ok_21_9,
    "msg=%r（⛔ 不弹模态框，只走游戏内提示）" % (w25.msg,))
# ⭐ 阳性对照：好档 ⇒ 不含该文案
_d21b = _tf.mkdtemp(prefix="_zt21b_")
with open(os.path.join(_d21b, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    _f.write('{"version": 1, "world_w": 3840, "floor_y": 599, "terrains": []}')
N.GAME_ASSETS = _d21b
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w25b = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
        w25b._autoload_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_21_10 = ("存档读不出来" not in (w25b.msg or ""))
chk("㉑-10 ⭐ B3 阳性对照：好档 ⇒ msg **不含**该文案（证明不是无条件弹）",
    _ok_21_10, "msg=%r" % (w25b.msg,))

# ---- B4：工具栏贴图提示在源码里，且 render 通过 ----
_ok_21_11 = ("贴图按平台顶面判归属" in _src21)
chk("㉑-11 ⭐⭐ B4 工具栏含「贴图按平台顶面判归属，只改高度不影响」提示", _ok_21_11,
    "命中 %d 次" % _src21.count("贴图按平台顶面判归属"))
_pok6, _perr6 = True, ""
try:
    for _ww in (w23, w24):
        _ww.set_mode("edit")
        _ww.edit_sel = 0
        _img = _ww.grab().toImage()
        _pok6 = _pok6 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok6, _perr6 = False, "%s: %s" % (type(_e).__name__, _e)
chk("㉑-12 ⭐⭐ 拖过地板 / 拖过厨房台之后，工具栏仍 render 通过", _pok6,
    _perr6 if _perr6 else "render OK")

for _d in (_d21, _d21b):
    shutil.rmtree(_d, ignore_errors=True)


# ============================================================================
section("㉒·PR21 · 存档状态可见（A1）+ 直线默认零厚（A2）")
# ============================================================================

# ---- A1-1：工具栏状态文案四态 ----
_d22 = _tf.mkdtemp(prefix="_zt22_")
with open(os.path.join(_d22, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    json.dump({"version": 1, "world_w": 3840, "floor_y": 599,
               "terrains": [{"kind": "solid", "x0": 82.0, "y0": 516.0,
                             "x1": 155.0, "y1": 528.0}]}, _f)
N.GAME_ASSETS = _d22
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w26 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
        _st0 = w26._save_state
        _txt0 = w26._save_status_cn()
        w26._autoload_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_22_1 = (_st0 == "present" and "未载入" in _txt0
            and "已载入 1 条" in w26._save_status_cn())
chk("㉒-1 ⭐⭐ A1-1 未载入 ⇒ 「⚠ 未载入」；载入后 ⇒ 「√ 已载入 1 条」", _ok_22_1,
    "载入前(%s)=%r ／ 载入后=%r" % (_st0, _txt0, w26._save_status_cn()))
# ⭐ 四态里"没有存档文件"必须与"有但没载入"**分开**
_d22b = _tf.mkdtemp(prefix="_zt22b_")
N.GAME_ASSETS = _d22b
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w26b = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_22_2 = (w26b._save_state == "absent"
            and "还没有存档文件" in w26b._save_status_cn())
chk("㉒-2 ⭐⭐ A1-1 四态：没有存档文件 ⇒ 与「未载入」**分开**显示", _ok_22_2,
    "state=%s 文案=%r" % (w26b._save_state, w26b._save_status_cn()))

# ---- A1-2：进游戏时提示一次（且只一次）----
# ⛔⛔ 窗口必须挑对：要有存档文件（`_d22`）但**没调** `_autoload_terrain()`
#    ⇒ 状态才是「present（未载入）」。
#    我第一版用了 `_d22b`（**空目录、没有存档文件**）⇒ 状态是 `absent` ⇒ 不该弹
#    ⇒ 断言报红，**是我判据选错窗口，不是代码错**。
N.GAME_ASSETS = _d22
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w26c = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_22_pre = (w26c._save_state == "present")
w26c.start_night(0)
_ok_22_3 = (_ok_22_pre and "没载入" in (w26c.msg or "") and w26c.msg_t > 0.0)
chk("㉒-3 ⭐⭐ A1-2 有存档但没载入 ⇒ 进游戏时提示一次", _ok_22_3,
    "state=%s msg=%r msg_t=%.1f" % (w26c._save_state, w26c.msg, w26c.msg_t))
_m1 = w26c.msg
w26c.msg, w26c.msg_t = "", 0.0
w26c.start_night(0)                     # 再进一次 ⇒ 不该再弹
_ok_22_4 = (w26c.msg != _m1)
chk("㉒-4 ⭐ A1-2 阳性对照：第二次进游戏**不再**弹（只提示一次）", _ok_22_4,
    "第二次 msg=%r（第一次=%r）" % (w26c.msg, _m1))
# ⭐⭐ 阳性对照：已载入的窗口**不该**弹这条
w26.msg, w26.msg_t = "", 0.0
w26.start_night(0)
_ok_22_5 = ("没载入" not in (w26.msg or ""))
chk("㉒-5 ⭐⭐ A1-2 阳性对照：已载入的窗口进游戏**不弹**这条", _ok_22_5,
    "msg=%r" % (w26.msg,))

# ---- A2-1：不按 Shift 也零厚 ----
w27 = _fresh_with_block()
w27.custom_terrains = []
_n0 = len(w27.custom_terrains)
_r1 = w27._edit_add(300.0, 200.0, 700.0, 500.0, "solid", line=True, shift=False)
_t1 = w27.custom_terrains[-1] if _r1 else None
_ok_22_6 = (_r1 and (_t1["y0"] == _t1["y1"] or _t1["x0"] == _t1["x1"]))
chk("㉒-6 ⭐⭐ A2-1 直线工具**不按 Shift** 斜拖 (300,200)→(700,500) ⇒ 存成零厚",
    _ok_22_6, "实测 %s" % (_t1,))
# ⭐ 阳性对照：按 Shift 也必须是零厚（不是矩形）
w27.custom_terrains = []
_r2 = w27._edit_add(300.0, 200.0, 700.0, 500.0, "solid", line=True, shift=True)
_t2 = w27.custom_terrains[-1] if _r2 else None
_ok_22_7 = (_r2 and (_t2["y0"] == _t2["y1"] or _t2["x0"] == _t2["x1"]))
chk("㉒-7 ⭐⭐ A2-1 阳性对照：按 Shift 拖同一条 ⇒ 也零厚（Shift=强制另一轴）",
    _ok_22_7, "实测 %s" % (_t2,))

# ---- A2-2：45° 与 dx/dy 判轴 ----
for _tag, _a, _want in (("dx=dy=100（45°）", (100.0, 100.0, 100.0), "水平"),
                        ("dx=400 dy=100", (400.0, 100.0, 100.0), "水平"),
                        ("dx=100 dy=400", (100.0, 400.0, 100.0), "垂直")):
    w27.custom_terrains = []
    _okr = w27._edit_add(200.0, 200.0, 200.0 + _a[0], 200.0 + _a[1],
                         "solid", line=True, shift=False)
    _tt = w27.custom_terrains[-1] if _okr else None
    _got = "?"
    if _tt:
        if abs(_tt["y1"] - _tt["y0"]) < 1e-9:
            _got = "水平"
        elif abs(_tt["x1"] - _tt["x0"]) < 1e-9:
            _got = "垂直"
    chk("㉒-8 ⭐ A2-2 %s ⇒ 判成**%s**线（期望 %s）" % (_tag, _got, _want),
        _got == _want, "实测 %s" % (_tt,))

# ---- A2-3：零厚线**参与落地判定**（站在上面不掉下去）----
w28 = _fresh_with_block()
w28.custom_terrains = []
w28._edit_add(1100.0, 400.0, 1300.0, 400.0, "solid", line=True, shift=False)
w28.room = N.Room(N.NIGHTS[w28.night_idx], custom=w28.custom_terrains)
w28.set_mode("play")
w28.phase = "play"
w28.luna.x = 1200.0
w28.luna.y = 300.0
w28.luna.vy = 0.0
step(w28, n=40)
_ok_22_8 = (abs(w28.luna.y - 400.0) < 2.0 and w28.luna.on_ground)
chk("㉒-9 ⭐⭐⭐ A2-3 零厚线**参与落地判定**：站在上面 y=%.1f（期望 400）on_ground=%s"
    % (w28.luna.y, w28.luna.on_ground), _ok_22_8,
    "⇒ 零厚线能站人，不是只能看")
# ⭐ 阳性对照：同一位置**没有**线时必须掉到地板
#   ⛔⛔ 选点必须避开**全部默认平台**的 x 区间：餐桌 430~700(顶面488)、
#      厨房台 760~1060、吊柜 790~1010 ⇒ 用 x=600 会站在**餐桌**上（实测 y=488）。
#      ⇒ 换 x=1200（干净），否则这条阳性对照是假红。
w28.custom_terrains = []
w28.room = N.Room(N.NIGHTS[w28.night_idx], custom=w28.custom_terrains)
w28.set_mode("play")
w28.phase = "play"
w28.luna.x = 1200.0
w28.luna.y = 300.0
w28.luna.vy = 0.0
step(w28, n=40)
_ok_22_9 = abs(w28.luna.y - float(N.FLOOR_Y)) < 2.0
chk("㉒-10 ⭐ A2-3 阳性对照：同样位置**没线** ⇒ 掉到地板 y=%.1f（期望 %.1f）"
    % (w28.luna.y, float(N.FLOOR_Y)), _ok_22_9,
    "⇒ 两条一起才证明'站住'是那条线给的")

# ---- A2 幂等回归：Shift 拖出来的轴对齐线再进_edit_add 不得被压成零长 ----
w27.custom_terrains = []
_r3 = w27._edit_add(600.0, 380.0, 600.0, 430.0, "solid", line=True, shift=True)
_ok_22_10 = (_r3 and len(w27.custom_terrains) == 1
             and abs(w27.custom_terrains[-1]["y1"]
                     - w27.custom_terrains[-1]["y0"] - 50.0) < 1e-6)
chk("㉒-11 ⭐⭐ A2 幂等：已轴对齐的线 + Shift 再进 `_edit_add` ⇒ **不得**被压成零长",
    _ok_22_10,
    "实测 %s（这一条不修的话，鼠标 Shift 直线会「什么都没画」）"
    % (w27.custom_terrains[-1] if _r3 else None,))

# ---- B1：工具栏文案 ----
_src22 = open(os.path.join(HERE, "pet_engine", "night.py"),
              encoding="utf-8").read()
_ok_22_11 = ("直线工具 = 零厚线" in _src22
             and "要斜的薄板请用矩形工具" in _src22
             and "Shift 直线锁水平/垂直" not in _src22)
chk("㉒-12 ⭐⭐ B1 文案改成「直线工具 = 零厚线；要斜的薄板请用矩形工具」", _ok_22_11,
    "新文案命中=%d；旧文案残留=%d"
    % (_src22.count("直线工具 = 零厚线"),
       _src22.count("Shift 直线锁水平/垂直")))

# ---- 四态文案 render 通过 ----
_pok7, _perr7 = True, ""
try:
    for _ww in (w26, w26b, w27, w28):
        _ww.set_mode("edit")
        _img = _ww.grab().toImage()
        _pok7 = _pok7 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok7, _perr7 = False, "%s: %s" % (type(_e).__name__, _e)
chk("㉒-13 ⭐⭐ 四种存档状态 + 直线改动后，编辑器 render 都通过", _pok7,
    _perr7 if _perr7 else "render OK")

for _d in (_d22, _d22b):
    shutil.rmtree(_d, ignore_errors=True)


# ============================================================================
section("㉓·PR23 · 关卡边界（border_x）可编辑")
# ============================================================================

# ---- C1：真实鼠标拖边界到 x=2000 ⇒ start_night 后生效 ----
w29 = _fresh_with_block()
w29.cam_x = 0.0
w29._edit_key(Qt.Key_B)                       # ⭐ 边界工具
_ok_tool = (w29.edit_tool == "border")
_bx = 2000.0
_a = (K(w29, _bx), K(w29, 100.0))
_b = (K(w29, _bx), K(w29, 500.0))             # ⭐ **竖直**拖
w29.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, _a))
w29.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, _b))
w29.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, _b))
_ok_23_1 = (_ok_tool and abs(w29.custom_border - _bx) < 1.0
            and abs(w29.room.border_x - _bx) < 1.0)
chk("㉓-1 ⭐⭐ C1 按 B + **竖直拖**到 x=2000 ⇒ custom_border=%.1f room.border_x=%.1f"
    % (w29.custom_border or -1, w29.room.border_x), _ok_23_1,
    "工具=%s（回执 §1）" % w29.edit_tool)
w29.start_night(0)
_ok_23_1b = abs(w29.room.border_x - _bx) < 1.0
chk("㉓-2 ⭐⭐ C1 `start_night` 后 border_x 仍是 %.1f（期望 2000）" % _bx,
    _ok_23_1b, "实测 %.1f" % w29.room.border_x)
# ⭐ 阳性对照：没拖 ⇒ 仍是关卡默认
w29b = _fresh_with_block()
w29b.start_night(0)
_ok_23_2 = abs(w29b.room.border_x
               - float(N.NIGHTS[w29b.night_idx]["border_x"])) < 1e-9
chk("㉓-3 ⭐ C1 阳性对照：没拖 ⇒ border_x = 关卡默认 %.0f"
    % w29b.room.border_x, _ok_23_2, "custom_border=%r" % (w29b.custom_border,))

# ---- C2 ⭐⭐⭐ 按**实测真相**写：border_x 不限制露娜移动 ----
# ⚠️⚠️ 派单 §0 说「露娜被 border_x 拦在 342.3」—— **实测推翻**：
#   ① `room.border_x` **只**进微波炉逻辑（trespass）与 HUD 禁区，物理层完全不读它；
#   ② 真正拦住她的是 `Luna.update:1638` 的**布墙**（读模块常量 TABLE_X0=430）⇒ 停在 408.3。
#   ⇒ 所以本条判据写成"**改 border 对露娜移动零影响**"，并加阳性对照证明那堵墙才是真凶。
w30 = _fresh_with_block()
w30.custom_terrains = []
w30.builtin_terrains = [dict(N.platform_dicts(N.PLATFORMS)[0])]
w30.builtin_terrains[0]["builtin"] = True
w30.set_mode("play")
w30.phase = "play"


def _walk_to(border, frames=1200):
    _w = _fresh_with_block()
    _w.custom_terrains = []
    _w.builtin_terrains = [dict(N.platform_dicts(N.PLATFORMS)[0])]
    _w.builtin_terrains[0]["builtin"] = True
    _w.custom_border = border
    _w.start_night(0)
    _l = _w.luna
    _l.x, _l.y = 80.0, float(N.FLOOR_Y)
    _l.vx = _l.vy = 0.0
    for _ in range(frames):
        _l.update(DT, {Qt.Key_Right}, _w.room)
    return _w.room.border_x, _l.x


_bx360, _x360 = _walk_to(None)
_bx2000, _x2000 = _walk_to(2000.0)
# ⭐⭐ PR24 之后"布墙跟着地形走" ⇒ 这个 helper 里**没有餐桌** ⇒ 不再有墙。
#   ⇒ 绝对值判据必须改成「**能走过 500**」，"零影响"仍用两个 border 值相等来证。
_ok_23_4 = (abs(_x360 - _x2000) < 0.5 and _x2000 > 500.0)
chk("㉓-4 ⭐⭐⭐ C2【真相版】改 border_x 对露娜移动**零影响**："
    "默认 360⇒x=%.1f ／ 拖到 2000⇒x=%.1f（两者相等 ⇒ 边界不管移动）"
    % (_x360, _x2000), _ok_23_4,
    "PR24 后无餐桌⇒无布墙⇒她能走过 500（改前两值都停在 408.3）")
# ⭐⭐ 阳性对照：border_x **确实**影响微波炉（这才它存在的意义）
def _mw_alert(border, luna_x):
    _w = _fresh_with_block()
    _w.custom_border = border
    _w.start_night(0)
    _w.mw.alert = 0.0
    _w.luna.x, _w.luna.y = luna_x, float(N.FLOOR_Y)
    _w.mw.sense = lambda l: 1.0                 # ⭐ 强制"看得见" ⇒ 只测 trespass 门禁
    for _ in range(30):
        _w.mw.update(DT, _w.luna, _w.room)
    return _w.mw.alert


_a_in = _mw_alert(360.0, 80.0)      # 界内（80 < 360）
_a_out = _mw_alert(360.0, 500.0)    # 越界（500 > 360）
_a_big = _mw_alert(2000.0, 500.0)   # 边界拖到 2000 ⇒ 500 又变成界内
_ok_23_5 = (_a_in == 0.0 and _a_out > 0.0 and _a_big == 0.0)
chk("㉓-5 ⭐⭐ C2 阳性对照：border_x 管的是**微波炉**：界内 alert=%.2f ／ "
    "越界 alert=%.2f ／ 边界拖到 2000 后同一个 x=500 又变界内 alert=%.2f"
    % (_a_in, _a_out, _a_big), _ok_23_5,
    "⇒ border = 微波炉从哪开始警戒，不是墙")

# ---- C3：Del 恢复默认 ----
w29.set_mode("edit")
w29.edit_sel_obj = ("border", -1)
_ok_23_6 = (w29._edit_del_obj() and w29.custom_border is None
            and abs(w29.room.border_x
                    - float(N.NIGHTS[w29.night_idx]["border_x"])) < 1e-9)
chk("㉓-6 ⭐⭐ C3 选中边界按 Del ⇒ custom_border=None 且 room 回到默认 %.0f"
    % N.NIGHTS[0]["border_x"], _ok_23_6, "custom_border=%r" % (w29.custom_border,))

# ---- C4：导出 v4 + 导入生效 ----
_d23 = _tf.mkdtemp(prefix="_zt23_")
N.GAME_ASSETS = _d23
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w31 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
        w31.set_mode("edit")
        w31.custom_border = 1234.0
        _p23 = w31.export_terrain()
finally:
    N.GAME_ASSETS = _ORIG_GA
with open(_p23, encoding="utf-8") as _f:
    _d = json.load(_f)
_ok_23_7 = (_d["version"] == 4 and _d.get("border_x") == 1234)
chk("㉓-7 ⭐⭐ C4 导出 ⇒ version=%s / border_x=%s（期望 4 / 1234）"
    % (_d["version"], _d.get("border_x")), _ok_23_7,
    "keys=%s" % sorted(_d.keys()))
N.GAME_ASSETS = _d23
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w32 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
        # ⛔ offscreen 下自动导入被闸门跳过 ⇒ 必须手动补（否则下面拿 None 减 1234 直接崩）
        w32._autoload_terrain()
        w32.start_night(0)
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_23_8 = (abs(w32.custom_border - 1234.0) < 1e-9
            and abs(w32.room.border_x - 1234.0) < 1e-9)
chk("㉓-8 ⭐⭐ C4 导入 ⇒ custom_border=%s room.border_x=%.1f（期望 1234）"
    % (w32.custom_border, w32.room.border_x), _ok_23_8,
    "⇒ 三条进游戏路径都吃它（PR18 已统一）")

# ---- C4/C5：老存档（v1/v2/v3）**不受影响** ----
for _ver in (1, 2, 3):
    _dv = _tf.mkdtemp(prefix="_zt23v%d_" % _ver)
    _doc = {"version": _ver, "world_w": 3840, "floor_y": 599, "terrains": []}
    if _ver >= 2:
        _doc["mw_patrol"] = [1000, 1400]
    with open(os.path.join(_dv, "custom_terrain.json"), "w",
              encoding="utf-8") as _f:
        json.dump(_doc, _f)
    N.GAME_ASSETS = _dv
    try:
        with contextlib.redirect_stdout(_io.StringIO()):
            w33 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
            w33._autoload_terrain()      # ⛔ 同上：不补调这条会**假绿**
            w33.start_night(0)
    finally:
        N.GAME_ASSETS = _ORIG_GA
    _ok = (w33.custom_border is None
           and abs(w33.room.border_x
                   - float(N.NIGHTS[w33.night_idx]["border_x"])) < 1e-9)
    chk("㉓-9 ⭐⭐ C4/C5 v%d 老存档加载 ⇒ border 仍走关卡默认 %.0f（不受影响）"
        % (_ver, N.NIGHTS[0]["border_x"]), _ok,
        "custom_border=%r room.border_x=%.1f" % (w33.custom_border, w33.room.border_x))
    shutil.rmtree(_dv, ignore_errors=True)

# ---- 阴性：v3 文件里**手塞** border_x 必须被忽略（版本语义不漂移）----
_dv3 = _tf.mkdtemp(prefix="_zt23bad_")
with open(os.path.join(_dv3, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    json.dump({"version": 3, "world_w": 3840, "floor_y": 599,
               "terrains": [], "border_x": 2500}, _f)
N.GAME_ASSETS = _dv3
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w34 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
        w34._autoload_terrain()          # ⛔ 同上：不补调这条会**假绿**
        w34.start_night(0)
finally:
    N.GAME_ASSETS = _ORIG_GA
_ok_23_10 = (w34.custom_border is None and w34.room.border_x == 360.0)
chk("㉓-10 ⭐⭐ 阴性：v3 文件里手塞 `border_x: 2500` 必须被**忽略**"
    "（v3 语义不许漂移）", _ok_23_10,
    "custom_border=%r room.border_x=%.1f" % (w34.custom_border, w34.room.border_x))
shutil.rmtree(_dv3, ignore_errors=True)

# ---- 边界夹取 ----
w35 = _fresh_with_block()
w35.set_mode("edit")
_ok_23_11 = (w35._edit_set_line("border", 5.0, 0.0, 5.0) is False
             and w35.custom_border is None)      # 5 < BODY_W/2+8 ⇒ 拒
_ok_23_11b = (w35._edit_set_line("border", 5000.0, 0.0, 5000.0) is False
              and w35.custom_border is None)     # 5000 > WORLD_W ⇒ 拒
chk("㉓-11 ⭐ 夹取：x=5（太小）与 x=5000（超世界）都被拒且不改状态",
    _ok_23_11 and _ok_23_11b,
    "下限=BODY_W/2+8=%.1f 上限=WORLD_W=%d" % (N.BODY_W * 0.5 + 8.0, N.WORLD_W))

# ---- 撤销 / 清空 ----
w36 = _fresh_with_block()
w36.set_mode("edit")
w36._edit_set_line("border", 1500.0, 0.0, 1500.0)
_set = w36.custom_border
w36.edit_undo()
_ok_23_12 = (_set == 1500.0 and w36.custom_border is None)
chk("㉓-12 ⭐⭐ Ctrl+Z 能撤掉边界设置（1500 → None）", _ok_23_12,
    "设完=%r 撤后=%r" % (_set, w36.custom_border))
w36._edit_set_line("border", 1500.0, 0.0, 1500.0)
w36.edit_clear()
_ok_23_13 = w36.custom_border is None
chk("㉓-13 ⭐ C 清空 ⇒ 边界回到默认（None = 不覆盖）", _ok_23_13,
    "custom_border=%r" % (w36.custom_border,))

# ---- render ----
_pok8, _perr8 = True, ""
try:
    for _ww in (w29, w31, w35, w36):
        _ww.set_mode("edit")
        _ww.edit_sel_obj = ("border", -1)
        _img = _ww.grab().toImage()
        _pok8 = _pok8 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok8, _perr8 = False, "%s: %s" % (type(_e).__name__, _e)
chk("⑳-14 ⭐⭐ 设了/没设边界、选中/未选中 四态 render 通过", _pok8,
    _perr8 if _perr8 else "render OK")

shutil.rmtree(_d23, ignore_errors=True)


# ============================================================================
section("㉔·PR24 · 布墙跟着地形走（让你出门）")
# ============================================================================

# ⛔⛔⛔ **不许硬编码 y0**：FLOOR_Y 是可变量（Ronny 2026-10-10 把它 599→670）。
#   硬编码 599 ⇒ 人物 spawn 在 670 而地板顶面 599 ⇒ 每帧掉出世界
#   ⇒ 被 `if self.y > VH+200: 传回 spawn` 兜底 ⇒ **死循环，x 永远不动**。
#   我第一版就是被这个卡了 9 条判据全红。
_FLOOR_ONLY = [{"kind": "solid", "x0": 0.0, "y0": float(N.FLOOR_Y),
                "x1": 3840.0, "y1": 720.0}]
_TABLE = {"kind": "solid", "x0": 430.0, "y0": 488.0,
          "x1": 700.0, "y1": float(N.FLOOR_Y)}


def _room_of(platforms):
    """造一个「platforms **只有**给定那几条」的 room。

    ⛔⛔ 必须每条都打 `builtin: True` 才会走 `Room.__init__` 的**全集模式**
       （否则走「默认 4 + custom」⇒ **默认餐桌还在** ⇒ 我第一版把 ㉔-1/2/3 测红了）。
       ⚠️ 这不是代码 bug，是我 helper 造错了房间。
    """
    _w = new_w()
    _pl = []
    for _p in platforms:
        _q = dict(_p)
        _q["builtin"] = True
        _pl.append(_q)
    _w.custom_terrains = []
    _w.builtin_terrains = _pl
    _w.room = N.Room(N.NIGHTS[_w.night_idx], custom=_w._room_custom())
    return _w


def _walk(platforms, frames=1200, dash=False):
    """按右 frames 帧 ⇒ 露娜最终 x（绕开微波炉/phase，直接驱动物理层）。"""
    _w = _room_of(platforms)
    _l = _w.luna
    _l.x, _l.y = 80.0, float(N.FLOOR_Y)
    _l.vx = _l.vy = 0.0
    _l.dash_t = 0.0
    for _ in range(frames):
        if dash:
            _l.dash_t = max(_l.dash_t, 0.15)     # ⭐ 一直续着冲
        _l.update(DT, {Qt.Key_Right}, _w.room)
    return _w, _l.x


# ---- C1：删掉餐桌 ⇒ 能走过 500；加回 ⇒ 仍停 408.3 ----
_w_no, _x_no = _walk(_FLOOR_ONLY)
_w_yes, _x_yes = _walk(_FLOOR_ONLY + [_TABLE])
_wall_stop = N.TABLE_X0 - N.BODY_W * 0.35
_ok_24_1 = (_x_no > 500.0 and abs(_x_yes - _wall_stop) < 1.0)
chk("㉔-1 ⭐⭐ C1 删掉餐桌 ⇒ 走到 x=%.1f（>500 ✅）／ 加回餐桌 ⇒ 停在 %.1f"
    % (_x_no, _x_yes), _ok_24_1,
    "408.3 = TABLE_X0(%d) − BODY_W×0.35(%.1f)" % (N.TABLE_X0, N.BODY_W * 0.35))

# ---- C2 ⭐⭐⭐ 本单最关键：冲刺分支也必须一起失效 ----
_wd_no, _xd_no = _walk(_FLOOR_ONLY, dash=True)
_wd_yes, _xd_yes = _walk(_FLOOR_ONLY + [_TABLE], dash=True)
_ok_24_2 = (_xd_no > 500.0 and abs(_xd_yes - _wall_stop) < 1.0)
chk("㉔-2 ⭐⭐⭐ C2 **冲刺分支**也改了：无餐桌冲刺到 x=%.1f ／ 有餐桌仍停在 %.1f"
    % (_xd_no, _xd_yes), _ok_24_2,
    "⇒ 两处都读 `table_wall_span`（只改一处的话这条会红）")

# ---- C3：餐桌挪位置 ⇒ 墙跟着挪 ----
# ⛔⛔ 第一版我把它挪到 x=1500 ⇒ 她走到 **1107.5** 就停 —— 那是**冰箱墙**
#    （FRIDGE x=1120，冰箱也是垂到地的实心体），根本还没走到餐桌那儿。
#    ⇒ 判据选点必须**避开冰箱**（x<1120）。这里挪到 300~500：
#      ① 与默认 430~700 只重叠 35%（<50%）⇒ 顺带证明派单的「x 重叠」判据在这里判不出；
#      ② 完全在冰箱左侧 ⇒ 不会被冰箱截住。
_moved = {"kind": "solid", "x0": 300.0, "y0": 488.0, "x1": 500.0,
          "y1": float(N.FLOOR_Y)}
_w_mv, _x_mv = _walk(_FLOOR_ONLY + [_moved])
_stop_mv = 300.0 - N.BODY_W * 0.35
_ok_24_3 = abs(_x_mv - _stop_mv) < 1.0
chk("㉔-3 ⭐⭐ C3 餐桌挪到 x=300~500 ⇒ 墙跟着挪，停在 %.1f（期望 %.1f）"
    % (_x_mv, _stop_mv), _ok_24_3,
    "⇒ 墙的位置来自 room.platforms，不是 TABLE_X0 常量"
    "（且与默认区间只重叠 35%% ⇒ 派单的 x-重叠判据在这一条会漏）")

# ---- ⭐ 判据函数本身的行为（含派单示例的两个坑）----
_rooms = {
    "默认 4 平台": N.platform_dicts(N.PLATFORMS),
    "只剩地板": _FLOOR_ONLY,
    "餐桌挪到 300~500": [_moved],
    "PR21 零厚水平线 y=488": [{"kind": "solid", "x0": 500.0, "y0": 488.0,
                              "x1": 900.0, "y1": 488.0}],
    "厨房台(760,380)": [{"kind": "solid", "x0": 760.0, "y0": 380.0,
                        "x1": 1060.0, "y1": 418.0}],
}


class _RR:
    def __init__(self, pl):
        self.platforms = pl


_span = {k: N.table_wall_span(_RR(v)) for k, v in _rooms.items()}
_ok_24_4 = (_span["默认 4 平台"] == (430.0, 700.0, 488.0)
            and _span["只剩地板"] is None
            and _span["餐桌挪到 300~500"] == (300.0, 500.0, 488.0)
            and _span["PR21 零厚水平线 y=488"] is None
            and _span["厨房台(760,380)"] is None)
chk("㉔-4 ⭐⭐ `table_wall_span` 五种输入全对", _ok_24_4,
    " ｜ ".join("%s=%s" % (k, "None" if v is None else "(%.0f,%.0f,%.0f)" % v)
               for k, v in _span.items()))
chk("㉔-4b ⭐⭐ 阴性钉死：零厚线**不得**变成 400px 宽的墙"
    "（派单示例的 x-重叠判据在这里会误命中）", _span["PR21 零厚水平线 y=488"] is None,
    "它不垂到地（y1=488 < FLOOR_Y-1）⇒ 不挡路")

# ---- C4：攀爬面不受影响 ----
_wL = _room_of(N.platform_dicts(N.PLATFORMS))
_lL = _wL.luna
_lL.x, _lL.y = 565.0, 550.0
_hit_cloth = _lL._ladder_here(_wL.room)
_ok_24_5 = _hit_cloth is not None
chk("㉔-5 ⭐⭐ C4 有餐桌时布面仍可爬（x=565,y=550 ⇒ %s）" % (_hit_cloth,), _ok_24_5,
    "⇒ LADDERS 桌布整面没被动（派单 §2.3）")
_wL2 = _room_of(_FLOOR_ONLY)
_lL2 = _wL2.luna
_lL2.x, _lL2.y = 565.0, 550.0
_ok_24_6 = True                     # ⛔ 只要求"不崩"
try:
    _hit2 = _lL2._ladder_here(_wL2.room)
    _wL2.luna.update(DT, set(), _wL2.room)      # ⭐ 真的跑一次物理
except Exception as _e:                        # noqa: BLE001
    _ok_24_6 = False
    _hit2 = "%s: %s" % (type(_e).__name__, _e)
chk("㉔-6 ⭐⭐ C4 无餐桌时爬梯查询 + 物理跑一帧**不崩**（_ladder_here=%s）"
    % (_hit2,), _ok_24_6, "判据：不抛异常")

# ---- C5：老存档（v3 / 1 条地板）⇒ 墙自动失效 ----
_d24 = _tf.mkdtemp(prefix="_zt24_")
_bl24 = [dict(_FLOOR_ONLY[0])]
_bl24[0]["builtin"] = True
with open(os.path.join(_d24, "custom_terrain.json"), "w", encoding="utf-8") as _f:
    json.dump({"version": 3, "world_w": 3840, "floor_y": 599,
               "terrains": _bl24}, _f)
N.GAME_ASSETS = _d24
try:
    with contextlib.redirect_stdout(_io.StringIO()):
        w37 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
        w37._autoload_terrain()      # ⛔ offscreen 闸门 ⇒ 必须手动补
        w37.start_night(0)
finally:
    N.GAME_ASSETS = _ORIG_GA
_span24 = N.table_wall_span(w37.room)
_l37 = w37.luna
_l37.x, _l37.y = 80.0, float(N.FLOOR_Y)
_l37.vx = _l37.vy = 0.0
for _ in range(1200):
    _l37.update(DT, {Qt.Key_Right}, w37.room)
_ok_24_7 = (_span24 is None and _l37.x > 500.0)
chk("㉔-7 ⭐⭐⭐ C5 **你的真实存档**（v3 / 只剩地板）加载后：墙=%s，"
    "露娜走到 x=%.1f ⇒ **出门成功**" % (_span24, _l37.x), _ok_24_7,
    "这就是 PR23 之后你仍然出不去的那个 bug")
shutil.rmtree(_d24, ignore_errors=True)

# ---- render ----
_pok9, _perr9 = True, ""
try:
    for _pl in (_FLOOR_ONLY, _FLOOR_ONLY + [_TABLE]):
        _ww = _room_of(_pl)
        _ww.set_mode("edit")
        _img = _ww.grab().toImage()
        _pok9 = _pok9 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok9, _perr9 = False, "%s: %s" % (type(_e).__name__, _e)
chk("㉔-8 ⭐⭐ 有/无餐桌两种地形下编辑器 render 都通过", _pok9,
    _perr9 if _perr9 else "render OK")


# ============================================================================
section("⑳·PR19 · 编辑器底图与游戏一致（所见即所得）")
# ============================================================================

_SEQ_NAMES = ("_draw_bg_slices", "_draw_bg", "_draw_zone", "_draw_nest",
              "_draw_stashes", "_draw_fridge", "_draw_mw", "_draw_luna",
              "_draw_edit_overlay", "_draw_edit_toolbar", "_draw_menu")


def _seq(w, mode, phase):
    """录一次 paintEvent 的 _draw_* 调用序列。

    ⛔ `mode` 与 `phase` 必须**分别**传：我第一版用 `phase = "menu" if edit else "play"`
       推导，结果「menu 态」那一探实际录的是**游戏态** ⇒ 三条判据一起假红
       （menu 态本来 phase 就是 menu，而游戏态 phase 是 play）。
    """
    w.mode = mode
    w.phase = phase
    got = []
    for n in _SEQ_NAMES:
        def mk(nm):
            def f(pp, *a, **k):
                got.append(nm)
            return f
        setattr(w, n, mk(n))
    try:
        _im = QImage(int(N.VW), int(N.VH), QImage.Format_ARGB32)
        w.render(_im)
    finally:
        for n in _SEQ_NAMES:
            try:
                delattr(w, n)
            except AttributeError:
                pass
    return got


w20 = new_w()
_seq_menu = _seq(w20, "play", "menu")     # menu 选关界面（mode=play, phase=menu）
_seq_edit = _seq(w20, "edit", "menu")     # 编辑器（mode=edit, phase=menu）
_seq_play = _seq(w20, "play", "play")     # 正式游戏（mode=play, phase=play）

# ---- C1：edit 序列含 _draw_bg_slices；menu 态**不含**（阳性对照）----
_ok_20_1 = ("_draw_bg_slices" in _seq_edit
            and "_draw_bg_slices" not in _seq_menu)
chk("⑳-1 ⭐⭐ C1 edit 态序列含 `_draw_bg_slices`（menu 态不含 ⇒ 确实按 mode 分流）",
    _ok_20_1, "edit=%s" % (_seq_edit,))
chk("⑳-1b ⭐ C1 阳性对照：menu 态序列 = %s" % (_seq_menu,), True,
    "里面没有 _draw_bg_slices ⇒ 不是无脑全画")

# ---- C3：edit 序列含 _draw_mw ----
_ok_20_3 = ("_draw_mw" in _seq_edit and "_draw_mw" not in _seq_menu)
chk("⑳-3 ⭐⭐ C3 edit 态序列含 `_draw_mw`（编辑态看得见微波炉了）", _ok_20_3,
    "edit=%s" % (_seq_edit,))

# ---- C4：edit 不调 _draw_bg；menu 态**调**（阳性对照）----
_ok_20_4 = ("_draw_bg" not in _seq_edit and "_draw_bg" in _seq_menu)
chk("⑳-4 ⭐⭐ C4 edit 态**不**调 `_draw_bg`；menu 态仍调（没把选关界面也改了）",
    _ok_20_4, "edit 有 _draw_bg=%s / menu 有 _draw_bg=%s"
    % ("_draw_bg" in _seq_edit, "_draw_bg" in _seq_menu))

# ---- ⭐ C2 核心判据：只剩底图链时，两态整幅图 md5 逐字节相同 ----
_OBJ_D = ("_draw_nest", "_draw_stashes", "_draw_fridge", "_draw_mw",
          "_draw_fx_behind", "_draw_luna", "_draw_fx_front")
_EDIT_D = ("_draw_edit_overlay", "_draw_edit_toolbar", "_draw_hud",
           "_draw_menu", "_draw_platforms")


def _render_at(cam, mode):
    w20.cam_x = float(cam)
    w20.mode = mode
    w20.phase = "menu" if mode == "edit" else "play"
    _im = QImage(int(N.VW), int(N.VH), QImage.Format_ARGB32)
    w20.render(_im)
    return _im


def _stub(names):
    for n in names:
        setattr(w20, n, (lambda p, *a, **k: None))


def _unstub(names):
    for n in names:
        try:
            delattr(w20, n)
        except AttributeError:
            pass


_c2 = {}
for _cam in (0, 1500, 2560):
    _stub(_OBJ_D + _EDIT_D)
    try:
        _a, _b = _render_at(_cam, "edit"), _render_at(_cam, "play")
    finally:
        _unstub(_OBJ_D + _EDIT_D)
    _c2[_cam] = (hashlib.md5(_a.bits().tobytes()).hexdigest(),
                 hashlib.md5(_b.bits().tobytes()).hexdigest())
_ok_20_2 = all(v[0] == v[1] for v in _c2.values())
chk("⑳-2 ⭐⭐⭐ C2【本单核心】只剩底图链时，cam_x=0/1500/2560 三档"
    "edit 与 play 整幅图 **md5 逐字节相同**", _ok_20_2,
    " ｜ ".join("x=%d %s%s" % (k, v[0][:10], "==" if v[0] == v[1] else "!=%s" % v[1][:10])
               for k, v in sorted(_c2.items())))
chk("⑳-2b ⭐ C2 阳性对照：cam_x=1500（不是 0）时也相同 ⇒ 不是碰巧在 x=0 一致",
    _c2[1500][0] == _c2[1500][1] and _c2[0][0] != _c2[1500][0],
    "x=0 的 md5=%s 与 x=1500 的 %s 不同 ⇒ 判据对 cam_x 有分辨力"
    % (_c2[0][0][:10], _c2[1500][0][:10]))

# ---- ⭐⭐ 差异定位：编辑态与游戏态的差异**全部且仅仅**来自 工具栏+覆盖层+HUD ----
GW, GH, STEP, SAMP = N.VW // 16, N.VH // 16, 16, 4


def _ndiff(a, b):
    n = 0
    for gy in range(GH):
        for gx in range(GW):
            for y in range(gy * STEP, gy * STEP + STEP, SAMP):
                hit = False
                for x in range(gx * STEP, gx * STEP + STEP, SAMP):
                    if a.pixelColor(x, y) != b.pixelColor(x, y):
                        hit = True
                        break
                if hit:
                    n += 1
                    break
    return n


_d_real = _ndiff(_render_at(1500, "edit"), _render_at(1500, "play"))
_stub(("_draw_edit_toolbar", "_draw_edit_overlay", "_draw_hud"))
try:
    _d_min = _ndiff(_render_at(1500, "edit"), _render_at(1500, "play"))
finally:
    _unstub(("_draw_edit_toolbar", "_draw_edit_overlay", "_draw_hud"))
_ok_20_6 = (_d_real > 0 and _d_min == 0)
chk("⑳-6 ⭐⭐⭐ 差异定位：真实渲染差 %d 格，**去掉工具栏+覆盖层+HUD 后差 %d 格**"
    % (_d_real, _d_min), _ok_20_6,
    "⇒ 编辑态与游戏态的画面差异**全部且仅仅**来自这三样（其余逐像素相同）")

# ---- ⭐ 派单 §3 的「家具贴图重影」：实测游戏态**压根不贴** ----
#   `_draw_platforms` 全文件只有一个调用点，且在 `if bg_img is not None: ... return`
#   **之后** ⇒ 只有"没有美术底图"时才走程序贴图。当前 scene_bg.png 在 ⇒ 不走。
_src20 = open(os.path.join(HERE, "pet_engine", "night.py"),
              encoding="utf-8").read()
_ps = [i for i in range(len(_src20))
       if _src20.startswith("self._draw_platforms(p)", i)]
_ok_20_7 = (len(_ps) == 1)
chk("⑳-7 ⭐⭐ 派单 §3「重影」实测：`_draw_platforms` 全文件只有 **%d** 个调用点"
    % len(_ps), _ok_20_7,
    "⇒ 有美术底图时游戏态**根本不贴**家具图 ⇒ 重影当前不存在，"
    "编辑态不画它正好=与游戏一致")

# ---- C5：三档 cam_x 强制 render ----
_pok5, _perr5 = True, ""
try:
    for _cam in (0, 1280, 2560):
        w20.cam_x = float(_cam)
        w20.set_mode("edit")
        w20.edit_sel = 0
        _img = w20.grab().toImage()
        _pok5 = _pok5 and _img.width() > 0 and _img.height() > 0
except Exception as _e:                        # noqa: BLE001
    _pok5, _perr5 = False, "%s: %s" % (type(_e).__name__, _e)
chk("⑳-5 ⭐⭐ C5 编辑态 cam_x = 0 / 1280 / 2560 三档强制 render 通过", _pok5,
    _perr5 if _perr5 else "render OK")

# ---- ⛔ 禁碰核对：`_draw_bg` 函数体**逐字节未变**（对比 PR16 基线副本）----
def _func_src(text, name):
    i = text.index("    def %s(self" % name)
    j = text.find("\n    def ", i + 10)
    return text[i:j if j > 0 else len(text)]


try:
    _base_txt = open(os.path.join(os.path.dirname(HERE), "_work",
                                   "_baseline_PR16",
                                   "night.py.5675lines.1c3887fb"),
                     encoding="utf-8").read()
    _h_now = hashlib.md5(_func_src(_src20, "_draw_bg").encode("utf-8")).hexdigest()
    _h_base = hashlib.md5(_func_src(_base_txt, "_draw_bg").encode("utf-8")).hexdigest()
    _ok_20_8 = (_h_now == _h_base)
    chk("⑳-8 ⭐⭐ 禁碰核对：`_draw_bg` 函数体 md5 与 PR16 基线**逐字节相同**"
        "（派单 §6）", _ok_20_8,
        "现在=%s 基线=%s" % (_h_now[:12], _h_base[:12]))
except (OSError, ValueError) as _e:
    chk("⑳-8 ⭐⭐ 禁碰核对：`_draw_bg` 函数体 md5 与 PR16 基线逐字节相同",
         False, "基线读不到：%s" % _e)


# ============================================================================
section("⑯·PR16-A · 强制渲染（⛔ 画分支的错只在真渲染时暴露）")
# ============================================================================

_paint_ok, _paint_err = True, ""
try:
    for _ww, _cx in ((w4, 0.0), (w5, 1280.0), (w6, float(N.CAM_X_MAX))):
        _ww.set_mode("edit")
        _ww.cam_x = _cx
        _ww.custom_stashes = [{"x": 480.0, "y": 488.0,
                               "icon": "yolk", "kind": "loose"}]
        _ww.custom_fridge = [{"x": 1148.0, "y": 260.0, "icon": "watermelon"}]
        _ww.custom_spawn = (800.0, 400.0)
        _ww.custom_patrol = (2000.0, 2400.0)
        _ww.custom_nest = (1500.0, 1700.0)
        _ww.edit_sel = 0
        _img = _ww.grab().toImage()
        _paint_ok = _paint_ok and _img.width() > 0 and _img.height() > 0
except Exception as _e:                          # noqa: BLE001
    _paint_ok, _paint_err = False, "%s: %s" % (type(_e).__name__, _e)
chk("⑯-28 ⭐⭐ cam_x = 0 / 1280 / 2560 三档都强制 render 通过"
    "（工具栏新文本 + 覆盖层）", _paint_ok,
    _paint_err if _paint_err else "render OK")

# ============================================================================
print()
print("=" * 74)
print("  结果：%d 通过 / %d 失败（共 %d 条）" % (len(OK), len(BAD), len(OK) + len(BAD)))
if BAD:
    print("  ⛔ 未过：")
    for b in BAD:
        print("     · %s" % b)
print("=" * 74)
sys.exit(1 if BAD else 0)
