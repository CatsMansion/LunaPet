# -*- coding: utf-8 -*-
"""hundred.py —— 「是男人就下一百层」（Ronny 2026-10-05）

=====================================================================
⛔⛔⛔ 本文件是**独立小游戏**，⛔ 不是「深夜厨房」换皮。
   玩法铁律：**素材只管动作，容器/UI/地形由引擎绘制**。
=====================================================================

## ⭐⭐ v4 定稿：加左右键（Ronny 2026-10-05 拍板）

### 为什么必须加左右键 —— 这是量出来的结构冲突，不是偏好问题
v3 单键版（人自动向右跑，玩家只有一个「跳」）实测出**两条要求互相矛盾**：
  · 可解性：相邻层右沿差 Δright ≥ NEXT_DX − FULL_ARC_DX + MIN_WINDOW
              = 96.4 − 78.7 + 64 = **81.7px**
    （下一层右移不够多，起跳窗口就倒挂：要么落回本层原地打转，
      要么落点冲出下一层右沿。v1 实测「按 466 次 floor 纹丝不动」就是这个。）
  · 难度：下一层左沿必须越过「不按跳的落点」
          left_{f+1} > right_f + DROP_DX + 身体半宽
          ⇒ Δleft ≥ 390px（平台**完全不重叠**）
    （否则玩家全程不按键，靠平台重叠也能一路蹭下去。v3 实测蹭到第 8 层不死。）

而 Δleft 与 Δright 只差**半宽变化**（99 层共收窄 150px ⇒ 每层差 1.5px），
所以两个要求**不可能同时满足** —— 差 152~214px，不是调参能补的。

### v4 的解法：把选择权还给玩家
玩家能控 x ⇒ 落点自由 ⇒ 只要相邻层**重叠 ≥ MIN_OVERLAP** 就永远有解。
上面前提全部消失：
  · 平台可以收回屏幕内（不需要无界世界，也不需要横向镜头）
  · 难度来源从「摆平台刁难」换成「操作精度」：
    平台**变窄**（360→210）+ **间距变大**（落点窗口收窄）+ 不能乱按跳

## ✅ v4 的输入（三键）
   ← → / A D  横向加速（有摩擦，能精确停住）
   空格 / ↑ / W / 鼠标    跳（地面起跳 + 一次滞空救）
   R 重开　Esc 退出

## 物理参数（⛔ 横向与纵向都是实测出来的，不是解析值）
   纵向沿用 v3：GRAVITY / JUMP_V 反推自「刚好跳得起一层、且跳得不高不低」。
   横向新增 RUN_ACCEL / RUN_MAX / GROUND_FRICTION ——
   ⭐ 加速度要够大（起手 0.15s 到全速，否则平台间移动太肉），
     摩擦要够大（松键能刹住，否则玩家无法停在窄平台边上）。
"""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (QColor, QPainter, QPen, QBrush, QLinearGradient,
                           QFont, QPolygonF)
from PySide6.QtWidgets import QWidget, QApplication

# ============================================================================
# 逻辑坐标（与 night.py 一致：1280×720，按屏幕高度缩放）
# ============================================================================
VW, VH = 1280, 720

FLOOR_H      = 110.0       # 每层楼板带的垂直间距
TARGET_FLOOR = 100
CAM_KEEP     = 0.34        # 镜头把当前层顶面放在画面 34% 处

# --- 纵向物理（⛔ 改任何一个，自测①「物理参数自洽」会红）---
GRAVITY    = 2000.0
DIVE_V     = 150.0        # ⭐⭐ v4.1：跳跃 = **向下扑**的初速（正值）
                         #   ⛔⛔ 不是往上弹 —— 这是 v1~v4.0 四版全死的根因：
                         #     写 vy = JUMP_V(负) ⇒ 角色 y 从没比脚下更深 ⇒ 层号恒为 1。
                         #   ⭐ 150 的选法（实测标定，别凭感觉改）：
                         #     下潜 1 层(110px)  0.265s
                         #     下潜 2 层(220px)  0.400s
                         #     下潜 3 层(330px)  0.504s  ← 窗口到这（落地判定查三层）
                         #     满速横移 = 240 × 0.504 = 121px = 最窄平台的 0.58 倍
                         #   ⛔ 别调大：520 那版窗口只有 0.15s / 横移 24px，
                         #     玩家来不及调落点（实测策略直接卡死在第 1 层）。
MAX_FALL   = 1250.0
BODY_W     = 32.0
AIR_JUMPS  = 1             # ⭐ 空中还能救几次（=1）
# ⭐ 兼容旧名（外部脚本/自测里若还引用 JUMP_V，指向新的下扑初速）
JUMP_V     = DIVE_V

# --- ⭐ v4 新增：横向物理（玩家可控）---
RUN_ACCEL     = 2200.0     # ⭐ 地面加速度：0.11s 到全速，太肉了平台之间跑不动
AIR_ACCEL     = 1150.0     # ⭐ 空中加速度：地面的 1/1.9 —— 够微调落点，但不会失控
RUN_MAX       = 240.0      # 最高速（比 v3 的 118 快一倍，跨 300px 平台只花 1.25s）
GROUND_FRIC   = 2600.0     # ⭐ 地面摩擦（⛔ 只在**松手**时施加）：刹停距离
                             #   240²/(2*2600) = 11.1px << 最窄平台 210px ⇒ 窄平台也站得住
AIR_FRIC      = 1500.0     # ⭐⭐ 空中阻尼（同样只在松手时）：**必须能在一次滞空内刹住**
                             #   滞空 0.650s，240/(0.650*60) = 每帧要减 6.2px 才刚好归零
                             #   ⛔ v4.1 原来用 380 → 每帧只减 6.3 但**初速是满速 240**
                             #     ⇒ 0.65s 只减到 40，空中滑了 58px 直接飞出重叠区，
                             #     落回本层 → 死循环（自测⑥「按了 3390 次卡在第 1 层」）。
                             #   1500 → 0.65s 内减 585px > 240 ⇒ **一次滞空能完全刹住**，
                             #     玩家「起跳后松手」就能垂直落下，这是最直觉的操作。

# --- 平台布局 ---
MIN_OVERLAP = 96.0         # ⭐ 相邻层最少重叠（3 个身位）。低于此窄平台之间无解
SPREAD_MAX  = 210.0        # ⭐ 第 1 层的偏移余量上限（随层数线性收缩到 MIN_SPREAD）
MIN_SPREAD  = 64.0         # ⭐ 深层余量下限

GROUND_SNAP = 8.0          # ⭐ v4.1：站着不动时允许的下沉容差（px）
                         #   = 一帧重力的最大下沉量 g·dt²。dt 钳在 1/20 ⇒
                         #     2000 × 0.05² = 5.0px，取 8 留余量。
                         #   ⛔ 取 <5 会在掉帧时"站着站着就滑下去"；
                         #     取太大则边缘走出后会被吸回，边缘手感变糊。

# 派生量（⛔ 别在别处重新算）
#
# ⭐⭐⭐ v4.1 拆开的两个窗口：**原本是同一个 `_WINDOW_F=4`，两个用途是冲突的**
#
#   | 用途            | 想要的效果 | 冲突方向 |
#   |-----------------|-----------|---------|
#   | 操作窗口        | 大（横移远、手感宽）| ↑ |
#   | 落地判定范围    | 小（掉下去容易摔）| ↓ |
#
#   共用一个常量 ⇒ 只能选一边。选"手感"的结果（实测 886 个采样点）：
#     摔死 21% / 被救回来并站住 **78%** —— 掉下去几乎总能救，
#     玩起来基本不会输，"难度"是假的。
#   ⛔ 注意这 78% 里有一部分是**假绿来源**：站着不动层号自己涨、
#     涨出容错窗才摔。现在那个 bug 修掉了，摔死率才是真实的 21%。
#
#   ✅ 拆开：手感与判定解耦。
#
# ⚠️ 实测结论（别再当"难度旋钮"用）：拆完摔死率只从 21% → **24%**（886 采样点）。
#   真正决定"摔不摔"的是**平台重叠率**（相邻层重叠 118~181px，平台宽 240~346px），
#   以及**玩家会不会在空中修正落点**（play() 实测 sloppy 0.6/0.8/1.0 结果完全相同
#   ⇒ 空中朝目标横移能自我修正 ⇒ 主动操作的玩家几乎不摔）。
#   ⛔ 要提高难度，该动 `plat_center` 的 spread / 重叠率，不是这两个常量。
_WINDOW_F = 4            # ⭐ **操作窗口** = 空中能横移多远（玩家能救回多少）
                         #   ⛔ 别改小：N=3 只给 0.504s / 121px 横移，
                         #     而实测最坏净横移 114px —— 容错只剩 7px，
                         #     自测⑥ 会在第 15 层摔死。N=4 给 0.583s / 144px（0.69 倍
                         #     最窄平台）⇒ 30px 容错，够 sloppy=0.4 手抖通过。
_CATCH_F  = 2            # ⭐⭐ **落地判定范围** = 掉下去能被哪几层接住
                         #   ✅ 它的作用是**正确性**，不是难度：
                         #     判定接不到时，死线必须也在同一层，
                         #     否则角色会"判定接不到、但还没到死线"地悬在半空。
                         #   ⛔ 与 _WINDOW_F 拆开是必要的：两者相等时
                         #     空中修正与落点判定耦合，改手感就会连带改死亡线。
_CATCH_Y   = 0.55        # 落在 _CATCH_F 层顶面之下这么多个层高才判死
                         #   （给最后一级容错，别让擦边坠落算摔）
_DIVE_T   = (-DIVE_V + (DIVE_V * DIVE_V + 2.0 * GRAVITY * FLOOR_H * _WINDOW_F) ** 0.5) / GRAVITY
                         # ⭐ 下潜 _WINDOW_F 层的下落时间（解析）
_AIR_T    = _DIVE_T
DIVE_DIST = DIVE_V * DIVE_V / (2.0 * GRAVITY)   # 下扑初速对应的「等效上抛高度」
DROP_T    = (2.0 * FLOOR_H / GRAVITY) ** 0.5   # 自由落一层的时间
# ⛔ RISE 保留旧名但**含义变了**：v4.1 起跳跃是向下扑，
#   不存在「往上跳多高」。RISE 现在表示「下扑初速等效的上抛高度」，
#   自测① 必须改用 _DIVE_T / 下潜距离来断言，别再拿它比层高。
RISE      = DIVE_DIST


# ============================================================================
# ⭐⭐ 实测工具（⛔⛔ 禁解析值 —— 见文件末尾「为什么必须实测」）
# ============================================================================
def measure(dt=1.0 / 60.0):
    """跑**真实**的积分顺序，量出「下潜窗口」和窗口内的水平位移。

    ⛔ 为什么不写解析式：解析式是连续系统的答案，而引擎每帧
      `vy += g*dt` 再 `y += vy*dt`，峰值落在帧边界上，实测与解析有差
      （night.py 上次差 7.6px，把「跳上台面」判据假绿了两版）。
      玩法窗口只有几十 px 宽，用解析值算 = 判据必假。

    ⭐ v4.1：跳跃是**向下扑**，所以量的不是「滞空」而是
      **下潜窗口** = 从起跳到下潜 _WINDOW_F 层的时间，
      以及这期间满速能横移多远 —— 这就是玩家的操作空间。

    ⛔⛔ 这里量的是 **_WINDOW_F（操作窗口）**，⛔ **不是 _CATCH_F（落地判定）**。
      两者 v4.1 已拆开：手感由 _WINDOW_F 决定，能被哪层接住由 _CATCH_F 决定。
      ⛔ 早先注释写"= 落地判定查的层数"，是拆开前的遗留，害得下面
        `_AIR_TIME, _HALF_DX, _CTRL_SPAN` 的赋值错位过一次。

    返回 (窗口秒数, 过半时水平位移, 窗口结束时水平位移)
    """
    c = Climber(0.0, 0.0)
    c.on_ground = True
    c.vx = float(RUN_MAX)
    c.jump()
    y0 = c.y
    half_x = None
    for i in range(600):                 # 600 帧 = 10s，物理上足够
        c.step_vertical(dt)
        c.step_horizontal(1, dt)         # ⭐ 全程按住右
        dy = c.y - y0
        if half_x is None and dy >= FLOOR_H * _WINDOW_F * 0.5:
            half_x = c.x                  # 窗口过半
        if dy >= FLOOR_H * _WINDOW_F:    # 窗口结束
            return (i * dt, half_x, c.x)
    return (None, half_x, c.x)


_AIR_TIME = None          # 实测：下潜 _WINDOW_F 层所需时间（s）= 玩家的操作窗口
_CTRL_SPAN = None         # 实测：**整个窗口内**满速横移距离（px）= 操作空间
_HALF_DX   = None         # 实测：窗口过半时的横移距离（诊断用，不参与判据）
_FULL_ARC = None          # 兼容旧名（= _CTRL_SPAN）




def plat_width(f: int) -> float:
    """第 f 层平台宽度。f 从 1 起。

    ⭐ 难度来源之一：宽度线性收窄。⛔ 不做平台移动 —— 平台一动，
      玩家就得盯着看，而这个游戏的乐趣在**落点判断**上。
    """
    t = (f - 1) / float(TARGET_FLOOR - 1)
    return 360.0 - 150.0 * t           # 360 → 210


def plat_center(f: int) -> float:
    """第 f 层平台水平中心（v4：**夹在屏幕内**，不再需要无界世界）。

    ⭐⭐⭐ v4 拍板加左右键后，本函数的要求**塌缩成一条**，v1/v2/v3 三版全死的地方：

      **只要相邻两层重叠 >= MIN_OVERLAP，就永远存在解。**
      因为玩家能控 x —— 起跳点自己选，落点自己调，
      站在重叠区起跳就必然落进下一层。

    v3 之所以要搞无界世界 + 横向镜头，就是因为玩家**不能控 x**：
      落点被引擎钉死，要「可解」就得右沿差 >= 81.7px，
      要「有难度」就得左沿差 >= 390px，两者只差 1.5px ⇒ 不可能同时满足。

    ## ⛔⛔ v4.1 修掉的死 bug：递归累加 = 第 4 层起永久贴右墙

    旧实现是 `cx = plat_center(f-1) + spread*jitter` 然后夹到 `[half, VW-half]`。
    这是**有偏随机游走**（jitter 均值 1.0 ⇒ 期望每层 +spread），
    必然在几层内撞上右墙，而夹紧又让它**永久钉在边界上**
    ⇒ 实测第 4~100 层中心全是 1078~1081，97 层平台完全重叠、x 纹丝不动，
      游戏从第 4 层起退化成「原地跳竖直电梯」。

    ⛔ 而且判据 ④ 只查「重叠 >= MIN_OVERLAP」，这种退化**照样全绿** ——
      重叠越大越"合格"。⇒ 判据必须落在**位移量**上，不能只查重叠。

    ## v4.1 解法：折返（boustrophedon），不走随机游走

    每层相对**上一层**的偏移 = `spread * jitter`，但符号**强制交替**
    （向右一步就必定下一步向左，反之亦然），所以偏移在 0 附近震荡、
    不会单向漂移。撞到边界就翻转符号 ⇒ 100 层铺满整个画面宽度。

    ⭐ 抖动来自 (f*2654435761) 取模，⛔ 不用 random —— 重开必须一样，
      玩家要能靠"练"过关。
    """
    if f <= 1:
        return 470.0
    w_cur = plat_width(f)
    # ⭐ 目标偏移量：浅层给满 SPREAD_MAX，随层数线性收缩到 MIN_SPREAD
    t = (f - 1) / float(TARGET_FLOOR - 1)
    spread = SPREAD_MAX + (MIN_SPREAD - SPREAD_MAX) * t
    h = (f * 2654435761) % 4294967296
    jitter = 0.72 + 0.56 * (h / 4294967296.0)      # [0.72, 1.28)
    prev = plat_center(f - 1)
    prev_w = plat_width(f - 1)
    half = w_cur / 2.0 + 24.0
    prev_half = prev_w / 2.0 + 24.0
    # ⭐ 符号交替：从 f-1 的偏移方向**反向**走出去
    step = spread * jitter * (-1.0 if (f - 2) % 2 == 0 else 1.0)
    cx = prev + step
    # ⭐ 撞墙就翻转符号（而不是夹紧）—— 夹紧会永久贴边，折返能弹回来
    lo, hi = half, VW - half
    if cx < lo:
        cx = prev - step
    elif cx > hi:
        cx = prev - step
    return max(lo, min(hi, cx))


def plat_overlap(f: int) -> float:
    """第 f 与 f+1 层的**水平重叠量**（<0 表示完全不重叠）。自测④ 直接验它。"""
    w1, w2 = plat_width(f), plat_width(f + 1)
    c1, c2 = plat_center(f), plat_center(f + 1)
    return (w1 / 2.0 + w2 / 2.0) - abs(c2 - c1)


# ============================================================================
# 角色
# ============================================================================
class Climber:
    """爬梯人。x / y(脚底)，与 night.py 的 Luna 同一套约定。

    ⭐ v4 输入：jump() + step_horizontal(dir, dt)，dir = -1 / 0 / +1。
    """

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.vx = 0.0
        self.vy = 0.0
        self.on_ground = False
        self.alive = True
        self.air_jumps = AIR_JUMPS
        self.face = 1
        self.leg = 0.0
        self.squash = 0.0

    def step_vertical(self, dt):
        """⭐ 纵向积分（每帧**先加重力后位移**，与 night.py 同一套 ⇒ 跳高实测比解析值小）。"""
        self.vy += GRAVITY * dt
        if self.vy > MAX_FALL:
            self.vy = MAX_FALL
        self.y += self.vy * dt

    def step_horizontal(self, dir_in, dt):
        """⭐ 横向积分：按住 = 净加速，松手 = 摩擦减速。

        ## ⛔⛔ v4.1 修掉的死 bug（写在这里，别再改回去）

        原实现是「**无条件**加摩擦」：
            vx += dir * RUN_ACCEL * dt      # 按住右：+36.67/帧
            vx -= GROUND_FRIC * dt         # 无条件：  −43.33/帧
                                    净 = −6.67  ⇒  vx 恒等于 0
        于是「按住右键 1 秒，x 470.0 → 470.0」，横向控制**完全不存在**。
        ⛔ 这不是调参问题：`GROUND_FRIC > RUN_ACCEL` 时**任何**取值都起不来，
          除非把摩擦挪到「只在松手时」这一分支。

        ⛔ 摩擦一律用**减法**（`vx -= fric*dt*sign`）⛔ 不用 `vx *= (1-k)`：
          后者在 |k*dt| ≥ 1 时会**符号翻转**（vx 变成正数反向加速），
          帧率一掉就出现「松手反而往回跑」。

        ⭐ 地面/空中用**不同加速度**（不是不同摩擦）：
          地面 accel 大 = 起跳前能跑起来；空中 accel 小 = 只能微调落点，
          这正是 v4 的操作空间来源。
        """
        if dir_in:
            # --- 按住：只有加速度，没有摩擦 ---
            acc = RUN_ACCEL if self.on_ground else AIR_ACCEL
            self.vx += dir_in * acc * dt
            self.face = 1 if dir_in > 0 else -1
        else:
            # --- 松手：摩擦把 vx 拉向 0，且不越过 0 ---
            fric = GROUND_FRIC if self.on_ground else AIR_FRIC
            if abs(self.vx) <= fric * dt:
                self.vx = 0.0
            else:
                self.vx -= fric * dt * (1.0 if self.vx > 0 else -1.0)
        # ⭐ 钳住最高速
        if self.vx > RUN_MAX:
            self.vx = RUN_MAX
        elif self.vx < -RUN_MAX:
            self.vx = -RUN_MAX
        self.x += self.vx * dt

    def jump(self) -> bool:
        """按一下 = **主动往下扑一层**（⛔ 不是往上弹，见下）。

        ## ⛔⛔⛔ v4.1 修掉的死穴：跳跃方向从根上就错了

        这个游戏叫「**下**一百层」。v1~v4.0 全都把跳跃写成 `vy = JUMP_V`（负值 = 往上），
        于是一整局里角色的 y **从来没有比脚下平台更深过**：

            frame 24  y=60.0  ← 第 1 层顶面，起跳
            frame 33  y=-17.0 ← 最高点
            frame 64  y=60.0  ← 又落回第 1 层顶面

        `f_of_y(y)` 恒等于 1 ⇒ **层号永远不涨**，自测⑥ 无论怎么按都卡在第 1 层。
        而且判据 ①「跳高 > 层高」还**全绿**（115.6 > 110）——
        它验的是"能跳多高"，而这个游戏需要的是"能往下走多远"，
        ⛔ 判据问错了问题，所以 4 版都没抓到。

        ✅ 正确语义：跳跃 = 给一个**向下**的初速 + 短暂滞空。
          滞空那 0.65s 就是玩家的**操作窗口**（空中能横移多少），
          之后继续加速下坠，落到下一层。
        """
        if not self.alive:
            return False
        if self.on_ground:
            # ⭐ 下扑：vy 为正 = 向下
            self.vy = DIVE_V
            self.on_ground = False
            # ⭐ 这里必须留满 AIR_JUMPS，不是 AIR_JUMPS-1。
            #   滞空救的语义是"**离开平台之后**还能再救一次"，
            #   地面起跳的那一次已经用掉了「地面跳」这个额度，
            #   不该再额外来扣空中救的额度 —— 早先写 -1，
            #   等于第一次滞空救直接被吞，掉落中再也救不回来。
            self.air_jumps = AIR_JUMPS
            return True
        if self.air_jumps > 0:
            # 滞空救 = 减缓下坠（往回抬一下），给玩家再争取一点横移时间
            self.vy = -DIVE_V * 0.55
            self.air_jumps -= 1
            return True
        return False


# ⭐ 模块加载时就把实测值跑出来。
#   ⛔ 必须在 Climber 定义之后调用（measure 要造 Climber），
#   也⛔ 不能放到 main() 里 —— 自测脚本 import 本模块时就要用到。
# ⛔⛔ v4.1 修正过的返回值错位：这里原本写成
#   `_AIR_TIME, _CTRL_SPAN, _NEXT_DX = measure()`
# 而 measure 返回的是 (窗口秒数, **过半位移**, **结束位移**)
# ⇒ `_CTRL_SPAN` 拿到的是半窗口数据，比真值小一半。
#   注释写着"窗口内满速横移距离"、自测⑧ 也拿它跟平台宽度比，
#   判据就变成了"半窗口能否覆盖 1/3 平台"——比真实难度松。
_AIR_TIME, _HALF_DX, _CTRL_SPAN = measure()
_FULL_ARC = _CTRL_SPAN


# ============================================================================
# 主窗口
# ============================================================================
class HundredWindow(QWidget):

    def __init__(self, pack=None):
        super().__init__()
        self.pack = pack
        self.setWindowTitle("猫猫公寓 · 是男人就下一百层")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setFocusPolicy(Qt.StrongFocus)

        scr = QApplication.primaryScreen().availableGeometry()
        k = (scr.height() * 0.82) / VH
        self.k = max(0.7, min(1.6, k))
        self.setFixedSize(int(VW * self.k), int(VH * self.k))

        # ---- 状态 ----
        self.phase = "title"          # title | play | dead | win
        self.floor = 1
        self.best = 0
        self.hero = None
        self.cam_y = 0.0              # ⭐ 镜头纵向偏移（>0 表示世界往上移）
        self.flash = 0.0
        self.shake = 0.0
        self.dead_t = 0.0
        self.win_t = 0.0
        self.trail = []
        self.msg = ""
        self.msg_t = 0.0
        self.fell_from = 0            # 从第几层掉下去的（死亡文案用）
        # ⭐ v4：左右键是**按住**生效的（不是按下瞬间）⇒ 必须记按住状态
        self.keys = set()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._last = None

    # ------------------------------------------------------------ 生命周期
    def start(self):
        self.floor = 1
        y = self._plat_y(1)
        self.hero = Climber(plat_center(1), y)
        self.hero.on_ground = True
        self.cam_y = y - VH * CAM_KEEP
        self.trail = []
        self.keys = set()
        self.dead_t = self.win_t = self.shake = 0.0
        self.phase = "play"
        self._say("← → 移动　空格 跳。落到下一层就算过。", 2.8)

    # ------------------------------------------------------------ 坐标
    def _plat_y(self, f: int) -> float:
        """第 f 层平台**顶面**的世界 y（随 f 线性向下）。"""
        return 60.0 + (f - 1) * FLOOR_H

    # ------------------------------------------------------------ 输入
    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            self.close()
            return
        if k == Qt.Key_R:
            self.start()
            return
        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Up, Qt.Key_W):
            self._press()
            return
        # ⭐ 左右键：记进按住集合，⛔ 不在这里直接动 x（要在 _tick 里按 dt 积分）
        if k in (Qt.Key_Left, Qt.Key_A):
            self.keys.add(-1)
            return
        if k in (Qt.Key_Right, Qt.Key_D):
            self.keys.add(1)
            return

    def keyReleaseEvent(self, ev):
        k = ev.key()
        if k in (Qt.Key_Left, Qt.Key_A):
            self.keys.discard(-1)
            return
        if k in (Qt.Key_Right, Qt.Key_D):
            self.keys.discard(1)

    def _dir(self) -> int:
        """当前按住的横向输入：左右同时按 = 0（互相抵消）。"""
        return (1 if 1 in self.keys else 0) - (1 if -1 in self.keys else 0)

    def mousePressEvent(self, ev):
        self._press()

    def _press(self) -> None:
        if self.phase == "title":
            self.start()
            return
        if self.phase == "play":
            if self.hero.jump():
                self.flash = 0.18
            return
        if self.phase == "dead":
            if self.dead_t > 0.6:            # ⭐ 缓冲：防"连按变连跳"
                self.start()
            return
        if self.phase == "win":
            if self.win_t > 0.8:
                self.start()

    # ------------------------------------------------------------ 主循环
    def _tick(self):
        import time
        now = time.perf_counter()
        if self._last is None:
            self._last = now
        dt = min(now - self._last, 1.0 / 20.0)     # ⭐ 钳住大 dt，防穿透
        self._last = now
        self.flash = max(0.0, self.flash - dt)
        self.shake = max(0.0, self.shake - dt * 3.2)
        self.msg_t = max(0.0, self.msg_t - dt)
        if self.phase == "play":
            self._step_play(dt)
        elif self.phase == "dead":
            self.dead_t += dt
        elif self.phase == "win":
            self.win_t += dt
        self.update()

    def _step_play(self, dt):
        h = self.hero

        # --- 水平：玩家可控（v4 新增）---
        h.step_horizontal(self._dir(), dt)
        # ⭐ 屏幕边界：夹在 [身体半宽, VW−身体半宽]。
        #   ⛔ 平台全在屏内（v4 的布局前提），所以角色也必须在屏内，
        #     否则会出现「站在平台外的空气上」。
        if h.x < BODY_W * 0.5:
            h.x = BODY_W * 0.5
            h.vx = max(0.0, h.vx)
        elif h.x > VW - BODY_W * 0.5:
            h.x = VW - BODY_W * 0.5
            h.vx = min(0.0, h.vx)

        # --- 垂直：先加重力后位移（⭐ 与 night.py 同一套，跳高实测比解析值小）---
        prev_y = h.y
        h.step_vertical(dt)

        # --- 落地：只查「当前层附近」，⛔ 不遍历 100 层 ---
        #   ⭐ 判定用「上一帧在顶面上方 + 这一帧到了顶面下方」——
        #     只判"这一帧穿过了顶面"会在**已经站在平台上时漏检**（贴着没有"穿过"），
        #     角色会在 y0↔y0+1.6 之间隔帧抖（night.py 踩过同一个坑）。
        #   ⭐ 窗口 floor±1 / floor+2 给容错：v4 玩家能控 x，
        #     大部分时候只会掉一层，但手滑往侧面跳也该有救回机会。
        was_air = not h.on_ground
        h.on_ground = False
        # ⭐⭐⭐ v4.1 修掉的第五个 bug：**站着不动，层号自己涨**。
        #
        #   症状：玩家什么都没按，200 帧内 floor 从 1 涨到 12。
        #
        #   根因不是"落地判定缺闩锁"，而是**状态被单向抹掉**：
        #       was_air = not h.on_ground     ← 站着时算出 False（正确）
        #       h.on_ground = False           ← 紧接着就被抹成 False（错误）
        #       if was_air:  ...落地判定...     ← 整段被跳过（正确）
        #   ⇒ 这一帧结束时 `on_ground` 停在 False。下一帧 `was_air` 变 True，
        #     重力把 y 从 py 推到 py+0.6，落地条件重新成立 ⇒ floor++。
        #     循环 ⇒ 每秒涨十几层，⑥"只按了 4 次跳却到第 100 层"就是这么来的。
        #
        # ✅ 正确解法：**补回"重新着地"分支**。
        #   离地只有两种情况，都要在这里被识别出来：
        #     ① 按跳 —— `jump()` 在 `_press()` 里就把 `on_ground` 置 False 了，
        #        所以起跳那一帧 `was_air` 本来就是 True，**不会**被这个分支误吸回去；
        #     ② 走出平台边缘 —— 下面的 `over` 判定为假，自然放它下坠。
        if not was_air:
            py = self._plat_y(self.floor)
            w = plat_width(self.floor)
            cx = plat_center(self.floor)
            over = (cx - w / 2.0 - BODY_W * 0.5
                    <= h.x <= cx + w / 2.0 + BODY_W * 0.5)
            # ⭐ 容差 GROUND_SNAP：一帧重力的最大下沉量 = g·dt²。
            #   dt 被钳在 1/20 ⇒ 2000×0.05² = **5.0px**，所以阈值必须 > 5，
            #   取 8。⛔ 取小了会在掉帧时"站着站着就掉下去"。
            if over and (h.y - py) <= GROUND_SNAP:
                h.y = py
                h.vy = 0.0
                h.on_ground = True
        # --- 落地：只在「上一帧在空中」时判定 ---
        if was_air:
            best = None
            # ⭐⭐⭐ v4.1 修掉的第四个 bug：**必须排除当前层本身**。
            #   下扑玩法的第 1 帧就离开了地面（prev_y=60 → y=63），
            #   而当前层 `py=60` 恰好满足 `prev_y <= py+1 and y >= py`
            #   ⇒ **本层立刻把自己接住**，y 被强行拉回 60。
            #   症状：跳跃数值上等于「原地踏一步」，层号永远不涨，
            #         自测⑥ 打满 20 万帧仍停在第 1 层。
            #   ⛔ 这类 bug 判据抓不到，因为「层号涨不涨」看着是层号问题，
            #     实际是落地判定的**候选集**错了。
            for f in range(self.floor + 1, min(TARGET_FLOOR, self.floor + _CATCH_F) + 1):
                if f < 1 or f > TARGET_FLOOR:
                    continue
                py = self._plat_y(f)
                w = plat_width(f)
                cx = plat_center(f)
                if not (cx - w / 2.0 - BODY_W * 0.5 <= h.x <= cx + w / 2.0 + BODY_W * 0.5):
                    continue
                if prev_y <= py + 1.0 and h.y >= py:
                    if best is None or py < best:
                        best = py
            if best is not None:
                h.y = float(best)
                h.vy = 0.0
                h.on_ground = True
                h.air_jumps = AIR_JUMPS
                # ⭐⭐ 落地刹速**必须 gate 在 was_air 上**。
                #   ⛔⛔ v4.1 修掉的死 bug：不 gate 的话，「站着不动」时
                #     落地判定每帧都重新成立（vy 被重力加到 >0，
                #     prev_y <= py+1 且 y >= py 恒真），
                #     于是 `vx *= 0.4` 每帧执行一次 ——
                #     稳态解 (vx + 36.67)*0.4 = vx ⇒ **vx 恒等于 24.4**
                #     （RUN_MAX 是 240，实际只剩 1/10）。
                #     症状：按着右键跑，屏幕上一寸一寸挪，快到像没生效。
                if was_air:
                    # 落地就把横向速度刹掉大半 —— 否则角色会在平台上打滑，
                    # 玩家明明站住了却一直往边缘漂（night.py 踩过"落地要清速度"）。
                    h.vx *= 0.4
                    self.shake = 0.55
                    h.squash = 1.0
                    self._arrive(f_of_y(best))
        if h.squash > 0.0:
            h.squash = max(0.0, h.squash - dt * 4.0)
        if h.on_ground:
            h.leg += dt

        # --- 层号推进：站到哪层就是哪层 ---
        if h.on_ground:
            nf = f_of_y(h.y)
            if nf > self.floor:
                self.floor = nf
                if self.floor > self.best:
                    self.best = self.floor
                self._say("第 %d 层" % self.floor, 0.7)
                if self.floor >= TARGET_FLOOR:
                    self.phase = "win"
                    self.win_t = 0.0
                    return

        # --- 镜头跟随（只跟"往下"，不跟"往上"—— 往上跳时画面别乱晃）---
        #   ⛔⛔ 绝不能用「掉出画面底」判死：镜头是绝对跟随，
        #     `h.y - cam_y` 恒等于 VH*CAM_KEEP = 244.8px，永远 < VH+80
        #     ⇒ 角色无限下坠、层号冻结、phase 永远 play。
        #     （这是 v2/v3 自测「只到第 4 层」「不跳也不死」的根因。）
        #   ✅ 正确判据：**掉到当前层的容错窗之下还没被任何平台接住** = 摔。
        want = h.y - VH * CAM_KEEP
        if want > self.cam_y:
            self.cam_y = want

        # ⭐⭐ v4：**镜头不横向跟随**（角色能自己跑了，平台也全在屏内）。
        #   v3 那个 cam_x 是为了兜「角色 x 单调递增」才加的，
        #   现在这个前提不存在了 —— 留着只会让画面左右晃。
        if not h.on_ground:
            # ⭐ v4.1：容错窗跟着 **_CATCH_F** 走，不是 _WINDOW_F。
            #   落地判定只接 _CATCH_F 层 ⇒ 摔死线必须在同一层，
            #   否则会出现"判定接不到、但还没到死线"的角色**凭空悬在中间**。
            _guard = self._plat_y(min(TARGET_FLOOR, self.floor + _CATCH_F))
            if h.vy > 0.0 and h.y > _guard + FLOOR_H * _CATCH_Y:
                self.phase = "dead"
                self.dead_t = 0.0
                self.fell_from = self.floor
                if self.floor > self.best:
                    self.best = self.floor
                return

        # --- 拖尾 ---
        self.trail.append((h.x, h.y))
        if len(self.trail) > 14:
            self.trail.pop(0)

    def _arrive(self, f):
        pass

    def _say(self, s, dur=1.5):
        self.msg, self.msg_t = s, dur

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(self.k, self.k)

        depth = min(1.0, self.floor / float(TARGET_FLOOR))
        g = QLinearGradient(0, 0, 0, VH)
        g.setColorAt(0.0, QColor(int(20 + 12 * (1 - depth)), int(22 + 14 * (1 - depth)), int(36 + 18 * (1 - depth))))
        g.setColorAt(1.0, QColor(8, 9, 17))
        p.fillRect(QRectF(0, 0, VW, VH), g)

        # ⭐ 震屏画在**世界坐标系**里（已 translate 过），所以只平移内容不动背景框
        p.save()
        p.translate(0.0, -self.cam_y)
        if self.shake > 0.01:
            p.translate(4.0 * self.shake * (1 if (int(self.shake * 22) % 2) else -1), 0.0)

        # ---- 侧墙（v4 世界 x = 屏幕 x，⛔ 不再跟 cam_x）----
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawRect(QRectF(0, self.cam_y, 54, VH))
        p.drawRect(QRectF(VW - 54, self.cam_y, 54, VH))

        # ---- 只画视野内的层，⛔ 不画 100 层（一次 paint 400 个 rect 会卡）----
        lo = max(1, int((self.cam_y - FLOOR_H) // FLOOR_H))
        hi = min(TARGET_FLOOR, int((self.cam_y + VH + FLOOR_H) // FLOOR_H) + 1)
        for f in range(lo, hi + 1):
            self._draw_floor(p, f, f == self.floor)

        # ---- 已走过的层：淡淡刻痕（进度感，不写字）----
        p.setPen(QPen(QColor(120, 130, 165, 46), 1.0))
        for f in range(max(1, self.floor - 12), self.floor + 1):
            y = self._plat_y(f)
            p.drawLine(QPointF(58, y), QPointF(VW - 58, y))

        # ---- 拖尾 ----
        for i, (tx, ty) in enumerate(self.trail):
            al = (i + 1) / float(len(self.trail))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 214, 150, int(70 * al)))
            p.drawEllipse(QPointF(tx, ty - 12), 5.0, 7.0)

        if self.hero is not None:
            self._draw_hero(p, self.hero)
        p.restore()

        self._draw_hud(p)
        if self.phase in ("title", "dead", "win"):
            self._draw_overlay(p)
        p.end()

    def _draw_floor(self, p, f, is_cur):
        w = plat_width(f)
        cx = plat_center(f)
        y = self._plat_y(f)
        # 楼板：右侧往下收细 —— 暗示"跑出去就没了"
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(126, 108, 96) if is_cur else QColor(66, 72, 96))
        p.drawRoundedRect(QRectF(cx - w / 2.0, y, w, 14.0), 5, 5)
        # 右沿小箭头：⭢ 这一层往哪走
        p.setBrush(QColor(255, 200, 120, 150) if is_cur else QColor(150, 158, 180, 90))
        p.drawPolygon(QPolygonF([QPointF(cx + w / 2.0 - 1, y + 2),
                                 QPointF(cx + w / 2.0 + 12, y + 7),
                                 QPointF(cx + w / 2.0 - 1, y + 12)]))
        # 板下阴影：楼板之间的暗区
        p.setBrush(QColor(0, 0, 0, 92))
        p.drawRect(QRectF(cx - w / 2.0 + 10, y + 14, max(4.0, w - 20.0), 10))
        if f >= self.floor - 1 and f <= self.floor + 2:
            p.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
            p.setPen(QPen(QColor(230, 216, 190) if is_cur else QColor(146, 152, 176)))
            p.drawText(QRectF(cx - 40, y - 27, 80, 20), Qt.AlignCenter, "%d" % f)

    def _draw_hero(self, p, h):
        """纯程序绘制。⛔ 不画脸（2.5 头身资源全是侧面手绘，程序正面小人掉档）。

        ⭐ v4 新增：**朝向**由 h.face 决定（左右键），
          走路动画由 |vx| 驱动 —— 站着不动时不该有迈腿，否则像滑步。
        """
        sq = h.squash
        sw, sh = 1.0 + 0.26 * sq, 1.0 - 0.22 * sq
        bw, bh = 25.0 * sw, 42.0 * sh
        x, y = h.x, h.y
        p.setPen(Qt.NoPen)
        # ⭐ 迈腿频率跟**速度**走，不是跟时间走
        spd = abs(h.vx) / max(1.0, RUN_MAX)
        ph = (int(h.leg * (5.0 + 7.0 * spd)) % 2)
        moving = h.on_ground and spd > 0.06
        # 身体整体按朝向镜像（⛔ 别镜像文字/文字层，只镜像这个角色）
        p.save()
        p.translate(x, y)
        p.scale(h.face if h.face else 1, 1.0)
        p.translate(-x, -y)
        for dx, op in ((-6.0, 0), (3.0, 1)):
            lift = 3.0 if (moving and ph == op) else 0.0
            p.setBrush(QColor(140, 112, 74))
            p.drawRoundedRect(QRectF(x + dx, y - 6.0 - lift, 5.0, 9.0), 2, 2)
        # 身
        p.setBrush(QColor(204, 168, 108))
        p.drawRoundedRect(QRectF(x - bw / 2, y - bh - 6.0, bw, bh), 9, 9)
        # 尾（⛔ 只在有速度时甩起来，静止时垂着 —— v4 才有"活着"的感觉）
        p.setBrush(QColor(186, 150, 96))
        _tw = 8.0 + 6.0 * spd if moving else 0.0
        p.drawRoundedRect(QRectF(x - bw / 2 - 5.0, y - bh * 0.55 - _tw, 5.0,
                                  bh * 0.55 + _tw), 2, 2)
        # 头
        hr = 12.5 * sw
        p.setBrush(QColor(232, 198, 150))
        p.drawEllipse(QPointF(x, y - bh - 6.0 - hr * 0.45), hr, hr * 1.05)
        # 耳（金棕 + 银色挑染的暗示）
        p.setBrush(QColor(214, 178, 118))
        p.drawPolygon(QPolygonF([QPointF(x - 7, y - bh - 12.0),
                                 QPointF(x - 9, y - bh - 23.0),
                                 QPointF(x - 1, y - bh - 17.0)]))
        p.drawPolygon(QPolygonF([QPointF(x + 7, y - bh - 12.0),
                                 QPointF(x + 9, y - bh - 23.0),
                                 QPointF(x + 1, y - bh - 17.0)]))
        if self.flash > 0.02:
            p.setBrush(QColor(255, 240, 190, int(130 * self.flash / 0.2)))
            p.drawEllipse(QPointF(x, y - bh * 0.6), bw * 1.4, bw * 1.4)
        p.restore()

    def _draw_hud(self, p):
        p.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        p.setPen(QPen(QColor(238, 228, 202)))
        p.drawText(QRectF(24, 18, 420, 26), Qt.AlignLeft | Qt.AlignVCenter,
                   "第 %d / %d 层" % (min(self.floor, TARGET_FLOOR), TARGET_FLOOR))
        p.setFont(QFont("Microsoft YaHei", 11))
        p.setPen(QPen(QColor(168, 174, 196)))
        p.drawText(QRectF(24, 42, 520, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   "最好 %d 层　·　← → 移动　空格 跳（空中还能救一次）" % self.best)
        bw, by = 460.0, 64.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawRoundedRect(QRectF(24, by, bw, 5.0), 2, 2)
        p.setBrush(QColor(255, 206, 120))
        p.drawRoundedRect(QRectF(24, by, bw * (min(self.floor, TARGET_FLOOR) / float(TARGET_FLOOR)), 5.0), 2, 2)
        if self.msg_t > 0.0:
            p.setFont(QFont("Microsoft YaHei", 12))
            p.setPen(QPen(QColor(255, 226, 170)))
            p.drawText(QRectF(0, 88, VW, 26), Qt.AlignCenter, self.msg)

    def _draw_overlay(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(6, 7, 12, 190))
        p.drawRect(QRectF(0, 0, VW, VH))

        def big(s, size, y, col):
            p.setFont(QFont("Microsoft YaHei", size, QFont.Bold))
            p.setPen(QPen(QColor(*col)))
            p.drawText(QRectF(0, y, VW, size + 20), Qt.AlignCenter, s)

        if self.phase == "title":
            big("是男人就下一百层", 44, 210, (255, 226, 170))
            p.setFont(QFont("Microsoft YaHei", 14))
            p.setPen(QPen(QColor(206, 210, 228)))
            p.drawText(QRectF(0, 286, VW, 26), Qt.AlignCenter,
                       "往下掉一百层。掉到下一层的平台上，就算过一层。")
            p.drawText(QRectF(0, 322, VW, 26), Qt.AlignCenter,
                       "平台一层比一层窄，站的地方越来越少。")
            p.drawText(QRectF(0, 358, VW, 26), Qt.AlignCenter,
                       "掉下去的时候还能按一次跳救自己 —— 但只有一次。")
            p.setPen(QPen(QColor(150, 156, 180)))
            p.drawText(QRectF(0, 410, VW, 24), Qt.AlignCenter,
                       "← → 移动　空格 跳　·　R 重开　·　Esc 退出")
        elif self.phase == "dead":
            big("摔了", 52, 196, (240, 150, 140))
            p.setFont(QFont("Microsoft YaHei", 15))
            p.setPen(QPen(QColor(226, 216, 196)))
            p.drawText(QRectF(0, 282, VW, 26), Qt.AlignCenter,
                       "下到第 %d 层　（最好 %d 层）" % (min(self.floor, TARGET_FLOOR), self.best))
            if self.dead_t > 0.6:
                p.setPen(QPen(QColor(178, 184, 208)))
                p.drawText(QRectF(0, 336, VW, 24), Qt.AlignCenter, "空格 / 点击 重来")
        elif self.phase == "win":
            big("100 层", 58, 186, (255, 226, 170))
            p.setFont(QFont("Microsoft YaHei", 15))
            p.setPen(QPen(QColor(226, 216, 196)))
            p.drawText(QRectF(0, 276, VW, 26), Qt.AlignCenter, "你下到底了。")
            if self.win_t > 0.8:
                p.setPen(QPen(QColor(178, 184, 208)))
                p.drawText(QRectF(0, 336, VW, 24), Qt.AlignCenter, "空格 / 点击 再来一次")


def f_of_y(y):
    """世界 y → 层号（1 起）。"""
    f = int((y - 60.0) // FLOOR_H) + 1
    return max(1, f)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    HundredWindow().show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
