# -*- coding: utf-8 -*-
"""_自测_可达性.py —— 三档关卡的**静态可达性**检查

⭐ 为什么用静态几何而不是"模拟一个玩家打一遍"：
   我先写了个模拟玩家版，它报"三档都拿不到食物" —— ⛔ 假警报。
   根因：模拟玩家不会爬梯/跳，而容器大多在台面（y=470）和吊柜（y=320）上。
   ⭐ 单位测试全绿 ≠ 玩得通；但"模拟操作"本身如果写不对，会给出**更糟的假警报**。
   ⭐ 所以这一项改成**纯几何判定** —— 更稳、更能定位到底是哪一件够不到。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pet_engine import night as N

# 实测值（来自 _自测_夜间.py 的跳跃断言 190~225）
JUMP_MAX = 211
REACH_DY = 66.0        # 敲容器的 y 判定半径
REACH_DX = 54.0        # 敲容器的 x 判定半径

plats = [(x0, y0, x1) for (x0, y0, x1, y1) in N.PLATFORMS[1:]]   # 去掉地板
OK = []
BAD = []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print("  %s  %s   %s" % ("OK  " if cond else "FAIL", name, info))


def how_to_reach(x, y, ladder_x, ladder_top):
    """她怎么才能站到能敲到这个容器的位置。返回可读路径或 None。

    ⭐ 关键：**梯子不需要在容器正上方** —— 爬上台面后可以沿台面横向走过去。
      （我第一版把"梯子必须在容器 ±30px 内"当必要条件，误报了 9 件"够不到"。）
    ⭐ 所以正确判据是两条：
      ① 能不能**站上**覆盖容器 x 的某一层平台 P（|P.y - 容器y| ≤ 判定半径）；
      ② 从地面（或更低的平台）能不能到 P —— 靠梯子（顶端 == P.y）或跳（落差 ≤ 211）。
    """
    # 覆盖容器 x 的表面，**地板也要算**（⛔ 第一版漏了地板 → 地板上的容器全被判"够不到"）
    cand = [(N.FLOOR_Y, 0, 1280)] + [(py0, px0, px1) for (px0, py0, px1) in plats if px0 <= x <= px1]
    cand.sort(key=lambda t: t[0])          # y 小 = 位置高（先试高层，再退回地面）
    for (py, px0, px1) in cand:
        if abs(py - y) > REACH_DY:
            continue                        # 这一层站上去也够不到（高度不对）
        # ② 从地面能不能到这一层
        if py >= N.FLOOR_Y - 1:
            return "地板"                    # 就在地板层
        # ⭐ 梯子：只要**有一根梯子的顶端 == 这一层的 y** 就行（⛔ 不要求梯子在容器正上方）
        #   ⭐ 2026-10-03 追加攀爬面（LADDER_ZONES，桌布整面）—— 取中心 x 参与同一判据
        _lad_all = list(N.LADDERS) + [((z[0] + z[1]) / 2.0, z[2], z[3]) for z in N.LADDER_ZONES]
        for (lx, ltop, lbot) in _lad_all:
            if abs(ltop - py) <= 2.0:
                return "爬梯子 x=%d → 站 y=%d，沿台面走到 x=%d" % (lx, py, x)
        # ⛔ 解包顺序必须是 (y, x0, x1) —— 我曾经写成 (qx, qy0, qx1)，
        #    结果 `qy0 > py` 变成在比 **x0 和 y**，跳跃判定整个是错的
        #    （先误报"全部可达"，改布局后又误报"够不到"）。
        for (qy0, qx0, qx1) in cand:
            if qy0 > py and (qy0 - py) <= JUMP_MAX:
                return "从 y=%d 跳 %dpx → 站 y=%d" % (qy0, qy0 - py, py)
    return None


print("=" * 76)
print("可达性：每个容器/冰箱能不能走到（静态几何，不模拟操作）")
print("=" * 76)
ladder_x, ladder_top, _ = N.LADDERS[0]
print("梯子 x=%d 顶端 y=%d   跳跃上限 %dpx   判定半径 dx=%.0f dy=%.0f"
      % (ladder_x, ladder_top, JUMP_MAX, REACH_DX, REACH_DY))
print("平台：%s" % [(x0, y0, x1) for (x0, y0, x1) in plats])

for cfg in N.NIGHTS:
    name = cfg["name"]
    print("\n【%s】边界 x=%d  微波炉巡逻 %s  容器 %d 件"
          % (name, cfg["border_x"], tuple(cfg["patrol"]), len(cfg["stashes"])))
    for s in cfg["stashes"]:
        how = how_to_reach(s["x"], s["y"], ladder_x, ladder_top)
        risk = "⚠ 要越界 %.0fpx" % max(0, s["x"] - cfg["border_x"]) if s["x"] > cfg["border_x"] else "区内"
        chk("  %-10s x=%-5d y=%-4d" % (s["icon"], s["x"], s["y"]),
            how is not None, "%s  %s" % (how or "⛔ 够不到", risk))
    # 冰箱 —— ⭐ 2026-10-03 改口径：QTE 站位 = **桌面上**（背景板里冰箱下半被桌布挡住，
    #   看得见的部分全在桌面以上；地板那侧现在是实心布墙，根本站不进去）
    fx = N.FRIDGE["x"] + 40.0        # 冰箱段在桌面右半（570~730），取 610
    fr = how_to_reach(fx, N.TABLE_TOP, ladder_x, ladder_top)
    chk("  冰箱      x=%-5d y=%-4d" % (fx, N.TABLE_TOP), fr is not None,
        "%s  %s" % (fr or "⛔ 够不到",
                     "⚠ 要越界 %.0fpx" % (fx - cfg["border_x"]) if fx > cfg["border_x"] else "区内"))

print()
print("=" * 76)
print("通过 %d / %d" % (len(OK), len(OK) + len(BAD)))
if BAD:
    print("未通过：")
    for b in BAD:
        print("   " + b)
print("=" * 76)
sys.exit(1 if BAD else 0)
