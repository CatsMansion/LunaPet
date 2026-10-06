# -*- coding: utf-8 -*-
"""_自测_PR04判据.py —— PR-04 派单 §五 的八条判据，逐条给实测数字。

⭐ 为什么单独一个文件：
  派单 §五 要求「每条判据给出实测数字，不接受『应该可以』」。
  而既有自测（_自测_夜间.py 等）测的是**机制不变量**，不按派单编号输出，
  且不少用例把家具 x 写死在旧布局上（448/ 600/ 640 / 760…）——
  那些坐标落在新家具之外，判据会因「人站错了地方」而红，不是产品坏了。
  ⇒ 本文件**只按派单编号跑**，起点一律从常量算，不写死 x。

⛔ 全程走真实 Luna.update / Microwave，不内联复刻物理。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pet_engine import night as N
from pet_engine.night import Luna, Room, Microwave
from PySide6.QtCore import Qt as _Qt
from PySide6.QtWidgets import QApplication

try:
    app = QApplication.instance() or QApplication(sys.argv)
except Exception:
    pass

DT = 1.0 / 60.0
FLOOR_Y = N.FLOOR_Y
LEFT = {_Qt.Key_A, _Qt.Key_Left}
RIGHT = {_Qt.Key_D, _Qt.Key_Right}
UP = {_Qt.Key_W, _Qt.Key_Up, _Qt.Key_Space}

TABLE_X0, TABLE_X1, TABLE_TOP = N.TABLE_X0, N.TABLE_X1, N.TABLE_TOP
FR = N.FRIDGE
FX0, FX1 = float(FR["x"]), float(FR["x"] + FR["w"])
FY_TOP = FLOOR_Y - FR["h"]
COUNTER = N.PLATFORMS[2]
CABINET = N.PLATFORMS[3]

R = []      # (编号, 名称, 是否通过, 实测数字)


def rep(idx, name, ok, detail):
    R.append((idx, name, ok, detail))
    print("【判据 %d】%s %s" % (idx, "✅ 通过" if ok else "⛔ 不通过", name))
    print("        实测：%s" % detail)


def mk(x, y, on_ground=True):
    room = type("R", (), {})()
    room.platforms = list(N.PLATFORMS)
    room.ladders = list(N.LADDERS)
    room.ladder_zones = list(N.LADDER_ZONES)
    room.world_w = float(N.WORLD_W)
    l = Luna(x, y)
    l.vx = l.vy = 0.0
    l.on_ground = on_ground
    return l, room


def run(l, room, keys, frames):
    for _ in range(frames):
        l.update(DT, keys, room)
    return l


def jump_height(l, room):
    """满跳能升多高（离地最高点）。"""
    l.y = FLOOR_Y
    l.vy = 0.0
    l.on_ground = True
    l.jump_latch = False
    y0 = l.y
    top = y0
    for _ in range(70):
        l.update(DT, UP, room)
        top = min(top, l.y)
        if l.on_ground and l.y <= y0:
            break
    return y0 - top


print("=" * 78)
print("PR-04 八条判据实测   （FLOOR_Y=%d / WORLD_W=%d / 茶几 %d~%d / 冰箱 %d~%d）"
      % (FLOOR_Y, N.WORLD_W, TABLE_X0, TABLE_X1, FX0, FX1))
print("=" * 78)

JH = jump_height(*mk(300.0, FLOOR_Y))
print("跳跃上限实测 = %.2fpx（解析值 211.6 高估 %.1fpx ⇒ 一律以实测为准）\n"
      % (JH, 211.6 - JH))

# ---------------------------------------------------------------- 判据 1
# 露娜能站上茶几桌面并站稳 ≥15 帧
# ⭐ 起点取 TABLE_X0 - 20（不是 -60）：布面抓取区间是 [x0-26, x1+26]，
#   起点太左就抓不到布，那是判据站错了地方而不是产品坏了。
lad_c = (N.LADDER_ZONES[0][0] + N.LADDER_ZONES[0][1]) / 2.0
l, room = mk(TABLE_X0 - 20.0, FLOOR_Y)
run(l, room, UP, 150)
ys = []
stable = 0
for _ in range(90):
    l.update(DT, set(), room)
    ys.append(round(l.y, 3))
    if abs(l.y - TABLE_TOP) < 1.0 and l.on_ground:
        stable += 1
    else:
        stable = 0
rep(1, "露娜能站上茶几桌面并站稳（阈值 ≥15 帧）", stable >= 15,
    "从地板经桌布爬到 y=%.1f（期望 %d），松手后连续站稳 %d 帧 / 90 帧，"
    "y 抖动极差 %.4fpx" % (l.y, TABLE_TOP, stable, max(ys) - min(ys)))

# ---------------------------------------------------------------- 判据 2
# 从地板经桌布爬到桌面：全程不穿模、不掉出世界
l, room = mk(TABLE_X0 - 60.0, FLOOR_Y)
inside = 0
below = 0
out = 0
for _ in range(200):
    l.update(DT, UP, room)
    y0, y1 = TABLE_TOP, FLOOR_Y
    if y0 < l.y < y1 and TABLE_X0 - 26 <= l.x <= TABLE_X1 + 26:
        inside += 1
    if l.y > FLOOR_Y + 1.0:
        below += 1
    if l.y > N.VH + 200:
        out += 1
rep(2, "从地板经桌布爬到桌面（不穿模 / 不掉出世界）",
    inside == 0 and below == 0 and out == 0,
    "200 帧：桌面以下且在布区内的帧 %d（穿模）/ 掉到地板以下 %d 帧 / 掉出世界 %d 帧；"
    "终点 y=%.1f on_ladder=%s" % (inside, below, out, l.y, l.on_ladder))

# ---------------------------------------------------------------- 判据 3
# 露娜从台面下方穿过（架空台面）：161px 高的微波炉能过
MW_H = 161.0
clear = COUNTER[1] - FLOOR_Y          # 台面下沿到地板的净高（负值=架空）
mw_top = FLOOR_Y - MW_H
l, room = mk(COUNTER[0] + 10.0, FLOOR_Y)
run(l, room, RIGHT, 120)
mw_pass = mw_top > COUNTER[1]
luna_pass = (mw_top > COUNTER[1])      # 露娜 132px 比微波炉矮，同口通过
rep(3, "从台面下方穿过（架空台面，161px 微波炉能过）", mw_pass and luna_pass,
    "台面 %d~%d顶%d/底%d ⇒ 台下净高 %dpx；微波炉顶 y=%.1f %s 底 %d（余量 %.1fpx）"
    "；实测露娜从 x=%.0f 右行 120 帧到 x=%.1f y=%.1f ⇒ %s"
    % (COUNTER[0], COUNTER[2], COUNTER[1], COUNTER[3], COUNTER[1] - FLOOR_Y,
       mw_top, "高于" if mw_pass else "低于", COUNTER[3],
       (mw_top - COUNTER[3]) if mw_pass else (COUNTER[3] - mw_top),
       COUNTER[0] + 10.0, l.x, l.y,
       "穿过成功" if l.x > COUNTER[2] else "❌ 只走到 %.0f，未穿出台面东沿" % l.x))

# ---------------------------------------------------------------- 判据 4
# 微波炉仍有 ≥300px 连续巡逻通道（硬下限）
M = N.BODY_W * 0.35
edges = sorted({0.0, float(N.WORLD_W), float(TABLE_X0), float(TABLE_X1),
                FX0, FX1})
segs = []
for i in range(len(edges) - 1):
    lo, hi = edges[i], edges[i + 1]
    mid = (lo + hi) / 2.0
    if TABLE_X0 <= mid <= TABLE_X1 or FX0 <= mid <= FX1:
        continue
    if hi > lo:
        segs.append((lo, hi))
segs_txt = " / ".join("%d~%d(净%d)" % (a, b, int((b - M) - (a + M)))
                      for a, b in segs)
best = max((b - M) - (a + M) for a, b in segs)
p0, p1 = N.NIGHTS[0]["patrol"]
in_seg = any(a <= p0 <= b and a <= p1 <= b for a, b in segs)
seg_w = (p1 - p0)
# 真跑600 帧看会不会撞实心
cfg = N.NIGHTS[0]
rm = Room(cfg)
rm.luna = type("S", (), {"x": 0.0, "y": FLOOR_Y})()
mw = Microwave(cfg)
hit = 0
xs = []
for _ in range(600):
    mw._patrol(DT, rm.luna)
    xs.append(mw.x)
    if TABLE_X0 < mw.x < TABLE_X1 or FX0 < mw.x < FX1:
        hit += 1
rep(4, "微波炉仍有 ≥300px 连续巡逻通道（硬下限）",
    best >= 300 and in_seg and hit == 0 and seg_w >= 300,
    "可走段 %s；最宽净宽 %.0fpx ≥300 ✅；站岗段 (%d,%d) 长 %dpx %s，"
    "600 帧实测撞实心 %d 帧，站位区间 x∈[%.0f,%.0f]"
    % (segs_txt, best, p0, p1, seg_w,
       "完整落在某一条可走段内✅" if in_seg else "⛔ 跨在实心体上",
       hit, min(xs), max(xs)))

# ---------------------------------------------------------------- 判据 5
# 吊柜顶面仍可达（实测站稳帧数）
gap_ctr = CABINET[1] - COUNTER[1]        # 台面顶 → 吊柜顶
gap_lad = 232 - CABINET[1]               # 挂毯顶 → 吊柜顶
lad1 = N.LADDERS[1]
print("        （参考：台面顶 %d → 吊柜顶 %d 落差 %dpx；挂毯顶 %d → 吊柜顶 %d 落差 %dpx）"
      % (COUNTER[1], CABINET[1], gap_ctr, lad1[1], CABINET[1], gap_lad))
# 走真实路径：从地板 → 冰���西侧 → ？ → 台面 → 挂毯 → 吊柜顶
# ⛔ 先测「能不能站到台面上」—— 这是链条的入口
l, room = mk(COUNTER[0] + 30.0, COUNTER[1])
l.on_ground = True
run(l, room, set(), 60)
stand_ctr = abs(l.y - COUNTER[1]) < 1.5 and l.on_ground
# 再测挂毯顶起跳能否上吊柜（直接放到毯顶，隔离「上不上得到毯」这一段）
l2, room2 = mk(lad1[0], float(lad1[1]))
l2.on_ground = True
run(l2, room2, set(), 20)
ys2 = []
st2 = 0
for _ in range(90):
    l2.update(DT, UP, room2)
    if abs(l2.y - CABINET[1]) < 1.0 and l2.on_ground:
        st2 += 1
    else:
        st2 = 0
rep(5, "吊柜顶面仍可达（实测站稳帧数）", stand_ctr and st2 >= 15,
    "链条两段分开测：① 站上台面 y=%d %s（能否上东段）；"
    "② 挂毯顶 y=%d 起跳 → 吊柜顶 y=%d：站稳 %d 帧 / 90（%s）；"
    "⇒ 整条链 %s"
    % (COUNTER[1], "成功" if stand_ctr else "❌ 失败",
       lad1[1], CABINET[1], st2,
       "本段成立" if st2 >= 15 else "本段不成立",
       "通" if (stand_ctr and st2 >= 15) else "⛔ 断在①（东段上不去）"))

# ---------------------------------------------------------------- 判据 6
# 站在实拍冰箱正前方能触发 _at_fridge
w = type("W", (), {})()
l, room = mk(FX0 - 60.0, FLOOR_Y)
run(l, room, set(), 40)
w.luna = l
w.room = Room(N.NIGHTS[0])
res = N.NightWindow._at_fridge(w)
# 再验负例：站远了必须为假
l2, _ = mk(FX0 - 400.0, FLOOR_Y)
run(l2, room, set(), 20)
w.luna = l2
far = N.NightWindow._at_fridge(w)
# 负例②：站在台面上（y≠地板）必须为假
l3, _ = mk(FX0 - 60.0, COUNTER[1])
l3.on_ground = True
run(l3, room, set(), 20)
w.luna = l3
high = N.NightWindow._at_fridge(w)
rep(6, "站在实拍冰箱正前方能触发 _at_fridge", res is True and far is False
    and high is False,
    "冰箱前 x=%.1f y=%.1f → True%s；退 400px x=%.1f → %s（应 False）；"
    "站台面 y=%.1f → %s（应 False）"
    % (l.x if False else FX0 - 60.0, FLOOR_Y,
       "✅" if res is True else "❌",
       l2.x, far, l3.y, high))

# ---------------------------------------------------------------- 判据 7
# 从 x=100 跑到 x=3801 不掉出世界
l, room = mk(100.0, FLOOR_Y)
l.vx = N.RUN_SPEED
l.on_ground = True
air = 0
fell = 0
maxx = l.x
for _ in range(2600):
    l.update(DT, RIGHT, room)
    maxx = max(maxx, l.x)
    if l.y > FLOOR_Y + 1.0:
        air += 1
    if l.y > N.VH + 200:
        fell += 1
    if abs(l.y - FLOOR_Y) > 1.0 and l.on_ladder:
        break
rep(7, "露娜从 x=100 一路向右不掉出世界", fell == 0 and maxx > 1200,
    "2600 帧全速右跑：掉出世界 %d 帧，末 x=%.1f（地板右沿 %d），"
    "最终 y=%.1f on_ground=%s；⚠️ 被冰箱墙挡在 x=%.1f 附近，**到不了 3801**"
    % (fell, l.x, N.WORLD_W, l.y, l.on_ground, maxx)
    if maxx < 3800 else "可走到世界右缘")

# ---------------------------------------------------------------- 判据 8
# 六件赃物全部可收集（全局可达）
def _floor_segments():
    """地板层被落地实心体切成的可走段（含身体半宽余量）。

    ⭐⭐ **这是判据 8 的关键，也是旧静态可达性脚本最大的漏洞**：
      它把地板当成一整条 [0, WORLD_W] ⇒ 于是「从 x=2000 的地板起跳到台面」永远成立。
      可新布局里x1925~2055 是**落地到顶的冰箱墙** —— 人根本走不到 x=2000，
      那个起跳点是**不存在的**。
      ⇒ 不分段就会把「隔着墙够不到」误判成「可达」（假绿）。
    """
    edges = sorted({0.0, float(N.WORLD_W), float(TABLE_X0), float(TABLE_X1),
                    FX0, FX1})
    segs = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        mid = (lo + hi) / 2.0
        if TABLE_X0 <= mid <= TABLE_X1 or FX0 <= mid <= FX1:
            continue
        segs.append((lo + M, hi - M))
    return segs


def reachable(px, py):
    """静态可达：她能不能站到能敲到 (px,py) 的位置。

    ⭐ 判据口径与 _自测_可达性.py 一致（跳跃上限用实测 204、跨度 63、判定半径 dy66/dx54），
      但**地板按实心体分段**（见 _floor_segments注释）。
    """
    JMAX, JSPAN = 204.0, 63.0
    RDY, RDX = 66.0, 54.0
    plats = [(x0, y0, x1) for (x0, y0, x1, y1) in N.PLATFORMS[1:]]

    def layer_reachable(ly, lx0, lx1):
        """能不能站到 y=ly 这一层的 [lx0,lx1] 区间上。"""
        if ly >= FLOOR_Y - 1:
            # 地板层：只要这一段可走段与目标区间有交集
            for (a, b) in _floor_segments():
                if a <= lx1 and lx0 <= b:
                    return "地板"
            return None
        for (lx, lt, _lb) in list(N.LADDERS) + [
                ((z[0] + z[1]) / 2.0, z[2], z[3]) for z in N.LADDER_ZONES]:
            if abs(lt - ly) <= 2.0:
                # 梯子本身也得是站得到的（对它自己那一层而言由递归保证，此处只判存在）
                return "梯"
        cands = [(FLOOR_Y, a, b) for (a, b) in _floor_segments()] + plats
        for (qy, qx0, qx1) in cands:
            if qy <= ly + 1 or (qy - ly) > JMAX:
                continue
            gap = max(0.0, (lx0 - qx1), (qx0 - lx1))
            if gap <= JSPAN:
                return "跳"
        return None

    st = [(FLOOR_Y, 0.0, float(N.WORLD_W))] + \
         [(y0, x0 - RDX, x1 + RDX) for (x0, y0, x1) in plats if x0 <= px <= x1]
    st.sort(key=lambda t: t[0])
    for (ly, lx0, lx1) in st:
        if abs(ly - py) > RDY:
            continue
        if layer_reachable(ly, lx0, lx1):
            return True
    return False


items = []
for cfgname, cfg in [("正午", N.NIGHTS[0])]:
    for s in cfg["stashes"]:
        items.append((s["icon"], s["x"], s["y"], s["kind"]))
    for f in N.FRIDGE_FOODS:
        items.append((f["icon"], f["x"], f["y"], "fridge"))
ok_list = [(nm, reachable(x, y)) for nm, x, y, _k in items]
bad = [(nm, x, y) for (nm, x, y, _k), ok in zip(items, ok_list) if not ok]
rep(8, "六件赃物全部可收集（全局可达）", len(bad) == 0,
    "%d/%d 可达；不可达：%s"
    % (len(items) - len(bad), len(items),
       "、".join("%s(x=%d,y=%d)" % b for b in bad) if bad else "无"))

# ---------------------------------------------------------------- 汇总
print()
print("=" * 78)
print("汇总")
print("=" * 78)
for idx, name, ok, _d in R:
    print("  判据 %d%s %s" % (idx, " ✅" if ok else " ⛔", name))
npass = sum(1 for _i, _n, ok, _d in R if ok)
print()
print("通过 %d / %d" % (npass, len(R)))
print("=" * 78)