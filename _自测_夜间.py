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
l.x, l.y = 300.0, 200.0
l.vx = l.vy = 0.0
step_pure(1 / 60, 90)                 # 1.5s 自由落体
chk("落到地板", abs(l.y - N.FLOOR_Y) < 1.0, f"y={l.y:.1f} 期望 {N.FLOOR_Y}")
chk("落地后 on_ground", l.on_ground)

print()
print("=" * 72)
print("③ 跑动")
print("=" * 72)
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
chk("跳得上料理台(落差178)", h > 178 + 12, f"余量 {h - 178:.0f}px")
chk("跳不上吊柜(落差328，须经台面中转)", h < 328 - 40, f"差 {328 - h:.0f}px")
chk("按住 W 落地后不连跳", abs(l.y - N.FLOOR_Y) < 1.0, f"y={l.y:.1f}")

print()
print("=" * 72)
print("⑤ 跳上料理台（全程按住 W）")
print("=" * 72)
l.x, l.y = 760.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
l.jump_latch = False
w.keys = {Qt.Key_W}
step_pure(1 / 60, 110)
w.keys = set()
chk("站在料理台顶面 470", abs(l.y - 470.0) < 1.5, f"y={l.y:.1f}")
chk("落台后不再弹起", l.on_ground and abs(l.vy) < 1.0,
    f"vy={l.vy:.1f} on_ground={l.on_ground}")

print()
print("=" * 72)
print("⑥ 爬梯（地板 → 料理台）")
print("=" * 72)
l.x, l.y = 700.0, N.FLOOR_Y          # 梯子中心 x=700
l.vx = l.vy = 0.0
l.on_ladder = False
l.jump_latch = False
w.keys = {Qt.Key_W}
step_pure(1 / 60, 10)
on_lad = l.on_ladder
step_pure(1 / 60, 100)
w.keys = set()
chk("进入爬梯状态", on_lad, f"on_ladder={on_lad}")
chk("爬到台面 470", abs(l.y - 470.0) < 2.0, f"y={l.y:.1f}")
chk("爬完回到地面态", not l.on_ladder, f"on_ladder={l.on_ladder}")
chk("爬到顶不会自动弹起", abs(l.y - 470.0) < 2.0, f"y={l.y:.1f}")

# ⭐ 站在平台上不许抖：连续 60 帧的 y 极差必须 < 1px
l.x, l.y = 760.0, 470.0
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
chk("高速下落落在料理台而非穿透到地板", abs(l.y - 470.0) < 2.0, f"y={l.y:.1f}")

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
freeze_mw(1100.0, 1)                  # 它朝右，露娜在它【背后】90px
l.x = 1010.0
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
l.x, l.y = N.STASHES[0]["x"], N.STASHES[0]["y"]
w._try_break()
chk("敲碎容器拿到三文鱼", l.carrying == ["salmon"], f"carrying={l.carrying}")
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
chk("窝边累计 +1", w.total_loot == 1, f"total={w.total_loot}")
chk("loot_log 记的是实际偷到的", w.loot_log == ["salmon"], f"{w.loot_log}")

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
l.x, l.y = 700.0, N.FLOOR_Y
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
w.keys = set()
l.x, l.y = 700.0, 520.0
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

# ---- \u566a\u58f0\uff1a\u8ddd\u79bb\u4e0d\u540c\uff0calert \u6da8\u5e45\u5fc5\u987b\u4e0d\u540c ----
l.x, l.y = 690.0, 470.0
mw.x, mw.y = 700.0, N.FLOOR_Y          # \u8ddd\u79bb 10px\uff1a\u8d34\u7740\u8033\u6735\u6572
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
near_alert = mw.alert
chk("\u8d34\u8eab\u6572\u7bb1 = \u5ffd\u7565\u566a\u58f0\uff0calert \u4e0a\u5347 >0.5", near_alert > 0.5,
    f"alert={near_alert:.2f}  dist=10px")
chk("\u566a\u58f0\u4f1a\u8bb0\u4f4f\u58f0\u6e90\uff08\u4ed6\u8f6c\u5934\u770b\uff09", mw.hear_x is not None,
    f"hear_x={mw.hear_x}")

w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, 470.0
mw.x, mw.y = 1100.0, N.FLOOR_Y         # \u8ddd\u79bb 410px\uff1a\u542c\u5f97\u89c1\u4f46\u5f31\u5f88\u591a
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
far_alert = mw.alert
chk("\u8fdc\u5904\u6572\u7bb1 = \u5c31\u7b11\u58f0\u5c0f\uff0c但 alert \u4ecd\u4e0a\u5347", 0.02 < far_alert < 0.30,
    f"alert={far_alert:.2f}  dist=410px")
chk("\u8ddd\u79bb\u8d8a\u8fd1\u566a\u58f0\u8d8a\u5927", far_alert < near_alert,
    f"{far_alert:.2f} < {near_alert:.2f}")

# \u8d85\u51fa\u542c\u89c9\u534a\u5f84 = \u5b8c\u5168\u542c\u4e0d\u89c1
w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, 470.0
mw.x, mw.y = 1245.0, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
chk("\u8d85\u51fa\u542c\u89c9\u534a\u5f84\u5c31\u5b8c\u5168\u542c\u4e0d\u89c1", mw.alert < 0.001,
    f"alert={mw.alert:.3f}  dist=510px  \u534a\u5f84={N.MW_HEAR_R:.0f}")

# ---- \u7d2f\u79ef\u800c\u4e0d\u662f\u4e00\u6572\u6ee1\uff1a\u6572\u4e09\u4e0b\u624d\u5feb\u8fdb\u8ffd\u8e2a ----
w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, 470.0
mw.x, mw.y = 700.0, N.FLOOR_Y
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

# 远处敲\uff1a弱很多，要\u6572\u5f88\u591a\u6b21\u624d\u80fd\u5806\u6ee1
w.start_night(1)
l, mw = w.luna, w.mw
mw.x, mw.y = 1050.0, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
far_alerts = []
for k in range(len(w.room.stashes)):
    if not w.room.stashes[k]["broken"]:
        l.x, l.y = w.room.stashes[k]["x"], w.room.stashes[k]["y"]
        w._try_break()
    far_alerts.append(mw.alert)
    l.carrying = []
step_ai(1 / 60, 3)
chk("\u8fdc\u5904\u9010\u4e2a\u6572\u8d8a\u8d8a\u8fd1\u540e\u7d2f\u79ef\uff0c\u6570\u6b21\u540e\u88ab\u9501\u5b9a",
    mw.state == "chase",
    f"far_alerts={[round(a,2) for a in far_alerts]} state={mw.state}")

# ---- \u6f5c\u884c\uff1a\u6309 Shift \u53d8\u6162\u4e14\u6362\u6210 walk\u52a8\u4f5c ----
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
chk("\u6f5c\u884c\u7528 walk \u52a8\u4f5c\uff08\u4e0d\u662f human_run\uff09", l.act == "walk", f"act={l.act}")
w.keys = set()
step_pure(1 / 60, 30)
chk("\u677e\u5f00 Shift \u6062\u590d\u5e38\u901f", l.sneak is False)

w.keys = {Qt.Key_D}
step_pure(1 / 60, 60)
chk("\u5e38\u901f 1s \u79fb\u52a8 240~320px", 240 < l.x - (300.0 + vx_sneak) < 320,
    f"{l.x - (300.0 + vx_sneak):.0f}px")
chk("\u5e38\u901f\u65f6\u7528 human_run", l.act == "human_run", f"act={l.act}")
w.keys = set()

# ---- \u722c\u68af\u5b50 = \u5b8c\u5168\u5b89\u5168\uff08Lode Runner \u673a\u5236\uff09 ----
w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = 700.0, 520.0                  # \u722c\u68af\u4e2d\u6bb5
l.vx = l.vy = 0.0
l.on_ladder, l.on_ground = True, False
mw.x, mw.y = 700.0, N.FLOOR_Y
mw.alert, mw.state = 0.30, "chase"       # ⭐ 从 0.3 起步：从满值 1.0 起步永远看不出「缓涨」
mw.hear_x = None
a0 = mw.alert
step_ai(1 / 60, 60)
chk("梯子上不再绝对安全：他追得上来（Ronny 10-03 上强度）", l.on_ladder and l.y < 530.0,
    f"y={l.y:.0f} on_ladder={l.on_ladder}")
chk("梯子上警戒缓涨而非归零", mw.alert > a0, f"alert {a0:.2f} -> {mw.alert:.2f}")

# \u4e0b\u6765\u5c31\u4e0d\u5b89\u5168\u4e86
l.on_ladder = False
l.on_ground = True
l.y = N.FLOOR_Y
mw.alert = 0.0
step_ai(1 / 60, 40)
chk("\u4e0b\u6765\u540e\u6062\u590d\u88ab\u89c1\u8ff7\u7684\u53ef\u80fd", mw.alert > 0.2,
    f"alert={mw.alert:.2f}")

# ---- \u753b\u9762\u80fd\u753b\uff08\u5bb9\u5668/\u788e\u7247/\u6f5c\u884c\uff09 ----
w.start_night(1)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, 470.0
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

# \u8df3\u8dc3\uff1a\u8ddd\u79bb 150~330px \u4e14\u9732\u5a1c\u5728\u5730\u677f\u4e0a \u2192 \u4ed6\u4f1a\u8df3\u4e00\u4e0b\u538b\u8fc7\u6765
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

# \u722c\u68af\uff1a\u9732\u5a1c\u5728\u53f0\u9762\u4e0a \u2192 \u4ed6\u8d70\u5230\u68af\u5b50\u811a\u4e0b\u5e76\u722c\u4e0a\u6765
l.x, l.y = 700.0, 470.0
l.on_ground, l.vy = True, 0.0
mw.x, mw.y = 620.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground = "chase", 1.0, 0.0, True
for _ in range(200):
    mw._chase(1 / 60, l, w.room)
chk("\u722c\u68af\u80fd\u529b\uff1a\u4f1a\u8d70\u5230\u68af\u5b50\u5e76\u722c\u4e0a\u53f0\u9762", mw.y < N.FLOOR_Y - 100,
    f"mw.y={mw.y:.0f}  \u53f0\u9762 470")

# \u722c\u68af\u4e0d\u53ef\u80fd\u8d8a\u8fc7\u53f0\u9762\u5e95\uff08\u4e0d\u4f1a\u7a7f\u5899\uff09
mw.y = min(mw.y, 468.0)
chk("\u722c\u68af\u4e0d\u4f1a\u7a7f\u8fc7\u53f0\u9762\u9876", mw.y >= 468.0, f"mw.y={mw.y:.0f}")

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

# \u8df3\u8dc3\uff1a\u8ddd\u79bb 150~330px \u4e14\u9732\u5a1c\u5728\u5730\u677f\u4e0a \u2192 \u4ed6\u4f1a\u8df3\u4e00\u4e0b\u538b\u8fc7\u6765
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

# \u722c\u68af\uff1a\u9732\u5a1c\u5728\u53f0\u9762\u4e0a \u2192 \u4ed6\u8d70\u5230\u68af\u5b50\u811a\u4e0b\u5e76\u722c\u4e0a\u6765
l.x, l.y = 700.0, 470.0
l.on_ground, l.vy = True, 0.0
mw.x, mw.y = 620.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground = "chase", 1.0, 0.0, True
for _ in range(200):
    mw._chase(1 / 60, l, w.room)
chk("\u722c\u68af\u80fd\u529b\uff1a\u4f1a\u8d70\u5230\u68af\u5b50\u5e76\u722c\u4e0a\u53f0\u9762", mw.y < N.FLOOR_Y - 100,
    f"mw.y={mw.y:.0f}  \u53f0\u9762 470")

# \u722c\u68af\u4e0d\u53ef\u80fd\u8d8a\u8fc7\u53f0\u9762\u5e95\uff08\u4e0d\u4f1a\u7a7f\u5899\uff09
mw.y = min(mw.y, 468.0)
chk("\u722c\u68af\u4e0d\u4f1a\u7a7f\u8fc7\u53f0\u9762\u9876", mw.y >= 468.0, f"mw.y={mw.y:.0f}")
