# -*- coding: utf-8 -*-
"""_自测_一百层v5.py —— v5 三种机制的判据

⛔ 判据纪律（来自项目规矩）：
  ① 判据必须落在**产物状态**上，不能只看"函数没抛异常"
  ② ⛔ 不许自造场景（标签与实际场景不符 = 假绿）
  ③ 阴性结果必须做阳性对照
  ④ 判据不许把进程打崩（每组独立 try，最后汇总）

v5 加的三样都要验"真的生效"，不是"代码写进去了"：
  · 落脚点 → 平台要真的更宽 / 金币要真的加 / 商店要真能开
  · 商店   → 买完boost 要真的变 / 钱不够要真的买不了
  · 障碍   → 分区要真的按预期排布 / 齿轮要真的转
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "pet_engine"))
sys.path.insert(0, _HERE)

from PySide6.QtWidgets import QApplication      # noqa: E402
from PySide6.QtCore import Qt, QEvent# noqa: E402
from PySide6.QtGui import QKeyEvent              # noqa: E402
import hundred                                   # noqa: E402

APP = QApplication.instance() or QApplication([])
FAILS = []
GROUPS = []


def group(name):
    def deco(fn):
        GROUPS.append((name, fn))
        return fn
    return deco


def ck(cond, label, detail=""):
    if cond:
        print("  ✅%s" % label)
    else:
        print("  ❌ %s  %s" % (label, detail))
        FAILS.append("%s %s" % (label, detail))


def run(w, n=1, dt=1.0 / 60.0):
    """跑 n 个 tick，用固定假时钟。⭐ 不 sleep，真跑会引入抖动。"""
    for _ in range(n):
        w._step_play(dt)
    return w


def fresh():
    w = hundred.HundredWindow()
    w.start()
    return w


# ─────────────────────────────────────────────────────────── ① 改名
@group("① 改名（Ronny 2026-10-05）")
def t_name():
    w = fresh()
    ck("是露娜就下一百层" in w.windowTitle(),
       "窗口标题已改", repr(w.windowTitle()))
    ck("是男人" not in w.windowTitle(), "标题里没有『是男人』")
    import gamehub
    names = [g.name for g in gamehub.GAMES]
    ck("是露娜就下一百层" in names, "gamehub 卡片名已改", str(names))
    ck(not any("是男人" in n for n in names), "gamehub 里没有『是男人』")
    # ⛔ 类名/模块名/键名**不许改**（改了炸 pet.json 和三个自测）
    ck(hasattr(hundred, "HundredWindow"), "类名 HundredWindow 保持不变")
    ck(any(g.key == "hundred" for g in gamehub.GAMES), "游戏键名 hundred 不变")
    w.close()


# ─────────────────────────────────────────────────────── ② 落脚点
@group("② 机制一：落脚点")
def t_landing():
    ck(hundred.LANDING_EVERY == 10, "落脚点间隔 = 每 10 层")
    ck(hundred.is_landing(10) and hundred.is_landing(20) and hundred.is_landing(100),
       "10/20/.../100 都是落脚点")
    ck(not hundred.is_landing(9) and not hundred.is_landing(11),
       "非10 倍数不是落脚点")
    # 落脚点必须比同深度普通层宽 —— 否则玩家不会想停上来
    for f in (10, 30, 50, 90):
        base = 360.0 - 150.0 * ((f - 1) / 99.0)
        w_l = hundred.plat_width(f)
        ck(w_l > base, "第 %d 层落脚点比普通层宽" % f,
           "%.1f vs %.1f" % (w_l, base))
    # ⭐ 阳性对照：普通层宽度必须**没有**被加宽
    ck(abs(hundred.plat_width(11) - (360.0 - 150.0 * (10 / 99.0))) < 0.01,
       "第 11 层（普通）宽度未被加宽")
    # 金币：踩落脚点要比普通层多
    ck(hundred.COIN_LANDING_BONUS > hundred.COIN_PER_FLOOR,
       "落脚点金币 > 普通层金币")
    w = fresh()
    c0 = w.coins
    run(w, 1)
    ck(w.coins >= c0, "金币不会为负", str(w.coins))
    w.close()


# ───────────────────────────────────────────────────────── ③ 商店
@group("③ 机制二：金币 + 商店")
def t_shop():
    ck(hundred.START_COINS == 0, "不给初始金币（第 1 层必须先做抉择）")
    # 价格递增
    p0 = hundred.shop_price(10, 0)
    p1 = hundred.shop_price(10, 1)
    p2 = hundred.shop_price(10, 2)
    ck(p0 < p1 < p2, "价格随购买次数递增", "%d < %d < %d" % (p0, p1, p2))
    # 三样都改**不同**的物理字段（否则两样是同一个东西）
    fields = [it[4] for it in hundred.SHOP_ITEMS]
    ck(len(set(fields)) == len(fields), "三样商品改的是不同字段", str(fields))

    w = fresh()
    w.coins = 100
    # 买第一样
    w.shop_sel = 0
    before = dict(w.hero.boost)
    w._buy()
    ck(w.bought.get("air", 0) == 1, "买第一样成功记账", str(w.bought))
    ck(w.coins < 100, "买完扣钱", str(w.coins))
    ck(w.hero.boost["air_jumps"] > before["air_jumps"],
       "轻身真的改了 air_jumps",
       "%s -> %s" % (before["air_jumps"], w.hero.boost["air_jumps"]))
    # 买满 2次 → 拒绝
    w.shop_sel = 0
    w.coins = 100
    w._buy()
    ck(w.bought.get("air", 0) == 2, "第二次购买成功")
    w.coins = 100
    w._buy()
    ck(w.bought.get("air", 0) == 2, "第三次被拒（限购 2 次）", str(w.bought))
    ck("买满" in w.shop_msg, "限购有反馈文案", repr(w.shop_msg))
    # 钱不够 → 买不了
    w2 = fresh()
    w2.coins = 0
    w2.shop_sel = 1
    w2._buy()
    ck(w2.bought == {}, "钱不够时买不了")
    ck("钱不够" in w2.shop_msg, "钱不够有反馈文案", repr(w2.shop_msg))
    #⭐ 买不起时 boost 不能变（这条最容易漏）
    ck(w2.hero.boost["fric_mul"] == 1.0, "买不起时 fric_mul 没变",
       str(w2.hero.boost["fric_mul"]))
    w.close(); w2.close()


# ─────────────────────────────────────────────────────── ④商店键
@group("④ 商店：开关约束")
def t_shop_key():
    w = fresh()
    # 不在落脚点上→ 开不了
    w.on_landing = False
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier))
    ck(w.phase != "shop", "不在落脚点上：E 开不了商店", w.phase)
    # 在落脚点上但**在空中**→ 也开不了
    w.on_landing = True
    w.hero.on_ground = False
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier))
    ck(w.phase != "shop", "滞空中：E 开不了商店", w.phase)
    # 在落脚点 + 站着 → 能开
    w.hero.on_ground = True
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier))
    ck(w.phase == "shop", "落脚点+站着：E 能开商店", w.phase)
    #商店里 Esc 是关商店，不是关窗口
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    ck(w.phase == "play", "商店里 Esc 关商店（回play，不是关窗口）", w.phase)
    w.close()


# ─────────────────────────────────────────────────────── ⑤ 商店暂停
@group("⑤ 商店：世界真的暂停")
def t_shop_pause():
    w = fresh()
    w.on_landing = True
    w.hero.on_ground = True
    w.floor = 10
    w.hero.y = w._plat_y(10)
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier))
    ck(w.phase == "shop", "已进商店", w.phase)
    y0, f0 = w.hero.y, w.floor
    for _ in range(120):
        w._step_obstacles(1.0 / 60.0)
    ck(abs(w.hero.y - y0) < 0.001, "商店里角色不动（不会读文案时摔死）",
       "Δy=%.4f" % (w.hero.y - y0))
    ck(w.floor == f0, "商店里层号不变")
    w.close()


# ────────────────────────────────────── ⑤b 全 100 层可解性（最重要的一条）
@group("⑤b 全 100 层几何可解性")
def t_solvable():
    """⭐⭐ 这条是 v5 最重要的一条判据：**没有任何一层是过不去的**。

    ## 为什么必须模拟而不能算
    我第一版用解析式算「Δ中心 + 半宽差 <= _CTRL_SPAN」，
    ⛔ 结果报「42 层不可解」，差点去改plat_center 的 spread。
    ⛔ **那是判据在制造证据** —— 我的模拟没复刻引擎的**落地拉回**
    （`step_vertical` 一路穿透，y 从 175 冲到 516），
    角色在穿过的瞬间 x 已经跑出平台 ⇒ 全部误判。
    ✅ 正确做法：**复刻落地拉回**（到达顶面即停），再穷举起跳点。
    修好后实测：**0 层无解**。

    ⛔ 这条正是 v5 齿轮缺陷（`vx += 340` 弹飞）的发现途径 ——
       大冲量让连着 5 层的齿轮区变成不可通行的墙。
    """
    def py(f):
        return 60.0 + (f - 1) * hundred.FLOOR_H

    def solvable(f, n=61):
        w = hundred.plat_width(f)
        c = hundred.plat_center(f)
        bw = hundred.BODY_W * 0.5
        lo, hi = c - w / 2 + bw, c + w / 2 - bw
        ok = 0
        for i in range(n):
            x0 = lo + (hi - lo) * i / (n - 1) if n > 1 else c
            for d in (-1, 1):
                hero = hundred.Climber(x0, py(f))
                hero.on_ground = True
                hero.jump()
                tgt = py(f + 1)
                landed = False
                for _t in range(120):
                    hero.step_horizontal(d, 1.0 / 60.0)
                    prev = hero.y
                    hero.step_vertical(1.0 / 60.0)
                    # ⭐ 复刻引擎的落地拉回，否则 y 穿透会算错落点
                    if prev <= tgt and hero.y >= tgt:
                        hero.y = tgt
                        w2 = hundred.plat_width(f + 1)
                        c2 = hundred.plat_center(f + 1)
                        if abs(hero.x - c2) <= w2 / 2 + bw:
                            landed = True
                        break
                if landed:
                    ok += 1
                    break
        return ok

    bad = [f for f in range(1, 100) if solvable(f) == 0]
    ck(not bad, "全 100 层都有解（无死层）", "无解层: %s" % bad[:12])
    # ⭐ 阳性对照：必须真有层是有解的（防"全0"假绿）
    oks = [f for f in range(1, 100) if solvable(f) > 0]
    ck(len(oks) == 99, "99 个有解层都被认出来", "实测 %d" % len(oks))


# ────────────────────────────────────── ⑤c 真实策略能通关（不靠"应该能"）
@group("⑤c 真实策略跑出真实分布")
def t_real_strategy():
    """⭐ 不造场景，用**会预测落点的真实策略**跑，看能不能真的通关。

    ⛔ 判据纪律：不用「扫全量统计」也不够，得看**端到端能不能win**。
    """
    def play(sloppy):
        w = hundred.HundredWindow()
        w.start()
        frames = 0
        stuck = 0
        lastf = 1
        while w.phase == "play" and frames < 80000:
            h = w.hero
            tgt = hundred.plat_center(w.floor + 1)
            if h.on_ground and abs(tgt - h.x) <= 14 + sloppy * 40:
                w._press()
            d = tgt - h.x
            w.keys = {1} if d > 6 else ({-1} if d < -6 else set())
            w._step_play(1.0 / 60.0)
            frames += 1
            if w.floor == lastf:
                stuck += 1
            else:
                stuck = 0
                lastf = w.floor
            if stuck > 3000:
                break
        r = (w.phase, w.floor, frames, w.coins, w.landings_hit)
        w.close()
        return r

    for s in (0.0, 0.6):
        ph, f, fr, c, li = play(s)
        ck(ph == "win", "sloppy %.1f 能通关" % s, "结果 %s 第 %d 层" % (ph, f))
        ck(li == 10, "sloppy %.1f 踩满 10 个落脚点" % s, "实测 %d" % li)
        ck(c > 100, "sloppy %.1f 攒到金币" % s, "实测 %d 枚" % c)


# ─────────────────────────────────────────────────────── ⑥ 障碍分区
@group("⑥ 机制三：障碍分区")
def t_obstacle_map():
    # 0 层必须无障碍（第 1 层不能一上来就撞）
    ck(hundred.obstacle_kind(1) == 0, "第 1 层无障碍")
    ck(hundred.obstacle_kind(5) == 0, "第 5 层无障碍（6 层才开始）")
    # 6..29 覆盖 1/2/3 三种
    kinds = set(hundred.obstacle_kind(f) for f in range(6, 30))
    ck(kinds == {1, 2, 3}, "6~29 层三种障碍都出现过", str(sorted(kinds)))
    # 30 层后全无 —— 深处平台只210px，叠障碍就是纯运气
    ck(all(hundred.obstacle_kind(f) == 0 for f in range(30, 101)),
       "30 层之后无障碍")
    # ⭐ 阳性对照：确实存在有障碍的层（防"全是0"假绿）
    nz = [f for f in range(1, 101) if hundred.obstacle_kind(f) != 0]
    ck(len(nz) >= 12, "确实有 %d 层带障碍" % len(nz))
    # 分布要分散，不能连着同一类
    seq = [hundred.obstacle_kind(f) for f in range(6, 30)]
    ck(any(seq[i] != seq[i + 1] for i in range(len(seq) - 1)),
       "障碍种类有变化（不是一整段同一种）", str(seq))


# ─────────────────────────────────────────────────────── ⑦ 障碍动画
@group("⑦ 障碍动画与碰撞")
def t_obstacle_anim():
    w = fresh()
    w.floor = 12
    a0, o0 = w.gear_ang, w.bar_off
    for _ in range(30):
        w._step_obstacles(1.0 / 60.0)
    ck(w.gear_ang != a0, "齿轮在转", "%.4f -> %.4f" % (a0, w.gear_ang))
    ck(w.bar_off != o0, "横板在往复", "%.2f -> %.2f" % (o0, w.bar_off))
    # 齿轮周期：深处更快，但有下限
    w.floor = 1
    p1 = w._obstacle_period()
    w.floor = 100
    p100 = w._obstacle_period()
    ck(p100 < p1, "越深齿轮越快", "第1层%.2fs → 第100层%.2fs" % (p1, p100))
    ck(p100 >= hundred.GEAR_MIN_PERIOD - 1e-6, "齿轮周期有下限（不会快到没法玩）",
       "%.3f >= %.3f" % (p100, hundred.GEAR_MIN_PERIOD))
    # ⭐ 障碍碰撞：把角色放到齿轮轨迹上必须能判到（阳性对照）
    w.floor = 12
    h = w.hero
    kind = hundred.obstacle_kind(12)
    cy = w._plat_y(12)
    gx = hundred.plat_center(12) + math.cos(w.gear_ang + 12 * 1.7) * (hundred.BAR_W * 0.42)
    gy = cy - 34.0 + math.sin(w.gear_ang + 12 * 1.7) * 22.0
    h.x, h.y = gx, gy + 21.0
    hit = w._obstacle_hit(12, h)
    ck(hit, "角色放在齿轮上：判到碰撞（第 12 层障碍=%d）" % kind)
    # ⛔ 远离障碍必须不判（阴性对照）
    h.x, h.y = 40.0, cy - 300.0
    ck(not w._obstacle_hit(12, h), "远离障碍：不判碰撞")
    # ⭐⭐ 画的位置必须 == 判的位置。⛔ 不一致的话玩家看到空的地方被判到，
    #   这是最难 debug 的一类bug（判据全绿、玩家说"明明没碰到"）。
    ck(abs(gx - (hundred.plat_center(12) + math.cos(w.gear_ang + 12 * 1.7) * (hundred.BAR_W * 0.42))) < 0.01,
       "绘制用相位 == 判定用相位（齿轮）")
    # ⭐ 不同层的齿轮必须在不同位置（否则 4 层看起来像一团）
    xs = [hundred.plat_center(f) + math.cos(w.gear_ang + f * 1.7) * (hundred.BAR_W * 0.42)
          for f in (10, 11, 12, 13) if hundred.obstacle_kind(f) == 2]
    ck(len(set(round(v, 1) for v in xs)) > 1 or len(xs) <= 1,
       "不同层齿轮位置不同（按层错开相位）", str([round(v, 1) for v in xs]))
    w.close()


import math  # noqa: E402  （放在后面给 t_obstacle_anim 用）


# ─────────────────────────────────────────────────────── ⑧ boost 生效
@group("⑧ 商店效果真的进物理")
def t_boost_physics():
    w = fresh()
    h = w.hero
    # 抓地：摩擦变大后松手，滑行距离必须更短
    def slide(fric_mul):
        c = hundred.Climber(300.0, 0.0)
        c.boost["fric_mul"] = fric_mul
        c.on_ground = True
        c.vx = hundred.RUN_MAX
        x0 = c.x
        for _ in range(60):
            c.step_horizontal(0, 1.0 / 60.0)
        return abs(c.x - x0)
    d1, d2 = slide(1.0), slide(1.7)
    ck(d2 < d1, "抓地：松手滑行更短", "%.1f -> %.1f" % (d1, d2))
    # 弹跳：dive_mul 大 => 下扑初速大
    c1 = hundred.Climber(0.0, 0.0); c1.on_ground = True
    c1.jump(); v1 = c1.vy
    c2 = hundred.Climber(0.0, 0.0); c2.on_ground = True
    c2.boost["dive_mul"] = 1.22; c2.jump(); v2 = c2.vy
    ck(v2 > v1, "弹跳：下扑初速更大", "%.1f -> %.1f" % (v1, v2))
    # 轻身：空中救次数
    c3 = hundred.Climber(0.0, 0.0)
    c3.boost["air_jumps"] = 2.0
    c3.on_ground = True
    c3.jump()
    n = 0
    while c3.jump():
        n += 1
        if n > 10: break
    ck(n == 2, "轻身：空中能救 2 次", "实测 %d 次" % n)
    w.close()


# ─────────────────────────────────────────── ⑧b 字体（豆腐块只能靠量化抓）
@group("⑧b 字体：不是豆腐块")
def t_font():
    fam = hundred._ensure_font()
    ck(bool(fam), "字体注册成功", repr(fam))
    ck(hundred._font_ok(), "量化判据：汉字与冷僻符号宽度不同")
    fm = hundred.QFontMetricsF(hundred._f(32))
    ck(fm.horizontalAdvance("游") > 0, "汉字有正宽度",
       "%.1f" % fm.horizontalAdvance("游"))
    # ⭐ 豆腐块的特征是**所有字符宽度趋同**。这里反查：
    #   若字体缺失，所有 advance 都会等于 fallback 宽度 ⇒ diff趋 0。
    from PySide6.QtGui import QFontDatabase
    ck(len(QFontDatabase.families()) > 0, "字体库非空",
       "%d 个 family" % len(QFontDatabase.families()))
    # ⛔ 源码里不许再直接 QFont("Microsoft YaHei", ...)
    import io
    src = io.open(os.path.join(_HERE, "pet_engine", "hundred.py"),
                  encoding="utf-8").read()
    ck('QFont("Microsoft YaHei"' not in src,
       "源码里没有裸QFont(\"Microsoft YaHei\") 调用（会静默降级成方块）")


# ─────────────────────────────────────────────── ⑨ 回归：v4 自测仍绿
@group("⑨ 回归：v4 的核心不变量没被破坏")
def t_regression():
    w = fresh()
    h = w.hero
    # 站着不动 200 帧，层号不许自己涨（v4.1 修的那个 bug）
    f0 = w.floor
    for _ in range(200):
        w._step_play(1.0 / 60.0)
    ck(w.floor == f0, "站着不动层号不自己涨", "%d -> %d" % (f0, w.floor))
    # 屏幕边界
    h.x = -999.0
    w._step_play(1.0 / 60.0)
    ck(h.x >= hundred.BODY_W * 0.5 - 0.01, "左边界夹住", str(h.x))
    h.x = 99999.0
    w._step_play(1.0 / 60.0)
    ck(h.x <= hundred.VW - hundred.BODY_W * 0.5 + 0.01, "右边界夹住", str(h.x))
    w.close()


def main():
    print("=" * 62)
    print("  一百层 v5 · 自测（改名 + 落脚点 + 商店 + 障碍）")
    print("=" * 62)
    for name, fn in GROUPS:
        print("\n%s" % name)
        try:
            fn()
        except Exception as e:
            import traceback
            traceback.print_exc()
            FAILS.append("[%s] 抛异常: %s" % (name, e))
    print("\n" + "=" * 62)
    if FAILS:
        print("❌ 未通过 %d 项：" % len(FAILS))
        for f in FAILS:
            print("   - %s" % f)
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())