# -*- coding: utf-8 -*-
"""_自测_世界边界.py —— PR-04：微波炉 investigate 被夹在视口宽（`VW`）的 P0 修复验收

⭐ 这条自测为什么必须存在（派单原话：「现在的自测全在 x<1280 里跑，压根测不到这个 bug」）

   PR-03 把世界从 1280 扩到 3840，只改了 `Luna._clamp_x`。
   `Microwave` 的investigate 路径上有**三处**夹取仍写 `VW - w*0.5 - 8`（= 1224）
   ⇒ 他能去查看的范围只有 [56, 1224]，**只占世界 30%**。
   而同一文件里`_chase` **完全没有夹取** ⇒ 他能为露娜追到 x=3000，
   却不会为一声响走到 x=1300。**同一个守卫两套活动范围，自相矛盾。**

   同一次漏改还带出第二个 bug：`PLATFORMS[0]` 地板右沿也还是 `VW`
   ⇒ `_clamp_x` 放行到 3801，地板却只到 1280（有效站立右沿 1301.7）
   ⇒ 露娜往右跑会**踩空掉出世界，被 y>VH+200 兜底瞬移回窝，赃物清零**。

⭐ 判据纪律（本项目血泪）：
   · **阳性对照必做**：把 `world_w` 临时改回 1280，判据必须报红
     —— 否则"修好了"可能只是"恰好没测到"。
   · 断言落在**行为**（他真的走过去了）而不是**源码文本**。
   · 边界与失败路径一起测：左端/ 右端 / 世界外 / 未越界时不启动。
   ·离屏+ 子进程由`_自测_全部.py` 保证，本脚本自己管退出码。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

import night as N# noqa: E402

DT = 1.0 / 60.0
OK, BAD = [], []


def chk(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'OK  ' if cond else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


class _Luna:
    """只带 sense/update 需要的字段。"""

    def __init__(self, x, y=N.FLOOR_Y, on_ladder=False):
        self.x = float(x)
        self.y = float(y)
        self.on_ladder = on_ladder
        self.escort = False
        self.carrying = []


def _reset_inv(mw):
    """把 investigate 相关状态清干净（复用 `_自测_夜间.py` 的同一套复位逻辑）。"""
    mw.invest_x = None
    mw.invest_linger = 0.0
    mw.invest_hold = 0.0
    mw._go_home = False


def _run(hear_x, start_x, world_w=None, frames=420, cfg_idx=0):
    """真跑 update()：在 start_x 放微波炉，让它听到 start_x 处的声响。
    返回 (mw, luna, 曾经走到的最大 x)。"""
    cfg = N.NIGHTS[cfg_idx]
    room = N.Room(cfg)
    mw = N.Microwave(cfg)
    luna = _Luna(N.NEST_X0 + 70)         # 露娜在允许区（不触发 chase）
    mw.x, mw.y = float(start_x), N.FLOOR_Y
    mw.alert, mw.state = 0.0, "patrol"
    _reset_inv(mw)
    if world_w is not None:
        mw.world_w = float(world_w)
    mw.hear_x = float(hear_x)
    mw.invest_hold = 99.0# 强制启动（绕开INVEST_HOLD 的自然衰减）
    mw.state = "patrol"
    reached = mw.x
    started = False
    for _ in range(frames):
        # ⛔ 每帧把world_w 重新按回来：update() 会从 room 同步，
        #   所以阳性对照时必须同时改 room.world_w 才拦得住。
        if world_w is not None:
            mw.world_w = float(world_w)
        mw.update(DT, luna, room)
        if not started and mw.invest_x is not None:
            started = True
        reached = max(reached, mw.x)
    return mw, luna, reached, started


print("=" * 74)
print("PR-04 · 世界边界（investigate 夹取 + 地板跨度）验收")
print("=" * 74)
print(f"  WORLD_W={N.WORLD_W}  VW={N.VW}  PLATFORMS[0]={N.PLATFORMS[0]}")
print()

# ------------------------------------------------------------------
# 1. 常量层：地板跨度必须等于世界宽
# ------------------------------------------------------------------
print("① 地板跨度 = WORLD_W（不是 VW）")
_floor = N.PLATFORMS[0]
chk("PLATFORMS[0] 右沿 == WORLD_W", _floor[2] == N.WORLD_W,
    f"x1={_floor[2]}（WORLD_W={N.WORLD_W}，旧值 VW={N.VW}）")
chk("PLATFORMS[0] 左沿 == 0 且贴着 FLOOR_Y", _floor[0] == 0 and _floor[1] == N.FLOOR_Y,
    f"({_floor[0]}, {_floor[1]})")

# ------------------------------------------------------------------
# 2. ⭐ 核心：在 x>1280 制造噪声，他必须真的走过去
# ------------------------------------------------------------------
print()
print("② ⭐ 核心：在 x>1280 制造噪声 ⇒ 他必须走过去 investigate")
# 各区代表点（设计端给的分区：A 露娜家 0~560 / B 560~1440 / C 1440~2200
#            / D 2200~3100 / E 3100~3560 / F 3560~3840）
_SPOTS = [
    ("B 区 1400（视口内边缘）", 1400.0, 700.0),
    ("C 区 1600（旧版够不到）", 1600.0, 700.0),
    ("C 区 2100", 2100.0, 900.0),
    ("D 区 2400", 2400.0, 900.0),
    ("D 区 3000", 3000.0, 1200.0),
    ("E 区 3300", 3300.0, 900.0),
    ("F 区 3700（最远）", 3700.0, 1000.0),
]
for name, hx, sx in _SPOTS:
    mw, luna, reached, started = _run(hx, sx)
    half = mw.w * 0.5
    hi = N.WORLD_W - half - 8.0
    ok = started and reached > N.VW - 1.0
    chk(f"噪声在 {name} ⇒ 他走过去了（invest_x→{hx:.0f}，实到x={reached:.0f}）", ok,
        f"上限 {hi:.0f}，视口右缘 {N.VW}" + ("" if ok else f"  ⛔ 只到 {reached:.0f}"))

# ⭐ 精确断言：他真的**站到**声源附近，而不是停在半路
print()
print("③ 他停在声源附近（到位判定，不是走过就算）")
for hx in (1600.0, 2400.0, 3300.0):
    mw, luna, reached, started = _run(hx, 700.0, frames=900)
    d = abs(mw.x - hx)
    chk(f"声源 {hx:.0f}：他停在 x={mw.x:.0f}（距声源 {d:.0f}px）", started and d <= 400.0,
        f"到位判定 INVEST_RADIUS={N.INVEST_RADIUS:.0f}，"
        f"到不了时会先到最远 %.0f" % (N.WORLD_W - mw.w * 0.5 - 8.0))

# ------------------------------------------------------------------
# 3. ⭐ 阳性对照：world_w 改回 1280，判据必须报红
# ------------------------------------------------------------------
print()
print("④ ⭐⭐ 阳性对照：把 world_w 临时改回 1280（=修好的行为），同一场景必须失败")
_1264 = N.Room(N.NIGHTS[0])
_saved_room_world = _1264.world_w
try:
    for hx in (1600.0, 2400.0, 3300.0):
        room = N.Room(N.NIGHTS[0])
        room.world_w = float(N.VW)          # 模拟"修之前"
        mw = N.Microwave(N.NIGHTS[0])
        luna = _Luna(N.NEST_X0 + 70)
        mw.x, mw.y = 700.0, N.FLOOR_Y
        mw.alert, mw.state = 0.0, "patrol"
        _reset_inv(mw)
        mw.hear_x = float(hx)
        mw.invest_hold = 99.0
        reached = mw.x
        for _ in range(900):
            mw.update(DT, luna, room)
            reached = max(reached, mw.x)
        _stale = reached <= N.VW + 1.0
        chk(f"world_w=1280 时他到不了 x={hx:.0f}（证明 ② 真在测世界宽）", _stale,
            f"实测只到 x={reached:.0f}")
finally:
    _1264.world_w = _saved_room_world

# ------------------------------------------------------------------
# 4. 夹取边界：左右两端 + 世界外
# ------------------------------------------------------------------
print()
print("⑤ 夹取边界（他不会走出世界，也不会被夹死）")
mw = N.Microwave(N.NIGHTS[0])
_half = mw.w * 0.5 + 8.0
cases = [
    ("声源 x=-500（世界外左侧）", -500.0, _half),
    ("声源 x=0（世界左缘）", 0.0, _half),
    ("声源 x=99999（世界外右侧）", 99999.0, N.WORLD_W - _half),
    ("声源 x=3840（世界右缘）", 3840.0, N.WORLD_W - _half),
]
for name, v, want in cases:
    got = mw._clamp_target_x(v)
    chk(name, abs(got - want) < 1e-6, f"夹成 {got:.1f}（期望 {want:.1f}）")

mw.x = 99999.0
mw._clamp_self_x()
chk("他自己被夹在world_w - 体型半宽 - 8", abs(mw.x - (N.WORLD_W - _half)) < 1e-6,
    f"x={mw.x:.1f}")
mw.x = -999.0
mw._clamp_self_x()
chk("他自己被夹在体型半宽 + 8", abs(mw.x - _half) < 1e-6, f"x={mw.x:.1f}")
chk("可活动区宽度 = 世界宽 - 体型 - 边距（不是视口宽）",
    N.WORLD_W - 2 * _half > N.VW * 2,
    f"[{_half:.0f}, {N.WORLD_W - _half:.0f}] 宽 {N.WORLD_W - 2 * _half:.0f}px"
    f"（视口只有 {N.VW}）")

# ------------------------------------------------------------------
# 5. 失败路径：不该启动的就不启动
# ------------------------------------------------------------------
print()
print("⑥ 失败路径（这些也必须守住，不然改动会引入新问题）")
#⑥-1 未越界时（露娜在允许区）不启动 investigate
cfg = N.NIGHTS[0]
room = N.Room(cfg)
mw = N.Microwave(cfg)
luna = _Luna(room.border_x - 100.0)
mw.x = 300.0
mw.hear_x = 2400.0
mw.invest_hold = 0.0            # ⛔ 不强制启动
mw.alert, mw.state = 0.0, "patrol"
_reset_inv(mw)
for _ in range(120):
    mw.update(DT, luna, room)
chk("invest_hold=0 ⇒ 不启动查看（不凭空走过去）", mw.invest_x is None,
    f"invest_x={mw.invest_x}")

# ⑥-2 声源就在他脚下 ⇒ 不启动（已在位置上了）
mw2 = N.Microwave(cfg)
room2 = N.Room(cfg)
luna2 = _Luna(N.NEST_X0 + 70)
mw2.x = 1600.0
mw2.hear_x = 1605.0
mw2.alert, mw2.state = 0.0, "patrol"
_reset_inv(mw2)
mw2.invest_hold = 99.0           # ⭐ 同上：必须在 _reset_inv 之后
for _ in range(60):
    mw2.update(DT, luna2, room2)
chk("声源就在脚下 ⇒ 不启动（防原地抖动）", mw2.invest_x is None,
    f"invest_x={mw2.invest_x}（hold={mw2.invest_hold:.1f}，确实已启动条件下界）")

# ⑥-3 chase 仍然压过 investigate（改动不能影响优先级）
mw3 = N.Microwave(cfg)
room3 = N.Room(cfg)
luna3 = _Luna(N.NEST_X0 + 70)
mw3.x = 700.0
mw3.hear_x = 2400.0
mw3.alert, mw3.state = 0.0, "patrol"
_reset_inv(mw3)
# ⚠️ 顺序：`invest_hold` 必须在 `_reset_inv` **之后**设 ——
#   `_reset_inv` 会把它清零，写在前面会被抹掉（第一版就这么栽的，
#   症状是 `_inv_started=False`，看起来像"改动把优先级改坏了"，其实是自测自己的错）。
mw3.invest_hold = 99.0
for _ in range(30):
    mw3.update(DT, luna3, room3)
_inv_started = mw3.invest_x is not None
mw3.state = "chase"
mw3.alert = 1.0
for _ in range(30):
    mw3.update(DT, luna3, room3)
chk("chase 仍压过 investigate（优先级没被改坏）",
    _inv_started and mw3.invest_x is None,
    f"启动过={_inv_started} 现invest_x={mw3.invest_x}")

# ------------------------------------------------------------------
# 6. ⭐ 地板跨度：露娜能走到世界右缘
# ------------------------------------------------------------------
print()
print("⑦ ⭐ 地板跨度：露娜往右跑不会踩空掉出世界")
KEY_R = {N.Qt.Key_D, N.Qt.Key_Right}
room4 = N.Room(N.NIGHTS[0])
luna4 = N.Luna(1200.0, N.FLOOR_Y)
luna4.on_ground = True
_air = 0
for _ in range(1600):                # 26.7秒，足够跑到世界右缘
    luna4.update(DT, KEY_R, room4)
    if not luna4.on_ground and luna4.y > N.FLOOR_Y + 1.0:
        _air += 1
chk("从 x=1200 起跑 1600 帧：从不悬空（地板没断）", _air == 0,
    f"悬空 {_air} 帧，末 x={luna4.x:.0f} y={luna4.y:.1f}")
chk("她能走到世界右缘（x > 3000）", luna4.x > 3000.0,
    f"末 x={luna4.x:.0f} / 上限 {N.WORLD_W - N.BODY_W * 0.5 - 8.0:.0f}")
chk("她站得住（on_ground=True 且 y==FLOOR_Y）",
    luna4.on_ground and abs(luna4.y - N.FLOOR_Y) < 0.01,
    f"on_ground={luna4.on_ground} y={luna4.y:.1f}")

# ⭐ 阳性对照：把地板改回 VW，她必踩空
_saved_plats = list(N.PLATFORMS)
N.PLATFORMS[0] = (0, N.FLOOR_Y, N.VW, N.VH)
try:
    room5 = N.Room(N.NIGHTS[0])
    luna5 = N.Luna(1200.0, N.FLOOR_Y)
    luna5.on_ground = True
    _fell = None
    for f in range(1600):
        px, py = luna5.x, luna5.y
        luna5.update(DT, KEY_R, room5)
        if _fell is None and luna5.y > N.FLOOR_Y + 1.0:
            _fell = (f, px, luna5.x)
            break
    chk("地板改回 VW 后她必踩空（证明 ⑦ 真在测地板跨度）", _fell is not None,
        f"第 {_fell[0]} 帧 x={_fell[1]:.1f}→{_fell[2]:.1f} 处悬空"
        if _fell else "⛔ 竟然没踩空，判据无效")
finally:
    N.PLATFORMS[:] = _saved_plats
chk("恢复后 PLATFORMS[0] 回到 WORLD_W", N.PLATFORMS[0][2] == N.WORLD_W,
    f"x1={N.PLATFORMS[0][2]}")

# ------------------------------------------------------------------
# 7. ⭐ 回归：旧的不变量（可活动区夹取）仍然成立
# ------------------------------------------------------------------
print()
print("⑧ 回归：`_自测_夜间.py` 的不变量② 用的 _HI 口径必须与新实现一致")
_lo = N.Microwave(N.NIGHTS[0]).w * 0.5 + 8.0
_hi = N.WORLD_W - N.Microwave(N.NIGHTS[0]).w * 0.5 - 8.0
print(f"     新可活动区 = [{_lo:.0f}, {_hi:.0f}]")
print("     ⚠️ `_自测_夜间.py:750` 写的是 `_HI = N.VW - mw.w*0.5 - 8.0`= 1224")
print("        它测的是 1275（视口内）⇒ 改动后仍绿，但**它测不到新范围**。")
print("        ⛔ 本自测的 ②~⑤ 才是x>1280 的覆盖。")

print()
print("=" * 74)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print("⛔ %d 项未过：%s" % (len(BAD), "、".join(BAD)))
print("=" * 74)
sys.exit(1 if BAD else 0)
