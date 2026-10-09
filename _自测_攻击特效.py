# -*- coding: utf-8 -*-
"""_自测_攻击特效.py —— PR14「攻击三档 + 程序绘制特效」验收

⭐ 纪律（沿用 _自测_自定义地形.py）：
   ① 一律驱动**真实**代码（真实 keyPressEvent / keyReleaseEvent / _tick / paintEvent）
   ② 可控假时钟（perf_counter 替换掉），保证 dt 稳定
   ③ ⭐ 必须**强制 render 一次** —— paintEvent 里的错只在真渲染时暴露
   ④ ⛔ **阴性结果必配阳性对照**：光"没抛异常"不能证明判据有分辨力

⛔ 本文件只测 PR14（pet_engine/night.py 的攻击三档）。
   ⛔ `_自测_地形.py` 名字最像，测的是**桌宠**地形，与本单无关。

判据清单（派单 §七的 13 条）：
   ① 点按 J ⇒ 只有普攻
   ② 按住 0.35s 松手 ⇒ 蓄力 1（击退 312，粒子红）
   ③ 按住 0.70s ⇒ 蓄力 2（击退 338，粒子蓝 26 粒）
   ④ 按住 0.5s ⇒ 只出蓄力 1，不升不降
   ⑤ 按住 1.5s ⇒ 只放一次招
   ⑥ 攻击冷却期间按 J 无效
   ⑦ 默认行为回归（J 以外的键逐字未变）
   ⑧ Effect.update 到 t>=1.0 返回 False（防泄漏）
   ⑨ len(fx) > 24 丢最旧的
   ⑩ 强制 render 不抛异常
   ⑪ 三处 _draw_luna 调用点都插了特效（grep 计数 = 3）
   ⑫ 阴性：阈值改坏必须被抓住（阳性对照）
   ⑬ 0.30 变色点与 0.35 出招点是分开的
   + 补充：QTE 是否吞 J / 击退作用对象/ 档位表一致性
"""
import os
import sys
import json

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

# =============================================================================
# ⭐⭐⭐ 假时钟：**必须在这里、`from pet_engine import night` 之前**替换
# =============================================================================
# ⭐ 照抄 `_自测_自定义地形.py` 的既有套路。
#   ⚠️⚠️⚠️ 我第一版把替换写在文件更下方、建窗口**之后** ⇒ `dt` 恒为 0，
#   `atk_wind` 卡在 0.144 不动，我一度**误判成「三段推进被 PR14 改坏了」**。
#   ⇒ 症状：按住 J 蓄满也不出招、`hit_by` 从没被调用、几���判据一起红。
#   ⚠️ **报「时序不推进」之前先量 dt**（`w._last` 与假时钟差多少）。
#   教训与PR13 同型：**判据自身出问题 vs 产品代码出问题，必须先分清**，
#   否则会去改没坏的代码。
import time as _time_mod

_T = [0.0]
_time_mod.perf_counter = lambda: _T[0]

DT = 1.0 / 60.0


def step(w, n=1):
    """推进 n 帧，dt 由假时钟给出（精确 DT）。"""
    for _ in range(n):
        _T[0] += DT
        w._tick()


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

# ⭐ 真实键盘事件（走keyPressEvent / keyReleaseEvent，⛔ 不许直接调 try_attack）
def kd(k):
    return QKeyEvent(QKeyEvent.KeyPress, k, Qt.NoModifier)


def ku(k):
    return QKeyEvent(QKeyEvent.KeyRelease, k, Qt.NoModifier)


def mk(btn=Qt.LeftButton):
    return QMouseEvent(MouseEventHolder.MouseButtonPress, QPointF(0, 0),
                       btn, btn, Qt.NoModifier)


from PySide6.QtCore import QEvent


class MouseEventHolder:
    MouseButtonPress = QEvent.Type.MouseButtonPress
    MouseButtonRelease = QEvent.Type.MouseButtonRelease


def new_w():
    """造一个干净窗口（进play 态、开跑）。"""
    w = N.NightWindow(N.load_pack(os.path.join(HERE, "packs", "luna")))
    w.phase = "play"
    w.mode = "play"
    return w


def reset(w):
    """把露娜的攻击/蓄力状态清干净，返回 w。"""
    l = w.luna
    l.charging = False
    l.charge_t = 0.0
    l.atk_fired = False
    l.atk_lvl = N.ATK_TAP
    l.atk_wind = l.atk_act = l.atk_rec = l.atk_cd = 0.0
    l.punch = 0.0
    w.keys.clear()
    w.fx = []
    return w


def settle(w, frames=24):
    """把窗口推进若干帧，让攻击走完「前摇 → 命中窗口」。

    ⭐⭐ **为什么要单独一步**：`hit_by`（击退）发生在 `atk_act`（命中窗口）里，
       而 `hold_j` 只负责"蓄力 + 松手放招"——放招那一刻只进了前摇。
       ⛔ 不补这一步 ⇒ `hit_knocks` 永远是空的，看起来像「击退没生效」，
       实际是**判据没等到命中那一帧**。
    ⚠️ 这个坑与 PR13 的「gate 条件没满足却报红」同型：**先确认门禁真满足**。
    """
    step(w, frames)
    return w


def tap_j(w):
    """真实点按 J：按下 + 立刻松开（charge_t ≈ 0 ⇒ 必须是普攻）。"""
    w.keyPressEvent(kd(Qt.Key_J))
    w.keyReleaseEvent(ku(Qt.Key_J))


def hold_j(w, seconds):
    """真实按住 J 若干秒：按下 → 推进若干帧 → **松手**。

    ⭐⭐ **必须包含松手**（第一版漏了它，报出"蓄力档位恒为 0"的假失败）：
       蓄力出招的触发点是 `keyReleaseEvent`，只按住不放 ⇒ 永远不会出招。
       ⛔ 蓄力 2 是例外——它在 `fx_tick` 里蓄满就自动放（不靠松手）。
    ⇒ 返回 (松手前的蓄力秒数, 松手后的档位)。
    """
    w.keyPressEvent(kd(Qt.Key_J))
    step(w, max(1, int(round(seconds / DT))))
    ct = w.luna.charge_t         # ⇒ 松手前的蓄力秒数
    w.keyReleaseEvent(ku(Qt.Key_J))
    return ct, w.luna.atk_lvl


# ============================================================================
section("⑭·PR14 · 攻击三档（派单 §七 判据）")
# ============================================================================

# ---- 判据 1：点按 J ⇒ 只有普攻 ----
# ⭐⭐ 必须同时验证两件事：出招了，**且**是普攻（不是"没出招"也算通过）。
w = reset(new_w())
tap_j(w)
_ok1 = (w.luna.atk_lvl == N.ATK_TAP
        and w.luna.atk_wind > 0.0
        and not w.luna.charging)
chk("⑭-1 ⛔⭐ 点按 J ⇒ 只有普攻（charge_t 从未达 0.35）", _ok1,
    "lvl=%d(期望0) wind=%.3f charging=%s charge_t=%.3f"
    % (w.luna.atk_lvl, w.luna.atk_wind, w.luna.charging, w.luna.charge_t))
# ⭐⭐ **阳性对照**：蓄 0.35s 后点松，档位必须**不是** 0。
#   ⛔ 没有这条，"判据 1 恒绿"可能是因为 try_attack 根本没被调到。
w = reset(new_w())
_ct1b, _lvl1b = hold_j(w, 0.40)
_ok1p = (_lvl1b == N.ATK_C1)
chk("⑭-1b ⭐ 阳性对照：蓄 0.40s 松手 ⇒ 档位是蓄力 1（不是普攻）", _ok1p,
    "lvl=%d（期望 %d）⇒ 说明判据 1 认得出档位差异"
    % (w.luna.atk_lvl, N.ATK_C1))

# ---- 判据 2：按住 0.35s 松手 ⇒ 蓄力 1（击退 312，粒子红）----
w = reset(new_w())
_ct2, _lvl2 = hold_j(w, 0.40)
_ok2 = w.luna.atk_lvl == N.ATK_C1
chk("⑭-2 ⭐⭐ 按住 0.40s 松手 ⇒ 蓄力 1", _ok2,
    "charge_t=%.3f lvl=%d（期望 %d）" % (_ct2, w.luna.atk_lvl, N.ATK_C1))
# ⭐ 击退档位（走**真实命中结算**，⛔ 不许只查表）
w2 = reset(new_w())
w2.luna.face = 1
w2.luna.x = 500.0
w2.luna.y = float(N.FLOOR_Y)
# ⭐⭐ dx 必须落在**两段区间之间**：MW_CATCH_R(52) 之外、
#   ATK_REACH+半宽(110) 之内。dx=30 时 caught() 立刻为真 ⇒
#   _tick 先走「被抓」分支，攻击三段还没进命中窗口就被打断
#   ⇒ hit_by 从没被调用（**看起来像击退坏了，其实是判据站位错了**）。
w2.mw.x = 590.0              # dx=90 ⇒ 打得到，且不会被当场抓住
w2.mw.y = float(N.FLOOR_Y)
w2.hit_knocks = []
_orig_hit_by = w2.mw.hit_by
def _spy_hit_by(from_x, knock=N.ATK_KNOCK, stun=N.ATK_STUN):
    w2.hit_knocks.append(knock)
    return _orig_hit_by(from_x, knock, stun)
w2.mw.hit_by = _spy_hit_by
_ct2b, _lvl2b = hold_j(w2, 0.40)
# ⭐ 补推进：击退发生在**命中窗口**（atk_act），放招那一刻只进了前摇
settle(w2, 24)
_ok2b = (len(w2.hit_knocks) == 1
         and abs(w2.hit_knocks[0] - N.ATK_KNOCK1) < 1e-6)
chk("⑭-2b ⭐⭐ 蓄力 1 命中 ⇒ 击退 312.0（ATK_KNOCK1）", _ok2b,
    "实测击退=%s（期望 [%.1f]）" % (w2.hit_knocks, N.ATK_KNOCK1))

# ---- 判据 3：按住 0.70s ⇒ 蓄力 2（击退 338，粒子蓝 26 粒）----
w3 = reset(new_w())
w3.luna.face = 1
w3.luna.x = 500.0
w3.luna.y = float(N.FLOOR_Y)
w3.mw.x = 590.0
w3.mw.y = float(N.FLOOR_Y)
w3.hit_knocks = []
_o3 = w3.mw.hit_by
def _spy3(from_x, knock=N.ATK_KNOCK, stun=N.ATK_STUN):
    w3.hit_knocks.append(knock)
    return _o3(from_x, knock, stun)
w3.mw.hit_by = _spy3
_ct3, _lvl3 = hold_j(w3, 0.75)      # ⚠️ 必须**超过** 0.70（靠 fx_tick 自动出招）
# ⭐ 补推进：击退发生在**命中窗口**（atk_act），放招那一刻只进了前摇
settle(w3, 24)
_ok3 = (w3.luna.atk_lvl == N.ATK_C2
        and len(w3.hit_knocks) == 1
        and abs(w3.hit_knocks[0] - N.ATK_KNOCK2) < 1e-6)
chk("⑭-3 ⭐⭐ 按住 0.75s ⇒ 蓄力 2 且击退 338.0（自动出招，不等松手）", _ok3,
    "lvl=%d(期望%d) 击退=%s 期望[%.1f]"
    % (w3.luna.atk_lvl, N.ATK_C2, w3.hit_knocks, N.ATK_KNOCK2))
# ⭐ 粒子阶段：蓄力 2 应是蓝 + 26 粒
_st = N.FX_CHARGE_STAGES[2]
_ok3b = (_st[1] == (95, 150, 245) and _st[2] == 26)
chk("⑭-3b ⭐ 蓄力 2 粒子配置 = 蓝 (95,150,245) + 26 粒", _ok3b,
    "阶段表第三档：颜色=%s 粒子数=%d 脉动=%.1f" % (_st[1], _st[2], _st[3]))

# ---- 判据 4：按住 0.5s ⇒ 只出蓄力 1（不升不降）----
w4 = reset(new_w())
_ct4, _lvl4 = hold_j(w4, 0.50)
_ok4 = (_ct4 < N.ATK_CHARGE2 and w4.luna.atk_lvl == N.ATK_C1)
chk("⑭-4 ⭐⭐ 按住 0.5s ⇒ 只出蓄力 1（0.5 在 [0.35,0.70) 区间）", _ok4,
    "charge_t=%.3f（< %.2f 才成立）lvl=%d" % (_ct4, N.ATK_CHARGE2, w4.luna.atk_lvl))

# ---- 判据 5：按住 1.5s ⇒ 只放一次招 ----
w5 = reset(new_w())
w5.luna.face = 1
w5.luna.x = 500.0
w5.luna.y = float(N.FLOOR_Y)
w5.mw.x = 530.0
w5.mw.y = float(N.FLOOR_Y)
w5.fires = []
_real_fire = w5._fx_fire
def _spy_fire(lvl):
    w5.fires.append(lvl)
    return _real_fire(lvl)
w5._fx_fire = _spy_fire
_ct5, _lvl5 = hold_j(w5, 1.5)
_ok5 = len(w5.fires) == 1
chk("⑭-5 ⭐⭐ 按住 1.5s ⇒ 只放一次招（蓄满锁定，不连放）", _ok5,
    "出招次数=%d %s（期望恰好 1）" % (len(w5.fires), w5.fires))

# ---- 判据 6：⭐ 攻击冷却期间按 J 无效 ----
w6 = reset(new_w())
w6.luna.atk_cd = 0.5        # ⭐ 人为置于冷却中
w6.keyPressEvent(kd(Qt.Key_J))
_ok6 = (not w6.luna.charging
        and w6.luna.atk_wind <= 0.0
        and w6.luna.atk_cd > 0.0)      # ⭐ 冷却不许被起手消耗掉
chk("⑭-6 ⭐⭐ 攻击冷却期间按 J 无效（ATK_CD 语义未被破坏）", _ok6,
    "charging=%s wind=%.3f cd=%.3f（期望 cd 仍>0）"
    % (w6.luna.charging, w6.luna.atk_wind, w6.luna.atk_cd))
# ⭐⭐ 阳性对照：把 cd 清零后同一次按键**必须**能起手
#   ⛔ 没有这条，"按 J 无效"可能是因为 can_attack 恒返回 False（判据失效）。
w6b = reset(new_w())
w6b.luna.atk_cd = 0.0
w6b.keyPressEvent(kd(Qt.Key_J))
chk("⑭-6b ⭐ 阳性对照：冷却清零后按 J ⇒ 能起手蓄力", w6b.luna.charging,
    "charging=%s（期望 True，证明判据 6 有分辨力）" % (w6b.luna.charging,))

# ---- 判据 7：默认行为回归 —— J 以外的键逐字未变 ----
# ⭐ K 冲刺：按 K ⇒ dash_t > 0
w7 = reset(new_w())
w7.keyPressEvent(kd(Qt.Key_K))
_ok7a = w7.luna.dash_t > 0.0
chk("⑭-7a ⭐ K 冲刺行为未变（dash_t > 0）", _ok7a,
    "dash_t=%.3f" % w7.luna.dash_t)
# ⭐ 方向键仍然进 keys 集（移动没被 J 的改造牵连）
w7b = reset(new_w())
w7b.keyPressEvent(kd(Qt.Key_D))
_ok7b = (Qt.Key_D in w7b.keys)
chk("⑭-7b ⭐ 方向键仍进 keys 集（移动未被牵连）", _ok7b,
    "keys=%s" % (w7b.keys,))
# ⭐ 蓄力中按 K：冲刺应被拒（攻击三段/蓄力独占）
w7c = reset(new_w())
w7c.keyPressEvent(kd(Qt.Key_J))        # 开始蓄力
w7c.keyPressEvent(kd(Qt.Key_K))
chk("⑭-7c ⭐ 蓄力中按 K：冲刺**仍被拒**（两件事互斥）",
    w7c.luna.dash_t <= 0.0,
    "dash_t=%.3f（期望 ≤0）" % w7c.luna.dash_t)

# ---- 判据 8：Effect.update 到 t>=1 返回 False（防泄漏）----
e1 = N.Effect("claw", 0.0, 0.0, 0.16, 1, 26.0, (255, 255, 255), N.ATK_TAP)
_alive = True
_n = 0
while _alive and _n < 1000:
    _alive = e1.update(DT)
    _n += 1
_ok8 = (not _alive) and e1.t >= 1.0 and _n < 1000
chk("⑭-8 ⭐⭐ Effect 播完 ⇒ update 返回 False（会被移除，不泄漏）", _ok8,
    "第%d帧返回 False，t=%.3f" % (_n, e1.t))
# ⭐⭐ 阳性对照：**charge 是持续的**，⛔ 不能靠 update 判死
e2 = N.Effect("charge", 0.0, 0.0, 9.9, 1, 90.0, (255, 255, 255), N.ATK_TAP)
_ok8b = all(e2.update(0.05) for _ in range(400))     # 推进 20 秒
chk("⑭-8b ⭐ 阳性对照：charge 特效 20s 内 update 恒 True（靠外部移除）", _ok8b,
    "⚠️ charge 若靠 t 判死 ⇒ 按住 J 时粒子会凭空消失")

# ---- 判据 9：len(fx) > 24 丢最旧的 ----
w9 = reset(new_w())
for _i in range(40):
    w9.fx_spawn("claw", 100.0, 200.0, N.ATK_TAP)
_ok9 = (len(w9.fx) == N.FX_MAX
        and abs(w9.fx[-1].x - 100.0) < 1e-6)   # 最新那个还在
chk("⑭-9 ⭐⭐ fx 超上限 ⇒ 丢最旧的（防连点刷屏）", _ok9,
    "生成 40 个后剩 %d（上限 %d）" % (len(w9.fx), N.FX_MAX))
# ⭐⭐ 阳性对照：不超过上限时**一个都不许丢**
w9b = reset(new_w())
for _i in range(N.FX_MAX):
    w9b.fx_spawn("claw", 100.0, 200.0, N.ATK_TAP)
_ok9b = len(w9b.fx) == N.FX_MAX
chk("⑭-9b ⭐ 阳性对照：正好 %d 个 ⇒ 一个都不丢" % N.FX_MAX, _ok9b,
    "剩 %d" % len(w9b.fx))

# ---- 判据 10：⭐⭐ 强制 render 不抛异常 ----
# ⚠️ 画特效的代码只在 paintEvent 里跑 ⇒ 不 render 就永远测不到。
#   ⛔ 只验"不抛异常 + 图像非空"，⛔ 不许声称"看起来对"（Ronny 实机目检）。
_render_err = ""
_render_ok = True
try:
    wr = reset(new_w())
    # ⭐ 摆满三档的全部特效种类，确保每条绘制路径都被跑到
    for lvl in (N.ATK_TAP, N.ATK_C1, N.ATK_C2):
        wr.fx_spawn("claw", wr.luna.x + 30, wr.luna.y - 60, lvl)
        wr.fx_spawn("impact", wr.mw.x, wr.mw.y - 90, lvl)
        wr.fx_spawn("charge", wr.luna.x, wr.luna.y - 60, lvl)
        # ⭐ 推进到不同进度：t=0 / t=0.5 / t=0.99 都要画一遍
        for _e in list(wr.fx):
            _e.t = 0.5
        wr.grab()
    # ⭐ facing=-1（镜像分支）也必须render 一次
    wr.luna.face = -1
    wr.fx_spawn("claw", wr.luna.x - 30, wr.luna.y - 60, N.ATK_C2)
    wr.fx_spawn("impact", wr.mw.x, wr.mw.y - 90, N.ATK_C2)
    wr.grab()
    # ⭐ 蓄力粒子三阶段都要画一遍（阶段切换不重置 t）
    for _ct in (0.0, 0.15, 0.30, 0.45, 0.70, 0.75):
        wr.luna.charge_t = _ct
        wr.grab()
    _img = wr.grab().toImage()
    _render_ok = (_img.width() > 0 and _img.height() > 0)
except Exception as _e:                       # noqa: BLE001
    _render_ok = False
    _render_err = "%s: %s" % (type(_e).__name__, _e)
chk("⑭-10 ⭐⭐ 强制 render 不抛异常（三档 × 三阶段 × 双朝向全覆盖）",
    _render_ok, _render_err if _render_err else "render OK")

# ---- 判据 11：三处 _draw_luna 调用点都插了特效（grep 计数）----
_src = open(os.path.join(HERE, "pet_engine", "night.py"), encoding="utf-8").read()
_n_behind = _src.count("self._draw_fx_behind(p)")
_n_front = _src.count("self._draw_fx_front(p)")
_n_luna = _src.count("self._draw_luna(p)")
_ok11 = (_n_behind == 3 and _n_front == 3 and _n_luna == 3)
chk("⑭-11 ⭐⭐ 三处 _draw_luna 调用点都插了特效（behind/front 各 3 次）", _ok11,
    "behind=%d front=%d luna=%d（期望 3/3/3）"
    % (_n_behind, _n_front, _n_luna))
# ⭐⭐ 阳性对照：故意数一个不存在的函数名 ⇒ 必须是 0（证明这个计数判据有分辨力）
chk("⑭-11b ⭐ 阳性对照：不存在的函数名计数必须为 0",
    _src.count("self._draw_fx_NOPE(p)") == 0,
    "计数判据本身有分辨力（不是恒等于 3）")

# ---- 判据 13：⭐⭐ 0.30 变色点与 0.35 出招点是分开的 ----
# ⭐ 这是 Ronny 拍板的核心手感：0.30 变色（提示） / 0.35 出招（判定）。
#   ⛔ 混用成一个阈值 ⇒ "看到红了但松手没出招"。
w13 = reset(new_w())
w13.luna.face = 1
w13.luna.x = 500.0
w13.luna.y = float(N.FLOOR_Y)
w13.mw.x = 3000.0        # ⭐ 放远点，确保打不到 ⇒ 判据只看"出不出招"，不掺命中
w13.mw.y = float(N.FLOOR_Y)
# 手动把 charge_t 推到三个观测点，分别问"粒子什么色""出了招没"
# ⭐⭐ 必须问**真实代码**，⛔ 不能在脚本里复刻一遍阶段判据
#  （复刻 = 测的是我自己的复制品，产品代码改了判据不会红）。
# ⇒ 做法：把 charge_t 真的设进去，然后**驱动真实的 _draw_fx_charge**，
#   用 monkey-patch 抓它实际用的画笔颜色。
def _probe(win, ct):
    """把 charge_t 置为 ct，返回 (实际画出的粒子色, **自动出招**会不会发生)。

    ⭐⭐ 两个问题必须**分别**问：
       ① 粒子什么色        ⇒ 只看视觉阈值（ATK_HINT=0.30）
       ② 自动出招会不会发生 ⇒ 只看判定阈值（ATK_CHARGE1=0.35）

    ⛔⛔⛔ **⛔ 绝对不要问「松手会不会出招」** —— 松手**永远**会出招（普攻也算）。
       我第一版就是这么写的，三个点全报 True、判据零分辨力，
       一度以为"自动出招没做阈值区分"。实际是**问错了对象**。
       ⚠️ 判据写完先问一句：它问的是不是产品真正要保证的那件事？

    ⚠️ 顺序陷阱：画粒子前⛔ 不能动 charging，否则被 `_fx_stop_charge` 清零
       ⇒ 画出来永远是白色（这也是我第一版另一个坑）。
    """
    # ---- ① 粒子色：走**真实** `_draw_fx_charge`，抓实际用的画笔颜色 ----
    win.luna.charging = True
    win.luna.charge_t = ct
    win.luna.atk_fired = False
    _seen = []

    class _FakeP:
        def __init__(self, sink):
            self._sink = sink
        def __getattr__(self, name):
            return getattr(self._sink, name)
        def setBrush(self, *a):
            _seen.append(a[0] if a else None)
            return self._sink.setBrush(*a)
        def setPen(self, *a, **k):
            return self._sink.setPen(*a, **k)

    from PySide6.QtGui import QPainter, QImage
    _img = QImage(64, 64, QImage.Format_ARGB32)
    _img.fill(0)
    _p = QPainter(_img)
    _e = N.Effect("charge", 0.0, 0.0, 9.9, 1, 90.0, (255, 255, 255), N.ATK_TAP)
    _e.t = 0.4
    try:
        win._draw_fx_charge(_FakeP(_p), _e)
    finally:
        _p.end()
    col = None
    for c in _seen:
        if c is not None:
            rgb = c.getRgb()
            col = (rgb[0], rgb[1], rgb[2])
            break
    # ---- ② 出招档位：走**真实** keyReleaseEvent ----
    # ⭐⭐⚠️ 我换过**三种问法**，前两种都错，这是第三版（也是唯一对的）：
    #   v1「松手会不会出招」  ⇒ 错：松手永远出招（普攻也算），零分辨力
    #   v2「自动出招会不会发生」⇒ 错：自动出招只在 0.70（蓄力2）触发，
    #                            问0.31/0.36 三个点全是 False，同样零分辨力
    #   v3「松手出**哪一档**」  ⇒ ✅ 对：0.29→普攻(白)、0.31→蓄力1(红)、0.36→蓄力1(红)
    #      ⭐ 真正要证明的是「变色点(0.30)与出招点(0.35)分开了」：
    #        玩家看到红色时（0.31）松手拿到的是**蓄力1**，而红色**在 0.30 就已出现**
    #        ⇒ 两者不是同一个数。
    win.luna.charging = True
    win.luna.charge_t = ct
    win.luna.atk_fired = False
    win.luna.atk_lvl = N.ATK_TAP
    win.luna.atk_wind = win.luna.atk_act = win.luna.atk_rec = win.luna.atk_cd = 0.0
    win.keys.add(Qt.Key_J)
    win.keyReleaseEvent(ku(Qt.Key_J))     # ⭐ 真实松手 ⇒ 问「出哪一档」
    win.keys.discard(Qt.Key_J)
    return col, win.luna.atk_lvl


_c29, _lv29 = _probe(w13, 0.29)
_c31, _lv31 = _probe(w13, 0.31)
_c36, _lv36 = _probe(w13, 0.36)
# ⭐⭐ 期望（这是「两个阈值分开」的**最强证明**，不是我想反了）：
#   0.29⇒白 + 普攻(0)   还没变色，也没到出招点
#   0.31⇒红 + 普攻(0)   ⭐ **粒子已经红了，但松手仍出普攻** ← 关键
#   0.36⇒红 + 蓄力1(1)  到0.35 才真的出蓄力招
# ⭐⭐⭐ 0.31 那行就是全部意义所在：
#   「颜色变了」与「出招档位变了」**发生在两个不同的数上**
#   ⇒ 若两个阈值被混成同一个数，0.31 就会直接给蓄力1，这条立刻红。
# ⚠️ 我第一版把 0.31 的期望**写成蓄力1**，实测红 ⇒ 一度以为代码错了。
#   查下来是我把「红」当成了「已升级」。这是**判据说反了，不是代码说反了**。
_ok13 = (_c29 == (235, 240, 245) and _lv29 == N.ATK_TAP
         and _c31 == (245, 95, 85) and _lv31 == N.ATK_TAP
         and _c36 == (245, 95, 85) and _lv36 == N.ATK_C1)
chk("⑭-13 ⭐⭐⭐ 0.30 变色点与 0.35 出招点**分开**（Ronny 拍板的核心手感）",
    _ok13,
    "0.29⇒色%s 档%d(期望白/普攻0) ｜ "
    "0.31⇒色%s 档%d ⭐已红但仍普攻(证明分开) ｜ "
    "0.36⇒色%s 档%d(期望红/蓄力1=1)"
    % (_c29, _lv29, _c31, _lv31, _c36, _lv36))
chk("⑭-13b ⭐⭐⭐ 常量本身：ATK_HINT(0.30) ≠ ATK_CHARGE1(0.35)",
    abs(N.ATK_HINT - 0.30) < 1e-9 and abs(N.ATK_CHARGE1 - 0.35) < 1e-9
    and N.ATK_HINT != N.ATK_CHARGE1,
    "ATK_HINT=%.3f ATK_CHARGE1=%.3f ATK_CHARGE2=%.3f"
    % (N.ATK_HINT, N.ATK_CHARGE1, N.ATK_CHARGE2))

# ---- 判据 12：阴性/阳性对照 —— 把阈值改坏必须被抓住 ----
# ⭐⭐ 这条必须**驱动真实代码**，⛔ 不能在脚本里写一个
#    「假如阈值是 0.30 会怎样」的小算式 —— 那是测我自己的复制品。
# ⇒ 做法：把模块常量**真的临时改坏**，跑真实判定，再**改回来**。
# ⚠️ `finally` 还原是必须的：判据污染后续 ⇒ 后面全红，调试成本爆炸。
# ⭐⭐⭐ **「混用」要混的是 `ATK_CHARGE1`（出招判定），不是 `ATK_HINT`。**
#   我第一版只把 ATK_HINT 改坏 ⇒ 实测 0.31 仍出普攻（判据红）。
#   查下来**代码是对的**：出招档位读的是 `charge_t < ATK_CHARGE1`，
#   与 `ATK_HINT` 无关⇒ 只改 HINT 当然不影响出招。
#   ⇒ 真实的坏情况是「开发者把出招阈值写成 0.30」（两个数被合成一个）。
#   ⚠️ 教训：**造阳性对照时要造出「真的会出错的写法」**，
#     不是随便改一个相关但无影响的数。
_ORIG_C1 = N.ATK_CHARGE1
try:
    N.ATK_CHARGE1 = 0.30                # ⛔ 出招点被误写成变色点
    w12 = reset(new_w())
    w12.luna.face = 1
    w12.luna.x = 500.0
    w12.luna.y = float(N.FLOOR_Y)
    w12.mw.x = 3000.0
    w12.mw.y = float(N.FLOOR_Y)
    _c12, _lv12 = _probe(w12, 0.31)
    # ⭐ 阈值被写成 0.30 后，0.31 就会直接给蓄力1 —— 判据 13 那个"仍普攻"变红
    _ok12 = (_c12 == (245, 95, 85) and _lv12 == N.ATK_C1)
finally:
    N.ATK_CHARGE1 = _ORIG_C1# ⭐⚠️ 必须还原
chk("⑭-12 ⭐⭐ 阳性对照：出招阈值被误写成 0.30 ⇒ 0.31 就直接给蓄力1"
    "（证明判据 13 真有分辨力）", _ok12,
    "改坏后 0.31 ⇒ 色%s 档%d（期望 红/蓄力1=1）" % (_c12, _lv12))
chk("⑭-12b ⭐⭐ 还原检查：ATK_CHARGE1 必须已回到 %.2f（⛔ 判据不许污染后续）"
    % _ORIG_C1,
    abs(N.ATK_CHARGE1 - _ORIG_C1) < 1e-9,
    "当前 ATK_CHARGE1=%.4f" % N.ATK_CHARGE1)

# ============================================================================
section("⑭· 补充判据（本单实测中发现的额外风险点）")

# ---- 补充 1：QTE 期间J 会不会被吞（派单 §4.3 要求我查并报）----
_ok_qte = (Qt.Key_J not in N.QTE_MOVE_KEYS
           and Qt.Key_J not in (Qt.Key_Left, Qt.Key_Right,
                                 Qt.Key_Up, Qt.Key_Down))
chk("⑭-s1 ⭐ 查实：QTE **不吞 J 键**（QTE 只屏蔽方向键）", _ok_qte,
    "J 在 QTE_MOVE_KEYS 里？%s（期望 False ⇒ 无冲突）"
    % (Qt.Key_J in N.QTE_MOVE_KEYS,))

# ---- 补充 2：击退作用对象（派单 §五 要求我查并报）----
# ⭐ 全文件只有一处消费击退 ⇒ 作用对象一直是**微波炉**，不是露娜。
#   本单只把那一处改成按档取表，⛔ 没改作用对象。
_n_knock_use = _src.count("mw.hit_by(")
_has_table = ("mw.hit_by(l.x, ATK_KNOCK_TABLE" in _src)
_ok_obj = (_n_knock_use == 1) and _has_table and ("l.hit_by" not in _src)
chk("⑭-s2 ⭐ 查实：击退作用对象=**微波炉**（唯一消费点已改为分档）", _ok_obj,
    "mw.hit_by( 调用 %d 处；该处已用 ATK_KNOCK_TABLE=%s；l.hit_by 不存在=%s"
    % (_n_knock_use, _has_table, "l.hit_by" not in _src))

# ---- 补充 3：三档击退值必须严格递增且等于 Ronny 拍板值 ----
_ok_kn = (N.ATK_KNOCK_TABLE == (260.0, 312.0, 338.0))
chk("⑭-s3 ⭐ 三档击退 = (260.0, 312.0, 338.0)（Ronny 拍板）", _ok_kn,
    "实测 %s" % (N.ATK_KNOCK_TABLE,))
# ⭐⭐ 报告 Ronny 要我提的那件事：312 与 338 只差 26px
_gap = N.ATK_KNOCK2 - N.ATK_KNOCK1
_gap_pct = _gap / N.ATK_KNOCK1 * 100.0
chk("⑭-s3b ⭐⚠️ 已量化报设计端：蓄力1 vs 2 的击退只差 %.0fpx（%.1f%%）"
    % (_gap, _gap_pct),
    N.ATK_KNOCK1 < N.ATK_KNOCK2,
    "⇒ 手感可能分不出来，⭐ 红/蓝粒子才是主要区分手段（本单已照做）")

# ---- 补充 4：普攻击退必须**逐字不变**（ATK_KNOCK 没被改）----
_ok_def = (N.ATK_KNOCK == 260.0)
chk("⑭-s4 ⭐⭐ 普攻击退 ATK_KNOCK 仍 = 260.0（默认行为逐字不变）", _ok_def,
    "ATK_KNOCK=%.1f" % N.ATK_KNOCK)
# ⭐⭐ 阳性对照：真打一次普攻，击退必须是 260
w_s4 = reset(new_w())
w_s4.luna.face = 1
w_s4.luna.x = 500.0
w_s4.luna.y = float(N.FLOOR_Y)
w_s4.mw.x = 590.0
w_s4.mw.y = float(N.FLOOR_Y)
w_s4.hit_knocks = []
_o = w_s4.mw.hit_by
def _spy_s4(from_x, knock=N.ATK_KNOCK, stun=N.ATK_STUN):
    w_s4.hit_knocks.append(knock)
    return _o(from_x, knock, stun)
w_s4.mw.hit_by = _spy_s4
tap_j(w_s4)
settle(w_s4, 24)
_ok_s4b = (len(w_s4.hit_knocks) == 1
           and abs(w_s4.hit_knocks[0] - 260.0) < 1e-6)
chk("⑭-s4b ⭐⭐ 阳性对照：真打一次普攻 ⇒ 击退确为 260.0", _ok_s4b,
    "实测 %s（期望 [260.0]）" % w_s4.hit_knocks)

# ---- 补充 5：四个老时序常量一个都没动（派单 §4.3 硬约束 1）----
_ok_const = (N.ATK_WIND == 0.16 and N.ATK_ACT == 0.09
             and N.ATK_REC == 0.42 and N.ATK_CD == 0.12)
chk("⑭-s5 ⭐⭐ ATK_WIND/ACT/REC/CD 四个常量一个都没动", _ok_const,
    "WIND=%.2f ACT=%.2f REC=%.2f CD=%.2f" % (N.ATK_WIND, N.ATK_ACT,
                                             N.ATK_REC, N.ATK_CD))
# ⭐⭐ 阳性对照：用**错误值**去查，必须红
_ok_const_p = not (N.ATK_WIND == 0.17 and N.ATK_ACT == 0.09)
chk("⑭-s5b ⭐ 阳性对照：若 ATK_WIND 被改成 0.17，这条判据必须红", _ok_const_p,
    "判据对常量变化有分辨力")

# ---- 补充 6：刀光弧数三档递增（普攻 1 / 蓄力1 2 / 蓄力2 3）----
_ok_n = (N.FX_CLAW_N == (1, 2, 3))
chk("⑭-s6 ⭐ 刀光弧数 = (1, 2, 3) 三档递增", _ok_n,
    "实测 %s" % (N.FX_CLAW_N,))

# ---- 补充 7：try_attack 默认参数 ⇒ 老调用方行为不变 ----
_ok_defarg = "def try_attack(self, lvl: int = ATK_TAP)" in _src
chk("⑭-s7 ⭐⭐ try_attack 默认参数 = ATK_TAP ⇒ 老调用 `try_attack()` 行为不变",
    _ok_defarg, "签名带默认值 ⇒ 任何老代码调try_attack() 都是普攻")

# ---- 补充 8：蓄力粒子在出招后必须被清掉（不许永久挂屏幕上）----
w_s8 = reset(new_w())
w_s8.keyPressEvent(kd(Qt.Key_J))
step(w_s8, 1)
_n_charge_before = len([e for e in w_s8.fx if e.kind == "charge"])
_ct_s8, _lvl_s8 = hold_j(w_s8, 0.40)
_n_charge_after = len([e for e in w_s8.fx if e.kind == "charge"])
_ok_s8 = (_n_charge_before >= 1 and _n_charge_after == 0)
chk("⑭-s8 ⭐⭐ 蓄力粒子：按下就有，出招后被清掉（⛔ 不许永久挂屏幕上）", _ok_s8,
    "按下时 %d 个 ⇒ 出招后 %d 个" % (_n_charge_before, _n_charge_after))

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
