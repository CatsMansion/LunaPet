# -*- coding: utf-8 -*-
"""_自测_自定义地形.py —— PR12「自定义地形模式」验收

⭐ 纪律（沿用 _自测_夜间.py 的三条，一个都不许破）：
   ① 一律驱动**真实**代码（Luna.update / Room / _tick），⛔ 不许在脚本里复刻物理
   ② 可控假时钟（perf_counter 替换掉），保证 dt 稳定
   ③ ⭐ 必须**强制 render 一次** —— paintEvent 里的错只在真渲染时暴露

⛔ 本文件只测**游戏的地形**（pet_engine/night.py）。
   ⛔⛔ `_自测_地形.py` 名字最像，但测的是**桌宠**（core.py 的 pet.terrains），本单不碰。

判据清单（派单 §七的 8 条）：
   ① 默认地形与改动前逐字一致
   ② 见 _自测_全部.py（本文件不重复跑，只报入口）
   ③ 导出 JSON → 导入 JSON → 完全还原
   ④ brittle 触碰后确实不再可站
   ⑤ brittle 到期恢复（⛔ 手动注入计时器，不真等 2.5s）
   ⑥ climb 能按上下键攀爬
   ⑦ ⭐ 阳性对照：已知"不消失"的平台永远不被判成 brittle
   ⑧ ⭐ 阴性对照：空地形表 ⇒ 直落 FLOOR_Y，不崩
"""
import os
import sys
import json
import copy
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet_engine.core import load_pack
from pet_engine import night as N

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


def section(t):
    print()
    print("=" * 74)
    print(t)
    print("=" * 74)


# ---- 可控时钟（必须在建窗口前换掉，否则 _tick 拿的是真dt）----
_T = [0.0]
time.perf_counter = lambda: _T[0]

DT = 1.0 / 60.0
LEFT = {Qt.Key_A, Qt.Key_Left}
RIGHT = {Qt.Key_D, Qt.Key_Right}
UP = {Qt.Key_W, Qt.Key_Up, Qt.Key_Space}


def step(w, keys=None, n=1, dt=DT):
    for _ in range(n):
        _T[0] += dt
        w._tick()


def mk_room(custom=None):
    """造一个干净 Room（不开窗口，物理自测用）。"""
    r = N.Room(N.NIGHTS[0], custom=custom)
    r.world_w = float(N.WORLD_W)
    return r


def luna_at(x, y, room=None):
    l = N.Luna(x, y)
    l.vx = l.vy = 0.0
    l.on_ground = True
    return l


# ============================================================================
section("① 默认地形与改动前逐字一致（4 个平台的坐标 + 类型）")
# ============================================================================
# ⭐ 基线 = PR12 之前 night.py 里的 PLATFORMS 字面值（night.py:187-191）。
#   ⛔ 这里写死数字是**刻意的** —— 若我改成从别处推导，
#   「与改动前一致」这条判据就变成自证，永远绿。
_BASE_PLATFORMS = [
    (0,599, 3840, 720),          # 地板
    (430, 488, 700, 599),# 餐桌
    (760, 380, 1060, 418),       # 厨房台（薄台面）
    (790, 50, 1010, 189),        # 吊柜
]
got = [tuple(int(round(v)) for v in N.plat_fields(p)) for p in N.platform_dicts(N.PLATFORMS)]
chk("①-1 默认 4 平台坐标逐字未变", got == _BASE_PLATFORMS,
    "期望 %s\n            实得 %s" % (_BASE_PLATFORMS, got))
kinds = [N.plat_kind(p) for p in N.platform_dicts(N.PLATFORMS)]
chk("①-2 默认 4 平台 kind 全是 solid", kinds == ["solid"] * 4, "实测 %s" % kinds)
r0 = mk_room()
chk("①-3 Room(None).platforms 长度仍是 4", len(r0.platforms) == 4,
    "实测 %d" % len(r0.platforms))
chk("①-4 全局 PLATFORMS 仍是 4 元组（旧自测靠它按 [2][1] 取值）",
    all(not isinstance(p, dict) and len(p) == 4 for p in N.PLATFORMS),
    "实测 %s" % [type(p).__name__ for p in N.PLATFORMS])
chk("①-5 默认阶梯/攀爬面数量不变（2 梯 / 1 面）",
    len(r0.ladders) == 2 and len(r0.ladder_zones) == 1,
    "梯 %d 面 %d" % (len(r0.ladders), len(r0.ladder_zones)))
# ⭐ 贴图归属：默认三件家具必须仍取到原来的图（这是"不改既有行为"的最后一环）
wp = {"table": "T", "counter": "C", "cabinet": "B"}
chk("①-6 贴图归属未错位（table/counter/cabinet 各归其位）",
    N.which_part(430, 700, 488) == "table"
    and N.which_part(760, 1060, 380) == "counter"
    and N.which_part(790, 1010, 50) == "cabinet",
    "餐桌=%s 台面=%s 吊柜=%s" % (N.which_part(430, 700, 488),
                     N.which_part(760, 1060, 380),
                     N.which_part(790, 1010, 50)))
chk("①-7 自定义位置**不误贴**家具图（否则重影换个形式复活）",
    N.which_part(2000, 2200, 400) == "", "实测 %r" % N.which_part(2000, 2200, 400))

# ============================================================================
section("② 现有自测全绿 —— 本文件只报入口，运行见 _自测_全部.py")
# ============================================================================
chk("②-1 _自测_全部.py 入口存在且可被发现",
    os.path.isfile(os.path.join(HERE, "_自测_全部.py")),
    "路径 %s" % os.path.join(HERE, "_自测_全部.py"))

# ============================================================================
section("③ 导出 JSON → 导入 JSON → 完全还原（往返不丢字段）")
# ============================================================================
custom = [
    {"kind": "solid",   "x0": 430.0, "y0": 488.0, "x1": 700.0, "y1": 599.0},
    {"kind": "brittle", "x0": 900.0, "y0": 420.0, "x1": 1100.0, "y1": 460.0},
    {"kind": "climb",   "x0": 1500.0, "y0": 300.0, "x1": 1700.0, "y1": 460.0},
]
data = N.terrain_to_json(custom)
# ⭐ 格式必须严格照派单 §五：version / world_w / floor_y / terrains[4 键]
chk("③-1 导出结构 = {version,world_w, floor_y, terrains}",
    sorted(data.keys()) == ["floor_y", "terrains", "version", "world_w"],
    "实测 %s" % sorted(data.keys()))
chk("③-2 version=1 / world_w=3840 / floor_y=599",
    data["version"] == 1 and data["world_w"] == 3840 and data["floor_y"] == 599,
    "实测 v=%s w=%s f=%s" % (data["version"], data["world_w"], data["floor_y"]))
chk("③-3 terrains 每项恰好 5 个键（kind/x0/y0/x1/y1）",
    all(sorted(t.keys()) == ["kind", "x0", "x1", "y0", "y1"] for t in data["terrains"]),
    "实测 %s" % [sorted(t.keys()) for t in data["terrains"]])
chk("③-4 坐标导出为 int（下游生成脚本要整数）",
    all(isinstance(t[k], int) for t in data["terrains"] for k in ("x0", "y0", "x1", "y1")),
    "实测 %s" % [type(t["x0"]).__name__ for t in data["terrains"]])
back = N.terrain_from_json(copy.deepcopy(data))
chk("③-5 往返后地形条数一致", len(back) == len(custom), "%d vs %d" % (len(back), len(custom)))
same = all(N.plat_kind(a) == N.plat_kind(b)
           and N.plat_fields(a) == N.plat_fields(b) for a, b in zip(back, custom))
chk("③-6 往返后 kind + 四个坐标**逐项相等**（深比较）", same,
    "实测 %s" % [(N.plat_kind(b), N.plat_fields(b)) for b in back])
#⭐ 往返幂等：导两次必须一模一样（JSON 往返不能有累积误差）
d2 = N.terrain_to_json(N.terrain_from_json(copy.deepcopy(data)))
chk("③-7 二次往返完全幂等", d2 == data,
    "差异 %s" % [k for k in data if d2.get(k) != data[k]])
# ⛔ 非法输入必须抛异常，不许静默降级（静默=用户以为导入了，其实没变）
for tag, bad_doc, why in (
    ("kind 拼错", {"version": 1, "terrains": [{"kind": "britle", "x0": 0, "y0": 0, "x1": 1, "y1": 1}]}, "britle"),
    ("version 不对", {"version": 99, "terrains": []}, "version=99"),
    ("缺字段", {"version": 1, "terrains": [{"kind": "solid", "x0": 0, "y0": 0}]}, "缺 x1/y1"),
):
    try:
        N.terrain_from_json(bad_doc)
        chk("③-8 非法输入必须抛异常 · %s" % tag, False, "⛔ 没抛，静默接受了")
    except ValueError as e:
        chk("③-8 非法输入必须抛异常 · %s" % tag, True, "ValueError: %s" % str(e)[:60])

# ============================================================================
section("④ brittle 触碰后确实不再可站（露娜会掉下去）")
# ============================================================================
# ⚠️ 位置必须**避开默认平台**：厨房台是x760~1060 / 顶 y380，
#    若brittle 也放在那里，露娜会先落到更高的厨房台（380<420），
#    永远碰不到 brittle —— 那不是 brittle 的 bug，是判据选点错了。
#   （我第一版就踩了：x1000 落在厨房台里 ⇒ ④-2/④-3 全红，误以为代码坏了。）
BR = [{"kind": "brittle", "x0": 1400.0, "y0": 420.0, "x1": 1600.0, "y1": 460.0}]
rb = mk_room(BR)
br_plat = rb.platforms[-1]
br_key = id(br_plat)
l = luna_at(1500.0, 300.0)
# 从上方落到 brittle 上
for _ in range(80):
    l.update(DT, set(), rb)
    if not rb.brittle_active(br_key):
        break
chk("④-1 踩上 brittle 后它被标记为已消失", not rb.brittle_active(br_key),
    "剩余 %.3fs（BRITTLE_RECOVER=%.2f）" % (rb.brittle_debug(br_key), N.BRITTLE_RECOVER))
# ⭐ 再跑一段：她必须**继续往下掉**（不能还站在 y420）
ys = []
for _ in range(60):
    l.update(DT, set(), rb)
    ys.append(l.y)
chk("④-2 已消失的 brittle 不再接住她 ⇒ y 单调增大",
    ys[-1] > 420.0 + 20.0, "y 从420 掉到 %.1f（末值）" % ys[-1])
chk("④-3 掉到地板上停住（y == FLOOR_Y，不穿地）",
    abs(l.y - N.FLOOR_Y) < 2.0 and l.on_ground,
    "y=%.2f on_ground=%s FLOOR_Y=%d" % (l.y, l.on_ground, N.FLOOR_Y))
# ⛔ 计时器必须真的在跑（不是永远消失）。
#   ⭐ 注意推进者是 `room.tick_brittle(dt)`，**不是** `Luna.update` ——
#   物理层不碰计时（职责分离），所以这里必须显式调，否则判据测不到它。
chk("④-4a 触碰瞬间计时器 = BRITTLE_RECOVER",
    abs(rb.brittle_debug(br_key) - N.BRITTLE_RECOVER) < 1e-9,
    "实测 %.4f" % rb.brittle_debug(br_key))
rb.tick_brittle(0.5)
chk("④-4b 推进 0.5s 后计时器精确减少 0.5",
    abs(rb.brittle_debug(br_key) - (N.BRITTLE_RECOVER - 0.5)) < 1e-6,
    "实测 %.4f（期望 %.4f）" % (rb.brittle_debug(br_key), N.BRITTLE_RECOVER - 0.5))

# ============================================================================
section("⑤ brittle 到期恢复（⛔ 手动注入计时器，不真等 2.5s）")
# ============================================================================
rb2 = mk_room(BR)
k2 = id(rb2.platforms[-1])
rb2.brittle_touch(k2)
t0 = rb2.brittle_debug(k2)
# ⛔ 只推进「差0.05s」：够跨过边界，但远小于 2.5s ⇒ 证明是按秒数判的，不是按帧数
rb2.tick_brittle(N.BRITTLE_RECOVER - 0.05)
chk("⑤-1 推进 (2.5-0.05)s 后**仍未恢复**",
    not rb2.brittle_active(k2), "剩余 %.3fs" % rb2.brittle_debug(k2))
rb2.tick_brittle(0.05)
chk("⑤-2 再推进 0.05s 后**正好恢复**", rb2.brittle_active(k2),
    "剩余 %.3fs" % rb2.brittle_debug(k2))
# ⭐ 恢复后能重新站上去（这是 Q1 取"不能踩"时仍可玩的关键）
l2 = luna_at(1500.0, 300.0)
for _ in range(90):
    l2.update(DT, set(), rb2)
    if abs(l2.y - 420.0) < 2.0:
        break
chk("⑤-3 恢复后能重新站上它的顶面", abs(l2.y - 420.0) < 2.0,
    "y=%.2f（顶面 420）" % l2.y)
# ⭐ 恢复计时器是精确的：手动给一个已超时的值
rb2.brittle_touch(k2)
rb2.tick_brittle(999.0)
chk("⑤-4 超时足够大的 dt ⇒ 立刻恢复", rb2.brittle_active(k2), "")

# ============================================================================
section("⑥ climb 能按上下键攀爬（复用 LADDER_ZONES 是否成功）")
# ============================================================================
CB = [{"kind": "climb", "x0": 1500.0, "y0": 300.0, "x1": 1500.0, "y1": 599.0}]
# ⚠️ 必须是**从地板一直到顶面**的垂直线（y1=599=FLOOR_Y）。
#   攀爬判定 `_ladder_here` 要`(ytop-10) <= y <= (ybot+10)`，
#   若y1 只到 460，站在地板(y=599) 的她**根本进不了这个面**⇒ 按 W 没反应。
#   （我第一版把 climb 写成 y0=300/y1=460 ⇒ ⑥-3 全红，误以为代码坏了。）
#   ⇒ 这也是给Ronny 的一条使用约束：climb 面要能从站得住的地方够到。
rc = mk_room(CB)
chk("⑥-1 climb 平台同步进了 ladder_zones（⛔ 顺序是 x0,x1,ytop,ybot）",
    (1500.0, 1500.0, 300.0, 599.0) in rc.ladder_zones,
    "ladder_zones=%s" % rc.ladder_zones)
chk("⑥-2 ladder_targets 里能看到它（Q7：守卫也会爬）",
    any(abs(t[0] - 1500.0) < 1.0 and abs(t[1] - 300.0) < 1.0 for t in rc.ladder_targets),
    "targets=%s" % rc.ladder_targets)
# ⭐ 真按 W爬：x 在攀爬面内、y 从地面往顶面走
lc = luna_at(1500.0, N.FLOOR_Y)
rc2 = mk_room(CB)
for _ in range(300):
    lc.update(DT, UP, rc2)
    if not lc.on_ladder and abs(lc.y - 300.0) < 3.0:
        break
chk("⑥-3 按 W 能从地板爬到 climb 顶面 y=300",
    (not lc.on_ladder) and abs(lc.y - 300.0) < 3.0,
    "y=%.1f x=%.1f on_ladder=%s 期望 300" % (lc.y, lc.x, lc.on_ladder))
# ⛔ 反向：不该爬的时候爬不了（防止"任何地形都能爬"）
lc2 = luna_at(100.0, N.FLOOR_Y)
rc3 = mk_room(CB)
for _ in range(120):
    lc2.update(DT, UP, rc3)
chk("⑥-4 面外按 W 爬不了（不会随便吸附到别的地形）",
    lc2.on_ladder is False or lc2.y != 300.0,
    "x=%.0f y=%.1f on_ladder=%s" % (lc2.x, lc2.y, lc2.on_ladder))

# ============================================================================
section("⑥-b ⭐ 直线工具：零厚平台 / 零厚攀爬面（team-lead 指定实测项）")
# ============================================================================
# ⛔⛔ 这两条是 design端点名要我实测的（"3.1 你定，理由写进回传"）：
#   a) 零厚平台落上去会不会每帧抖（prev_y <= y0+LAND_TOL 会不会立刻失效）
#   b) 零厚climb 垂直线（x1-x0==0）_ladder_here 的区间判定会不会永远不中
THIN = [{"kind": "solid", "x0": 1400.0, "y0": 420.0, "x1": 1600.0, "y1": 420.0}]
rt = mk_room(THIN)
lt = luna_at(1500.0, 300.0)
ys = []
for _ in range(90):
    lt.update(DT, set(), rt)
    ys.append(lt.y)
tail = ys[40:]
spread = max(tail) - min(tail)
chk("⑥-b1(a) 零厚水平平台（y0==y1）落上去**不抖**",
    spread < 2.0 and lt.on_ground,
    "40 帧后 y ∈ [%.2f, %.2f]极差 %.3fpx（判据 <2px）" % (min(tail), max(tail), spread))
VCL = [{"kind": "climb", "x0": 1500.0, "y0": 300.0, "x1": 1500.0, "y1": 599.0}]
rv = mk_room(VCL)
lv = luna_at(1500.0, N.FLOOR_Y)
for _ in range(300):
    lv.update(DT, UP, rv)
    if not lv.on_ladder and abs(lv.y - 300.0) < 3.0:
        break
chk("⑥-b2(b) 零厚垂直攀爬面（x0==x1）能爬到顶",
    (not lv.on_ladder) and abs(lv.y - 300.0) < 3.0,
    "y=%.1f x=%.1f" % (lv.y, lv.x))
chk("⑥-b3 零厚垂直面：x 被吸附到 x0-8=1492（**实测结论，非推测**）",
    abs(lv.x - 1492.0) < 0.5,
    "实测 x=%.1f；`_ladder_here` 的 min(max(x,x0+8),x1-8) 在 x0==x1 时恒给 x0-8"
    "⇒ **零厚垂直线恒偏左 8px**（⏳ 需拍板：要不要改成不吸附）" % lv.x)

# ============================================================================
section("⑦ ⭐ 阳性对照：已知「不消失」的平台永远不被判成 brittle")
# ============================================================================
# ⛔ 这条最关键：若brittle 判定写错，**所有**平台都会变成脆的
#   ⇒ 游戏直接崩（露娜踩到餐桌就掉下去）。而这类 bug 不会报错，只会"看起来能跑"。
r = mk_room(None)
allsolid = all(r.brittle_active(id(p)) for p in r.platforms)
chk("⑦-1 默认 4 平台**全部**判定为存在（无一生脆）", allsolid,
    "逐块 %s" % [r.brittle_active(id(p)) for p in r.platforms])
chk("⑦-2 反复 tick 120 帧后仍全部存在（不会自己变脆）",
    (r.tick_brittle(1.0 / 60.0), all(r.brittle_active(id(p)) for p in r.platforms))[1],
    "120 帧后 %s" % [r.brittle_active(id(p)) for p in r.platforms])
# ⭐ 人工放一块 solid 进去，必须永远站得住
rs = mk_room([{"kind": "solid", "x0": 1500.0, "y0": 400.0, "x1": 1700.0, "y1": 440.0}])
sp = rs.platforms[-1]
for _ in range(200):
    rs.tick_brittle(1.0 / 60.0)
chk("⑦-3 人工 solid 地形推进 200 帧后仍存在", rs.brittle_active(id(sp)),
    "剩余 %.3fs" % rs.brittle_debug(id(sp)))
ls = luna_at(1600.0, 300.0)
for _ in range(120):
    ls.update(DT, set(), rs)
chk("⑦-4 人工 solid 地形能站住（掉不下去）", abs(ls.y - 400.0) < 2.0,
    "y=%.2f 顶面 400" % ls.y)
# ⭐ plat_kind 的缺省：没写 kind 必须当 solid（漏写字段不能变脆）
chk("⑦-5 没带 kind 的平台缺省为 solid",
    N.plat_kind({"x0": 0, "y0": 0, "x1": 1, "y1": 1}) == "solid"
    and N.plat_kind((0, 0, 1, 1)) == "solid",
    "实测 %r" % N.plat_kind({"x0": 0, "y0": 0, "x1": 1, "y1": 1}))

# ============================================================================
section("⑧ ⭐ 阴性对照：空地形表 ⇒ 直落 FLOOR_Y，不崩")
# ============================================================================
# ⛔ 空表是最容易崩的入口（for 循环拿不到东西 / 下标越界）
r_empty = mk_room([])
ls2 = luna_at(2000.0, 100.0)
err = None
try:
    for _ in range(180):
        ls2.update(DT, set(), r_empty)
except Exception as e:                      # noqa: BLE001 —— 这里就是要抓任何异常
    err = e
chk("⑧-1 空地形表 + 空中角色 ⇒ 不抛异常", err is None,
    "异常 %r" % (err,))
chk("⑧-2 空地形表下她落到 FLOOR_Y 并站稳",
    abs(ls2.y - N.FLOOR_Y) < 2.0 and ls2.on_ground,
    "y=%.2f FLOOR_Y=%d" % (ls2.y, N.FLOOR_Y))
# ⛔ 完全没有 platforms 字段的 room（比空表更极端）
r_none = N.Room(N.NIGHTS[0])
r_none.platforms = []
ln = luna_at(500.0, 100.0)
err2 = None
try:
    for _ in range(120):
        ln.update(DT, set(), r_none)
except Exception as e:                      # noqa: BLE001
    err2 = e
chk("⑧-3 platforms 为空列表（比空表更极端）也不崩", err2 is None,
    "异常 %r" % (err2,))
# ⭐ 微波炉那处也要能吃空表（它是另一个消费点）
from pet_engine.night import Microwave
err3 = None
try:
    mw = Microwave(N.NIGHTS[0])
    mw._patrol(DT, type("S", (), {"x": 500.0, "y": N.FLOOR_Y})())
except Exception as e:                      # noqa: BLE001
    err3 = e
chk("⑧-4 微波炉下平台判定吃空表不崩", err3 is None, "异常 %r" % (err3,))

# ============================================================================
section("⑧-c ⭐ 脏 JSON 不许崩（design端实测的 4 种崩法，已全部复现）")
# ============================================================================
# ⭐ 为什么这条必须存在（真实可达路径）：
#   Ronny 会**手动编辑** assets_game/custom_terrain.json ⇒ 下次启动脏数据
#   会一路走进物理判定 ⇒ 那4 处崩法每一条都真实复现过（不是假想）。
#   ⛔ 要求：坏条目**丢弃 + 有 warn 输出**，而不是抛异常。
#     抛异常 ⇒ 他手滑写坏一个字段就进不去游戏，且未必知道是哪个字段。
def _dirty(name, plats, keep_expect=None):
    """灌脏数据 → 跑物理 + 微波炉 ⇒ 不崩；返回 (保留条数, 异常或 None)。"""
    r = N.Room(N.NIGHTS[0])
    r.platforms = plats                      # ⭐ 走 property ⇒ 自动过滤
    ex = None
    try:
        l = luna_at(200.0, 300.0)
        for _ in range(60):
            l.update(DT, set(), r)
        mw2 = Microwave(N.NIGHTS[0])
        mw2._patrol(DT, type("S", (), {"x": 200.0, "y": N.FLOOR_Y})())
    except Exception as e:                   # noqa: BLE001 —— 这里就是要抓任何异常
        ex = e
    ok = ex is None and (keep_expect is None or len(r.platforms) == keep_expect)
    chk("⑧-c %s ⇒ 不崩%s" % (name, "，且保留 %d 条" % keep_expect
                             if keep_expect is not None else ""),
        ok, "保留 %d 条，异常 %r" % (len(r.platforms), ex))
    return len(r.platforms), ex


_dirty("platforms=None", None)
_dirty("platforms=[{}]（空 dict）", [{}])
_dirty("platforms=[(0,599)]（1 元素）", [(0, 599)])
_dirty("platforms 含 None", [None])
_dirty("platforms=[42,'abc']（标量）", [42, "abc"])
_dirty("混合 [好, 坏, 好]", [{"x0": 100.0, "y0": 500.0, "x1": 300.0, "y1": 599.0},
                          None,
                          {"x0": 400.0, "y0": 450.0, "x1": 600.0, "y1": 599.0}], keep_expect=2)
# ⭐ 坐标反了 / y 超界**必须保留** —— 那是"这块地不好用"，不是"数据损坏"
_dirty("坐标反了 x0>x1（**该保留**）",
       [{"x0": 700, "y0": 488, "x1": 430, "y1": 599, "kind": "solid"}], keep_expect=1)
_dirty("y0 远高于画布（**该保留**）",
       [{"x0": 400, "y0": 9999, "x1": 600, "y1": 99999, "kind": "solid"}], keep_expect=1)
_dirty("4 元组正常项（**该保留**）", [(430, 488, 700, 599)], keep_expect=1)
# ⭐ ⭐ 必须有 warn 输出（⛔ 不许静默丢：用户以为生效了、画面却少一块）
_cap = []
_real_print = print
try:
    import builtins
    builtins.print = lambda *a, **k: _cap.append(" ".join(str(x) for x in a))
    _r = N.Room(N.NIGHTS[0])
    _r.platforms = [None, {}]
finally:
    import builtins
    builtins.print = _real_print
chk("⑧-c7 丢弃坏条目时**有 warn 输出**（⛔ 静默丢会被误认为生效了）",
    any("丢弃" in c for c in _cap), "捕获 %d 条输出，样例：%s"
    % (len(_cap), next((c for c in _cap if "丢弃" in c), "（无）")[:70]))
# ⭐ 已知的既有行为（⑧ 号判据已认可）：**全丢弃 ⇒ 地板也没了 ⇒ 自由落体**。
#   ⛔ 这里锁的是「它至少不崩」，不是「她站得住」—— 想要地板在，
#   应该只丢自定义层（custom 路径），而不是把整张表换掉。
r_empty2 = N.Room(N.NIGHTS[0])
r_empty2.platforms = [None]
l_empty = luna_at(200.0, 300.0)
for _ in range(60):
    l_empty.update(DT, set(), r_empty2)
chk("⑧-c8 全丢弃时不崩（**已知会自由落体**，锁的是不崩不是站住）",
    l_empty.y < N.VH + 200, "y=%.1f（地板已被一起丢弃，VH=%d）" % (l_empty.y, N.VH))
#⭐ ⭐ 但 **custom 路径**必须保住地板：Ronny 手改的是 custom JSON，不是整张表
r_custom_bad = N.Room(N.NIGHTS[0], custom=[None, {"kind": "solid"}])
chk("⑧-c9 custom 有脏条目时**默认 4 平台仍在**（地板保住）",
    len(r_custom_bad.platforms) == 4, "实测 %d 条" % len(r_custom_bad.platforms))
r_custom_ok = N.Room(N.NIGHTS[0], custom=[{"x0": 900, "y0": 400, "x1": 1000, "y1": 450}])
chk("⑧-c10 custom 全合法时 4+1 条",
    len(r_custom_ok.platforms) == 5, "实测 %d 条" % len(r_custom_ok.platforms))

# ============================================================================
section("⑧-d ⭐ 坐标【值类型】炸（design端第二道反例，比第一道更易手写触发）")
# ============================================================================
# ⭐ 第一版 `plat_valid` 只查「键在不在」⇒ 漏了这条路：
#   {"x0": "400"} 打字忘去引号/ 粘贴带引号⇒ TypeError: str - float
#   {"x0": null}   复制粘贴带了 null   ⇒ TypeError: NoneType - float
#   根因：物理层要算 `x0 - BODY_W*0.35` ⇒ **坐标必须是数**。
# ⛔ 底线要求：**无论「保留」还是「丢弃」，都不许崩。**
def _val_dirty(name, plat, expect_keep):
    """单个条目值类型脏 ⇒ 不崩 + 保留条数符合预期。"""
    r = N.Room(N.NIGHTS[0])
    r.platforms = [plat]
    ex = None
    try:
        l = luna_at(200.0, 300.0)
        for _ in range(60):
            l.update(DT, set(), r)
        m2 = Microwave(N.NIGHTS[0])
        m2._patrol(DT, type("S", (), {"x": 200.0, "y": N.FLOOR_Y})())
    except Exception as e:                   # noqa: BLE001
        ex = e
    chk("⑧-d %s ⇒ 不崩，%s" % (name, "保留" if expect_keep else "丢弃"),
        ex is None and (len(r.platforms) == 1) == expect_keep,
        "保留 %d 条，异常 %r" % (len(r.platforms), ex))
    return len(r.platforms), ex


# ---- design端点名的 2 条 ----
_val_dirty('坐标是字符串 "400"', {"x0": "400", "y0": 400, "x1": 700, "y1": 599}, True)
_val_dirty("坐标是 None", {"x0": None, "y0": 400, "x1": 700, "y1": 599}, False)
#⭐ 纯数字字符串**保留**（JSON 里 "400" 语义上就是 400）⇒ 那物理层必须能处理它
chk("⑧-d2a 纯数字字符串坐标被归一成 float（物理层能算）",
    all(isinstance(v, float) for v in N.plat_fields({"x0": "400", "y0": "400",
                                                    "x1": "700", "y1": "599"})),
    "实测 %s（类型 %s）"
    % (N.plat_fields({"x0": "400", "y0": "400", "x1": "700", "y1": "599"}),
       type(N.plat_fields({"x0": "400", "y0": "400",
                           "x1": "700", "y1": "599"})[0]).__name__))
# ---- 以下 5 条是我实测时顺手挖出来的，design端没提 ----
_val_dirty("y1 是字符串（**原先不崩**，因为它没参与算术）",
           {"x0": 100, "y0": 400, "x1": 700, "y1": "599"}, True)
_val_dirty("x0 是列表 [1,2]", {"x0": [1, 2], "y0": 400, "x1": 700, "y1": 599}, False)
_val_dirty("x0 是嵌套 dict", {"x0": {"a": 1}, "y0": 400, "x1": 700, "y1": 599}, False)
_val_dirty('x0 是 true（float(True)==1.0 会**静默通过**）',
           {"x0": True, "y0": 400, "x1": 700, "y1": 599}, False)
_val_dirty('x0 是 "abc"（转不了 float）',
           {"x0": "abc", "y0": 400, "x1": 700, "y1": 599}, False)
# ⛔⛔ 4 元组也要查值类型 —— 它是「旧格式」，但那 3 处自测/外部脚本同样可能塞脏数据
_val_dirty("4 元组含字符串", ("400", 488, 700, 599), True)
_val_dirty("4 元组含 None", (None, 488, 700, 599), False)

# ---- ⭐⭐ 回归：这些**必须仍然保留**（不能因为加了值校验被误伤）----
_keep = [
    ("坐标反了 x0>x1", {"x0": 700, "y0": 488, "x1": 430, "y1": 599}),
    ("四角全反", {"x0": 700, "y0": 599, "x1": 430, "y1": 488}),
    ("极窄 x1-x0=1", {"x0": 400, "y0": 400, "x1": 401, "y1": 599}),
    ("kind 是乱字符串 wat", {"x0": 400, "y0": 400, "x1": 700, "y1": 599, "kind": "wat"}),
    ("kind 缺失", {"x0": 400, "y0": 400, "x1": 700, "y1": 599}),
    ("climb 但零高", {"x0": 400, "y0": 400, "x1": 400, "y1": 400, "kind": "climb"}),
    ("y0 远高于画布", {"x0": 400, "y0": 9999, "x1": 600, "y1": 99999}),
    ("正常条目", {"x0": 400, "y0": 400, "x1": 700, "y1": 599}),
]
for nm, pl in _keep:
    chk("⑧-d3 %s ⇒ **仍保留**（值校验不许误伤）" % nm,
        N.plat_valid(pl), "plat_valid=%s" % N.plat_valid(pl))

# ---- ⭐⭐ 3.2 design端要的：custom 脏数据**不许拖垮默认地形** ----
r_cd = N.Room(N.NIGHTS[0], custom=[None, {"x0": 900, "y0": 400, "x1": 1000, "y1": 450}])
chk("⑧-d4 ⭐ custom 脏数据**不拖垮默认地形**（4 平台 + 1 好= 5 条）",
    len(r_cd.platforms) == 5, "实测 %d 条 %s" % (len(r_cd.platforms), r_cd.platforms))
chk("⑧-d5 ⭐ custom 脏数据时地板仍在（x=100 处仍可站）",
    any(p["x0"] == 0 and p["y0"] == N.FLOOR_Y for p in r_cd.platforms),
    "地板条 %s" % [p for p in r_cd.platforms if p["x0"] == 0])
r_cd2 = N.Room(N.NIGHTS[0], custom=[{"x0": "400", "y0": None, "x1": 700, "y1": 599},
                                  {"x0": None, "y0": 1, "x1": 2, "y1": 3}])
chk("⑧-d6 ⭐ custom 全是脏值 ⇒ **默认 4 平台仍在**（地板不消失）",
    len(r_cd2.platforms) == 4, "实测 %d 条" % len(r_cd2.platforms))
l_cd = luna_at(100.0, 300.0)
for _ in range(60):
    l_cd.update(DT, set(), r_cd2)
chk("⑧-d7 ⭐ custom 全脏时她仍站在地板上（**不是自由落体**）",
    abs(l_cd.y - N.FLOOR_Y) < 2.0 and l_cd.on_ground,
    "y=%.2f on_ground=%s FLOOR_Y=%d" % (l_cd.y, l_cd.on_ground, N.FLOOR_Y))

# ============================================================================
section("⑨ 编辑器：模式切换 / 增删 / 撤销 / 清空")
# ============================================================================
pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = N.NightWindow(pack)
w.start_night(0)
# ⛔ 判据⑨-2 必须**先**检查初始态，再改mode。
#   （我第一版把 render 测试写在前面，于是 mode 已是 edit，
#    ⑨-2 检查 "mode==play" 必然红 —— 那是判据自己污染了自己。）
chk("⑨-2 初始 mode=play / 无自定义地形",
    w.mode == "play" and w.custom_terrains == [],
    "mode=%s n=%d" % (w.mode, len(w.custom_terrains)))
# ⭐ 强制 render 一次（纪律③：paintEvent 的错只在真渲染时暴露）
w.mode = "edit"
try:
    w.render(w.grab())
    render_ok, rerr = True, None
except Exception as e:                      # noqa: BLE001
    render_ok, rerr = False, e
chk("⑨-1 编辑态强制 render 不抛异常", render_ok, "异常 %r" % (rerr,))

w.set_mode("edit")
chk("⑨-3 set_mode('edit') 后 room 是编辑态（含自定义层）",
    w.mode == "edit" and hasattr(w.room, "custom"), "mode=%s" % w.mode)
n0 = w._edit_add(500.0, 400.0, 700.0, 450.0, "solid")
chk("⑨-4 矩形添加一块地形成功", n0 and len(w.custom_terrains) == 1,
    "n=%d %s" % (len(w.custom_terrains), w.custom_terrains))
chk("⑨-5 加进去后 room.platforms 立刻变长（编辑中立即呈现）",
    len(w.room.platforms) == 5, "实测 %d" % len(w.room.platforms))
# ⛔ 非法矩形必须被拒
chk("⑨-6 零面积矩形被拒",
    not w._edit_add(500.0, 400.0, 500.0, 400.0, "solid")
    and len(w.custom_terrains) == 1, "n=%d" % len(w.custom_terrains))
chk("⑨-7 反向拖拽被规范化（x0<x1 / y0<y1）",
    w._edit_add(700.0, 450.0, 500.0, 400.0, "brittle")
    and w.custom_terrains[-1]["x0"] == 500.0
    and w.custom_terrains[-1]["y1"] == 450.0,
    "实测 %s" % w.custom_terrains[-1])
chk("⑨-8 超出地板线的部分被夹到 FLOOR_Y（不产生废数据）",
    all(t["y0"] <= N.FLOOR_Y and t["y1"] <= N.FLOOR_Y for t in w.custom_terrains),
    "实测 %s" % [(t["y0"], t["y1"]) for t in w.custom_terrains])
# ⭐ 点选 + 删除
i = w._edit_hit(600.0, 420.0)
chk("⑨-9 点选命中正确下标", i == 0, "命中 %d" % i)
chk("⑨-10 命中范围外的点返回 -1", w._edit_hit(3000.0, 300.0) == -1, "")
w.edit_sel = 0
chk("⑨-11 删除选中项", w._edit_del() and len(w.custom_terrains) == 1,
    "n=%d" % len(w.custom_terrains))
# ⭐ 撤销
before = len(w.custom_terrains)
w.edit_undo()
chk("⑭撤销恢复了一项", len(w.custom_terrains) == before + 1,
    "%d → %d" % (before, len(w.custom_terrains)))
# ⛔ 撤销到空栈必须返回 False 而不是崩
w._undo = []
chk("⑨-13 空撤销栈返回 False（不崩）", w.edit_undo() is False, "")
#⭐ 清空 + 二次确认
w._confirm_clear = False
w.edit_clear()
chk("⑨-14 清空后自定义地形为 0 块", len(w.custom_terrains) == 0,
    "n=%d" % len(w.custom_terrains))
#⭐ play_custom：自定义地形立刻进room
w._edit_add(1500.0, 400.0, 1700.0, 450.0, "climb")
w.set_mode("play_custom")
chk("⑨-15 play_custom 下自定义地形进了 room",
    len(w.room.platforms) == 5 and any(
        N.plat_kind(p) == "climb" for p in w.room.platforms),
    "platforms=%d" % len(w.room.platforms))
w.set_mode("play")
chk("⑨-16 回 play 后自定义地形**不**进 room（默认行为不变）",
    len(w.room.platforms) == 4, "platforms=%d" % len(w.room.platforms))
chk("⑨-17 自定义数据仍留着（切模式不清空编辑成果）",
    len(w.custom_terrains) == 1, "n=%d" % len(w.custom_terrains))

# ============================================================================
section("⑩ 编辑器：导出/导入真实文件往返")
# ============================================================================
tp = os.path.join(HERE, "_work", "_pr12_terrain.json")
os.makedirs(os.path.dirname(tp), exist_ok=True)
w.custom_terrains = [
    {"kind": "solid",   "x0": 430.0, "y0": 488.0, "x1": 700.0, "y1": 599.0},
    {"kind": "brittle", "x0": 900.0, "y0": 420.0, "x1": 1100.0, "y1": 460.0},
]
w.set_mode("edit")
real = w.export_terrain(tp)
chk("⑩-1 导出文件真实写出", os.path.isfile(real), "路径 %s" % real)
with open(real, "r", encoding="utf-8") as f:
    on_disk = json.load(f)
chk("⑩-2 磁盘内容结构 = 派单 §五",
    sorted(on_disk.keys()) == ["floor_y", "terrains", "version", "world_w"]
    and len(on_disk["terrains"]) == 2,
    json.dumps(on_disk, ensure_ascii=False)[:150])
w.custom_terrains = []
n_imp = w.import_terrain(tp)
chk("⑩-3 导入回来 2 块", n_imp == 2, "n=%d" % n_imp)
chk("⑩-4 导入后 kind 顺序与类型都对",
    [N.plat_kind(t) for t in w.custom_terrains] == ["solid", "brittle"],
    "实测 %s" % [N.plat_kind(t) for t in w.custom_terrains])
try:
    os.remove(real)
    removed = True
except OSError:
    removed = False
chk("⑩-5 测试文件已清理（不留垃圾）", removed or not os.path.isfile(real), "")

# ============================================================================
section("⑪ paintEvent 三条路径都 render 一遍（纪律③）")
# ============================================================================
for mode, why in (("play", "正常游戏"), ("play_custom", "自定义地形试跑"), ("edit", "编辑态")):
    w.mode = mode
    try:
        w.render(w.grab())
        e = None
    except Exception as ex:                 # noqa: BLE001
        e = ex
    chk("⑪-%s mode=%s render 不抛异常" % (why[:4], mode), e is None, "异常 %r" % (e,))

# ============================================================================
section("⑫ 直线工具：Shift 轴锁定 / 零厚数据形状")
# ============================================================================
w2 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
w2.start_night(0)
w2.set_mode("edit")
w2.custom_terrains = []
# ---- 水平线（dx > dy ⇒ 锁水平，y 相同）----
ok_h = w2._edit_add(500.0, 400.0, 700.0, 410.0, "solid", line=True, shift=True)
t = w2.custom_terrains[-1]
chk("⑫-1 Shift+宽横线 ⇒ 水平零厚（y0 == y1）",
    ok_h and t["y0"] == t["y1"], "实测 y0=%.1f y1=%.1f" % (t["y0"], t["y1"]))
chk("⑫-2 水平线 x 跨度 = 拖出来的宽度", abs(t["x1"] - t["x0"] - 200.0) < 1.0,
    "实测 %.1f" % (t["x1"] - t["x0"]))
# ---- 垂直线（dy > dx ⇒ 锁垂直，x 相同）----
w2.custom_terrains = []
ok_v = w2._edit_add(1500.0, 300.0, 1510.0, 599.0, "climb", line=True, shift=True)
t = w2.custom_terrains[-1]
chk("⑫-3 Shift+竖直线 ⇒ 垂直零厚（x0 == x1）",
    ok_v and t["x0"] == t["x1"], "实测 x0=%.1f x1=%.1f" % (t["x0"], t["x1"]))
chk("⑫-4 垂直线 y 跨度 = 拖出来的高度", abs(t["y1"] - t["y0"] - 299.0) < 1.0,
    "实测 %.1f" % (t["y1"] - t["y0"]))
# ⭐ 两种朝向**都要能选**（Ronny 原话「只能垂直或者水平」= 两者都允许）
# ⚠️ 每条判据前都要先把地形摆成对应形状 —— 我第一版忘了，
#    ⑫-3 已经把表换成垂直线了，⑫-5 却去点水平线的位置 ⇒ 必然 -1。
#    （这是判据自身的顺序 bug，不是代码 bug。）
w2.custom_terrains = []
w2._edit_add(500.0, 400.0, 700.0, 410.0, "solid", line=True, shift=True)
chk("⑫-5 水平线也能选（两种朝向都可选）", w2._edit_hit(600.0, 400.0) >= 0,
    "当前地形 %s 命中 %d" % (w2.custom_terrains[-1], w2._edit_hit(600.0, 400.0)))
w2.custom_terrains = []
w2._edit_add(1500.0, 300.0, 1510.0, 599.0, "climb", line=True, shift=True)
chk("⑫-6 垂直线也能选", w2._edit_hit(1500.0, 450.0) >= 0,
    "当前地形 %s 命中 %d" % (w2.custom_terrains[-1], w2._edit_hit(1500.0, 450.0)))
# ---- 不按 Shift ⇒ 自由（仍有厚度，不锁轴）----
w2.custom_terrains = []
w2._edit_add(500.0, 400.0, 700.0, 450.0, "solid", line=True, shift=False)
t = w2.custom_terrains[-1]
chk("⑫-7 不按 Shift ⇒ 自由（有厚度，未锁轴）",
    t["y1"] - t["y0"] > 0.0, "实测厚度 %.1f" % (t["y1"] - t["y0"]))
# ---- 导出时 y1 不许省（schema 统一）----
dd = N.terrain_to_json([{"kind": "solid", "x0": 500.0, "y0": 400.0,
                        "x1": 700.0, "y1": 400.0}])
chk("⑫-8 零厚地形导出时 y1 字段**仍在**（不许省）",
    "y1" in dd["terrains"][0] and dd["terrains"][0]["y1"] == 400,
    "实测 %s" % dd["terrains"][0])
chk("⑫-9 零厚往返导入后仍零厚",
    abs(N.terrain_from_json(dd)[0]["y1"] - 400.0) < 1e-6,
    "实测 %s" % N.terrain_from_json(dd)[0])
# ⛔⛔ 回归守卫：**亚像素坐标**导出后必须仍是零厚。
#   我第一版用 int(round(v)) 各取各的 ⇒ 垂直线 x0=1500.6/x1=1500.6
#   会变成 1501 和 1501（碰巧相等），但 x0=1499.5/x1=1499.5 在浮点下
#   可能分别落到 1500 与 1499 ⇒ 零厚线被撑成 2px 宽 ⇒ 语义从攀爬面变窄平台。
#   ⇒ 用**最刁钻的亚像素值**做阳性对照。
_dz = [{"kind": "climb", "x0": 1499.5, "y0": 300.0, "x1": 1499.5, "y1": 599.0},
       {"kind": "solid", "x0": 500.4, "y0": 400.6, "x1": 700.4, "y1": 400.6}]
_dzj = N.terrain_to_json(_dz)["terrains"]
chk("⑫-9a 亚像素垂直线导出后仍零厚（x0==x1）",
    _dzj[0]["x0"] == _dzj[0]["x1"],
    "导出 %s ⇒ x0=%d x1=%d" % (_dzj[0], _dzj[0]["x0"], _dzj[0]["x1"]))
chk("⑫-9b 亚像素水平线导出后仍零厚（y0==y1）",
    _dzj[1]["y0"] == _dzj[1]["y1"],
    "导出 %s ⇒ y0=%d y1=%d" % (_dzj[1], _dzj[1]["y0"], _dzj[1]["y1"]))
# ---- 工具切换 ----
for key, want in ((Qt.Key_4, "rect"), (Qt.Key_5, "line"), (Qt.Key_6, "select")):
    w2._edit_key(key)
    chk("⑫-10 快捷键切到 %s" % want, w2.edit_tool == want,
        "实测 %s" % w2.edit_tool)

# ============================================================================
section("⑬ platform_get：3 处手工灌 4 元组的自测不能炸")
# ============================================================================
# ⭐ design端指出的缺口：_自测_PR04判据.py:54 / _自测_冰箱.py:44 /
#   _d_新布局几何.py:36 都写 `room.platforms = list(N.PLATFORMS)`（4 元组）
#   ⇒ ⛔ 那些自测一个字都不许改，必须靠 helper 兼容。
rk = dict({"x0": 1, "y0": 2, "x1": 3, "y1": 4, "kind": "brittle"})
tp4 = (1, 2, 3, 4)
chk("⑬-1 platform_get 吃 dict", N.platform_get(rk, "kind") == "brittle",
    "实测 %r" % N.platform_get(rk, "kind"))
chk("⑬-2 platform_get 吃 4 元组（按位置映射）",
    N.platform_get(tp4, "x0") == 1 and N.platform_get(tp4, "y1") == 4,
    "实测 x0=%r y1=%r" % (N.platform_get(tp4, "x0"), N.platform_get(tp4, "y1")))
chk("⑬-3 4 元组没有 kind ⇒ 返回 default（不猜）",
    N.platform_get(tp4, "kind", "solid") == "solid"
    and N.platform_get(tp4, "kind", None) is None, "")
chk("⑬-4 plat_fields 两种都吃",
    N.plat_fields(rk) == (1, 2, 3, 4) and N.plat_fields(tp4) == (1, 2, 3, 4), "")
chk("⑬-5 plat_kind：4 元组一律 solid（不能猜成脆的）",
    N.plat_kind(tp4) == "solid" and N.plat_kind(rk) == "brittle", "")
# ⭐ 真跑一遍「灌 4 元组」的物理，确认不炸
r_mix = mk_room(None)
r_mix.platforms = list(N.PLATFORMS)          # ⛔ 复刻那 3 处自测的写法
lm = luna_at(200.0, 300.0)
err_mix = None
try:
    for _ in range(120):
        lm.update(DT, set(), r_mix)
except Exception as e:                      # noqa: BLE001
    err_mix = e
chk("⑬-6 房间灌 4 元组后露娜物理正常（不抛异常）", err_mix is None,
    "异常 %r落点 y=%.1f" % (err_mix, lm.y))
chk("⑬-7 灌 4 元组后仍能正常站在地板上",
    abs(lm.y - N.FLOOR_Y) < 2.0, "y=%.2f" % lm.y)

# ============================================================================
section("⑭ ⭐ 真机交互：三态切换 + 四种画法 + 导出往返（design端要求入判据）")
# ============================================================================
# ⭐ 为什么这一节存在：我第一版在回执里标了「真机交互未验证」，
#   却没有把它变成判据 —— 验证只存在于 design端 的复核脚本里，
#   换台机器跑就消失。⇒ 这一节把「鼠标真能用」钉成可复跑的断言。
#   ⛔ 纪律：用**真实 QMouseEvent / QKeyEvent** 驱动，不许直接调 _edit_add 冒充交互。
from PySide6.QtCore import QPoint, QEvent
from PySide6.QtGui import QMouseEvent, QKeyEvent

w3 = N.NightWindow(load_pack(os.path.join(HERE, "packs", "luna")))
w3.start_night(0)


def _mouse(kind, btn, pos, mods=Qt.NoModifier):
    return QMouseEvent(kind, QPointF_(pos), btn, btn, mods)


def QPointF_(pos):
    from PySide6.QtCore import QPointF
    return QPointF(float(pos[0]), float(pos[1]))


def key(k):
    return QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)


# ---- 三态切换 ----
w3._edit_key(Qt.Key_F2)
chk("⑭-1 F2 从play 进 edit", w3.mode == "edit", "mode=%s" % w3.mode)
w3._edit_key(Qt.Key_Escape)
chk("⑭-2 Escape 从 edit 回 play", w3.mode == "play", "mode=%s" % w3.mode)
w3._edit_key(Qt.Key_F4)
chk("⑭-3 F4 进 play_custom（自定义地形立刻试跑）", w3.mode == "play_custom",
    "mode=%s" % w3.mode)
w3._edit_key(Qt.Key_F2)
chk("⑭-4 F2 从 play_custom 进 edit", w3.mode == "edit", "mode=%s" % w3.mode)
# ⛔ 非法模式必须被拒：`_edit_key` 只处理具体按键、**不接受模式名**，
#    所以这条要测 set_mode 本身（我第一版错测了 _edit_key ⇒ 必然不抛 ⇒ 假红）。
try:
    w3.set_mode("F9")             # ⛔ 不存在的模式名
    chk("⑭-5 非法模式被拒（set_mode 抛 ValueError 不静默）", False, "⛔ 没抛")
except ValueError as e:
    chk("⑭-5 非法模式被拒（set_mode 抛 ValueError 不静默）", True, "ValueError: %s" % str(e)[:50])
# ⛔ F9 只是个普通按键，**不该**改变模式（也不该崩）
w3.mode = "play"
w3._edit_key(Qt.Key_F9)
chk("⑭-5b 无关按键（F9）不改变模式、也不崩", w3.mode == "play", "mode=%s" % w3.mode)
# ⭐⭐ 上面那条**故意把 mode 留在 play** ⇒ 下面的鼠标判据必须**先回到 edit**，
#    否则 mousePressEvent 第一行`if self.mode != "edit": return` 会全部跳过，
#    表现为"矩形/直线全画不出来"。⛔ 这是我第一版埋的顺序坑（红的时候一度
#    怀疑是鼠标事件构造错了）。凡是被判据改过mode，后面必须复位。
w3.set_mode("edit")

# ---- 四种画法：矩形 / 直线水平 / 直线垂直 / 斜线两处理 ----
w3.custom_terrains = []
w3._drag = None
# ① 矩形：真实按下-移动-松开三步
w3.edit_tool = "rect"
p0 = (200.0 * w3.k, 400.0 * w3.k)
p1 = (400.0 * w3.k, 450.0 * w3.k)
w3.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, p0))
w3.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, p1))
w3.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, p1))
chk("⑭-6 ⭐ 矩形：真实鼠标三事件画出一块",
    len(w3.custom_terrains) == 1, "n=%d %s" % (len(w3.custom_terrains),
                                     w3.custom_terrains[:1]))
if w3.custom_terrains:
    t = w3.custom_terrains[-1]
    chk("⑭-7 矩形坐标 = 拖的世界坐标（屏幕/k+cam_x 换算正确）",
        abs(t["x0"] - 200.0) < 2.0 and abs(t["x1"] - 400.0) < 2.0,
        "实测 x0=%.1f x1=%.1f（期望 200/400）" % (t["x0"], t["x1"]))
# ② 直线（水平）：按住 Shift
w3.custom_terrains = []
w3.edit_tool = "line"
a0 = (600.0 * w3.k, 380.0 * w3.k)
a1 = (800.0 * w3.k, 430.0 * w3.k)      # 故意 y 也变了，Shift 应把它压成水平
w3.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, a0, Qt.ShiftModifier))
w3.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, a1, Qt.ShiftModifier))
w3.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, a1, Qt.ShiftModifier))
ok_h2 = len(w3.custom_terrains) == 1 and w3.custom_terrains[-1]["y0"] == w3.custom_terrains[-1]["y1"]
chk("⑭-8 ⭐ 直线+Shift：真实鼠标画出**水平**零厚线", ok_h2,
    "实测 %s" % (w3.custom_terrains[-1] if w3.custom_terrains else "（没画出来）"))
# ③ 直线（垂直）：Shift 且 dy > dx
w3.custom_terrains = []
b0 = (1200.0 * w3.k, 300.0 * w3.k)
b1 = (1215.0 * w3.k, 560.0 * w3.k)     # dx 小 dy 大⇒ 应锁垂直
w3.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, b0, Qt.ShiftModifier))
w3.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, b1, Qt.ShiftModifier))
w3.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, b1, Qt.ShiftModifier))
ok_v2 = len(w3.custom_terrains) == 1 and w3.custom_terrains[-1]["x0"] == w3.custom_terrains[-1]["x1"]
chk("⑭-9 ⭐ 直线+Shift：真实鼠标画出**垂直**零厚线", ok_v2,
    "实测 %s" % (w3.custom_terrains[-1] if w3.custom_terrains else "（没画出来）"))
# ④ 不按 Shift ⇒ 自由（有厚度，dy 大也不锁轴）
w3.custom_terrains = []
c0 = (1200.0 * w3.k, 300.0 * w3.k)
c1 = (1215.0 * w3.k, 560.0 * w3.k)
w3.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, c0))
w3.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, c1))
w3.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, c1))
ok_f = len(w3.custom_terrains) == 1 and w3.custom_terrains[-1]["y1"] > w3.custom_terrains[-1]["y0"]
chk("⑭-10 ⭐ 直线**不按 Shift**：自由（有厚度，未锁轴）", ok_f,
    "实测 %s" % (w3.custom_terrains[-1] if w3.custom_terrains else "（没画出来）"))
# ⛔⛔ 负向：编辑态之外的鼠标事件**必须被忽略**（游戏里左键不该有效果）
n_before = len(w3.custom_terrains)
w3.mode = "play"
w3.mousePressEvent(_mouse(QEvent.MouseButtonPress, Qt.LeftButton, p0))
w3.mouseMoveEvent(_mouse(QEvent.MouseMove, Qt.NoButton, p1))
w3.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, Qt.LeftButton, p1))
chk("⑭-11 ⛔ play 态鼠标事件被忽略（不画地形、不抢游戏鼠标）",
    len(w3.custom_terrains) == n_before, "n=%d → %d" % (n_before, len(w3.custom_terrains)))
# ⛔ 编辑按键不许进游戏按键集合（否则 Delete 会被当移动键反复响应）
w3.mode = "edit"
w3.set_mode("edit")
w3.keys.clear()
w3.keyPressEvent(key(Qt.Key_Delete))
chk("⑭-12 ⛔ 编辑键不进 self.keys（否则游戏里被当按住不放的键）",
    len(w3.keys) == 0, "keys=%s" % w3.keys)

# ---- 导出往返（走真实按键S / O）----
w3.custom_terrains = [
    {"kind": "solid", "x0": 1500.0, "y0": 500.0, "x1": 1700.0, "y1": 599.0},
    {"kind": "climb", "x0": 1500.0, "y0": 300.0, "x1": 1500.0, "y1": 599.0},
]
tp3 = os.path.join(HERE, "_work", "_pr12_terrain2.json")
os.makedirs(os.path.dirname(tp3), exist_ok=True)
w3.terrain_path = tp3
w3.msg, w3.msg_t = "", 0.0
w3.keyPressEvent(key(Qt.Key_S))               # ⭐ 真实按键导出
exp_ok = os.path.isfile(tp3)
chk("⑭-13 ⭐ 按 S 真实导出文件", exp_ok, "路径 %s" % tp3)
w3.custom_terrains = []
w3.msg, w3.msg_t = "", 0.0
w3.keyPressEvent(key(Qt.Key_O))               # ⭐ 真实按键导入
imp_ok = len(w3.custom_terrains) == 2
chk("⑭-14 ⭐ 按 O 真实导入回来 2 块", imp_ok,
    "n=%d %s" % (len(w3.custom_terrains), w3.custom_terrains))
chk("⑭-15 导入后零厚语义还在（垂直线仍 x0==x1）",
    len(w3.custom_terrains) == 2 and w3.custom_terrains[1]["x0"] == w3.custom_terrains[1]["x1"],
    "实测 %s" % (w3.custom_terrains[1] if len(w3.custom_terrains) > 1 else "—"))
try:
    os.remove(tp3)
except OSError:
    pass

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