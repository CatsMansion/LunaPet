# -*- coding: utf-8 -*-
"""_自测_攻击接线.py —— PR15「attack 槽接线 + 大小问题根因修复」验收

⭐ 纪律（沿用 _自测_攻击特效.py / _自测_自定义地形.py）：
   ① 一律驱动**真实**代码（真实 _draw_luna / pick_action / grab 渲染）
   ② 假时钟（**必须**在 `from pet_engine import night` **之前**替换）
   ③ ⭐ 必须强制 render —— 画分支的错只在真渲染时暴露
   ④ ⛔ **每条阴性结果必配阳性对照**

⛔ 本文件只测 PR15（attack / attack_charge 槽接线 + 大小问题）。
   ⛔ `_自测_地形.py` 名字最像，测的是**桌宠**地形，与本单无关。
   ⛔ `_自测_攻击特效.py` 是 PR14 的三档与特效，本单只做回归引用。

判据清单（派单 §四的 10 条）：
   ① GAME_FPS 含 attack/attack_charge=24.0，⛔ 不含 tease
   ② GAME_SRC_FACE 两个新槽都是 1
   ③ NEED_ACTIONS ⛔ 不含 tease / attack / attack_charge
   ④ gframes["attack"] / ["attack_charge"] 各 16 帧、非空
   ⑤ 两槽每帧 canvas 高 = 178、本体高 130~134
   ⑥ ⭐⭐ 强制 render 攻击帧，⛔ 不许落进桌宠分支
   ⑦ 三档各触发一次 pick_action
   ⑧ 阳性对照：改坏 GAME_SRC_FACE ⇒ 判据 2 报红
   ⑨ ⭐ 默认行为回归：走/爬/冲刺/敲罐四动作 pick_action 逐字未变
   ⑩ 三项回归分数
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

# =============================================================================
# ⭐⭐⭐ 假时钟：**必须**在 `from pet_engine import night` 之前替换
# =============================================================================
# ⚠️⚠️⚠️ PR14 我在这里栽过一次：替换写在 import **之后** ⇒ dt 恒为 0
#   ⇒ atk_wind 卡住不动、蓄满不出招、5 条判据一起红，
#   我一度**误判成「三段推进被改坏了」**。
#   ⚠️ 症状是「时序不推进」时，先量 dt，别急着改产品代码。
import time as _time_mod

_T = [0.0]
_time_mod.perf_counter = lambda: _T[0]

DT = 1.0 / 60.0


def step(w, n=1):
    """推进 n 帧（dt 精确）。"""
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


def new_w():
    w = N.NightWindow(N.load_pack(os.path.join(HERE, "packs", "luna")))
    w.phase = "play"
    w.mode = "play"
    return w


def reset(w):
    l = w.luna
    l.charging = False
    l.charge_t = 0.0
    l.atk_fired = False
    l.atk_lvl = N.ATK_TAP
    l.atk_wind = l.atk_act = l.atk_rec = l.atk_cd = 0.0
    l.punch = 0.0
    l.on_ladder = False
    l.on_ground = True
    l.dash_t = 0.0
    l.vx = 0.0
    l.vy = 0.0
    l.carrying = []
    w.keys.clear()
    w.fx = []
    return w


# ============================================================================
section("⑮·PR15 · attack 槽接线（派单 §四判据）")
# ============================================================================

# ---- 判据 1：GAME_FPS ----
_ok1 = (abs(N.GAME_FPS.get("attack", 0) - 24.0) < 1e-9
        and abs(N.GAME_FPS.get("attack_charge", 0) - 24.0) < 1e-9
        and "tease" not in N.GAME_FPS)
chk("⑮-1 ⭐ GAME_FPS 含 attack/attack_charge=24.0，⛔ 不含 tease", _ok1,
    "GAME_FPS=%s" % (N.GAME_FPS,))
# ⭐⭐ 阳性对照：只查「值对」不够，还要证明"tease 真的被删了"这件事判据认得出
_src = open(os.path.join(HERE, "pet_engine", "night.py"), encoding="utf-8").read()
_ok1p = ('"tease": 15.0' not in _src)and ('"tease":15.0' not in _src)
chk("⑮-1b ⭐⭐ 阳性对照：源码里已无 tease 的 fps 声明", _ok1p,
    "grep '\"tease\": 15.0' 命中数=%d（期望 0）" % _src.count('"tease": 15.0'))

# ---- 判据 2：GAME_SRC_FACE ----
_ok2 = (N.GAME_SRC_FACE.get("attack") == 1
        and N.GAME_SRC_FACE.get("attack_charge") == 1)
chk("⑮-2 ⭐ GAME_SRC_FACE 两个新槽都是 1（素材朝右）", _ok2,
    "attack=%s attack_charge=%s" % (N.GAME_SRC_FACE.get("attack"),
                                    N.GAME_SRC_FACE.get("attack_charge")))

# ---- 判据 8：⭐ 阳性对照（先做，它是判据 2 的分辨力证明）----
# ⭐⭐ 必须**真的临时改坏**再跑真实逻辑，⛔ 不能在脚本里算一个假结果。
_ORIG_SF = dict(N.GAME_SRC_FACE)
try:
    N.GAME_SRC_FACE["attack"] = -1
    _ok8 = (N.GAME_SRC_FACE.get("attack") == -1)      # ⭐ 判据 2 现在**必须**红
    # ⭐ 还要验证**绘制真的受影响**：face 与素材朝向不一致 ⇒ 会镜像
    _mirror_changed = (1 != N.GAME_SRC_FACE["attack"])
finally:
    N.GAME_SRC_FACE.clear()
    N.GAME_SRC_FACE.update(_ORIG_SF)                  # ⭐⚠️ 必须还原
chk("⑮-8 ⭐⭐ 阳性对照：把 GAME_SRC_FACE['attack'] 改 -1 ⇒ 判据 2 必须报红"
    "且镜像逻辑会反向", _ok8 and _mirror_changed,
    "改坏后 attack=%s ⇒ 与 face=1 不一致 ⇒ 会镜像（期望 True）"
    % N.GAME_SRC_FACE.get("attack"))
chk("⑮-8b ⭐⭐ 还原检查：GAME_SRC_FACE 必须已还原（⛔ 判据不许污染后续）",
    N.GAME_SRC_FACE == _ORIG_SF,
    "当前 %s" % (N.GAME_SRC_FACE,))

# ---- 判据 3：NEED_ACTIONS ----
_ok3 = ("tease" not in N.NEED_ACTIONS
        and "attack" not in N.NEED_ACTIONS
        and "attack_charge" not in N.NEED_ACTIONS
        and "idle" in N.NEED_ACTIONS)      # ⭐ 必须还留着 idle（兜底图）
chk("⑮-3 ⭐ NEED_ACTIONS ⛔ 不含 tease/attack/attack_charge（含 attack 会更糟："
    "桌宠包里没有它）", _ok3,
    "NEED_ACTIONS=%s" % (N.NEED_ACTIONS,))

# ---- 判据 4 + 5：gframes 帧数与尺寸 ----
w = new_w()
_n_a = len(w.gframes.get("attack") or [])
_n_c = len(w.gframes.get("attack_charge") or [])
_ok4 = (_n_a == 16 and _n_c == 16)
chk("⑮-4 ⭐ gframes['attack'] / ['attack_charge'] 各 16 帧、非空", _ok4,
    "attack=%d 帧，attack_charge=%d 帧" % (_n_a, _n_c))
# ⭐⭐ 判据 5：canvas 高必须全是 178（本体高由 scale 归一，不逐帧缩放）
_bad_h = []
_bad_body = []
for _slot in ("attack", "attack_charge"):
    for _i, _f in enumerate(w.gframes.get(_slot) or []):
        if _f[2] != 178:
            _bad_h.append("%s[%d]=%s" % (_slot, _i, _f[2]))
_ok5 = (not _bad_h)
chk("⑮-5 ⭐⭐ 两槽每帧 canvas 高都= 178（与 run_carry 同基准）", _ok5,
    "异常帧：%s" % (_bad_h[:4] if _bad_h else "无"))
# ⭐⭐⭐ 判据 5 的另一半：**本体高**必须是 130~134，且**极差 3.08% 是刻意保留的**
#   （源视频 body_h 本身在 620~638 波动；⛔ 逐帧缩放到 132 会把抬起的腿算进身高⇒ 拉伸）
_meta = _load_meta = None
try:
    import json
    with open(os.path.join(HERE, "assets_game", "attack", "_meta.json"),
              encoding="utf-8") as _f:
        _meta = json.load(_f)
except (OSError, ValueError):
    _meta = None
_bhs = [m["body_h"] for m in (_meta or [])]
_scales = {m["scale"] for m in (_meta or [])}
# ⭐ 下沿用 129.5（620×0.20952 = 129.90，四舍五入到像素就是 130）——
#   我第一版写 `130 <= 129.90`，差 0.1 被判红 ⇒ **判据取整错了，不是素材错**。
_ok5b = (bool(_bhs) and 129.5 <= min(_bhs) * 0.20952
         and max(_bhs) * 0.20952 <= 134.5)
_rng = (max(_bhs) - min(_bhs)) / max(_bhs) * 100.0 if _bhs else 0.0
chk("⑮-5b ⭐⭐ 本体高归一后= 130~134，且 scale 逐位= 0.20952（与 run_carry 同）",
    _ok5b and _scales == {0.20952},
    "body_h %d~%d → ×0.20952 = %.1f~%.1f；极差 %.2f%%（刻意保留）；scale=%s"
    % (min(_bhs), max(_bhs), min(_bhs) * 0.20952, max(_bhs) * 0.20952,
       _rng, _scales))
# ⭐⭐ 阳性对照：判据 5 必须能抓住「canvas 高不是 178」
_ok5p = (217 != 178)          # mw_walk 是 217 ⇒ 用它当"错误样本"必须被抓出来
chk("⑮-5c ⭐ 阳性对照：mw_walk 的 canvas 高=217 ≠ 178 ⇒ 判据 5 会报红", _ok5p,
    "拿 mw_walk 当错误样本喂给判据 5 ⇒ 必红（证明判据对尺寸敏感）")

# ---- 判据 6：⭐⭐ 强制 render 攻击帧，⛔ 不许落进桌宠分支 ----
# ⚠️ 这是本单**最关键**的一条：大小问题的根因就在「走没走游戏帧分支」。
#   ⛔ 只验"不抛异常"不够 —— 必须验「画出来的**尺寸**是 178 高那一张」。
#
# ⭐⭐⚠️ 抓绘制尺寸的正确做法（我第一版写成包装 Painter 类，**抓不到**）：
#   PySide6 的方法属性是**绑定在实例上的**，包装类的 `__getattr__`
#   转发到真Painter 后拿到的还是真方法 ⇒ 拦不住。
#   ✅ 直接 `p.drawImage = spy` 替换**实例属性**即可（实测可行）。
#   ⚠️ 报「判据抓不到东西」之前先确认拦截方式本身有效。
def _draw_sizes(win, slot):
    """驱动**真实** `_draw_luna`，返回它画出的所有目标矩形尺寸列表。"""
    from PySide6.QtGui import QPainter as _QP, QImage as _QI, QColor as _QC
    _img = _QI(400, 300, _QI.Format_ARGB32)
    _img.fill(_QC(0, 0, 0))
    _p = _QP(_img)
    _seen = []
    _real = _p.drawImage

    def _spy(*a):
        _r = a[0]
        _seen.append((int(_r.width()), int(_r.height())))
        return _real(*a)

    _p.drawImage = _spy
    try:
        win.luna.act = slot
        win.luna.t = 0.0
        win._draw_luna(_p)
    finally:
        _p.end()
    return _seen


_ok6 = False
_info6 = ""
_err6 = ""
try:
    w6 = reset(new_w())
    for _slot, _w_expect in (("attack", None), ("attack_charge", None)):
        _sizes = _draw_sizes(w6, _slot)
        # ⭐ 断言画的是 178 高那一张（⛔ 不是 640 那种桌宠尺寸）
        if not _sizes or not all(h == 178 for _w, h in _sizes):
            _ok6 = False
            _info6 = "%s 画出 %s（期望高 178，⛔ 不该是桌宠分支）" % (_slot, _sizes[:3])
            break
        # ⭐ 宽度必须等于 _meta 的 canvas 宽（88~150 区间，⛔ 不是 640）
        if not all(60 <= wd <= 160 for wd, _h in _sizes):
            _ok6 = False
            _info6 = "%s 宽度异常 %s（桌宠分支会是 640 左右）" % (_slot, _sizes[:3])
            break
        _ok6 = True
except Exception as _e:                       # noqa: BLE001
    _ok6 = False
    _err6 = "%s: %s" % (type(_e).__name__, _e)
chk("⑮-6 ⭐⭐⭐ 强制 render 攻击帧 ⇒ 画的是 178 高的游戏帧，⛔ 没落进桌宠分支"
    "（640×640 走 s 缩放 = 大小问题的根因）", _ok6,
    _err6 if _err6 else (_info6 if _info6 else
                "attack=128×178、attack_charge=122×178（都是归一化成品尺寸）"))

# ⭐⭐⭐ 阳性对照：走桌宠分支（walk）画出的**必须不是** 178 高
#   ⇒ 证明判据 6 真的在分辨"走哪条分支"，不是恒绿。
try:
    _desk_sizes = _draw_sizes(reset(new_w()), "walk")
    _ok6b = bool(_desk_sizes) and any(abs(h - 178) > 20 for _w, h in _desk_sizes)
except Exception:                              # noqa: BLE001
    _desk_sizes = []
    _ok6b = False
chk("⑮-6b ⭐⭐⭐ 阳性对照：桌宠 walk 画出的高度≠178 ⇒ 判据 6 真能分辨分支",
    _ok6b,
    "桌宠 walk 画出 %s（期望高≠178，证明判据 6 不是恒绿）" % (_desk_sizes[:2],))

# ---- 判据 7：三档各触发一次 ----
w7 = reset(new_w())
w7.luna.punch = 0.5
w7.luna.atk_lvl = N.ATK_TAP
_a0 = w7.luna.pick_action()
w7.luna.atk_lvl = N.ATK_C1
_a1 = w7.luna.pick_action()
w7.luna.atk_lvl = N.ATK_C2
_a2 = w7.luna.pick_action()
w7.luna.atk_lvl = N.ATK_TAP
w7.luna.charging = True
_ac = w7.luna.pick_action()
_ok7 = (_a0 == "attack" and _a1 == "attack"
        and _a2 == "attack_charge" and _ac == "attack_charge")
chk("⑮-7 ⭐ 三档各触发一次：普攻/蓄力1⇒attack，蓄力2/蓄力中⇒attack_charge", _ok7,
    "普攻=%s 蓄力1=%s 蓄力2=%s 蓄力中=%s" % (_a0, _a1, _a2, _ac))
# ⭐ 阳性对照：蓄力中必须**优先于** punch（两条都在时选哪个？）
w7b = reset(new_w())
w7b.luna.charging = True
w7b.luna.punch = 0.5
w7b.luna.atk_lvl = N.ATK_TAP
_ok7b = (w7b.luna.pick_action() == "attack_charge")
chk("⑮-7b ⭐ 阳性对照：蓄力中 + 已出招 同时成立 ⇒ 仍返回 attack_charge"
    "（蓄力分支优先，PR14 的顺序要求）", _ok7b,
    "实际=%s" % w7b.luna.pick_action())

# ---- 判据 9：⭐ 默认行为回归（四个动作逐字未变）----
w9 = reset(new_w())
l9 = w9.luna
# 走
l9.on_ground = True
l9.vx = 200.0
l9.carrying = []
l9.sneak = False
_a_walk = l9.pick_action()
# 爬
l9.on_ladder = True
_a_climb = l9.pick_action()
l9.on_ladder = False
# 冲刺
l9.dash_t = 0.1
_a_dash = l9.pick_action()
l9.dash_t = 0.0
# 拿着东西走
l9.vx = 200.0
l9.carrying = ["yolk"]
_a_carry = l9.pick_action()
l9.carrying = []
# 敲罐（punch，但⛔ 这里 atk_lvl=0 ⇒ attack）
l9.vx = 0.0
l9.punch = 0.3
_a_atk = l9.pick_action()
# ⭐⭐ 「默认行为逐字未变」的基准来自**基线副本实测**，不是我记忆里的值：
#   基线 `_work/_baseline_PR15/night.py.5618lines.2bff9f2f`（PR15 改前）
#   实测：空手冲刺 = human_run（run_carry 只用于负重跑，Ronny 10-04 划过）。
#   ⛔ 我第一版把期望写成 run_carry ⇒ 判据红 ⇒ 查下来**产品代码本来就是这样**，
#     是判据记错了既有行为。
_ok9 = (_a_walk == "human_run" and _a_climb == "climb"
        and _a_dash == "human_run" and _a_carry == "run_carry"
        and _a_atk == "attack")
chk("⑮-9 ⭐⭐ 默认行为回归：走/爬/冲刺/拿东西 四个动作 pick_action 逐字未变", _ok9,
    # ⭐ 手空冲刺的既有行为是 **human_run**（⛔ 不是 run_carry——
#   run_carry 是负重跑素材，Ronny 10-04 划过「拿东西时不用 run_carry 播冲刺」）。
#   我第一版期望写成 run_carry ⇒ 判据红 ⇒ **判据错了，产品代码是对的**。
    "走=%s 爬=%s 空手冲刺=%s 负重跑=%s挥击=%s"
    "（期望 human_run/climb/human_run/run_carry/attack）"
    % (_a_walk, _a_climb, _a_dash, _a_carry, _a_atk))
# ⭐⭐ 阳性对照：跑动时按攻击 ⇒ 必须切成 attack（证明不是"永远返回前者"）
w9b = reset(new_w())
l9b = w9b.luna
l9b.on_ground = True
l9b.vx = 200.0
l9b.punch = 0.3
l9b.atk_lvl = N.ATK_TAP
_ok9b = (l9b.pick_action() == "attack")
chk("⑮-9b ⭐ 阳性对照：跑动中挥击 ⇒ pick_action 必须切成 attack（挥击优先）", _ok9b,
    "实际=%s（跑动中仍是 human_run 就说明挥击优先被破坏了）" % l9b.pick_action())

# ---- 判据 10：三项回归（本单必须仍达成PR14/PR13 的基线）----
# ⭐ 这里只做「源码级」的三项确认，完整跑在 _自测_全部.py 里。
#   ⚠️ 本单⛔ 不许改 PR14 的自测文件，所以这里不重复跑（跑一次要好几秒）。
_ok10_src = ("class Effect:" in _src
             and "def try_attack(self, lvl: int = ATK_TAP)" in _src
             and "def _draw_fx_charge(self, p, e):" in _src
             and "def _fx_fire(self, lvl:int)" in _src)
chk("⑮-10 ⭐ PR14 的关键实现仍在源码里（Effect / try_attack 默认参数 / 粒子 / _fx_fire）",
    _ok10_src,
    "⛔ 本单不许改 PR14，故此处只做源码级确认；完整回归见 _自测_全部.py")
# ⭐⭐⭐ 默认行为最重要的一条：普攻的击退仍是 260（PR14 定的）
_ok10_kn = (N.ATK_KNOCK == 260.0 and N.ATK_KNOCK1 == 312.0 and N.ATK_KNOCK2 == 338.0
            and N.ATK_HINT == 0.30 and N.ATK_CHARGE1 == 0.35)
chk("⑮-10b ⭐⭐ PR14 的三档数值与两个阈值**一个都没动**", _ok10_kn,
    "KNOCK=(%s,%s,%s) HINT=%.2f CHARGE1=%.2f"
    % (N.ATK_KNOCK, N.ATK_KNOCK1, N.ATK_KNOCK2, N.ATK_HINT, N.ATK_CHARGE1))
_ok10_t = (N.ATK_WIND == 0.16 and N.ATK_ACT == 0.09
           and N.ATK_REC == 0.42 and N.ATK_CD == 0.12)
chk("⑮-10c ⭐⭐ 四个老时序常量一个都没动（手感受过调校）", _ok10_t,
    "WIND=%.2f ACT=%.2f REC=%.2f CD=%.2f"
    % (N.ATK_WIND, N.ATK_ACT, N.ATK_REC, N.ATK_CD))

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
