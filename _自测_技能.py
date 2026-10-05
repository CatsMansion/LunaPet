# -*- coding: utf-8 -*-
"""_自测_技能.py —— 攻击（J）与冲刺（K）的时序与不变量验证

⭐ 为什么单独一个文件（不是塞进 _自测_夜间.py）：
   技能是**帧级时序**的东西，而夜间自测是"局面级"的。
   2026-09-30 教训：「伸懒腰时飞」那类 bug，静态"两帧对比"测不出来，
   必须跑**完整动作链路**、逐帧断言不变量。所以这里驱动真实 w._tick()。

⭐ 三条设计铁律（每条都对应一条断言）：
   ① 攻击有前摇和后摇 —— 前摇是可打断窗口，后摇是不能连打窗口
   ② 命中判定是**身前单向** —— 她不能打到背后（否则潜行的"绕后"没意义）
   ③ 冲刺的价值不是"跑更快"而是**穿过去**（无敌帧期间 caught() 失效）
"""
import math
import os
import sys
import time

# ⭐ 键位提示条一致性断言要读 night.py 源码（见文件末尾）
#   ——这是**唯一**允许"读源码"而不是调代码的地方，因为要检的是
#   "提示文案"与"按键绑定"两个**文本**之间的一致性，运行时拿不到提示原文。
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "pet_engine", "night.py"), encoding="utf-8") as _f:
    _src = _f.read()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet_engine.core import load_pack
from pet_engine import night as N

pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = N.NightWindow(pack)

_T = [0.0]
time.perf_counter = lambda: _T[0]


def step(n=1, dt=1.0 / 60.0):
    """驱动真实 _tick —— ⛔ 绝不内联复刻一份物理逻辑（激光笔"连扑98次"假警报的教训）"""
    for _ in range(n):
        _T[0] += dt
        w._tick()
        if w.phase != "play":
            w.phase, w.phase_t = "play", 0.0


OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"  {'OK  ' if cond else 'FAIL'}  {name}{('   ' + info) if info else ''}")


def fresh(night=1):
    w.start_night(night)
    l, mw = w.luna, w.mw
    l.x, l.y, l.vx, l.vy = 300.0, N.FLOOR_Y, 0.0, 0.0
    l.carrying = []
    l.atk_wind = l.atk_act = l.atk_rec = l.atk_cd = 0.0
    l.atk_hit_done = False
    l.dash_t = l.dash_i = l.dash_cd = 0.0
    mw.x, mw.y = 1000.0, N.FLOOR_Y
    mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
    mw.fury, mw.fury_t, mw.fury_x = False, 0.0, None
    mw.stun, mw.knock_vx = 0.0, 0.0
    mw.invest_x, mw.invest_linger, mw.invest_hold = None, 0.0, 0.0
    return l, mw


# ==================================================================
print("=" * 68)
print("✔ 攻击三段时序（前摇 / 命中窗口 / 后摇/ 冷却）")
print("=" * 68)
l, mw = fresh()
chk("初始不在攻击中", l.try_attack() is True)
chk("起手进入前摇", l.atk_wind > 0.0 and l.atk_act == 0.0,
    f"wind={l.atk_wind:.3f} act={l.atk_act:.3f}")

# ---- 前摇期间不能再次攻击（可打断窗口）----
# ⛔ 对称验证：前摇内被拒 + 前摇结束后能打（只测前者= 永久禁用也能过）
_wf = int(N.ATK_WIND * 60)
_ok = True
for _ in range(_wf - 2):
    _ok = _ok and (l.try_attack() is False)
step(1)
_ok = _ok and (l.try_attack() is False)     # 最后一帧仍在前摇内
chk("前摇期间不能再次起手（可被打断窗口）", _ok,
    f"连续试 {_wf} 帧全被拒（ATK_WIND={N.ATK_WIND}s ≈ {_wf} 帧）")

# ---- 前摇结束 → 命中窗口 ----
step(1)
while l.atk_wind > 1e-6:
    step(1)
chk("前摇结束进入命中窗口", l.atk_act > 0.0 and l.atk_wind <= 1e-6,
    f"act={l.atk_act:.4f} 期望 ATK_ACT={N.ATK_ACT:.3f}")
# ⛔⛔ 判据按**帧量化**比，不是按秒比小数：
#   _tick 里"wind 归零那一帧"同时给 act 赋 0.09 又减了一次 dt，
#   所以进入 act 时实测 0.0733，差值恰好 = 一帧 (0.01667)。
#   act 实际持续 5 帧 = 0.083s，与理论 0.09s 差不到一帧 → **不是 bug，是帧量化**。
#   ⛔ 拿 0.0733 vs 0.09 直接比会误报"命中窗口短了 20%"。
_act_f_expect = N.ATK_ACT * 60          # 5.4 帧 → 允许 5 或 6
_act_f = int(round(_act_f_expect))
_act_f = _act_f if abs(_act_f - _act_f_expect) < 0.5 else int(_act_f_expect)
chk("命中窗口长度 = ATK_ACT（按帧量化）",
    abs(l.atk_act - (N.ATK_ACT - 1.0 / 60.0)) < 1e-6,
    f"实测 {l.atk_act:.4f} = ATK_ACT − 1帧（{N.ATK_ACT:.3f}−0.0167）；理论 {_act_f_expect:.1f} 帧")

# ---- 命中窗口结束 → 后摇 ----
while l.atk_act > 1e-6:
    step(1)
chk("命中窗口结束进入后摇", l.atk_rec > 0.0, f"rec={l.atk_rec:.4f}")
_rf = int(N.ATK_REC * 60)
_ok = True
for _ in range(_rf - 2):
    _ok = _ok and (l.try_attack() is False)
chk("后摇期间不能连打（防贴着它狂按秒杀）", _ok,
    f"连续试 {_rf} 帧全被拒（ATK_REC={N.ATK_REC}s ≈ {_rf} 帧）")

# ---- 后摇结束 → 冷却 ----
while l.atk_rec > 1e-6:
    step(1)
chk("后摇结束进入冷却", l.atk_cd > 0.0, f"cd={l.atk_cd:.4f}")
# ⛔ 不写死帧数，循环到解锁为止再核对总帧数。
#   踩过的坑：写 `int(ATK_CD*60)=7` 会**早1 帧**（实际第 8 帧解锁），
#   然后误报"冷却不解锁"。帧量化下 `0.12s×60=7.2` 必须向上取整到 8。
#   ⛔ 而且不能只测"冷却内被拒" —— 那把 ATK_CD 设成 9999 也全过 = 假绿。
#   ✅ 所以两边都测：解锁前每帧都必须被拒，解锁那一帧必须成功。
_n = 0
_unlocked = False
while _n < 30:
    _n += 1
    step(1)
    if l.try_attack():                 # 未到解锁帧时这一直返回 False
        _unlocked = True
        break
_expect = int(N.ATK_CD * 60) + 1# 7.2 → 8
chk("冷却结束后可以再起手", _unlocked and _n == _expect,
    f"实测第 {_n} 帧解锁，期望 {_expect} 帧（{N.ATK_CD}s×60={N.ATK_CD * 60:.1f} 向上取整）")

# ==================================================================
print()
print("=" * 68)
print("✔ 攻击命中：身前单向 + 击退 + 硬直")
print("=" * 68)

# ---- 身前的容器：能打碎 ----
# ⛔ 同样要把守卫钉到远处：它踱步进ATK_REACH(62) 会**抢走**这一击
#   （_resolve_attack_hit 一次挥击可同时结算守卫+容器，守卫优先break）。
l, mw = fresh()
st = w.room.stashes[0]
l.x, l.y, l.face = st["x"] - 30.0, st["y"], 1
l.carrying = []
l.atk_wind = l.atk_act = l.atk_rec = l.atk_cd = 0.0
_FAR = 1100.0                          # 远在露娜右侧，绝不进入攻击范围
mw.x, mw.y = _FAR, N.FLOOR_Y
mw.pause_t = 999.0                      # ⭐ 冻结踱步（见击退段的踩坑记录）
l.try_attack()
while l.atk_wind > 1e-6:
    step(1)
while l.atk_act > 1e-6:
    step(1)
chk("⭐ 攻击能击碎身前的容器", st["broken"] and len(l.carrying) == 1,
    f"broken={st['broken']} 手上的东西={l.carrying}")
# ⛔⛔ 判据用 carrying（手上的东西），⛔ 不是 loot_stash：
#   loot_stash 是**回窝才入账**的。实测敲碎瞬间 carrying=['1:yolk'] 而 loot_stash=[]，
#   拿 loot_stash 当判据会得到"攻击拿不到东西"的假失败。
chk("攻击拿到的容器编码带价值", (not l.carrying) or ":" in l.carrying[0],
    f"{l.carrying[0] if l.carrying else None}（格式 value:icon）")

# ---- 背后的容器：打不到 ----
l, mw = fresh()
st2 = w.room.stashes[1]
l.x, l.y, l.face = st2["x"] + 30.0, st2["y"], 1   # 面朝右，容器在左边=背后
l.carrying = []
l.atk_wind = l.atk_act = l.atk_rec = l.atk_cd = 0.0
_BFAR = 1100.0
mw.x, mw.y = _BFAR, N.FLOOR_Y
mw.pause_t = 999.0
l.try_attack()
while l.atk_wind > 1e-6:
    step(1)
while l.atk_act > 1e-6:
    step(1)
chk("⭐ 攻击打不到背后（身前单向，绕后才有意义）", not st2["broken"],
    f"st2.broken={st2['broken']}  她在 x={l.x:.0f} face={l.face} 容器 x={st2['x']}")

# ---- 击退守卫 ----
# ⛔⛔⛔ 隔离守卫踱步，**绝对不能靠每帧回钉 mw.x**。三次踩坑记录：
#   ① 只设一次 mw.x = l.x+40 → 前摇 10 帧里他自己踱步走远，够不到，压根没打中
#   ② 每帧在 step **之后**钉 → 把击退位移覆盖回去，实测"击退 2px"（假的）
#   ③ 每帧在 step **之前**钉 → 更隐蔽：单帧位移是对的(+3.8/+3.4/+3.0)，
#      但每帧都从 340 重新起步，**累积被清零**，总量只剩 2.3px（还是假的）
#   ✅ 正确做法：只冻结**踱步行为**，绝不碰位置 ——
#      pause_t 是 _patrol 的"停下环顾"计时，设成很大即可让他站桩不动，
#      但击退（stun 分支）根本不走 _patrol，所以位移完整保留。
l, mw = fresh()
l.x, l.y, l.face = 300.0, N.FLOOR_Y, 1
_BASE = 340.0                          # 露娜 300 + 40，在 ATK_REACH(62) 内
mw.x, mw.y = _BASE, N.FLOOR_Y
mw.pause_t = 999.0                      # ⭐ 冻结踱步（只影响 _patrol，不影响击退）
l.atk_wind = l.atk_act = l.atk_rec = l.atk_cd = 0.0
l.try_attack()
while l.atk_wind > 1e-6:
    step(1)
_hit_stun = 0.0
_hit_face = None
while l.atk_act > 1e-6:
    step(1)                             # ⛔ 绝不碰 mw.x
    _hit_stun = max(_hit_stun, mw.stun)
    if _hit_stun > 0.0 and _hit_face is None:
        _hit_face = mw.face             # ⛔ 必须在硬直那一帧抓 face
# ⭐ 击退是**持续**的：命中窗口只有 5 帧，窗口内只走 19px，
#   剩下的要等他把 stun 跑完（实测完整 88px）。
#   ⛔ 别在命中窗口内就断言"击退 > 20" —— 那量的是窗口内那一小段，
#   不是玩家实际感受到的击退。玩家感受到的是"他被我推开了一段"。
while mw.stun > 0.0:
    step(1)
_knock = mw.x - _BASE
# ⛔⛔⛔ 击退总量是**解析可算**的，别拍脑袋定阈值：
#   每帧 x += vx*dt ; vx *= (1 - 7*dt)  ⇒  vx(t) = v0·e^(-7t)
#   累计 = ∫₀^stun v0·e^(-7t)dt = (v0/7)·(1 - e^(-7·stun))
#   v0=260, stun=0.45 → (260/7)·(1 - e^-3.15) = 37.14 × 0.957 ≈ **35.5px**
#   ⚠️ 曾把阈值写成 >60，隐含假设"不衰减"（那上限是 260px）——错的，害我查了三轮。
#   也曾记"独立诊断 88.2px"，那是**重复调 hit_by 把 vx 叠起来**的假数。
#   ✅ 判据 = 与解析值误差 < 2px（帧离散化只会让它略小，不会偏大）。
_KNOCK_TH = (N.ATK_KNOCK / 7.0) * (1.0 - math.exp(-7.0 * N.ATK_STUN))
chk("⭐ 攻击能击退守卫（对齐解析值，非拍脑袋阈值）",
    abs(_knock - _KNOCK_TH) < 2.0,
    f"守卫 {_BASE:.0f} → {mw.x:.0f}  击退 {_knock:.1f}px"
    f"  解析值 {_KNOCK_TH:.1f}px  差 {abs(_knock - _KNOCK_TH):.1f}px")
# ⭐ 击退的**玩法意义**是"创造逃跑窗口"，判据用玩家能拉开多少来锚，
#   而不是"位移多少像素"：硬直 0.45s 露娜 RUN 300 能跑 135px，
#   守卫被推开 ~36px → 净拉开 ~170px，够换一个容器方向。
_GAP = _knock + N.RUN_SPEED * N.ATK_STUN
chk("⭐ 击退 + 硬直够创造一个逃跑窗口（净拉开 > 容器间距）", _GAP > 150.0,
    f"击退 {_knock:.0f}px + 硬直期位移 {N.RUN_SPEED * N.ATK_STUN:.0f}px"
    f" = 净拉开 {_GAP:.0f}px")
chk("击退附带硬直（它站桩不动）", _hit_stun > 0.0,
    f"峰值 stun={_hit_stun:.3f} 期望 ATK_STUN={N.ATK_STUN:.2f}")
# ⛔ face 必须在硬直帧抓：硬直结束后他会恢复 _patrol 重新转向，
#   事后再看量到的是踱步方向，不是"被打得脸朝后"。
chk("被击退后脸朝后（面向来敌）", _hit_face == -1,
    f"命中帧 face={_hit_face}  期望 -1（她在他左边，他被打得转身）")

# ---- 手上有东西时不能攻击取物 ----
l, mw = fresh()
st3 = w.room.stashes[0]
l.x, l.y, l.face = st3["x"] - 30.0, st3["y"], 1
l.carrying = ["1:yolk"]
l.atk_wind = l.atk_act = l.atk_rec = l.atk_cd = 0.0
l.try_attack()
while l.atk_wind > 1e-6:
    step(1)
while l.atk_act > 1e-6:
    step(1)
chk("手上已有东西 → 攻击不能覆盖 carrying", not st3["broken"] and l.carrying == ["1:yolk"],
    f"broken={st3['broken']} carrying={l.carrying}")

# ==================================================================
print()
print("=" * 68)
print("✔ 冲刺：无敌帧 / 冷却 / 撞墙不穿模")
print("=" * 68)

# ---- 无敌帧让 caught() 失效 ----
l, mw = fresh()
mw.x, mw.y = l.x + 20.0, N.FLOOR_Y          # 站在抓捕半径内
chk("起手前会被抓住（对照）", mw.caught(l) is True,
    f"距离 {abs(mw.x - l.x):.0f}px < 抓捕半径 {N.MW_CATCH_R:.0f}")
chk("⭐ 冲刺起手成功", l.try_dash(1) is True)
chk("起手即有无敌帧（比位移窗口长）", l.dash_i > 0.0,
    f"dash_i={l.dash_i:.3f} > dash_t={l.dash_t:.3f}")
_inv_frames = int(l.dash_i * 60)          # DASH_INV=0.26 → 15 帧
_ok = _inv_frames > 0
_tested = 0
for _ in range(max(1, _inv_frames)):
    # ⛔ 每帧把守卫摆到抓捕半径内：她冲刺会位移，不跟着摆就"走远了当然抓不到"=假绿。
    #   这里**摆位置是对的**（要测的正是"就在身边也抓不到"），
    #   但要用 `pause_t` 冻踱步，别让守卫自己跑开造成误判。
    mw.x, mw.y = l.x + 10.0, N.FLOOR_Y
    mw.pause_t = 999.0
    step(1)
    if l.dash_i > 0.0:
        _ok = _ok and (mw.caught(l) is False)
        _tested += 1
chk("⭐ 无敌帧期间 caught() 全程失效（冲刺的价值是穿过去）",
    _ok and _tested > 0,
    f"实测 {_tested} 帧站在抓捕半径内（dash_i={N.DASH_INV}s → 应为 15 帧）")

# ---- 无敌帧结束后恢复 ----
while l.dash_i > 0.0:
    step(1)
mw.x, mw.y = l.x + 10.0, N.FLOOR_Y      # 钉回抓捕半径内
chk("无敌帧结束后恢复可被抓", (l.dash_i <= 0.0) and (mw.caught(l) is True),
    f"dash_i={l.dash_i:.4f} 距离 {abs(mw.x - l.x):.0f}px")

# ---- 冷却 ----
# ⛔ 对称验证：既测"冷却内被拒"，也测"冷却结束能冲"。
#   只测前者的话，把DASH_CD 改成 9999 也全过= 假绿。
l, mw = fresh()
chk("冲刺起手", l.try_dash(1) is True)
_n = 0
_locked_ok = True
_unlocked = False
while _n < 120:
    _n += 1
    step(1)
    if l.try_dash(1):                 # 冷却未到时一直返回 False
        _unlocked = True
        break
    _locked_ok = _locked_ok and l.dash_cd > 0.0
_expect = int((N.DASH_TIME + N.DASH_CD) * 60) + 1   # 1.5s=90 → 91
chk("冷却期间不能再冲（不能连闪）", _locked_ok,
    f"连续 {_n - 1} 帧被拒时 dash_cd 始终 > 0")
chk("冷却结束后可以再冲", _unlocked and _n == _expect,
    f"实测第 {_n} 帧解锁，期望 {_expect} 帧（{N.DASH_TIME}+{N.DASH_CD}s={N.DASH_TIME + N.DASH_CD}s）")

# ---- 撞桌布墙不穿模 ----
# ⛔ 必须验证"他是被墙拦下的"，⛔ 不能只看"没穿过"。
#   DASH_SPEED=620 × DASH_TIME=0.20 = 理论位移 124px。
#   起点 350、理论终点 474 > 桌布左缘 470 → **不钉任何东西的话本来就该撞上**。
#   但如果起点更靠左、或 dash 提前结束，位移就会很小 ——
#   所以判据是"撞墙时位移受限"：位移量必须明显小于理论 124px。
l, mw = fresh()
l.x = N.TABLE_X0 - 120.0
l.y, l.vy = N.FLOOR_Y, 0.0
l.atk_wind = l.atk_act = l.atk_rec = 0.0
l.dash_t = l.dash_i = l.dash_cd = 0.0
_dash_x0 = l.x
l.try_dash(1)                       # 往右冲，桌布墙在 TABLE_X0
_theo = N.DASH_SPEED * N.DASH_TIME
_n = 0
for _ in range(40):
    step(1)
    _n += 1
    if l.dash_t <= 0.0:
        break
_actual = l.x - _dash_x0
_m = N.BODY_W * 0.35
chk("⭐ 冲刺被桌布墙挡住（不穿模）", l.x < N.TABLE_X0,
    f"起点 {_dash_x0:.0f} → 终点 {l.x:.0f}  桌布左缘 {N.TABLE_X0:.0f}  实际位移 {_actual:.0f}px")
# ⛔ 关键判据：位移**远小于**自由冲刺的理论值 → 证明是被墙拦住，不是自己停了
chk("位移受限（确实被墙拦下，不是 dash 提前结束）",
    _actual < _theo * 0.75,
    f"实际 {_actual:.0f}px vs 自由冲刺理论 {_theo:.0f}px（比例 {_actual / _theo:.0%}）")
chk("撞墙后冲刺立即结束（不会贴着墙抖动）", l.dash_t <= 0.0,
    f"dash_t={l.dash_t:.3f}")

# ---- 攻击中不能冲刺 ----
l, mw = fresh()
l.atk_wind = 0.0
l.try_attack()
chk("攻击前摇期间不能冲刺（两技能互斥）", l.try_dash(1) is False,
    f"wind={l.atk_wind:.3f}")

# ==================================================================
print()
print("=" * 68)
print("✔ 技能键位：提示条与实际绑定一致")
print("=" * 68)

# ⛔⛔ 这条断言是被真bug 逼出来的（2026-10-04）：
#   加了 J/K 两个技能键之后，**屏幕上的操作提示条没同步**，
#   玩家看到的还是「A/D 移动 W 跳 W/S 爬梯 Shift 潜行 E 敲碎容器 R 重来 Esc 退出」
#   —— J 和 K 根本不出现，等于新技能白加（没人知道按什么）。
#   而且它**不会让任何测试变红**，纯靠人肉看图才发现。
#✅ 判据：提示条里出现的每个键位字母，都必须能在 keyPressEvent 里找到分支；
#   反向也要成立（按了有反应 ≠ 写出来了，但写了没反应 = 骗人）。
import re as _re

# ⛔⛔⛔ 坑（三连，缺一个就假绿）：
#   ① 提示串**跨行拼接** —— drawText(QPointF(24,32), 换行, "A/D 移动 ...")。
#      单行 `and` 匹配抓不到。
#   ② 「移动」二字在文件里**第一次出现是注释**（"QTE 期间锁移动"），
#      远在提示行之前 → `next()` 取第一个必然取错。
#      ⛔ 必须**遍历全部候选**再筛，不能取第一个匹配。
#   ③ `\b([A-Z])\b` 在中英混排下匹配不到（中文在 str 模式 re 里不是 \w）→ 取全部大写字母。
#   ④ ⛔ 窗口**不能直接当文本用** —— `[-3,+3]` 会把**上下文注释里的英文**一起吃进来
#      （实测多出 F/P/Q/T，全来自附近的 `# QTE_FAIL` `# PUSH` 之类注释）→ 假失败。
#      ⛔ 只取**字符串字面量**里的内容，注释天然被排除。
_kb = _src[_src.index("def keyPressEvent"):_src.index("def keyReleaseEvent")]
_lines = _src.splitlines()
_cand = [i for i, ln in enumerate(_lines) if "移动" in ln]
_help, _hi = "", None
for i in _cand:
    win = _lines[max(0, i - 3):i + 3]
    if any("drawText" in x for x in win):   # 提示行 = 前后窗口里有 drawText 的那个
        _hi = i
        # 提示串可能跨行拼接 → 把窗口内所有引号内容按顺序接起来
        _help = "".join("".join(_re.findall(r'"([^"]*)"', x)) for x in win)
        break
_help_letters = set(_re.findall(r"[A-Z]", _help))
#   "A/D" "W/S" "Esc" 会被拆成单字母；Shift 走 event.modifiers()
#   不是 Key_ 分支，从"有没有绑定"的角度算有。
_bound = set(_re.findall(r"Qt\.Key_([A-Z])\b", _kb))
_bound |= {"A", "D", "W", "S", "R", "ESC"}   # 方向键/字母键走另一条分支
_missing = sorted(_help_letters - _bound)
chk("（自检）提示行提取成功（防 _help='' 造成全条假绿）",
    _hi is not None and len(_help_letters) > 0,
    f"含「移动」的行共 {len(_cand)} 处（第1 处是注释不是提示），"
    f"命中行号 {_hi}  提出键位 {sorted(_help_letters)}")
chk("提示条里每个键位都有真实绑定（不存在骗人的提示）", not _missing,
    f"提示条键位 {sorted(_help_letters)}  有绑定 {sorted(_bound)}"
    f"  ⛔ 无绑定 {_missing}")
_skill_keys = sorted({"J", "K"} - _help_letters)
chk("⭐ 技能键 J/K 写进了操作提示条", not _skill_keys,
    f"提示条实际含 {sorted(_help_letters)}"
    f"{'' if not _skill_keys else f'；⛔ 缺 {_skill_keys}'}")

# ==================================================================
print()
print("=" * 68)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print("未通过：")
    for b in BAD:
        print("  -", b)
print("=" * 68)
