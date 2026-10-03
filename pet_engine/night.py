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

FLOOR_Y = 648               # 地板顶面（y 向下）
NEST_X0, NEST_X1 = 96, 236  # 窝（回这里 = 这趟成功）
# ⛔⛔ 允许区边界**不在这里** —— 它是逐档的（NIGHTS[i]["border_x"]）。
#    留一个模块级 BORDER_X 会有个很坑的失败模式：谁改了它，游戏毫无反应，
#    因为真正生效的是 room.border_x。已删。

# 平台 (x0, y0=顶面, x1, y1=底面)。⛔ 单向平台：只有从上往下落才会踩到
PLATFORMS = [
    (0,    FLOOR_Y, VW, VH),        # 地板（也是单向，但从下面顶不上来）
    (520,  470,     880, 500),      # 料理台
    (980,  320,     1240, 350),     # 吊柜顶
]

# 梯子 (中心x, 顶端y, 底端y)
LADDERS = [
    (700, 470, FLOOR_Y),
]

# 赃物：y 是"它坐在哪个面上"（顶面 y）。icon 复用 packs/luna/ui/ 里的现成图标
# ⛔ 这份只是【档二·深夜】的基准数据，真正生效的是 NIGHTS[i]["stashes"]
STASHES = [
    {"x": 690,  "y": 470, "icon": "salmon"},
    {"x": 810,  "y": 470, "icon": "yogurt"},
    {"x": 1080, "y": 320, "icon": "chicken"},
    {"x": 1180, "y": 320, "icon": "shrimp"},
    {"x": 960,  "y": FLOOR_Y, "icon": "yolk"},
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

# ⛔ 微波炉的巡逻段/速度/视野/听觉/警戒涨速**全部逐档**（见 NIGHTS）。
#    这里只留两条不分档的：垂直容差、抓捕半径。
MW_SIGHT_DY = 110.0         # 视野垂直容差（不分档 —— 改了会让三档手感一起变）
MW_CATCH_R  = 52.0          # 抓捕半径（不分档 —— 这是"被抓住了"的判定，不该随难度漂）
ALERT_DECAY = 0.8           # 脱离视野每秒掉多少（不分档 —— 掉得快就没"绕开"这件事了）

ACTOR_H = 132.0             # ⭐ 露娜在关卡里的高度（逻辑像素），反推缩放系数
BODY_W  = 62.0              # 碰撞体宽度（比视觉窄，手感更好）

# ---- 容器 & 噪音（Ronny 2026-10-03：「吃的放在容器里，敲碎会惊动警卫」）----
# ⭐ 为什么是"累积值"而不是"一敲就警觉满"：一敲就满的话玩家只敢敲一次，
#   游戏退化成"敲一下立刻跑"，完全没有取舍。累积 + 衰减才有
#   「一路小心慢慢摸」和「快速砸开三个然后冲回窝」两条路。
NOISE_MAX   = 0.62          # ⭐ 贴着他耳朵敲，一次满 0.62 → 再两下就锁死
NOISE_DECAY = 0.30          # 每秒自然衰减
MW_HEAR_R   = 420.0         # ⭐ 听觉半径。⛔ 不能开大：室内可活动区宽 770px，开到 560 就是“全室都听见”，噪声机制等于没有。
                             # 420 让它变成位置相关的战术资源：微波炉走到东边时，西侧台面的容器就能安静顶掉。
SNEAK_SPEED = 108.0         # 潜行速度（正常 300）—— ⭐ 零素材成本，walk 动作直接用


NEED_ACTIONS = ["idle", "walk", "human_run", "jump", "fall", "climb", "land"]

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

_NIGHT1 = [
    {"x": 760,  "y": 470, "icon": "salmon"},
    {"x": 840,  "y": 470, "icon": "yogurt"},
    {"x": 1010, "y": FLOOR_Y, "icon": "yolk"},
    {"x": 1130, "y": FLOOR_Y, "icon": "blueberry"},
]
_NIGHT2 = list(STASHES)
_NIGHT3 = [
    {"x": 690,  "y": 470, "icon": "salmon"},
    {"x": 810,  "y": 470, "icon": "yogurt"},
    {"x": 1080, "y": 320, "icon": "chicken"},
    {"x": 1180, "y": 320, "icon": "shrimp"},
    {"x": 1040, "y": 320, "icon": "pumpkin"},
    {"x": 960,  "y": FLOOR_Y, "icon": "yolk"},
    {"x": 1160, "y": FLOOR_Y, "icon": "watermelon"},
]

NIGHTS = [
    {
        "name": "初更",
        "sub": "厨房灯刚灭，微波炉还没开始踱步",
        "stashes": _NIGHT1,
        "border_x": 500,
        "patrol": (760, 1010), "patrol_speed": 75.0,
        "chase_speed": 205.0, "sight": 240.0, "hear": 110.0,
        "alert_gain": 1.5, "alert_hear": 0.8,
    },
    {
        "name": "深夜",
        "sub": "正常的夜里。它开始踱步了。",
        "stashes": _NIGHT2,
        "border_x": 430,
        "patrol": (700, 1190), "patrol_speed": 95.0,
        "chase_speed": 250.0, "sight": 300.0, "hear": 150.0,
        "alert_gain": 1.9, "alert_hear": 0.95,
    },
    {
        "name": "凌晨三点",
        "sub": "整层楼只有冰箱在响。吊柜顶上那几样最好。",
        "stashes": _NIGHT3,
        "border_x": 360,
        "patrol": (640, 1230), "patrol_speed": 120.0,
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
    def __init__(self, x, y):
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
        # ⭐ 跳键闩锁：必须【松开再按】才能再跳。
        #   没有它的话按住 W 会落地即起跳一路连跳（实测踩上台面后立刻弹到 y=379），
        #   爬梯到顶也会自动弹一下 —— 玩家会觉得"我没让它跳"。
        self.jump_latch = False

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
        self.x += self.vx * dt
        self.y += self.vy * dt

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
        for (xc, ytop, ybot) in room.ladders:
            if abs(self.x - xc) < 30.0 and (ytop - 10.0) <= self.y <= (ybot + 10.0):
                return (xc, ytop, ybot)
        return None

    # ---- 表现 ---------------------------------------------------------
    def pick_action(self):
        if self.on_ladder:
            return "climb"
        if not self.on_ground:
            return "jump" if self.vy < -40 else "fall"
        if abs(self.vx) > 34.0:
            # ⭐ 潜行用 walk（28 帧慢走），正常跑用 human_run。
            #   ⛔ 别让潜行也播 human_run —— 那个是冲刺动作，播出来等于告诉她"我在全速跑"。
            return "run_carry" if self.carrying else ("walk" if self.sneak else "human_run")
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
        self.climb_t = 0.0
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

        s = self.sense(luna) if trespass else 0.0
        if s >= 1.0:
            self.alert = min(1.0, self.alert + self.alert_gain * dt)
        elif s > 0.0:
            self.alert = min(1.0, self.alert + self.alert_hear * dt)
        else:
            self.alert = max(0.0, self.alert - ALERT_DECAY * dt)

        if self.alert >= 1.0:
            self.state = "chase"
        elif self.alert <= 0.02 and self.state == "chase":
            self.state = "patrol"

        if self.state == "chase":
            self._chase(dt, luna, room)
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
            lad = min(room.ladders, key=lambda L: abs(L[0] - luna.x))
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

        dx = luna.x - self.x
        if abs(dx) > 4.0:
            self.face = 1 if dx > 0 else -1
            self.x += self.face * self.chase_speed * dt
        # 下平台：走出平台边缘就自由落体
        on_p = None
        for (x0, y0, x1, y1) in room.platforms:
            if x0 - 20 <= self.x <= x1 + 20 and abs(self.y - y0) < 2.0:
                on_p = y0
                break
        if on_p is None and self.y < FLOOR_Y:
            self.y = min(FLOOR_Y, self.y + self.chase_speed * 0.9 * dt)

    def caught(self, luna) -> bool:
        return (abs(luna.x - self.x) < MW_CATCH_R and
                abs(luna.y - self.y) < MW_CATCH_R + 20.0)


# ============================================================================
# ⑤ 关卡容器（把常量打包，方便以后换房间）
# ============================================================================

class Room:
    def __init__(self, cfg: dict):
        self.platforms = list(PLATFORMS)
        self.ladders = list(LADDERS)
        # ⭐ taken = 食物已被拿走；broken = 容器已被敲开（敲开才会变 taken）
        self.stashes = [dict(s, taken=False, broken=False) for s in cfg["stashes"]]
        self.border_x = float(cfg["border_x"])     # ⭐ 允许区边界随档位变
        self.mw_patrol = tuple(cfg["patrol"])


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
        self.luna = Luna(NEST_X0 + 70, FLOOR_Y)
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
        self._narr_seen = set()      # 本档已用过的旁白，避免连着重复
        self._break_fx = []          # 容器碎裂特效 [[x, y, t], ...]
        self.noise_flash = 0.0       # 噪音闪烁倒计时
        self.mw_t = 0.0              # 微波炉动画计时（步频按速度重映射）
        self._mw_px = self.mw.x      # 上一帧的 x（用来差分算速度，Microwave 没有 vx）
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
        if k == Qt.Key_E:
            self._try_break()
        elif k == Qt.Key_R:
            self.start_night(self.night_idx)

    def keyReleaseEvent(self, ev):
        self.keys.discard(ev.key())

    # ------------------------------------------------------------ 开一局
    def start_night(self, idx: int):
        cfg = NIGHTS[idx]
        self.night_idx = idx
        self.room = Room(cfg)
        self.luna = Luna(NEST_X0 + 70, FLOOR_Y)
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
        # ⭐⭐ 在崭边且崭边有待结算的东西 → E = 结算（而不是敲容器）
        if l.x < NEST_X1 + 40 and self.loot_stash:
            self._narrate("settle_now")
            self._settle()
            return
        if l.carrying:
            self._say("手上还拿着。放下才能再拿。")
            return
        for st in self.room.stashes:
            if st["broken"]:
                continue
            if abs(l.x - st["x"]) < 54.0 and abs(l.y - st["y"]) < 66.0:
                st["broken"] = True
                l.carrying = [st["icon"]]   # ⭐ 只拿一件
                self._break_fx.append([float(st["x"]), float(st["y"]), 0.0])
                self._make_noise(float(st["x"]), NOISE_MAX)
                self._narrate("steal")
                return
        self._narrate("empty")

    def _make_noise(self, x: float, strength: float):
        """一次声响。⭐ 强度按【与微波炉的距离】线性衰减，超出听觉半径他根本听不见。

        这条是"深层赃物取舍"的来源：近处的容器好够、但敲出来最响；
        吊柜顶上的最安全、也最难够。两条路都得走，玩家自己选。
        """
        self.noise_flash = 0.55
        mw = self.mw
        d = abs(x - mw.x)
        if d > MW_HEAR_R:
            self._say("…他没听见。")
            return
        # ⭐ 平方（而不是线性）衰减：声音随距离快速变弱。
        #   线性时 d=410/R=420 只剩 2.4%，“远处”和“贴身”差了 25 倍，中间段毫无区分。
        #   平方后：距 210 仍有 75%，距 350 剩 31% —— 两个区域有明确差异。
        f = 1.0 - (d / MW_HEAR_R) ** 2
        k = strength * f
        mw.alert = min(1.0, mw.alert + k)
        mw.hear_x = x              # ⭐ 他会转头朝声源看（比 alert 数字更有戏）
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
        """
        n = len(self.loot_stash)
        self.loot_log.extend(self.loot_stash)   # ⭐ 入库的是【实际偷到的那些】
        self.loot_stash = []                   # 结算完下架打空
        self.total_loot += n
        self.trip_loot += n
        base = n * 110
        clean = 40 if self.caught_cnt == 0 else 0
        late = max(0.0, self.night_t - n * 25.0) * 2.0
        score = base + clean - self.caught_cnt * 30 - late
        rank = "S" if score >= 780 else "A" if score >= 560 else "B" if score >= 380 else "C"
        left = sum(1 for s in self.room.stashes if not s["taken"])
        self.result = {
            "night": NIGHTS[self.night_idx]["name"],
            "loot": n, "left": left, "total": self.total_loot,
            "caught": self.caught_cnt, "time": self.night_t,
            "score": int(round(score)), "rank": rank,
        }
        self.phase = "result"
        self.phase_t = 0.0
        self._narrate("finish" if left == 0 else "home")
        print(f"[夜间] 结算：带回 {n} 剩 {left} 被抓 {self.caught_cnt} "
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
        self.mw_t += dt * (min(_mwv / 95.0, 3.0) if _mwv > 1.0 else 0.4)

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
            l.update(dt, self.keys, self.room)
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
        self._draw_platforms(p)
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
        for i, (x0, y0, x1, y1) in enumerate(self.room.platforms):
            if i == 0:      # 地板
                p.setBrush(QColor(58, 52, 62))
                p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                p.setPen(QPen(QColor(90, 82, 96), 2))
                p.drawLine(QPointF(x0, y0 + 1), QPointF(x1, y0 + 1))
                p.setPen(Qt.NoPen)
                continue
            # 台面
            p.setBrush(QColor(74, 66, 80))
            p.drawRoundedRect(QRectF(x0, y0, x1 - x0, y1 - y0), 5, 5)
            p.setPen(QPen(QColor(120, 112, 126), 3))
            p.drawLine(QPointF(x0 + 4, y0 + 1.5), QPointF(x1 - 4, y0 + 1.5))
            p.setPen(Qt.NoPen)
            # 柜体（虚化的下半截）
            p.setBrush(QColor(48, 44, 56))
            p.drawRect(QRectF(x0 + 10, y1, x1 - x0 - 20, min(120, VH - y1)))

        for (xc, ytop, ybot) in self.room.ladders:
            # ⭐ 梯子重画：44px 宽的实体 → 【两根细杆 + 横档】（Ronny 10-03）
            #   实体梯子有厚度，挤在露娜身上就看不清她在爬什么。
            p.setPen(QPen(QColor(150, 140, 160), 4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(xc - 13, ytop), QPointF(xc - 13, ybot))
            p.drawLine(QPointF(xc + 13, ytop), QPointF(xc + 13, ybot))
            p.setPen(QPen(QColor(120, 112, 132), 3))
            for yy in range(int(ytop) + 14, int(ybot), 24):
                p.drawLine(QPointF(xc - 13, yy), QPointF(xc + 13, yy))
            p.setPen(Qt.NoPen)

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


    def _draw_stashes(self, p):
        """容器：⛔ 完好时**不画食物**（只透过玻璃看到一点轮廓），
        敲碎那一帧才把食物真正露出来 —— 「看得见拿不到」是这机制的视觉核心。"""
        for st in self.room.stashes:
            ic = self.icons.get(st["icon"])
            cx, cy = st["x"], st["y"]
            if st["broken"]:
                # 碎掉之后：只剩罐子碎片。⛔ 不再画食物 ——
                # 食物已经在她手上了（敲碎=拿走是同一下），留在原地等于凭空复制一份。
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(190, 205, 215, 120))
                for dx, dy, r in ((-13, -3, 4), (9, -2, 3), (0, 3, 3.5), (16, 4, 2.5)):
                    p.drawEllipse(QPointF(cx + dx, cy + dy), r, r)
                continue

            bob = math.sin(self.mw.climb_t * 2 + cx) * 1.6
            body = QRectF(cx - 17, cy - 40 + bob, 34, 40)
            # ① 微光（提示这里有东西、可以敲）
            gg = QRadialGradient(body.center(), 2, body.center(), 40)
            gg.setColorAt(0, QColor(255, 230, 170, 80))
            gg.setColorAt(1, QColor(255, 230, 170, 0))
            p.fillRect(QRectF(cx - 40, cy - 60, 80, 80), QBrush(gg))
            # ② 罐盖
            p.setBrush(QColor(122, 106, 96))
            p.setPen(QPen(QColor(90, 78, 72), 1.4))
            p.drawRoundedRect(QRectF(cx - 19, body.top() - 6, 38, 9), 3, 3)
            # ③ 玻璃罐身（半透明，能看见里面食物的轮廓）
            p.setBrush(QColor(196, 214, 224, 120))
            p.setPen(QPen(QColor(150, 172, 186), 1.6))
            p.drawRoundedRect(body, 7, 7)
            # ④ 里面的食物：只画底部一条（露一点轮廓，不给全貌）
            if ic is not None:
                p.setPen(Qt.NoPen)
                # ⛔ drawImage 只接 (target, image, source)三个参数，没有四参数重载（多传一个 source 会 TypeError）
                # ⭐ 食物画大一点（Ronny 10-03）：30px → 36px，且取更大部分
                p.drawImage(QRectF(cx - 18, cy - 27 + bob, 36, 36), ic,
                            QRectF(0, int(ic.height() * 0.18),
                            ic.width(), int(ic.height() * 0.82)))
                p.setBrush(QColor(220, 180, 120))
                p.drawEllipse(QPointF(cx, cy - 12), 12, 8)
            # ⑤ 玻璃高光
            p.setPen(QPen(QColor(255, 255, 255, 150), 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx - 10, body.top() + 8), QPointF(cx - 10, body.top() + 20))

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
                    ic = self.icons.get(nm)
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
            ic = self.icons.get(nm)
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
        p.drawText(QPointF(24, 32), "A/D 移动    W 跳    W/S 爬梯    Shift 潜行    E 敲碎容器    R 重来    Esc 退出")

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
    pack_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(here), "packs", "luna")
    w = start(pack_dir)
    print("[夜间] 已启动：深夜厨房灰盒")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
