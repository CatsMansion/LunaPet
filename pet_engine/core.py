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
    # ⭐⭐ 2026-10-01 Ronny：「run 的移速为 **walk 的 5 倍**」
    run_speed_mul: float = 5.0
    # ⭐⭐ 睡眠（2026-09-26）：连续待机多久睡着 → 睡着 → 叫醒 → 伸懒腰
    sleep_after: Tuple[float, float] = (40.0, 90.0)   # 连续无互动多久入睡（秒，随机区间）
    sleep_mood_decay_scale: float = 0.2               # 睡着时好感度衰减倍率（睡得香，掉得慢）
    wake_radius: float = 120.0                        # 光标靠近多少 px 会把她吵醒
    stretch_chance: float = 0.6                       # 醒来后做伸懒腰的概率
    sleep_wakeup_need: float = 1.0                    # 摇几下才醒（拖拽时）——预留


# ⭐ 地形边缘余量：脚底中点可以越出平台边这么多 px，才判"没有支撑"
#   取值 ≈ idle 的横向半宽（实测 右轮廓 +112 / 左 −79）→ 让她"整个人基本离开平台"才掉。
#   ⛔ 不要用当前动作的轮廓：那个每帧随动作变（fall ≠ idle），边缘阈值会抖。
#   ⭐ 可在 pet.json 的每个地形项里用 `edge_tol` 单独覆盖。
TERRAIN_EDGE_TOL = 200.0


def _resolve_terrain(t: dict, screen: Tuple[int, int, int, int]) -> dict:
    """把地形配置解析成**绝对屏幕坐标**。

    ⭐ 三种写法：
         x0:-420  → sr - 420        （负值 = 从右 / 下边往里量，自适应屏幕尺寸）
         x0: 100  → sl + 100        （正值 = 从左上角往外量）
         x1:"right" / y1:"bottom"   （⭐ 保留字 = 直接贴到那条边）
    """
    sl, st, sr, sb = screen
    EDGE = {"left": sl, "right": sr, "top": st, "bottom": sb}

    def v(key, pos_base, neg_base):
        raw = t[key]
        if isinstance(raw, str):
            return float(EDGE.get(raw.lower(),
                                  {"x0": sl, "x1": sr, "y0": st, "y1": sb}[key]))
        raw = float(raw)
        return neg_base + raw if raw < 0 else pos_base + raw

    return {"x0": v("x0", sl, sr), "y0": v("y0", st, sb),
            "x1": v("x1", sl, sr), "y1": v("y1", st, sb),
            # ⭐ 边缘余量：没配就用全局默认（⛔ 显式带过来，否则被这里丢掉）
            "edge_tol": float(t.get("edge_tol") or TERRAIN_EDGE_TOL),
            "label": t.get("label", "猫爬架")}


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
    # ⭐⭐ 2026-10-01「地形」：可站立的平台列表，每项 {'x0','y0','x1','y1'}（屏幕坐标，y0=平台顶）。
    #   来自 pet.json 的 `terrain`。⛔ 为空 = 只有屏幕底可站（旧的默认行为，向后兼容）。
    terrains: Optional[list] = None

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
        run_speed_mul=float(b.get("run_speed_mul", 5.0)),
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
                   display_scale=float(d.get("display_scale", 1.0)),
                   terrains=list(d["terrain"]) if d.get("terrain") else None)


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
                        silhouette: Tuple[int, int, int, int], margin: int = 0,
                        ground_y: Optional[float] = None):
        """⭐ 按【角色实际轮廓】限位（不是按窗口中心 —— 那是 DyberPet 的坑）

        screen      = (left, top, right, bottom) 桌面可用区
        silhouette  = (dx_left, dx_right, dy_top, dy_bottom)
                      角色轮廓相对"脚底中点"的四向偏移
        ground_y    = ⭐⭐ 本帧"她脚下的地面高度"（屏幕 y）。
                      ⛔ 默认 None = 屏幕底。
                      ✅ 传了就是【地形】：站在猫爬架平台上时，地面是平台顶而不是屏幕底。
                        这是 2026-10-01 新增的「地形」机制的落地接口 —— 见 `Pet.ground_at()`。
        """
        sl, st, sr, sb = screen
        dl, dr, dtp, dbt = silhouette
        # 左：脚底 x + dl 不能小于 sl
        self.x = max(self.x, float(sl - dl + margin))
        # 右：脚底 x + dr 不能大于 sr
        self.x = min(self.x, float(sr - dr - margin))
        # 下：脚底 y 不能超过【地面】（默认屏幕底；有地形时是平台顶）
        floor = float(sb) if ground_y is None else float(ground_y)
        bottom_limit = float(floor - dbt)
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
        # ⭐⭐⭐ 2026-10-01「地形」—— Ronny：「猫爬架**就是个地形**，默认在屏幕右端，
        #   最好可以让玩家进行自定义」。每项 {'x0','y0','x1','y1'}（屏幕坐标，y0 = 平台顶）。
        #   ⛔ P0 只做"可站立的矩形平台"：她走进平台范围就站到平台顶，走出去就自由落体。
        #   ⭐ pet.json 里可以写**负值**表示"从右/下边算"（如 x0:-420 = 右边距 420），
        #      这样换显示器/改分辨率不用重配。
        self.terrains: List[dict] = []
        for _t in (getattr(pack, "terrains", None) or []):
            try:
                self.terrains.append(_resolve_terrain(_t, screen))
            except (KeyError, TypeError, ValueError) as _e:
                print(f"[地形] ⛔ 跳过一条无效配置：{_t}（{_e}）")
        self.anim: Optional[Anim] = None
        self._sil: Optional[Tuple[int, int, int, int]] = None   # ⭐ 本帧轮廓缓存（地形判定用）
        self.jumping: bool = False                              # ⭐ 引擎驱动的抛物线跳进行中
        self.excited: bool = False                              # ⭐ 兴奋模式（激光等）→ 移动用 run
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
        _loc = self._loco_act()
        if random.random() < b.walk_weight and _loc in self.pack.actions:
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
            self.play_walk()
            self.state_timer = random.uniform(*b.walk_duration)   # ⭐ 必定重设
        else:
            # ⭐⭐ 2026-09-28 转身接线：走路结束 → 先转回正面（turn_out）再 idle
            #   turn_out 原生：侧身朝右(#0) → 正面(#11)；镜像规则与 walk 相同。
            #   ⛔ 目标还没走到、走路计时先到点 → 继续走完，【不能中途停下转身】
            #     （否则"转身回正面 0.96s → 又马上侧身继续走"，两截动作反复横跳）
            if self.state == "walk" and self.goal is not None:
                self.play_walk()
                self.state_timer = random.uniform(*b.walk_duration)
                return
            if self.state == "walk" and self._has("turn_out"):
                self.play("turn_out")
                return                                             # 播完由 step() 接 idle
            self.play("idle")
            self.state_timer = random.uniform(*b.idle_duration)   # ⭐ 必定重设

    # ---------- ⭐⭐ 地形（2026-10-01）----------
    def ground_at(self, x: float, y: Optional[float] = None) -> float:
        """本帧"她脚下的地面高度"（屏幕 y）。

        ⭐ 默认 = 屏幕底；站在地形平台范围内时 = 平台顶。
        ⛔ 取**最高的**那个平台顶（min y），叠放平台也能正确处理。

        ⭐⭐ 2026-10-01 关键修正（Ronny：「等她溜达到屏幕右边 → **会瞬移到平台上**」）：
            ⛔ 旧版只看 x：「走进平台范围就吸附到平台顶」→ 她从平台✔侧面走过去时
               **瞬间被弹到平台顶**，像瞬移。
            ✅ 现在要**同时满足**：x 在范围内 **且** 脚底已经在平台顶附近（不低太多）。
               她在平台**下方**时，平台不当她的地面 → 她会撞在平台侧面上（而不是被弹上去），
               改由 `_terrain_climb()` 触发**攀爬**。
        """
        g = float(self.screen[3])
        if y is None:
            y = self.body.y
        # ⭐ 她的横向占位。⛔ 不用当前动作的轮廓（每帧随动作变 → 边缘阈值抖，
        #   实测在 fall/idle 切换处 `on_ground` 来回抖了两帧）→ 用固定容差。
        for t in self.terrains:
            try:
                x0, top, x1 = float(t["x0"]), float(t["y0"]), float(t["x1"])
                tol = float(t.get("edge_tol", TERRAIN_EDGE_TOL))
            except (KeyError, TypeError, ValueError):
                continue
            # ⭐⭐ 2026-10-01 修（Ronny：「我的意思是**还没到边缘**就开始播 fall 了」）：
            #   ⛔ 旧判据只用"脚底中点" —— 她**中点在边缘上**（身体大半还在平台上、
            #      右脚离边缘还有 200 多 px）就开始掉，看起来就是"没到边缘就掉了"。
            #   ✅ 往外留 `edge_tol` 的余量：**整个人基本离开平台**才判悬空。
            #      ⭐ 这个值可在 pet.json 里按地形单独调（`edge_tol`），不用改代码。
            if x + tol < x0 or x - tol > x1:
                continue
            # ⭐ 只有脚底"已经到平台顶附近或更高"时，平台才算她的地面（容差 4px）
            if y <= top + 4.0:
                g = min(g, top)
        return g

    # ---------- ⭐⭐ 地形攀爬（2026-10-01）----------
    def _terrain_climb(self, dt: float):
        """撞到地形侧面 → 往上爬。

        ⭐ Ronny：「我想要**往上爬**的动作」（对应 P0 的"瞬移到平台上"）
        ⛔ 素材 `climb` 还没装机时：她停在平台边缘**不动**（不是被弹上去），
           等素材到位后自动走这条路径 —— 不需要再改代码。
        """
        if self.dragging or not self.body.on_ground:
            return False
        if self.state in ("climb", "fall", "land", "land_settle",
                          "drag", "drag_in", "drag_out"):
            return False
        for t in self.terrains:
            try:
                x0, top, x1 = float(t["x0"]), float(t["y0"]), float(t["x1"])
            except (KeyError, TypeError, ValueError):
                continue
            # 她的水平位置已经进入平台范围，但脚底还在平台顶下方 → 该爬
            if x0 <= self.body.x <= x1 and self.body.y > top + 4.0:
                # ⭐⭐ 只有 climb 素材**真的装机了**才启用爬升。
                #   ⛔ 没有素材时**什么都不做** —— 不要在这里 play("idle") 或清 goal：
                #      那样会每帧打断她的状态机（实测：她会被永久卡住不动，
                #      因为地形窗口在她上方、看起来只是"被挡住"，是 P0 可接受的表现）。
                #      （`_自测_互动.py` 就因此从 11/11 掉到 9/11）
                if not self._has("climb"):
                    return False
                # ⭐⭐ 2026-10-01 Ronny：「爬墙**不一定非要爬到顶**，可以爬到
                #   **头和小红点一样高**的时候跳」→ 爬升终点不再恒为平台顶：
                #     取「平台顶 top」与「让**头顶**与红点等高的位置」中**较低的**那个
                #     （屏幕 y 越大越低）—— 即 max(top, head_stop)。
                #     · 不能爬过平台顶（上面没东西可抓）→ 以 top 为上限
                #     · 红点在她头顶之上时，爬到"头顶刚好与红点齐平"即可起跳
                #   ⛔ 只在兴奋态（激光）下这么做；普通爬平台仍爬到顶。
                #   ⛔ 若红点**不在她头顶之上**（_head_stop 不低于她现在的高度）→ 不据此提前停，
                #      仍按平台顶爬（否则 climb_speed 会退化成原地爬）。
                _stop = top
                _dy = getattr(self, "_laser_pos_y", None)     # ⭐ 由 ui 的激光驱动每帧写入
                if self.excited and _dy is not None:
                    _sil = self._sil or (0, 0, -1, 0)
                    _head_stop = float(_dy) + abs(float(_sil[2]))   # 头顶与红点等高时 body.y 应到哪
                    if _head_stop < self.body.y - 4.0:
                        _stop = max(top, _head_stop)
                self.goal = None
                self.play("climb")
                self._climb_top = _stop
                self.climb_speed = max(60.0, (self.body.y - _stop) / 1.33)   # ⭐ 与素材节奏对齐（16 帧 @12fps）
                return True
        return False

    # ---------- ⭐⭐ 抛物线跳跃（2026-10-01）----------
    def jump_to(self, height: float, dx: float = 0.0) -> bool:
        """往上跳 height 像素、同时水平移动 dx 像素，按**二次函数轨迹**落下来。

        ⭐⭐ Ronny 2026-10-01：「我要的跳是那种**往上几百像素的位移**，
           然后保持**二次函数的轨迹 fall 下来**」
        ⭐ 追加：「高度**不要固定**，要去追鼠标，而且最好能进行**大约 150px 的斜向位移**」

        ⭐ 物理上就是这么简单：给一个向上的初速度 v0 = √(2gh) + 一个水平速度 vx，
           而 `update()` 里本来就有重力（`vy += g·dt` + `y += vy·dt`）——
           两者合起来**天然就是抛物线**，不需要任何额外插值。

        ⛔ 素材只管**姿势**（蹲/起跳/空中/落地），**整体位移由这里控** ——
           这是项目铁律（Ronny：「净上升为 0 就是我们要的，位置由引擎控」）。
        """
        if not self.body.on_ground or self.dragging:
            return False
        h = max(0.0, float(height))
        if h <= 1.0:
            return False
        self.body.vy = -math.sqrt(2.0 * self.behaviour.gravity * h)
        # ⭐ 水平速度：让 dx 在**飞行时间内**均匀走完（飞行时间由高度决定）
        t_flight = 2.0 * math.sqrt(2.0 * h / self.behaviour.gravity)
        self.body.vx = (float(dx) / t_flight) if t_flight > 1e-6 else 0.0
        self.body.on_ground = False
        self.jumping = True          # ⭐ 跳跃期间跳过"支撑检查"（否则会被判悬空、播 fall）
        # ⭐⭐ Ronny 2026-10-01：「只播放**上半程和刚落下的 1/2**，落下的**最后 1/2 程用 fall**」
        #   → 记下飞行总时长和已飞时间，按**进度**在 75% 处把动画切成 fall。
        self._jump_total = self.jump_flight_time(h)
        self._jump_t = 0.0
        self._jump_switched = False
        return True

    def _jumping(self) -> bool:
        """是否处于引擎驱动的跳跃中"""
        return bool(getattr(self, "jumping", False))

    def jump_flight_time(self, height: float) -> float:
        """跳 height 高再落回原高度所用的时间（用来配素材时长/fps）"""
        h = max(0.0, float(height))
        if h <= 1.0:
            return 0.0
        return 2.0 * math.sqrt(2.0 * h / self.behaviour.gravity)

    # ---------- ⭐⭐ 兴奋模式 / 移动动作选择（2026-10-01）----------
    def _loco_act(self) -> str:
        """当前"移动"该用哪个**素材**：兴奋态且有 `human_run` 素材时用它，否则 `walk`。

        ⭐ Ronny 2026-10-01：「新增**兴奋模式**，在激光模式下**不再 walk 改为 run**」
        ⭐ 同日更正：「（四足版）有点像**猩猩**，先不要启用，把这个动作记为**猩猩跑**」
           → 等真正的**人类跑**（`human_run`）到位再启用。
        ⛔ 状态名仍然是 `walk`（状态机只认 walk）—— 变的只是**播哪个素材**，
           这样 turn_in / turn_out 的接力、走路计时、速度缓动全都不用动。
        """
        if getattr(self, "excited", False) and "human_run" in self.pack.actions:
            return "human_run"
        return "walk"

    def play_walk(self):
        """播当前的移动素材（walk 或 run），但**状态名固定回 `walk`**"""
        name = self._loco_act()
        self.play(name)
        self.state = "walk"

    def set_excited(self, on: bool):
        """兴奋模式开关（激光等刺激场景）。⭐ 关掉时如果正在跑，立刻换回走路素材。"""
        self.excited = bool(on)
        if not self.excited and self.anim and self.anim.act.name == "run":
            self.play_walk()

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
            # ⭐⭐ 2026-10-01：空中也走水平速度 —— 抛物线跳要能"斜着跳"过去
            #   （Ronny：「最好能进行大约 150px 的斜向位移」）
            if abs(self.body.vx) > 0.01:
                self.body.x += self.body.vx * dt

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
                    self.play_walk()

        # 被摸计时
        if self._pat_t > 0:
            self._pat_t -= dt
            if self._pat_t <= 0 and self.state == "pat":
                self.play("idle")
                self.state_timer = random.uniform(*b.idle_duration)

        # 走路位移：⭐ 由 stride_px 推出的每帧位移 × 该帧播放速度
        if self.state == "walk" and self.anim:
            # ⭐⭐ 2026-10-01：速度按**实际在播的素材**算（兴奋态播的是 human_run）
            _lname = self.anim.act.name if self.anim.act.name in ("walk", "human_run") else "walk"
            act = self.pack.actions[_lname]
            if _lname == "human_run":
                # ⭐ Ronny：「run 的移速为 **walk 的 5 倍**」
                _mul = b.run_speed_mul
            else:
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
        # ⭐⭐ 2026-10-01：缓存本帧轮廓 —— `ground_at()` 要用它算"她整个人还在不在平台上"
        #   （轮廓是屏幕像素口径，与 body.x/y 同一坐标系）
        self._sil = silhouette
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
                    self.play_walk()
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
        self.body.clamp_to_screen(self.screen, silhouette, self.behaviour.screen_margin,
                                  ground_y=self.ground_at(self.body.x))

        # ⭐⭐⭐ 2026-10-01 地形攀爬（Ronny：「我想要**往上爬**的动作」）
        #   ⛔ 旧版是"走进平台范围 → 瞬间吸附到平台顶" = 瞬移
        #   ✅ 现在：撞到平台侧面 → 播 climb，逐帧把 body.y 抬到平台顶 → 站定
        #   ⛔ climb 素材没装机时：停在边缘不动（不弹上去），素材到位自动生效
        if self.state == "climb":
            # ⛔⛔ 爬墙时**不能有重力**：她在贴墙爬，不是自由落体。
            #   实测漏了这条时，重力每帧把她往下拽，和爬升速度对抗 →
            #   她在 2128~2152 之间来回晃、永远爬不上去。
            self.body.vy = 0.0
            self.body.on_ground = True
            _top = getattr(self, "_climb_top", None)
            _spd = getattr(self, "climb_speed", 300.0)
            self.body.y -= _spd * dt
            if _top is not None and self.body.y <= float(_top):
                self.body.y = float(_top)
                self.body.on_ground = True
                # ⭐⭐ 2026-10-01 Ronny：「在高处玩激光会在爬行和跳之间穿插 idle，
                #   ⛔ 不要穿插 idle，**直接爬完就跳**」
                #   → 兴奋态（激光等）下：爬到顶立刻起跳；否则才回 idle。
                if getattr(self, "excited", False):
                    self.play("jump_excited" if "jump_excited" in self.pack.actions
                              else "jump" if "jump" in self.pack.actions else "idle")
                    # ⭐⭐ Ronny：「先爬墙**再朝着小红点跳**」→ 跳跃的水平方向朝红点
                    #   （`_laser_pos_x` 由 ui 的激光驱动每帧写入；没有就朝她当时面向）
                    _lx = getattr(self, "_laser_pos_x", None)
                    _dx = 0.0
                    if _lx is not None:
                        # ⭐⭐ 2026-10-01 Ronny：横向起跳抓红点的距离 150 → **800**
                        #   （同 ui 的"够近就抓"那处；爬完起跳也是"朝红点扑"，口径要一致）
                        _dx = max(-800.0, min(800.0, float(_lx) - self.body.x))
                    # 跳的高度用**头顶**对目标（同激光接线：顶端去够，不是脚底）
                    self.jump_to(float(getattr(self, "_climb_jump_h", 220.0)), _dx)
                else:
                    self.play("idle")
                    self.state_timer = random.uniform(*self.behaviour.idle_duration)
        else:
            self._terrain_climb(dt)

        # ⭐⭐ 2026-10-01 抛物线跳的「动画时序」（Ronny：「只播放**上半程和刚落下的 1/2**，
        #   落下的**最后 1/2 程用 fall**」）
        #   → 按**飞行进度**切：前 75%（上升 + 下落前半）用 jump 素材，
        #     超过 75% 就换成 fall 的下落姿势。抛物线本身不受影响，只换姿势。
        if self.jumping:
            self._jump_t = getattr(self, "_jump_t", 0.0) + dt
            _tot = getattr(self, "_jump_total", 0.0)
            if (not getattr(self, "_jump_switched", False) and _tot > 0
                    and self._jump_t >= _tot * 0.75):
                # 下落后半程 → 换成下落姿势
                if self._has("fall") and self.state != "fall":
                    self.play("fall")
                self._jump_switched = True
            elif (not getattr(self, "_jump_switched", False) and self.anim
                  and self.anim.act.name in ("jump", "jump_excited")):
                # ⭐⭐ Ronny 2026-10-01：「起跳动画本身循环可以，就是**加速播放塞进前面的时间里**」
                #   → 不用素材自己的 fps，改成**按飞行进度映射帧号**：
                #     进度 0~75% 正好把素材从头到尾跑一遍（= 加速）。
                n = len(self.anim.seq)
                if n > 1 and _tot > 0:
                    prog = min(0.9999, max(0.0, self._jump_t / (_tot * 0.75)))
                    self.anim.i = int(prog * n)
                    # ⛔⛔ 必须同时清掉 finished —— `advance()` 可能已经把帧号推到末尾并
                    #   置 finished=True，下一帧 `step()` 的"播完分支"就会**插一个 idle 进来**
                    #   （实测：跳跃中空中播 idle 两帧，看起来就是"在空中走路"）。
                    self.anim.finished = False
            if self.body.on_ground:          # 落地 → 跳跃结束
                self.jumping = False
                self._jump_switched = False
                self.body.vx = 0.0           # ⭐ 水平速度也清零，别让她落地后继续滑

        # ⭐⭐⭐ 2026-10-01 地形的「支撑检查」（⛔ 爬墙期间跳过：那时候"有没有地面"
        #   不适用，她在墙上；跑这段会把她判成悬空 → 启动重力 → 爬升被拽回去）
        #   ⛔ 原来 `on_ground` 只在【落地】那一刻被设 True（clamp_to_screen 里），
        #      而**没有任何地方在"脚下没有支撑"时把它设回 False** ——
        #      于是她走出地形平台边缘后，人悬在半空、也不下落。
        #      （Ronny 实测：「如果她站在平台上，左右走会悬空，没有往下位移的动作」）
        #   ✅ 每帧问一次"脚下那块地面还在不在"：
        #        脚底【高于】地面 → 悬空 → 交给重力，并接 fall 动作（他说"其实下落就能用"）
        #        否则 → 踩实
        #   ⛔ 拖拽中不判（那时候她的高度由鼠标决定，`end_drag` 已经设过 on_ground=False）
        if not self.dragging and self.state != "climb" and not self._jumping():
            if self.body.y < self.ground_at(self.body.x) - 0.5:
                # ⭐⭐ 物理状态**无条件**更新（下落的物理前提）。
                #   ⛔ 上一版把 "jump"/"jump_excited" 塞进下面的"排除列表"，
                #      结果整段不执行 —— 连 `on_ground = False` 都没设，
                #      她站在平台边缘外**不下落**（实测 y 恒定不变）。
                #   ✅ 拆开：物理照常，"播什么姿势"单独判。
                if self.body.on_ground:
                    self.body.on_ground = False
                    self.body.vy = 0.0
                # ── 播什么姿势 ──
                if (self.state not in ("fall", "land", "land_settle", "climb",
                                       "drag", "drag_in", "drag_out",
                                       "jump", "jump_excited")
                        and getattr(self, "_fall_delay", 0.0) <= 0.0):
                    # ⭐⭐ 2026-10-01 Ronny：「从高处下来**只 fall 改为先跳再 fall**」
                    #   落差够大（比如从地形平台顶掉下来）→ 先播起跳姿势一小段，
                    #   再由下面的 `_fall_delay` 切到 fall。
                    _drop = self.ground_at(self.body.x) - self.body.y
                    if _drop > 60.0 and self._has("jump"):
                        self.play("jump")
                        self._fall_delay = 0.35
                    else:
                        self.play("fall")
            else:
                self.body.on_ground = True
                self.jumping = False      # ⭐ 踩到地面 → 跳跃结束

        # ⭐ 离台"先跳再 fall"的延时切换
        _fd = getattr(self, "_fall_delay", 0.0)
        if _fd > 0.0:
            self._fall_delay = max(0.0, _fd - dt)
            if self._fall_delay <= 0.0 and self.state in ("jump", "jump_excited"):
                self.play("fall")
            else:
                self.body.on_ground = True
                self.jumping = False      # ⭐ 踩到地面 → 跳跃结束

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
