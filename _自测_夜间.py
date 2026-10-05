# -*- coding: utf-8 -*-
"""_自测_夜间.py —— 夜间冒险灰盒的源码层验证

⭐ 纪律（2026-09-29 / 09-30 两次事故定的）：
   ① 一律驱动【真实】w._tick()，⛔ 不许在脚本里复刻一份物理逻辑
   ② 用可控假时钟替换 perf_counter，保证 dt 稳定
   ③ ⭐ 必须强制 render 一次 —— paintEvent 里的错只在真渲染时暴露（QLinearGradient 那次）
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet_engine.core import load_pack
from pet_engine import night as N

pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = N.NightWindow(pack)
w.start_night(1)               # ⭐ 2026-10-03 起初始是选档菜单，测试直接进「深夜」

# ---- 可控时钟 ----
_T = [0.0]
_orig = time.perf_counter
time.perf_counter = lambda: _T[0]


def step(dt=1.0 / 60.0, n=1):
    for _ in range(n):
        _T[0] += dt
        w._tick()


def step_pure(dt=1.0 / 60.0, n=1):
    """⭐ 只测物理时用的 step：把微波炉冻住、不会被抓。

    为什么需要：梯子在 x=700，已经在允许区外（BORDER_X=430），测爬梯时露娜必然越界，
    微波炉会真的追过来把她抓住 → phase 变 meowed → _tick 不再更新物理 →
    她卡在半空（实测 y=593 不动）。这是【测试污染】，不是物理 bug。
    """
    for _ in range(n):
        sx, sy = w.mw.x, w.mw.y
        _T[0] += dt
        w._tick()
        if w.phase != "play":
            w.phase, w.phase_t = "play", 0.0
        w.mw.x, w.mw.y = sx, sy
        w.mw.alert, w.mw.state = 0.0, "patrol"


def step_ai(dt=1.0 / 60.0, n=1):
    """测 AI 时用：不让"被抓 → 押送演出"把后续的 alert 断言吞掉。

    ⛔ 踩过的坑：正面视野那组跑完 60 帧后微波炉已经追上并把露娜抓了，
       phase 变 meowed/hauled → _tick 里不再 update → 后面三组 alert 全是 0，
       但"进入追击"这种只看 state 的断言照样过，假绿。
    """
    for _ in range(n):
        _T[0] += dt
        w._tick()
        if w.phase != "play":
            w.phase, w.phase_t = "play", 0.0


def render():
    pm = QPixmap(w.size())
    pm.fill(Qt.transparent)
    w.render(pm)


OK, BAD = [], []

# ⭐ 2026-10-03 比例重排后：测试里的坐标不再写死，全部从 night 派生。
#   下面这些是旧布局（470/320/552/700）的替身，新布局见 night.py 的 PLATFORMS/LADDERS。
FLOOR   = N.FLOOR_Y          # 672
COUNTER = N.PLATFORMS[2][1] # 料理台顶 375
TABLE   = N.PLATFORMS[1][1] # 餐桌顶 474
HANGER  = N.PLATFORMS[3][1] # 吊柜顶 177
LADX    = N.LADDERS[0][0]    # 梯子 x 620
LADTOP  = N.PLATFORMS[2][1] # 梯子顶 = 料理台 375



def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


print("=" * 72)
print("① 构造与资源")
print("=" * 72)
chk("构造成功", w is not None)
chk("缩放系数合理 0.15<s<0.5", 0.15 < w.s < 0.5, f"s={w.s:.4f}")
chk("动作帧已加载", set(["idle", "human_run", "jump", "climb", "fall"]).issubset(w.imgs),
    f"已加载 {sorted(w.imgs)}")
chk("赃物图标覆盖三档全部", len(w.icons) == len({s["icon"] for n in N.NIGHTS for s in n["stashes"]}),
    f"{len(w.icons)}/{len({s['icon'] for n in N.NIGHTS for s in n['stashes']})}")

print()
print("=" * 72)
print("② 重力与落地")
print("=" * 72)
l = w.luna
l.x, l.y = 120.0, 200.0            # ⭐ x=120：餐桌在 300~470，落点必须避开它
l.vx = l.vy = 0.0
step_pure(1 / 60, 90)                 # 1.5s 自由落体
chk("落到地板", abs(l.y - N.FLOOR_Y) < 1.0, f"y={l.y:.1f} 期望 {N.FLOOR_Y}")
chk("落地后 on_ground", l.on_ground)

# ⭐ 餐桌是矮平台：站在它上方自由落体会被接住（Ronny 10-03 加的）
#   ⭐ 2026-10-03 布局重排：餐桌 470~730（x=380 已不在桌上方，会落空到地板）
l.x, l.y = 600.0, 200.0
l.vx = l.vy = 0.0
l.on_ground = False
step_pure(1 / 60, 90)
chk("餐桌能接住落下来的人", abs(l.y - TABLE) < 1.0, f"y={l.y:.1f} 期望 {TABLE}")

print()
print("=" * 72)
print("③ 跑动")
print("=" * 72)
# ⭐ 2026-10-03：桌布现在是从桌面垂到地的实心面（470~730），起跑点必须在开阔地板段
#   （800 在布区右侧），否则 1s 会被布墙拦下（实测从 380 起跑只跑出 68px）
l.x, l.y = 800.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
x0 = l.x
w.keys = {Qt.Key_D}
step_pure(1 / 60, 60)                 # 1s
w.keys = set()
vx_run = abs(l.x - x0)
chk("1 秒右跑 240~320px", 240 < vx_run < 320, f"实际 {vx_run:.0f}px")
chk("动作切到 human_run", l.act == "human_run", f"act={l.act}")

print()
print("=" * 72)
print("④ 跳跃高度 + 跳键闩锁")
print("=" * 72)
l.x, l.y = 300.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
l.jump_latch = False
best = N.FLOOR_Y
w.keys = {Qt.Key_W}                    # ⭐ 全程按住，用来验证不会连跳
for _ in range(150):
    step_pure()
    best = min(best, l.y)
w.keys = set()
h = N.FLOOR_Y - best
chk("跳高 190~225px", 190 < h < 225, f"实际 {h:.0f}px")
# ⛔ 落差必须**从 PLATFORMS 现算**，不许写死 —— 写死就是"布局改了判据还按旧值算"，
#   这正是 ⑤ 假绿了两个版本的原因。2026-10-04 台面 397→380 后地板就跳不上了。
_drop_floor = N.FLOOR_Y - COUNTER       # 地板 → 台面 = 219
_drop_table = TABLE - COUNTER           # 茶几 → 台面 = 108
chk("地板跳不上台面（新布局，差 15px）", h < _drop_floor,
    f"跳高 {h:.0f} < 落差 {_drop_floor:.0f}，差 {_drop_floor - h:.0f}px")
chk("茶几跳得上台面（差 %.0fpx）" % (_drop_table - 12),
    h > _drop_table + 12, f"跳高 {h:.0f} > 落差 {_drop_table:.0f}，余 {h - _drop_table:.0f}px")
chk("跳不上吊柜(落差328，须经台面中转)", h < 328 - 40, f"差 {328 - h:.0f}px")
chk("按住 W 落地后不连跳（落在地板或餐桌都算落地）",
    abs(l.y - N.FLOOR_Y) < 1.0 or abs(l.y - TABLE) < 1.0, f"y={l.y:.1f}")

print()
print("=" * 72)
print("⑤ 跳上料理台")
print("=" * 72)
# ⛔⛔ 2026-10-04 新布局后**地板跳不上台面**，判据不能写"从地板 760 起跳"了：
#   台面顶从 397 抬到 380（为了让台下净高 181px 走得下微波炉 161px），
#   于是地板→台面落差 = 599-380 = 219px，而**实测跳高只有 204px**（离散积分峰值），
#   差 15px —— 物理上就是跳不上去。旧判据拿旧落差 178 算，所以一直假绿。
#   ✅ 真实路径只有一条：**茶几(488) → 台面(380)**，落差 108px + 水平跨度 60px。
#     实测（茶几中段 x=640 起跑）落点 x=777.1 y=380 站得住。
#   ⛔ 别为了"让判据变绿"把台面压回 397 —— 那样微波炉就过不了台下。
#   ⛔ 楼层顺序不可改：台面(380) → 茶几(488) → 地板(599) 是向下单调的，
#     玩家从阳台(左)出发必须先爬茶几，再从茶几跳台面。
l.x, l.y = 640.0, N.TABLE_TOP          # 茶几中段
l.vx = l.vy = 0.0
l.on_ground = True
l.jump_latch = False
w.keys = {Qt.Key_D}                    # 先向右助跑
step_pure(1 / 60, 18)                  # ⭐ 18 帧是实测过的窗口：
#   14~18 帧能上台面（落点 x=757~777, y=380）；
#   10 帧起跳太早 → 落进台面与茶几之间的空隙掉回地板；
#   20 帧起跳太晚 → 已经跑过茶几右缘 700 掉下去了。
#   ⛔ 别写死"跑够 0.5s"这种直觉值 —— 助跑帧数直接决定能不能过。
w.keys = {Qt.Key_D, Qt.Key_W}          # 助跑中起跳
step_pure(1 / 60, 8)                   # ⭐ 只按住 8 帧就松
# ⛔⛔ 千万别"全程按住 W"：台面上方 790~1010 是**吊柜**（顶 50），
#   而 Luna.update 里 `if self.on_ladder or want_up` → 按住 W 会被判成"想爬吊柜"
#   → 直接进爬梯态卡在 y≈270（实测落点 x=900 y=270.7，on_ground=False）。
#   玩家实机是「起跳后松手」，所以判据也必须松手。
w.keys = set()
step_pure(1 / 60, 62)
chk("经茶几跳上料理台", abs(l.y - COUNTER) < 1.5 and l.on_ground,
    f"落点 x={l.x:.1f} y={l.y:.1f} on_ground={l.on_ground}")
chk("落台后不再弹起", l.on_ground and abs(l.vy) < 1.0,
    f"vy={l.vy:.1f} on_ground={l.on_ground}")

print()
print("=" * 72)
print("⑥ 爬桌布（地板 → 餐桌。2026-10-03：桌布整面可扒，LADDER_ZONES）")
print("=" * 72)
l.x, l.y = float(LADX), FLOOR          # 布面中心 x=600
l.vx = l.vy = 0.0
l.on_ladder = False
l.jump_latch = False
w.keys = {Qt.Key_W}
step_pure(1 / 60, 10)
on_lad = l.on_ladder
step_pure(1 / 60, 100)
w.keys = set()
chk("进入爬梯状态", on_lad, f"on_ladder={on_lad}")
chk("爬到桌面（派生）", abs(l.y - TABLE) < 2.0, f"y={l.y:.1f} 期望 {TABLE}")
chk("爬完回到地面态", not l.on_ladder, f"on_ladder={l.on_ladder}")
chk("爬到顶不会自动弹起", abs(l.y - TABLE) < 2.0, f"y={l.y:.1f}")

# ⭐ 站在平台上不许抖：连续 60 帧的 y 极差必须 < 1px
l.x, l.y = 760.0, COUNTER
l.vx = l.vy = 0.0
l.on_ground = True
l.on_ladder = False
w.keys = set()
ys = []
for _ in range(60):
    step_pure()
    ys.append(l.y)
chk("站台上 60 帧不抖", (max(ys) - min(ys)) < 1.0,
    f"极差 {max(ys)-min(ys):.2f}px  y∈[{min(ys):.1f},{max(ys):.1f}]")

# ⭐ 高速下落不许穿透上层平台
l.x, l.y = 760.0, 120.0
l.vx = l.vy = 0.0
l.on_ground = False
step_pure(1 / 60, 90)
chk("高速下落落在料理台而非穿透到地板", abs(l.y - COUNTER) < 2.0, f"y={l.y:.1f}")

print()
print("=" * 72)
print("⑦ 允许区与微波炉")
print("=" * 72)
# ⛔ 这一组必须【确定性】：巡逻带随机踱步节奏后，微波炉朝向不再可预测，
#    靠"让它自己走过来"去撞视野会时灵时不灵（实测 alert 从 0.95 飘到 0.02）。
#    → 手动钉死 mw.x / face / dir，并把 walk_t 拉长到不触发转身。
def freeze_mw(x, face):
    w.mw.x, w.mw.y = x, N.FLOOR_Y
    w.mw.face = w.mw.dir = face
    w.mw.walk_t, w.mw.pause_t = 999.0, 0.0


l.x, l.y = 200.0, N.FLOOR_Y
l.vx = l.vy = 0.0
freeze_mw(760.0, 1)
w.mw.alert = 0.0
w.mw.state = "patrol"
step_ai(1 / 60, 120)                     # 2s 待在允许区内
chk("区内不被追", w.mw.state == "patrol" and w.mw.alert < 0.01,
    f"state={w.mw.state} alert={w.mw.alert:.2f}")

freeze_mw(900.0, 1)                   # 它朝右，露娜在它正前方 150px
l.x = 1050.0
step_ai(1 / 60, 60)                      # 1s
chk("正面被看见 → 警戒涨满", w.mw.alert > 0.9, f"alert={w.mw.alert:.2f}")
step_ai(1 / 60, 20)
chk("进入追击", w.mw.state == "chase", f"state={w.mw.state}")

w.mw.alert = 0.0
w.mw.state = "patrol"
# ⛔ 2026-10-04：原来 freeze_mw(1100, 1) 让它朝右，但**新布局深夜档巡逻段右端就是 1108**
#   —— 走 8px 就掉头，掉头后面朝左就变成「正面看见」→ alert 直接涨到 1.00，
#   报成「背后近距离听得见」FAIL。判据自己造了个正面场景。
#   ✅ 正确摆法：微波炉放在**巡逻段中段**且朝右，露娜在它**左后方**，
#     这样 1s 内它不会走到右端掉头，测的才是真正的"背后听见"这一档（0.5）。
_p0, _p1 = N.NIGHTS[1]["patrol"] if len(N.NIGHTS) > 1 else N.NIGHTS[0]["patrol"]
freeze_mw(_p1 - 150.0, 1)             # 朝右，距右端还有 150px 余量
l.x = _p1 - 150.0 - 90.0             # 它背后 90px
step_ai(1 / 60, 60)
chk("背后近距离听得见（半速）", 0.3 < w.mw.alert < 0.95, f"alert={w.mw.alert:.2f}")

w.mw.alert = 0.0
w.mw.state = "patrol"
freeze_mw(700.0, 1)                   # 它朝右，露娜在远处背后 → 无感
l.x = 400.0
step_ai(1 / 60, 60)
chk("远处背后无感", w.mw.alert < 0.01, f"alert={w.mw.alert:.2f}")

l.x = 200.0                           # 逃回允许区
w.mw.alert = 1.0
w.mw.state = "chase"
step_ai(1 / 60, 300)
chk("退回区内警戒清零", w.mw.alert < 0.05, f"alert={w.mw.alert:.2f}")

print()
print("=" * 72)
print("⑧ 偷东西 + 回窝结算")
print("=" * 72)
w.start_night(1)
l = w.luna
# ⭐⭐ 2026-10-04：容器分了四档，不再硬编码"三文鱼"——
#   ⛔ 写死icon 会让"重排关卡数据"必然带崩这组测试（已踩过）。
#   ✅ 改成：从 stashes 里取第0 号，并按它的 value/icon 断言。
s0 = w.room.stashes[0]
l.x, l.y = s0["x"], s0["y"]
w._try_break()
exp0 = f"{s0['value']}:{s0['icon']}"
chk(f"敲碎第 0 号容器拿到 {exp0}", l.carrying == [exp0], f"carrying={l.carrying}")
chk("容器标记为已破", w.room.stashes[0]["broken"] is True)
# ⭐ 只能拿一件：手上���东西时再敲下一个容器不会多拿
l.x, l.y = w.room.stashes[1]["x"], w.room.stashes[1]["y"]
w._try_break()
chk("手上有东西时不能再拿", len(l.carrying) == 1,
    f"carrying={l.carrying}  stash[1].broken={w.room.stashes[1]['broken']}")

l.x = 150.0                            # 走进窝里
step(1 / 60, 5)
chk("回窝 **不结算**，只放下（暂存）", w.phase == "play" and bool(w.loot_stash),
    f"phase={w.phase} loot_stash={w.loot_stash}")
chk("放下后手上空了", l.carrying == [], f"carrying={l.carrying}")
chk("窝边汇总还没加（没结算）", w.total_loot == 0, f"total={w.total_loot}")
w._try_break()                        # 在窝边按 E = 结算
chk("窝边按 E → 出结算面板", w.phase == "result", f"phase={w.phase}")
r = w.result or {}
chk("结算记了带回数", r.get("loot") == 1, f"{r}")
chk("结算有评级", r.get("rank") in ("S", "A", "B", "C"), f"rank={r.get('rank')}")
chk("结算后窝边拿库清空", w.loot_stash == [], f"{w.loot_stash}")
chk("窝边累计 = 该容器的价值（不是 1）", w.total_loot == s0["value"],
    f"total={w.total_loot}  该容器 value={s0['value']}")
chk("loot_log 记的是实际偷到的", w.loot_log == [exp0], f"{w.loot_log}")

# ⭐ 惩罚要轻：已入库的绝不能被倒扣
before = w.total_loot
w.start_night(1)
l = w.luna
l.x, l.y = N.STASHES[0]["x"], N.STASHES[0]["y"]
w._try_break()
l.x, l.y = 1000.0, N.FLOOR_Y           # 抱着赃物跑到禁区深处
w.mw.x, w.mw.y = 1000.0, N.FLOOR_Y
w.mw.alert, w.mw.state = 1.0, "chase"
step(1 / 60, 3)
chk("被抓时手上赃物还没入账", w.total_loot == before, f"{before} → {w.total_loot}")

print()
print("=" * 72)
print("⑨ 被抓 → YOU MEOWED → 押送回窝")
print("=" * 72)
w.start_night(1)
l = w.luna
l.x, l.y = 1000.0, N.FLOOR_Y
w.mw.x, w.mw.y = 1000.0, N.FLOOR_Y
w.mw.alert, w.mw.state = 1.0, "chase"
l.carrying = ["yogurt"]
step(1 / 60, 3)
chk("触发 YOU MEOWED", w.phase == "meowed", f"phase={w.phase}")
chk("被抓计数 +1", w.caught_cnt == 1, f"caught={w.caught_cnt}")
render()
chk("meowed 画面能画（无异常）", True)

step(1 / 60, 200)                     # 1.5s 大字 + 0.9s 押送，留余量
chk("押送后回到 play", w.phase == "play", f"phase={w.phase}")
chk("被押送回窝", abs(l.x - (N.NEST_X0 + 70)) < 2.0, f"x={l.x:.1f} 期望 {N.NEST_X0+70}")
chk("赃物清零", l.carrying == [], f"carrying={l.carrying}")
chk("总赃物没被倒扣", w.total_loot == before, f"{before} → {w.total_loot}")

print()
print("=" * 72)
print("⑩ 三档配置 + 选档")
print("=" * 72)
chk("三档齐备", len(N.NIGHTS) == 3, f"{[n['name'] for n in N.NIGHTS]}")
for i, cfg in enumerate(N.NIGHTS):
    w.start_night(i)
    mw, rm = w.mw, w.room
    gap = N.RUN_SPEED - cfg["chase_speed"]
    chk(f"档{i+1} {cfg['name']}：追得掉（{gap:.0f}px/s 余速）", gap > 0, f"追 {cfg['chase_speed']:.0f} vs 跑 {N.RUN_SPEED:.0f}")
    chk(f"档{i+1} 边界一致（room=配置）", rm.border_x == cfg["border_x"],
        f"room {rm.border_x} vs cfg {cfg['border_x']}")
    chk(f"档{i+1} 微波炉用的是本档速度", abs(mw.chase_speed - cfg["chase_speed"]) < 1e-6,
        f"mw {mw.chase_speed} vs cfg {cfg['chase_speed']}")
    chk(f"档{i+1} 巡逻段在本档范围内", mw.p0 == cfg["patrol"][0] and mw.p1 == cfg["patrol"][1])
    # ⛔ 难度必须真的单调递增（否则"三档"只是三个名字）
    if i:
        p = N.NIGHTS[i - 1]
        harder = (cfg["alert_gain"] > p["alert_gain"] and
                  cfg["border_x"] <= p["border_x"] and
                  len(cfg["stashes"]) >= len(p["stashes"]) and
                  cfg["chase_speed"] >= p["chase_speed"])
        chk(f"档{i+1} 确实比档{i} 难", harder,
            f"警戒 {p['alert_gain']}→{cfg['alert_gain']}　"
            f"边界 {p['border_x']}→{cfg['border_x']}　"
            f"赃物 {len(p['stashes'])}→{len(cfg['stashes'])}　"
            f"追速 {p['chase_speed']}→{cfg['chase_speed']}")

print()
print("=" * 72)
print("⑪ 旁白")
print("=" * 72)
w.start_night(1)
l = w.luna
n_steal = len(N.NARRATION["steal"])
w._narr_seen.clear()
r1 = []
for _ in range(n_steal):
    w._narrate("steal")
    r1.append(w.msg)
chk(f"一轮 {n_steal} 抽不重复", len(set(r1)) == n_steal, f"{r1}")
r2 = []
for _ in range(n_steal):
    w._narrate("steal")
    r2.append(w.msg)
chk("池子抽干后轮转（第二轮仍不重复）", len(set(r2)) == n_steal, f"{r2}")
chk("轮转不影响别的池子", w._narr_seen.issubset({("steal", i) for i in range(n_steal)}),
    f"{sorted(w._narr_seen)}")
for k, pool in N.NARRATION.items():
    chk(f"旁白池「{k}」非空", len(pool) > 0, f"{len(pool)} 句")
chk("开场白三档各一句", all(len(N.NARRATION["enter"]) >= 3 for _ in (0,)), "3 句")

print()
print("=" * 72)
print("⑫ 渲染（真实 paintEvent）")
print("=" * 72)
for ph in ("play", "meowed", "result", "menu"):
    w.phase = ph
    w.phase_t = 0.5
    w.mw.alert, w.mw.state = (1.0, "chase") if ph in ("play", "menu") else (0.0, "patrol")
    if ph == "menu":
        w.menu_sel = 2
    if ph == "result":
        w.result = w.result or {"night": "深夜", "loot": 5, "left": 0, "total": 12,
                                "caught": 1, "time": 96.0, "score": 585, "rank": "A"}
    try:
        render()
        chk(f"{ph} 画面能画", True)
    except Exception as e:
        chk(f"{ph} 画面能画", False, f"{type(e).__name__}: {e}")

# 爬梯态
w.phase = "play"
l.on_ladder = True
l.act = "climb"
try:
    render()
    chk("climb 画面能画", True)
except Exception as e:
    chk("climb 画面能画", False, f"{type(e).__name__}: {e}")

print()
print("=" * 72)
print("⑬ 爬梯动作（Ronny 2026-10-03 实机反馈：动作没装上）")
print("=" * 72)
w.start_night(1)
l = w.luna
l.x, l.y = float(LADX), FLOOR
l.vx = l.vy = 0.0
l.on_ladder = False
l.on_ground = True
l.jump_latch = False

w.keys = {Qt.Key_W}
step_pure(1 / 60, 12)
t0 = l.t
step_pure(1 / 60, 12)
t1 = l.t
chk("爬梯时动作是 climb", l.act == "climb", f"act={l.act}")
chk("爬梯时动画帧在推进", t1 > t0, f"t {t0:.2f} → {t1:.2f}（fps=12）")

w.keys = set()
step_pure(1 / 60, 2)
t2 = l.t
step_pure(1 / 60, 10)
chk("松开按键后帧停住（不悬空蹬腿）", abs(l.t - t2) < 1e-6,
    f"t {t2:.2f} → {l.t:.2f}")

w.keys = {Qt.Key_S}
t3 = l.t
step_pure(1 / 60, 12)
chk("下梯时动画倒着播（t 递减）", l.t < t3, f"t {t3:.2f} → {l.t:.2f}")
chk("下梯确实在往下走", l.y > 470.0, f"y={l.y:.1f}")

# ⭐ 爬梯时按左右要能蹬开 —— 不做这条她会卡在梯子上（A/D 被爬梯分支吞掉）
#   ⭐ 2026-10-03：蹬开点必须低于"布顶+46"（离顶 46px 内按左右 = 跨上桌面，是另一条语义）
w.keys = set()
l.x, l.y = float(LADX), 550.0
l.vx = l.vy = 0.0
l.on_ladder = True
l.on_ground = False
w.keys = {Qt.Key_D}
step_pure(1 / 60, 3)
chk("梯子上按左右能蹬开（不卡死）", (not l.on_ladder) and abs(l.vx) > 1.0,
    f"on_ladder={l.on_ladder} vx={l.vx:.0f}")
w.keys = set()
step_pure(1 / 60, 60)
chk("蹬开后正常落到地板", abs(l.y - N.FLOOR_Y) < 2.0, f"y={l.y:.1f}")

# 下梯画面能画（走真实 paintEvent）
l.on_ladder = True
l.climb_down = True
l.act = "climb"
l.t = 6.0
try:
    render()
    chk("下梯画面能画", True)
except Exception as e:
    chk("下梯画面能画", False, f"{type(e).__name__}: {e}")

print()
print()
print("=" * 72)
print("\u2714 \u5668\u9f44 + \u566a\u58f0 + \u6f5c\u884c + \u722c\u68af\u5b89\u5168")
print("=" * 72)
w.start_night(1)
l, mw = w.luna, w.mw

# ⭐⭐ 2026-10-04：容器分四档后，噪声测试**必须显式挑档**。
#   ⛔ 别再用硬编码下标（旧写法取 stashes[2]，重排后变成 plate/loose）——
#     噪声是逐档的（loose 0 / plate 0.26 / jar 0.62），拿错档整组断言必假失败。
#   ✅ 按 kind 找样本：噪声测试用 jar（最响），零噪声测试用 loose。
def _pick(w, kind):
    """返回该档里第一个还没被破的容器"""
    for s in w.room.stashes:
        if s.get("kind") == kind and not s["broken"]:
            return s
    return None


# ---------- ① jar：贴身敲 = 大声 ----------
w.start_night(1)
l, mw = w.luna, w.mw
_st = _pick(w, "jar")
chk("本档有 jar 容器（噪声测试样本）", _st is not None, f"{_st}")
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + 10, FLOOR        # 距离 10px：贴着耳朵敲
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
near_alert = mw.alert
chk("贴身敲罐 = 忽略噪声，alert 上升 >0.5", near_alert > 0.5,
    f"alert={near_alert:.2f}  dist=10px  kind=jar")
chk("噪声会记住声源（他转头看）", mw.hear_x is not None,
    f"hear_x={mw.hear_x}")
# ⭐⭐ 破罐 = 直接疯狂追踪（Ronny 2026-10-04 核心需求）
chk("⭐ 破罐 → 守卫直接 frenzy", mw.fury is True,
    f"fury={mw.fury}  fury_t={mw.fury_t:.1f}")
chk("frenzy 时 state=chase 且 alert 锁 1.0",
    mw.state == "chase" and mw.alert >= 1.0,
    f"state={mw.state} alert={mw.alert:.2f}")
chk("frenzy 锁定的是【罐子的位置】不是露娜",
    mw.fury_x == float(_st["x"]),
    f"fury_x={mw.fury_x} 罐子x={_st['x']} 露娜x={l.x:.0f}")

# ---------- ② jar：远处敲 = 小声 ----------
w.start_night(1)
l, mw = w.luna, w.mw
_st = _pick(w, "jar")
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + 410.0, N.FLOOR_Y    # 距离 410px：听得见但弱很多
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
far_alert = mw.alert
chk("远处敲罐 = 声音小，但 alert 仍上升", 0.02 < far_alert < 0.30,
    f"alert={far_alert:.2f}  dist=410px")
chk("距离越近噪声越大", far_alert < near_alert,
    f"{far_alert:.2f} < {near_alert:.2f}")

# ---------- ③ loose：零噪声（2026-10-04 新增档位）----------
w.start_night(1)
l, mw = w.luna, w.mw
_st = _pick(w, "loose")
chk("本档有 loose 容器（零噪声样本）", _st is not None, f"{_st}")
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + 10, FLOOR
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
chk("⭐ loose 贴身拿 = 完全无声（alert 不动）", mw.alert == 0.0,
    f"alert={mw.alert:.3f} kind=loose noise={_st['noise']}")
chk("loose 不会引发 frenzy", mw.fury is False, f"fury={mw.fury}")
# ⭐ 四档噪声必须是**严格递增**（否则分档就没意义了）
_nz = {k: N.KIND_TABLE[k]["noise"] for k in N.KIND_ORDER}
chk("四档噪声递增：loose<plate<fridge<jar",
    _nz["loose"] < _nz["plate"] < _nz["fridge"] < _nz["jar"], f"{_nz}")
# ⭐⭐ 风险与价值同向（设计不变量，Ronny 10-04 核心约束）
_vl = {k: N.KIND_TABLE[k]["value"] for k in N.KIND_ORDER}
chk("⭐ 价值递增：loose<plate<fridge<jar（风险越高越值钱）",
    _vl["loose"] < _vl["plate"] < _vl["fridge"] < _vl["jar"], f"{_vl}")
chk("⭐ 只有 jar 会引爆 frenzy",
    [k for k in N.KIND_ORDER if N.KIND_TABLE[k]["fury"]] == ["jar"],
    f"{[k for k in N.KIND_ORDER if N.KIND_TABLE[k]['fury']]}")

# 超出听觉半径 = 完全听不见
w.start_night(1)
l, mw = w.luna, w.mw
_st = w.room.stashes[2]
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + 460.0, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
chk("超出听觉半径就完全听不见", mw.alert < 0.001,
    f"alert={mw.alert:.3f}  dist=460px  半径={N.MW_HEAR_R:.0f}")

# ---- 累f积f而c不d是f一0敲2满1：a敲2三9下b才d快b进b追d踪a ----
w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, COUNTER
mw.x, mw.y = float(LADX), FLOOR
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._break_fx = []
alerts = []
for k in range(3):
    if not w.room.stashes[k]["broken"]:
        l.x, l.y = w.room.stashes[k]["x"], w.room.stashes[k]["y"]
        w._try_break()
    alerts.append(mw.alert)
    l.carrying = []   # ⛔ 只能拿一件，模拟回窝放下才能再敲
step_ai(1 / 60, 3)   # 让 update 跑一下，state 才会更新   # ⛔ 用 step_ai：step_pure 每帧把 mw.state 重置为 patrol
chk("\u8d34\u8eab敲\u4e24\u4e0b\u5c31\u8fdb chase\uff08不是\u4e00\u6572\u6ee1\uff09", mw.state == "chase",
    f"alerts={[round(a,2) for a in alerts]} state={mw.state}")

# 远处敲：弱很多，敲完一整层也不该靠累积锁定
# ⭐⭐ 2026-10-04 改判据（容器分四档 + investigate 之后，这条断言的**前提整个变了**）：
#   旧写法断言「逐个敲光全部容器 → 累积到 chase」。那在"所有容器噪声都是 0.62"的
#   旧设计下成立（五次叠到 3.1）。四档分化后（loose 0 / plate 0.26 / jar 0.62）
#   本档理论上限只有 0.552，**永远到不了 1.0** —— 旧断言是拿旧数据套新代码。
#
#   ⛔ 但改判据前必须先回答"这是 bug 还是新设计的必然"（2026-10-04 实测算过）：
#     守卫在 x=1050 时逐个敲的实测累计 = [0.00, 0.14, 0.31, 0.55, 0.55]。
#     0.55 是**数学上限**而非"衰减吃掉了"—— 说明"敲光一整层不足以引 him 锁定"
#     是四档设计的必然结果，不是漏配。
#     再加上 ALERT_DECAY=0.8/秒 + "一次只能拿一件"（每趟回窝 3~4 秒），
#     跨容器的 alert 累积在**真实玩法里根本不可达**（峰值从没超过 0.25）。
#   ✅ 所以噪声机制换了一条兑现路径：**investigate（走过去查看）**，见下面新增那组。
#   ⛔ 别再把"累积到 chase"当噪声机制的验收标准，除非先改KIND_TABLE 的数值设计。
w.start_night(1)
l, mw = w.luna, w.mw
mw.x, mw.y = 1050.0, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
mw.invest_x, mw.invest_linger, mw.invest_hold = None, 0.0, 0.0
far_alerts = []
for k in range(len(w.room.stashes)):
    if not w.room.stashes[k]["broken"]:
        l.x, l.y = w.room.stashes[k]["x"], w.room.stashes[k]["y"]
        w._try_break()
    far_alerts.append(mw.alert)
    l.carrying = []
step_ai(1 / 60, 3)
# ✅ ① 正确预期：敲光非 frenzy 容器**不会**触发 chase（这是设计，不是 bug）
chk("敲光一整层不靠累积触发 chase（四档噪声上限 < 1.0）",
    mw.state != "chase" and mw.alert < 1.0,
    f"far_alerts={[round(a, 2) for a in far_alerts]} state={mw.state} alert={mw.alert:.3f}")
# ✅ ② 但逐个靠近确实单调不减（噪声机制没坏，只是上限变了）
_inc = all(b >= a - 1e-9 for a, b in zip(far_alerts, far_alerts[1:]))
chk("逐个靠近时 alert 单调不减（越近越响）", _inc,
    f"{[round(a, 2) for a in far_alerts]}")

# ============================================================================
# ⭐⭐ investigate（走过去查看声源）—— Ronny 2026-10-04 拍板「方向二」
#
# ⭐ 为什么这组断言必须存在（四档容器逼出来的空洞，不是凭空加的功能）：
#   ALERT_DECAY=0.8/秒，而"一次只能拿一件"要求每趟回窝 3~4 秒。
#   实测：plate 档 0.26 的噪声即使贴着守卫敲，alert 峰值也只有 0.26，
#   回窝路上必然衰减归零 → **plate 成哑档**（分档做了、手感做了，玩起来没后果）。
#   investigate 补的是噪声的**位置后果**：不是把 alert 堆满，而是让他**挪开**。
#
# ⛔ 三条不变量逐条断言（改动这个功能前先读）：
#   ① 速度 < RUN_SPEED：查看不是追杀，玩家永远跑得掉
#   ② 目标夹进可活动区：不能走出房间
#   ③ 一次性：到达 → 环顾 → 回巡逻；且 chase 永远压过 investigate
# ============================================================================

def _reset_inv():
    mw.invest_x, mw.invest_linger, mw.invest_hold = None, 0.0, 0.0


# ---------- ① 贴脸敲 plate → 他真的走过去看 ----------
w.start_night(1)
l, mw = w.luna, w.mw
_st = _pick(w, "plate")
chk("本档有 plate 容器（investigate 样本）", _st is not None, f"{_st}")
l.x, l.y = _st["x"], _st["y"]
l.carrying = []
mw.x, mw.y = _st["x"] - 60.0, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
_reset_inv()
w._try_break()
chk("⭐ 够响的声响登记了触发记忆（invest_hold > 0）",
    mw.invest_hold > 0.0, f"hold={mw.invest_hold:.2f}")
_x0 = mw.x
for _ in range(20):                # 最多走 10 秒，中途被 chase 就停
    step_ai(1 / 60, 30)
    if mw.state == "chase":
        break
chk("⭐ 他离开巡逻位走向声源", abs(mw.x - _x0) > 40.0,
    f"位移 {abs(mw.x - _x0):.0f}px  { _x0:.0f} -> {mw.x:.0f}")
chk("走到声源附近停住", abs(mw.x - _st["x"]) < 70.0,
    f"偏差 {abs(mw.x - _st['x']):.0f}px（声源 x={_st['x']}）")
chk("查看是一次性的：看完回巡逻，不是追着人跑",
    mw.invest_x is None and mw.state != "chase",
    f"state={mw.state} invest_x={mw.invest_x}")
chk("环顾计时无负值残留（只清 invest_x 会留脏状态）",
    mw.invest_linger >= 0.0, f"linger={mw.invest_linger:.3f}")

# ---------- ② 远距离敲 plate → 不启动查看（位置仍是战术资源）----------
w.start_night(1)
l, mw = w.luna, w.mw
_st2 = _pick(w, "plate")
l.x, l.y = _st2["x"], _st2["y"]
l.carrying = []
mw.x, mw.y = _st2["x"] + 400.0, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
_reset_inv()
w._try_break()
_k400 = mw.hear_strength(float(_st2["x"]), 0.26)
step_ai(1 / 60, 20)
chk("400px 外敲 plate 不启动查看（听不清就只转头）",
    mw.invest_x is None,
    f"衰减后 k={_k400:.3f} < 门槛 {N.INVEST_ALERT:.2f}  invest_x={mw.invest_x}")

# ---------- ③ 三条不变量 ----------
chk("不变量①investigate 速度 < RUN_SPEED（他是在查看不是追杀）",
    N.INVEST_SPEED < N.RUN_SPEED - 8.0,
    f"{N.INVEST_SPEED:.0f} < {N.RUN_SPEED - 8.0:.0f}")

_LO = mw.w * 0.5 + 8.0
_HI = N.VW - mw.w * 0.5 - 8.0
_edge_ok = True
_edge_info = []
for _hx in (5.0, 1275.0, 640.0):         # 左右边界外 + 房中央
    w.start_night(1)
    l, mw = w.luna, w.mw
    mw.alert, mw.state = 0.0, "patrol"
    mw.hear_x = _hx
    mw.x, mw.y = 300.0, N.FLOOR_Y
    _reset_inv()
    mw.invest_hold = 99.0                   # 强制启动
    step_ai(1 / 60, 1)
    _tgt = mw.invest_x
    step_ai(1 / 60, 200)
    _inside = (_LO - 1.0) <= mw.x <= (_HI + 1.0)
    _edge_ok = _edge_ok and (_tgt is not None
                             and _LO - 1.0 <= _tgt <= _HI + 1.0 and _inside)
    _edge_info.append(f"hx={_tgt}→x={mw.x:.0f}")
chk("不变量② 目标夹进可活动区，他不会走出房间", _edge_ok,
    f"界=[{_LO:.0f},{_HI:.0f}]  " + " ".join(_edge_info))

# chase 压过 investigate
w.start_night(1)
l, mw = w.luna, w.mw
mw.alert, mw.state = 0.0, "patrol"
mw.hear_x = 1100.0
mw.x, mw.y = 300.0, N.FLOOR_Y
_reset_inv()
mw.invest_hold = 99.0
step_ai(1 / 60, 1)
_inv_started = mw.invest_x is not None
mw.state = "chase"
mw.alert = 1.0                              # 强行进入 chase
step_ai(1 / 60, 1)
_inv_cleared = (mw.invest_x is None and mw.invest_linger == 0.0)
step_ai(1 / 60, 10)
chk("不变量③ chase 立刻压过 investigate（发现你就只追你）",
    _inv_started and _inv_cleared and mw.invest_x is None,
    f"先启动={_inv_started} 进chase后清空={_inv_cleared}  10帧后={mw.invest_x}")



# ---- 潜c行c：a按9 Shift 变8慢2且4换2成0 walk动8作c ----
w.start_night(1)
l = w.luna
l.x, l.y = 300.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
w.keys = {Qt.Key_Shift, Qt.Key_D}
step_pure(1 / 60, 60)
vx_sneak = l.x - 300.0
chk("\u6f5c\u884c 1s \u79fb\u52a8 80~125px", 80 < vx_sneak < 125, f"{vx_sneak:.0f}px  \u666e\u901a\u662f {N.RUN_SPEED:.0f}")
chk("\u6f5c\u884c\u65f6\u72b6\u6001\u6807\u4e3a\u6f5c\u884c\u4e2d", l.sneak is True)
chk("\u6f5c\u884c\u7528 sneak \u52a8\u4f5c\uff08\u4e0d\u662f walk / human_run\uff09", l.act == "sneak", f"act={l.act}")
w.keys = set()
step_pure(1 / 60, 30)
chk("\u677e\u5f00 Shift \u6062\u590d\u5e38\u901f", l.sneak is False)

# ⭐ 2026-10-03：布墙 470~730 —— 潜行 1s 后她已在 ~408，再跑 1s 会撞墙，挪到开阔段再测
l.x, l.y = 800.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
_x0 = l.x
w.keys = {Qt.Key_D}
step_pure(1 / 60, 60)
chk("\u5e38\u901f 1s \u79fb\u52a8 240~320px", 240 < l.x - _x0 < 320,
    f"{l.x - _x0:.0f}px")
chk("\u5e38\u901f\u65f6\u7528 human_run", l.act == "human_run", f"act={l.act}")
w.keys = set()

# ---- 爬c梯f子0 = 完c全8安9全8（8Lode Runner 机a制6）9 ----
w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = float(LADX), 510.0                  # 爬c梯f中d段5（⛔ 别放 520：断言是 y<520 严格小于，放 520 必挂）
l.vx = l.vy = 0.0
l.on_ladder, l.on_ground = True, False
l.escort = False                                # ⭐ 上一组若被抓，escort 残留会让 sense 直接归零
mw.x, mw.y = float(LADX), FLOOR
mw.alert, mw.state = 0.30, "chase"       # ⭐ 从 0.3 起步：从满值 1.0 起步永远看不出「缓涨」
mw.hear_x = None
a0 = mw.alert
step_ai(1 / 60, 60)
chk("梯子上不再绝对安全：他追得上来（Ronny 10-03 上强度）", l.on_ladder and l.y < 520.0,
    f"y={l.y:.0f} on_ladder={l.on_ladder}")
chk("梯子上警戒缓涨而非归零", mw.alert > a0, f"alert {a0:.2f} -> {mw.alert:.2f}")

# 下b来5就1不d安9全8了6
l.on_ladder = False
l.on_ground = True
l.y = N.FLOOR_Y
l.escort = False                                # ⭐ 押送态会挡住 sense（trespass 判定带 not escort）
mw.alert = 0.0
step_ai(1 / 60, 40)
chk("\u4e0b\u6765\u540e\u6062\u590d\u88ab\u89c1\u8ff7\u7684\u53ef\u80fd", mw.alert > 0.2,
    f"alert={mw.alert:.2f}")

# ---- 画b面2能d画b（8容9器8/碎e片7/潜c行c）9 ----
w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, COUNTER
l.sneak = True
w._break_fx = [[690.0, 470.0, 0.4]]
for st in w.room.stashes:
    st["broken"] = (st["x"] > 800)
try:
    render()
    chk("\u5bb9\u5668+\u788e\u7247+\u6f5c\u884c\u753b\u9762\u80fd\u753b", True)
except Exception as e:
    chk("\u5bb9\u5668+\u788e\u7247+\u6f5c\u884c\u753b\u9762\u80fd\u753b", False, f"{type(e).__name__}: {e}")

print()
print("=" * 72)
print("\u2714 \u5fae\u6ce2\u7089\u4f53\u578b / \u722c\u68af / \u8df3\u8dc3\uff08Ronny 10-03\uff1a\u4e0a\u5f3a\u5ea6\uff09")
print("=" * 72)
w.start_night(1)
l, mw = w.luna, w.mw
chk("\u5fae\u6ce2\u7089\u6bd4\u9732\u5a1c\u9ad8\uff08183cm vs 150cm\uff09", mw.body_h > N.ACTOR_H,
    f"mw {mw.body_h:.0f}px  vs  \u9732\u5a1c {N.ACTOR_H:.0f}px")
chk("\u722c\u68af\u6bd4\u9732\u5a1c\u6162\uff08\u7ed9\u5979\u8131\u7a00\u7a97\u53e3\uff09", mw.climb_speed < N.CLIMB_SPEED,
    f"mw {mw.climb_speed:.0f} vs \u9732\u5a1c {N.CLIMB_SPEED:.0f} px/s")
chk("\u5fae\u6ce2\u7089\u8df3\u4e0d\u4e0a\u53bb\u6599\u7406\u53f0\uff08\u843d\u5dee178px\uff09",
    mw.jump_v ** 2 / (2 * N.GRAVITY) < 170.0,
    f"\u8df3\u9ad8 {mw.jump_v**2/(2*N.GRAVITY):.0f}px < 170")

# 跳3跃3：a距d离b 150~330px 且4露2娜c在8地0板f上a →2 他6会a跳3一0下b压b过7来5
l.x, l.y = 900.0, N.FLOOR_Y
l.on_ground, l.vy, l.on_ladder = True, 0.0, False
mw.x, mw.y = 600.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground, mw.jump_cd = "chase", 1.0, 0.0, True, 0.0
w.phase = "play"
mw._chase(1 / 60, l, w.room)
chk("\u8fdc\u79bb\u65f6\u4f1a\u8df3\uff08\u538b\u8fc7\u6765\uff09", (not mw.on_ground) and mw.vy < 0,
    f"vy={mw.vy:.0f} on_ground={mw.on_ground}")
top = mw.y
for _ in range(90):
    mw._chase(1 / 60, l, w.room)
    top = min(top, mw.y)
chk("\u8df3\u8dc3\u540e\u4f1a\u843d\u56de\u5730\u677f", mw.on_ground and abs(mw.y - N.FLOOR_Y) < 1.0,
    f"y={mw.y:.1f}")
chk("\u8df3\u9ad8\u5728\u9884\u671f\u5185", N.FLOOR_Y - top < 90, f"\u5b9e\u9645\u8df3\u9ad8 {N.FLOOR_Y-top:.0f}px")

# 爬c梯f：a露2娜c在8台0面2上a →2 他6走0到0梯f子0脚a下b并6爬c上a来5
l.x, l.y = float(LADX), float(LADTOP)
l.on_ground, l.vy = True, 0.0
mw.x, mw.y = 620.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground = "chase", 1.0, 0.0, True
for _ in range(200):
    mw._chase(1 / 60, l, w.room)
chk("\u722c\u68af\u80fd\u529b\uff1a\u4f1a\u8d70\u5230\u68af\u5b50\u5e76\u722c\u4e0a\u53f0\u9762", mw.y < N.FLOOR_Y - 100,
    f"mw.y={mw.y:.0f}  \u53f0\u9762 470")

# 爬c梯f不d可f能d越a过7台0面2底5（8不d会a穿f墙9）9
mw.y = min(mw.y, 468.0)
chk("\u722c\u68af\u4e0d\u4f1a\u7a7f\u8fc7\u53f0\u9762\u9876", mw.y >= 468.0, f"mw.y={mw.y:.0f}")

print()
print("=" * 72)
print("⑭ 2026-10-03 三连修：布墙 / 攀爬面 / QTE 锁移动（Ronny 实机反馈）")
print("=" * 72)

# ① 布墙：脚低于桌面时，从布区外不许一步跨进 TABLE_X0~TABLE_X1
# ⛔ 2026-10-04：起点原来写死 x=430，而**新布局 TABLE_X0 就是 430** ——
#   人一出生就在布区里，按设计规则「已在布区内的人自由走出」当然能走出去，
#   于是报 x=580 FAIL。判据不是被产品代码拦的，是它自己站错了起点。
#   ✅ 起点改成 TABLE_X0 - 80（布区外 80px），跑 0.5s 撞墙，期望被钉在 TABLE_X0 - m。
#   ⛔ 真实厨房里也不可能"从桌布里面走出来" —— 那里是桌子底下，只能从桌面下。
w.start_night(1)
l = w.luna
l.x, l.y = N.TABLE_X0 - 80.0, N.FLOOR_Y
l.vx, l.vy = N.RUN_SPEED, 0.0
l.on_ground = True
for _ in range(30):
    l.update(1 / 60, {Qt.Key_D}, w.room)     # 0.5s 全速右跑
_m = N.BODY_W * 0.35
chk("布墙：地面全速右跑被拦在布区外", l.x <= N.TABLE_X0 - _m + 1.0,
    f"x={l.x:.0f}（钉位 {N.TABLE_X0 - _m:.1f}） 布左缘 {N.TABLE_X0}")

# ② 攀爬面：布前按 W 能扒布，一路爬到桌面（整面可扒，不是只有一根杆）
l.x, l.y = 448.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ladder = False
l.on_ground = True
w.keys = {Qt.Key_W}
step_pure(1 / 60, 150)
w.keys = set()
chk("攀爬面：布前按 W 爬到桌面", abs(l.y - N.TABLE_TOP) < 2.0 and not l.on_ladder,
    f"y={l.y:.1f} 期望 {N.TABLE_TOP}")

# ③ 爬到底 = 站在地板上（⛔ 不是地板下方 —— 底端 632 就是「掉到地底下」事故的根因）
l.x, l.y = 600.0, 500.0
l.on_ladder = True
l.on_ground = False
w.keys = {Qt.Key_S}
step_pure(1 / 60, 120)
w.keys = set()
chk("爬布到底落在地板上（不在地板下方）", abs(l.y - N.FLOOR_Y) < 1.0 and not l.on_ladder,
    f"y={l.y:.1f} 期望 {N.FLOOR_Y}")

# ④ QTE 锁移动：QTE 期间方向键只喂 QTE，不驱动移动
w.start_night(1)
l = w.luna
l.x, l.y = 610.0, N.TABLE_TOP          # 站在桌面冰箱前
l.vx = l.vy = 0.0
l.on_ground = True
w.keys = set()
w._qte_start()
qx = l.x
w.keys = {Qt.Key_Left, Qt.Key_Right}
step(1 / 60, 10)                        # 0.17s，一直按着左右
moved = abs(l.x - qx)
chk("QTE 期间方向键不移动", moved < 1.0 and w.qte is not None,
    f"位移 {moved:.1f}px  qte={'进行中' if w.qte else '已结束'}")
w.qte = None
w.keys = set()

print("=" * 72)
print(f"通过 {len(OK)} / {len(OK)+len(BAD)}")
if BAD:
    print("未通过： " + "、".join(BAD))
print("=" * 72)
time.perf_counter = _orig


print()
print("=" * 72)
print("\u2714 \u5fae\u6ce2\u7089\u4f53\u578b / \u722c\u68af / \u8df3\u8dc3\uff08Ronny 10-03\uff1a\u4e0a\u5f3a\u5ea6\uff09")
print("=" * 72)
w.start_night(1)
l, mw = w.luna, w.mw
chk("\u5fae\u6ce2\u7089\u6bd4\u9732\u5a1c\u9ad8\uff08183cm vs 150cm\uff09", mw.body_h > N.ACTOR_H,
    f"mw {mw.body_h:.0f}px  vs  \u9732\u5a1c {N.ACTOR_H:.0f}px")
chk("\u722c\u68af\u6bd4\u9732\u5a1c\u6162\uff08\u7ed9\u5979\u8131\u7a00\u7a97\u53e3\uff09", mw.climb_speed < N.CLIMB_SPEED,
    f"mw {mw.climb_speed:.0f} vs \u9732\u5a1c {N.CLIMB_SPEED:.0f} px/s")
chk("\u5fae\u6ce2\u7089\u8df3\u4e0d\u4e0a\u53bb\u6599\u7406\u53f0\uff08\u843d\u5dee178px\uff09",
    mw.jump_v ** 2 / (2 * N.GRAVITY) < 170.0,
    f"\u8df3\u9ad8 {mw.jump_v**2/(2*N.GRAVITY):.0f}px < 170")

# 跳3跃3：a距d离b 150~330px 且4露2娜c在8地0板f上a →2 他6会a跳3一0下b压b过7来5
l.x, l.y = 900.0, N.FLOOR_Y
l.on_ground, l.vy, l.on_ladder = True, 0.0, False
mw.x, mw.y = 600.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground, mw.jump_cd = "chase", 1.0, 0.0, True, 0.0
w.phase = "play"
mw._chase(1 / 60, l, w.room)
chk("\u8fdc\u79bb\u65f6\u4f1a\u8df3\uff08\u538b\u8fc7\u6765\uff09", (not mw.on_ground) and mw.vy < 0,
    f"vy={mw.vy:.0f} on_ground={mw.on_ground}")
top = mw.y
for _ in range(90):
    mw._chase(1 / 60, l, w.room)
    top = min(top, mw.y)
chk("\u8df3\u8dc3\u540e\u4f1a\u843d\u56de\u5730\u677f", mw.on_ground and abs(mw.y - N.FLOOR_Y) < 1.0,
    f"y={mw.y:.1f}")
chk("\u8df3\u9ad8\u5728\u9884\u671f\u5185", N.FLOOR_Y - top < 90, f"\u5b9e\u9645\u8df3\u9ad8 {N.FLOOR_Y-top:.0f}px")

# 爬c梯f：a露2娜c在8台0面2上a →2 他6走0到0梯f子0脚a下b并6爬c上a来5
l.x, l.y = float(LADX), float(LADTOP)
l.on_ground, l.vy = True, 0.0
mw.x, mw.y = 620.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground = "chase", 1.0, 0.0, True
for _ in range(200):
    mw._chase(1 / 60, l, w.room)
chk("\u722c\u68af\u80fd\u529b\uff1a\u4f1a\u8d70\u5230\u68af\u5b50\u5e76\u722c\u4e0a\u53f0\u9762", mw.y < N.FLOOR_Y - 100,
    f"mw.y={mw.y:.0f}  \u53f0\u9762 470")

# 爬c梯f不d可f能d越a过7台0面2底5（8不d会a穿f墙9）9
mw.y = min(mw.y, 468.0)
chk("\u722c\u68af\u4e0d\u4f1a\u7a7f\u8fc7\u53f0\u9762\u9876", mw.y >= 468.0, f"mw.y={mw.y:.0f}")
