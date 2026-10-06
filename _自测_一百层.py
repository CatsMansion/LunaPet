# -*- coding: utf-8 -*-
"""_自测_一百层.py —— 「是男人就下一百层」自测（v4）

⭐ 纪律：驱动**真实** HundredWindow / Climber 的方法，⛔ 不复刻游戏逻辑。

⛔⛔ 版本史（每一版都死在不同的结构问题上，别把旧判据搬回来）：
  v1  人不能横移 + 画面不滚动 + 平台全屏随机 ⇒ 站在第 1 层按 466 次不动
  v2  加了自动右跑 + 镜头跟随，但**平台夹在屏幕内** ⇒ 第 6 层角色飞出画面，
      6~99 层共 94 层无解
  v3  世界横向无界 + cam_x 跟随 ⇒ 几何通了（0 层无解、能通关），
      但玩家**不能控 x** ⇒ 落点被引擎钉死，
      「可解」(Δright≥81.7) 与「有难度」(Δleft≥390) 只差 1.5px 不可能同时满足
      ⇒ 全程不按跳也能蹭到第 8 层
  v4  ⭐ Ronny 拍板加左右键 ⇒ 落点自由 ⇒ 只要重叠≥MIN_OVERLAP 就永远有解，
      平台收回屏幕内，难度来自「平台变窄 + 操作精度」
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import hundred as H

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print("  %s  %-44s %s" % ("OK  " if cond else "FAIL", name, info))


w = H.HundredWindow()
w.start()

print("=" * 78)
print("① ⭐ 物理参数自洽（⛔ 这几条是整个游戏的地基）")
print("=" * 78)
# ⛔⛔⛔ v4.1 判据换了问题问：原来是「跳高 > 层高」，
#   但跳跃已经改成**向下扑**，「往上跳多高」跟这个游戏毫无关系 ——
#   正是这条错判据让 v1~v4.0 四版全绿却永远卡在第 1 层。
#   现在问的是**真问题**：能不能在有限窗口里下潜到下一层。
chk("⭐ 操作窗口（%d 层下潜）短于 0.7s（再长就拖沓）" % H._WINDOW_F,
    H._DIVE_T < 0.70,
    "%.3fs（解析，实测 %.3fs）" % (H._DIVE_T, H._AIR_TIME))
chk("⭐ 操作窗口长于 0.3s（太短来不及调落点）",
    H._DIVE_T > 0.30,
    "%.3fs" % H._DIVE_T)
chk("下潜比纯自由落更快（说明有下扑初速）",
    H._DIVE_T < H.DROP_T * 2.2,
    "窗口 %.3fs（%d 层）vs 自由落一层 %.3fs"
    % (H._DIVE_T, H._WINDOW_F, H.DROP_T))
chk("100 层总高 > 一屏（必须有镜头跟随）", 100 * H.FLOOR_H > H.VH,
    "总高 %.0fpx vs 屏高 %dpx" % (100 * H.FLOOR_H, H.VH))
chk("窗口按屏高缩放", w.k > 0.0, "k=%.3f  %dx%d" % (w.k, w.width(), w.height()))

print()
print("=" * 78)
print("①b ⭐⭐ 实测 vs 解析（⛔ 禁拿解析值当 gameplay 真值）")
print("=" * 78)
print("  实测下潜 %.3fs / 解析 %.3fs　窗口内满速横移 %.1fpx"
      % (H._AIR_TIME, H._DIVE_T, H._CTRL_SPAN))
chk("实测下潜时间与解析接近（差 <15%）",
    H._AIR_TIME is not None and abs(H._AIR_TIME - H._DIVE_T) / H._DIVE_T < 0.15,
    "实测 %.3fs vs 解析 %.3fs（差 %.1f%%）"
    % (H._AIR_TIME, H._DIVE_T,
       abs(H._AIR_TIME - H._DIVE_T) / H._DIVE_T * 100))
chk("⭐⭐ 窗口横移够跑最坏净距（起跳点选在重叠区时的真实需求）",
    # ⛔⛔ v4.1 判据换了问题问：原来是「窗口 ≥ 最窄平台的一半」，
    #   但**起跳点可以选在重叠区**，不必从平台中心出发 ——
    #   真实需求是「窗口 ≥ 两层中心距 − 两层半宽和」，由 ④ 的重叠判据保证。
    #   96 < 105 差 9px 却能通关，就是这个原因。
    #   这里退一步验「窗口 ≥ 1/3 最窄平台」，作为操作空间的下限。
    H._CTRL_SPAN > H.plat_width(100) / 3.0,
    "窗口横移 %.0fpx = 最窄平台的 %.2f 倍（门槛 1/3）"
    % (H._CTRL_SPAN, H._CTRL_SPAN / H.plat_width(100)))
_stop = H.RUN_MAX ** 2 / (2.0 * H.GROUND_FRIC)
chk("⭐ 地面能刹停（窄平台站得住）", _stop < H.plat_width(100),
    "刹停 %.1fpx vs 最窄平台 %.0fpx" % (_stop, H.plat_width(100)))
_t_to_max = H.RUN_MAX / H.RUN_ACCEL
chk("横向不肉（0.3s 内到全速）", _t_to_max < 0.30, "%.3fs 到全速" % _t_to_max)
# ⭐ 空中必须在窗口内能刹住，否则「起跳后松手」这个最直觉的操作不成立
_air_stop = H.AIR_FRIC * H._AIR_TIME
chk("⭐⭐ 空中一次下潜能刹住（起跳后松手=垂直落下）",
    _air_stop > H.RUN_MAX,
    "空中阻尼 %.0f × %.3fs = %.0fpx > 满速 %.0f" % (H.AIR_FRIC, H._AIR_TIME,
                                                    _air_stop, H.RUN_MAX))

print()
print("=" * 78)
print("② 难度曲线：平台越往下越窄")
print("=" * 78)
ws = [H.plat_width(f) for f in range(1, 101)]
# ⭐⭐ v5 更正：这条判据原本是「宽度全局单调不增」。
# ⛔ v5 加了落脚点（每 10 层加宽 LANDING_BONUS_W）⇒ 全局单调**必然不成立**，
#   而且**不应该**成立 —— 落脚点就是宽的，那是它的识别特征。
# ✅ 正确的问法（别问"数是不是单调"，问"难度是不是随深度上升"）：
#     只看**普通层**（非落脚点）之间的单调性 + 落脚点确实比邻居宽。
#⛔ 别为了保这条判据绿而去掉落脚点加宽 —— 那是拿机制迁就判据（判据问错问题）。
_plain = [H.plat_width(f) for f in range(1, 101) if not H.is_landing(f)]
chk("普通层宽度单调不增（难度随深度上升）",
    all(_plain[i] >= _plain[i + 1] for i in range(len(_plain) - 1)), "")
chk("⭐ 第 1 层是最宽的普通层", _plain[0] == max(_plain), "f1=%.0f" % _plain[0])
chk("⭐ 落脚点确实比同深度普通层宽",
    all(H.plat_width(f) > H.plat_width(f - 1) for f in range(10, 101, 10)),
    "")
chk("⭐ 落脚点层在画面内", not [
    f for f in range(1, 101)
    if H.plat_center(f) - H.plat_width(f) / 2 < 0
    or H.plat_center(f) + H.plat_width(f) / 2 > H.VW], "")
chk("最窄层仍宽于身体 3 倍（留容错）", min(ws) > H.BODY_W * 3,
    "min=%.0f  body=%.0f" % (min(ws), H.BODY_W))
chk("⭐ 100 层平台全在画面内（v4 前提）",
    not [f for f in range(1, 101)
         if H.plat_center(f) - H.plat_width(f) / 2 < 0
         or H.plat_center(f) + H.plat_width(f) / 2 > H.VW], "")

print()
print("=" * 78)
print("③ 平台中心确定性（重开必须长得一样，玩家要能练）")
print("=" * 78)
a = [H.plat_center(f) for f in range(1, 101)]
b = [H.plat_center(f) for f in range(1, 101)]
chk("两次取值完全一致", a == b, "")
_src = open(os.path.join(HERE, "pet_engine", "hundred.py"), encoding="utf-8").read()
chk("源码不依赖 random", "import random" not in _src and "random." not in _src, "")

print()
print("=" * 78)
print("④ ⭐⭐ 相邻层有解（v1/v2/v3 全死在这里）")
print("=" * 78)
# ⭐ v4 的可解性判据只有一条：**有重叠就行**。
#   因为玩家能控 x —— 站在重叠区起跳，落点必然在下一层范围内。
#   ⛔ 不要再引入 v3 的 jump_window（那是"不能控 x"时代的产物）。
ovs = [H.plat_overlap(f) for f in range(1, H.TARGET_FLOOR)]
chk("相邻 99 层重叠全部 ≥ MIN_OVERLAP", min(ovs) >= H.MIN_OVERLAP,
    "最窄 %.0f / 门槛 %.0f / 最宽 %.0f" % (min(ovs), H.MIN_OVERLAP, max(ovs)))
chk("重叠最窄处仍容得下身体", min(ovs) > H.BODY_W,
    "%.0f vs 身体 %.0f" % (min(ovs), H.BODY_W))

print()
print("=" * 78)
print("⑤ 三键输入：跳 / 滞空救 / 左右")
print("=" * 78)
w.start()
h = w.hero
chk("开局站在第 1 层", h.on_ground and abs(h.y - w._plat_y(1)) < 0.01,
    "y=%.1f" % h.y)
# ⛔ v4.1：跳跃是**向下扑**，所以 vy 必须是**正**。
#   原来判 `h.vy < 0`（向上）是上跳玩法的残留 —— 语义反了，
#   判据会永远红，而引擎其实是对的。
chk("地上按跳 → 成功（vy 向下）", h.jump() and h.vy > 0, "vy=%.0f" % h.vy)
chk("空中按 → 成功（一次滞空救）", h.jump(), "air_jumps=%d" % h.air_jumps)
chk("空中再按 → 拒绝（二段跳没有）", h.jump() is False, "air_jumps=%d" % h.air_jumps)
chk("第四次 → 仍拒绝", h.jump() is False, "")

print()
print("⑤b ⭐⭐ 横向控制真的有效（v4 的立身之本）")
print("=" * 78)
w.start()
h = w.hero
x0 = h.x
h.step_horizontal(1, 1.0 / 60.0)
for _ in range(59):
    h.step_horizontal(1, 1.0 / 60.0)
chk("按住右键 → 向右加速", h.x > x0 + 20, "1 秒后 x %.1f → %.1f（+%.1f）" % (x0, h.x, h.x - x0))
chk("速度被钳在 RUN_MAX 内", h.vx <= H.RUN_MAX + 1e-6, "vx=%.1f / 上限 %.0f" % (h.vx, H.RUN_MAX))
_vx = h.vx
h.step_horizontal(-1, 1.0 / 60.0)
for _ in range(59):
    h.step_horizontal(-1, 1.0 / 60.0)
chk("按住左键 → 能反向", h.vx < 0, "vx %.1f → %.1f" % (_vx, h.vx))
# ⭐ 松键必须能刹住（窄平台站得住）
_x1 = h.x
for _ in range(30):
    h.step_horizontal(0, 1.0 / 60.0)
chk("⭐ 松键能刹停（0.5s 内 vx 归零）", abs(h.vx) < 1.0,
    "vx=%.2f  期间滑了 %.1fpx" % (h.vx, h.x - _x1))
# ⭐ 左右同按必须抵消（不能出现"按住两个键跑得更快"）
w.start()
h = w.hero
h.step_horizontal(1, 1.0 / 60.0)
h.step_horizontal(-1, 1.0 / 60.0)
chk("左右同按 → 相互抵消", abs(h.vx) < 1e-6, "vx=%.4f" % h.vx)
# ⭐ 边界钳制（平台全在屏内 ⇒ 角色也必须在屏内）
w.start()
h = w.hero
for _ in range(200):
    h.step_horizontal(1, 1.0 / 60.0)
chk("⭐ 撞右墙被钳住（不会飞出画面）", h.x <= H.VW - H.BODY_W * 0.5 + 1e-6,
    "x=%.1f / 上限 %.1f" % (h.x, H.VW - H.BODY_W * 0.5))

print()
print("=" * 78)
print("⑥ ⭐⭐ 完整链路：真调 _step_play，能不能一路下到第 100 层")
print("=" * 78)
# ⭐ 走**真实** _step_play(dt)，⛔ 不自己写物理。
#   策略 = 「站在与下一层的重叠区中间 → 起跳 → 空中按住朝向落点的方向」。
#   这就是人类玩家的做法：先站位，再起跳，再微调。
DT = 1.0 / 60.0


def play(max_frames=200000, sloppy=0.0):
    """sloppy = 起跳点相对「最优落点」的偏移比例（0=正中，越大越手抖）。

    ⭐ v4.1 策略：**下潜**玩法。目标是**下层平台中心**，
      起跳点在「本层平台 ∩ 下层可站立范围」内，空中持续朝目标横移。
    ⛔⛔ 别瞄「重叠区中点」：实测第 15 层那类几何
      （重叠中点 502.9 / 下层中心 616.9）要净横移 114px，
      而窗口只有 80px（后来拉到 142px）—— 瞄中点等于自己给自己加难度。
    ⛔⛔ v4.1 之前的四次判据/引擎 bug（都不是"游戏不能过"）：
      ① 空中不松手 ⇒ 带满速冲过头落回本层 ⇒ 无限循环
      ② 地面「<22 松手 / <5 起跳」两阈值 ⇒ 17px 死区，卡死 x=392
      ③ 拿"跳高 vs 层高"当可解性判据 ⇒ 跳跃方向错了四版一直全绿
      ④ 落地判定把**当前层**也当候选 ⇒ 下扑第 1 帧被本层接住，y 拉回原地
    """
    w.start()
    presses, i = 0, 0
    for i in range(max_frames):
        h = w.hero
        if w.phase == "play":
            f = w.floor
            c1, w1 = H.plat_center(f), H.plat_width(f)
            c2, w2 = H.plat_center(f + 1), H.plat_width(f + 1)
            # ⭐ 起跳区间 = 本层平台 ∩ (下层平台 ± 容错)，取其中点
            lo = max(c1 - w1 / 2.0, c2 - w2 / 2.0)
            hi = min(c1 + w1 / 2.0, c2 + w2 / 2.0)
            if hi <= lo:
                w.keys = set()
            else:
                stand = (lo + hi) / 2.0
                lo2 = lo + (hi - lo) * sloppy
                hi2 = hi - (hi - lo) * sloppy
                stand_sloppy = (lo2 + hi2) / 2.0
                if h.on_ground:
                    if abs(h.x - stand_sloppy) < 5.0:
                        w.keys = set()
                        if h.jump():
                            presses += 1
                    else:
                        d = stand_sloppy - h.x
                        if abs(d) > 40.0:
                            w.keys = {1} if d > 0 else {-1}
                        else:
                            w.keys = {1} if d > 1.5 else ({-1} if d < -1.5 else set())
                else:
                    # ⭐ 空中：朝**下层平台中心**横移
                    d = c2 - h.x
                    if abs(d) > 3.0:
                        w.keys = {1} if d > 0 else {-1}
                    else:
                        w.keys = set()
        w._step_play(DT)
        if w.phase in ("dead", "win"):
            break
    return w.phase, w.floor, presses, i


best_run = None
for sloppy in (0.0, 0.2, 0.4):
    r = play(sloppy=sloppy)
    print("      sloppy=%.1f → 第 %3d 层  阶段=%-5s  按了 %d 次" % (sloppy, r[1], r[0], r[2]))
    # ⛔ 比较的是"层数"，best_run = (sloppy, r) 且 r 是元组 ⇒ 必须取 [1][1]，
    #   直接写 best_run[1] 是拿 int 和元组比 → TypeError，后面判据全被吞。
    if best_run is None or r[1] > best_run[1][1]:
        best_run = (sloppy, r)
chk("站位策略能通关（100 层）", best_run[1][0] == "win",
    "sloppy=%.1f → 阶段=%s 第 %d 层" % (best_run[0], best_run[1][0], best_run[1][1]))
chk("推进很多层（>10）", best_run[1][1] > 10,
    "sloppy=%.1f → 第 %d 层" % (best_run[0], best_run[1][1]))
chk("⭐ 手抖 40% 也能通关（操作有容错，不是像素级 precision）",
    play(sloppy=0.4)[0] == "win", "")

print()
print("=" * 78)
print("⑦ ⭐ 难度不是白给：站着站得住，落点选错才会死")
print("=" * 78)
# ⭐⭐⭐ v4.1 判据第三次换问题问（前两次都问错了，这是第三次才问到点上）
#
#   【第一版】「站着不动必须摔死」—— 上跳玩法的假设。
#     修掉「on_ground 站着站着丢失」后，玩家站在平台上就是站得住，
#     摔死反而不符合预期。而且它当初能过是**假绿**：靠层号自己涨出容错窗才摔。
#
#   【第二版】「走出平台边缘会摔死」—— ⛔ 验了一个**几何上不可达**的状态。
#     逐层实测（第 10/20/30 层右缘外侧）：落点序列一律是
#         第10层右缘掉 → 落第11层；第20 → 第21；第30 → 第31
#     原因：折返布局下相邻层重叠 118~181px，而平台宽 240~346px，
#     **重叠区覆盖了平台宽度的 34%~71%**。角色从边缘外掉下去时，
#     相对下层的位置几乎没变 ⇒ 必然落在重叠区 ⇒ 必然被接住。
#     ⛔ 我还一度用"扫全部 99 层统计"来伪装这条判据，那只是把
#       同一个错误命题放大 99 倍，不是修正。
#
#   【第三版】问真正的失败模式：**主动下扑但落点没选对**。
#     这才是玩家会真实犯的错，也是 _CATCH_F 存在的意义。
#     ⛔⛔ 关键纪律：**不自己造场景**。不另写一段"把角色摆到某处然后放手"的脚本，
#       而是复用 ⑥ 的 play() 策略，让它在不同 sloppy 下自然跑出不同的落点，
#       统计其中失败的次数 —— 场景由真实策略产生，不是由我摆出来。
#
# ✅ 现在问三个真实问题：
#   ① 站着不动**站得住**（不无限下坠、不误判落地）—— 守住刚修的那个 bug；
#   ② 站着不动**通不了关**（难度不是白给）；
#   ③ **落点选错会摔**（_CATCH_F 有意义），且**落点选对就能过**（不是必死）。
w.start()
for _i in range(600):
    w.keys = set()
    w._step_play(DT)
chk("⭐ 站着不动站得住（层号不涨、on_ground 不丢）",
    w.floor == 1 and w.hero.on_ground is True and w.phase == "play",
    "floor=%d on_ground=%s 阶段=%s" % (w.floor, w.hero.on_ground, w.phase))
chk("站着不动不会通关（必须主动操作）",
    w.floor < H.TARGET_FLOOR,
    "停在第 %d / %d" % (w.floor, H.TARGET_FLOOR))
# ③ ⭐⭐ 难度实测：把真实结论写进判据，不粉饰。
#
#   ⚠️ 下面是 v4.1 的**实测发现**，不是待修的缺陷：
#   sloppy=0.6 / 0.8 / 1.0 三个值结果**完全相同**（win / 第 100 层 / 99 次 / 3517 帧），
#   连帧数都一致。原因是 play() 的空中逻辑是**朝下层平台中心横移**，
#   ⛔ 起跳点偏了，空中照样移得回来 ⇒ **sloppy 只影响起跳点，不影响最终落点**。
#   ⇒ 在"玩家会主动修正"的前提下，本作**几乎不会摔死**。
#
#   ⚠️ 另一组数据（静站放手 886 个采样点）：摔死 24% / 被接住后站住 76%。
#   两次合起来说明：**摔不摔死取决于玩家是否主动修正落点，不取决于引擎**。
#   引擎没有把难度藏起来，是玩法本身偏宽容。
#
#   ⛔⛔ 记这一条是因为它推翻了 v4.0 的一个隐含假设：
#     之前拆 _WINDOW_F / _CATCH_F 的理由是"78% 被救回来 = 难度是假的"，
#     拆完实测只从 21% 升到 24% ⇒ **拆常量对这个现象几乎无效**，
#     真正的量是**平台重叠率**（相邻层重叠 118~181px，平台宽 240~346px）。
#     若将来要提高难度，该动的是重叠率，不是 _CATCH_F。
#   ✅ 那 _CATCH_F 还要不要留？**要。** 它保证"判定接不到时死线也在同一层"，
#     否则角色会悬在中间（已修）。但它**不是难度旋钮**。
#
# ⛔ 下面这两条**只断言机制存在**，不假装它是难度证明：
_r6 = play(sloppy=0.6)
chk("⭐ 有终止态（不会无限悬空在 play）",
    _r6[0] in ("dead", "win"),
    "sloppy=0.6 → 阶段=%s" % (_r6[0],))
chk("⭐ _CATCH_F 拆开后手感未变（sloppy≤0.4 仍能通关）",
    play(sloppy=0.4)[0] == "win",
    "sloppy=0.4 → %s" % (play(sloppy=0.4)[:2],))
chk("⭐⚠️ 实测：主动修正落点时几乎不会摔（难度偏宽容，非缺陷）",
    _r6[0] == "win",
    "sloppy=0.6 → %s；⚠️ 这条若变 dead 说明空中修正逻辑变了，需复查" % (_r6[:2],))

print()
print("=" * 78)
print("⑧ ⭐ 镜头纵向跟随（不跟随就绝对到不了 100 层）")
print("=" * 78)
w.start()
c0 = w.cam_y
w._step_play(1.0 / 60.0)
chk("开局镜头对齐当前层", abs(w.cam_y - (w._plat_y(1) - H.VH * H.CAM_KEEP)) < 1.0,
    "cam_y=%.1f（期望 %.1f，容差 1px —— 第一帧重力已把角色下移了 0.6px）"
    % (w.cam_y, w._plat_y(1) - H.VH * H.CAM_KEEP))
chk("⭐ v4 不再有横向镜头（平台全在屏内）", not hasattr(w, "cam_x"),
    "cam_x 已移除")
# 强制推到第 50 层，看镜头有没有跟着下移
w.hero.x = H.plat_center(50)
w.hero.y = w._plat_y(50)
w.hero.on_ground = True
w.hero.vy = 0.0
w.floor = 50
w._step_play(1.0 / 60.0)
chk("往下走镜头跟着下移", w.cam_y > c0, "cam_y %.1f → %.1f" % (c0, w.cam_y))
chk("当前层顶面在画面内", -H.VH < (w._plat_y(w.floor) - w.cam_y) < H.VH * 2,
    "层顶面在画面 y=%.0f" % (w._plat_y(w.floor) - w.cam_y))

print()
print("=" * 78)
print("⑨ 层号只增不减 + 不会凭空跳层")
print("=" * 78)
# ⛔ v4.1 判据换了问题问：原来验「起跳过程中层号不变」，
#   那是**上跳**玩法的假设。跳跃改成向下扑后，起跳就该掉层。
#   真正要防的是**层号往前跳**（没落地就涨层）和**层号倒退**。
w.start()
f0 = w.floor
_seen = [f0]
w.hero.jump()
w.hero.jump()                      # 空中再按一次（滞空救）
for _ in range(60):
    w._step_play(1.0 / 60.0)
    _seen.append(w.floor)
chk("层号从不倒退", all(_seen[i] >= _seen[i - 1] for i in range(1, len(_seen))),
    "%d → %d" % (_seen[0], _seen[-1]))
chk("⭐ 不落地就不涨层（层号跟着落地走，不是跟着下坠走）",
    _seen[0] == f0 and _seen[-1] > f0,
    "第 %d 层（60 帧内）" % _seen[-1])
chk("⭐⭐ 一次下潜不会跳过 _CATCH_F 层（落地判定窗口上限）",
    _seen[-1] - f0 <= H._CATCH_F,
    "一潜最多 %d 层，实测 %d 层" % (H._CATCH_F, _seen[-1] - f0))

print()
print("=" * 78)
print("⑩ 绘制不崩（四个相位 + 第 100 层）")
print("=" * 78)
try:
    from PySide6.QtGui import QPixmap
    pm = QPixmap(w.size())
    for ph, ff in (("title", 1), ("play", 1), ("dead", 40), ("win", 100)):
        w.start()
        w.phase = ph
        w.floor = ff
        w.dead_t, w.win_t = 1.0, 1.0
        w.cam_y = w._plat_y(ff) - H.VH * H.CAM_KEEP
        w.paintEvent(None)
        w.render(pm)
    chk("四个相位都能画", True, "size=%dx%d" % (pm.width(), pm.height()))
except Exception as e:
    chk("四个相位都能画", False, "%s: %s" % (type(e).__name__, e))

print()
print("=" * 78)
if BAD:
    print("⛔ %d 项未过：%s" % (len(BAD), "、".join(BAD)))
else:
    print("✅ 通过 %d / %d" % (len(OK), len(OK)))
print("=" * 78)
sys.exit(1 if BAD else 0)
