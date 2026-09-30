# -*- coding: utf-8 -*-
"""core.py —— 桌面宠物引擎 · 纯逻辑层（⛔ 零 UI 依赖）

⭐ 为什么单独一层：今天踩的坑（循环周期 / 步幅 / 屏幕限位 / 拖拽手感）
  **全是这一层的事**。拆干净了，将来换壳（Godot / Electron）只重写 ui/，素材与参数不动。

⛔ 本文件不许 import PySide6 / PyQt / tkinter —— 保持可单独测试。
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ============================================================================
# ① 角色包加载
# ============================================================================

@dataclass
class Action:
    name: str
    frames: int                  # 帧数
    fps: float                   # 播放帧率
    loop: str                    # cycle | once | pingpong | hold
    cycle_frames: Optional[int] = None   # ⭐ 一个完整循环跨多少帧（走路的"两步"就填这里）
    stride_px: Optional[float] = None    # ⭐ 一个循环前进多少像素 → 引擎自己推每帧位移
    mirrorable: bool = False             # 能否由本动作镜像出反向（左走）
    # ⭐⭐ 2026-09-27：逐动作画布（支持横画幅）
    #    趴姿是横躺的，用 2:3 竖幅会把她挤成一小团 → 睡眠三段改走横画幅。
    #    None = 回落顶层 canvas/anchor（现有 9 个动作不受影响，向后兼容）。
    canvas: Optional[Tuple[int, int]] = None   # 本动作的画布尺寸
    anchor: Optional[Tuple[int, int]] = None   # 本动作的贴地参考点在画布中的位置
    # ⭐⭐ 2026-09-28：起始帧（once 动作跳过素材开头的静止预备段）
    #    实测依据（_析_转身diff.py）：turn_in 18 帧里 #0-#8 相邻差异率 0.02~2.4%（基本静止），
    #    #9 起才真正转身（11%→22%）。整段播 = 决定走路后原地站 0.72s 才动身，观感迟钝。
    #    pet.json 里给 turn_in 写 "start": 9 → 只播转身段。
    start: int = 0
    # ⭐⭐ 2026-09-28：动作切换的几何补偿数据（由装机脚本预计算写进 pet.json）
    #    角色 bbox 中心在【画布】内的坐标。切动作时用它让【角色视觉位置】连续 ——
    #    否则"躺→站"这类切换会因 anchor / 画布尺寸不同而整只跳走。
    #    实测：sleep_out 末帧中心 x=358.5 vs idle x=273 → 无补偿时水平跳 85px（Ronny 看到的"闪烁"）。
    entry_center: Optional[Tuple[float, float]] = None
    exit_center: Optional[Tuple[float, float]] = None
    # ⭐⭐ 2026-09-29：叠加道具层（方案 B）
    #    角色帧之上，按帧号叠一张或多张 PNG 并控制显隐。
    #    ⭐ 用途（Ronny：「端起饭碗一口闷，吃完碗应该是空的」）：
    #      角色视频里的碗**始终画成空的**，碗里的食物由这里叠加 →
    #      "吃完碗空"= 到某一帧把食物层隐藏 = 【确定性代码控制】，不靠 AI 画对。
    #    每项字段（全部可选，缺省见 ui.py `_draw_overlays`）：
    #      image : str         —— ui/ 下的文件名（如 "food_chicken.png"）
    #      anchor: [x, y]      —— 叠加图左上角相对【本动作 anchor】的偏移（画布坐标）
    #      scale : float       —— 额外缩放（1.0 = 原始像素）
    #      show  : [起帧, 止帧] —— 只在这段帧号内显示（含端点；缺省=全程）
    #      fade_out: [起帧, 止帧] —— 在这段内由全显渐隐到 0（用于"吃完了"）
    overlays: Optional[list] = None

    @property
    def frame_dt(self) -> float:
        return 1.0 / self.fps

    @property
    def move_per_frame(self) -> float:
        """⭐ 每帧位移 = 步幅 ÷ 循环帧数。**不再需要手调 frame_move。**"""
        if not self.stride_px or not self.cycle_frames:
            return 0.0
        return self.stride_px / self.cycle_frames

    def sequence(self) -> List[int]:
        """返回播放顺序的帧号列表（含 loop 展开）"""
        n = self.frames
        s = min(self.start, max(0, n - 1))      # ⭐ once 动作的起始帧（跳过静止预备段）
        if self.loop == "cycle":
            return list(range(n))
        if self.loop == "once" or self.loop == "hold":
            return list(range(s, n))
        if self.loop == "pingpong":
            return list(range(n)) + list(range(n - 2, 0, -1))   # 不去重首尾
        return list(range(n))


@dataclass
class Behaviour:
    idle_duration: Tuple[float, float] = (3.0, 8.0)
    walk_duration: Tuple[float, float] = (2.5, 5.0)
    turn_ease_tau: float = 0.35
    # ⭐ v0.2 互动与目标导向
    mood_max: float = 100.0            # 好感度上限
    mood_per_click: float = 8.0        # 每点一下加多少
    mood_decay: float = 1.2            # 每秒自然衰减
    seek_cursor_mood: float = 65.0     # ⭐ 好感度高于这个 → 会主动朝光标走
    seek_chance: float = 0.5           # 达到条件时"去找光标"的概率
    arrive_eps: float = 12.0           # 距目标多近算"到了"（px）
    pat_duration: float = 1.2          # 被摸时播多久 pat（秒）        # ⭐ 掉头缓动（秒）：换向时速度平滑过零，不是一帧掉头   # ⭐ 走多久再重新决定（原来复用 idle_duration，且从不重置 → 每帧重入）
    turn_chance: float = 0.35                          # ⭐ 换向概率（1.0 = 每次都翻 = 闪烁）
    walk_weight: float = 0.6
    gravity: float = 1800.0
    # ⭐⭐ 单摆模型（Ronny 定的规格）：鼠标速度 = 力，重力拉回，有惯性
    drag_tilt_max: float = 45.0        # 硬上限（"晃个 45° 不成问题"）
    tilt_omega0: float = 5.0           # 固有频率 rad/s（越大回正越快、越"轻"）
    tilt_zeta: float = 0.35            # 阻尼比 <1 → 欠阻尼，会晃过头（惯性感的来源）
    tilt_drive: float = 2200.0         # 鼠标速度达到 v_ref 时的驱动力（度/s²）
    tilt_vref: float = 3000.0          # 多大的鼠标速度算"快速甩"（px/s）
    tilt_v_tau: float = 0.05           # 鼠标速度低通（滤抖动）
    tilt_force_tau: float = 0.12       # ⭐ 力的惯性：换向时"手"不会瞬移（越大越拖）
    tilt_drive_exp: float = 1.6        # ⭐ 力的指数曲线：>1 → 慢移几乎不倾、快甩才猛涨
    screen_margin: int = 0
    walk_speed: float = 1.0        # 走速倍率（手感微调用）
    # ⭐⭐ 2026-09-29 Ronny 定：激光笔在手时移速暴增至该倍率（露娜 = 2.5）
    #   为什么单列一个数：这是**角色设定**（猫的兴奋程度/体能），不是引擎常数。
    #   以后放到角色包里，一只猫一个值 —— 同样的红点，慢猫和快猫反应不一样。
    laser_speed_mul: float = 2.5
    # ⭐⭐ 睡眠（2026-09-26）：连续待机多久睡着 → 睡着 → 叫醒 → 伸懒腰
    sleep_after: Tuple[float, float] = (40.0, 90.0)   # 连续无互动多久入睡（秒，随机区间）
    sleep_mood_decay_scale: float = 0.2               # 睡着时好感度衰减倍率（睡得香，掉得慢）
    wake_radius: float = 120.0                        # 光标靠近多少 px 会把她吵醒
    stretch_chance: float = 0.6                       # 醒来后做伸懒腰的概率
    sleep_wakeup_need: float = 1.0                    # 摇几下才醒（拖拽时）——预留


@dataclass
class PetPack:
    name: str
    root: str
    canvas: Tuple[int, int]
    anchor: Tuple[int, int]        # 角色"脚底中点"在画布中的位置
    actions: Dict[str, Action]
    behaviour: Behaviour
    scale: float = 1.0
    # ⭐⭐ 2026-09-30：桌面上这个角色该多大 —— 这是**角色设定**（和 laser_speed_mul 同类），
    #   不是引擎常数。⛔ 此前它被硬编码在 ui.py 里（0.45*(1/0.85)^3），
    #   调大小必须改代码，而且让所有 anchor×s 的算式带上非整数倍。
    display_scale: float = 1.0

    def frame_path(self, action: str, idx: int) -> str:
        return os.path.join(self.root, "action", f"{action}_{idx}.png")

    def canvas_of(self, action: str) -> Tuple[int, int]:
        """⭐ 取某动作的画布尺寸：动作自己声明优先，否则回落顶层"""
        act = self.actions.get(action)
        if act is not None and act.canvas is not None:
            return act.canvas
        return self.canvas

    def anchor_of(self, action: str) -> Tuple[int, int]:
        """⭐ 取某动作的贴地参考点：动作自己声明优先，否则回落顶层。

        ⚠️ 语义：从"脚底中点"扩展为"贴地参考点" ——
           站姿 = 脚底中点；侧躺 = 身体下缘中点。都是"贴着地面那个点"。
        """
        act = self.actions.get(action)
        if act is not None and act.anchor is not None:
            return act.anchor
        return self.anchor


def load_pack(folder: str) -> PetPack:
    with open(os.path.join(folder, "pet.json"), "r", encoding="utf-8") as f:
        d = json.load(f)
    acts = {}
    for k, v in d.get("actions", {}).items():
        acts[k] = Action(name=k, frames=int(v["frames"]), fps=float(v.get("fps", 10)),
                         loop=v.get("loop", "cycle"),
                         cycle_frames=v.get("cycle_frames"),
                         stride_px=v.get("stride_px"),
                         mirrorable=bool(v.get("mirrorable", False)),
                         # ⭐ 逐动作画布：不写 → None → 回落顶层（向后兼容）
                         canvas=tuple(v["canvas"]) if v.get("canvas") else None,
                         anchor=tuple(v["anchor"]) if v.get("anchor") else None,
                         start=int(v.get("start", 0)),
                         entry_center=tuple(v["entry_center"]) if v.get("entry_center") else None,
                         exit_center=tuple(v["exit_center"]) if v.get("exit_center") else None,
                         # ⭐ 叠加道具层（缺省 None = 无叠加，不影响现有动作）
                         overlays=list(v["overlays"]) if v.get("overlays") else None)
    b = d.get("behaviour", {})
    beh = Behaviour(
        idle_duration=tuple(b.get("idle_duration", (3.0, 8.0))),
        walk_duration=tuple(b.get("walk_duration", (2.5, 5.0))),
        turn_ease_tau=float(b.get("turn_ease_tau", 0.35)),
        mood_max=float(b.get("mood_max", 100.0)),
        mood_per_click=float(b.get("mood_per_click", 8.0)),
        mood_decay=float(b.get("mood_decay", 1.2)),
        seek_cursor_mood=float(b.get("seek_cursor_mood", 65.0)),
        seek_chance=float(b.get("seek_chance", 0.5)),
        arrive_eps=float(b.get("arrive_eps", 12.0)),
        pat_duration=float(b.get("pat_duration", 1.2)),
        turn_chance=float(b.get("turn_chance", 0.35)),
        walk_weight=float(b.get("walk_weight", 0.6)),
        gravity=float(b.get("gravity", 1800.0)),
        drag_tilt_max=float(b.get("drag_tilt_max", 45.0)),
        tilt_omega0=float(b.get("tilt_omega0", 5.0)),
        tilt_zeta=float(b.get("tilt_zeta", 0.35)),
        tilt_drive=float(b.get("tilt_drive", 2200.0)),
        tilt_vref=float(b.get("tilt_vref", 3000.0)),
        tilt_v_tau=float(b.get("tilt_v_tau", 0.05)),
        tilt_force_tau=float(b.get("tilt_force_tau", 0.12)),
        tilt_drive_exp=float(b.get("tilt_drive_exp", 1.6)),
        screen_margin=int(b.get("screen_margin", 0)),
        walk_speed=float(b.get("walk_speed", 1.0)),
        laser_speed_mul=float(b.get("laser_speed_mul", 2.5)),
        sleep_after=tuple(b.get("sleep_after", (40.0, 90.0))),
        sleep_mood_decay_scale=float(b.get("sleep_mood_decay_scale", 0.2)),
        wake_radius=float(b.get("wake_radius", 120.0)),
        stretch_chance=float(b.get("stretch_chance", 0.6)),
        sleep_wakeup_need=float(b.get("sleep_wakeup_need", 1.0)),
    )
    return PetPack(name=d.get("name", os.path.basename(folder)), root=folder,
                   canvas=tuple(d.get("canvas", (512, 512))),
                   anchor=tuple(d.get("anchor", (256, 512))),
                   actions=acts, behaviour=beh, scale=float(d.get("scale", 1.0)),
                   display_scale=float(d.get("display_scale", 1.0)))


# ============================================================================
# ② 动作状态机（纯逻辑）
# ============================================================================

class Anim:
    """一个动作的播放游标"""

    def __init__(self, act: Action):
        self.act = act
        self.seq = act.sequence()
        self.t = 0.0
        self.i = 0
        self.finished = False

    def advance(self, dt: float) -> int:
        """推进 dt 秒，返回当前应显示的帧号（原图帧号）"""
        self.t += dt
        while self.t >= self.act.frame_dt:
            self.t -= self.act.frame_dt
            self.i += 1
            if self.i >= len(self.seq):
                if self.act.loop in ("cycle", "pingpong"):
                    self.i = 0
                else:
                    self.i = len(self.seq) - 1
                    self.finished = True
        return self.seq[self.i]

    def reset(self):
        self.t = 0.0
        self.i = 0
        self.finished = False


@dataclass
class Body:
    """宠物的世界坐标与物理量（⭐ 用"脚底中点"作为参考点，方便贴地）"""
    x: float = 0.0
    y: float = 0.0          # 脚底 y
    vx: float = 0.0
    vy: float = 0.0
    on_ground: bool = True
    tilt: float = 0.0       # ⭐ 当前倾角（度）

    def clamp_to_screen(self, screen: Tuple[int, int, int, int],
                        silhouette: Tuple[int, int, int, int], margin: int = 0):
        """⭐ 按【角色实际轮廓】限位（不是按窗口中心 —— 那是 DyberPet 的坑）

        screen      = (left, top, right, bottom) 桌面可用区
        silhouette  = (dx_left, dx_right, dy_top, dy_bottom)
                      角色轮廓相对"脚底中点"的四向偏移
        """
        sl, st, sr, sb = screen
        dl, dr, dtp, dbt = silhouette
        # 左：脚底 x + dl 不能小于 sl
        self.x = max(self.x, float(sl - dl + margin))
        # 右：脚底 x + dr 不能大于 sr
        self.x = min(self.x, float(sr - dr - margin))
        # 下：脚底 y 不能超过屏幕底
        bottom_limit = float(sb - dbt)
        if self.y > bottom_limit:
            self.y = bottom_limit
            self.vy = 0.0
            if not self.on_ground:
                self.on_ground = True
        # ⭐⭐ 上：头顶不能超出屏幕顶（2026-09-28 实测缺这条 → 睡眠站起时头顶被切）
        #   silhouette 的 dtp 是【负数】（向上偏移），所以 top_limit = st - dtp = st + |dtp|
        #   ⛔ 睡眠动作站姿帧轮廓高 507，比 idle 的 488 高 → 睡着站起来时最容易顶出去
        top_limit = float(st - dtp + margin)
        if self.y < top_limit:
            self.y = top_limit
            if self.vy < 0:
                self.vy = 0.0


class Pet:
    """宠物：状态机 + 物理（⛔ 不含任何渲染）"""

    def __init__(self, pack: PetPack, screen: Tuple[int, int, int, int]):
        self.pack = pack
        self.behaviour = pack.behaviour
        self.screen = screen
        self.body = Body()
        self.body.x = (screen[0] + screen[2]) / 2
        self.body.y = float(screen[3])
        self.anim: Optional[Anim] = None
        self.state = "idle"
        self.facing_right = True
        self.state_timer = random.uniform(*self.behaviour.idle_duration)
        self.dragging = False
        self._drag_hist: List[Tuple[float, float, float]] = []
        # ⭐ 惯性倾斜用的状态（速度/加速度估计）
        self._tilt_x = self.body.x
        self._tilt_vx = 0.0
        self._tilt_vx_f = 0.0
        self._last_dt = 1 / 60
        # ⭐ 单摆状态：角（度）与角速度（度/秒）
        self._theta = 0.0
        self._omega = 0.0
        self._force_f = 0.0            # ⭐ 带惯性的力（手也有质量）
        self._walk_v = 0.0
        # ⭐ v0.2
        self.mood = 50.0
        self.goal = None               # "goto" | "seek" | None
        self.goal_x = 0.0
        self._pat_t = 0.0              # 被摸剩余时间
        self._cursor_x = None          # 最近一次光标位置（由 UI 喂进来）
        # ⭐⭐ 2026-09-30 光标唤醒改【边沿触发】：记上一帧光标在不在 wake_radius 内。
        #   为什么：点枕头让她睡时鼠标正压在她身上（距离 0px），
        #   电平触发会让她刚躺下就被自己的鼠标摇醒 → 播 sleep_out（Ronny 报的 bug）。
        self._cursor_near = False
        self._hearts = []              # ⭐ 供 UI 画的爱心（(t秒, x偏移)）            # ⭐ 当前走路速度（平滑跟随目标，掉头时过零）
        # ⭐⭐ 睡眠状态（2026-09-26）
        self.asleep = False            # 正在睡（sleep_in 之后 / sleep_loop 中）
        self._sleep_t = 0.0            # 连续"清醒待机"累计秒
        self._sleep_need = random.uniform(*self.behaviour.sleep_after)   # 本次入睡阈值
        self._wake_stage = 0           # 0=没在起 1=正在放 sleep_out 2=正在放 stretch
        self.last_wake_reason = ""
        self.play("idle")

    # ---------- 动作 ----------
    def _center_near(self, name: str, near_end: bool):
        """取某动作的"角色中心"（画布坐标）。near_end=True 用退出中心，否则用入口中心。"""
        a = self.pack.actions.get(name)
        if a is None:
            return None
        return (a.exit_center or a.entry_center) if near_end else (a.entry_center or a.exit_center)

    def play(self, name: str):
        act = self.pack.actions.get(name)
        if act is None:
            return
        if self.anim and self.anim.act.name == name and act.loop in ("cycle", "pingpong"):
            return
        # ⭐⭐ 2026-09-28 修：动作切换的几何补偿（Ronny：「sleep out 和 default 中间有闪烁」）
        #   渲染恒等式 W = body - anchor（ui.py `_apply_pos`），角色锚点的屏幕坐标 = W + a = body。
        #   要求切换前后【角色的世界坐标】不变 ⇒ body 不该动；
        #   要求切换前后【画面上的落地点】不变 ⇒ 只需补 anchor 差：
        #       body += (a_new - a_old)
        #
        #   ⛔⛔ 2026-09-29 修（Ronny：「sleep out 之后人物往上闪现了大概半个身位」）
        #   上一版还额外补偿了 bbox 中心差 (c_old - c_new)，**这是错的**。
        #   实测：sleep_out→stretch 单帧跳 (+118.5, -20.0)，sleep_out→idle 跳 (+101.5, -12.0)。
        #   根因：`c` 是【角色 bbox 在画布内的构图位置】，不是角色在世界里的位置。
        #   sleep_out 这一个动作内部，角色从趴姿（中心 y=419）爬起到站姿（中心 y=257.5），
        #   构图本身就在画布内大幅移动 —— 这是**素材内部该发生的位移**，
        #   补偿再去用 c_old 反推 body，等于把同一份位移做了两遍，角色整体向上飞。
        #   ✅ 只用 anchor 差后：sleep_out→stretch 只动 (+16, -6)，stretch→idle 动 (0, 0)（anchor 相同）。
        #   ⚠️ 副作用：sleep_out 末帧构图偏右（中心 x=358.5）会保留 ——
        #      但那是**素材构图**问题，该在素材层修（重出/重裁 sleep_out），不该用位置补偿掩盖。
        # ⭐⭐⭐ 2026-09-30：切动作的几何补偿**整体搬到 UI 层**（PetWindow._compensate_switch）。
        #   ⛔ 这里原来做 `body += (a_new - a_old)`（anchor 差），是错的口径：
        #      anchor 差 ≠ "角色在画面上的实际贴地点之差"。
        #      实测（切动作时角色最低点的屏幕跳变）：
        #        sleep_out 末帧 → idle 首帧   水平 +74.4px / 垂直 -9.5px
        #        sleep_out 末帧 → stretch 首帧 水平 +86.8px / 垂直 -9.5px
        #        idle 末帧 → sleep_in 首帧     水平 -55.0px
        #      因为 sleep 三件套画布 520x536 / anchor.x=240，而站姿段素材构图偏右
        #      （末帧 bbox 中心 358.5，idle 是 273）→ 一切回 idle 就横向瞬移 74px。
        #   ✅ 正确口径只有 UI 层能算：它手里有**每一帧的真实 bbox**。
        #      补偿判据 = 让"角色在屏幕上的最低点"与"中轴"在切换前后不动：
        #          屏幕最低点 = body.y + (y1_img − anchor.y) × s
        #          屏幕中轴   = body.x + ((x0+x1)/2 − anchor.x) × s
        #      （推导见 ui.py `_compensate_switch`）
        _ = self.state
        self.anim = Anim(act)
        self.state = name

    # ---------- ⭐⭐ 睡眠 / 叫醒 / 伸懒腰 ----------
    def _has(self, name: str) -> bool:
        return name in self.pack.actions

    def fall_asleep(self):
        """入睡：sleep_in（once）→ sleep_loop（循环）"""
        if self.asleep or self.dragging:
            return False
        self.asleep = True
        self.goal = None
        self._sleep_t = 0.0
        self._wake_stage = 0
        # ⭐⭐ 2026-09-30：入睡瞬间【预热"光标在不在附近"】。
        #   ⛔ 否则入睡第一帧会把"光标本来就压在她身上"误判成"刚从外面进来" → 立刻摇醒。
        #     （_dbg_枕头.py 冷启动 A 组就是这么被摇醒的：光标距离 0 ≤ wake_radius 120）
        if self._cursor_x is not None:
            self._cursor_near = (abs(self._cursor_x - self.body.x)
                                 <= self.behaviour.wake_radius)
        if self._has("sleep_in"):
            self.play("sleep_in")            # 播完由 step() 接到 sleep_loop
        else:
            self.play("sleep_loop" if self._has("sleep_loop") else "idle")
        return True

    def wake(self, reason: str = "") -> bool:
        """叫醒：sleep_out（once）→ stretch（once，可缺省）→ idle

        ⭐ 三段衔接是关键：
           sleep_out 播完**不能直接回 idle**（那会有"睡姿→站姿"的硬切），
           而是接一个舒展动作（伸懒腰），再回 idle。
           ⛔ stretch 素材缺失时优雅降级：有 land_settle 就用它当"舒展"，
             都没有就先 walk 都不接，直接 idle（不会崩）。
        """
        if self._wake_stage == 0 and not self.asleep and \
                self.state not in ("sleep_in", "sleep_loop"):
            return False
        self.asleep = False
        self._sleep_t = 0.0
        self.last_wake_reason = reason
        self.goal = None
        self._wake_stage = 0
        self._sleep_need = random.uniform(*self.behaviour.sleep_after)
        if self._has("sleep_out"):
            self._wake_stage = 1
            self.play("sleep_out")
        else:
            self._wake_stage = 0
            self.play("idle")
            self.state_timer = random.uniform(*self.behaviour.idle_duration)
        return True

    def _after_sleep_out(self):
        """sleep_out 播完 → 决定要不要伸懒腰"""
        b = self.behaviour
        if self._has("stretch") and random.random() < b.stretch_chance:
            self._wake_stage = 2
            self.play("stretch")
            return
        if not self._has("stretch") and self._has("land_settle"):
            # ⭐ 兜底：还没有真正的伸懒腰素材时，用"落地收尾"当舒展动作
            self._wake_stage = 2
            self.play("land_settle")
            return
        self._wake_stage = 0
        self.play("idle")
        self.state_timer = random.uniform(*b.idle_duration)

    def _wake_from_cursor(self):
        """光标靠近就把她吵醒（⭐ 边沿触发：从半径外【进来】那一下才算）

        ⛔⛔ 2026-09-30 修（Ronny：「睡觉还是一键 sleep out 不是 sleep in」）
           旧写法是【电平触发】——只要睡着时光标在 wake_radius 内就唤醒。
           而"点枕头让她睡"这个操作，鼠标必然【正压在她身上】（距离 0px）：
             点枕头 → asleep=True → play(sleep_in) → 播完接 sleep_loop
             → 下一帧 _wake_from_cursor 发现光标距离 0 ≤ 120 → wake → play(sleep_out)
             → 玩家看到的就是"刚躺下又站起来"。
           ⭐ 实测（_dbg_枕头.py）：
             光标停在她身上 → sleep_in → **sleep_out** → idle   ⛔
             光标挪开 300px → sleep_in → sleep_loop            ✅

        ✅ 改为【边沿触发】：只有光标"从半径外进入半径内"的那一刻才唤醒。
           · 鼠标一直压着她（刚点完枕头）→ 不打扰，她安稳睡着
           · 鼠标移开再移回 → 正常叫醒
           · 点击 / 拖拽 仍照旧能叫醒（不走这条路径）
        """
        if self._cursor_x is None:
            return
        near = abs(self._cursor_x - self.body.x) <= self.behaviour.wake_radius
        # ⭐⭐ 无论睡没睡都要刷新"上一帧在不在附近"——
        #   ⛔ 旧写法在没睡时直接 return，导致睡着那一帧 was_near 还是陈旧值，
        #      光标若正压在她身上就会立刻被判成"刚从外面进来" → 又把她摇醒。
        was_near = self._cursor_near
        self._cursor_near = near
        if not self.asleep:
            return
        if near and not was_near:
            self.wake("cursor")

    # ---------- ⭐ v0.2：互动 ----------
    def on_click(self):
        """被点一下 —— 睡着时=叫醒（照样加好感、照样冒爱心）"""
        b = self.behaviour
        self.mood = min(b.mood_max, self.mood + b.mood_per_click)
        self._hearts.append([0.0])
        if len(self._hearts) > 6:
            self._hearts.pop(0)
        if self.asleep or self.state in ("sleep_in", "sleep_loop"):
            self.wake("click")          # ⭐ 睡着时点一下 = 叫醒，不播 pat
            return
        self._pat_t = b.pat_duration
        if "pat" in self.pack.actions:
            self.play("pat")
        self.goal = None               # 被摸时先不走动，专心享受
        self.state_timer = b.pat_duration

    def set_cursor(self, x: float):
        """UI 把光标位置喂进来（goal=seek 时用）"""
        self._cursor_x = x

    # ---------- ⭐ v0.2：目标导向 ----------
    def _pick_goal(self):
        """挑下一个目标：好感度高 → 可能主动走向光标；否则随便挑个地方"""
        b = self.behaviour
        sl, st, sr, sb = self.screen
        if (self._cursor_x is not None and self.mood >= b.seek_cursor_mood
                and random.random() < b.seek_chance):
            self.goal = "seek"
            self.goal_x = self._cursor_x
        else:
            self.goal = "goto"
            self.goal_x = random.uniform(float(sl) + 80.0, float(sr) - 80.0)

    def _goal_reached(self) -> bool:
        return abs(self.goal_x - self.body.x) <= self.behaviour.arrive_eps

    def _arrive(self):
        """到站：清目标 + 按当前状态接 turn_out / idle

        ⭐⭐ 2026-09-28：走到头停下的"侧身→正面"也必须走 turn_out。
           ⛔ 旧写法直接 play("idle")：她侧着身子走到目标点，一帧之内变成正面 =
              Ronny 看到的"转身动作也没有"的另一半。
        ⭐⭐ 2026-09-28 抽成方法：现在有【两个】入口会走到这里 ——
           ① update() 里 `_goal_reached()` 判定到达
           ② step() 里发现被墙挡住、目标永远够不到（见那里的注释）
           两处的收尾动作必须一致，所以合并成一个。
        """
        self.goal = None
        if self.state == "walk" and self._has("turn_out"):
            self.play("turn_out")     # 播完由 step() 接 idle + 重设 state_timer
        else:
            self.state_timer = random.uniform(*self.behaviour.idle_duration)
            self.play("idle")

    def _idle_pick(self):
        """待机 / 走路计时结束后，挑下一个动作

        ⛔ 修过一个真 bug：原来这里每次都 `facing_right = random()<0.5`，
           而 `play()` 在"已经在播同一个循环动作"时会**直接 return**，
           导致 `state_timer` 永远不被重置 → `_idle_pick()` **每帧重入** →
           **每帧随机翻向 = 左右闪烁**。
        ✅ 修法两条：
           ① **无论如何都重设 state_timer**（保证不会每帧重入）
           ② 只在【从非走路状态进入走路】时才考虑换向，且只以 `turn_chance` 的概率翻
        """
        b = self.behaviour
        if random.random() < b.walk_weight and "walk" in self.pack.actions:
            # ⭐ v0.2：不是原地走，而是"挑个地方走过去"
            self._pick_goal()
            # ⭐ 只在"从别的状态进入走路"时才决定朝向；走路中续期则保持原方向
            if self.state != "walk":
                if random.random() < b.turn_chance:
                    self.facing_right = not self.facing_right
            # ⭐⭐ 2026-09-28 转身接线（Ronny：转身动作也没有）
            #   走路素材原生朝右；turn_in 原生：正面(#0-#15) → 侧身朝右(#17)。
            #   起步方向与目标一致后播 turn_in，播完由 step() 接 walk。
            #   ⛔ 镜像规则（ui.paintEvent）：turn_in / walk 同用 facing_right ——
            #      朝右走 = 原生；朝左走 = 镜像 → 转身结束时面朝与 walk 起步一致，无硬切。
            if self.state != "walk" and self._has("turn_in"):
                if self.goal is not None:
                    self.facing_right = self.goal_x > self.body.x   # 转向 = 起步方向
                self.play("turn_in")
                return                                              # state_timer 由 turn_in 播完重设
            self.play("walk")
            self.state_timer = random.uniform(*b.walk_duration)   # ⭐ 必定重设
        else:
            # ⭐⭐ 2026-09-28 转身接线：走路结束 → 先转回正面（turn_out）再 idle
            #   turn_out 原生：侧身朝右(#0) → 正面(#11)；镜像规则与 walk 相同。
            #   ⛔ 目标还没走到、走路计时先到点 → 继续走完，【不能中途停下转身】
            #     （否则"转身回正面 0.96s → 又马上侧身继续走"，两截动作反复横跳）
            if self.state == "walk" and self.goal is not None:
                self.play("walk")
                self.state_timer = random.uniform(*b.walk_duration)
                return
            if self.state == "walk" and self._has("turn_out"):
                self.play("turn_out")
                return                                             # 播完由 step() 接 idle
            self.play("idle")
            self.state_timer = random.uniform(*b.idle_duration)   # ⭐ 必定重设

    # ---------- 物理 ----------
    def update(self, dt: float):
        b = self.behaviour
        if self.dragging:
            self._update_drag_tilt()
            return

        # 重力
        if not self.body.on_ground:
            self.body.vy += b.gravity * dt
            self.body.y += self.body.vy * dt

        # ⭐⭐ v0.2：好感度自然衰减 + 爱心飘动计时（睡着时掉得慢 → "睡得香"）
        self.mood = max(0.0, self.mood - b.mood_decay * dt
                        * (b.sleep_mood_decay_scale if self.asleep else 1.0))
        for h in self._hearts:
            h[0] += dt
        self._hearts = [h for h in self._hearts if h[0] < 1.1]

        # ⭐⭐ 睡眠：连续"清醒待机"累计到阈值 → 睡着；光标靠近 → 叫醒
        if not self.dragging:
            if self._wake_stage > 0:
                self._sleep_t = 0.0                     # 正在起床，别记入睡眠计时
            elif self.asleep or self.state in ("sleep_in", "sleep_loop"):
                self._sleep_t = 0.0
            elif self.state in ("idle", "walk"):
                self._sleep_t += dt
                if self._sleep_t >= self._sleep_need:
                    self.fall_asleep()
            else:
                self._sleep_t = 0.0                     # 被摸/下落/落地 → 重置
            self._wake_from_cursor()

        # ⭐ v0.2：目标导向 —— 有目标就朝它走，到了就停
        #  ⭐ 只在【脚沾地 + 不在下落/落地中】才允许目标驱动走路
        #    ⛔ 否则松手后会立刻从 fall 切回 walk（"拿起来触发不了 fall"的根因）
        #    ⛔ 2026-09-28：还要排除 turn_in/turn_out —— 否则转身动画每帧被 play("walk") 顶掉，
        #       "转身"永远播不完（等于没接）
        if (self.goal in ("goto", "seek") and self._pat_t <= 0
                and self.body.on_ground and self.state not in ("fall", "land", "turn_in", "turn_out")
                and not self.asleep and self._wake_stage == 0):
            if self.goal == "seek" and self._cursor_x is not None:
                self.goal_x = self._cursor_x
            if self._goal_reached():
                self._arrive()
            else:
                self.facing_right = self.goal_x > self.body.x
                if self.state != "walk":
                    self.play("walk")

        # 被摸计时
        if self._pat_t > 0:
            self._pat_t -= dt
            if self._pat_t <= 0 and self.state == "pat":
                self.play("idle")
                self.state_timer = random.uniform(*b.idle_duration)

        # 走路位移：⭐ 由 stride_px 推出的每帧位移 × 该帧播放速度
        if self.state == "walk":
            act = self.pack.actions["walk"]
            # ⭐⭐ 2026-09-29 Ronny：追激光红点时移速暴增至 laser_speed_mul 倍
            #   （露娜 = 2.5。她看到红点会兴奋地扑过去，不是平常散步的速度）
            #   ⛔ 只对 seek（追红点）生效，普通漫游 goto 不受影响。
            _mul = b.laser_speed_mul if self.goal == "seek" else 1.0
            spd = act.move_per_frame * act.fps * b.walk_speed * _mul   # px/s
            tgt = spd * (1.0 if self.facing_right else -1.0)
            # ⭐⭐ 掉头缓动：换向时速度平滑过零（减速 → 微顿 → 反向加速）
            #    不做这一步的话，facing_right 一翻，人物一帧之内就掉头往回走 = 一顿 = 左右闪烁
            self._walk_v += (tgt - self._walk_v) * min(1.0, dt / max(b.turn_ease_tau, 1e-4))
            self.body.x += self._walk_v * dt
        else:
            self._walk_v = 0.0

        # ⭐ 松手后：驱动力归零，让单摆自己被重力拉回（会晃几下再停）
        self._force_f += (0.0 - self._force_f) * min(1.0, dt / max(b.tilt_force_tau, 1e-4))
        self._tilt_pendulum(dt, self._force_f)

    def _tilt_pendulum(self, dt: float, force: float):
        """⭐⭐ 受驱动的阻尼单摆 —— 这才是"有重量"的正确物理

            θ'' = −ω₀²·sin θ   （重力把角色拉回竖直）
                  − 2ζω₀·θ'    （阻尼：晃几下会停）
                  + F            （鼠标速度 = 力；且 F 自身带惯性）

        ⭐ 为什么"快甩才冲到 45°"是物理必然，不是调出来的：
           这是个**欠阻尼**（ζ<1）系统，快速施力会产生 **overshoot（过冲）** ——
           慢慢移动 → 力小 → 只轻倾；快速甩 → 力大 + 惯性过冲 → 冲到接近上限。
        ⭐ 而"惯性加大"= 降低 ω₀ 与 ζ → 摆得慢、晃过头、停得晚 → 读起来就是"重"。
        """
        b = self.behaviour
        th = math.radians(self._theta)
        acc = (-b.tilt_omega0 ** 2 * math.sin(th) * (180.0 / math.pi)
               - 2.0 * b.tilt_zeta * b.tilt_omega0 * self._omega
               + force)
        self._omega += acc * dt
        self._theta += self._omega * dt
        self._theta = max(-b.drag_tilt_max, min(b.drag_tilt_max, self._theta))
        self.body.tilt = self._theta

    def _update_drag_tilt(self):
        """拖拽中：用【鼠标速度】作为驱动力"""
        dt = max(getattr(self, "_last_dt", 1 / 60), 1e-4)
        b = self.behaviour
        # 鼠标速度（低通，滤掉抖动）
        vx = (self.body.x - self._tilt_x) / dt
        self._tilt_x = self.body.x
        self._tilt_vx_f += (vx - self._tilt_vx_f) * min(1.0, dt / max(b.tilt_v_tau, 1e-4))
        v_norm = min(abs(self._tilt_vx_f) / max(b.tilt_vref, 1e-6), 1.6)
        # ⭐ 指数曲线：v_norm^exp —— 慢慢移动几乎不出力，快速甩才猛涨
        raw = math.copysign(b.tilt_drive * (v_norm ** max(b.tilt_drive_exp, 1e-3)), self._tilt_vx_f)
        # ⭐⭐ 力本身也要有惯性：换向时"手"不能瞬移，要慢慢把力扳过去
        self._force_f += (raw - self._force_f) * min(1.0, dt / max(b.tilt_force_tau, 1e-4))
        self._tilt_pendulum(dt, self._force_f)

    def step(self, dt: float, silhouette: Tuple[int, int, int, int]):
        """推进一帧：动画 + 物理 + 边界"""
        self._last_dt = dt          # ⭐ 倾斜的滞后要用真实 dt
        if self.anim:
            self.anim.advance(dt)
            if self.anim.finished:
                # 一次性动作播完 → 按状态决定接什么
                if self.state == "fall":
                    self.play("land")
                elif self.state == "drag_in":
                    # ⭐⭐ 2026-09-29「拿起过渡」播完 → 接悬挂循环（drag）
                    #   素材：drag_in 末帧 = drag 首帧（同一源帧，实测 XOR 0.00%）→ 零缝
                    self.play("drag")
                elif self.state == "drag_out":
                    # ⭐⭐ 2026-09-29「松手过渡」播完 → 接下落（fall）
                    #   素材：drag_out 末帧宽 333 ≈ fall_0 的 326（差 7px）。
                    #   没有这段时 drag(227) 直接跳 fall(324)，宽度落差 43%，松手瞬间整只撑开。
                    self.play("fall")
                elif self.state == "sleep_in":
                    # ⭐ 睡下 → 接睡眠循环
                    self.play("sleep_loop" if self._has("sleep_loop") else "idle")
                elif self.state == "sleep_out":
                    # ⭐⭐ 起床后接"伸懒腰"（没有素材就降级）
                    self._after_sleep_out()
                elif self.state == "tease":
                    # ⭐⭐ 2026-09-29 逗猫/激光笔：跳起来抓完 → 回站姿
                    #   ⛔ tease 若是 cycle 会永远循环、她一直扑 → 改成 once（pet.json）。
                    #   ⭐ 回 idle 后激光笔的 _laser_tick 会重新给目标 → 继续追。
                    self.play("idle")
                    self.state_timer = random.uniform(*self.behaviour.idle_duration)
                elif self.state == "turn_in":
                    # ⭐⭐ 2026-09-28 转身接线：正面 → 侧身（朝向已定），现在起步走
                    #   （state_timer 在这里才重设，turn_in 的时长不占 walk_duration）
                    self.play("walk")
                    self.state_timer = random.uniform(*self.behaviour.walk_duration)
                elif self.state == "turn_out":
                    # ⭐⭐ 转身接线：侧身 → 正面，收工回 idle
                    self.play("idle")
                    self.state_timer = random.uniform(*self.behaviour.idle_duration)
                elif self.state in ("stretch", "land_settle") and self._wake_stage == 2:
                    self._wake_stage = 0
                    self.play("idle")
                    self.state_timer = random.uniform(*self.behaviour.idle_duration)
                else:
                    self.state_timer = random.uniform(*self.behaviour.idle_duration)
                    self.play("idle")
        self.update(dt)
        _x_before = self.body.x
        self.body.clamp_to_screen(self.screen, silhouette, self.behaviour.screen_margin)

        # ⭐⭐ 2026-09-28：够不到的目标要主动作废（否则"贴着墙原地走"）
        #   根因：`_pick_goal` 挑目标写死 ±80px 边距，但角色的**真实轮廓**左右能占
        #        174/151px（walk），所以目标落进 [sl+80, sl+174) 这一带时她永远走不到 ——
        #        `_goal_reached()` 判 `|goal_x - body.x| <= arrive_eps`，被墙挡住就永远为假。
        #   ⛔ 09-28 加了"有目标就不许停（不许中途转身）"之后，这里从"能自愈"
        #      （原来走完计时会回 idle、重挑目标）变成"不自愈"：
        #      实测她会贴着墙原地走，直到 40~90 秒后按睡眠计时睡着才解脱。
        #      `_自测_转身接线.py` ⑩ 就是这么挂的（那次还把睡眠关了，于是永久卡住）。
        #   ✅ 判据：本帧被 clamp 挪动了，且目标还在被挡住的那一侧 → 认作"到站"，
        #      走 `_arrive()`（清目标 + turn_out → idle）。
        #      ⭐ 用"被挡住"而不是"预测可达范围"：不必知道各动作轮廓，
        #        对 seek（光标在屏外）这类目标同样成立。
        if self.goal is not None and self.state == "walk" and self.body.x != _x_before:
            blocked_left = self.body.x > _x_before and self.goal_x < self.body.x
            blocked_right = self.body.x < _x_before and self.goal_x > self.body.x
            if blocked_left or blocked_right:
                self._arrive()

        # 走路/待机计时切换
        if self.state in ("idle", "walk"):
            self.state_timer -= dt
            if self.state_timer <= 0:
                # ⭐⭐ 2026-09-29：激光笔在手（goal=="seek"）时**不许挑漫游目标** ——
                #   ⛔ 否则 _idle_pick() → _pick_goal() 会把 seek 目标顶成随机点，
                #      她掉头走反方向（实测 goal_x 2200 → 83）。
                #   ✅ seek 期间只续期计时，方向永远由 _laser_tick 每帧重设。
                if self.goal == "seek":
                    self.state_timer = random.uniform(*self.behaviour.walk_duration)
                else:
                    self._idle_pick()

    # ---------- 拖拽 ----------
    def begin_drag(self, mx: float, my: float):
        # ⭐ 被拎起来 → 之前那个"要走过去的目标"作废
        #   （⛔ 不清的话，松手后目标还在，update() 会立刻 play("walk") 把 fall 顶掉）
        self.goal = None
        self.dragging = True
        # ⭐ 被拎起来 → 睡眠状态与计时全部作废
        self.asleep = False
        self._sleep_t = 0.0
        self._wake_stage = 0
        self._sleep_need = random.uniform(*self.behaviour.sleep_after)
        self.body.vx = 0.0
        self.body.vy = 0.0
        self._drag_hist = []
        self._tilt_x = self.body.x
        self._tilt_vx = 0.0
        self._tilt_vx_f = 0.0
        self._tilt_ax_f = 0.0
        # ⭐⭐ 2026-09-29：先播「被拿起」的过渡（drag_in，once 1 秒），再进悬挂循环（drag）。
        #    旧写法直接 play("drag")，从待机站姿瞬间切成悬挂，Ronny 实机反馈「拿起之前没有动画」。
        #    过渡素材一直躺在源视频里（站立→收拢段），此前装机只取了后半段悬挂。
        self.play("drag_in" if self._has("drag_in") else "drag")
        self._tilt_x = self.body.x      # ⭐ 补偿后重设，避免第一帧算出虚假鼠标速度

    def move_drag(self, mx: float, my: float):
        self.body.x, self.body.y = mx, my
        self._update_drag_tilt()

    def end_drag(self):
        self.dragging = False
        self.body.on_ground = False
        # ⭐⭐ 2026-09-29：松手先播「展开下落」过渡（drag_out，once 0.67s），再进 fall。
        #    旧写法直接 play("fall")，从收拢悬挂(宽227)瞬间撑成舒展下落(宽324)，
        #    Ronny 实机反馈「和 fall 衔接不连贯」。
        self.play("drag_out" if self._has("drag_out") else "fall")

    def current_frame_path(self):
        if not self.anim:
            return None
        idx = self.anim.seq[self.anim.i]
        return self.pack.frame_path(self.anim.act.name, idx)
