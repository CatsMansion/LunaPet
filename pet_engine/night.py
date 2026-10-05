# -*- coding: utf-8 -*-
"""night.py —— 「夜间冒险」灰盒 v1

⭐ 这是什么
    桌宠之外单独开的一个小游戏窗口：深夜厨房，操控露娜越过允许区边界去偷东西，
    别被微波炉抓到。被抓 → 黑魂风 "YOU MEOWED" → 押送回窝，这趟赃物清零。

⛔ 与桌宠的边界
    本模块【不 import 也不调用】core.Pet / ui.PetWindow。
    桌宠的物理是"屏幕坐标 + 地形驱动 + 情绪状态机"，跟横板关卡需要的
    AABB / 单向平台 / 追击 AI 完全是两回事，硬塞进去两边都得改。
    只复用两样纯资源：① 角色包的 PNG 帧（pack.frame_path）② UI 图标（赃物）。

⭐ 灰盒的含义
    房间里所有东西都是扁平色块，没有美术。目的是先把手感、AI、机制跑通，
    让 Ronny 目检「跑跳爬 + 越界被押送 + 偷东西」这三条是否成立。
    美术是后面单独一批派单的事。

坐标系统
    全部用【逻辑坐标】VW×VH = 1280×720；paintEvent 开头 p.scale(k, k) 统一放大，
    所以关卡数据、物理、AI 里写的数都是逻辑像素，跟窗口实际大小无关。
"""
from __future__ import annotations

import math
import json
import os
import sys

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QRect
from PySide6.QtGui import (QImage, QPixmap, QPainter, QColor, QPen, QBrush,
                           QFont, QLinearGradient, QRadialGradient, QIcon)
from PySide6.QtWidgets import QApplication, QWidget

try:                                    # 包内导入 / 直接跑脚本 两种都支持
    from .core import load_pack
    from .ui import silhouette_of
except ImportError:
    from core import load_pack
    from ui import silhouette_of


# ============================================================================
# ① 关卡数据 —— 深夜厨房（灰盒，改这里就能改关卡）
# ============================================================================

VW, VH = 1280, 720

FLOOR_Y = 599               # ⭐⭐ 2026-10-03 按**背景板实测**（派单 42 v3）：
                            #   设定端程序二次确认（y=580 行内std 13.61 平滑区 →
                            #   y=600 std 16.11 纹理区）。⛔ 不是执行端初测的 578（那是踢脚线，
                            #   差 21px 但肉眼极像 —— 最强梯度那条不一定是目标）。
                            #   ⚠️ 代价：地板只剩 121px 高（原 672 时有 48px），可站面积变大，
                            #   但吊柜/冰箱能占的高度变多 —— 这正是我们要的（背景板里它们更高）。
NEST_X0, NEST_X1 = 10, 200    # ⭐「阳台」：露娜住的地方（回这里 = 这趟成功）
                              #   Ronny：「左边就是露娜住的阳台」。宽 190px = 0.58m
# ⛔⛔ 允许区边界**不在这里** —— 它是逐档的（NIGHTS[i]["border_x"]）。
#    留一个模块级 BORDER_X 会有个很坑的失败模式：谁改了它，游戏毫无反应，
#    因为真正生效的是 room.border_x。已删。

# 平台 (x0, y0=顶面, x1, y1=底面)。⛔ 单向平台：只有从上往下落才会踩到
# ⭐⭐ 2026-10-03 按真实尺寸重排（Ronny：「猫 40cm / 餐桌 1m / 冰箱 1.8m / 柜子 2m」）
#   换算基准：1cm = 3.3px（露娜 40cm = 132px）
#   y0 = 顶面 = **角色站上去的 y**（⛔ 不是家具顶，是站位）
# ⭐⭐ 2026-10-03 按背景板 v3 实测坐标（Ronny：「和生成图对准」）
# ⛔⛔ 这段「冰箱(570~730) 与桌布(470~730) 的 x 重叠是合理的」的说法**已于 10-04 作废**：
#   Ronny 明确要求「茶几和冰箱重合的问题最好也修修，让他们错开」——
#   重合不是"前景遮挡所以合理"，是背景板 v3 本身就把两个家具画在同一处。
#   现布局冰箱已挪到右墙 1120~1250，与茶几 430~700 完全错开（见下方 10-04 段）。
TABLE_X0, TABLE_X1, TABLE_TOP = 430, 700, 488   # ⭐ 餐桌具名常量（桌布左/右/桌面顶）
                                                #   实心墙/攀爬区/冰箱判定共用这一份，别再各写一遍数字
# ⭐⭐⭐ 2026-10-04 重排（配合背景板 v4）：冰箱从「茶几正后方」挪到**右墙独立段**。
#   起因：背景板 v3 实测冰箱 x≈553~735、桌布 x≈395~840 → 冰箱几乎完全落在桌布里，
#   下半被挡，_at_fridge 被迫写成「站上桌面才够得着」。玩法上能跑，但视觉上就是重合。
#
# ⭐⭐⭐ **重排时撞上的真矛盾（本轮最重要发现，别再重犯）**：
#   茶几(落地实心) + 厨房台(落地实心) + 冰箱(落地实心) 三个实心体把 1280px 地板切碎 ——
#   可走段只剩 0~430 / 700~760 / 1060~1120 / 1250~1280，
#   **微波炉根本没有一条 ≥300px 的连续通道可巡逻**（实测三档全部撞实心，见 _d_新布局几何.py）。
#   ⛔ 而它是地面单位（跳 55px 够不到 178px 缺口），不能放到台面上巡逻。
#   ✅ 解法：**厨房台改成薄台面（架空）** —— 台面板厚 38px（≈11cm，符合真实台面板），
#      台下留空当通道。微波炉 161px 高（599−161=438 > 435 台面下沿）→ **它从台面下方
#      穿过去在视觉上是对的**（它本来就比台面矮）。露娜也能从台下走，或跳上台面。
#   ⭐ 这是「游戏逻辑 > 氛围与真实性」的直接落地：为了留出巡逻通道，台下不做成实心柜体。
PLATFORMS = [
    (0,    FLOOR_Y, VW, VH),        # 地板
    (TABLE_X0, TABLE_TOP, TABLE_X1, FLOOR_Y),  # ⭐ 餐桌（桌布左 430 / 右 700 / 桌面 488）
    (760,  380,     1060, 418),     # ⭐ 厨房台：顶 380 / **底 418（薄台面，架空可穿行）**
    (790,  50,      1010, 189),     # ⭐ 吊柜（柜顶 50 / 下沿 189 / 左 790 / 右 1010）
]

# ⭐ 冰箱（贴右墙，独立段）—— 2026-10-04 从「茶几正后方」挪到这里，与茶几完全错开。
#   x 1120~1250（宽 130px ≈ 39cm，单门冰箱），顶 50（高 549px ≈ 166cm ≈ 1.8m 标称）
#   ⭐ 底 = FLOOR_Y(599)：冰箱**落地实心** → 它左边的地板才是微波炉巡逻段的东端尽头。
#   ⭐ 挪右墙后 _at_fridge 回到最自然的语义：「站在冰箱正前方的地板上」，
#     不再需要「站上茶几桌面」这个由遮挡逼出来的 hack。
FRIDGE = {"x": 1120, "y": 599, "w": 130, "h": 549}
# ⭐ 冰箱里的东西（比地面容器多）—— 高风险高回报：它就在微波炉巡逻段的东端尽头
#   坐标是**冰箱内部格子**（按新冰箱 x1120~1250 重排，不再压在茶几布幔上）
FRIDGE_FOODS = [
    {"x": 1148, "y": 260, "icon": "watermelon"},
    {"x": 1222, "y": 260, "icon": "blueberry"},
    {"x": 1148, "y": 400, "icon": "pumpkin"},
    {"x": 1222, "y": 400, "icon": "yogurt"},
]

# ---- QTE 参数（限时按键序列）----
QTE_TIME_LIMIT = 0.95         # ⭐ 每按一个键的时限（秒）—— 手残也来得及，但不许磨
QTE_LEN        = 3            # 序列长度
QTE_FAIL_ALERT = 0.34         # ⛔ 按错/超时的惩罚：微波炉警觉 +0.34（不是直接失败）
# ⭐⭐ QTE 期间锁移动（Ronny 10-03：「qte 的时候因为是方向键也经常因为动了所以离开判定区域」）
#   根因：keyPressEvent 里 self.keys.add(k) 在 QTE 分支【之前】执行 ——
#   方向键已经进了按键集合，QTE 虽然把它"吃掉"不重复响应，_tick 照样拿它驱动移动。
#   ✅ 双保险：QTE 开始时清掉按着的移动键 + 让她站定；QTE 期间 _tick 只传过滤后的键集。
QTE_MOVE_KEYS = {Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down,
                 Qt.Key_A, Qt.Key_D, Qt.Key_W, Qt.Key_S, Qt.Key_Space}

# 梯子 (中心x, 顶端y, 底端y)
# ⭐⭐ 2026-10-03 加了第二根：吊柜(980~1240, y=320) 与台面(520~880) 之间有 100px 空隙，
#   跳跃上限 211px 但**跨度不够**（要落到 980 起点）→ 吊柜上三个容器原本**根本拿不到**。
#   ⭐ 这条是 `_自测_可达性.py` 的静态分析抓出来的（模拟玩家版没报，因为模拟玩家更笨）。
# ⭐⭐ 2026-10-03 Ronny：「梯子之后挪到挂毯和桌布上」
#   布是柔的、没有厚度的 —— 正好解掉他最早提的「梯子有厚度、姿势不适配」，
#   而且猫爬布本来就比爬铁杆合理。结构上仍是 LADDERS（位置/端点不变），
#   只是绘制从「两根细杆+横档」改成「一条垂布」。
# ⭐⭐ 三条布道（2026-10-03 重排后）：普通人物之间的越界后并不总是跳得过去的
#   原因：餐桌 290~690 与 厨房桌 830~1080 之间有 **140px 空隙**，而跳跃射程只有
#   211px高 × 悬空 0.21s × 300px/s = **63px** → 实测 5 件容器格不到。
LADDERS = [
    (565,  488, FLOOR_Y),   # ⭐ 桌布攀爬：桌面 488 → 地板 599（新茶几中心 565）
                            #   ⛔⛔ 2026-10-03 修复「掉到地底下」：原写底端 632（桌布视觉下摆），
                            #   但 FLOOR_Y=599 —— 爬到底她会站在**地板下方 33px**，
                            #   一离开梯子就自由落体掉出世界（y>VH+200 被拽回窝）。
                            #   执行端回传 §五·4 建议"取 632"是按视觉下沿给的 —— 站位不能低于地板，不采纳。
                            #   视觉下摆 632 只是"布画到那里"，落脚点必须 = 地板。
    (900,  232, 310),       # ⭐ 挂毯攀爬：上端 232（挂杆）→ 下端 310
                            #   ⭐ 2026-10-04 对准新吊柜(790~1010)：x 由 762 → 900，
                            #   下端 300 → 310（实测从厨房台顶 397 起跳最高 193，
                            #   抓毯区间 [222,320] 稳稳吃进 —— 旧值 300 只差 2px，很脆）。
                            #   ⭐ **实测数据**：跳跃上限 = 204px（不是解析 211，离散积分会掉一点）。
                            #     厨房台顶 397 起跳到 193 → 吊柜底 189 差 4px 上不去 ⛔
                            #     ⇒ 吊柜**只能靠挂毯上去**，这个 4px 是"必须保留挂毯"的硬理由。
]

# ⭐⭐ 攀爬面（2026-10-03「桌子地形很奇怪」修复）：桌布是**全覆盖垂到地**的整面布，
#   不是一根杆 —— 整面（470~730 × 488~599）都应该能扒着往上爬。
#   同时这面布对地面行走是**实心墙**（见 Luna.update 里的布墙判定），
#   ⛔ 不能再让她从桌布里面穿过去 —— 背景板里布是垂到地的，穿模一眼假。
#   冰箱（1120~1250）已挪到**右墙独立段**，与茶几（430~700）完全错开 ——
#   所以 QTE 回到最自然的语义：**站在冰箱正前方的地板上**按 E（见 _at_fridge）。
LADDER_ZONES = [
    (TABLE_X0, TABLE_X1, TABLE_TOP, FLOOR_Y),   # 桌布整面：左 430 / 右 700 / 顶 488 / 底 599
]

# ============================================================================
# ⭐⭐ 容器类型（Ronny 2026-10-04：「不要所有东西都放罐子里，
#      根据食物本身的特性选择盘子/直接放桌上/放冰箱」）
# ============================================================================
# ⭐ 为什么按"食物的物理特性"分档，而不是按"容器好不好看"分：
#   这四档对应的是**四种真实的偷取难度**，难度必须和战利品价值对齐，
#   否则玩家会永远只拿最安全的那档，危险档变成没人碰的死档。
#
#   kind=loose  直接敞着放 —— 盘子/砧板上，伸手就拿。**零噪声**。
#                适合：刚洗好的青菜、盘子里的水果、放在台面上的面包
#   kind=plate  扣着盖子的盘子 —— 要先掀盖。**小噪声**（近距离才听得到）。
#                适合：盖着盖子的菜、装盘的肉
#   kind=jar    密封罐 —— 要撬。**噪声大 + 破了直接让守卫疯狂追踪**。
#                适合：腌菜、酱料、罐头
#   kind=fridge  冰箱 —— 要开冰箱门走 QTE。噪声中等（撬门声）。
#                适合：需要冷藏的
#
# ⭐⭐ **风险与价值必须同向**（这是本设计的核心约束）：
#   jar 是最危险的档，所以它必须是**最值钱**的档。
#   否则玩家的最优解永远是「只拿 loose」，jar 永远没人碰 ——
#   而Ronny 要的正是「破罐 = 全面暴怒」这种高戏剧性，
#   没人碰的话这条机制就白设计了。
#   → 用 `value` 分三档（1/2/4 件）来对齐，结算时按 value 计。
#
# ⛔ noise 单位与 _make_noise 的 strength 同口径（0~1，贴着他耳边才满值）
# ⛔ fury=True = 破它会让守卫直接进 frenzy（见 Microwave.fury）
KIND_TABLE = {
    "loose": {"noise": 0.00, "fury": False, "value": 1,
              "label": "敞着放的", "hit": 46.0},
    "plate": {"noise": 0.26, "fury": False, "value": 2,
              "label": "盖着盖的盘子", "hit": 50.0},
    "jar":   {"noise": 0.62, "fury": True,  "value": 4,
              "label": "密封罐", "hit": 54.0},
    "fridge": {"noise": 0.34, "fury": False, "value": 3,
               "label": "冰箱里的", "hit": 46.0},
}
KIND_ORDER = ("loose", "plate", "jar", "fridge")

# ⭐⭐ 手上东西的编码 = "value:icon"（例 "4:yogurt"）。
#   为什么带前缀：结算要按**价值**算而不是按件数（loose 1 分、jar 4 分），
#   而渲染要的是 icon 名 —— 一条串同时带两个信息，省掉给 carrying 加第二个列表。
#   ⛔ 兼容：纯 icon 串（无冒号）按 value=1 处理，见 _loot_value()。
def _loot_split(item: str):
    """("4", "yogurt") → value=4, icon="yogurt"；无冒号 → value=1。"""
    if ":" in item:
        v, nm = item.split(":", 1)
        try:
            return int(v), nm
        except ValueError:
            return 1, item
    return 1, item

# 赃物：y 是"它坐在哪个面上"（顶面 y）。icon 复用 packs/luna/ui/里的现成图标
# ⛔ 这份只是【档二·深夜】的基准数据，真正生效的是 NIGHTS[i]["stashes"]
# ⭐ kind 选取按食物特性：
#   yolk 蛋黄 → 敞开的碗里挑出来 = loose（最容易）
#   watermelon西瓜 / pumpkin 南瓜 → 整个摆在台面上 = loose
#   blueberries 蓝莓 → 装在碗里 = loose
#   salmon 三文鱼 → 摆在盘子上 = plate
#   chicken 整鸡 → 扣着盖 = plate
#   shrimp 虾 → 装在碗里 = plate
#   yogurt 酸奶 → 密封罐 = jar（要撬）
#   sweetpotato 蒸红薯 → 密封保鲜罐 = jar
STASHES = [
    # ⭐ 2026-10-04 随新布局重排（旧坐标 520/680/800/950/900 是按旧茶几 470~730、
    #   旧台 700~1000 摆的，家具一挪就全错位 —— ⛔ 改布局必须同步重排这三条 NIGHTS 全部坐标）。
    {"x": 480,  "y": 488, "icon": "yolk",     "kind": "loose"},   # 茶几西：伸手就拿
    {"x": 650,  "y": 488, "icon": "yogurt",   "kind": "jar"},     # 茶几东：唯一 jar
    {"x": 830,  "y": 380, "icon": "salmon",   "kind": "plate"},   # 厨房台西：掀盖
    {"x": 990,  "y": 380, "icon": "chicken",  "kind": "plate"},   # 厨房台东：靠近冰箱
    {"x": 1000, "y": 599, "icon": "blueberry", "kind": "loose"},  # 地板·冰箱前（绕后拿）
]

# ---- 手感常数（**逐档不变**的那些；都是逻辑像素/秒）----
GRAVITY     = 2000.0
RUN_SPEED   = 300.0
# ⭐ 起跳速度：跳高 = JUMP_V²/(2*GRAVITY)。
#   地板 648 → 料理台 470 落差 178px，理论 211px 留约 30px 余量（之前 860 只有 178，
#   刚好卡在临界，离散积分一损失就跳不上去）。
#   ⛔ 别再往上加：205 上不了吊柜（落差 328），「必须经由料理台中转」是刻意的分层。
JUMP_V      = 920.0
CLIMB_SPEED = 150.0
AIR_CTRL    = 0.75          # 空中的水平控制力折扣
LAND_TOL    = 2.0           # 落地判定容差（平台顶面上下各 2px 都算"贴着"）

# ⭐⭐⭐ 露娜技能参数（Ronny 2026-10-04「给露娜设计攻击技能和冲刺技能」）
# ============================================================================
# ⭐ 设计原则：**每个技能都要有一帧"我做了个决定"的时刻**。
#   如果一个技能没有代价、没有时机判断，它就只是另一个走路键。
#   所以攻击有前摇（会被打断）、冲刺有冷却（不能连用）。
# ============================================================================
#
# ---- 攻击：三段式（按 J / 左键）----
# ⭐ 三段时长是这套手感的命门，调参时只改这里：
#   ·前摇 0.16s = 玩家能"看清自己在做什么"，也够守卫走过来打断
#   · 命中 0.09s= 判定窗口，太长会打到不存在的目标
#   · 后摇 0.26s = 惩罚连打；这段时间还能微调方向但跑不开
#   · 冷却 0.12s = 在后摇之后，让"打空一下"有明确的手感断点
ATK_WIND     = 0.16
ATK_ACT      = 0.09
ATK_REC      = 0.26
ATK_CD       = 0.12
# ⭐ 攻击范围（身前单向）：62px。比容器的 hit 半径(46~54)宽 ——
#   玩家不需要贴到像素级才打得到，但要够不到"隔着台面"的容器。
ATK_REACH    = 62.0
# ⭐ 攻击能打到的垂直容差：56px（够覆盖同层和上下层台面差 91px 的一半 → 同层才行）
ATK_DY       = 56.0
# ⭐ 击退参数：够把他推开一段，但⛔ 不能推穿墙（clamp 会兜住）
ATK_KNOCK    = 260.0
ATK_STUN     = 0.45         # 硬直 0.45s ≈ 露娜能拉开 135px
# ⭐⭐ 攻击打**容器**与打**守卫**是两个结果，别混成同一个键：
#   · 打守卫 = 击退 + 硬直（控场，不掉血 —— 他是"押送者"不是敌人）
#   · 打容器 = 撬开/打翻，按容器类型给不同噪声
#   同一次挥击若同时够到两者（贴着罐子站在他面前）→ **两个都结算**，
#   因为那是玩家自己选的站位，代价理应一起付。
# ============================================================================
#
# ---- 冲刺（按 K / 右键）----
# ⭐ 冲刺不是"跑得更快" —— 潜行时 RUN 才是快的。冲刺的价值是**穿过去**：
#   无敌帧期间被抓判定失效，可以从微波炉身上碾过去。
DASH_TIME    = 0.20         # 持续 0.20s
DASH_SPEED   = 620.0        # 期间速度（比 RUN 300 快一倍）
DASH_INV     = 0.26         # ⭐ 无敌帧比持续时间长 0.06s —— 出手那一瞬就生效
DASH_CD      = 1.30# 冷却 1.3s（⛔ 短于1.0 就能连穿，守卫变摆设）
# ⭐ 冲刺**不产生任何噪声**（它是移动不是动作）——
#   这点是它和攻击的根本区别：攻击换战果，冲刺换位置。

# ⛔ 微波炉的巡逻段/速度/视野/听觉/警戒涨速**全部逐档**（见 NIGHTS）。
#    这里只留两条不分档的：垂直容差、抓捕半径。
MW_SIGHT_DY = 120.0        # 视野垂直容差（不分档 —— 改了会让三档手感一起变）
                           # ⭐ 2026-10-03：110 → 120。冰箱 QTE 改成站上桌面（y=488）后，
                           #   她（488）与地板上的微波炉（599）dy=111 —— 原值 110 差 1px 刚好"看不见"，
                           #   等于在它头顶撬冰箱零风险。120 让桌面成为"看得见但够不着"的一层
                           #   （厨房台 397 dy=202 仍是安全高低差，高处优势保留）。
MW_CATCH_R  = 52.0          # 抓捕半径（不分档 —— 这是"被抓住了"的判定，不该随难度漂）
ALERT_DECAY = 0.8           # 脱离视野每秒掉多少（不分档 —— 掉得快就没"绕开"这件事了）

ACTOR_H = 132.0             # ⭐ 露娜在关卡里的高度（逻辑像素），反推缩放系数
BODY_W  = 62.0              # 碰撞体宽度（比视觉窄，手感更好）

# ---- 容器 & 噪音（Ronny 2026-10-03：「吃的放在容器里，敲碎会惊动警卫」）----
# ⭐ 为什么是"累积值"而不是"一敲就警觉满"：一敲就满的话玩家只敢敲一次，
#   游戏退化成"敲一下立刻跑"，完全没有取舍。累积 + 衰减才有
#   「一路小心慢慢摸」和「快速砸开三个然后冲回窝」两条路。
NOISE_MAX   = 0.62          # ⭐ 贴着他耳朵敲，一次满 0.62 → 再两下就锁死
# ⭐⭐ frenzy（疯狂追踪）时长（Ronny 10-04「罐子一破警卫直接疯狂追踪」）
#   ⛔ 别设成"永久"：玩家一旦触发就只能重开档，那是不可接受的失败设计。
#   ⛔ 也别设太短：9 秒是他从东头冲到西头再折回来的量级，够跑但跑不轻松。
#   ✅ 提前解除：跑回允许区（x < border_x）**且手上没有东西** → 他认为事情过去了
FURY_SECONDS = 9.0
NOISE_DECAY = 0.30          # ⛔⛔ 死常量，**全项目零引用**（实测 grep 只有这一行）。
                             #   真正生效的衰减是 ALERT_DECAY(0.8/秒)，不是这个 0.30。
                             #   ⛔ 别照这条注释去推演"回一趟窝噪声掉多少"—— 会算错 2.6 倍。
                             #   保留只为兼容旧引用；新逻辑一律读 ALERT_DECAY。
MW_HEAR_R   = 420.0         # ⭐ 听觉半径。⛔ 不能开大：室内可活动区宽 770px，开到 560 就是“全室都听见”，噪声机制等于没有。
                             # 420 让它变成位置相关的战术资源：微波炉走到东边时，西侧台面的容器就能安静顶掉。
SNEAK_SPEED = 108.0         # 潜行速度（正常 300）—— 36%，与桌宠侧 sneak 的 stride 同比例

# ============================================================================
# ⭐⭐ investigate（查看声源）—— Ronny 2026-10-04 拍板「方向二」
#
# ⛔ 为什么必须有它（这是分四档容器逼出来的空洞，不是凭空加的功能）：
#   ALERT_DECAY = 0.8/秒，而"一次只能拿一件"要求每趟回窝 3~4 秒。
#   实测（2026-10-04 推演）：plate 档 0.26 的噪声，即使贴着守卫敲，
#   alert 峰值也只有 0.26，回窝路上**必然衰减归零**。
#   → plate 档"永远看不到后果"，成了哑档：分档做了，手感做了，但玩起来没意义。
#
# ✅ investigate 补的是"噪声的**位置后果**"，不是"数值后果"：
#   听到够响的声音 → 他**离开巡逻位走过去看** → 到达后环顾 → 回巡逻。
#   ⭐ 这样 plate 有了明确功能（惊动他、挪开他、制造窗口），
#     且**不需要让 alert 堆满**，所以不跟 frenzy 抢戏（frenzy 才是"堆满"级事件）。
#
# ⛔ 三条不变量（别改坏）：
#   ① 速度必须 < RUN_SPEED(300)。他是在"查看"不是"追杀"，
#      玩家永远跑得掉 —— 否则等于凭空多了一个追不上也躲不掉的压力源。
#   ② 目标 x 必须夹进可活动区，不能走出房间（VW - 体型）。
#   ③ 到达即结束（一次性），⛔ 不能反复横跳 —— 否则变成"他跟着噪声跳舞"，
#      玩家会用噪声把他当导航，潜行策略整个崩掉。
INVEST_ALERT   = 0.20        # 门槛：这次的声响够不够让他走过去看一眼
INVEST_SPEED   = 165.0       # 查看速度（patrol 的 1.7 倍，chase 的 0.6 倍）
INVEST_LINGER  = 0.85        # 到达后环顾多久再回巡逻
INVEST_RADIUS  = 30.0        # 多近算"到了"（小于就停 —— 到位判定，别让他来回抖）
# ⭐⭐ INVEST_HOLD：听见之后，"记得要去看看"能维持多久。
#   ⛔⛔ 为什么必须有这个独立记忆（2026-10-04 实测踩出来的）：
#     拿【瞬时 alert】当触发条件是错的 —— alert 每秒衰减 0.8，
#     plate 档 0.26 的噪声在 0.33 秒内就掉到门槛以下。
#     实测：敲完第0.5 秒 alert 已归零，investigate 一次都没触发（invest_x 全程 None），
#     守卫只是在正常踱步（位移 378px = 巡逻，不是查看）。
#   根因与"plate 成哑档"是同一个：**噪声是事件，衰减是状态，用同一个变量耦合必然互相吃掉**。
#   ✅ 所以"听到"这件事要独立记住一小会儿（HOLD），判断"该不该去看"用事件强度，
#      不再用那个正在衰减的 alert。
INVEST_HOLD    = 0.60# 触发记忆维持秒数（够他反应过来迈腿，又不至于赖着不走）


# ⭐⭐ 2026-10-04 补 sneak / tease：
#   ⛔ 漏了它们的后果是**静默兜底** —— 绘制处写的 `self.imgs.get(l.act) or self.imgs["idle"]`，
#     拿不到帧就画 idle。所以「潜行」和「挥击」明明 pick_action 返回对了，画面上却是
#     一张站姿死图（Ronny：「潜行没实装」「露娜还是不会攻击」同一根因）。
NEED_ACTIONS = ["idle", "walk", "human_run", "jump", "fall", "climb", "land",
                "sneak", "tease"]

# ---- 游戏专用素材（2026-10-03 派单 35 回传）----
# ⭐ 放在 自研引擎/assets_game/，不进 packs/ —— 微波炉不是桌宠角色，不该进桌宠包。
GAME_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets_game")
GAME_FPS = {"mw_walk": 12.0, "run_carry": 24.0}
# ⭐ 素材的**原始朝向**（+1 朝右 / -1 朝左），实测自素材本身，不是猜的：
#   mw_walk 素材朝左（能看到侧脸和制服前襟，尾巴在右后）→ -1
#   run_carry 素材朝右（脸朝右，鱼在右边的嘴里）    → +1
# ⛔ 之前写 `if face < 0: mirror` —— 那只在"素材朝右"时才碰巧正确。
#   微波炉素材朝左，所以它 face=1（该朝右）时**没被镜像**，等于拿屁股对着玩家（Ronny 实机反馈）。
#   ✅ 改成"和素材原始朝向不一致才镜像"，两套素材共用一条规则。
GAME_SRC_FACE = {"mw_walk": -1, "run_carry": 1}

# ============================================================================
# ①之二、三档夜晚（2026-10-03）
#
# ⭐ 难度不是"调一个数"就能表达的东西，它由四个维度一起拧出来，
#   单一维度拧到底会变成"数字变难受"而不是"局面变难"：
#     · 禁区有多大（BORDER_X 越靠左 = 可偷的地方越大）
#     · 微波炉多快多警觉（追不追得上、能不能提前绕开）
#     · 赃物摆在哪（摆得深 = 必须深入 = 必然路过它）
#     · 运力够不够（RUN_SPEED vs MW_CHASE_SPEED 决定"能不能全身而退"）
# ============================================================================

# ============================================================================
# ⭐ 2026-10-04 三档重排（Ronny：「不要所有东西都放罐子里」+「攻击/冲刺技能」）
#
# ⭐⭐ 重排的核心原则：**难度 = 价值**，三档都要满足
#   「玩家想要更多价值 → 必须冒更大风险 → 风险是玩家自己选的」。
#   具体到摆法：
#   · loose  放在【浅处】（餐桌靠西、地板）—— 顺手拿，不值得为它冒险
#   · plate  放在【中段】（厨房台）—— 要看时机
#   · jar    放在【最深处】（东端台面 / 冰箱正对面）—— 必须深入敌区，
#            而且一破就是 frenzy。**它必须最值钱**，否则没人碰（见 KIND_TABLE 注释）
#
# ⛔ 每档都至少留一个 loose 在浅处：初学者要有"稳的"选项，
#   否则一进档就逼玩家点罐子 → 第一关就 frenzy → 挫败感直接劝退。
# ============================================================================
_NIGHT1 = [
    # —— 初更：他踱得很慢（75px/s），宽松教学档 ——
    # ⭐ 2026-10-04 随新布局（茶几 430~700 / 台 760~1060 / 冰箱 1120）全部重摆
    {"x": 470,  "y": 488, "icon": "yolk",      "kind": "loose"},   # 茶几西：伸手就拿
    {"x": 660,  "y": 488, "icon": "blueberry", "kind": "loose"},   # 茶几东
    {"x": 820,  "y": 380, "icon": "salmon",    "kind": "plate"},   # 厨房台：掀盖
    {"x": 1000, "y": 380, "icon": "yogurt",    "kind": "jar"},     # ⭐ 唯一 jar，放最东
    {"x": 900,  "y": 599, "icon": "pumpkin",   "kind": "plate"},   # 地板·台下
]
_NIGHT2 = list(STASHES)
_NIGHT3 = [
    # —— 凌晨三点：他追得最快（282）、禁区最深（360）——
    # ⭐ 三个 jar 全压在东端= 必须一路深入到最里面。
    #   这是"高收益必须高风险"的最直白表达：想要 4+4+4=12 就得开三次 frenzy。
    {"x": 450,  "y": 488, "icon": "yolk",       "kind": "loose"},  # 茶几西：唯一的喘息点
    {"x": 680,  "y": 488, "icon": "salmon",     "kind": "plate"},
    {"x": 800,  "y": 380, "icon": "chicken",    "kind": "plate"},
    {"x": 900,  "y": 380, "icon": "yogurt",     "kind": "jar"},    # ⭐ jar
    {"x": 1020, "y": 380, "icon": "pumpkin",    "kind": "plate"},
    {"x": 830,  "y": 599, "icon": "blueberry",  "kind": "loose"},  # 地板：绕后拿
    {"x": 1060, "y": 599, "icon": "watermelon", "kind": "jar"},    # ⭐ jar（全图最深，冰箱脚下）
]

NIGHTS = [
    {
        "name": "初更",
        "sub": "厨房灯刚灭，微波炉还没开始踱步",
        "stashes": _NIGHT1,
        "border_x": 500,
        # ⭐ 2026-10-04 重排：厨房台改成**架空薄台面**（顶 397 / 底 435），
        #   微波炉（161px 高，599−161=438 > 435）能从台面**下方**穿行 ⇒ 不再穿模。
        #   ⭐ 所以巡逻段可以横跨 700~1100 这整条，包括茶几右边与厨房台下方。
        "patrol": (820, 1108), "patrol_speed": 75.0,
        "chase_speed": 205.0, "sight": 240.0, "hear": 110.0,
        "alert_gain": 1.5, "alert_hear": 0.8,
    },
    {
        "name": "深夜",
        "sub": "正常的夜里。它开始踱步了。",
        "stashes": _NIGHT2,
        "border_x": 430,
        "patrol": (790, 1108), "patrol_speed": 95.0,
        "chase_speed": 250.0, "sight": 300.0, "hear": 150.0,
        "alert_gain": 1.9, "alert_hear": 0.95,
    },
    {
        "name": "凌晨三点",
        "sub": "整层楼只有冰箱在响。吊柜顶上那几样最好。",
        "stashes": _NIGHT3,
        "border_x": 360,
        # ⭐ 东端收到 1180：冰箱移到 1120~1250 之后，巡逻右端**不能进冰箱体**
        #   （冰箱是落地实心，y1=599 —— 与旧茶几同性质，会穿模）。
        "patrol": (760, 1108), "patrol_speed": 120.0,
        "chase_speed": 282.0, "sight": 350.0, "hear": 180.0,
        "alert_gain": 2.5, "alert_hear": 1.3,
    },
]
# ⛔ 三档的"跑得掉"是硬底线：MW_CHASE_SPEED 必须 < RUN_SPEED(300)。
#    最紧的一档 282 只比露娜慢 18px/s —— 跑掉了但几乎跑不掉，就是"险"。
NIGHT_GAP = 0.30          # 结算：用时超过"带回数 × 这个秒数"就扣分


# ============================================================================
# ①之三、旁白（露娜的自我戏剧化）
#
# ⭐ 用法上的规矩：旁白只承载**她怎么想**，⛔ 不承载**她为什么这么做**。
#   动机是"她饿了想偷东西"，中二只体现在那句"整个厨房都是我的"。
#   —— 反过来写成"为了执行暗黑使命她必须潜入"，就假了。
#
# ⛔ 文案规矩：短、口语、别写成诗句。别用「吾」「汝」「宿命」这类真中二，
#    也不要用感叹号堆情绪。她是**觉得自己在做大事**，不是在演讲。
#    一篇最多一句最满的，其余收着。
# ============================================================================

NARRATION = {
    "enter": [
        "夜，安全。",
        "厨房的灯灭了。该我了。",
        "凌晨三点。整层楼只有冰箱在响。",
    ],
    "wait": [
        "还没到时间。",
        "再等等。",
        "窝里这点不够。",
    ],
    "cross": [
        "规矩我懂。但今晚例外。",
        "再往前一步，就算越界了。",
        "这条线我熟。闭着眼都能走。",
    ],
    "steal": [
        "到手。",
        "这个归我。",
        "战利品，入库。",
    ],
    "empty": [
        "这儿没东西。",
        "空的。白跑一趟。",
    ],
    # ⭐ fury：破罐引燃全场后的旁白（Ronny 10-04）。
    #   这几句的任务是把"我刚干了一件不可挽回的事"说清楚 ——
    #   玩家要立刻明白这不是普通被发现，是自己点的火。
    "fury": [
        "玻璃碎了——它听见了。",
        "完了。整层都听见了。",
        "这声响藏不住。",
    ],
    # ⭐ fury_far：破罐了但离得远，他只听到闷响 → 没进 frenzy。
    #   这几句是把"没炸起来"讲清楚，别让玩家以为技能失灵了。
    "fury_far": [
        "…远处响了一下。听不清。",
        "他好像没听清。趁现在。",
        "闷响。没惊动他。",
    ],
    "spotted": [
        "⚠ 有人看到了。",
        "被盯上了。跑。",
        "它转过来了。",
    ],
    "caught": [
        "……下次一定。",
        "又是这只微波炉。",
        "押送我的是微波炉本人。",
    ],
    "home": [
        "带回来了。",
        "今晚到此为止。",
        "这次收获还行。",
    ],
    "finish": [
        "全部搬完了。收工。",
        "柜子空了。撤。",
    ],
}


# ============================================================================
# ② 资源加载
# ============================================================================

def _load_needed(pack, names):
    """只加载本模块用得到的动作（全量 load_frames 会把 24 个动作都读进内存）"""
    out = {}
    for n in names:
        act = pack.actions.get(n)
        if act is None:
            continue
        imgs = []
        for i in range(act.frames):
            p = pack.frame_path(n, i)
            if not os.path.exists(p):
                continue
            im = QImage(p)
            if not im.isNull():
                imgs.append(im)
        if imgs:
            out[n] = imgs
    return out


def _load_icons(pack_root, names):
    d = os.path.join(pack_root, "ui")
    out = {}
    for n in names:
        p = os.path.join(d, n + ".png")
        if not os.path.exists(p):
            continue
        im = QImage(p)
        if not im.isNull():
            out[n] = im
    return out


# ============================================================================
# ③ 玩家：露娜
# ============================================================================

class Luna:
    def __init__(self, x, y, sneak_ok: bool = False):
        # ⭐ sneak_ok：潜行专属动作 sneak 是否**真的能播**（派单 37 素材在途）。
        #   由窗口在构造时算好传进来 —— ⛔ Luna 自己拿不到窗口/包对象，别在它里面查。
        self.sneak_ok = sneak_ok
        self.x = x
        self.y = y              # ⭐ 脚底中点
        self.vx = 0.0
        self.vy = 0.0
        self.face = 1           # 1 朝右 / -1 朝左
        self.on_ground = False
        self.on_ladder = False
        self.act = "idle"
        self.t = 0.0            # 当前动作的播放时间
        self.carrying = []      # 这趟偷到的赃物
        self.escort = False     # 正被押送回窝（演出中）
        # ⭐⭐ 动画是否在推进。**不要用 vy/vx 判** —— 爬梯时这两个值被强制清零
        #   （爬梯是位置直改，不靠速度积分），用它们判会让爬梯动画永远停在第 0 帧，
        #   看上去就是"爬梯动作没装上"（Ronny 2026-10-03 实机反馈）。
        self.moving = False
        self.climb_down = False # 下梯（用于把 climb 帧上下翻转）
        self.sneak = False      # 潜行中
        self.punch = 0.0        # ⭐ 挥击中（敲容器瞬间播爪的动作），>0 时优先于移动动作
        # ⭐ 跳键闩锁：必须【松开再按】才能再跳。
        #   没有它的话按住 W 会落地即起跳一路连跳（实测踩上台面后立刻弹到 y=379），
        #   爬梯到顶也会自动弹一下 —— 玩家会觉得"我没让它跳"。
        self.jump_latch = False
        # ⭐⭐⭐ 攻击（Ronny 2026-10-04「给露娜设计攻击技能」）
        #三段式：前摇 windup → 命中 active → 后摇 recover
        #   为什么必须有前摇和后摇 —— 这是整个技能设计的核心：
        #   · 前摇 = **可被打断的窗口**。守卫在前摇里碰到她 = 白打。
        #     没有前摇的话她能无脑连打，守卫就只是个沙袋。
        #   · 后摇 = **不能连打**的窗口。防止"贴着它狂按"秒杀。
        #   ⛔ 三段都是"能力"而不是"惩罚"：前摇让玩家学会算距离，
        #       后摇让玩家学会"打一下就跑"，不是让玩家变笨。
        # 计时统一用「剩余秒数」往 0 减，⛔ 不用阶段枚举（枚举要 6 个字段，易错）
        self.atk_wind = 0.0    # 前摇剩余
        self.atk_act = 0.0     # 命中判定窗口剩余
        self.atk_rec = 0.0     # 后摇剩余
        self.atk_cd = 0.0      # 冷却（打完之后才开始算，保证节奏可感）
        self.atk_hit_done = False   # ⭐ 本次攻击是否已结算过（防一帧多次判定）
        # ⭐⭐ 冲刺（2026-10-04）：短距高速 + 无敌帧
        self.dash_t = 0.0      # 冲刺剩余时间
        self.dash_i = 0.0      # ⭐ 无敌帧剩余（>0 时被抓判定失效）
        self.dash_cd = 0.0# 冷却
        self.dash_dir = 1      # 冲刺方向（快照，⛔ 不能读实时按键，冲刺中转向= 瞬移）

    # ---- 物理 ---------------------------------------------------------
    def update(self, dt, keys, room):
        if self.escort:
            return

        left = keys & {Qt.Key_A, Qt.Key_Left}
        right = keys & {Qt.Key_D, Qt.Key_Right}
        up = keys & {Qt.Key_W, Qt.Key_Up, Qt.Key_Space}
        down = keys & {Qt.Key_S, Qt.Key_Down}

        # ⭐ 潜行（按住 Shift）：慢、且不产生任何噪音。
        #   ⛔ 只在地面生效 —— 空中潜行没有意义（跳本身就有声），
        #   爬梯时也算了（梯子上本来就安全，见 Microwave.sense 的梯子豁免）。
        self.sneak = bool(keys & {Qt.Key_Shift}) and self.on_ground and not self.on_ladder

        # ⭐⭐ 技能冷却与无敌帧推进（2026-10-04）。
        #⛔ 只减这两类"没有阶段转移"的计时。
        #   ⛔⛔ 攻击三段（wind/act/rec）**不在这里减** —— 它们有阶段转移
        #   （前摇结束→命中，命中结束→后摇），由窗口层_night.py 的 _tick 推进。
        #   两处都减会出现"前摇只持续一半时间"，而且更难查的是
        #   窗口层的阶段判断会永远等不到 0（因为已经被这里减过了）。
        if self.atk_cd > 0.0:
            self.atk_cd = max(0.0, self.atk_cd - dt)
        if self.dash_cd > 0.0:
            self.dash_cd = max(0.0, self.dash_cd - dt)
        if self.dash_i > 0.0:
            self.dash_i = max(0.0, self.dash_i - dt)

        # ---------- 冲刺：独占整段位移 ----------
        # ⭐ 优先级最高：冲刺中**屏蔽一切普通移动**。
        #   不屏蔽的话玩家会一边冲刺一边按方向，冲刺就退化成"稍微快一点的跑"，
        #   无敌帧的意义（穿过守卫）也就没了。
        if self.dash_t > 0.0:
            self.dash_t = max(0.0, self.dash_t - dt)
            self.vx = 0.0
            prev_x = self.x
            self.x += self.dash_dir * DASH_SPEED * dt
            self.vy += GRAVITY * dt * 0.35     # ⭐ 冲刺中重力减半（滞空感）
            self.y += self.vy * dt
            if self.y >= FLOOR_Y:
                self.y, self.vy = FLOOR_Y, 0.0
                self.dash_t = 0.0# 落地即结束（冲刺是地面技）
            # 冲刺中不打伞：不能同时攻击
            if self.atk_wind > 0.0:
                self.atk_wind = 0.0
            # ⭐⭐ 冲刺也必须被桌布墙挡住 ——⛔ 别漏这一步。
            #   漏了的话玩家按住 D 冲刺会**直接穿过桌布**进餐桌里，
            #   而桌布是实心墙（渲染上是垂到地的整面布），穿模一眼假。
            #   判据与常速移动完全一致（prev_x 不在区里、这一帧进了区→ 钉回墙边）。
            if self.y > TABLE_TOP + LAND_TOL:
                m = BODY_W * 0.35
                _hit = lambda px: px + m > TABLE_X0 and px - m < TABLE_X1
                if _hit(self.x) and not _hit(prev_x):
                    self.x = (float(TABLE_X0 - m) if prev_x < TABLE_X0
                              else float(TABLE_X1 + m))
                    self.dash_t = 0.0          # 撞墙 = 冲刺结束（不给"贴墙滑行"）
            self._clamp_x(room)
            return

        # ---------- 攻击三段：这里只做【减速】，⛔ 不碰计时 ----------
        # ⛔⛔ 计时（wind/act/rec）由窗口层 _tick 推进，因为它们有阶段转移。
        #   在这里也减 = 减两次 → 前摇只剩一半，且窗口层等不到 0（阶段不转移）。
        if self.atk_wind > 0.0:
            self.vx *= 0.82# ⭐ 前摇有减速（不是完全定住，但明显走不动）
        elif self.atk_act > 0.0:
            self.vx *= 0.70
        elif self.atk_rec > 0.0:
            self.vx *= 0.86            # 后摇几乎还能动一点（不至于完全僵住）
        # ⭐ punch 只是"播 tease 动作"的计时，与三段并行递减（它没有阶段转移，
        #   所以放在这里减是对的）。⛔ 别把 punch 当攻击计时用 —— 它是表现层。
        if self.punch > 0.0:
            self.punch = max(0.0, self.punch - dt)

        # --- 梯子 ---
        lad = self._ladder_here(room)
        if lad is not None:
            # ⭐ 站在梯子上只按左右 = 蹬开梯子离开。
            #   ⛔ 不做这条的话她会【卡在梯子上】——上下键是"进出梯子"的语义，
            #   而左右键在爬梯分支里被吞掉，vx 恒为 0，玩家按 A/D 完全没反应。
            if (left or right) and not (up or down) and self.on_ladder:
                _, ytop, ybot = lad
                # ⭐⭐ 已经爬到台面边缘了 → 直接站上台，不要弹出去
                #   （Ronny 10-03 反馈的「爬空气」：之前这里无条件弹射，
                #     爬到不远就按上时会直接被弹出梯子变成自由落体）
                if self.y <= ytop + 46:
                    self.y = ytop
                    self.on_ladder = False
                    self.on_ground = True
                    self.moving = False
                    self.face = 1 if right else -1
                    return
                self.on_ladder = False
                self.moving = False
                self.climb_down = False
                self.face = 1 if right else -1
                self.vx = self.face * RUN_SPEED * 0.55
                self.vy = -240.0
                self.on_ground = False
                return
            _, ytop, ybot = lad
            # ⭐⭐ 站在梯子【端点】上时，方向键的含义要翻转 —— 否则会无限弹跳：
            #   爬到顶 → 退出爬梯站上台面 → 脚底仍在梯子范围内 → 按 W 又爬上去 →
            #   再被顶回台面 → 470↔467.5 反复弹（实测每帧交替）。
            #   ✅ 横板标准规则：站在顶端按【上】不再爬（改跳），按【下】才下梯；
            #      站在底端按【上】才上梯，按【下】无动作。
            on_ground_now = (not self.on_ladder) and self.on_ground
            at_top = on_ground_now and abs(self.y - ytop) < 2.0
            at_bot = on_ground_now and abs(self.y - ybot) < 2.0
            want_up = up and not at_top
            want_down = down and not at_bot
            if self.on_ladder or want_up or want_down:
                if not self.on_ladder:
                    self.x = lad[0]     # ⭐ 抓梯/抓布瞬间吸附到攀爬列（布面 = 吸进面内 8px）
                self.on_ladder = True
                self.vy = 0.0
                self.vx = 0.0
                self.jump_latch = bool(up)   # ⭐ 爬到顶时不许"自动弹一下"
                # ⭐ 爬梯时 vy 恒为 0，动画推进只能看这两个输入
                self.climb_down = want_down or (self.on_ladder and down and not up)
                self.moving = self.climb_down or (up and not at_top)
                if up and not at_top:
                    self.y -= CLIMB_SPEED * dt
                elif down and not at_bot:
                    self.y += CLIMB_SPEED * dt
                _, ytop, ybot = lad
                # 爬到顶 → 自动站上去
                if self.y <= ytop - 4:
                    self.y = ytop
                    self.on_ladder = False
                    self.on_ground = True
                    self.moving = False
                    self.climb_down = False
                # 爬到底 → 落地
                elif self.y >= ybot:
                    self.y = ybot
                    self.on_ladder = False
                    self.on_ground = True
                    self.moving = False
                    self.climb_down = False
                self._clamp_x(room)
                return
        else:
            self.on_ladder = False

        # --- 水平 ---
        dir_in = (1 if right else 0) - (1 if left else 0)
        if dir_in != 0:
            self.face = dir_in
        ctrl = AIR_CTRL if not self.on_ground else 1.0
        # ⭐ 潜行 = 慢 + 缓起缓停（快了就没有"蹑手蹑脚"的感觉）
        spd = SNEAK_SPEED if self.sneak else RUN_SPEED
        acc = 8.0 if self.sneak else 14.0
        target = dir_in * spd
        # 简单的加减速（不用加速度常数，直接向目标速度靠拢，灰盒够用）
        self.vx += (target - self.vx) * min(1.0, dt * (acc * ctrl))

        # --- 跳跃（⛔ 必须松开再按，见 jump_latch 注释）---
        if up and self.on_ground and not self.jump_latch:
            self.vy = -JUMP_V
            self.on_ground = False
            self.jump_latch = True
        if not up:
            self.jump_latch = False

        # --- 重力 + 单向平台 ---
        self.vy += GRAVITY * dt
        prev_y = self.y
        prev_x = self.x
        self.x += self.vx * dt
        self.y += self.vy * dt

        # ⭐⭐ 布墙（2026-10-03「桌子地形很奇怪」修复）：桌布全覆盖垂到地，背景里看着是实体，
        #   所以脚在桌面高度以下时不许从布区外撞进来（要过去只能扒布，或从桌面上走下来）。
        #   ⭐ 判据 = 身体矩形【上一帧不挨布、这一帧挨上】→ 钉回墙边。
        #     ⛔ 别用"上一帧在区外"判定 —— 人被钉在墙边时 prev 恰好落进边界，
        #       下一帧就被当成"已经在里面"放行（实测全速 0.5s 穿过整块布区）。
        #   已在布区里的人（蹬布跳出、爬到底落到地板）不受影响：挨着→挨着，自由走出。
        #   爬梯不走这里（爬梯分支已提前 return）。
        # ⭐ m 必须在**两个墙判定之外**赋值：冰箱墙那段的 y 条件是"在地板层"，
        #   与茶几布墙的 y 条件互斥，早先写在布墙分支里 → 冰箱分支取不到 → NameError。
        m = BODY_W * 0.35
        if self.y > TABLE_TOP + LAND_TOL:
            _hit = lambda px: px + m > TABLE_X0 and px - m < TABLE_X1
            if _hit(self.x) and not _hit(prev_x):
                self.x = float(TABLE_X0 - m) if prev_x < TABLE_X0 else float(TABLE_X1 + m)
                if abs(self.vx) > 1.0:
                    self.vx = 0.0        # 顶住墙就别再攒速度

        # ⭐⭐ 冰箱墙（2026-10-04）：冰箱挪到右墙独立段后成了**新的落地实心体**，
        #   而它**不在 PLATFORMS 里**（PLATFORMS 只有地板/茶几/台面/吊柜）
        #   ⇒ 布墙那套判据根本扫不到它。
        #   实测事故：从厨房台面(380)一路向右走出台面，会**穿过 1120~1250 的冰箱体**
        #   落在冰箱里（y=599, x=1218）—— 视觉上整个人嵌进冰箱。
        #   ⭐ 这跟 MEMORY 里「判据只覆盖它知道的那一半 = 假绿」同源：
        #     穿模自测第一版只扫 PLATFORMS，报「三档全 OK」，其实漏判了冰箱。
        #   ✅ 修法：冰箱也做撞侧判定。
        #   ⛔⛔ 这里**不能照抄布墙那套「上一帧不挨、这一帧挨」的边沿触发** ——
        #     边沿触发要求"实体宽度 >> 身体半宽 m"。冰箱只有 130px，m=21.7 就占了 1/6，
        #     而横向是**渐进加速**（每帧只位移 4~5px）⇒ 角色中心还在 1098 时身体右缘已经
        #     触到 1120（1098+21.7=1120.0），判据在**入口那一帧就漏掉**，之后全程"挨→挨"
        #     边沿永不触发 → 一路飘进冰箱（实测落点 x=1200.7, y=599）。
        #     这跟 MEMORY 里「桌布布墙别用上一帧在区外判定」同源，但冰箱是**窄实体 + 慢速**，
        #     边沿判据在这里根本不成立。
        #   ✅ 正确口径：判"进入"用**身体中心点**落进实体区间（电平判定，不依赖 prev），
        #     钉回时再按 m 留出身体半宽。电平判定不怕慢速，也不怕实体窄。
        #   ⛔ y 条件必须排除「站在冰箱顶上」：顶上 y≈_fy_top，此时中心也在 1120~1250 内，
        #     不排除就会把站在冰箱上的人判成"撞墙"给弹回地板。
        _fx0, _fx1 = float(FRIDGE["x"]), float(FRIDGE["x"] + FRIDGE["w"])
        _fy_top = FLOOR_Y - FRIDGE["h"]
        if _fy_top + LAND_TOL < self.y < FLOOR_Y + LAND_TOL \
                and _fx0 <= self.x <= _fx1:
            self.x = float(_fx0 - m) if self.x - _fx0 < _fx1 - self.x else float(_fx1 + m)
            if abs(self.vx) > 1.0:
                self.vx = 0.0
        # ⭐ 冰箱顶的落点**不能在这里单独结算** —— 下面第 828 行有 `self.on_ground = False`，
        #   单独结算会被无条件抹掉（踩过：判据看着对，人还是往下穿）。
        #   ✅ 所以冰箱顶走"伪平台"路线：塞进下面那个落点循环，一起参与"取最高"的比较。

        self.on_ground = False
        if self.vy >= 0:
            # ⭐⭐ 单向平台落地的正确写法。踩过的两个坑：
            #   ① 只判"这一帧穿过了顶面"（prev_y <= y0 <= y）→ **已经站在平台上时会漏检**，
            #      因为贴着顶面时根本没有"穿过"这回事 → 角色在 y0↔y0+1.6 之间隔帧抖。
            #      ✅ 改成"上一帧还在顶面上方（含站着）+ 这一帧到了顶面下方"。
            #   ② 按 platforms 的书写顺序取第一个命中 → 高速下落时会穿过料理台直接落地板。
            #      ✅ 改成取【最高】的那个（y0 最小）—— 才是真正先碰到的那层。
            hit = None
            for (x0, y0, x1, y1) in room.platforms:
                if not (x0 - BODY_W * 0.35 <= self.x <= x1 + BODY_W * 0.35):
                    continue
                if prev_y <= y0 + LAND_TOL and self.y >= y0:
                    if hit is None or y0 < hit:
                        hit = y0
            # ⭐ 冰箱顶也参与"取最高"：冰箱是平台不是墙（台面/吊柜落到顶上合法），
            #   但它不在 PLATFORMS 里（那儿只有地板/茶几/台面/吊柜）⇒ 必须在这里补。
            if _fx0 - m <= self.x <= _fx1 + m \
                    and prev_y <= _fy_top + LAND_TOL and self.y >= _fy_top:
                if hit is None or _fy_top < hit:
                    hit = _fy_top
            if hit is not None:
                self.y = float(hit)
                self.vy = 0.0
                self.on_ground = True

        self._clamp_x(room)
        self.moving = abs(self.vx) > 1.0 or abs(self.vy) > 1.0
        if self.y > VH + 200:                            # 掉出世界（不该发生，兜底）
            self.x, self.y = NEST_X0 + 70, FLOOR_Y
            self.moving = False

    def _clamp_x(self, room):
        half = BODY_W * 0.5
        self.x = max(half + 8.0, min(VW - half - 8.0, self.x))

    def _ladder_here(self, room):
        # ⭐⭐ 攀爬面（桌布整面）优先于点梯：布是垂到地的一整面，面上任意 x 都能扒。
        #   返回的 x 已吸附进布面（距边缘 8px）—— 抓布那一下有个"扒上去"的吸附感。
        for (x0, x1, ytop, ybot) in room.ladder_zones:
            if x0 - 26.0 <= self.x <= x1 + 26.0 and (ytop - 10.0) <= self.y <= (ybot + 10.0):
                return (min(max(self.x, x0 + 8.0), x1 - 8.0), ytop, ybot)
        for (xc, ytop, ybot) in room.ladders:
            if abs(self.x - xc) < 30.0 and (ytop - 10.0) <= self.y <= (ybot + 10.0):
                return (xc, ytop, ybot)
        return None

    # ---- 技能 ---------------------------------------------------------
    def try_attack(self) -> bool:
        """起手一次攻击。返回是否成功起手。

        ⭐ 三道闸门，任一不满足就**静默拒绝**（不给提示）：
          ① 冷却没转好   ② 已经在攻击中（三段任一段都在跑）
          ③ 冲刺中（冲刺独占）
        ⛔ 不检查"够不够得到目标" —— 那是命中窗口的事。
          在这里判"够不到就不播"会让玩家按了没反应，以为按键坏了。
        """
        if self.atk_cd > 0.0:
            return False
        if self.atk_wind > 0.0 or self.atk_act > 0.0 or self.atk_rec > 0.0:
            return False
        if self.dash_t > 0.0:
            return False
        self.atk_wind = ATK_WIND
        self.atk_act = 0.0
        self.atk_rec = 0.0
        self.atk_hit_done = False
        self.punch = ATK_WIND + ATK_ACT + ATK_REC   # ⭐ 复用 tease 动作当挥击演出
        return True

    def try_dash(self, dir_in: int) -> bool:
        """起手一次冲刺。dir_in = 1 右 / -1 左 / 0 = 沿当前朝向。"""
        if self.dash_cd > 0.0 or self.dash_t > 0.0:
            return False
        # ⛔ 攻击三段期间不能冲刺（两个都是"决定"，不能同时做）
        if self.atk_wind > 0.0 or self.atk_act > 0.0 or self.atk_rec > 0.0:
            return False
        if dir_in == 0:
            dir_in = self.face
        self.dash_dir = 1 if dir_in >= 0 else -1
        self.face = self.dash_dir
        self.dash_t = DASH_TIME
        # ⭐ 无敌帧比位移窗口略长：出手即生效，落地仍有效
        self.dash_i = DASH_INV
        self.dash_cd = DASH_TIME + DASH_CD
        return True

    def in_atk_window(self) -> bool:
        """当前是否在【命中判定窗口】内 —— 只有这时才结算命中。"""
        return self.atk_act > 0.0

    # ---- 表现 ---------------------------------------------------------
    def pick_action(self):
        # ⭐ 挥击优先（Ronny 10-03 反馈「露娜还是不会攻击」）：
        #   根因是 pick_action 只看移动状态 —— 她**站着不动**时按 E 根本不切动作。
        #   ⛔ 而不是"没有挥击素材"（tease 已经装上了）。
        if self.punch > 0.0:
            return "tease"
        # ⭐⭐ 冲刺表现（Ronny 10-04）：用 human_run —— 那是她全速跑的素材，
        #   语义上最接近"一口气冲出去"，⛔ 别用 sneak（那是慢的）。
        #   ⛔ 拿东西时**不**用 run_carry 播冲刺：那素材肩上有东西的姿势，
        #     冲刺是无负重爆发，混用会让"冲刺"看起来像"负重快跑"。
        if self.dash_t > 0.0:
            return "run_carry" if self.carrying else "human_run"
        if self.on_ladder:
            return "climb"
        if not self.on_ground:
            return "jump" if self.vy < -40 else "fall"
        if abs(self.vx) > 34.0:
            # ⭐ 三分支优先级：拿着东西 > 潜行 > 普通跑
            #   ⛔ 别让潜行播 human_run（那是冲刺动作，播出来等于告诉她"我在全速跑"）。
            if self.carrying:
                return "run_carry"
            if self.sneak:
                # ⭐ 潜行优先用 sneak 动作（派单 37 在途）；缺帧时退回 walk。
                #   ⛔ 别无条件用 "sneak" —— core 会把空帧列表塞进 anim，
                #     anim.finished 永不触发 → 角色永久卡死。
                return "sneak" if self.sneak_ok else "walk"
            return "human_run"
        return "idle"


# ============================================================================
# ④ 执法者：微波炉
# ============================================================================

class Microwave:
    """⭐ 设定：它追露娜【不是】为了护着 koko，是为了维护秩序 ——
    它认为每只猫都该待在自己的区域里。所以它不会"攻击"，只会"押送回去"。

    灰盒表现：一个深色方块 + 门缝里透出的一道橙光（朝向就是那一面）。
    """

    def __init__(self, cfg: dict):
        p0, p1 = cfg["patrol"]
        self.x = (p0 + p1) / 2
        self.y = FLOOR_Y
        self.face = 1
        self.dir = 1
        self.alert = 0.0
        self.state = "patrol"       # patrol | chase | return
        self.w = 96.0
        self.h = 78.0
        # ⭐ 微波炉的体型/运动能力（Ronny 2026-10-03：「给微波炉能爬梯和跳跃的能力，上点强度」）
        #   设定他 183cm、露娜 150cm → 本体高 161px（素材按这个高度抽的）。
        #   ⛔ 别再用旧的 78px —— 那是灰盒方块时代的遗留，只影响视野起点与兜底绘制。
        self.body_h = 161.0
        self.climb_speed = 78.0    # 爬梯速度（比露娜 150 慢一半 → 留给她逃脱的窗口）
        self.jump_v = 470.0        # 起跳 → 跳高 = 470²/(2*2000) ≈ 55px（够不平台上 178px 的料理台）
        self.vy = 0.0
        self.on_ground = True
        self.jump_cd = 0.0         # 跳跃冷却
        self.on_ladder = False    # ⭐ 他是否正在梯子上（爬梯状态，⛔ 不能靠 y 判断）
        self.climb_t = 0.0        # ⭐⭐ 2026-10-04 补回：原来这行被黏在上一行注释末尾，
                                  #   字段**从未真正初始化**。全项目当前无读写点（已绕过），
                                  #   但代码与注释不一致 = 下次谁写 self.climb_t 就 AttributeError。
        # ⭐⭐ investigate（2026-10-04，方向二）：听到够响的声音后离开巡逻位走过去看
        #   ⛔ 与 chase/patrol 的关系：它是 patrol 的**子行为**，不是第三种"警报等级"。
        #     优先级永远低于 chase —— 玩家一旦被发现，查看立刻让位（不许"一边追一边查看"）。
        self.invest_x = None      # 要去查看的声源 x（None = 不在查看）
        self.invest_linger = 0.0  # 到达后的环顾倒计时
        # ⭐⭐ invest_hold：**独立于 alert** 的"听到了、值得去看"记忆。
        #   ⛔ 绝不复用 alert 当触发源（实测会因衰减太快而永不触发，见 INVEST_HOLD 注释）。
        self.invest_hold = 0.0
        # ⭐ 难度参数全部来自档位配置（不是模块常数）
        self.p0, self.p1 = float(p0), float(p1)
        self.patrol_speed = float(cfg["patrol_speed"])
        self.chase_speed = float(cfg["chase_speed"])
        self.sight = float(cfg["sight"])
        self.hear = float(cfg["hear"])
        self.alert_gain = float(cfg["alert_gain"])
        self.alert_hear = float(cfg["alert_hear"])
        # ⭐ 踱步节奏：走一段 → 停下环顾（转身）→ 再走。
        #   没有它的话微波炉会长时间背对同一个方向，露娜可以站在它背后大摇大摆地偷
        #   （实测：固定巡逻时 alert 一直是 0）。猫不是摄像头，但也不是扫描仪，
        #   给它一个"走走停停回头看"的节奏，玩家就有可预判的窗口期。
        self.walk_t = 2.0
        self.pause_t = 0.0
        self.hear_x = None         # 最近一次听到的声源 x（让他转头）
        # ⭐⭐ frenzy（疯狂追踪）—— Ronny 2026-10-04「罐子一破，警卫会直接疯狂追踪」
        #   与 chase 的区别不是"更凶一点"，是**性质变了**：
        #   · chase 会被 ALERT_DECAY 慢慢降回 patrol，露娜绕开就能甩掉
        #   · frenzy **不衰减**，且**锁定**露娜最后已知位置（不再依赖视野）
        #   · 持续到玩家【跑回允许区并放下一件东西】为止 —— 给一条明确的解除路径，
        #     否则玩家一旦触发就只能重开档，那是不可接受的
        self.fury = False
        self.fury_t = 0.0          # >0 = 还在 frenzy 计时内
        self.fury_x = None# 锁定的目标 x（他往那冲）
        self.stun = 0.0            # 被露娜攻击击退后的硬直
        self.knock_vx = 0.0        # 击退速度（会衰减）

    def sense(self, luna) -> float:
        """返回察觉强度：1.0 正面看见 / 0.5 背后听见 / 0.0 毫无察觉

        ⭐ 为什么要有"背后听见"这一档：只有正面视野时，露娜只要绕到微波炉背后
        站着就绝对安全（实测：她站 x=900、微波炉朝右走到 950，alert 一直是 0）。
        猫不是摄像头，近到 150px 不可能没反应 —— 但也不该跟正面一样快，
        否则"从背后溜过去"这个玩法就没了。

        ⭐⭐ 「在梯子上 = 安全」（抄 Lode Runner：守卫不会追到玩家所在的梯格）。
        这是那游戏最关键的一条：它让**高处**有了明确回报，玩家会主动往高处钻。
        顺带省掉微波炉的爬梯/拎起素材 —— 他只在地板上巡逻就够了。
        """
        # ⭐⭐ 梯子上不再是"完全安全"（Ronny 10-03：给微波炉爬梯能力，上点强度）
        #   从 0.0 改成 0.3 —— 他爬上来要时间（速度只有露娜一半），
        #   所以爬梯是**相对安全**而不是绝对安全：能拖住你，拖不死你。
        if luna.on_ladder:
            return 0.3
        dx = (luna.x - self.x) * self.face
        if abs(luna.y - self.y) >= MW_SIGHT_DY:
            return 0.0
        if -20.0 <= dx <= self.sight:
            return 1.0
        if abs(luna.x - self.x) <= self.hear:      # 在背后但很近
            return 0.5
        return 0.0

    def update(self, dt, luna, room):
        # ⛔ 越界才追：露娜退回允许区内，微波炉就当没看见 —— 这是"允许区机制"的核心
        trespass = luna.x > room.border_x and not luna.escort

        # ⭐⭐ frenzy 计时与解除（2026-10-04）
        #   解除条件 =玩家跑回允许区**并放下一件东西**（回窝）。
        #   ⛔ 不能只靠时间到 ——那样玩家在 frenzy 里等几秒就没事了，
        #     "疯狂追踪"就退化成"追一会儿"，失去压迫感。
        if self.fury_t > 0.0:
            self.fury_t -= dt
            if luna.x < room.border_x and not luna.carrying:
                # 回到安全区且手上空了 → 他"认为事情过去了"
                self.fury = False
                self.fury_x = None
                self.fury_t = 0.0
                self.alert = 0.0
                self.state = "return"
            elif self.fury_t <= 0.0:
                # 计时到但玩家还在外面 → 只解除 frenzy，速度回到普通 chase
                self.fury = False
                self.fury_x = None

        # ⭐ 硬直（被露娜打中）：站桩不动，视觉上给"我打到了"的反馈
        if self.stun > 0.0:
            self.stun -= dt
            # 击退位移（指数衰减）
            if abs(self.knock_vx) > 1.0:
                self.x += self.knock_vx * dt
                self.knock_vx *= max(0.0, 1.0 - 7.0 * dt)
            if self.stun > 0.0:
                return                     # ⛔ 硬直期间不跑逻辑

        s = self.sense(luna) if trespass else 0.0
        if self.fury:
            # ⭐ frenzy 期间 alert **锁死在 1.0**（不涨也不跌），且不看视野
            self.alert = 1.0
            self.state = "chase"
            # 锁定：每个周期刷新目标 x（他冲向最后已知位置）
            if luna.x > room.border_x:
                self.fury_x = luna.x
        elif s >= 1.0:
            self.alert = min(1.0, self.alert + self.alert_gain * dt)
        elif s > 0.0:
            self.alert = min(1.0, self.alert + self.alert_hear * dt)
        else:
            self.alert = max(0.0, self.alert - ALERT_DECAY * dt)

        if self.alert >= 1.0:
            self.state = "chase"
        elif self.alert <= 0.02 and self.state == "chase":
            self.state = "patrol"

        # ============ investigate：走过去查看声源（2026-10-04 方向二）============
        # ⛔ 优先级铁律：chase 一律压过 investigate。
        #   理由：他已经在追你了还"顺便看一眼别的"，那玩家永远无法靠躲视线脱身，
        #   等于凭空多一个无法规避的压力源。发现你 = 只追你。
        if self.invest_hold > 0.0:
            self.invest_hold = max(0.0, self.invest_hold - dt)
        if self.state == "chase":
            self.invest_x = None
            self.invest_linger = 0.0
        else:
            # ---- ① 启动条件：**触发记忆**到期，且当前没有在查看 ----
            # ⛔ 判据是 invest_hold（由 _make_noise 按事件强度登记），
            #   ⛔⛔ 不是 alert —— alert 每秒掉 0.8，plate 的 0.26 撑不过 0.33 秒，
            #     拿它当条件实测一次都没触发过（守卫只是在踱步）。
            if (self.invest_hold > 0.0 and self.stun <= 0.0
                    and self.hear_x is not None and self.invest_x is None):
                # 目标夹进可活动区（他不能走出房间）
                half = self.w * 0.5
                self.invest_x = max(half + 8.0,
                                    min(VW - half - 8.0, float(self.hear_x)))
            # ---- ② 查看途中又听到新的响动 → 改目标跟过去 ----
            #   ⛔ 但**一次性**（到达就结束），⛔ 不是持续追踪 ——
            #     否则玩家能用噪声把他当导航，潜行的位置管理整套崩掉。
            #   ⭐⭐ 这里**要求 invest_hold > 0.0，所以实际上"走途中"几乎不会改目标**
            #     （hold 一启动就开始衰减，通常撑不到走完）。
            #     ⛔ 别把这条注释读成"他会跟着新声音一路追"—— **不会**，他只去第一处。
            #     这条真正生效的场景是：刚启动那几帧内又响了一声（时间上很近），
            #     此时改目标是合理的。总的效果就是"他走向你敲的第一下"。
            #   ⛔ 门槛 `hear_x` 离他已有一定距离才改目标：贴着他响就别追着改了，
            #     否则他会在原地反复微调（"抖动"），看起来像 bug。
            if (self.invest_x is not None and self.invest_hold > 0.0
                    and self.stun <= 0.0 and self.invest_linger <= 0.0
                    and self.hear_x is not None
                    and abs(float(self.hear_x) - self.x) > MW_HEAR_R * 0.5):
                half = self.w * 0.5
                self.invest_x = max(half + 8.0,
                                    min(VW - half - 8.0, float(self.hear_x)))

        if self.state == "chase":
            self._chase(dt, luna, room)
        elif self.invest_x is not None:
            self._investigate(dt)
        else:
            self._patrol(dt, luna)

            # ⭐ 听到声音就转头看声源（比 alert 数字更有戏）。
            # ⛔ chase 时不抢头：追赶中必须看路，不能被声音带偏。
            if self.hear_x is not None and self.alert > 0.12 and self.state != "chase":
                self.face = 1 if self.hear_x >= self.x else -1

    def _patrol(self, dt, luna):
        if self.pause_t > 0:                    # 停下环顾中
            self.pause_t -= dt
            return
        self.walk_t -= dt
        if self.walk_t <= 0:                    # 走够了 → 停一下并转身
            self.pause_t = 0.7
            self.walk_t = 2.2
            self.dir = -self.dir
            self.face = self.dir
            return
        self.x += self.dir * self.patrol_speed * dt
        if self.x <= self.p0:
            self.x, self.dir = self.p0, 1
        if self.x >= self.p1:
            self.x, self.dir = self.p1, -1
        self.face = self.dir

    # ------------------------------------------------------------------
    def _investigate(self, dt):
        """⭐⭐ 走过去查看声源（Ronny 2026-10-04 拍板方向二）

        与 _chase 的区别不是"慢一点的追"，是**目的不同**：
          · chase  ：目标是露娜，锁死，追到就抓
          · invest ：目标是**声源**，看一眼就完事，不追人

        ⛔⛔ 三条不变量（改动前先读）：
          ① 速度 < RUN_SPEED(300)。他是在查看不是追杀，玩家永远跑得掉。
             一旦调过 300，"噪声惊动他"就从战术资源变成死刑。
          ② 一次性：到达 → 环顾 INVEST_LINGER → 结束回巡逻。
             ⛔ 绝不能持续追踪声源 —— 玩家会学会"敲一下把他钓到任何地方"，
               潜行整套（位置管理）直接作废。
          ③ 环顾期间不读 patrol 的 pause_t/walk_t：
             那两个是**踱步节奏**的私有状态，investigate 借用会污染他之后的巡逻节奏
             （实测过一次：查看完他站着不动 0.7s 才继续，像卡住了）。
        """
        if self.invest_linger > 0.0:
            # ---- 到达：停下来环顾，然后结束本次查看 ----
            self.invest_linger -= dt
            # 环顾时左右转一点，像在找声音来源（比"定住不动"有戏）
            self.face = -self.face if (int(self.invest_linger * 7) % 2 == 0) else self.face
            if self.invest_linger <= 0.0:
                self.invest_x = None    # 一次性：看完就回巡逻
                # ⭐⭐ 连linger 一起清零（2026-10-04 实测）：
                #   只清 invest_x 会留下**负值** linger（实测 -0.02），
                #   看着像"还有 0 秒的查看在进行"，下次的判据 `linger <= 0.0`
                #   会误判成"正在环顾中" → 新声音来了不会改目标。
                #   判断依据是数值符号，不是 None，所以负值是实打实的脏状态。
                self.invest_linger = 0.0
            return

        tgt = self.invest_x
        if tgt is None:
            return
        dx = tgt - self.x
        if abs(dx) <= INVEST_RADIUS:
            # 到位 → 进入环顾
            self.invest_linger = INVEST_LINGER
            return
        self.face = 1 if dx > 0 else -1
        # ⛔ ① 速度硬上限
        self.x += self.face * min(INVEST_SPEED, RUN_SPEED - 8.0) * dt
        # ⛔ ② 再夹一次（p0/p1 是巡逻范围，但查看目标可能落在它之外）
        self.x = max(self.w * 0.5 + 8.0, min(VW - self.w * 0.5 - 8.0, self.x))
        self.y = FLOOR_Y                 # 查看只在地板上走（⛔ 不爬梯：他只是去看一眼）
        # 打断踱步节奏的残留：查看结束后 patrol 会用这两个值，
        # 这里主动清零，避免"刚查完立刻又停 0.7s"的观感（见不变量 ③）
        self.pause_t = 0.0
        self.walk_t = 1.0
        self.y = FLOOR_Y

    def _chase(self, dt, luna, room):
        # ⭐⭐ 跳跃物理（Ronny 10-03 新增）：先算重力，再判是否落地
        if not self.on_ground:
            self.vy += GRAVITY * dt
            self.y += self.vy * dt
            if self.y >= FLOOR_Y:
                self.y = FLOOR_Y
                self.vy = 0.0
                self.on_ground = True
        if self.jump_cd > 0.0:
            self.jump_cd -= dt

        # ⭐⭐ 露娜在台面上：先走到梯子脚下，再**爬上去**（他现在是能爬梯的）
        #   ⛔ 判定不能用 `self.y >= FLOOR_Y - 1` 当"他在地板上" ——
        #      爬梯第一帧 y 就掉到 647 以下，会被这个条件踢出爬梯分支（实测只爬了 1 帧就停）。
        #   ✅ 用 on_ladder 标志表示"他已经在梯子上了"，下梯时再清。
        if luna.y < FLOOR_Y - 30.0 and (self.y >= FLOOR_Y - 1.0 or self.on_ladder):
            lad = min(room.ladder_targets, key=lambda L: abs(L[0] - luna.x))
            lx = lad[0]
            if not self.on_ladder and abs(self.x - lx) > 12.0:
                self.face = 1 if lx > self.x else -1
                self.x += self.face * self.chase_speed * dt
                return
            self.on_ladder = True
            self.face = 1
            # ⭐ 爬梯速度刻意比露娜慢（78 vs 150）—— 他能追上来了，但追不死
            self.y = max(lad[1], self.y - self.climb_speed * dt)
            if self.y <= lad[1]:
                self.y = lad[1]
                # 爬到位就下来（他要站到台面上，不是挂在梯子上）
                self.on_ladder = False
            return
        self.on_ladder = False

        # ⭐⭐ 跳跃：露娜在【地板】、距离还够远时，他会跳一下压过来
        #   （只在纯地板局触发；她一上台面就走梯子路线，不会被跳）
        if (self.on_ground and self.jump_cd <= 0.0
                and abs(luna.y - FLOOR_Y) < 4.0
                and 150.0 < abs(luna.x - self.x) < 330.0):
            self.vy = -self.jump_v
            self.on_ground = False
            self.jump_cd = 1.4
            self.face = 1 if luna.x > self.x else -1

        # ⭐⭐ frenzy（2026-10-04）：冲向**锁定的位置**，而不是当前感知到的她。
        #   差别在玩家体验上很关键 —— 普通 chase 他"边看边追"，
        #   frenzy 他"直冲刚才炸响的地方"，玩家可以利用这一点抄他背后绕回去。
        tgt_x = self.fury_x if (self.fury and self.fury_x is not None) else luna.x
        dx = tgt_x - self.x
        if abs(dx) > 4.0:
            self.face = 1 if dx > 0 else -1
            # ⭐ frenzy 提速 ×1.25，但⛔ **必须仍小于 RUN_SPEED(300)**。
            #   这是硬底线： frenzy 只该让玩家更紧张，不该让"跑不掉"变成跑不掉。
            #   最紧的一档 282 × 1.25 = 352> 300 → 所以要 clamp 到 RUN_SPEED-8。
            spd = self.chase_speed
            if self.fury:
                spd = min(spd * 1.25, RUN_SPEED - 8.0)
            self.x += self.face * spd * dt
        # 下平台：走出平台边缘就自由落体
        on_p = None
        for (x0, y0, x1, y1) in room.platforms:
            if x0 - 20 <= self.x <= x1 + 20 and abs(self.y - y0) < 2.0:
                on_p = y0
                break
        if on_p is None and self.y < FLOOR_Y:
            self.y = min(FLOOR_Y, self.y + self.chase_speed * 0.9 * dt)

    def caught(self, luna) -> bool:
        # ⭐⭐ 露娜冲刺无敌帧（2026-10-04）：冲刺期间被抓判定直接失效 ——
        #   冲刺是"穿过他"的核心价值，否则只是个加速键，不敢往他身上冲。
        if getattr(luna, "dash_i", 0.0) > 0.0:
            return False
        return (abs(luna.x - self.x) < MW_CATCH_R and
                abs(luna.y - self.y) < MW_CATCH_R + 20.0)

    def go_fury(self, at_x: float, seconds: float = 9.0, heard: float = 1.0):
        """被破罐引爆：进入疯狂追踪。`heard` = 这次声响在守卫耳中的强度 0~1。

        ⭐⭐ **`heard` 必须参与判定**（2026-10-04 自测抓到的真 bug）：
           最初写成"破罐无条件 fury"，结果隔 410px 敲罐子照样全场暴怒 ——
           但那个距离他只听到闷响（_make_noise 的平方衰减只剩 3%）。
           物理上讲不通，而且**毁掉了这套设计**：
           "远处破罐 = 只是有点响"正是玩家深入敌区时唯一的减压阀，
           无条件 fury 会让"离远点"这个选择彻底失效。
           ⛔ 所以：heard 太弱 → 只按普通噪声走，不进 frenzy。
        """
        # ⭐ 阈值 0.30：低于这个强度就只是"听见点动静"。
        #   换算成距离（M=420 平方衰减）：heard 0.30 ≈ 距离 330px 以内。
        #   也就是"贴身或在半个房间内破罐"才引爆。
        if heard < 0.30:
            return False
        self.fury = True
        self.fury_t = max(self.fury_t, seconds)
        self.fury_x = float(at_x)
        self.alert = 1.0
        self.state = "chase"
        self.face = 1 if at_x >= self.x else -1
        return True

    def hear_strength(self, at_x: float, strength: float) -> float:
        """一次声响在守卫耳中的强度（0~1）。与 _make_noise 同一套平方衰减口径。

        ⭐ 抽出来是为了让 go_fury 和 _make_noise **共用同一个衰减** ——
           两处各写一份的话，改了衰减公式就会只改一处，然后出现
           "响度算出来是 0.03 但守卫还是暴怒"这种鬼故事。
        """
        d = abs(float(at_x) - self.x)
        if d > MW_HEAR_R:
            return 0.0
        return max(0.0, 1.0 - (d / MW_HEAR_R) ** 2) * strength

    def hit_by(self, from_x: float, knock: float = 260.0, stun: float = 0.45):
        """被露娜打中：往她反方向击退 + 硬直。

        ⭐ 击退方向 = 从攻击者指向他（她打他 → 他往后飞），不是"她推他"。
        ⭐ 硬直 0.45s ≈ 他停下 0.45 秒；露娜 RUN 300 → 能拉开 135px，
        够她转身往另一个容器跑。⛔ 别调太长，长了他就不像威胁了。
        """
        d = 1.0 if self.x >= from_x else -1.0
        self.knock_vx = d * float(knock)
        self.stun = max(self.stun, float(stun))
        self.face = -d                      # 被打得脸朝后
        # ⭐ 硬直不能解除 fury —— 否则玩家可以无限连击把它打懵，
        #   那"破罐 = 必被追"的压力就没了。只压速度，不压状态。
        if self.fury:
            self.fury_x = self.x             # 被打懵时原地僵住，不冲了


# ============================================================================
# ⑤ 关卡容器（把常量打包，方便以后换房间）
# ============================================================================

class Room:
    def __init__(self, cfg: dict):
        self.platforms = list(PLATFORMS)
        self.ladders = list(LADDERS)
        self.ladder_zones = list(LADDER_ZONES)
        # ⭐ 微波炉用的"可攀爬目标"：点梯原样 + 攀爬面取中心 x（它走向中心再爬，
        #   与露娜抓布的位置基本重合，视觉上就是"他扒着布追上来"）
        self.ladder_targets = list(self.ladders) + [
            ((z[0] + z[1]) / 2.0, z[2], z[3]) for z in self.ladder_zones]
        # ⭐ taken = 食物已被拿走；broken = 容器已被敲开（敲开才会变 taken）
        # ⭐⭐ 2026-10-04：按食物特性分档（KIND_TABLE），所以这里把
        #   noise / fury / value / hit 全部**解算成实例上的字段** ——
        #   ⛔ 别在下游现查 KIND_TABLE[st["kind"]]：st["kind"] 可能被关卡数据覆盖，
        #   现查会让"这一局这个容器到底是什么档"变成隐式依赖，难排查。
        stashes = []
        for s in cfg["stashes"]:
            kind = s.get("kind", "plate")
            spec = KIND_TABLE.get(kind, KIND_TABLE["plate"])
            stashes.append(dict(
                s, kind=kind,
                noise=spec["noise"], fury=spec["fury"],
                value=spec["value"], hit=spec["hit"],
                taken=False, broken=False))
        self.stashes = stashes
        self.border_x = float(cfg["border_x"])     # ⭐ 允许区边界随档位变
        self.mw_patrol = tuple(cfg["patrol"])
        # ⭐ 冰箱内容（每局重置）：QTE 成功才拿得到
        self.fridge_left = [dict(f) for f in FRIDGE_FOODS]


# ============================================================================
# ⑥ 窗口
# ============================================================================

class NightWindow(QWidget):
    def __init__(self, pack):
        super().__init__()
        self.pack = pack
        self.setWindowTitle("猫猫公寓 · 夜间冒险（灰盒）")
        self.setWindowFlags(Qt.Window | Qt.WindowCloseButtonHint)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setFocusPolicy(Qt.StrongFocus)

        # ---- 缩放：窗口按屏幕高度适配，逻辑坐标恒为 VW×VH ----
        scr = QApplication.primaryScreen().availableGeometry()
        k = (scr.height() * 0.82) / VH
        self.k = max(0.7, min(1.6, k))
        self.setFixedSize(int(VW * self.k), int(VH * self.k))

        # ---- 资源 ----
        self.imgs = _load_needed(pack, NEED_ACTIONS)
        if "idle" not in self.imgs:
            raise RuntimeError("角色包里没有 idle 帧，跑不起来")
        sil = silhouette_of(self.imgs["idle"], pack.anchor_of("idle"))
        body_h = float(sil[3] - sil[2])
        self.s = ACTOR_H / body_h if body_h > 1 else 0.26
        print(f"[夜间] 角色本体高 {body_h:.0f}px（画布）→ s={self.s:.4f} → 关卡里 {ACTOR_H:.0f}px")

        # ⭐ 图标要覆盖**三档全部**（档三用到档一档二没放的 blueberry/pumpkin/watermelon）
        _all_ic = sorted({s["icon"] for n in NIGHTS for s in n["stashes"]})
        self.icons = _load_icons(pack.root, _all_ic)
        print(f"[夜间] 赃物图标 {len(self.icons)}/{len(_all_ic)}")

        # ---- 状态 ----
        self.night_idx = 1                    # 0/1/2 → NIGHTS
        self.room = Room(NIGHTS[self.night_idx])
        self.luna = Luna(NEST_X0 + 70, FLOOR_Y, sneak_ok=self._can_play("sneak"))
        self.mw = Microwave(NIGHTS[self.night_idx])
        self.keys = set()
        self.phase = "menu"          # menu | play | meowed | hauled | result
        self.phase_t = 0.0
        self.menu_sel = self.night_idx
        # ---- 游戏专用素材（微波炉走 / 露娜拿东西跑）----
        # ---- 游戏专用素材（微波炉走 / 露娜拿东西跑）----
        self.gframes = self._load_game_frames()

        self.loot_stash = []          # ⭐ 崭边暂存（已放下、待结算）【Ronny 10-03】
        self.total_loot = 0          # ⭐ 纯装饰累积（零数值），单向
        self.loot_log = []           # 已入库的图标名序列（窝边堆用）
        self.haul_t = 0.0
        self.haul_from = (0.0, 0.0)
        self.msg = ""
        self.msg_t = 0.0
        self.night_t = 0.0           # 本档用时（秒）
        self.caught_cnt = 0          # 本档被抓次数
        self.trip_loot = 0           # 本档带回总数
        self.result = None           # 结算面板数据
        # ⭐ 冰箱 QTE（Ronny 2026-10-03）
        #   ⭐⭐ 关键设计：**QTE 期间游戏不暂停** —— 微波炉还在逼近，玩家得一边按对键一边盯着他。
        #      暂停的话这就只是个无意义的按键小游戏，没有压力就没有取舍。
        self.qte = None              # None | {"seq":[...], "got":int, "t":float, "food":dict}
        self.qte_flash = 0.0         # 成功/失败的闪白反馈
        self.fridge_door = 0.0       # ⭐ 冰箱下门开度 0~1（QTE 成功时开一下；纯程序绘制）
        # ⭐ 场景底图：美术出的静态底图。存在时用它替代程序绘制的墙/地/家具/布。
        self.has_scene_bg = os.path.isfile(os.path.join(GAME_ASSETS, "scene_bg.png"))
        # ⭐ 背景板整图（派单 42 v3）。它是 1280x720 的美术件，程序只画角色/微波炉/
        #   容器/冰箱门动画/UI —— 墙地家具布全在图里。
        _bgp = os.path.join(GAME_ASSETS, "scene_bg.png")
        _bg = QImage(_bgp) if os.path.isfile(_bgp) else QImage()
        self.bg_img = None if _bg.isNull() else _bg
        # ⭐ 场景分件贴图（派单 40v3）：吊柜 / 料理台 / 桌布 / 挂毯。餐桌按裁决走程序绘制。
        self.sparts = {}
        for _k in ("cabinet", "counter", "cloth", "towel"):
            _f = os.path.join(GAME_ASSETS, "scene", _k + ".png")
            _im = QImage(_f)
            self.sparts[_k] = None if _im.isNull() else _im
        self._narr_seen = set()      # 本档已用过的旁白，避免连着重复
        self._break_fx = []          # 容器碎裂特效 [[x, y, t], ...]
        self.noise_flash = 0.0       # 噪音闪烁倒计时
        self.mw_t = 0.0              # 微波炉动画计时（步频按速度重映射）
        self._mw_px = self.mw.x      # 上一帧的 x（用来差分算速度，Microwave 没有 vx）
        self._mw_sm = 0.0            # ⭐ 平滑后的速度（供步频计算，避免抽搐）
        self._was_over = False       # 越界旁白只在她【跨过去那一下】说
        self._was_seen = False       # 被发现的旁白同理，不逐帧刷屏

        # ---- 循环 ----
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._last = None

    # ------------------------------------------------------------ 输入
    def keyPressEvent(self, ev):
        k = ev.key()
        self.keys.add(k)
        if k == Qt.Key_Escape:
            self.close()
            return
        if self.phase == "menu":
            if k in (Qt.Key_Up, Qt.Key_W):
                self.menu_sel = (self.menu_sel - 1) % len(NIGHTS)
            elif k in (Qt.Key_Down, Qt.Key_S):
                self.menu_sel = (self.menu_sel + 1) % len(NIGHTS)
            elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self.start_night(self.menu_sel)
            elif k in (Qt.Key_1, Qt.Key_2, Qt.Key_3):
                i = k - Qt.Key_1
                self.menu_sel = i
                self.start_night(i)
            return
        if self.phase == "result":
            if k == Qt.Key_R:
                self.start_night(self.night_idx)
            elif k in (Qt.Key_1, Qt.Key_2, Qt.Key_3):
                i = k - Qt.Key_1
                self.menu_sel = i
                self.start_night(i)
            elif k in (Qt.Key_Return, Qt.Key_Enter):
                self.menu_sel = self.night_idx
                self.phase = "menu"
            return
        if self.qte and k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self._qte_step(k)          # ⭐ QTE 吃掉方向键（移动键在 QTE 期间禁用）
            return
        if k == Qt.Key_E:
            self._try_break()
        elif k == Qt.Key_R:
            self.start_night(self.night_idx)
        # ⭐⭐ 技能键（Ronny 2026-10-04）
        #   J = 攻击（三段：前摇 0.16 / 命中 0.09 / 后摇 0.26）
        #   K = 冲刺（0.20s 位移 + 0.26s 无敌帧 + 1.3s 冷却）
        # ⛔ 别把技能键塞进 self.keys —— 那是"持续按住"的键集，
        #   技能是**一次性触发**，混进去会被当成按住不放反复触发。
        elif k == Qt.Key_J:
            self.luna.try_attack()
        elif k == Qt.Key_K:
            # ⭐ 冲刺方向：读当前按着的左右键，没有就沿当前朝向
            d = 0
            if self.keys & {Qt.Key_Left, Qt.Key_A}:
                d = -1
            elif self.keys & {Qt.Key_Right, Qt.Key_D}:
                d = 1
            self.luna.try_dash(d)

    def keyReleaseEvent(self, ev):
        self.keys.discard(ev.key())

    # ------------------------------------------------------------ 开一局
    def start_night(self, idx: int):
        cfg = NIGHTS[idx]
        self.night_idx = idx
        self.room = Room(cfg)
        self.luna = Luna(NEST_X0 + 70, FLOOR_Y, sneak_ok=self._can_play("sneak"))
        self.mw = Microwave(cfg)
        self.phase = "play"
        self.phase_t = 0.0
        self.haul_t = 0.0
        self.night_t = 0.0
        self.caught_cnt = 0
        self.trip_loot = 0
        self.result = None
        self._narr_seen = set()
        self._break_fx = []
        self.noise_flash = 0.0
        self._was_over = False
        self._was_seen = False
        self._narrate("enter", [idx])
        print(f"[夜间] 开局：{cfg['name']}　赃物 {len(self.room.stashes)} 样"
              f"　边界 x={cfg['border_x']:.0f}　追速 {cfg['chase_speed']:.0f}")

    def _load_game_frames(self):
        """读 assets_game/ 的帧序列。它们不走 core.load_frames（那里只管桌宠包）。"""
        out = {}
        for name in GAME_FPS:
            d = os.path.join(GAME_ASSETS, name)
            mp = os.path.join(d, "_meta.json")
            if not (os.path.isdir(d) and os.path.isfile(mp)):
                print(f"[游戏素材] 缺 {name}（保持占位）")
                out[name] = []
                continue
            meta = json.load(open(mp, encoding="utf-8"))
            frames = []
            for m in meta:
                # ⛔ 必须存 QImage 不是 QPixmap —— QPainter.drawImage(QRectF, img, QRectF)
                #   那个重载只吃 QImage，传 QPixmap 会 TypeError（桌宠的 imgs 本来就是 QImage）。
                img = QImage(os.path.join(d, m["file"]))
                if img.isNull():
                    continue
                cw, ch = m["canvas"]
                frames.append((img, cw, ch, cw // 2, ch))   # anchor = 脚底中点
            out[name] = frames
            if frames:
                print(f"[游戏素材] {name} {len(frames)} 帧  canvas {frames[0][1]}x{frames[0][2]}")
            else:
                print(f"[游戏素材] {name} 读不出帧")
        return out

    def _can_play(self, name: str) -> bool:
        """⭐ 这个动作**真的有帧可播吗**。

        ⛔ 不能写 `name in self.pack.actions` —— 占位注册（如 eat）在 actions 里、
           但盘上没帧；而 NEED_ACTIONS 之外的动作压根没被读进 self.imgs。
           两种情况下画面都会静默退化成 idle（看着就是"没实装"）。
        """
        return bool(self.imgs.get(name))

    def _try_break(self):
        """E = 敲碎面前的容器，把食物抢出来。**这一下会发出声音。**

        ⭐ 一次操作完成"拿东西"，不做成两步（先敲碎、再按 E 捡）——
           两步会让最基础的循环变得手忙脚乱，而"敲"本身就是最有反馈感的动作。
        """
        if self.phase != "play":
            return
        l = self.luna
        # ⭐ 每次只能拿一件（Ronny 2026-10-03）。两个原因：
        #   ① 把“拿了什么”变成了一个可见状态（头顶一件），而不是一个数字；
        #   ② 手上有东西时跑走要用拿东西的动作（单独一张素材），空手就用 human_run。
        # ⭐⭐ 判定顺序：**先容器，后冰箱**（Ronny 2026-10-03 实机反馈「罐子和冰箱重合点不到」）
        #   原因：原本冰箱判定在前且范围更宽（x-96 ~ x+w+26），
        #   而 x=1080 / 1180 两个容器正好落在里面 → 永远走不到容器的敲击分支。
        #   ⭐ 容器的判定半径（本来就比冰箱紧，"离得近的那个先响应"）也更符合直觉。
        # ⭐⭐ 2026-10-04：判定半径改成**逐容器**（KIND_TABLE.hit），
        #   因为四档容器的"手感该有的松紧"不一样：
        #   loose 最好拿(46) → jar 最难(54)。⛔ 别再用一个 54 打天下 ——
        #   那会让"敞着放"的东西拿起来跟撬罐子一样费劲，分档就白分了。
        for st in self.room.stashes:
            if st["broken"] or st.get("scratched"):
                continue
            if abs(l.x - st["x"]) < st["hit"] and abs(l.y - st["y"]) < 66.0:
                # ⛔ 手上已有东西 → 拒绝（⛔ 别让它落到下面那两行去，否则会**覆盖** carrying）
                if l.carrying:
                    self._say("手上还拿着。回窝放下才能再拿。")
                    return
                self._take_stash(st, by_attack=False)
                return
        # ⭐⭐ 冰箱 QTE：在冰箱前按 E → 进入限时按键序列
        #   ⛔ 放在"手上没东西"判定**之前**，但要求空手 —— 手上拿着东西打不开冰箱。
        if self._at_fridge() and self.room.fridge_left:
            if l.carrying:
                self._say("手上拿着东西，打不开冰箱。")
            else:
                self._qte_start()
            return
        # ⭐⭐ 在窝边且窝边有待结算的东西 → E = 结算（而不是敲容器）
        if l.x < NEST_X1 + 40 and self.loot_stash:
            self._narrate("settle_now")
            self._settle()
            return
        if l.carrying:
            self._say("手上还拿着。回窝放下才能再拿。")
            return
        # ⭐ 容器判定已挪到本函数最前面（先容器后冰箱），这里不再重复一轮
        self._narrate("empty")

    def _take_stash(self, st: dict, by_attack: bool = False):
        """取走一个容器里的东西。**E 键与攻击都走这里**（⛔ 别复制一份结算逻辑）。

        ⭐⭐ 2026-10-04 四档容器：噪声/价值/是否引爆全部来自 st 上的字段
           （Room 构造时已从 KIND_TABLE 解算），这里只负责执行。
        ⭐ jar 的 fury=True → 破它直接让守卫进入疯狂追踪（Ronny：
          「罐子改为一但破裂警卫会直接疯狂追踪」）。这是全场最响、最危险的一下。
        ⭐⭐ 攻击取走 vs 键取走：只有**动画**不同（攻击已经在播 tease 了），
           代价**完全一样** —— 攻击不会比按 E 更安静。
           原因：攻击的价值是"打碎 + 顺手拿走 + 击退追兵"，不是"绕过噪声"。
           若给攻击减噪声，玩家就会全程用攻击，潜行这套就没了。
        """
        l = self.luna
        st["broken"] = True
        # ⭐ 手上东西存 "value:icon"（结算按价值、渲染按 icon）
        l.carrying = [f"{st['value']}:{st['icon']}"]            # ⭐ 一次只拿一件
        self._break_fx.append([float(st["x"]), float(st["y"]), 0.0])
        kind = st.get("kind", "plate")
        # ⭐ 噪声用该档自己的值，⛔ 不用 NOISE_MAX —— 那会让四档听起来一样。
        # ⭐⭐ 先算这次声响在守卫耳中的强度（共用平方衰减口径），
        #    再用它决定要不要引燃 frenzy —— 两处共用一个 k，避免口径漂移。
        heard = self.mw.hear_strength(float(st["x"]), st["noise"])
        self._make_noise(float(st["x"]), st["noise"])
        if st.get("fury"):
            # ⭐⭐ 破罐 → 疯狂追踪。注意用的是**容器位置**而不是露娜位置：
            #   守卫该冲向"炸响的地方"，这是玩家能听见、能预判、能绕开的信息。
            # ⛔ go_fury 内部会判 heard（远处/太弱只算普通噪声）—— 见那函数注释。
            if self.mw.go_fury(float(st["x"]), FURY_SECONDS, heard):
                self._say("砰——！！")
                self._narrate("fury")
            else:
                self._say("咔。…听不清是哪边。")
                self._narrate("fury_far")
        elif not by_attack:
            l.punch = 0.42                                # ⭐ 播"挠"的挥击动作
        self._narrate("steal")

    def _resolve_attack_hit(self):
        """在攻击的**命中窗口**内结算一次。⛔ 每次攻击只结算一次（atk_hit_done）。

        ⭐⭐ 一次挥击可能同时够到【容器】和【守卫】—— 玩家自己选的站位，
           两个都结算（代价一起付）。这让"贴着罐子站在它面前打"变成一个
           高风险高回报的选项，而不是"只有守卫被打"。
        """
        l = self.luna
        if l.atk_hit_done or not l.in_atk_window():
            return
        # ⭐ 判定是**身前单向**：|dx| <= ATK_REACH 且方向一致
        #   （⛔ 别用圆形范围 —— 那意味着她能打到背后，潜行的"绕后"就没意义了）
        hit_any = False
        # --- ① 守卫 ---
        mw = self.mw
        if (abs(l.x - mw.x) <= ATK_REACH + mw.w * 0.5
                and abs(l.y - mw.y) <= ATK_DY
                and (mw.x - l.x) * l.face >= -18.0):
            mw.hit_by(l.x, ATK_KNOCK, ATK_STUN)
            hit_any = True
            self._say("啪！")
        # --- ② 容器 ---
        for st in self.room.stashes:
            if st["broken"] or st.get("scratched"):
                continue
            if (abs(l.x - st["x"]) <= ATK_REACH
                    and abs(l.y - st["y"]) <= ATK_DY
                    and (st["x"] - l.x) * l.face >= -18.0):
                if l.carrying:
                    # 手上拿着→ 这一下打不到东西（但守卫那半仍然结算）
                    self._say("手上还拿着。")
                    break
                self._take_stash(st, by_attack=True)
                hit_any = True
                break
        if hit_any:
            l.atk_hit_done = True

    def _at_fridge(self) -> bool:
        l = self.luna
        # ⭐⭐ 2026-10-04 冰箱挪到右墙独立段（1120~1250）后，判据回到**最自然的语义**：
        #   「站在冰箱正前方的地板上按 E」。
        #   ⛔ 旧写法 `abs(l.y - TABLE_TOP) < 6` 是被遮挡逼出来的 hack —— 冰箱压在
        #     茶几正后方、下半被布幔挡住，才被迫要求她「站上桌面」。挪开后那个判据
        #     会让她**站在 88px 高的茶几上够一个站在地面的冰箱**，物理上说不通。
        #   判据 = x 在冰箱门区附近（左右各留余量）+ **人在地板层**。
        return (l.x > FRIDGE["x"] - 104.0 and l.x < FRIDGE["x"] + FRIDGE["w"] + 26.0
                and abs(l.y - FLOOR_Y) < 6.0)

    def _qte_start(self):
        """开始一次开冰箱 QTE。⭐ 序列用方向键（玩家全程看屏幕，不用低头看键盘）。"""
        import random
        dirs = [Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down]
        seq = [random.choice(dirs) for _ in range(QTE_LEN)]
        # 拿一件还没被拿的
        pool = self.room.fridge_left
        if not pool:
            return
        food = pool[0]
        self.qte = {"seq": seq, "got": 0, "t": 0.0, "food": food}
        self.qte_flash = 0.0
        # ⭐⭐ QTE 锁移动（第一道保险）：把已经按着的移动键从集合里清掉 + 让她当场站定。
        #   不清的话：她按着 → 走到冰箱前按 E，QTE 开始那一刻手指还压着方向键，
        #   人会继续滑出判定区（Ronny 10-03 实机反馈）。
        self.keys -= QTE_MOVE_KEYS
        self.luna.vx = 0.0
        self._say("撬一下……")
        self._make_noise(FRIDGE["x"], NOISE_MAX * 0.55)   # 撬门本身有点响（比敲容器轻）

    def _qte_step(self, key):
        """按一个键。返回 True 表示这次输入被 QTE 吃掉了。"""
        q = self.qte
        if not q:
            return False
        if key == q["seq"][q["got"]]:
            q["got"] += 1
            q["t"] = 0.0
            if q["got"] >= len(q["seq"]):
                self._qte_win()
            else:
                self._say("咔。")
        else:
            self._qte_fail()
        return True

    def _qte_win(self):
        f = self.qte["food"]
        self.room.fridge_left.remove(f)
        # ⭐ 冰箱是 kind=fridge那一档（value=3）—— 写同样的 "value:icon" 编码
        spec = KIND_TABLE["fridge"]
        self.luna.carrying = [f"{spec['value']}:{f['icon']}"]
        self.qte = None
        self.qte_flash = 0.4
        # ⭐ 门开一下（纯程序绘制，派单 36 回传裁决：冰箱门开不用素材）
        self.fridge_door = 1.0
        self._say("开了。")
        self._narrate("fridge")

    def _qte_fail(self):
        self.qte = None
        self.qte_flash = 0.4
        # ⛔ 惩罚是"微波炉警觉 + 噪音"，⛔ 不是直接失败/丢命（玩法文档：惩罚要轻）
        self.mw.alert = min(1.0, self.mw.alert + QTE_FAIL_ALERT)
        self.mw.hear_x = FRIDGE["x"]
        if self.mw.alert >= 1.0:
            self.mw.state = "chase"
        self._make_noise(FRIDGE["x"], NOISE_MAX * 0.8)
        self._say("哐——！")

    def _make_noise(self, x: float, strength: float):
        """一次声响。⭐ 强度按【与微波炉的距离】线性衰减，超出听觉半径他根本听不见。

        这条是"深层赃物取舍"的来源：近处的容器好够、但敲出来最响；
        吊柜顶上的最安全、也最难够。两条路都得走，玩家自己选。
        """
        self.noise_flash = 0.55
        mw = self.mw
        # ⭐⭐ 衰减口径统一走 mw.hear_strength —— ⛔ 别在这里再写一份 (1-d/R)²。
        #   两处各写一份的代价：改公式时只改一处，
        #   然后出现"响度算出来 0.03 但守卫照样暴怒"这种自相矛盾（已踩过）。
        k = mw.hear_strength(x, strength)
        if k <= 0.0:
            self._say("…他没听见。")
            return
        mw.alert = min(1.0, mw.alert + k)
        mw.hear_x = x# ⭐ 他会转头朝声源看（比 alert 数字更有戏）
        # ⭐⭐ 登记"值得走过去看一眼"的触发记忆（方向二的核心）。
        #   ⛔⛔ 判据用 k（**已按距离衰减**的响度），不是 strength：
        #     strength 是容器自己的响度，跟"他听不听得清"无关。
        #     贴脸敲 plate：k≈0.26 刚好过门槛 → 他会走过去看；
        #     400px 外敲 plate：k≈0.10 听不清 → 只转头，不走路（位置依然是战术资源）。
        #   ⛔ 别拿 mw.alert 当条件（见 INVEST_HOLD 注释：衰减太快，实测永不触发）。
        if k >= INVEST_ALERT:
            mw.invest_hold = INVEST_HOLD
        if mw.alert >= 1.0:
            mw.state = "chase"   # ⭐ 敲完立刻追，不等下一帧 update
            #   （否则下一帧开始就会衰减，alert 掉到 0.987，
            #    state 迟一帧才进 chase ——玩家会觉得“他体量一个催了又没了”）
        if k > 0.28:
            self._say("砰——！")
        else:
            self._say("咔。")

    def _say(self, s):
        self.msg = s
        self.msg_t = 1.6

    def _narrate(self, key: str, force_from: list = None):
        """抽一句旁白。

        ⭐ `force_from` 用于按档位取（开场白三档各一句）。
        ⭐ 本档同一事件不连着重复同一条 —— 读两遍就出戏。
        """
        pool = NARRATION.get(key) or []
        if not pool:
            return
        seen = self._narr_seen
        cand = [i for i in range(len(pool)) if (key, i) not in seen]
        if not cand:
            # ⭐ 这个事件的池子抽干了 → 只清它自己的记录，开第二轮。
            #   （清空全部会让别的已开始轮换的事件被拉回第一句。）
            seen.difference_update({k for k in seen if k[0] == key})
            cand = list(range(len(pool)))
        if force_from:
            cand = [i for i in force_from if i < len(pool)] or cand
        i = cand[0] if len(cand) == 1 else cand[hash(str(self.night_t)) % len(cand)]
        seen.add((key, i))
        self._say(pool[i])

    # ------------------------------------------------------------ 结算
    def _settle(self):
        """回窝且手里有东西 → 今晚到此为止，出结算。

        ⭐ 惩罚要轻（玩法文档定的）：**已经入库的不清零**，
        只损失"这一趟还没带回去的"—— 有紧张感，不劝退。
        ⭐⭐ 2026-10-04：计分改按**价值**（loot_stash 存 "kind:icon" 串）。
           ⛔ 别再 len(loot_stash) 当件数 —— 那样loose 和 jar 都算 1，
             玩家冒着点罐子被全场追的险却和端碗拿苹果同分，
             "风险与价值同向"的设计就作废了。
        """
        # ⭐ 兼容旧的纯 icon 串（存档/旧测试可能塞的是 "salmon"）
        vals = []
        for it in self.loot_stash:
            if ":" in it:
                vals.append(int(it.split(":", 1)[0]))
            else:
                vals.append(1)
        n = len(vals)
        vsum = sum(vals)
        self.loot_log.extend(self.loot_stash)   # ⭐ 入库的是【实际偷到的那些】
        self.loot_stash = []                   # 结算完下架打空
        self.total_loot += vsum
        self.trip_loot += vsum
        # ⭐ 计分按价值加权（每点价值 110 分 = 原来一件110 的口径放大到 4）
        base = vsum * 110
        clean = 40 if self.caught_cnt == 0 else 0
        # ⭐ 超时门槛也按价值算（偷 4 件花的时间本来就该比偷 1 件多）
        late = max(0.0, self.night_t - vsum * 25.0) * 2.0
        score = base + clean - self.caught_cnt * 30 - late
        rank = "S" if score >= 780 else "A" if score >= 560 else "B" if score >= 380 else "C"
        left = sum(1 for s in self.room.stashes if not s["taken"])
        self.result = {
            "night": NIGHTS[self.night_idx]["name"],
            "loot": n, "value": vsum, "left": left, "total": self.total_loot,
            "caught": self.caught_cnt, "time": self.night_t,
            "score": int(round(score)), "rank": rank,
        }
        self.phase = "result"
        self.phase_t = 0.0
        self._narrate("finish" if left == 0 else "home")
        print(f"[夜间] 结算：带回 {n} 件（价值 {vsum}）剩 {left} 被抓 {self.caught_cnt} "
              f"用时 {self.night_t:.0f}s → {rank}（{self.result['score']}）")

    # ------------------------------------------------------------ 循环
    def _tick(self):
        import time
        now = time.perf_counter()
        dt = 0.016 if self._last is None else min(0.033, now - self._last)
        self._last = now

        l, mw = self.luna, self.mw
        if self.msg_t > 0:
            self.msg_t -= dt
        if l.punch > 0.0:
            l.punch = max(0.0, l.punch - dt)
        if self.noise_flash > 0:
            self.noise_flash = max(0.0, self.noise_flash - dt * 1.6)
        for fx in self._break_fx:
            fx[2] += dt * 2.3
        self._break_fx = [fx for fx in self._break_fx if fx[2] < 1.0]
        # ⭐ 微波炉步频按速度重映射：游戏里他巡逻 95px/s、追击 250px/s，
        #   素材只出了一条中性慢走（12fps），快慢由引擎控 —— 不需要出两条。
        #   ⛔ Microwave 没有 vx（它直接改 self.x），用位置差分算瞬时速度。
        _mwv = abs(self.mw.x - self._mw_px) / max(dt, 1e-6)
        self._mw_px = self.mw.x
        # ⭐ 平滑：瞬时速度逐帧抖（转向/加减速都会让它抖），指数移动平滑一下
        self._mw_sm += (_mwv - self._mw_sm) * min(1.0, dt * 6.0)
        _sm = self._mw_sm
        self.mw_t += dt * (min(_sm / 95.0, 2.6) if _sm > 1.0 else 0.4)
        # ⭐ 冰箱 QTE 计时：⛔ 游戏**不暂停**，微波炉还在追（这才叫 QTE）
        if self.qte is not None and self.phase == "play":
            self.qte["t"] += dt
            if self.qte["t"] > QTE_TIME_LIMIT:
                self._qte_fail()
        if self.qte_flash > 0:
            self.qte_flash = max(0.0, self.qte_flash - dt * 2.0)
        # ⭐ 冰箱门：开 → 停 0.5s → 关（成功那一下要给玩家看到"门真的开了"）
        if self.fridge_door > 0.0:
            self.fridge_door -= dt * 2.2
            if self.fridge_door < 0.0:
                self.fridge_door = 0.0

        if self.phase == "menu":
            # 菜单：让角色在窝里待机（呼吸），别冻成一张图
            l.t += dt * 10.0
            self.update()
            return

        if self.phase == "result":
            self.phase_t += dt
            l.t += dt * 10.0
            self.update()
            return

        if self.phase == "play":
            self.night_t += dt
            # ⭐⭐ QTE 锁移动（第二道保险）：QTE 期间方向键只喂 QTE，不驱动移动。
            mv = self.keys - QTE_MOVE_KEYS if self.qte is not None else self.keys
            l.update(dt, mv, self.room)
            # ⭐⭐ 攻击三段的推进 + 命中结算。
            #   ⭐ 这里是**唯一**推进 wind/act/rec 的地方（Luna.update 只做减速）——
            #     三段是状态机（wind→act→rec→cd），阶段转移必须有唯一的裁判。
            #   ⛔ 结算必须在 update **之后**：Luna.update 会改变位置
            #     （前摇减速、跳跃等），先结算会用到上一帧的位置。
            #   ⛔ 别把这段搬进 Luna.update：那里拿不到守卫和容器的语义。
            if l.atk_wind > 0.0:
                l.atk_wind = max(0.0, l.atk_wind - dt)
                if l.atk_wind <= 1e-6:
                    l.atk_act = ATK_ACT          # 前摇结束 → 进命中窗口
            if l.atk_act > 0.0:
                self._resolve_attack_hit()      # ⭐ 在窗口内才结算，且每次只结算一次
                l.atk_act = max(0.0, l.atk_act - dt)
                if l.atk_act <= 1e-6:
                    l.atk_rec = ATK_REC          # 命中窗口结束 → 进后摇
            elif l.atk_rec > 0.0:
                l.atk_rec = max(0.0, l.atk_rec - dt)
                if l.atk_rec <= 1e-6:
                    l.atk_cd = ATK_CD# 后摇结束 → 才开始冷却
            mw.update(dt, l, self.room)

            # 越界的第一句话（只在跨过去那一下说，不重复刷屏）
            if l.x > self.room.border_x and not self._was_over:
                self._was_over = True
                self._narrate("cross")
            elif l.x < self.room.border_x:
                self._was_over = False

            # 被看见的瞬间说一句（⛔ 不是每帧，alert 刚起来那一下）
            if mw.alert > 0.35 and not self._was_seen:
                self._was_seen = True
                self._narrate("spotted")
            elif mw.alert < 0.1:
                self._was_seen = False

            # ⭐⭐ 回宝 = 放下（暂存），**不结算**。结算要玩家在崭边主动按 E。
            if l.x < NEST_X1 and l.carrying:
                self.loot_stash.extend(l.carrying)
                l.carrying = []
                self._narrate("drop")
            elif mw.caught(l) and l.x > self.room.border_x:
                self.phase = "meowed"
                self.phase_t = 0.0
                self.caught_cnt += 1
                self.qte = None             # ⭐ 被抓时 QTE 必须作废（否则按键还在喂一个死 QTE）
                self._narrate("caught")

        elif self.phase == "meowed":
            self.phase_t += dt
            if self.phase_t > 1.5:              # 大字停留时间（太长会打断节奏）
                self.phase = "hauled"
                self.phase_t = 0.0
                self.haul_t = 0.0
                self.haul_from = (l.x, l.y)
                l.carrying = []
                l.on_ladder = False
                l.vx = l.vy = 0.0

        elif self.phase == "hauled":
            # ⭐ 押送演出：微波炉把露娜拎回窝（1.1 秒插值），不是瞬移
            self.haul_t = min(1.0, self.haul_t + dt / 0.9)
            e = self.haul_t * self.haul_t * (3 - 2 * self.haul_t)
            tx, ty = NEST_X0 + 70, FLOOR_Y
            x0, y0 = self.haul_from
            l.x = x0 + (tx - x0) * e
            l.y = y0 + (ty - y0) * e - math.sin(e * math.pi) * 60.0   # 拎起来的一点点抛物线
            mw.x = l.x + 34.0
            mw.y = FLOOR_Y
            mw.face = -1
            if self.haul_t >= 1.0:
                l.escort = False
                mw.state = "patrol"
                mw.alert = 0.0
                mw.x = (mw.p0 + mw.p1) / 2          # ⭐ 用本档的巡逻段，不是模块常数
                self.phase = "play"
                self.phase_t = 0.0
                self._say("被押送回窝了。这趟白干。")

        # 动作推进
        a = l.pick_action()
        if a != l.act:
            l.act, l.t = a, 0.0
        act = self.pack.actions.get(a)
        fps = GAME_FPS["run_carry"] if a == "run_carry" else (act.fps if act else 10.0)
        if a == "climb":
            # ⭐ 判据是 l.moving，不是 vy —— 爬梯时 vy 被强制清零，用 vy 会让动画永停。
            # ⭐ 下梯 = 同一个 climb 动作【倒着播】（t 递减），⛔ 不是把 sprite 上下翻转 ——
            #   翻转会让她头朝下倒挂。倒着播才是"手往下抓、脚往下蹬"。
            #   t 为负时 `int(t) % len` 在 Python 里仍返回正下标，循环不会崩。
            if l.moving:
                l.t += dt * fps * (-1.0 if l.climb_down else 1.0)
        else:
            l.t += dt * fps
        self.update()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.scale(self.k, self.k)

        self._draw_bg(p)
        if self.phase == "menu":
            self._draw_nest(p)
            self._draw_luna(p)          # ⭐ 她在窝里等着，不是冻住的立绘
            self._draw_menu(p)
            p.end()
            return
        self._draw_zone(p)
        # ⭐⭐ 背景板（派单 42 v3 美术件）：美术出的整图，含墙/地/家具/布/生活装饰。
        #   画在最底层；它已经包含家具和布 → 程序绘制的平台/布全部跳过，
        #   只保留需要动的层：冰箱门动画 / 容器 / 微波炉 / 角色 / HUD。
        if self.bg_img is not None:
            p.drawImage(QRectF(0, 0, VW, VH), self.bg_img,
                        QRectF(0, 0, self.bg_img.width(), self.bg_img.height()))
            self._draw_nest(p)
            self._draw_stashes(p)
            self._draw_fridge(p)
            self._draw_mw(p)
            self._draw_luna(p)
            self._draw_hud(p)
            if self.phase == "meowed":
                self._draw_meowed(p, self.phase_t)
            if self.phase == "result":
                self._draw_result(p)
            p.end()
            return
        self._draw_platforms(p)
        self._draw_fridge(p)
        self._draw_nest(p)
        self._draw_stashes(p)
        self._draw_mw(p)
        self._draw_luna(p)
        self._draw_hud(p)
        if self.phase == "meowed":
            self._draw_meowed(p, self.phase_t)
        if self.phase == "result":
            self._draw_result(p)
        p.end()

    # -- 选档 --
    def _draw_menu(self, p):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 12, 20, 190))
        p.drawRect(QRectF(0, 0, VW, VH))

        p.setPen(QColor(240, 226, 196))
        f = QFont("Microsoft YaHei", 34)
        p.setFont(f)
        p.drawText(QRectF(0, 96, VW, 52), Qt.AlignCenter, "猫猫公寓 · 夜间冒险")
        p.setFont(QFont("Microsoft YaHei", 14))
        p.setPen(QColor(160, 158, 172))
        p.drawText(QRectF(0, 148, VW, 28), Qt.AlignCenter, "深夜的公共区域。拿点东西回来。")

        # 三张卡
        cw, ch, gap = 260, 214, 34
        total = len(NIGHTS) * cw + (len(NIGHTS) - 1) * gap
        x = (VW - total) / 2
        for i, cfg in enumerate(NIGHTS):
            r = QRectF(x + i * (cw + gap), 220, cw, ch)
            sel = (i == self.menu_sel)
            p.setPen(QPen(QColor(214, 178, 118) if sel else QColor(70, 70, 86),
                          3 if sel else 1.5))
            p.setBrush(QColor(34, 34, 48) if sel else QColor(22, 22, 32))
            p.drawRoundedRect(r, 12, 12)

            p.setPen(QColor(238, 220, 184) if sel else QColor(140, 140, 156))
            p.setFont(QFont("Microsoft YaHei", 22 if sel else 19, QFont.Bold))
            p.drawText(QRectF(r.left(), r.top() + 16, r.width(), 34),
                       Qt.AlignCenter, cfg["name"])
            p.setFont(QFont("Microsoft YaHei", 12))
            p.setPen(QColor(150, 148, 162))
            p.drawText(QRectF(r.left() + 14, r.top() + 54, r.width() - 28, 46),
                       Qt.AlignHCenter | Qt.TextWordWrap, cfg["sub"])

            # 关键数字（⛔ 别写"难度★"，写玩家真正会变的那几个量）
            p.setFont(QFont("Microsoft YaHei", 12))
            p.setPen(QColor(190, 188, 200))
            lines = [
                f"赃物　{len(cfg['stashes'])} 样",
                f"禁区　宽 {VW - cfg['border_x']:.0f}",
                f"它　　追 {cfg['chase_speed']:.0f} / 我 {RUN_SPEED:.0f}",
            ]
            for k, s in enumerate(lines):
                p.drawText(QRectF(r.left() + 20, r.top() + 112 + k * 22, r.width() - 34, 22), s)
            # 跑得掉/险 的直观提示
            gap_px = RUN_SPEED - cfg["chase_speed"]
            p.setPen(QColor(140, 220, 170) if gap_px >= 60 else QColor(240, 170, 120))
            p.drawText(QRectF(r.left() + 20, r.top() + 182, r.width() - 34, 22),
                       f"余速　+{gap_px:.0f}" + ("　跑得掉" if gap_px >= 60 else "　很险"))

        p.setFont(QFont("Microsoft YaHei", 14))
        p.setPen(QColor(236, 214, 170))
        p.drawText(QRectF(0, 470, VW, 30), Qt.AlignCenter,
                   "↑↓ 选档　　Enter / 空格 开始　　1 2 3 直接进对应档　　Esc 退出")
        if self.total_loot:
            p.setFont(QFont("Microsoft YaHei", 13))
            p.setPen(QColor(170, 168, 180))
            p.drawText(QRectF(0, 512, VW, 26), Qt.AlignCenter,
                       f"窝边已经堆了 {self.total_loot} 样 —— 看左边那个窝")

    # -- 结算 --
    def _draw_result(self, p):
        r = self.result or {}
        a = min(1.0, self.phase_t / 0.35)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(8, 9, 14, int(212 * a)))
        p.drawRect(QRectF(0, 0, VW, VH))

        box = QRectF(VW / 2 - 250, 150, 500, 400)
        p.setPen(QPen(QColor(190, 160, 104, int(220 * a)), 2))
        p.setBrush(QColor(22, 22, 30, int(242 * a)))
        p.drawRoundedRect(box, 14, 14)

        p.setPen(QColor(238, 220, 184))
        p.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        p.drawText(QRectF(box.left(), box.top() + 22, box.width(), 32),
                   Qt.AlignCenter, f"{r.get('night','')} · 今晚到此为止")

        # 评级大字
        rank = r.get("rank", "C")
        p.setFont(QFont("Georgia", 84, QFont.Bold))
        p.setPen(QColor(196, 158, 92))
        p.drawText(QRectF(box.left(), box.top() + 62, box.width(), 104),
                   Qt.AlignCenter, rank)

        p.setFont(QFont("Microsoft YaHei", 14))
        p.setPen(QColor(190, 188, 200))
        rows = [
            ("带回", f"{r.get('loot',0)} 样"),
            ("没搜到", f"{r.get('left',0)} 样"),
            ("被抓", f"{r.get('caught',0)} 次"),
            ("用时", f"{r.get('time',0):.0f} 秒"),
            ("窝边累计", f"{r.get('total',0)} 样"),
        ]
        for k, (a_, b_) in enumerate(rows):
            y = box.top() + 186 + k * 30
            p.setPen(QColor(160, 158, 172))
            p.drawText(QRectF(box.left() + 66, y, 160, 26), a_)
            p.setPen(QColor(232, 226, 210))
            p.drawText(QRectF(box.left() + 226, y, 190, 26), b_)

        p.setFont(QFont("Microsoft YaHei", 12))
        p.setPen(QColor(140, 138, 152))
        p.drawText(QRectF(box.left(), box.bottom() - 34, box.width(), 22),
                   Qt.AlignCenter, f"评分 {r.get('score',0)}　（被抓不清零，只扣分）")

        p.setFont(QFont("Microsoft YaHei", 14))
        p.setPen(QColor(236, 214, 170))
        p.drawText(QRectF(0, VH - 74, VW, 30), Qt.AlignCenter,
                   "R 重来这档　　1 2 3 换档　　Enter 回选档")

    # -- 背景 --
    def _draw_bg(self, p):
        g = QLinearGradient(0, 0, 0, VH)
        g.setColorAt(0.0, QColor(18, 20, 34))
        g.setColorAt(1.0, QColor(38, 34, 46))
        p.fillRect(QRectF(0, 0, VW, VH), QBrush(g))

        # 窗（左上，月光）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(52, 60, 92))
        p.drawRoundedRect(QRectF(60, 60, 210, 190), 6, 6)
        p.setBrush(QColor(96, 108, 150))
        p.drawRoundedRect(QRectF(72, 72, 186, 166), 4, 4)
        p.setBrush(QColor(150, 160, 200))
        p.drawRect(QRectF(160, 72, 8, 166))
        p.drawRect(QRectF(72, 150, 186, 8))
        # 月光洒在地上
        mg = QRadialGradient(QPointF(200, 470), 40, QPointF(200, 470), 340)
        mg.setColorAt(0, QColor(150, 170, 220, 60))
        mg.setColorAt(1, QColor(150, 170, 220, 0))
        p.fillRect(QRectF(0, 260, 620, VH - 260), QBrush(mg))

        # 远景家具剪影（灰盒：几个深色块，给房间一点纵深）
        p.setBrush(QColor(26, 26, 40))
        p.drawRoundedRect(QRectF(980, 470, 260, 178), 8, 8)     # 冰箱
        p.drawRect(QRectF(300, 400, 120, 248))                   # 柜子

    # -- 允许区 --
    def _draw_zone(self, p):
        bx = self.room.border_x            # ⭐ 随档位变，不是模块常数
        z = QLinearGradient(0, FLOOR_Y - 200, 0, FLOOR_Y)
        z.setColorAt(0, QColor(120, 220, 160, 0))
        z.setColorAt(1, QColor(120, 220, 160, 70))
        p.fillRect(QRectF(0, FLOOR_Y - 200, bx, 200 + (VH - FLOOR_Y)), QBrush(z))
        # 边界线（虚线）
        pen = QPen(QColor(150, 240, 190, 200), 3, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(bx, FLOOR_Y - 230), QPointF(bx, VH))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(150, 240, 190, 220))
        p.drawEllipse(QPointF(bx, FLOOR_Y - 236), 5, 5)

    # -- 平台与梯子 --
    def _draw_platforms(self, p):
        # ⭐⭐⭐ 配色来源：Ronny 2026-10-03 提供的**自家厨房实拍照片**分区中位色
        #   吊柜 #ECEDE8 亮白 ｜台面 #6B5B4B 木色 ｜地板 #7D6A59 暖木 ｜墙面 #63564B 暖褐
        #   ⭐ 之前是从执行端出的 AI 废图取色（#2D3C4A 冷蓝灰 / #181E27 深蓝黑）——
        #      ⛔ 那张是模型想象的"夜晚厨房"，色相跟真实厨房**完全反着**，
        #         我还照着它把吊柜压暗 0.72（说"米白对比太强"）——双重错。
        # ✅ 现在：**色相照实拍**（暖白 + 木色），**亮度整体压暗**（因为是半夜）。
        #    压暗系数 ≈ 0.42：白天 #ECEDE8 → 夜里 #63635F 的暖灰白。
        _D = 0.42
        def dk(r, g, b):
            return QColor(int(r * _D), int(g * _D), int(b * _D))
        parts = self.sparts
        for i, (x0, y0, x1, y1) in enumerate(self.room.platforms):
            if i == 0:      # 地板：暖木色（实拍 #7D6A59）
                p.setBrush(dk(125, 106, 89))                    # 夜里压暗后的木地板
                p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                p.setPen(QPen(dk(152, 139, 123), 2))              # 墙脚线
                p.drawLine(QPointF(x0, y0 + 1), QPointF(x1, y0 + 1))
                p.setPen(Qt.NoPen)
                continue
            _pw, _ph = x1 - x0, y1 - y0
            _img = None
            if i == 1:
                _img = parts.get("table")       # 餐桌：⚠️ AI 三次都出透视，执行端建议改程序绘制
            elif i == 2:
                _img = parts.get("counter")     # 料理台
            elif i == 3:
                _img = parts.get("cabinet")     # 吊柜
            if _img is not None:
                # ⭐ 保持宽高比贴入框中（⛔ 不拉伸变形：旧贴图是按 1.8m 宽的料理台出的，
                #   新布局的厨房桌只有 0.76m 宽，直接拉会把柜门压成竖条）
                _tw, _th2 = _img.width(), _img.height()
                _s = min(_pw / float(_tw), _ph / float(_th2))
                _dw, _dh = _tw * _s, _th2 * _s
                p.drawImage(QRectF(x0 + (_pw - _dw) / 2.0, y0 + (_ph - _dh) / 2.0, _dw, _dh),
                            _img, QRectF(0, 0, _tw, _th2))
                continue
            if i == 1:
                # ⭐ 餐桌程序绘制：纯几何形（矩形台面 + 两条矩形腿），AI 画不准，程序画反而更准
                #   配色照实拍木色：台面 #6B5B4B，夜里压暗
                p.setPen(Qt.NoPen)
                p.setBrush(dk(107, 91, 75))                       # 木桌面
                p.drawRect(QRectF(x0, y0, _pw, 16))
                p.setBrush(dk(116, 101, 82))                       # 桌面受光
                p.drawRect(QRectF(x0, y0, _pw, 4))
                p.setBrush(dk(87, 75, 59))                        # 腿
                p.drawRect(QRectF(x0 + 14, y0 + 16, 13, _ph - 16))
                p.drawRect(QRectF(x1 - 27, y0 + 16, 13, _ph - 16))
                p.setBrush(dk(70, 60, 48))                        # 腿根阴影
                p.drawRect(QRectF(x0 + 10, _ph - 6, _pw - 20, 6))
                continue
            # 通用台面（无贴图时的兜底）
            p.setBrush(dk(107, 91, 75))                        # 木色台面
            p.drawRoundedRect(QRectF(x0, y0, _pw, _ph), 5, 5)
            p.setPen(QPen(dk(130, 114, 96), 3))                 # 台面高光
            p.drawLine(QPointF(x0 + 4, y0 + 1.5), QPointF(x1 - 4, y0 + 1.5))
            p.setPen(Qt.NoPen)
            p.setBrush(dk(80, 68, 55))
            p.drawRect(QRectF(x0 + 10, y1, _pw - 20, min(120, VH - y1)))

        for (xc, ytop, ybot) in self.room.ladders:
            # ⭐⭐ 2026-10-03 Ronny：「梯子之后挪到挂毯和桌布上，这样看起来更有意思」
            #   —— 布是**软的、没有厚度**的，正好解掉他最早提的「梯子有厚度、姿势不适配」。
            #   ⭐ 而且猫爬布本来就比爬铁杆合理。
            # ⭐ 布是**静态的** → 底图（assets_game/scene_bg.png）里有美术版时就不画程序版，避免重影。
            #   ⭐ 冰箱相反：它要开门动画，永远程序画，底图里**不要**画冰箱。
            if self.has_scene_bg:
                break
            _hang = ytop < 300.0                     # 吊柜层那条 = 挂毯
            # ⭐ 优先用美术分件贴图（派单 40v3），缺件才退回程序绘制
            _pimg = self.sparts.get("towel" if _hang else "cloth")
            if _pimg is not None:
                _pw = _pimg.width() if not _hang else _pimg.width()
                p.drawImage(QRectF(xc - _pw / 2.0, ytop, _pw, ybot - ytop), _pimg,
                            QRectF(0, 0, _pimg.width(), _pimg.height()))
                continue
            w_ = 74.0 if not _hang else 62.0
            top_y = ytop - (4.0 if not _hang else 2.0)
            base = QColor(196, 122, 106) if not _hang else QColor(120, 158, 176)
            dark = QColor(158, 92, 82) if not _hang else QColor(92, 126, 146)
            p.setPen(Qt.NoPen)
            p.setBrush(dark)
            # 波浪底边（布的下摆不是直的）
            p.drawPath(self._cloth_path(xc, top_y, ybot, w_))
            p.setBrush(base)
            p.drawPath(self._cloth_path(xc, top_y, ybot, w_ - 7.0))
            # 竖向褶皱
            p.setPen(QPen(dark, 1.6))
            for k in (-1, 0, 1):
                xx = xc + k * (w_ * 0.26)
                p.drawLine(QPointF(xx, top_y + 6), QPointF(xx, ybot - 6 - abs(k) * 4))
            # ⭐ 横向小格纹（布的织纹，远看只是一点质感）
            p.setPen(QPen(dark, 1.0, Qt.DotLine))
            yy = top_y + 18
            while yy < ybot - 8:
                p.drawLine(QPointF(xc - w_ * 0.4, yy), QPointF(xc + w_ * 0.4, yy))
                yy += 22
            p.setPen(Qt.NoPen)

    @staticmethod
    def _cloth_path(cx, ytop, ybot, half_w):
        """一条垂下来的布：两侧微收、底边波浪。"""
        from PySide6.QtGui import QPainterPath
        pth = QPainterPath()
        amp = 7.0
        pth.moveTo(cx - half_w, ytop)
        pth.lineTo(cx - half_w * 0.92, ybot - amp)
        pth.quadTo(cx - half_w * 0.5, ybot + amp, cx, ybot - amp * 0.5)
        pth.quadTo(cx + half_w * 0.5, ybot - amp * 1.6, cx + half_w * 0.92, ybot - amp)
        pth.lineTo(cx + half_w, ytop)
        pth.closeSubpath()
        return pth

    def _draw_nest(self, p):
        x0, x1 = NEST_X0, NEST_X1
        p.setBrush(QColor(96, 74, 96))
        p.drawRoundedRect(QRectF(x0, FLOOR_Y - 26, x1 - x0, 30), 12, 12)
        p.setBrush(QColor(128, 100, 126))
        p.drawRoundedRect(QRectF(x0 + 8, FLOOR_Y - 18, x1 - x0 - 16, 16), 8, 8)
        # ⭐ 已入库的赃物堆（纯装饰，零数值，不影响任何判定）
        #   从 loot_log 取**实际偷到过的那些**，不是固定轮询 STASHES ——
        #   否则档一偷到的和档三偷到的摆出来一样，就不像"她偷了多少"。
        # ⭐ 窝边两栏：待结算（亮）在上，已入库（暗）在下 —— 玩家要能一眼看出「还没结算」
        for bag, is_stash in ((self.loot_stash, True), (self.loot_log[-12:], False)):
            for i, nm in enumerate(bag):
                ic = self.icons.get(nm)
                col, rw = i % 6, i // 6
                bx = x0 + 12 + col * 20
                by = FLOOR_Y - (46 if is_stash else 72) - rw * 22
                if ic is not None:
                    p.drawImage(QRectF(bx, by, 20, 20), ic, QRectF(0, 0, ic.width(), ic.height()))
                else:
                    p.setBrush(QColor(220, 180, 120))
                    p.drawEllipse(QPointF(bx + 10, by + 10), 8, 8)
        if self.loot_stash:
            near = self.luna.x < NEST_X1 + 90
            p.setPen(QColor(255, 226, 150) if near else QColor(198, 176, 116))
            p.setFont(QFont('Microsoft YaHei', 12, QFont.Bold))
            tip = '按 E 结算' if near else ('窝边待结算 %d 样' % len(self.loot_stash))
            p.drawText(QPointF(x0 - 14, FLOOR_Y - 84), tip)


    def _draw_fridge(self, p):
        """冰箱 + QTE 面板（Ronny 2026-10-03）

        ⭐⭐ 2026-10-03 21:05：**背景板已含冰箱**（美术件，`scene_bg.png` 里的 570~730/50~600）
        → 程序画的冰箱会**重影**，Ronny 实机反馈后**拆掉**。
        ⛔ 拆掉后代价：QTE 成功的"门开"动画做不了（美术图是静态的）。
        ✅ 替代反馈：**门缝透光 + 冰箱区域提亮**（见下面 bg 分支）。
        无背景板时（灰盒回退）仍走完整程序绘制。
        """
        fr = FRIDGE
        x, y0 = fr["x"], fr["y"] - fr["h"]
        w, h = fr["w"], fr["h"]
        if self.bg_img is not None:
            # ⭐ 背景板模式：冰箱已经在图里，⛔ 只叠加「门开」的替代反馈
            if self.fridge_door > 0.02:
                _a = int(150 * self.fridge_door)
                _vis = max(60.0, TABLE_TOP - 8.0 - y0)   # ⭐ 桌布以上的可见段（下面被布挡住）
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(210, 235, 255, _a))
                p.drawRect(QRectF(x + w - 16, y0 + 14, 6, min(h - 40, _vis - 14)))  # 门缝透光
                p.setBrush(QColor(190, 220, 255, int(46 * self.fridge_door)))
                p.drawRect(QRectF(x - 22, y0 - 10, w + 44, h + 20))      # 区域提亮
                p.setPen(QPen(QColor(255, 232, 180, int(190 * self.fridge_door)), 2))
                p.drawRect(QRectF(x - 22, y0 - 10, w + 44, h + 20))
            near = self._at_fridge()
            if self.room.fridge_left and not self.qte:
                p.setPen(QColor(255, 226, 150) if near else QColor(150, 140, 122))
                p.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
                p.drawText(QPointF(x - 4, y0 - 12), "按 E 撬开" if near else "冰箱")
            if self.qte:
                self._draw_qte(p)
            return
        p.setPen(QPen(QColor(146, 152, 164), 2))
        p.setBrush(QColor(206, 211, 220))
        p.drawRoundedRect(QRectF(x, y0, w, h), 12, 12)          # 柜体
        up_h = h * 0.36                                          # 上：冷冻室
        dn_y = y0 + up_h + 5
        dn_h = y0 + h - 6 - dn_y
        # ⭐ 下门（冷藏）：QTE 成功时向外转开
        swing = 26.0 * self.fridge_door                          # 最大开度（度）
        p.save()
        p.translate(x + 5, dn_y)                                 # 铰链在左边
        if swing > 0.5:
            p.setPen(QPen(QColor(60, 64, 74), 1.4))
            p.setBrush(QColor(236, 240, 246))
            # 开门后露出的"里面"（深色 + 一道冷光）
            p.setBrush(QColor(38, 42, 52))
            p.drawRect(QRectF(0, 0, w - 10, dn_h))
            p.setBrush(QColor(150, 210, 235, 90))
            p.drawRect(QRectF(2, 2, w - 14, dn_h - 4))
        p.setPen(QPen(QColor(120, 126, 138), 1.6))
        p.setBrush(QColor(228, 232, 238) if swing <= 0.5 else QColor(240, 244, 248))
        p.drawRect(QRectF(0, 0, w - 10, dn_h))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(158, 164, 176))
        p.drawRoundedRect(QRectF(w - 22, dn_h * 0.25, 5, dn_h * 0.5), 3, 3)
        p.restore()
        # 上门（冷冻）：固定关着
        p.setPen(QPen(QColor(120, 126, 138), 1.6))
        p.setBrush(QColor(228, 232, 238))
        p.drawRect(QRectF(x + 5, y0 + 5, w - 10, up_h - 3))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(158, 164, 176))
        p.drawRoundedRect(QRectF(x + w - 15, y0 + 14, 5, up_h * 0.45), 3, 3)
        p.setBrush(QColor(120, 128, 142))                       # 底部踢脚
        p.drawRect(QRectF(x + 4, y0 + h - 6, w - 8, 6))
        # 里面还剩几件（小横条，开门时才看得见）
        if self.fridge_door > 0.05:
            for f in self.room.fridge_left:
                p.setBrush(QColor(255, 230, 170, int(190 * self.fridge_door)))
                p.drawRect(QRectF(x + 12, dn_y + 10 + (f["y"] - 520) * 0.30, w - 30, 4))
        near = self._at_fridge()
        if self.room.fridge_left and not self.qte:
            p.setPen(QColor(255, 226, 150) if near else QColor(140, 132, 116))
            p.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
            p.drawText(QPointF(x - 10, y0 - 10), "按 E 撬开" if near else "冰箱")
        if self.qte:
            self._draw_qte(p)

    def _draw_qte(self, p):
        q = self.qte
        bw, bh, gap = 68.0, 68.0, 16.0
        n = len(q["seq"])
        total = n * bw + (n - 1) * gap
        x0 = VW * 0.5 - total / 2
        cy = 300.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(16, 16, 22, 218))
        p.drawRoundedRect(QRectF(x0 - 24, cy - bh / 2 - 30, total + 48, bh + 62), 14, 14)
        names = {Qt.Key_Left: "\u2190", Qt.Key_Right: "\u2192",
                 Qt.Key_Up: "\u2191", Qt.Key_Down: "\u2193"}
        for i, kd in enumerate(q["seq"]):
            x = x0 + i * (bw + gap)
            done = i < q["got"]
            p.setBrush(QColor(90, 200, 140) if done else QColor(52, 54, 66))
            p.setPen(QPen(QColor(214, 178, 118), 2))
            p.drawRoundedRect(QRectF(x, cy - bh / 2, bw, bh), 10, 10)
            p.setPen(QColor(20, 20, 26) if done else QColor(240, 232, 210))
            p.setFont(QFont("Consolas", 30, QFont.Bold))
            p.drawText(QRectF(x, cy - bh / 2 + 10, bw, bh), Qt.AlignCenter, names.get(kd, "?"))
        left = max(0.0, 1.0 - q["t"] / QTE_TIME_LIMIT)
        p.setBrush(QColor(40, 42, 52))
        p.drawRoundedRect(QRectF(x0 - 12, cy + bh / 2 + 12, total + 24, 10), 5, 5)
        p.setBrush(QColor(255, 190, 90) if left > 0.35 else QColor(255, 110, 80))
        p.drawRoundedRect(QRectF(x0 - 12, cy + bh / 2 + 12, (total + 24) * left, 10), 5, 5)
        p.setPen(QColor(240, 226, 196))
        p.setFont(QFont("Microsoft YaHei", 12))
        p.drawText(QRectF(x0 - 12, cy - bh / 2 - 24, total + 24, 20), Qt.AlignCenter,
                   "\u6309\u5e8f\u53eb\u65b9\u5411\u952e\uff08\u4ed6\u8fd8\u5728\u8ffd\uff09")

    def _draw_stashes(self, p):
        """容器：**按食物特性分四档**画（Ronny 2026-10-04「不要所有东西都放罐子里」）。

        ⭐ 四档的视觉语言必须一眼可辨 —— 玩家要在**看见容器的瞬间**就决定
          "这个值不值得冒险"，所以形状差异要大过颜色差异：
          · loose  敞开的碗/砧板，食物**完全露在外面**（最亮）
          · plate  扣着盖的盘子，盖上有个小把手
          · jar    密封罐，盖子是金属的 + 罐身高（最暗 + 有反光条）
          · fridge 冰箱格（画一个小格子框，不画罐子）
        ⛔ 完好时 jar/plate **不画食物全貌**（只透过缝看到一点），
          「看得见拿不到」是这机制的视觉核心；loose 例外 —— 它本来就是敞着的。
        """
        for st in self.room.stashes:
            ic = self.icons.get(st["icon"])
            cx, cy = st["x"], st["y"]
            kind = st.get("kind", "plate")
            if st["broken"]:
                # 碎掉之后：只剩碎片。⛔ 不再画食物 ——
                # 食物已经在她手上了（敲碎=拿走是同一下），留在原地等于凭空复制一份。
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(190, 205, 215, 120))
                # ⭐ 碎片形状跟着容器档位走：盘子碎成薄片、罐子碎成块
                if kind == "plate":
                    frags = ((-13, -2, 7, 2.4), (9, -1, 6, 2.0), (0, 4, 8, 2.2))
                elif kind == "jar":
                    frags = ((-13, -3, 4, 4), (9, -2, 3, 3), (0, 3, 3.5, 3.5),
                             (16, 4, 2.5, 2.5))
                else:                        # loose：碗/砧板碎片
                    frags = ((-12, 0, 6, 2.6), (10, 1, 5, 2.2))
                for dx, dy, rx, ry in frags:
                    p.drawEllipse(QPointF(cx + dx, cy + dy), rx, ry)
                continue
            if st.get("scratched"):
                # ⭐ 方案⑥（2026-10-03）：挠过但没碎 → 留三道爪痕
                #   （单 A 的 v1 视频动作幅度小，用这个补足"她在挠"的观感，零素材成本）
                p.setPen(QPen(QColor(236, 240, 246, 190), 2.2, Qt.SolidLine, Qt.RoundCap))
                for k in range(3):
                    sx = cx - 12 + k * 9
                    p.drawArc(QRectF(sx - 7, st["y"] - 34, 15, 26), 250 * 16, 110 * 16)

            # ⛔ 这里原来写的是 self.mw.climb_t —— 那是 Luna 的字段，Microwave 上没有
            #   （之前一直没炸是因为这个分支只在有完好容器时才走到，而旧测试恰好没渲染到）。
            #   ⭐ 统一用 self.mw_t（微波炉动画计时，全局都有）。
            bob = math.sin(self.mw_t * 2.0 + cx) * 1.6

            # ① 微光（提示这里有东西、可以拿）—— ⭐ 强度跟着档位走：
            #    jar 风险高 → 光最亮（远远就吸引注意，反而是"这是诱饵"的视觉语言）
            glow_a = 80 if kind == "loose" else (60 if kind == "plate" else 105)
            probe = QRectF(cx - 17, cy - 40 + bob, 34, 40)
            gg = QRadialGradient(probe.center(), 2, probe.center(), 40)
            gg.setColorAt(0, QColor(255, 230, 170, glow_a))
            gg.setColorAt(1, QColor(255, 230, 170, 0))
            p.fillRect(QRectF(cx - 40, cy - 60, 80, 80), QBrush(gg))

            if kind == "loose":
                # ---- ① 敞着放：一只浅碗 + 完全露在外面的食物 ----
                p.setBrush(QColor(214, 222, 228, 60))
                p.setPen(QPen(QColor(168, 184, 194), 1.6))
                p.drawEllipse(QRectF(cx - 20, cy - 14 + bob, 40, 13))
                p.drawArc(QRectF(cx - 20, cy - 20 + bob, 40, 20), 180 * 16, 180 * 16)
                if ic is not None:
                    p.setPen(Qt.NoPen)
                    # ⭐ loose 是唯一"食物全貌可见"的档 —— 它本来就是敞着的
                    p.drawImage(QRectF(cx - 16, cy - 30 + bob, 32, 32), ic,
                                QRectF(0, int(ic.height() * 0.18),
                                ic.width(), int(ic.height() * 0.82)))
            elif kind == "plate":
                # ---- ② 扣着盖的盘子：矮、宽、盖上有个小把手 ----
                p.setBrush(QColor(206, 216, 224, 110))
                p.setPen(QPen(QColor(158, 176, 188), 1.6))
                p.drawRoundedRect(QRectF(cx - 22, cy - 16 + bob, 44, 16), 5, 5)
                p.setBrush(QColor(178, 190, 200, 190))
                p.setPen(QPen(QColor(140, 158, 170), 1.4))
                p.drawRoundedRect(QRectF(cx - 23, cy - 25 + bob, 46, 11), 4, 4)
                # 盖顶把手（⛔ 别省，这是"盖着"的唯一识别特征）
                p.setPen(QPen(QColor(120, 138, 150), 2.0, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(cx - 5, cy - 27 + bob), QPointF(cx + 5, cy - 27 + bob))
                # 盖子边缘漏出一点食物色（"里面确实有东西"）
                if ic is not None:
                    p.setPen(Qt.NoPen)
                    p.drawImage(QRectF(cx - 12, cy - 20 + bob, 24, 14), ic,
                                QRectF(0, int(ic.height() * 0.30),
                                ic.width(), int(ic.height() * 0.70)))
            elif kind == "jar":
                # ---- ③ 密封罐：最高最暗 + 金属盖 + 两道反光条（旧版那个土黄块已删） ----
                body = QRectF(cx - 17, cy - 44 + bob, 34, 44)
                p.setBrush(QColor(196, 214, 224, 120))
                p.setPen(QPen(QColor(150, 172, 186), 1.6))
                p.drawRoundedRect(body, 7, 7)
                p.setBrush(QColor(122, 106, 96))
                p.setPen(QPen(QColor(90, 78, 72), 1.4))
                p.drawRoundedRect(QRectF(cx - 19, body.top() - 6, 38, 9), 3, 3)
                if ic is not None:
                    p.setPen(Qt.NoPen)
                    p.drawImage(QRectF(cx - 18, cy - 31 + bob, 36, 36), ic,
                                QRectF(0, int(ic.height() * 0.18),
                                ic.width(), int(ic.height() * 0.82)))
                # ⭐ 玻璃高光（两条 → 玻璃感；旧版只有一条，看着像塑料）
                p.setPen(QPen(QColor(255, 255, 255, 150), 2.4,
                              Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(cx - 10, body.top() + 8),
                           QPointF(cx - 10, body.top() + 20))
                p.setPen(QPen(QColor(255, 255, 255, 95), 1.8,
                              Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(cx + 6, body.top() + 12),
                           QPointF(cx + 6, body.top() + 24))
            else:  # fridge
                # ---- ④ 冰箱格：小格子框 + 里面透出的食物（由 _draw_fridge 主导，这里只画格） ----
                p.setBrush(QColor(150, 172, 186, 70))
                p.setPen(QPen(QColor(120, 146, 162), 1.6))
                p.drawRoundedRect(QRectF(cx - 20, cy - 26 + bob, 40, 30), 4, 4)
                p.setPen(QPen(QColor(120, 146, 162), 1.2))
                p.drawLine(QPointF(cx - 20, cy - 11 + bob), QPointF(cx + 20, cy - 11 + bob))
                if ic is not None:
                    p.setPen(Qt.NoPen)
                    p.drawImage(QRectF(cx - 14, cy - 22 + bob, 28, 28), ic,
                                QRectF(0, int(ic.height() * 0.18),
                                ic.width(), int(ic.height() * 0.82)))

            if st.get("scratched") and kind in ("plate", "jar"):
                # ⭐ 方案⑥（2026-10-03）：挠过但没碎的容器留三道爪痕 ——
                #   单 A 的 v1 视频动作幅度小（头部 y 极差仅 17px），用这个补足"她在挠"的观感，
                #   ⭐ 零素材成本。等单 A v3 出来了这段自然就不画了。
                p.setPen(QPen(QColor(236, 240, 246, 200), 2.2,
                              Qt.SolidLine, Qt.RoundCap))
                for k in range(3):
                    sx = cx - 12 + k * 9
                    p.drawArc(QRectF(sx - 7, cy - 30 + bob, 15, 24),
                              250 * 16, 110 * 16)
                p.setPen(Qt.NoPen)

        # ⑦ 碎裂特效（扩散的碎片环）
        for fx in self._break_fx:
            t = fx[2]
            p.setPen(Qt.NoPen)
            for k in range(7):
                ang = k * 0.897 + t * 0.6
                rad = 12 + 46 * t
                p.setBrush(QColor(236, 244, 250, int(230 * (1 - t))))
                p.drawEllipse(QPointF(fx[0] + math.cos(ang) * rad,
                                       fx[1] - 20 + math.sin(ang) * rad * 0.6),
                                 4.5 * (1 - t) + 1, 4.5 * (1 - t) + 1)

    def _draw_mw(self, p):
        m = self.mw
        x, y = m.x, m.y
        # 视野（只在追击时才明显，巡逻时很淡）
        a = int(40 + 70 * m.alert)
        vg = QLinearGradient(x, y - 40, x + m.face * m.sight, y - 40)
        vg.setColorAt(0, QColor(255, 170, 80, a))
        vg.setColorAt(1, QColor(255, 170, 80, 0))
        p.setBrush(QBrush(vg))
        p.setPen(Qt.NoPen)
        fx = x + m.face * m.sight
        p.drawPolygon([QPointF(x, y - 70), QPointF(fx, y - 230),
                       QPointF(fx, y + 30), QPointF(x, y - 20)])

        # ⭐ 本体：优先用真帧（派单 35 单 C），缺帧时退回灰盒方块
        _mf = self.gframes.get("mw_walk") or []
        if _mf:
            _k = int(self.mw_t * GAME_FPS["mw_walk"]) % len(_mf)
            _pm, _cw, _ch, _ax, _ay = _mf[_k]
            p.save()
            p.translate(x, y)
            if m.face != GAME_SRC_FACE["mw_walk"]:
                p.scale(-1.0, 1.0)
            p.drawImage(QRectF(-_ax, -_ay, _cw, _ch), _pm, QRectF(0, 0, _cw, _ch))
            p.restore()
        else:
            self._draw_mw_box(p, x, y, m)

        if m.state == "chase":
            p.setPen(QPen(QColor(255, 120, 80), 3))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(x, y - m.body_h - 26), 10, 10)
            p.setPen(Qt.NoPen)

    def _draw_mw_box(self, p, x, y, m):
        """灰盒兜底（没有真帧时用）。"""
        p.setBrush(QColor(44, 46, 58))
        _h = m.body_h
        _w = m.w * (_h / 78.0)
        p.drawRoundedRect(QRectF(x - _w / 2, y - _h, _w, _h), 12, 12)
        p.setBrush(QColor(30, 32, 42))
        p.drawRoundedRect(QRectF(x - _w / 2 + 10, y - _h + 12, _w - 20, _h - 32), 8, 8)
        glow = 120 + int(100 * max(m.alert, 0.25 if m.state == "chase" else 0.0))
        p.setBrush(QColor(255, 150 + glow // 4, 60, min(255, glow + 80)))
        ex = x + m.face * (_w / 2 - 14)
        p.drawRoundedRect(QRectF(ex - 6, y - _h + 20, 12, _h - 44), 5, 5)

    def _draw_luna(self, p):
        l = self.luna
        s = self.s
        # ⭐ 手上拿着东西时用游戏帧（run_carry），空手回到桌宠动作
        if l.act == "run_carry":
            _rf = self.gframes.get("run_carry") or []
            if _rf:
                _k = int(l.t * GAME_FPS["run_carry"]) % len(_rf)
                _pm, _cw, _ch, _ax, _ay = _rf[_k]
                p.save()
                p.translate(l.x, l.y)
                if l.face != GAME_SRC_FACE["run_carry"]:
                    p.scale(-1.0, 1.0)
                p.drawImage(QRectF(-_ax, -_ay, _cw, _ch), _pm, QRectF(0, 0, _cw, _ch))
                p.restore()
                for i, nm in enumerate(l.carrying):
                    ic = self.icons.get(_loot_split(nm)[1])
                    if ic is not None:
                        p.drawImage(QRectF(l.x - 9 + i * 18, l.y - 118 - i * 6, 18, 18),
                                    ic, QRectF(0, 0, ic.width(), ic.height()))
                return
        imgs = self.imgs.get(l.act) or self.imgs["idle"]
        act = self.pack.actions.get(l.act) or self.pack.actions["idle"]
        cw, ch = self.pack.canvas_of(l.act)
        ax, ay = self.pack.anchor_of(l.act)
        idx = int(l.t) % len(imgs)
        im = imgs[idx]

        p.save()
        p.translate(l.x, l.y)
        if l.face < 0:
            p.scale(-1.0, 1.0)
        p.drawImage(QRectF(-ax * s, -ay * s, cw * s, ch * s),
                    im, QRectF(0, 0, cw, ch))
        p.restore()

        # 携带的赃物（顶在头上）
        for i, nm in enumerate(l.carrying[-3:]):
            ic = self.icons.get(_loot_split(nm)[1])
            bx = l.x - 10 + i * 20
            by = l.y - ACTOR_H - 18 - i * 6
            if ic is not None:
                p.drawImage(QRectF(bx - 9, by, 18, 18), ic, QRectF(0, 0, ic.width(), ic.height()))
            else:
                p.setBrush(QColor(230, 190, 130))
                p.drawEllipse(QPointF(bx, by + 9), 8, 8)

    def _draw_hud(self, p):
        l, mw = self.luna, self.mw
        f = QFont("Microsoft YaHei", 13)
        p.setFont(f)

        # 越界提示
        trespass = l.x > self.room.border_x
        p.setPen(QColor(255, 235, 210))
        # ⛔ 别漏写技能键（2026-10-04 补）：提示条上一次只到 E，
        #   加了 J/K 之后没同步 → 玩家根本不知道这两个键存在。
        #   判据：这里出现的每个键，都必须能在 keyPressEvent 找到对应分支。
        p.drawText(QPointF(24, 32),
                   "A/D 移动    W 跳    W/S 爬梯    Shift 潜行    "
                   "E 敲碎容器    J 攻击    K 冲刺    R 重来    Esc 退出")

        cfg = NIGHTS[self.night_idx]
        done = sum(1 for s in self.room.stashes if s["broken"])
        state = "越界中" if trespass else "在允许区内"
        p.setPen(QColor(150, 240, 190) if not trespass else QColor(255, 170, 120))
        p.drawText(QPointF(24, 58),
                   f"{cfg['name']}　{state}　{l.sneak and '潜行中' or '…'}　手上 {len(l.carrying)} 样　"
                   f"已破 {done}/{len(self.room.stashes)}　窝边共 {self.total_loot} 样　"
                   f"{self.night_t:.0f}s")

        # 警戒条
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(QRectF(VW - 240, 20, 200, 12), 6, 6)
        col = QColor(255, 120, 80) if mw.state == "chase" else QColor(255, 190, 90)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(VW - 240, 20, 200 * mw.alert, 12), 6, 6)
        p.setPen(QColor(255, 235, 210))
        p.drawText(QPointF(VW - 240, 16), "微波炉")

        # 提示语
        if self.msg_t > 0:
            al = min(1.0, self.msg_t / 0.4)
            p.setPen(QColor(255, 240, 200, int(255 * al)))
            fb = QFont("Microsoft YaHei", 16)
            p.setFont(fb)
            p.drawText(QRectF(0, VH - 70, VW, 40), Qt.AlignCenter, self.msg)

    def _draw_meowed(self, p, t):
        a = min(1.0, t / 0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int(190 * a)))
        p.drawRect(QRectF(0, 0, VW, VH))
        fg = QFont("Georgia", 74, QFont.Bold)
        p.setFont(fg)
        p.setPen(QColor(196, 158, 92, int(255 * a)))
        p.drawText(QRectF(0, VH / 2 - 60, VW, 120), Qt.AlignCenter, "YOU MEOWED")
        fs = QFont("Microsoft YaHei", 15)
        p.setFont(fs)
        p.setPen(QColor(190, 190, 190, int(220 * a)))
        p.drawText(QRectF(0, VH / 2 + 60, VW, 40), Qt.AlignCenter, "被微波炉押送回窝")


# ============================================================================
# ⑦ 入口
# ============================================================================

def start(pack_dir: str):
    pack = load_pack(pack_dir)
    w = NightWindow(pack)
    w.show()
    return w


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    here = os.path.dirname(os.path.abspath(__file__))
    # ⛔ 别把 `--play` 当成角色包路径 —— 过滤掉所有 -- 开头的参数
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pack_dir = args[0] if args else os.path.join(
        os.path.dirname(here), "packs", "luna")
    w = start(pack_dir)
    # ⭐ `--play` = 跳过主菜单直接进游戏（省掉"还要按一下确认键"这一步）
    if "--play" in sys.argv:
        w.start_night(0)
        print("[夜间] 已启动：直接进档（--play）")
    else:
        print("[夜间] 已启动：主菜单（按 Space/回车 开始）")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
