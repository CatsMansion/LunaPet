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

# ⭐⭐ 2026-10-04 实测值（_d_新布局几何.py，真实 Luna.update 跑出来）：
#   跳跃上限 = **204px**，⛔ 不是解析值 211。
#   ⛔ 解析值 JUMP_V²/(2g) = 211.6 会**高估 7~8px** —— 离散积分每帧先加重力再位移，
#     峰值出现在帧边界上而不是解析顶点，所以实测必然略小。
#   ⚠️ 后果：拿 211 当判据，会把「差 5px 够不到」的平台**误判成够得到**。
#     这不是保守估计，是**乐观估计**，方向正好是最坏的那一侧。
JUMP_MAX = 204
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

    ⭐ 关键：**梯子/起跳点不需要在容器正上方** —— 爬上台面后可以沿台面横向走过去。
      （我第一版把"梯子必须在容器 ±30px 内"当必要条件，误报了 9 件"够不到"。）

    ⭐⭐ 2026-10-04 修判据的**结构性缺陷**（背景板 v4 重排后暴露）：
      旧版只在「**覆盖容器 x** 的平台」列表 cand 里找起跳点，
      于是「起跳台不覆盖容器 x」的情况一律判够不到。
      实测反例：茶几(430~700) 不覆盖 x=820，但**从茶几顶起跳正好落到厨房台 380**，
      旧判据把台面上 4 件容器全报成 FAIL（实测 `_d_新布局几何.py` + 真机 Luna.update
      跑出来是通的 —— 落点 x=898 y=380）。
      ✅ 正确做法：**跳跃判据要在「全场平台」里找起跳点**，只要
         「起跳台顶 y 与目标层 y 的落差 ≤ JUMP_MAX」**且两者 x 区间有交集或够得着跨度**。
         只有「站上去」这一步才要求覆盖容器 x。
    """
    # ① 站位候选：**必须覆盖容器 x** 的那一层（站上去才能敲）
    stand = [(N.FLOOR_Y, 0, 1280)] + [(py0, px0, px1) for (px0, py0, px1) in plats
                                       if px0 <= x <= px1]
    stand.sort(key=lambda t: t[0])          # y 小 = 位置高（先试高层）
    for (py, px0, px1) in stand:
        if abs(py - y) > REACH_DY:
            continue                        # 这一层站上去也够不到（高度不对）
        how = _can_get_there(py, px0, px1)
        if how:
            return "%s → 沿台面走到 x=%d" % (how, x)
    return None


def _can_get_there(py, tx0, tx1):
    """能不能站到 y=py 这一层（该层 x 区间 = [tx0,tx1]）。返回路径描述或 None。
    ⭐ 起跳点在**全场平台**里找（不要求覆盖目标 x）—— 见 how_to_reach 注释。
    ⭐⭐ 目标区间必须**显式传进来**：第一版我图省事写成模块级 px0_lo/px1_hi 全局，
       结果跨度判定永远拿 0~1280 去比 —— 等于没有跨度约束，会判出
       "从地板横跨 1280px 跳上台子"的假可达。全局变量在测试脚本里也一样是地雷。
    """
    if py >= N.FLOOR_Y - 1:
        return "地板"                         # 就在地板层
    # 梯子 / 攀爬面：只要有一根的顶端 == 这一层的 y
    _lad_all = list(N.LADDERS) + [((z[0] + z[1]) / 2.0, z[2], z[3]) for z in N.LADDER_ZONES]
    for (lx, ltop, lbot) in _lad_all:
        if abs(ltop - py) <= 2.0:
            return "爬梯子 x=%d → 站 y=%d" % (lx, py)
    # ⭐ 跳跃：**全场**平台做起跳点（解包顺序 = (y, x0, x1)，
    #   ⛔ 曾经写成 (qx, qy0, qx1) 结果在拿 x0 比 y，跳跃判定整个是错的）。
    _all = [(N.FLOOR_Y, 0, 1280)] + [(py0, px0, px1) for (px0, py0, px1) in plats]
    for (qy, qx0, qx1) in _all:
        if qy <= py + 1:
            continue                        # 起跳层不比目标层高
        if (qy - py) > JUMP_MAX:
            continue
        # 跨度：起跳区间与**目标层区间**的最近距离 ≤ JUMP_SPAN
        gap = 0.0
        if qx1 < tx0:
            gap = tx0 - qx1
        elif tx1 < qx0:
            gap = qx0 - tx1
        if gap <= JUMP_SPAN:
            return "从 y=%d 跳（落差 %dpx / 跨度 %dpx）→ 站 y=%d" % (qy, qy - py, gap, py)
    return None


# 跳跃跨度：悬空时间 × 水平速度。
# ⭐ 实测口径见 _d_新布局几何.py —— 满跳升 204px 时的横移约 63px。
#   ⛔ 别拿"射程 211px"当跨度，那是**高度**不是水平距离，两者混用会判出跨整屏的假可达。
JUMP_SPAN = 63.0


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
    # 冰箱 —— ⭐ 2026-10-04 改口径：QTE 站位 = **冰箱正前方的地板**。
    #   旧口径是 `N.TABLE_TOP`（站茶几桌面）—— 那是冰箱压在茶几正后方时
    #   被遮挡逼出来的 hack（背景板 v3 实测冰箱 553~735 落在桌布 395~840 内）。
    #   冰箱挪到右墙独立段（1120~1250）后，站地板才是唯一说得通的语义。
    #   ⛔ 判据取 x = 冰箱左沿 - 30（门朝左开，站门前），
    #     ⛔ 不要再用 FRIDGE["x"]+40（旧值是"桌面右半"的产物，冰箱一挪就指错地方）。
    fx = N.FRIDGE["x"] - 30.0
    fr = how_to_reach(fx, N.FLOOR_Y, ladder_x, ladder_top)
    chk("  冰箱      x=%-5d y=%-4d" % (fx, N.FLOOR_Y), fr is not None,
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
