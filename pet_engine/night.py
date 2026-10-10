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
                           QFont, QLinearGradient, QRadialGradient, QIcon,
                           QPolygonF)
from PySide6.QtWidgets import QApplication, QWidget

try:                                    # 包内导入 / 直接跑脚本 两种都支持
    from .core import load_pack
    from .ui import silhouette_of
except ImportError:
    from core import load_pack
    from ui import silhouette_of

# ============================================================================
# 🎵 音频（PR-03 第三批）—— ⛔ **函数内延迟 import**，理由同core/ui
#   ① `ui → ui_toolbar → night → audio` 会成环吗？—— 不会（audio 不import 我们），
#      但 audio 要import PySide6.QtMultimedia，那是**打包 excludes里曾经有的一条**。
#      放顶层 ⇒ 打包漏插件时整个游戏连窗口都开不出来（ModuleNotFoundError）。
#   ② 放在函数内 ⇒ 最坏情况只是"没声音"，游戏照常跑（可降级）。
#   ⛔ 因此 `LunaPet.spec` 的 hiddenimports 里必须点名 "audio"（同 night/gamehub）。
# ============================================================================


def _make_audio(parent=None):
    """造一套音频。**绝不抛异常** —— 音频坏掉不该让游戏开不出窗口。"""
    try:
        import audio as _audio
        return _audio.Audio(parent)
    except Exception as e:                     # pragma: no cover
        print(f"[夜间] ⛔ 音频引擎初始化失败（游戏继续，无声）: "
              f"{type(e).__name__}: {e}")
        return None


def _is_day_level(cfg: dict) -> bool:
    """这一档是白天档吗？决定起白天 BGM 还是夜间 BGM（PR-05）。

    ⭐ **为什么判「关卡名」而不是「游戏全局只有一个时间」**：
       2026-10-05 Ronny 把三档并成**一档「正午」**，设定是「白天大中午偷」
       （见 `NIGHTS` 上面那段裁决注释）。
       ⇒ 现在**唯一那档就是白天档**，但起的是夜间 BGM `bgm_steal`，设定与音频对不上。

    ⭐ 认这两个词（`正午` / `白天`），⛔ 别写死成"只有一档所以总是白天"——
       以后加夜档时这一行能自动分流，不用回来改。
    ⚠️ 判据在**配置**里查而不是硬编码在这里，是为了让每档能显式覆盖：
       `cfg["bgm"]` 存在就以它为准（见 `start_night`）。
    """
    name = str(cfg.get("name", ""))
    return ("正午" in name) or ("白天" in name)


def _stop_level_bgm(snd) -> None:
    """⭐ 停掉**这一档可能在响的所有 BGM**（PR-05：白天 + 夜间两套共存）。

    ⛔ **为什么要这个函数，而不是在每个调用点列举名字**：
       结算（`_show_result`）和被抓（`_on_caught`）两处原本都只写了
       `stop_loop("bgm_steal")`。加了白天 BGM 之后，
       ⛔ 它们会**漏停白天那条 ⇒ 结算面板上白天 BGM 还在响**
       （结算面板是**不限时**的，玩家会一直听着）。
       而每加一条 BGM 就要回来补一次 `stop_loop` ⇒ 迟早再漏。
       ⇒ 改成「枚举 `_loops` 里所有 bgm_* 一次停干净」，**以后加 BGM 不用改这里**。

    ⚠️ 只停 `bgm_` 前缀。（2026-10-06 PR-06：原先这里还写着"环境音走
       面板期降音量那条线，它要在结算期间继续响"——那条线已随 Ronny
       「环境音不要了」一起删干净，这里同步更新，别再引用它。）
    """
    if snd is None:
        return
    for name in [k for k in list(getattr(snd, "_loops", {}).keys())
                 if k.startswith("bgm_")]:
        snd.stop_loop(name)


def _level_bgm_name(cfg: dict):
    """这一档该起哪条 BGM。白天档→ 预拼循环件；其余 → `bgm_steal`；取不到 → None。

    ⭐ 抽成函数的原因（2026-10-06 BGM 起播修复）：
       `start_night` 与"押送回窝结束回到 play"两处都要决定起哪条。
       两处各写一份 `import audio` + 分流 ⇒ 以后改分流要回来改两处，
       而漏改的那一处症状是**"被抓一次之后 BGM 永久静音"**（已实测踩过）。
    ⛔ 白天 BGM 的 import 必须**函数内**（同`_make_audio` 的纪律：
       打包漏 QtMultimedia 时顶层 import 会让窗口都开不出来）。
    """
    try:
        import audio as _audio
    except Exception:                            # pragma: no cover
        return None
    # 关卡配置里显式指定 bgm 就以它为准
    name = str(cfg.get("bgm") or "") or None
    if name is None and _is_day_level(cfg):
        name = _audio.BGM_DAY_LOOP
    return name


# ============================================================================
# ① 关卡数据 —— 深夜厨房（灰盒，改这里就能改关卡）
# ============================================================================

VW, VH = 1280, 720

# ⭐⭐⭐ 2026-10-05 PR-03 第一批：左右镜头跟随
#   世界宽 3840（= 3 张 1280 切片），视口仍是 VW ⇒ cam_x ∈ [0, 2560]
WORLD_W = 3840
CAM_X_LAG   = 6.0        # 平滑系数。⛔ 别>10（滞后）别<4（硬跟）
CAM_X_DEAD  = 24.0       # 死区半宽：露娜在 cam_x+640±24 内移动 ⇒ 镜头**完全不动**
CAM_X_CENTER = VW * 0.5  # 视口中心 = 640
CAM_X_MAX   = WORLD_W - VW      # = 2560

# ⭐⭐ PR16 · 编辑态手动平移速度（px/s）。
#   ⛔ 与 _step_cam 完全独立：那是 play 路径的「跟随露娜」，
#      这是 edit 路径的「Ronny 自己挪视野」，两者互不相干。
#   ⛔ 别设 <400：挪完 3840 宽要 10 秒，难受（派单 §A.1 原话）。
EDIT_CAM_SPEED = 900.0

FLOOR_Y = 670               # ⭐⭐⭐ 2026-10-10 Ronny 拍板：**地板顶面下移到「画布底往上 50px」**
                            #   （VH=720 ⇒ 720−50=670；原 599，下移 71px）
                            #   ⚠️⚠️ **已知代价（Ronny 选的乙案「只改这一个数」）**：
                            #     `FRIDGE={"x":1120,"y":599,...}` 是**硬编码**、⛔ 不跟 FLOOR_Y 变
                            #     ⇒ **冰箱会比地板低 71px**（陷进地板）。
                            #     同理 `LADDERS[0]` 的 ybot 仍是旧值 ⇒ 梯子/桌布底差 71px。
                            #   ⭐ 为什么敢直接改：实测美术切片 `scene_bg_0.png` 的
                            #     y=560~712 **全是木地板暖色、一路铺到画布底 720、没有硬边线**
                            #     ⇒ 视觉上人物**不会陷进墙里**。
                            #   📌 历史：2026-10-03 按背景板实测定的 599
                            #     （y=580 平滑区 → y=600 纹理区，非初测的 578 踢脚线）
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
# ⛔⛔ 2026-10-06 追加作废：PR-04 曾把这组x 按实拍暂改成 690~1180，
#   但 BG02i 要按图生图 prompt 整体重绘 ⇒ 坐标表作废、已回退。**别再照那张表改。**
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
# ⛔⛔ 2026-10-06 **PR-04 坐标重排已作废**（BG02i 要按图生图 prompt 整体重绘，
#   家具位置/顶面高度都会变）。曾按实拍暂改成 茶几 690~1180 / 台 2040~2320 /
#   吊柜 2015~2320 / 冰箱 1925，等 PR04v2 重新给表。**当前这组是旧示意图布局，勿当实测。**
PLATFORMS = [
    # ⭐⭐⭐ 2026-10-05 P0：地板右沿 `VW` → `WORLD_W`。
    #   病根同 investigate：PR-03 把世界改成 3840 时只改了 `_clamp_x`，
    #   忘了平台表 —— 而 `_clamp_x` 放行到 x=3801，**地板却只到 1280**。
    #   ⛔ 实测（_work/_探_地板右沿.py）：露娜从 x=1200 起跑，
    #   第 8~12 帧就在 x≈1302 处踩空（站立判定的有效右沿 = 1280+BODY_W*0.35 = 1301.7），
    #   掉进 y>VH+200 的兜底 ⇒ **被瞬移回窝，赃物清零**。
    #   ⇒ 玩家往右跑会「突然被拽回窝」，这是穿帮不是玩法。
    #   ✅ 一改就好（实测扩到 WORLD_W 后她能走到 x=3801 站稳）。
    (0,    FLOOR_Y, WORLD_W, VH),   # 地板
    (TABLE_X0, TABLE_TOP, TABLE_X1, FLOOR_Y),  # ⭐ 餐桌（桌布左 430 / 右 700 / 桌面 488）
    (760,  380,     1060, 418),     # ⭐ 厨房台：顶 380 / **底 418（薄台面，架空可穿行）**
    (790,  50,1010, 189),     # ⭐ 吊柜（柜顶 50 / 下沿 189 / 左 790 / 右 1010）
]

# ============================================================================
# ⭐⭐⭐ PR12 · 自定义地形（层）的数据层
# ============================================================================
# ⛔⛔ 为什么 `PLATFORMS` 本体**仍然是 4 元组**，而 dict 层另起：
#   派单 §2.1 要求"平台从4 元组升级为 dict"。但项目里有 **6 处自测按下标取元组**：
#     _自测_夜间.py:85-87   N.PLATFORMS[2][1] / [1][1] / [3][1]
#     _自测_PR04判据.py:40-41 N.PLATFORMS[2] / [3]
#   若把 PLATFORMS 元素直接换成 dict，`[1]` 会变KeyError ⇒ 这 2 个自测直接崩
#   ⇒ 违反派单验收线第 2 条「现有 22 个自测全绿」。
# ✅ 折中且可搜索的做法（已报设计端，等确认）：**全局常量不动**（自测照旧），
#   运行时一律用 `Room.platforms`，它是 **list[dict]**。
#   ⭐ 这样"新增代码全走 dict"成立，"既有自测一行不改"也成立，两条都保住。
#
# ⭐ 三种 kind（Ronny 2026-10-08「永久/ 碰触后短暂消失 / 攀爬」）：
#   "solid"   永久地形，永远可站
#   "brittle" 碰触后短暂消失（踩上→ 消失 → BRITTLE_RECOVER 秒后回来）
#   "climb"   攀爬地形（按上下键），**复用已验证的 LADDER_ZONES 机制**
TERRAIN_KINDS = ("solid", "brittle", "climb")

# ⛔⛔ Ronny 2026-10-08 已定案（派单 §六）：
#   Q1 消失后能否再踩= ⛔ **不能**
#   Q4 恢复秒数      = ✅ **2.5 秒定稿**
BRITTLE_RECOVER = 2.5         # brittle 消失后多少秒恢复（秒）—— Ronny 定稿
# ⛔⛔ Q1 定案为「不能」⇒ 已消失的平台**完全不参与落地判定**，恢复期间站不上去。
#   ⛔ 别改成"能"：那会让"站在原地等它回来"变成可行解，脆地形就失去意义。
BRITTLE_RECOVERABLE_STAND = False   # Ronny 定稿：不能

# 导出 JSON 的格式版本（派单 §五 写死 version=1）
TERRAIN_JSON_VERSION_V1 = 1     # PR12 的格式（只有 terrains 四键）

# ⭐⭐ PR12 · 直线工具（Ronny 2026-10-08 定案）
#   Ronny 原话：「直线就是绘制**没有厚度**的地形。绘制斜面或直线地形，
#   **没有厚度没有 y1 的数据**。垂线是绘制垂直攀爬面，这样的地形只能攀爬。
#   要一个 Shift 锁定按钮，按下 Shift 时直线只能垂直或水平」
#⭐ 这是「不需要重写落地判定」的关键：
#   水平线（y0 == y1）⇒ 零厚平台 ⇒ 现有 `prev_y <= y0+LAND_TOL and y >= y0` 直接能用
#   垂直线（x0 == x1）⇒ 零厚攀爬面 ⇒ _ladder_here 的解包形态一致，可直接复用
# ⛔⛔ 导出时 `y1` 字段**不许省**（哪怕等于 y0）—— schema 统一，不搞两套格式。
# ⛔ 零厚平台的**最小可画尺寸**见 EDIT_MIN（零厚≠无尺寸，0会被当成空矩形拒掉）
# ⭐ 零厚线的**副轴下限**（主轴必须是精确 0，见 _edit_add）。
#   ⛔⛔ 我第一版对主轴也做补齐（`xa -= EDIT_MIN/2`）⇒ 水平线被撑成 2px 宽、
#      垂直线被撑成 2px 厚 ⇒ 「垂直线=攀爬面」这个语义直接废了
#      （面宽 2px 时 `_ladder_here` 的 `min(max(x,x0+8), x1-8)` 恒给 x0-8，
#      玩家会被硬拽到线的左侧 8px 处）。⇒ **零厚必须真的是零厚。**
EDIT_MIN = 0.0

# ⭐ 「厚度 < 这个值就算零厚」的判定阈值（渲染/点选用，**不是绘制下限**）。
#   ⛔ 为什么不用 EDIT_MIN：那个是"最小可画尺寸"，恒为 0；拿它判零厚会永远为真。
#   ⛔⛔ 也不能取 0：`== 0` 在浮点加减后不可靠（拖拽算出来是 0.0000001 也可能）。
_THIN_EPS = 0.5# px

# ⛔⛔ **斜线（本版不支持）**—— 我的取舍，需Ronny 拍板（已报设计端）：
#   Ronny 原话覆盖了「水平线」「垂直线」「Shift 锁定」三种，
#   但**没覆盖"既不水平也不垂直的零厚斜线"**。
#   ⛔ 而斜线会**破坏落地判定**：现有判定是 `prev_y <= y0 + LAND_TOL and y >= y0`
#      —— 它整个建立在"平台有一个确定的顶面 y0"这个单一假设上。
#      斜面意味着顶面随 x 变 ⇒ 要重写 :1183 那段，还会连带影响 :1804 微波炉下平台。
#   ⇒ 本版实现：直线工具在**没按 Shift** 时画有厚度的矩形（自由）；
#                **按住 Shift** 时画零厚线并强制轴对齐（水平 或 垂直，两者都允许）。
#   ⛔ 绝不静默降级成水平线 —— 那会让用户以为画了斜线，实际不是。
EDIT_LINE_ANGLE_LOCK = True     # Shift = 强制水平/垂直

# ============================================================================
# ⭐⭐⭐ PR13 · 食物 / 起点 / 窝区 / 巡逻段 的白名单与默认值
# ============================================================================
# ⛔⛔ icon 白名单是**硬约束**（派单 §1.4，已实测）：
#   图标是**启动时按 NIGHTS 里出现过的 icon 一次性预加载**的
#   （`NightWindow.__init__`: `_all_ic = sorted({s["icon"] for n in NIGHTS for s in n["stashes"]})`）
#   而 `_draw_stashes` 用 `self.icons.get(st["icon"])` 取
#   ⇒ 名字不在白名单里 ⇒ 取到 None ⇒ **绘制崩**。
#   ⛔ 所以编辑器**只允许从这 7 个里选**，且 import 校验要拒掉白名单外的。
FOOD_ICONS = ("blueberry", "chicken", "pumpkin",
              "salmon", "watermelon", "yogurt", "yolk")
# ⛔⛔ 地面容器的 kind 白名单（派单 §1.5）：
#   `fridge` 档是给**冰箱格**（FRIDGE_FOODS）走的另一条路。
#   ⛔ 混进地面容器 ⇒ 玩家在台面上看到一个冰箱格，语义错乱。
FOOD_KINDS = ("loose", "plate", "jar")

# ⭐ 编辑器新建食物时的默认值（派单 §2.2）
DEFAULT_FOOD_ICON = "yolk"
DEFAULT_FOOD_KIND = "loose"
#⭐ 冰箱食物只有 icon、没有 kind（派单 §1.1 的两列是独立的两条路）
DEFAULT_FRIDGE_ICON = "watermelon"

# ⭐⭐ JSON schema 版本（派单 §4）
#   v1 = 只有 4 个键（terrains）—— PR12 的格式
#   v2 = 新增 5 个键（stashes / fridge_foods / spawn / mw_patrol / nest）
# ⛔⛔ **导出时的规则（派单 §4.2，硬要求）**：
#   5 个新字段**全为 null** ⇒ 导出 **v1 四键**（保住既有 3 条自测）
#   任一非 null            ⇒ 导出 **v2 全键**
#   ⇒ 所以 v1 与 v2 都是**合法**输出，取决于有没有覆盖。
TERRAIN_JSON_VERSION_V2 = 2     # PR13 的格式（+5 个可覆盖字段）
# ⭐⭐ PR16（B 段，Ronny 2026-10-09 拍板「方案 1」）：地形条目带 `builtin: true`
#   ⇒ 表示这条是**默认 PLATFORMS 里被改过的**，导出时升 v3。
#   ⛔ 判据与 `Room.__init__` 用的是**同一个**（`存在任一 builtin 条目`），别搞两套。
TERRAIN_JSON_VERSION_V3 = 3
# ⭐⭐ PR23：`border_x`（关卡边界）需要第 4 个版本 —— **不塞进 v3**。
#   ⛔ 理由：v3 已经有明确语义（= 带 builtin 的地形集），塞进去会让**老 v3 文件
#      的含义漂移**（同一份文件在不同版本下读出不同的 border_x）。
TERRAIN_JSON_VERSION_V4 = 4
# ⭐ **导入时三个都要接受**（旧版本缺失的字段按默认处理）
TERRAIN_JSON_VERSIONS = (TERRAIN_JSON_VERSION_V1, TERRAIN_JSON_VERSION_V2,
                         TERRAIN_JSON_VERSION_V3, TERRAIN_JSON_VERSION_V4)

# ⭐⭐ null 语义必须严格区分（派单 §4.1，⛔ 不许合并）：
#   None / 键缺失 = **不覆盖，用关卡默认**
#   [] / {}       = **显式设为空**（"这关一个容器都没有"）
#   ⛔ 合并了就永远无法表达"故意清空" ⇒ 这是语义，不是便利性。
# ⭐⭐ PR23：加第 6 个可覆盖字段 `border_x`（关卡边界）。
#   ⛔ **null 语义与其余 5 类完全一致**：None = 不覆盖（用关卡默认）。
#      ⛔ 不许拿 0 当"不覆盖" —— 写法必须和其它 5 类一样。
OVERRIDE_KEYS = ("stashes", "fridge_foods", "spawn", "mw_patrol", "nest",
                 "border_x")

# ---------------- PR13 · 编辑器 5 个新工具 ----------------
# ⭐ 工具名 → 中文名 + 快捷键（键位派单 §2.1 已定死，⛔ 别撞 PR12 的 1~6/S/O/C/Z/Del/F2/F4）
#⭐ 顺序 = 工具栏显示顺序 = 键位数字顺序（7/8/9/0/-），不是字典序
#   （字典序会把 "-" 排到最前、"0" 排到 "9" 前面 ⇒ 工具栏和手对不上）
EDIT_TOOLS = (
    ("rect",       "矩形",   "4"),
    ("line",       "直线",   "5"),
    ("select",     "选择",   "6"),
    ("food",       "食物",   "7"),
    ("fridge",     "冰箱食物", "8"),
    ("luna_spawn", "露娜起点", "9"),
    ("mw_patrol",  "巡逻段", "0"),
    ("nest",       "窝区",   "-"),
    # ⭐⭐ PR23：关卡边界。键位 **B**（PR23 §2.2 实测：1~0/- 与 S/O/C/Z/Del/F2/F4
    #   /Home/End/PageUp/Down/A/D/←/→ 全占，B 空闲）
    ("border",     "边界",   "B"),
)
# ⭐ 键 → 工具。⛔ 显式建表而不是 `if k == Key_7: ...` 一路if：
#   那样漏一个键位根本看不出来（正是 PR13 半改时被漏掉的原因）。
EDIT_TOOL_BY_KEY = {
    Qt.Key_4: "rect", Qt.Key_5: "line", Qt.Key_6: "select",
    Qt.Key_7: "food", Qt.Key_8: "fridge",
    Qt.Key_9: "luna_spawn", Qt.Key_0: "mw_patrol", Qt.Key_Minus: "nest",
    Qt.Key_B: "border",          # ⭐⭐ PR23 · 关卡边界
}
# ⭐ 需要**拖一条水平线段**的工具（点一下没意义，必须有两端）
# ⭐⭐ PR23：边界也走"拖一条线"的路径（⛔ 竖直线，只取 x）
EDIT_LINE_TOOLS = ("mw_patrol", "nest", "border")
# ⭐ 单实例工具（派单 §2.1）：再点一次 = 移动，不是新增
EDIT_SINGLE_TOOLS = ("luna_spawn", "mw_patrol", "nest", "border")
# ⭐ 新放置食物的默认属性（派单 §2.2）
DEFAULT_FOOD = {"icon": "yolk", "kind": "loose"}
# ⭐ 三种地面容器的画法颜色（派单 §2.4「按 kind 三色区分」）
#   ⛔ 不复用 _EDIT_COLOR（那是地形 solid/brittle/climb 的语义色）
#     ⇒ 混用会让"红色的东西"到底是脆化地形还是 jar 食物说不清。
FOOD_KIND_COLOR = {
    "loose": (255, 214, 122),   # 暖黄=散落
    "plate": (140, 226, 160),   # 绿=盘子里
    "jar":   (150, 190, 255),   # 蓝=罐子
}
FOOD_KIND_CN = {"loose": "散落", "plate": "盘子", "jar": "罐子"}


def platform_dicts(plats=None) -> list:
    """4 元组列表 → dict 列表（含 kind）。

    ⭐ kind 是**按位置**判定的，不是按坐标猜的 —— 理由见下方注释。
    ⛔⛔ **位置映射是硬编码的**：只对默认 PLATFORMS 的 4 项成立。
       自定义地形（编辑器的）一律显式带 kind，不走这个函数。
    位置约定（与 PLATFORMS 的书写顺序一一对应）：
       0 地板 / 1 餐桌 / 2 厨房台 / 3 吊柜 —— **全部 solid**。
    ⚠️ 为什么不给吊柜标 climb：吊柜在旧布局里没有攀爬面（桌布/挂毯才是），
       擅自把它变 climb 会让微波炉/露娜多出���条攀爬路径 ⇒ 改变既有行为。
       ⛔ 那是玩法改动，不属于本单。
    """
    src = PLATFORMS if plats is None else plats
    out = []
    for i, p in enumerate(src):
        if isinstance(p, dict):
            out.append(dict(p))
            continue
        out.append({"x0": p[0], "y0": p[1], "x1": p[2], "y1": p[3],
                    "kind": "solid"})
    return out


def platform_get(p, key: str, default=None):
    """按**字段名**取一块地形上的值 —— tuple / dict 都吃。

    ⭐ 这是 design端要求的**唯一收口点**（原话：「加两个 helper，tuple / dict 都吃」）。
       项目里有 3 处自测/诊断脚本**不走 Room.__init__**、直接
       `room.platforms = list(N.PLATFORMS)` 灌 4 元组：
         _自测_PR04判据.py:54 / _自测_冰箱.py:44 / _d_新布局几何.py:36
       ⛔⛔ 所以**新代码必须走这个helper**，不能直接 `p["x0"]`——
          那样这三处一灌元组就 KeyError，新代码全炸。
       ⛔ 而那三处**一个字都不许改**（改判据是设计端的活）。

    映射（tuple 按位置，dict 按 key）：
       x0→0, y0→1, x1→2, y1→3, kind→无（tuple 一律当 solid）
    """
    _TUP_IDX = {"x0": 0, "y0": 1, "x1": 2, "y1": 3}
    if isinstance(p, dict):
        return p.get(key, default)
    if key in _TUP_IDX:
        try:
            return p[_TUP_IDX[key]]
        except (IndexError, TypeError):
            return default
    return default                      # ⭐ 4 元组没有 kind ⇒ default


def plat_fields(p):
    """取出一块地形的 (x0, y0, x1, y1)，**dict 与 4 元组都吃**。

    ⭐ 为什么要这个 helper：`room.platforms` 现在是 list[dict]，
       但脚本/旧代码可能塞 4 元组进来（自测就是这么干的）。
       ⇒ 统一在这里收口，避免每个消费点各写一遍 if。

    ⭐⭐ **坐标在这里统一 float() 归一**（2026-10-08）：
       `plat_valid` 放行了纯数字字符串（`"400"` 语义上就是 400），
       那物理层拿到的就还是 str ⇒ `x0 - BODY_W*0.35` 会 TypeError。
       ⇒ **归一必须放在这里**（所有消费点的唯一收口），
          而不是让每个 `p["x0"]` 调用点各自包一层 float()——
          那样漏一处就是一个新的崩法。
    ⛔ 转不动的（`plat_valid` 已经挡掉，这里是双保险）原样返回，
       不抛 —— 判据负责丢弃，helper 只负责取值。
    """
    if isinstance(p, dict):
        vals = (p["x0"], p["y0"], p["x1"], p["y1"])
    else:
        vals = (p[0], p[1], p[2], p[3])
    out = []
    for v in vals:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(v)
    return tuple(out)


def plat_kind(p, default: str = "solid") -> str:
    """取 kind，**缺省 solid**。

    ⭐ 缺省 solid 是刻意的：任何没带 kind 的平台都必须能被站，
       否则「漏写一个字段 ⇒ 地形变脆/ 变爬」会变成极难查的玩法 bug。
    ⭐ 这条也是自测第 7 条（阳性对照）的依据：
       **已知不脆的平台永远不该被判成 brittle**。
    ⛔ 4 元组一律返回 default —— 它**没有 kind 这个信息**，
       猜一个等于把"未知的平台"当成永久地形，静默改变玩法。
    """
    return str(platform_get(p, "kind", default) or default)


def table_wall_span(room):
    """这个 room 里有没有「餐桌/桌布」这一条？⇒ (x0, x1, ytop) 或 None

    ⭐⭐⭐ **PR24 · 本函数存在的唯一理由**（实测踩出来的真 bug）：
       原来两处布墙直接读**模块常量** `TABLE_X0/TABLE_X1/TABLE_TOP`
       ⇒ Ronny 把餐桌从地形里删掉，**这堵墙照样在** ⇒ 「删了地形还是出不去」。

    ⛔⛔ **判据不许读 `TABLE_X0/TABLE_X1`**（否则上面那个 bug 原样复发）。
       只读 `room.platforms`。

    ⭐ **为什么用「顶面高度 + 是否垂到地」，而不是派单建议的「x 重叠 ≥50%」**
       （工程规约 §3.1 要求先跑示例，我跑了，实测两个问题）：
       | 输入 | 派单判据 | 本函数 | 哪个对 |
       |---|---|---|---|
       | 默认餐桌 (430,488,700,599) | 命中 | 命中 | 都对 |
       | 只剩地板 (0,599,3840,720) | None | None | 都对 |
       | **餐桌挪到 x=1500** | **None ❌** | 命中 | **本函数对**（判据 C3 要求墙跟着挪） |
       | **PR21 零厚水平线 y=488** | **命中 ❌** | None | **本函数对**（线不该变成 400px 宽的墙） |

    ⭐ 判据（两条都要，缺一个就错）：
       ① 顶面高度 `y0` 在 `TABLE_TOP ± 40`（448~528）⇒ 「这是张桌面」
       ② **垂到地** `y1 >= FLOOR_Y - 1`⇒ 「它挡路」
          ⛔ 这条把零厚线排除在外（线 y1==y0，不垂到地）
    """
    best = None
    for p in getattr(room, "platforms", None) or []:
        x0, y0, x1, y1 = plat_fields(p)
        if abs(float(y0) - TABLE_TOP) > 40.0:
            continue
        if float(y1) < FLOOR_Y - 1.0:
            continue                      # ⭐ 不垂到地 ⇒ 不挡路（零厚线走这里）
        _seg = (float(x0), float(x1), float(y0))
        # 命中多条 ⇒ 取**最宽**的那条（最宽的才是真正挡路的）
        if best is None or (_seg[1] - _seg[0]) > (best[1] - best[0]):
            best = _seg
    return best


def plat_valid(p) -> bool:
    """这块地形**结构上**能不能用？⇒ bool（不抛异常）。

    ⭐⭐ 存在的理由（真实可达的路径，不是洁癖）：
       Ronny 会**手动编辑** `assets_game/custom_terrain.json`。
       ⇒ 下次启动时，脏数据会**一路走进物理判定**，而物理层是
         `for _p in room.platforms` 直接解包 —— 一条脏数据就崩整个游戏。
       实测四种崩法（都真实复现过）：
         platforms=None      ⇒ TypeError: 'NoneType' object is not iterable
         [{}] 空 dict         ⇒ KeyError: 'x0'
         [(0, 599)] 1 元素    ⇒ IndexError: tuple index out of range
         [None]              ⇒ TypeError: 'NoneType' object is not subscriptable

    ⛔⛔ 判定**故意只查「能不能安全参与算术」，不查「数值合不合理」**：
       · 坐标反了（x0>x1）不崩、y0 远高于画布不崩 —— 那只是"这块地不好用"，
         不是"数据损坏"。判它非法会让Ronny 手摆的怪地形凭空消失。
       · 所以这里只挡**会让解包/比较崩掉**的那些。

    ⭐⭐⭐ 为什么要多一层「值能转 float」（第二道闸，2026-10-08 补）：
       第一版只查「键在不在」⇒ 漏掉了**值类型炸**这条路，而它**更容易被手写触发**：
         {"x0": "400", ...}    打字忘了去引号/ 从别处粘来带引号 ⇒ ⛔ TypeError
         {"x0": null, ...}      复制粘贴带了个 null     ⇒ ⛔ TypeError
         {"x0": [1,2], ...}     写成数组                ⇒ ⛔ TypeError
       根因：物理层要算 `x0 - BODY_W*0.35` 和 `self.x <= x1 + ...`
       ⇒ **坐标必须是数**。
       ⚠️⚠️ 实测这条**不对称**，所以「四个字段必须全查**：
         实测 `y1` 是字符串**居然不崩**（它没参与算术），
         而 `x0` 是字符串**立刻崩** ⇒ 只靠"自己试一次崩不崩"必然漏。
    """
    if p is None or isinstance(p, (bool, int, float, str, bytes)):
        return False                      #标量/None 一律非法
    # ⭐ 四个坐标的「能当数用」判定，dict 与 tuple 共用（抽出来免得写两遍漏一处）
    def _nums_ok(vals):
        for v in vals:
            # ⛔ bool 必须单独挡：float(True)==1.0 会静默通过 ⇒ "x0": true
            #   会被当成 x=1 使用，静默改变地形。这种"看起来合法"比崩更坏。
            if isinstance(v, bool):
                return False
            # ⛔ 只放行 int/float/str：list/dict/None/tuple 一律判非法
            if not isinstance(v, (int, float, str)):
                return False
            try:
                float(v)
            except (TypeError, ValueError):
                return False              # "abc" 这种转不了的 ⇒ 非法
        return True

    if isinstance(p, dict):
        if not all(k in p for k in ("x0", "y0", "x1", "y1")):
            return False
        # ⭐ 纯数字字符串（"400"）算**合法** —— JSON 里 "400" 语义上就是 400，
        #   物理层用 float() 归一（见 plat_fields）。
        return _nums_ok((p["x0"], p["y0"], p["x1"], p["y1"]))
    if isinstance(p, (tuple, list)):
        # ⛔⛔ 4 元组也要查值类型 —— 它是「旧格式」，但那 3 处自测/外部脚本
        #   同样可能塞进脏数据，物理层一样会崩。
        return len(p) >= 4 and _nums_ok((p[0], p[1], p[2], p[3]))
    return False


def sanitize_platforms(plats, warn_prefix="地形") -> list:
    """过滤掉结构不合法的地形条目。⇒ 干净列表（坏的已丢弃）。

    ⭐⭐ **为什么是「丢弃」而不是「抛异常」**：
       抛异常 ⇒ Ronny 手滑写坏一个字段，整个游戏进不去，
       而他未必知道是哪个字段 ⇒ **改一个数要重新开一次游戏才能试**。
       丢弃 + warn ⇒ 坏的那块不生效，其余照常，他能立刻看到 warn 说哪块被丢。
    ⭐ warn 必须打出来（⛔ 不许静默）：静默丢弃 = 用户以为地形生效了，
       画面上却少一块 ⇒ 这种"看起来能跑但结果不对"是最难查的一类。
    """
    if plats is None:
        print("[%s] ⚠️ 地形表是 None，已按空表处理" % warn_prefix)
        return []
    out, bad = [], 0
    try:
        it = list(plats)
    except TypeError:
        print("[%s] ⚠️ 地形表不是可迭代对象（%r），已忽略" % (warn_prefix, type(plats).__name__))
        return []
    for i, p in enumerate(it):
        if plat_valid(p):
            out.append(p)
        else:
            bad += 1
            print("[%s] ⚠️ 第 %d 条地形结构不合法，已丢弃：%r" % (warn_prefix, i, p))
    if bad:
        print("[%s] ⚠️ 共丢弃 %d / %d 条（手改JSON 时最常见：少了字段/ 写成了嵌套）"
              % (warn_prefix, bad, len(it)))
    return out


def which_part(x0, x1, y0, floor_y=None) -> str:
    """这块地形该贴哪张家具图？→ "table" / "counter" / "cabinet" / ""（不贴）。

    ⭐⭐ **为什么必须有一层显式判据**（这是我改掉「按序号取图」的核心）：
       原来的写法是 `i==1 餐桌 / i==2 料理台 / i==3 吊柜`—— 靠**书写序号**。
       自定义地形一旦进来，序号与家具的对应关系立刻失效
       ⇒ 第 2 项会贴上料理台、第 3 项贴吊柜 ⇒ 重影换个形式复活。

    ⛔⛔ 判据只用**既有常量**，一个���数字都不引入 ——
       否则改布局时这里会静默失效（贴错图不报错）。
       x 区间取自 PLATFORMS 原有的三项家具。

    ⚠️ 已知局限（写在这里免得下一个人以为是精确的）：
       判据是「x 区间**重叠超过一半**」⇒ 一个横跨两个家具的大平台
       会被判给x 中心所在的那个家具。默认 4 平台各占一段，不会命中这个边界；
       ⛔ 自定义地形若出现超长横条，贴图归属会变得不确定
       —— 已在「未验证」里报出，等Ronny 拍板是否要更严格的归属规则。
    """
    fy = FLOOR_Y if floor_y is None else floor_y
    w = max(1.0, float(x1) - float(x0))

    def overlap(ax0, ax1):
        """x 区间重叠长度 / 宽度。>=0.5 ⇒ 归属它。"""
        lo = max(float(ax0), float(x0))
        hi = min(float(ax1), float(x1))
        return max(0.0, hi - lo) / w

    # 吊柜在最��面（y0 很小），厨房台次之，餐桌在最下—— 与 PLATFORMS 的 y 一致
    if float(y0) <= 120.0 and overlap(TABLE_X0, TABLE_X1) < 0.5 \
            and overlap(760, 1060) >= 0.5:
        return "cabinet"
    if overlap(760, 1060) >= 0.5:
        return "counter"
    if overlap(float(TABLE_X0), float(TABLE_X1)) >= 0.5:
        return "table"
    return ""


def terrain_to_json(terrains, world_w=None, floor_y=None, overrides=None) -> dict:
    """导出为派单 §五/§4.1 定死的结构。

    ⛔ 字段名与顺序照抄派单，我下游要按字段名写生成脚本。
    ⭐ 导出时**把坐标转成 int**：编辑器里拖出来的都是 float，
       而 JSON 里带一串小数会让下游生成脚本难对齐。
    ⛔⛔ **零厚语义必须保住**：整条直线（x0==x1 或 y0==y1）转 int 后仍要相等。
       实测踩过一次坑：垂直线 x0=1500.4 时 `int(round(1499.6))==1500` 与
       `int(round(1500.4))==1500` 侥幸相等，但 `x0=1500.6` 会变成 1501 ≠ 1500
       ⇒ 零厚线被"撑"成 2px 宽的矩形，语义从"攀爬面"变成"窄平台"。
       ✅ 修法：**同一侧用同一个取整结果** —— 先各自 round，再让相等的两侧
          直接共用同一个值。这不是取巧，是零厚语义的要求。

    ⭐⭐⭐ **PR13：version 自适应（派单 §4.2，硬要求）**：
       5 个可覆盖字段**全为 None** ⇒ 导出 **v1 四键**（与 PR12 逐字一致，
       保住既有 3 条自测：`:141` 键集合、`:144` version==1、`:626` 磁盘键集合）
       任一非 None ⇒ 导出 **v2 全键**
       ⛔ 这不是"偷懒兼容"，是**契约**：v1 文件下游脚本按四键解析才不会崩。
    """
    _has_builtin = False

    def _r(v):
        # ⭐ 取整用"四舍五入到整数"，但**保留符号对称性**：
        #   round(-0.5)=0 与 round(0.5)=0 不一致，所以统一走 floor(v+0.5)。
        return int(math.floor(float(v) + 0.5))

    out = []
    for p in terrains:
        _xa, _ya, _xb, _yb = plat_fields(p)
        ix0, iy0 = _r(_xa), _r(_ya)
        ix1, iy1 = _r(_xb), _r(_yb)
        # ⭐ 零厚侧强制相等（两侧都取**同一个**值，不是各取各的）
        if abs(float(_yb) - float(_ya)) < _THIN_EPS:
            iy1 = iy0
        if abs(float(_xb) - float(_xa)) < _THIN_EPS:
            ix1 = ix0
        _e = {"kind": plat_kind(p), "x0": ix0, "y0": iy0, "x1": ix1, "y1": iy1}
        # ⭐⭐ PR16 · B 段：这条是**被改过的默认平台** ⇒ 打 builtin 标记（v3）
        if platform_get(p, "builtin"):
            _e["builtin"] = True
            _has_builtin = True
        out.append(_e)
    doc = {
        "version": TERRAIN_JSON_VERSION_V1,
        "world_w": int(WORLD_W if world_w is None else world_w),
        "floor_y": int(FLOOR_Y if floor_y is None else floor_y),
        "terrains": out,
    }
    # ---- PR13：按需升 v2；PR16：有 builtin ⇒ 升 v3 ----
    ov = overrides or {}
    # ⭐⭐ null 语义（§4.1）：**None = 不覆盖**，这才是"导出 v1"的判据。
    #   ⛔ 别把 None 和 [] 混为一谈 —— [] 表示"显式清空"，必须真的写进文件。
    has_any = any(ov.get(k) is not None for k in OVERRIDE_KEYS)
    if not has_any and not _has_builtin:
        return doc                       # ⭐ v1：四键，不带任何新字段
    # ⛔ v3 优先于 v2：v3 文件**也要**写 overrides（可以同时有改过的默认平台 + 食物）
    # ⭐⭐ PR23：版本优先级 **v4 > v3 > v2 > v1**（一位一增，不跳级）
    #   ⛔ v4 文件**也要**写全部 overrides（可以同时有 builtin 地形 + 边界 + 食物）
    if ov.get("border_x") is not None:
        doc["version"] = TERRAIN_JSON_VERSION_V4
    elif _has_builtin:
        doc["version"] = TERRAIN_JSON_VERSION_V3
    else:
        doc["version"] = TERRAIN_JSON_VERSION_V2
    _write_overrides(doc, ov)
    return doc


def _write_overrides(doc: dict, ov: dict) -> None:
    """把 5 个可覆盖字段写进 doc（v2 用）。⛔ 非 None 才写键。"""
    if ov.get("stashes") is not None:
        doc["stashes"] = [
            {"x": _i_round(s["x"]), "y": _i_round(s["y"]),
             "icon": str(s["icon"]), "kind": str(s["kind"])}
            for s in ov["stashes"]]
    if ov.get("fridge_foods") is not None:
        doc["fridge_foods"] = [
            {"x": _i_round(f["x"]), "y": _i_round(f["y"]),
             "icon": str(f["icon"])}
            for f in ov["fridge_foods"]]
    if ov.get("spawn") is not None:
        sp = ov["spawn"]
        #⭐ spawn 固定是 {"luna": {...}} 一层壳 —— 以后加"微波炉起点"也好扩展
        doc["spawn"] = {"luna": {"x": _i_round(sp["luna"][0]),
                                  "y": _i_round(sp["luna"][1])}}
    if ov.get("mw_patrol") is not None:
        doc["mw_patrol"] = [_i_round(ov["mw_patrol"][0]),
                             _i_round(ov["mw_patrol"][1])]
    if ov.get("nest") is not None:
        doc["nest"] = [_i_round(ov["nest"][0]), _i_round(ov["nest"][1])]
    # ⭐⭐ PR23：关卡边界（v4 才有这个键）
    if ov.get("border_x") is not None:
        doc["border_x"] = _i_round(ov["border_x"])


def _i_round(v):
    """坐标取整（与地形同一套口径：floor(v+0.5)，保证符号对称）。"""
    return int(math.floor(float(v) + 0.5))


def terrain_from_json(data: dict) -> list:
    """导入（派单 §五 的结构）→ list[dict]。

    ⭐ 往返要**完全还原**（自测第 3 条）：只认上面5 个 key，
       其余一律忽略（不保留未知字段 —— 那会让往返不幂等）。
    ⛔ 非法 kind 抛 ValueError 而不是静默降级成 solid：
       静默降级 = 用户导入的手滑写错"britle" ⇒ 全变永久地形 ⇒ 自己看不出来。
    """
    if not isinstance(data, dict):
        raise ValueError("地形 JSON 顶层必须是对象")
    ver = data.get("version")
    # ⭐⭐ PR13：**v1 与 v2 都接受**（v1 缺失的字段按 null 处理）
    #   ⛔ 不写成 `ver != TERRAIN_JSON_VERSION` —— 那样 v1 文件会被拒，
    #   而 PR12 导出的全是 v1 ⇒ Ronny 手里的文件全打不开。
    if ver not in TERRAIN_JSON_VERSIONS:
        raise ValueError("不支持的 version=%r（当前支持 %s）"
                         % (ver, "/".join(str(v) for v in TERRAIN_JSON_VERSIONS)))
    ts = data.get("terrains")
    if not isinstance(ts, list):
        raise ValueError("terrains 必须是数组")
    out = []
    for i, t in enumerate(ts):
        if not isinstance(t, dict):
            raise ValueError("terrains[%d] 必须是对象" % i)
        k = str(t.get("kind") or "solid")
        if k not in TERRAIN_KINDS:
            raise ValueError("terrains[%d].kind=%r 非法（只能是 %s）"
                             % (i, k, "/".join(TERRAIN_KINDS)))
        try:
            _e = {"kind": k,
                  "x0": float(t["x0"]), "y0": float(t["y0"]),
                  "x1": float(t["x1"]), "y1": float(t["y1"])}
        except KeyError as e:
            raise ValueError("terrains[%d] 缺字段 %s" % (i, e))
        # ⭐⭐ PR16 · B 段：只有 **v3** 才认 builtin（v1/v2 分支逐字不变，
        #   保住自测 `:141/:144/:626` 的键集合与 version 断言）。
        if ver == TERRAIN_JSON_VERSION_V3 and t.get("builtin"):
            _e["builtin"] = True
        out.append(_e)
    return out


# ============================================================================
# ⭐⭐⭐ PR13 · overrides 的校验与从 JSON 解出
# ============================================================================
def _num(v, what):
    """数值字段校验：⛔ bool 单独挡、⛔ 转不了 float 就抛。

    ⛔ bool 必须挡：`float(True) == 1.0` 会**静默通过**
      ⇒ `"x": true` 会被当成 x=1 使用，用户完全看不出来。
      这是 PR12 踩过的坑（plat_valid 里 `_nums_ok` 同样挡）。
    """
    if isinstance(v, bool):
        raise ValueError("%s 不能是布尔值（true/false 会被当成 1/0 静默通过）" % what)
    if not isinstance(v, (int, float, str)):
        raise ValueError("%s 类型不合法：%r" % (what, v))
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError("%s 不是数值：%r" % (what, v))


def _pair(v, what, strict=True):
    """2 元数值序列校验。⇒ (float, float)。
    ⛔ `strict=True` 时要求 p0 < p1（退化成一个点 = 无意义，直接拒）。
    """
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise ValueError("%s 必须是 2 元数组，收到 %r" % (what, v))
    a = _num(v[0], what + "[0]")
    b = _num(v[1], what + "[1]")
    if strict and a >= b:
        raise ValueError("%s 要求左< 右，收到 %r（退化成一个点了）" % (what, list(v)))
    return (a, b)


def overrides_from_json(data: dict) -> dict:
    """从（v1 或 v2）JSON 解出 overrides dict。⛔ 非法就抛。

    ⭐⭐ **null 语义**（派单 §4.1，⛔ 不许合并）：
       - 键缺失 / `null` ⇒ **None** ⇒ "不覆盖，用关卡默认"
       - `[]` / `{}`     ⇒ 保留成空容器 ⇒ "显式设为空"
       ⇒ 所以这里**必须区分"键在但为 null"和"键不在"**，
         两者都归None；而 `[]` 要原样保留成空 list。
    """
    if not isinstance(data, dict):
        raise ValueError("地形 JSON 顶层必须是对象")
    ver = data.get("version")
    if ver not in TERRAIN_JSON_VERSIONS:
        raise ValueError("不支持的 version=%r（当前支持 %s）"
                         % (ver, "/".join(str(v) for v in TERRAIN_JSON_VERSIONS)))
    ov = {}

    # ---- stashes（地面/台面容器）----
    st = data.get("stashes")
    if st is not None:
        if not isinstance(st, list):
            raise ValueError("stashes 必须是数组或 null")
        items = []
        for i, s in enumerate(st):
            if not isinstance(s, dict):
                raise ValueError("stashes[%d] 必须是对象" % i)
            ic = str(s.get("icon") or "")
            if ic not in FOOD_ICONS:
                raise ValueError("stashes[%d].icon=%r 不在白名单里（只能是 %s）"
                                 % (i, ic, "/".join(FOOD_ICONS)))
            kd = str(s.get("kind") or "")
            # ⛔⛔ 地面容器**只允许三种**（派单 §1.5）：fridge 档是给冰箱格走的另一条路
            if kd not in FOOD_KINDS:
                raise ValueError("stashes[%d].kind=%r 非法（地面容器只能是 %s）"
                                 % (i, kd, "/".join(FOOD_KINDS)))
            items.append({"x": _num(s.get("x"), "stashes[%d].x" % i),
                          "y": _num(s.get("y"), "stashes[%d].y" % i),
                          "icon": ic, "kind": kd})
        ov["stashes"] = items                    # ⭐ 空 list 也保留 ⇒ "显式清空"

    # ---- fridge_foods（冰箱内食物，只有 icon）----
    ff = data.get("fridge_foods")
    if ff is not None:
        if not isinstance(ff, list):
            raise ValueError("fridge_foods 必须是数组或 null")
        items = []
        for i, f in enumerate(ff):
            if not isinstance(f, dict):
                raise ValueError("fridge_foods[%d] 必须是对象" % i)
            ic = str(f.get("icon") or "")
            if ic not in FOOD_ICONS:
                raise ValueError("fridge_foods[%d].icon=%r 不在白名单里（只能是 %s）"
                                 % (i, ic, "/".join(FOOD_ICONS)))
            items.append({"x": _num(f.get("x"), "fridge_foods[%d].x" % i),
                          "y": _num(f.get("y"), "fridge_foods[%d].y" % i),
                          "icon": ic})
        ov["fridge_foods"] = items

    # ---- spawn（露娜起点，单实例）----
    sp = data.get("spawn")
    if sp is not None:
        if not isinstance(sp, dict):
            raise ValueError("spawn 必须是对象或 null")
        lu = sp.get("luna")
        if lu is None:
            raise ValueError("spawn.luna 不能为空（这是单实例字段）")
        if not isinstance(lu, dict):
            raise ValueError("spawn.luna 必须是对象")
        ov["spawn"] = {"luna": (_num(lu.get("x"), "spawn.luna.x"),
                                _num(lu.get("y"), "spawn.luna.y"))}

    # ---- mw_patrol（微波炉巡逻段，单实例）----
    mp = data.get("mw_patrol")
    if mp is not None:
        ov["mw_patrol"] = _pair(mp, "mw_patrol", strict=True)

    # ---- nest（窝区，单实例）----
    ns = data.get("nest")
    if ns is not None:
        ov["nest"] = _pair(ns, "nest", strict=True)

    # ---- border_x（关卡边界，单实例）· ⭐⭐ PR23 ----
    #   ⛔⛔ **只认 v4**：v1/v2/v3 的文件里出现 `border_x` 键时**必须忽略**，
    #      否则手改老文件就能改关卡边界 —— 那会让"v3 的语义"漂移。
    if ver == TERRAIN_JSON_VERSION_V4:
        _bx = data.get("border_x")
        if _bx is not None:
            ov["border_x"] = _num(_bx, "border_x")

    # ⭐ 没出现的键**一律不写进 dict**（而不是写 None）——
    #   因为 Room 要靠"键在不在"区分「不覆盖」与「显式设为空」。
    return ov

# ⭐ 冰箱（贴右墙，独立段）—— 2026-10-04 从「茶几正后方」挪到这里，与茶几完全错开。
#   x 1120~1250（宽 130px ≈ 39cm，单门冰箱），顶 50（高 549px ≈ 166cm ≈ 1.8m 标称）
#   ⭐ 底 = FLOOR_Y(599)：冰箱**落地实心** → 它左边的地板才是微波炉巡逻段的东端尽头。
#   ⭐ 挪右墙后 _at_fridge 回到最自然的语义：「站在冰箱正前方的地板上」，
#     不再需要「站上茶几桌面」这个由遮挡逼出来的 hack。
FRIDGE = {"x": 1120, "y": FLOOR_Y, "w": 130, "h": 549}
# ⭐⭐⭐ 2026-10-10 Ronny 拍板：**冰箱也不要了**。
#   ⛔ **为什么用开关而不是删代码**：FRIDGE 在 8 处被活引用（墙判定 / QTE / 伪平台落点 /
#      微波炉巡逻右端 / 绘制 / 冰箱食物 / 编辑器放置校验），全删会连带打翻一堆判据。
#   ⛔ **为什么不用 w/h = 0**：那样判定会退化成「x 到 x 的零宽区间」⇒ 变成一堵隐形墙，
#      比留着冰箱更难排查。
#   ⇒ 开关 = 冰箱**整体不存在**（不画、不撞、不放东西、不参与巡逻右端）。
FRIDGE_ENABLED = False
# ⭐ 冰箱里的东西（比地面容器多）—— 高风险高回报：它就在微波炉巡逻段的东端尽头
#   坐标是**冰箱内部格子**（按新冰箱 x1120~1250 重排，不再压在茶几布幔上）
FRIDGE_FOODS = []   # ⭐⭐ Ronny 2026-10-10 授权：容器全清

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
                            #   下端 300 → 310（抓毯区间 [222,320] 稳稳吃进 —— 旧值 300 只差 2px，很脆）。
                            #   ⭐⭐ **实测数据（2026-10-05 verifier 独立复核，推翻旧结论）**：
                            #     · 夜间跳跃速度 JUMP_V=920、GRAVITY=2000 ⇒ 跳高 211.6px
                            #       （离散积分实测 204.00px）
                            #     · 从挂毯顶 y=232 起跳 ⇒ 可上吊柜【顶面 y=50】，
                            #       实测 5/7 种操作站稳 15 帧
                            #       （原地跳 / 长按 / 小幅横移都行；
                            #        ⛔ 左或右按 30 帧会飞出 x 范围落到台 y=380）
                            #     ⛔ **旧注释「厨房台顶 397 起跳到 193 → 吊柜底 189 差 4px 上不去」是错的**：
                            #       那个 193/204 是**桌宠主程序**的值，不是夜间关卡的。
                            #     ⭐ **挂毯的真正作用**：把「台 380 → 柜 50」这 330px 拆成
                            #       191px（台380→毯232）+ 182px（毯232→柜50），两段都在 204px 内。
                            #       ⛔ 没有挂毯时，玩家在台面直接跳要够 330px > 204px，**上不去**。
                            #       ⇒ 这是"必须保留挂毯"的真正硬理由，**不是 4px**。
]

# ⭐⭐ 攀爬面（2026-10-03「桌子地形很奇怪」修复）：桌布是**全覆盖垂到地**的整面布，
#   不是一根杆 —— 整面（470~730 × 488~599）都应该能扒着往上爬。
#   同时这面布对地面行走是**实心墙**（见 Luna.update 里的布墙判定），
#   ⛔ 不能再让她从桌布里面穿过去 —— 背景板里布是垂到地的，穿模一眼假。
#   冰箱（1120~1250）已挪到**右墙独立段**，与茶几（430~700）完全错开——
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
    {"x": 1000, "y": FLOOR_Y, "icon": "blueberry", "kind": "loose"},  # 地板·冰箱前（绕后拿）
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
#   · 后摇 0.42s = 惩罚连打；这段时间还能微调方向但跑不开
#     ⭐ 2026-10-05 Ronny 拍板 0.26 → **0.42**：合计 0.16+0.09+0.42 = **0.67s**，
#       正好够美术端的 16 帧 pingpong（8 个姿态正放 = 8/12 = 0.667s）播完。
#       ⛔ 旧值 0.26 ⇒ 合计 0.51s ⇒ **第 5 帧「右爪横扫」永远播不到**，
#       而验收线要靠那一帧证明"不是拳击手" ⇒ 动画比动作短，自相矛盾。
#   · 冷却 0.12s = 在后摇之后，让"打空一下"有明确的手感断点
# ⛔ 只改 ATK_REC：前摇/命中的时序已对上手感，⛔ 别动 ATK_WIND / ATK_ACT。
ATK_WIND     = 0.16
ATK_ACT      = 0.09
ATK_REC      = 0.42
ATK_CD       = 0.12
# ⭐ 攻击范围（身前单向）：62px。比容器的 hit 半径(46~54)宽 ——
#   玩家不需要贴到像素级才打得到，但要够不到"隔着台面"的容器。
ATK_REACH    = 62.0
# ⭐ 攻击能打到的垂直容差：56px（够覆盖同层和上下层台面差 91px 的一半 → 同层才行）
ATK_DY       = 56.0
# ⭐ 击退参数：够把他推开一段，但⛔ 不能推穿墙（clamp 会兜住）
ATK_KNOCK    = 260.0
ATK_STUN     = 0.45         # 硬直 0.45s ≈露娜能拉开 135px

# ============================================================================
# PR14 · 攻击三档（点按 / 蓄力 1 / 蓄力 2）—— Ronny 2026-10-09 18:52 拍板
# ============================================================================
# ⛔⛔ **`ATK_HINT` 与 `ATK_CHARGE1` 必须是两个数**（0.30 vs 0.35）：
#    0.30 = **视觉提示点**（粒子变红），0.35 = **出招判定点**。
#    这 0.05s 就是给玩家的「看到红色了，再按一下就到第二档」的时间差。
#    ⛔ 混用成一个阈值 ⇒ 出现"看到红了但松手没出招"的别扭手感（判据 ⑬ 专测这条）。
ATK_HINT= 0.30            # 粒子由白转红
ATK_CHARGE1     = 0.35           # 蓄力 1 出招
ATK_CHARGE2     = 0.70           # 蓄力 2 出招
# ⭐ 击退分档（Ronny 拍板 +20% / +30%）。⛔ 不覆写 ATK_KNOCK，只新增。
ATK_KNOCK1     = 312.0           # = 260 × 1.2
ATK_KNOCK2     = 338.0           # = 260 × 1.3
# ⚠️⚠️ **Ronny 要我提醒的事（不改数值，只报）**：
#   312 与 338 只差 **26px（8%）** ⇒ 蓄力 1 与蓄力 2 的**击退手感很可能分不出来**。
#   ⇒ ⭐ **红/蓝粒子才是主要区分手段**，击退差距只是辅助。
#   ⇒ ⛔ 若实测发现分不出来，⛔ 别自己拉大数值，回传报设计端。
# ⭐ 档位编号（⛔ 别用 0/1/2 混着当充能秒数用）
ATK_TAP, ATK_C1, ATK_C2 = 0, 1, 2
# ⭐ 三档的击退查表：索引 = 档位号。⛔ 别在消费点写 if/else 挑常数。
ATK_KNOCK_TABLE = (ATK_KNOCK, ATK_KNOCK1, ATK_KNOCK2)
# ⭐ 特效生命周期（秒）。三档不同：档越高冲击越持久。
FX_DUR = (0.16, 0.22, 0.30)
# ⭐ 刀光弧数（三档）。Ronny：普攻 1 道、蓄力 2~3 道。
FX_CLAW_N = (1, 2, 3)
# ⭐ 刀光颜色（普攻 / 蓄力1 / 蓄力2）。蓄力 2 偏紫，与"蓝粒子"呼应。
FX_CLAW_COLOR = ((235, 245, 255), (180, 240, 255), (236, 210, 255))
# ⭐ 蓄力 2 的"炸开"冲击色（暖金，§3.4）
FX_IMPACT_GOLD = (255, 205, 90)
# ⭐⭐ 蓄力粒子的三阶段（派单 §3.4 表）
#    (charge_t 下限, 颜色, 粒子数, 脉动幅度 px, 内圈半径 px)
FX_CHARGE_STAGES = (
    (0.00,           (235, 240, 245), 14, 1.0, 90.0),   # 聚拢中（白）
    (ATK_HINT, (245, 95,  85),  14, 2.4, 70.0),   # 蓄力1 就绪（红）
    (ATK_CHARGE2,     (95, 150, 245), 26, 4.0, 110.0),  # 蓄力2 就绪（蓝）
)
# ⭐ 效果列表上限（派单 §3.2：防连点刷屏）。超了丢最旧的。
FX_MAX = 24
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
MW_HEAR_R   = 240.0         # ⭐ 听觉半径（px）。
                             # ⛔⛔ 2026-10-05 Ronny 定「他应该安静呆着」后，由 420 收窄到 240。
                             #   ⭐ 理由（⚠️ 下面提到560 那个数字是**旧世界宽度**下的说法，别再照它推演）：
                             #     · 420 覆盖可活动区约 1/3 宽 ⇒ 你在房间任何地方敲一下他都听得到
                             #       ⇒ 位置管理作废（实测：站在他背后 61px 也会被察觉）
                             #     · 240 ⇒ 只有靠近他才听得见，潜行重新有意义
                             #   ⛔ 旧注释写「开到 560 就是全室都听见」——那是 1280px 宽世界下的估算；
                             #     在 3840px 地图里 560 只占 1/7。
                             #     程序端 10-05 报出此处数字不一致，判定正确
                             #     （引擎文件属程序端，设计端只报告不改）。
SNEAK_SPEED = 108.0         # 潜行速度（正常 300）—— 36%，与桌宠侧 sneak 的 stride 同比例

# ============================================================================
# ⭐⭐⭐ 待机（idle）—— Ronny 2026-10-05 定位拍板
#   原话：「他应该**安静呆着**，看到露娜干坏事就冲刺出来抓才是对的」
#   ⇒ 他从「一直在踱步的警卫」改成「**站岗的猫**：默认不动，被惊动才动」
# ============================================================================
# ⛔⛔ 为什么改（旧版的病根不是数值，是**默认状态**）：
#   旧版 `_patrol` 是"走 2.2s → 停 0.7s → 转身 → 走"的无限循环，
#   而 patrol 段 (820,1108) 恰好横跨整个禁区中段⇒
#   ① 玩家在禁区的容器 (660/820/900/1000) 四分之三落在他走动范围里
#   ② 他一直在动 ⇒ 玩家永远找不到"安全窗口"
#   实测：露娜在 x=1000 静止不动，1 秒内 alert 就拉满并 chase
#   （alert_gain=1.5/秒 ⇒ 0.67 秒满）⇒ 观感是「恐怖人机」。
# ✅ 新默认：他**不动**。只有两种情况会动——
#   ① 听到声音（investigate）→ 走过去看一眼 → 回来继续呆
#   ② 看见露娜进禁区（chase）→ 冲刺出来抓
# ⛔ 素材缺"待机"动作怎么办：**先不画**，逻辑上他站着不动就行。
#   玩法铁律「素材只管动作」不要求每个状态都有专属帧。
IDLE_STIR_P     = 9.0        # 待机时每隔多久「轻轻转头看看」（秒）
                              # ⛔ 别短于 8s：实测 5s 时20 秒内转头 10 次，
                              #   那不叫"站岗"，那叫"抽搐"。9s ≈ 玩家换一次位置的时间。
IDLE_STIR_TURN  = True       # ⭐ 待机的"踱脚"只转头，⛔ 不平移
                               # 理由：平移就变回"巡逻"了。猫站岗时会扭头，但不会挪窝。

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


# ⭐⭐ 2026-10-04 补 sneak：
#   ⛔ 漏了它的后果是**静默兜底** —— 绘制处写的 `self.imgs.get(l.act) or self.imgs["idle"]`，
#     拿不到帧就画 idle。所以「潜行」明明 pick_action 返回对了，画面上却是
#     一张站姿死图（Ronny：「潜行没实装」同一根因）。
# ⭐⭐⭐ **tease 已从这里移除（PR15，Ronny 2026-10-09：「tease 不应该在游戏里，
#   只是在桌宠里」）**：攻击演出改用 `assets_game/attack/` + `attack_charge/`。
#   ⛔ 别再把 attack 加进来 —— 它在 assets_game/（游戏专用），
#      `NEED_ACTIONS` 只喂 `_load_needed(pack, ...)`，那是**桌宠 packs**。
#      加进来 = 桌宠包里找不到它 = 又一次静默兜底画idle。
NEED_ACTIONS = ["idle", "walk", "human_run", "jump", "fall", "climb", "land",
                "sneak"]

# ---- 游戏专用素材（2026-10-03 派单 35 回传）----
# ⭐ 放在 自研引擎/assets_game/，不进 packs/ —— 微波炉不是桌宠角色，不该进桌宠包。
GAME_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets_game")
# ⭐ 夜间**覆盖**桌宠动作 fps 的地方。键 = 动作名（与 `pick_action()` 返回值同名）。
#   ⭐ 只列**游戏帧**槽（assets_game/）—— 桌宠动作的 fps 仍由 packs 自己的 anim 定，
#     ⛔ 别往这里加桌宠动作名（加了也不会被用上，只会让下一个人以为它生效了）。
# ⭐⭐⭐ PR15：`tease` 从这里**删掉**（Ronny：「tease 不应该在游戏里，只是在桌宠里」）。
#   ⛔ 删它的真实原因不是"不好看"，是**大小问题**（`s` 乘错了）：
#     tease 在 NEED_ACTIONS ⇒ 从桌宠 packs 加载 ⇒ 画布 640×640，
#     乘 s 之后角色高约 501px，而游戏帧是归一化后的 canvas 178（本体 132）
#     ⇒ **大 3.8 倍**。根因是**两张画布走了两条不同的缩放路径**，
#     不是数值没调好（详见 `_draw_luna` 里 attack 分支的注释）。
#   ⛔ 原来那段「15fps 是为 8 个攻击姿态」的注释（PR15 前）已随 tease 一起失效，
#     **已删除** —— 留着会误导下一个读代码的人去给桌宠动作调 fps。
#   ⭐ attack / attack_charge 都是 24.0 = 16 帧 / 0.667s，与 run_carry 同节奏。
GAME_FPS = {"mw_walk": 12.0, "run_carry": 24.0,
            "attack": 24.0, "attack_charge": 24.0}
# ⭐ 素材的**原始朝向**（+1 朝右 / -1 朝左），实测自素材本身，不是猜的：
#   mw_walk 素材朝左（能看到侧脸和制服前襟，尾巴在右后）→ -1
#   run_carry 素材朝右（脸朝右，鱼在右边的嘴里）    → +1
#   attack / attack_charge 素材朝右（PR15，与 run_carry 同源同朝向）→ +1
# ⛔ 之前写 `if face < 0: mirror` —— 那只在"素材朝右"时才碰巧正确。
#   微波炉素材朝左，所以它 face=1（该朝右）时**没被镜像**，等于拿屁股对着玩家（Ronny 实机反馈）。
#   ✅ 改成"和素材原始朝向不一致才镜像"，两套素材共用一条规则。
GAME_SRC_FACE = {"mw_walk": -1, "run_carry": 1, "attack": 1, "attack_charge": 1}

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
    {"x": 900,  "y": FLOOR_Y, "icon": "pumpkin",   "kind": "plate"},   # 地板·台下
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
    {"x": 830,  "y": FLOOR_Y, "icon": "blueberry",  "kind": "loose"},  # 地板：绕后拿
    {"x": 1060, "y": FLOOR_Y, "icon": "watermelon", "kind": "jar"},    # ⭐ jar（全图最深，冰箱脚下）
]

# ============================================================================
# ⭐⭐ 2026-10-05 Ronny 拍板：三档 → **只留一档（最难那档）**
#
# 保留的是原【凌晨三点】（`_NIGHT3`）—— 它在**所有维度**都最难：
#   听圈 180 / 视野 350 / 警戒增速 2.5 / 巡逻 120 / 边界 360（禁区最深）/ 容器 7 个
# ⇒ 难度不降反升，但玩家不用在三档里挑了。
#
# ⛔ **`sub` 的字我一个都没动**（设计端要求：等 Ronny 给「白天大中午偷」的新文案）。
#   ⛔ 所以现在这句「整层楼只有冰箱在响」在设定上**已经不成立**了（白天 + 环境音已删），
#     那是**已知待改**，⛔ 别当成"没人发现"。
#
# ⭐ UI 不用改：`len(NIGHTS)==1` 时菜单的上下键切换自然失效（正确行为），
#   `Key_1/2/3` 仍映射到同一档（见 keyPressEvent）。
# ⚠️ 但 `NightWindow.night_idx` 默认值**必须**从 1 改成 0 —— 否则启动就 IndexError。
# ============================================================================
NIGHTS = [
    {
        "name": "正午",
        # ⭐⭐ 2026-10-05 Ronny 20:44 亲自写的文案，**逐字用，⛔ 别改标点**：
        #   中间的「，」和末尾的「~」都是他特意写的。
        #   ⚠️ 末尾是**半角波浪号 `~`**（U+007E）—— Ronny 原话我没找到落盘文件，
        #      这是按设计端转述逐字落的。⏳ 若 Ronny 要的是全角「～」，
        #      只改这一个字符。
        "sub": "阳光正好，他在打盹。我来看看屋里有什么吃的~",
        "stashes": [],   # ⭐⭐ Ronny 2026-10-10 授权：容器全清，之后再说
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
        # ============ PR14 · 攻击三档 ============
        # ⭐ 蓄力中（按住 J 未达阈值）。⛔ 它是**表现层状态**，
        #   不是攻击计时 —— 真正的三段计时还是 atk_wind/act/rec。
        self.charging = False
        self.charge_t = 0.0          # 已蓄力秒数（0 ~ ATK_CHARGE2 封顶后锁住）
        self.atk_lvl = ATK_TAP# 本次出招的档位 0/1/2（决定击退与特效）
        self.atk_fired = False        # ⭐ 本次按住是否已出招（防连放，判据 ⑤）
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
        # ⭐⭐ 落地回调（2026-10-06 PR-06 接 `sfx_land` 用）。
        #   ⛔ Luna 自己**不import audio、不拿窗口对象**（同 `sneak_ok` 的纪律：
        #     物理层不依赖音频层，打包漏 QtMultimedia 时也照样能跑）。
        #   ✅ 由 `NightWindow.start_night` 注入一个函数，物理层只在
        #     「空中 → 落地」那**一帧**喊它一声（见 `update` 里的落点判定）。
        self.on_land = None

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
            # ⭐⭐ PR24：布墙改**跟着地形走**（⛔ 原来读 TABLE_X0/X1 常量 ⇒ 删了地形照样撞）
            _w = table_wall_span(room)
            if _w is not None and self.y > _w[2] + LAND_TOL:
                m = BODY_W * 0.35
                _wx0, _wx1 = _w[0], _w[1]
                _hit = lambda px: px + m > _wx0 and px - m < _wx1
                if _hit(self.x) and not _hit(prev_x):
                    self.x = (float(_wx0 - m) if prev_x < _wx0
                              else float(_wx1 + m))
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
        # ⭐ punch 只是"播挥击动作（attack / attack_charge）"的计时，与三段并行递减
        #   （它没有阶段转移，所以放在这里减是对的）。
        #   ⛔ 别把 punch 当攻击计时用 —— 它是表现层。
        #   ⚠️ PR15：原文写的是「播 tease」，tease 已下线（只在桌宠里）⇒ 已更正。
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
        # ⭐⭐ PR24：布墙改**跟着地形走**（⛔ 原来读 TABLE_X0/X1 常量 ⇒ 删了地形照样撞）
        #   ⛔ y 条件与 x 区间**都**来自 `_w`，⛔ 不留 TABLE_TOP 半截旧逻辑（派单 §2.2）
        _w = table_wall_span(room)
        if _w is not None and self.y > _w[2] + LAND_TOL:
            _wx0, _wx1 = _w[0], _w[1]
            _hit = lambda px: px + m > _wx0 and px - m < _wx1
            if _hit(self.x) and not _hit(prev_x):
                self.x = float(_wx0 - m) if prev_x < _wx0 else float(_wx1 + m)
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
        # ⭐⭐ PR25（2026-10-10）：FRIDGE_ENABLED=False ⇒ **没有冰箱墙**。
        #   ⛔ 下面整段必须**真跳过**，不能把 w 改成 0 ⇒ 那会变成一堵「隐形墙」。
        _fx0, _fx1 = 0.0, 0.0
        _fy_top = FLOOR_Y - FRIDGE["h"] if FRIDGE_ENABLED else 1e9
        if _fy_top + LAND_TOL < self.y < FLOOR_Y + LAND_TOL \
                and _fx0 <= self.x <= _fx1:
            self.x = float(_fx0 - m) if self.x - _fx0 < _fx1 - self.x else float(_fx1 + m)
            if abs(self.vx) > 1.0:
                self.vx = 0.0
        # ⭐ 冰箱顶的落点**不能在这里单独结算** —— 下面第 828 行有 `self.on_ground = False`，
        #   单独结算会被无条件抹掉（踩过：判据看着对，人还是往下穿）。
        #   ✅ 所以冰箱顶走"伪平台"路线：塞进下面那个落点循环，一起参与"取最高"的比较。

        # ⭐⭐ 2026-10-06 PR-06：落地音只在「**空中 → 落地**」这一帧响一次。
        #   ⛔⛔ 别在下面 `on_ground = True` 那一行**无条件**触发：
        #     `on_ground` 在**站着不动时每帧都会被重新判成 True**
        #     （这正是上面那个判据的写法——它必须这样才能解决"站着时隔帧抖"），
        #     无条件触发 ⇒ 站着不动就一直重播 0.35 秒的落地音，糊成一片。
        #   ⇒ 所以先把"这一帧开始时是不是已经站在地上"存下来，只在**由虚转实**时喊。
        #   ⚠️ 存的位置在爬梯分支**之后**：爬梯到顶/踩上沿那几处也会把 on_ground 置 True，
        #     于是它们天然被排除 ⇒ 爬梯落地**不响**落地音（派单明确要求）。
        was_ground = self.on_ground
        self.on_ground = False
        if self.vy >= 0:
            # ⭐⭐ 单向平台落地的正确写法。踩过的两个坑：
            #   ① 只判"这一帧穿过了顶面"（prev_y <= y0 <= y）→ **已经站在平台上时会漏检**，
            #      因为贴着顶面时根本没有"穿过"这回事 → 角色在 y0↔y0+1.6 之间隔帧抖。
            #      ✅ 改成"上一帧还在顶面上方（含站着）+ 这一帧到了顶面下方"。
            #   ② 按 platforms 的书写顺序取第一个命中 → 高速下落时会穿过料理台直接落地板。
            #      ✅ 改成取【最高】的那个（y0 最小）—— 才是真正先碰到的那层。
            hit = None
            hit_plat = None
            for _p in room.platforms:
                # ⭐ PR12：读 dict（`plat_fields` 同时吃 4 元组 ⇒ 旧数据/自测塞元组也不崩）
                x0, y0, x1, y1 = plat_fields(_p)
                if not (x0 - BODY_W * 0.35 <= self.x <= x1 + BODY_W * 0.35):
                    continue
                # ⭐⭐ PR12「碰触后短暂消失」：已触发的 brittle **不参与落地判定**
                #   ⇒ 她会自然往下掉（派单 §4.1② 的原话就是这个意思）。
                #   ⛔⛔ **禁止改成「边沿触发」**（上一帧不挨、这一帧挨）：
                #   平台很窄时会漏检 —— MEMORY 里冰箱那次已栽过
                #   （实体宽度只有身体半宽 1/6 时边沿判据必然漏）。
                #   ⛔⛔ **禁止「恢复时把角色钉回平台」**：她可能已经走到别处了。
                if plat_kind(_p) == "brittle" and not room.brittle_active(id(_p)):
                    continue
                if prev_y <= y0 + LAND_TOL and self.y >= y0:
                    if hit is None or y0 < hit:
                        hit = y0
                        hit_plat = _p
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
                # ⭐⭐ PR12「碰触后短暂消失」①：踩上去的**那一帧**标记已触发 + 计时器归零。
                #   ⛔ 放在 `on_ground=True` 之后、无条件触发（不是「由虚转实」时）：
                #     brittle 的语义是「碰触就消失」，站着不动也会在恢复后再次消失 ——
                #     这正是待拍板 Q1 想决定的点，当前取「不能站上去」⇒ 只触发一次，
                #     触发后计时器跑完就恢复，恢复后再站上去会**再次**触发。
                if hit_plat is not None and plat_kind(hit_plat) == "brittle":
                    room.brittle_touch(id(hit_plat))
                # ⭐ 落地音（PR-06）。**全场唯一接 `sfx_land` 的地方**。
                #   ⛔ 爬梯那三处（爬到台面沿/爬到顶/爬到底）⛔ 不接——
                #     它们不走这个落点判定，且派单明确要求"爬梯落地不响"。
                #   ⛔ 阈值 `not was_ground`：站着不动时 `on_ground` 每帧都为 True，
                #     不看这个就会每帧重播。
                if not was_ground and self.on_land is not None:
                    self.on_land()

        self._clamp_x(room)
        self.moving = abs(self.vx) > 1.0 or abs(self.vy) > 1.0
        if self.y > VH + 200:                            # 掉出世界（不该发生，兜底）
            # ⭐⭐⭐ PR13：读 room.spawn_luna（Luna.update 拿不到 window，只能读 room）
            #   ⛔⛔ **不做夹取**（Q13 裁定）：夹取要回答"哪里能站"，
            #     那是把落地判定逻辑复制一遍，且会与 `_clamp_x` 打架。
            #   ⭐ 默认 `room.spawn_luna = (NEST_X0+70, FLOOR_Y) = (80, 599)`
            #     ⇒ 与旧写法 `NEST_X0+70, FLOOR_Y` **逐字相同**。
            self.x, self.y = room.spawn_luna
            self.moving = False

    def _clamp_x(self, room):
        # ⭐⭐ 2026-10-05 PR-03：夹的是**世界宽**，不再是视口宽。
        #   旧版夹 VW(=1280) ⇒ 露娜永远走不出1280，3840 的世界对她等于不存在。
        #   ⛔ 边距沿用原来的 +8（贴边留一点，别让身体切在屏幕上）。
        half = BODY_W * 0.5
        world = float(getattr(room, "world_w", WORLD_W) or WORLD_W)
        self.x = max(half + 8.0, min(world - half - 8.0, self.x))

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
    def can_attack(self) -> bool:
        """三道闸门能不能过？⇒ bool（⛔ 不产生任何副作用，纯查询）。

        ⭐ PR14 把它从 `try_attack` 里**拆出来**是为了「按住 J 开始蓄力」时
           也得先问一遍能不能攻击 —— 否则会出现「冷却中按住 J，
           冷却转好后自动放招」这种玩家没主动按却打出的一招。
        ⛔ 纯查询：⛔ 不许在这里动任何状态。
        """
        if self.atk_cd > 0.0:
            return False
        if self.atk_wind > 0.0 or self.atk_act > 0.0 or self.atk_rec > 0.0:
            return False
        if self.dash_t > 0.0:
            return False
        return True

    def try_attack(self, lvl: int = ATK_TAP) -> bool:
        """起手一次攻击。返回是否成功起手。

        ⭐ 三道闸门，任一不满足就**静默拒绝**（不给提示）：
          ① 冷却没转好   ② 已经在攻击中（三段任一段都在跑）
          ③ 冲刺中（冲刺独占）
        ⛔ 不检查"够不够得到目标" —— 那是命中窗口的事。
          在这里判"够不到就不播"会让玩家按了没反应，以为按键坏了。

        ⭐⭐ PR14 新增 `lvl`（0=普攻 / 1=蓄力1 / 2=蓄力2）：
           ⛔ 默认值 ATK_TAP ⇒ **老调用方（`:3265` 原来的 `try_attack()`）
              行为逐字不变** —— 这是「默认行为不变」的实现方式：
              加参数而不改签名语义，别把默认值设成蓄力 2。
           ⭐ 档位存进 `self.atk_lvl`，命中结算时按它取击退。
        """
        if not self.can_attack():
            return False
        _lv = int(lvl)
        if _lv not in (ATK_TAP, ATK_C1, ATK_C2):
            raise ValueError("攻击档位只能是 ATK_TAP/ATK_C1/ATK_C2，收到 %r" % (lvl,))
        self.atk_lvl = _lv
        self.atk_wind = ATK_WIND
        self.atk_act = 0.0
        self.atk_rec = 0.0
        self.atk_hit_done = False
        # ⭐ 命中帧才生成冲击特效 ⇒ 由窗口层在 `_resolve_attack_hit` 里 spawn，
        #   这里**不生成**（普攻挥空不该有冲击波）。
        self.punch = ATK_WIND + ATK_ACT + ATK_REC   # ⭐ 挥击演出的时长（PR15：动作是 attack/attack_charge，不再是 tease）
        return True

    def try_dash(self, dir_in: int) -> bool:
        """起手一次冲刺。dir_in = 1 右 / -1 左 / 0 = 沿当前朝向。"""
        if self.dash_cd > 0.0 or self.dash_t > 0.0:
            return False
        # ⛔ 攻击三段期间不能冲刺（两个都是"决定"，不能同时做）
        if self.atk_wind > 0.0 or self.atk_act > 0.0 or self.atk_rec > 0.0:
            return False
        # ⭐⭐ PR14：**蓄力期间也不能冲刺**（判据 ⑭-7c 抓出来的真 bug）。
        #   ⛔ 为什么必须挡：蓄力是一个"决定"（她正聚力），冲刺是另一个。
        #     两者同时成立 = 玩家按住 J 再按 D 会"一边蓄力一边冲"，
        #     蓄满后还在冲刺位移中出招 ⇒ 击退起点和她的位置错开，手感全乱。
        #   ⚠️ 这条**不在**上面那三个检查里 —— 那三个查的是「已经出招」，
        #     蓄力时atk_wind/act/rec 都还是 0 ⇒ 不加这条就会漏过去。
        if self.charging:
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
        # ⭐⭐⭐ PR15：攻击演出改走**游戏帧槽**（attack / attack_charge）。
        #   ⛔ 原来这里返回 "tease"，而 tease 在 NEED_ACTIONS ⇒ 从桌宠 packs 加载
        #     ⇒ 画布 640×640，乘 s 之后角色高约 501px（正常是 132px）⇒ **大 3.8 倍**。
        #     这就是 Ronny 说的「大小问题又复发」的**根因**：不是数值没调好，
        #     而是**两张画布走了两条不同的缩放路径**。
        #   ⭐ 蓄力中也用 attack_charge：那段素材本身就是「拉弓 → 释放」，
        #     蓄力时看到拉弓、命中时看到出招，**视觉上正好对应蓄力机制**。
        #⛔ 别把 punch 顶起来当蓄力计时（punch 是"已出招"的计时，
        #     拿它当蓄力指示会让出招时机算错—— PR14 已踩过这个坑）。
        if self.charging:
            return "attack_charge"
        # ⭐ 挥击优先（Ronny 10-03 反馈「露娜还是不会攻击」）：
        #   根因是 pick_action 只看移动状态 —— 她**站着不动**时按 E 根本不切动作。
        #   ⛔ 而不是"没有挥击素材"。
        if self.punch > 0.0:
            # ⭐ 蓄力 2 用 attack_charge（它含"释放"那一下），其余两档用 attack
            return "attack_charge" if self.atk_lvl == 2 else "attack"
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
# ---------------------------------------------------------------------------
# PR14 · Effect —— 一次性攻击特效的**唯一收口点**
# ---------------------------------------------------------------------------
# ⭐ 为什么单独一个类：攻击特效有三种（刀光/冲击/蓄力粒子），
#   它们共享"进度 t: 0→1、播完就死"的语义 ⇒ 抽出来，
#   ⛔ 别在 NightWindow 里散落五个 self.fx_xxx 变量 —— 那样移除逻辑要写五遍，
#   漏一处就是特效永远留在屏幕上（内存泄漏 + 画面糊住）。
#
# ⭐⭐ `t` 是**归一化进度**（0~1），不是秒：
#   因为三种特效的时长不同（FX_DUR 三档），画法全按 t 写才不用到处乘dur。
#
# ⚠️ `kind="charge"` 的特殊约定（派单 §3.4）：
#   它是**持续**效果（按住 J 期间一直播），⛔ 不像 claw/impact 那样播完就死。
#   ⇒ 它的 `t` **不是**自己的进度，而是**全局蓄力进度 charge_t**（由外部每帧写）。
#   ⚠️ 阶段切换时⛔ 绝不重置它（否则粒子会跳一下）。
class Effect:
    """一次性攻击特效。⚠️ 每个实例只用一次（不复用），播完从列表移除。

    ⭐ `__slots__`：攻击特效每帧可能新建多个实例（有 GC 压力），
       不给实例配 `__dict__` 能省内存也省一点分配时间。
    """
    __slots__ = ("kind", "x", "y", "t", "dur", "facing", "r", "color",
                 "lvl", "_dead")

    def __init__(self, kind, x, y, dur, facing, r, color, lvl=ATK_TAP):
        self.kind = kind      # "claw" | "impact" | "charge"
        self.x = float(x)# 世界坐标
        self.y = float(y)
        self.t = 0.0          # 进度 0~1
        self.dur = max(1e-6, float(dur))
        self.facing = 1 if facing >= 0 else -1
        self.r = float(r)     # 基础半径（按档位给不同的值）
        self.color = color    # RGB 元组（不是 QColor：跨层传引用更省）
        self.lvl = int(lvl)   # ⭐ 档位 0/1/2 —— 画法按档分（弧数/粒子数/颜色）
        self._dead = False

    def update(self, dt) -> bool:
        """推进一帧。⇒ 还活着吗（False 就该被移除）。

        ⭐⭐ **charge 是唯一不靠自己的 t 判死的**：
           它按外部写入的 charge_t 决定阶段，由调用方在 charge 结束时移除。
           ⇒ 这里对 charge 返回恒 True，否则按住 J 时粒子会在 0.30s 处凭空消失。
        """
        if self.kind == "charge":
            return True
        self.t += dt / self.dur
        if self.t >= 1.0:
            self.t = 1.0          # ⭐ 钉住：画法里要能用 t=1 收尾，不许溢出
            self._dead = True
            return False
        return True

    @property
    def dead(self) -> bool:
        return self._dead


class Microwave:
    """⭐ 设定：它追露娜【不是】为了护着 koko，是为了维护秩序 ——
    它认为每只猫都该待在自己的区域里。所以它不会"攻击"，只会"押送回去"。

    灰盒表现：一个深色方块 + 门缝里透出的一道橙光（朝向就是那一面）。
    """

    def __init__(self, cfg: dict, patrol=None):
        # ⭐⭐⭐ PR13：patrol 从参数进来，**不再直接读 cfg**。
        #   ⛔⛔ 为什么要改（派单 §1.3）：
        #     原来 `p0, p1 = cfg["patrol"]` ⇒ 起点 = 巡逻段中点。
        #     若只把 self.x 设成 3000 而 patrol 还是 (760,1108)，
        #     他一巡逻就走回去了 ⇒ **等于没改**。
        #   ✅ 所以本单做「巡逻段」工具：p0/p1 由 room.mw_patrol 给，
        #     起点自动 = 中点，两者**永远一致**（不可能脱节）。
        #   ⭐ 默认 patrol=None ⇒ 落回 `cfg["patrol"]` ⇒ 与改动前**逐字相同**。
        #   ⛔ `self.y = FLOOR_Y` 硬编码**本单不动**（派单 §1.3 明确）。
        _pat = patrol if patrol is not None else cfg["patrol"]
        p0, p1 = _pat[0], _pat[1]
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
        # ⭐⭐⭐ 2026-10-05 P0：他会移动的**世界宽**（不是视口宽）。
        #   病根：investigate 的三处夹取写的是 `VW - w/2 - 8`（= 1224），
        #   而世界是 3840 ⇒ 他能去查看的范围只有 [56, 1224] = 世界的 30%，
        #   C/D/E/F 四个区（1440~3840）里的容器他**永远走不过去**。
        #   ⛔ 同一条路径上的 `_chase` 当时**完全没有夹取** ⇒ 他能为露娜追到 x=3000，
        #     却不会为一声响走到 x=1300 —— 同一个守卫两套活动范围，自相矛盾。
        #   ✅ 与 Room.world_w / Luna._clamp_x 同一套口径（同为"谁改了都有处可查"的显式字段）。
        #   每帧由 update() 从 room 同步 ⇒ room 是唯一真源，这里只是缓存。
        self.world_w = float(WORLD_W)
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
        # ⛔ 2026-10-05：walk_t/dir 随巡逻一起退役（待机不动了）。
        #   保留字段是因为别处还在读（_investigate 末尾要清它们，见该方法不变量③）。
        self.walk_t = 2.0
        self.pause_t = 0.0
        # ⭐⭐ idle_t：待机时距离下一次「扭头看看」还有几秒（Ronny「安静呆着」）
        # ⭐ 初始相位取一半（不是 0）：让"第一次转头"发生在 4.5s 而不是 0s，
        #   否则玩家开局就看到他猛地扭头，突兀。
        self.idle_t = IDLE_STIR_P * 0.5
        # ⭐⭐ idle_home：他**站岗的位置**。investigate 看完要回到这里，
        #   而不是继续巡逻（旧版没有"回家"这个概念，investigate 结束就回巡逻循环）。
        #   ⛔ 记成 float 一次即可：他站着不动 ⇒ 站位不变 ⇒ 不需要每帧更新。
        self.idle_home = float((p0 + p1) * 0.5)
        # ⭐ 回程标志：investigate 看完 ⇒ True ⇒ 走向 idle_home 且到位不环顾
        self._go_home = False
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

    def _clamp_self_x(self):
        """⭐⭐ 把**自己**的 x 夹进可活动区 `[体型半宽+8, 世界宽-体型半宽-8]`。

        ⭐⭐⭐ 2026-10-05 P0 新增（`VW` → `WORLD_W`）。
        ⛔⛔ 原来的三处夹取各写一份 `min(VW - half - 8.0, ...)`，那是**视口宽**。
          世界宽已是 3840（PR-03）而视口仍是 1280 ⇒
          他能去 investigate 的范围被锁死在 [56, 1224]，只占世界 30%。
        ⭐ 收成方法而不是就地改三处：这三处**同一天里被漏改过两次**
          （`_clamp_x` 改了、investigate 没改；本单又差点只改其中一处）。
          一份实现 = 以后漏改无处可藏。
        """
        half = self.w * 0.5 + 8.0
        self.x = max(half, min(self.world_w - half, self.x))

    def _clamp_target_x(self, at_x: float) -> float:
        """⭐ 把**声源x** 夹进可活动区（2026-10-05 P0：`VW` → `WORLD_W`）。

        ⚠️ 与 `_clamp_self_x` 分开是因为**夹的对象不同**：
           自己的 x 夹的是"体型不许出界"，声源 x 夹的是"目的地不许出界"。
           两者半宽口径恰好相同（都用 `w*0.5+8`），但语义不同，别合并成一个。
        """
        half = self.w * 0.5 + 8.0
        return max(half, min(self.world_w - half, float(at_x)))

    def sense(self, luna) -> float:
        """返回察觉强度：1.0 正面看见 / 0.4 背后听见 / 0.0 毫无察觉

        ## ⬝⬝ 2026-10-05 Ronny 定位：他是「站岗的猫」，不是扫描仪
        # 改动点（实测旧版的问题）：
        #   旧：背后只要 ≤hear(110~180) 就返回 **0.5**，而 alert_hear 是 0.8~1.3/秒
        #       ⇒ 站在他背后 60px，一秒内 alert 就满 ⇒ 「多管闲事」
        #       实测：x=1000 静止不动、他在 760，1 秒后 alert=1.00 state=chase
        #✅ 新：背后听见降级为 0.25，且要求**更近**（hear × 0.7）
        #   ⚠️⚠️ 2026-10-05 实测修正（verifier 扫 181 个进入相位，**0 个安全**）：
        #     「站他背后」的存活时间只有 **0.42 ~ 1.27 秒**
        #     （初更 0.93 / 深夜 0.77 / 凌晨三点 0.58 平均）。
        #     ⛔ 所以它【不是可 sustain 的安全区】，
        #       而是「必须主动管 x 进出的一次性掩体」。
        #   机制：背后 sense=0.25 ⇒ 慢速涨（涨满需 3~5 秒）；
        #     但他**每 9 秒转一次 face（IDLE_STIR_P）**，转到朝你时 sense=1.0
        #     ⇒ 满速涨（0.4~0.7 秒涨满）。
        #     ⇒ 玩家等不到"慢慢涨满"就会被抓到。
        #   ⭐ 真正永久安全的站位是【听圈外】（距离 > hear × 0.7，sense 恒 0.0）。
        #   ⚠️ 旧注释说「背后安全区变大」—— 那只描述了 s 从 0.5 降到 0.25 这件事，
        #     ⛔ 没有说明"转脸"这个 9 秒周期才是真正的死因 ⇒ 那句话会误导。
        #
        # 正面看见也加了距离衰减（近处 1.0 → 视野边缘 0.75）：
        #   ⛔ 别删——旧版是「视野内一律 1.0」，意味着他在 240px 外和20px 内
        #     察觉速度完全一样 ⇒ 那不是"看见"，那是"雷达锁定"。
        #   保留：dist 0 → 1.0, dist = sight*0.6 → 1.0，之后线性降到 0.75。
        #   ⭐ 意义：玩家贴着他走过去比隔着一段距离更危险 ⇒ 位置管理有了"贴近换时间"的取舍。
        """
        # ⭐ 梯子上 = 相对安全（抄 Lode Runner：守卫不追到玩家所在的梯格）。
        #   0.3 ⇒ 爬梯不是绝对安全，但能拖住你。
        if luna.on_ladder:
            return 0.3
        dx = (luna.x - self.x) * self.face      # 正 = 他面朝的方向
        dy = abs(luna.y - self.y)
        if dy >= MW_SIGHT_DY:
            return 0.0
        if -20.0 <= dx <= self.sight:
            # ⭐ 正面视野：近处满值，视野边缘衰减到 0.75（见 docstring）
            far = dx / self.sight
            return 1.0 if far < 0.6 else (1.0 - 0.25 * (far - 0.6) / 0.4)
        # ⭐ 背后听见：**更近 + 更弱**（旧版：≤hear 就 0.5）
        if abs(luna.x - self.x) <= self.hear * 0.7:
            return 0.25
        return 0.0

    def update(self, dt, luna, room):
        # ⛔ 越界才追：露娜退回允许区内，微波炉就当没看见 —— 这是"允许区机制"的核心
        trespass = luna.x > room.border_x and not luna.escort
        # ⭐ P0：可活动区跟着 room 走（room 是唯一真源，这里只是每帧同步缓存）。
        #   ⛔ 别在这里 clamp x —— chase 路径本来就没有夹取（能追到世界任何地方），
        #     夹了反而会把"追人跑全图"的行为改掉。只同步宽度。
        self.world_w = float(getattr(room, "world_w", WORLD_W) or WORLD_W)

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
            # ⚠️⚠️ 2026-10-06 实测澄清（**不是 bug，是设计现状，别"顺手修"**）：
            #   这一支的涨速恒为 `alert_hear`，**没有乘 `sense`**。
            #   实测（`_dbg_PR06判据根因.py` ①-b）：
            #     背后  60px  sense=0.25  每帧 0.0217   ← 涨
            #     背后  90px  sense=0.25  每帧 0.0217   ← 涨
            #     背后 120px  sense=0.25  每帧 0.0217   ← 涨
            #     背后 126px  sense=0.00  每帧 0.0000   ← 听不见
            #   ⇒ `sense` 在这一支里只当**开关**用（0.25 与 1.00 涨得一样快）。
            #   ⇒ 另一条配套事实：**背后档的有效门槛 = `hear × 0.7`**
            #     = 180 × 0.7 = **126px**，127px 起完全听不见。
            #   ⛔ Ronny / 设计端 2026-10-06 已拍板：**保持现状**。
            #     真要按强度加权 ⇒ "背后贴着"就和"正面看到"涨得一样快，
            #     潜行压力上升 ⇒ 那是**玩法变更**，不是修 bug。
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
                # ⭐ P0：夹取收进 `_clamp_target_x`（`VW` → `WORLD_W`）。
                #   ⛔ 这里不再自己写一份 `min(VW - half - 8, ...)`。
                _hx = self._clamp_target_x(self.hear_x)
                # ⬝⬝⬝ 2026-10-05 修一个实测到的抖动（新改动引入）
                #   病征：声源离他很近时，invest_x 等于他的位置
                #   → `_investigate` 判定「已到位」立即结束 → invest_x 变 None
                #   → 下一帧条件①再次成立（invest_hold 还在）
                #   ↳ 它在 964 / None 之间**逐帧闪烁**，位置不动。
                #   实测：距离 64px 的声音得到 invest_x=None（被判为没事发生）。
                # ✅ 修法：**声源已在脚下就不走过去看**——已经在位置上了。
                #   他会把头转向声源（下面那口代码负责），但不会“走到自己脚下再忽略一次”。
                if abs(_hx - self.x) > INVEST_RADIUS:
                    # ⭐ P0：`VW` → `WORLD_W`（夹目的地，不是夹自己）
                    self.invest_x = self._clamp_target_x(self.hear_x)
                    self._go_home = False   # ⭐ 新的一次查看，不是回程
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
                # ⭐ P0：同上，走同一个夹取方法
                self.invest_x = self._clamp_target_x(self.hear_x)
                self._go_home = False   # ⭐ 新的一次查看，不是回程

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
            # ⬝⬝ 2026-10-05 Ronny「他不会机械地走来走去」
            #   【不做的事】：不做“延迟抬头”。
            #   理由：抬头只是一个视觉反应，而不是位置变化——
            #   它不影响“他是否发现你”，只是看起来像在回头看。
            #   ⛔ 而真正的多管闲事是【他走过来】，那是 invest 的事。

    def _patrol(self, dt, luna):
        """⭐⭐⭐ 待机（2026-10-05 Ronny 定位改写）。


        ## ⛔ 旧版是"走 2.2s → 停 0.7s → 转身"的无限循环
        #  病根不是数值，是**默认就在动**：
        #   · patrol 段 (820,1108) 横跨整个禁区中段
        #   · 玩家禁区容器 (660/820/900/1000) 四分之三落在他走动范围里
        #   · 他一直在动 ⇒ 玩家永远找不到"安全窗口"
        #  实测：露娜 x=1000 静止不动、他在 760 ⇒ 1 秒内 alert 满 + chase
        #  ⇒ 观感是"恐怖人机"，而不是"保安"。
        #
        # ✅ 新版：**他站着不动**，只在待机计时到时轻轻扭头。
        #   会被惊动的情况只有两种（都不是"巡逻"）：
        #     ① investigate —— 听到声音，走过去看一眼，然后回来继续呆
        #     ② chase      —— 看见露娜进禁区，冲刺出来抓
        #
        # ⛔⛔ **不许在这里平移**。他一旦平移，"站岗的猫"就变回"巡逻的警卫"，
        #   玩家又会找不到安全窗口（本轮改动的全部意义就在这条）。
        #   `self.p0/p1` 保留只作为**初始站位**的取值范围。
        #
        # ⭐ 待机的"活气"从哪来：① 定期扭头（不挪窝）② 追出来 ③ 被打了会退
        #   —— 够了。猫站岗时的"活"是眼神和耳朵，不是腿。
        """
        self.idle_t -= dt
        if self.idle_t <= 0:
            self.idle_t = IDLE_STIR_P
            # ⭐ 只转头。⛔ 不动 x。
            self.face = -self.face
            # 转头时"看一眼"的顿挫（比瞬间翻面自然）
            self.pause_t = 0.35
        if self.pause_t > 0.0:
            self.pause_t -= dt

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
                # ⭐⭐ 2026-10-06 PR-07 修（**真bug**，verifier 与我各自独立复现）：
                #   「查看完回站岗点」原来写在**移动分支的末尾**，每走一帧就把
                #   `invest_x` 改写成 `idle_home`；而 `tgt` 是函数开头读的
                #   ⇒ 下一帧目标已经是站岗点，**他永远朝站岗点走、从不去看声源**。
                #   实测：声源 500 / 他 620 / 站岗点 934 ⇒ 全程离声源最近 **117.2px**
                #   （INVEST_RADIUS 只有 30）⇒ 「走过去查看声源」这个功能等于没上线，
                #   而所有相关判据因为"去站岗点的路上路过声源"全部**假绿**。
                #
                #   ✅ 正确的时机是**环顾结束之后**，不是"到达的那一刻"：
                #      到达 → 环视（站定不动）→ 环视结束 → 才把目标改成站岗点走回去。
                #   ⚠️ 为什么不能像最初想的那样在「到位」分支里就设 `invest_x=idle_home`：
                #      那样环视期间目标已经是站岗点，而环视结束这支队`invest_x = None`
                #      ⇒ 他**看完就站在声源旁边不动了**，违反 2026-10-05「看完要回站岗点」。
                #   ⛔ 原来那行`self.invest_linger = 0.0` 是**删掉**、不是搬过来：
                #      它原本的职责是"还没到位所以不环顾"；
                #      搬进「到位」的 else 会变成刚赋 INVEST_LINGER 又清零 ⇒ 环视 0 秒。
                self._go_home = True
                self.invest_x = self.idle_home
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
            if self._go_home:
                # ⭐⬈ 回站岗到位：直接停，不环视
                #   ⛔ 不能进环视：对着自己站的地方“低头看一会儿”
                #   比不动更拟人。到位就是到位。
                self.invest_x = None
                self._go_home = False
                self.idle_t = 0.0      # ⭐ 到家后立即允许下次抬头
                self.pause_t = 0.0
            else:
                # 到位 → 进入环视
                self.invest_linger = INVEST_LINGER
            return
        self.face = 1 if dx > 0 else -1
        # ⛔ ① 速度硬上限
        self.x += self.face * min(INVEST_SPEED, RUN_SPEED - 8.0) * dt
        # ⛔ ② 再夹一次（p0/p1 是巡逻范围，但查看目标可能落在它之外）
        # ⭐ P0：`VW` → `WORLD_W`（这是本单修的三处里**最要命**的一处 ——
        #   就算上面两处目标夹对了，自己走位仍被锁在 1224 ⇒ 他永远走不过去）。
        self._clamp_self_x()
        self.y = FLOOR_Y                 # 查看只在地板上走（⛔ 不爬梯：他只是去看一眼）
        # 打断踱步节奏的残留：查看结束后 patrol 会用这两个值，
        # 这里主动清零，避免"刚查完立刻又停 0.7s"的观感（见不变量 ③）
        self.pause_t = 0.0
        self.walk_t = 1.0
        self.y = FLOOR_Y
        # ⚠️⚠️ 2026-10-06 PR-07：原来"查看完回站岗点"的三行
        #   （`_go_home = True` / `invest_x = self.idle_home` / `invest_linger = 0.0`）
        #   写在这里 —— **移动分支的末尾**。那是全项目最隐蔽的一个 bug：
        #     `tgt = self.invest_x` 在函数**开头**读，而这里每走一帧就把目标
        #     改写成站岗点 ⇒ **下一帧读到的已是 idle_home，声源坐标被覆盖**，
        #     他永远朝站岗点走，"走过去查看声源"从未真正发生。
        #   ✅ 已挪到「环顾结束」那一支（见函数开头的 linger 分支）。
        #   ⛔ 别挪回来。挪回来这条判据立刻变回假绿，而且**测不出来**——
        #     因为"去站岗点的路上"经常刚好路过声源。

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
        for _p in room.platforms:
            # ⭐ PR12：读 dict（plat_fields 同时吃 4 元组）
            x0, y0, x1, y1 = plat_fields(_p)
            # ⛔⛔ Q2 Ronny 2026-10-08 定案：微波炉**完全不理** brittle。
            #   ⇒ 已触发的 brittle 对微波炉**不成立平台**，他当它不存在直接穿过去。
            #   ⛔ 这不是 bug 是定案，别"顺手修"成会掉下去—— 他没有"踩空"这个概念。
            if plat_kind(_p) == "brittle" and not room.brittle_active(id(_p)):
                continue
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
        #   换算成距离（**M=240** 平方衰减，2026-10-05 由 420 收窄）：heard 0.30 ≈ 距离 **172px** 以内。
        #   ⚠️ 旧注释写「M=420 / 330px」是 MW_HEAR_R 收窄时漏改的
        #     （那是 1280px 宽世界下的估算；verifier 实算 M=420 会得到 301.7px）。
        #   （历史批注：Ronny 17:55 听到的「24岁白女」问题与此无关，那是 sfx_caught 音色）
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
    # ⭐⭐⭐ `platforms` 做成 **property**：所有赋值路径都自动过滤脏数据。
    #   ⛔ 为什么必须用 property 而不是只在 __init__ 里过滤一次：
    #     项目里有 3 处**不走 __init__**、直接 `room.platforms = ...` 灌数据：
    #       _自测_PR04判据.py:54 / _自测_冰箱.py:44 / _d_新布局几何.py:36
    #     而 Ronny 手改 JSON 也会走编辑器的再次赋值。
    #     只在 __init__ 过滤 ⇒ 那 3 处 + 编辑器重新赋值仍然会把脏数据灌进来。
    #   ⭐ property 把"唯一收口点"变成语言层面的 ⇒ 漏不掉。
    _platforms = []

    @property
    def platforms(self):
        return self._platforms

    @platforms.setter
    def platforms(self, value):
        self._platforms = sanitize_platforms(value, warn_prefix="Room.platforms")

    def __init__(self, cfg: dict, custom=None, overrides=None):
        # ⭐⭐ PR12：`custom` 非 None 时用它当自定义地形层（list[dict]）。
        #   None ⇒ 完全走默认 PLATFORMS（**默认行为与改动前逐字一致**）。
        # ⭐⭐⭐ PR13：`overrides` 是**独立参数（dict）**，不是把 custom 改成多态。
        #   ⛔⛔ 为什么不用「custom 既能是 list 又能是 dict」（派单 §3.2的判断，我实测认同）：
        #     出问题时**没法判断这次传的到底是哪种** ⇒ 判据会静默测错对象。
        #     两处职责不同：custom = 地形（list）；overrides = 食物/起点/窝（dict）。
        self.custom = None
        # ⭐⭐⭐ PR16 · B 段（Ronny 拍板「方案 1 · 全集模式」）：
        #   custom 里**存在任一 builtin 条目** ⇒ 它**替换**默认 PLATFORMS，不是追加。
        #   ⛔ 判据与 `terrain_to_json` 升 v3 用的是**同一个**，别搞两套。
        #   ⛔ 不写 `custom is None` 之外的分支 —— 没 builtin 时行为**逐字不变**
        #      （自测 `:104` 断言 `Room(None).platforms` 长度 == 4）。
        _custom = list(custom) if custom else []
        _has_builtin = any(bool(platform_get(t, "builtin")) for t in _custom)
        if _has_builtin:
            self.platforms = sanitize_platforms(_custom, "自定义地形")
        else:
            self.platforms = platform_dicts(PLATFORMS) \
                + sanitize_platforms(_custom, "自定义地形")
        # ⭐ overrides 的**原样副本**（编辑器要拿它导出 JSON，也给自测看"用户到底设了什么"）
        #   ⛔ 必须**拷贝**：调用方若之后改了自己的 dict，room 里的不能跟着变。
        self.overrides = dict(overrides) if overrides else {}
        ov = self.overrides
        # ⭐⭐ PR12 · brittle 状态机（派单 §4.1）
        #   ⭐ 用 `id(plat)` 当键，**不用下标** —— 下标会随编辑器的增删漂移，
        #     漂了就变成"另一块地在消失"，这种 bug 极难查。
        #   ⛔ 为什么存 id 而不是把状态塞进 dict：dict 是从 JSON 导出的数据，
        #     塞运行时状态进去 ⇒ 导出时会把"谁触发过"一起写进文件，破坏往返还原。
        self._brittle = {}            # id(plat) -> 剩余恢复秒数
        # ⭐⭐ 2026-10-05 PR-03：世界宽（镜头跟随用）。旧代码无此概念。
        #   ⛔ 显式存成实例字段而不是全局读 —— 与 border_x 同一处置：
        #   谁改了它都有个可查的地方，漏改时不会"毫无反应"。
        self.world_w = float(WORLD_W)
        self.ladders = list(LADDERS)
        self.ladder_zones = list(LADDER_ZONES)
        # ⭐⭐ PR12：`kind="climb"` 的平台**同步进 ladder_zones**，
        #   复用已验证的攀爬逻辑（派单 §2.3「不要另写一套」）。
        #   ⚠️ 顺序不同！ladder_zones 是 (x0, x1, ytop, ybot)，
        #   platforms 是 (x0, y0, x1, y1) —— ⛔⛔ 不一样，别凭印象抄（派单 §2.3 警告）。
        #   ⭐⭐ Q7 Ronny 定案：**守卫（微波炉）也会爬它** ⇒ ladder_targets 收了它
        #     就是定案行为，不是副作用。下面 ladder_targets 的注释里记着这条。
        for _p in self.platforms:
            if plat_kind(_p) == "climb":
                # ⛔⛔⛔ 顺序：plat_fields 给的是 **(x0, y0, x1, y1)**，
                #   ladder_zones 要的是 **(x0, x1, ytop, ybot)** —— 顺序不同！
                #   ⛔ 我第一版写成 `append(plat_fields(_p))`，结果攀爬面变成
                #      (1500, 300, 1700, 460) ⇒ _ladder_here 把 y=300 当 x1、
                #      y=1700 当顶面 ⇒ 整块面判定错乱、**按 W 完全爬不上去**。
                #   ⇒ 这里必须**逐位重组**，不能整包塞。
                _x0, _y0, _x1, _y1 = plat_fields(_p)
                # ⭐ ytop=顶面(y0)，ybot=底面(y1)：攀爬面是这块平台的整面。
                self.ladder_zones.append((_x0, _x1, _y0, _y1))
        # ⭐ 微波炉用的"可攀爬目标"：点梯原样 + 攀爬面取中心 x（它走向中心再爬，
        #   与露娜抓布的位置基本重合，视觉上就是"他扒着布追上来"）
        # ⭐⭐ PR12：⛔ 必须**在 ladder_zones 补完 climb 之后**才算（顺序有讲究）
        self.ladder_targets = list(self.ladders) + [
            ((z[0] + z[1]) / 2.0, z[2], z[3]) for z in self.ladder_zones]
        # ⭐ taken = 食物已被拿走；broken = 容器已被敲开（敲开才会变 taken）
        # ⭐⭐ 2026-10-04：按食物特性分档（KIND_TABLE），所以这里把
        #   noise / fury / value / hit 全部**解算成实例上的字段** ——
        #   ⛔ 别在下游现查 KIND_TABLE[st["kind"]]：st["kind"] 可能被关卡数据覆盖，
        #   现查会让"这一局这个容器到底是什么档"变成隐式依赖，难排查。
        # ⭐⭐⭐ PR13：自定义 stashes **必须走同一段解算**（派单 §1.1 硬要求）——
        #   ⛔⛔ 另起一份解算 ⇒ 自定义食物的 noise/fury/value/hit 会与关卡食物不一致
        #   ⇒ 同一档食物表现不同 ⇒ 极难查。
        #   ⇒ 唯一的差别是**数据源**：下面把 `src` 选好，解算那段完全共用。
        #⭐ null 语义（§4.1）：键缺失/None ⇒ 用 cfg；[] ⇒ **显式清空**。
        _st_src = ov["stashes"] if ov.get("stashes") is not None else cfg["stashes"]
        stashes = []
        for s in _st_src:
            kind = s.get("kind", "plate")
            # ⛔⛔ 白名单校验放这里（不只是编辑器）：导入路径也走这儿 ⇒ 一道闸
            spec = KIND_TABLE.get(kind)
            if spec is None:
                raise ValueError("stashes.kind=%r 不合法（只能是 %s）"
                                 % (kind, "/".join(KIND_TABLE.keys())))
            stashes.append(dict(
                s, kind=kind,
                noise=spec["noise"], fury=spec["fury"],
                value=spec["value"], hit=spec["hit"],
                taken=False, broken=False))
        self.stashes = stashes
        # ⭐ 允许区边界随档位变；⭐⭐ PR23：可被 override（编辑器里拖出来）。
        #   ⛔ null 语义：`None` = 不覆盖 ⇒ 用关卡默认（360 / 1080 / 1500 ...）。
        self.border_x = (float(ov["border_x"])
                         if ov.get("border_x") is not None
                         else float(cfg["border_x"]))
        # ⭐⭐⭐ PR13：mw_patrol **激活它**（PR12 时它是死字段：只有写、没有读）。
        #   ⛔⛔ 只改起点不改 patrol 是**没用的**——他巡逻一圈就走回原区间
        #   （派单 §1.3）。所以本单做的是「巡逻段」，起点自动 = 中点，两者永远一致。
        #   ⭐ 默认值 `tuple(cfg["patrol"])` ⇒ 与改动前逐字相同。
        self.mw_patrol = (tuple(map(float, ov["mw_patrol"]))
                          if ov.get("mw_patrol") is not None
                          else tuple(cfg["patrol"]))
        # ⭐ 冰箱内容（每局重置）：QTE 成功才拿得到
        #   ⭐⭐ PR13：自定义 fridge_foods 走同一份拷贝逻辑，仅数据源不同。
        _ff_src = (ov["fridge_foods"] if ov.get("fridge_foods") is not None
                   else FRIDGE_FOODS)
        self.fridge_left = [dict(f) for f in _ff_src]
        # ⭐⭐⭐ PR13 · 露娜起点（单实例）
        #   ⛔⛔ **不做夹取**（Q13 裁定）：夹取要回答"谁能站"，那是把落地判定复制一遍，
        #     复杂度不划算且会与 `_clamp_x` 打架。
        #   ⭐ 所以起点允许放在空中（合法且有用：从吊柜开局）⇒ 她掉到地板即可。
        _sp = ov.get("spawn")
        self.spawn_luna = (tuple(map(float, _sp["luna"]))
                            if _sp else (NEST_X0 + 70.0, float(FLOOR_Y)))
        # ⭐⭐⭐ PR13 · 窝区（单实例），NEST_X0/X1 仍作默认值
        _nest = ov.get("nest")
        self.nest = (tuple(map(float, _nest))
                     if _nest else (float(NEST_X0), float(NEST_X1)))

    # ---------------- PR12 · brittle 状态机（派单 §4.1） ----------------
    # ⭐ 三条正确写法（派单给判据，我给实现）：
    #   ① 触碰 → 标记已触发 + 计时器 = 0     ⇒ brittle_touch()
    #   ② 已触发 → 不参与落地判定（她自然掉） ⇒ brittle_active() 返回 False
    #   ③ 计时 ≥ BRITTLE_RECOVER → 清标记     ⇒ tick_brittle()
    # ⛔⛔ 两条禁令我全部遵守，见各处注释。

    def brittle_touch(self, key) -> None:
        """① 被踩到/碰到：进入「已消失」倒计时。

        ⛔⛔ **重复踩不会重置计时器** —— 如果每次"还在平台上站着"都重置，
           计时器永远归零 ⇒ 平台永远不回来 ⇒ 玩家站着不动就永久失去这块地。
           ⛔ 这也是 Q1（派单 §六）取"不能踩"时的必然结果：
             踩一下→消失→计时跑完→回来→再踩→再消失（循环），但
             **恢复期间站不上去**，所以不会连成死循环。
        """
        self._brittle[key] = float(BRITTLE_RECOVER)

    def brittle_active(self, key) -> bool:
        """② 这块地形现在算不算「存在」。

        ⭐ 非brittle 一律 True —— **这是自测第 7 条阳性对照的依据**：
             一个没带 kind 的平台（或 kind=solid）永远返回 True，
             绝不会被判成"消失了"。
        ⛔⛔ Q1 未拍板 ⇒ 当前实现**不区分**"恢复中能不能再站"。
             若拍板为"能"，在这里加 `BRITTLE_RECOVERABLE_STAND` 分支即可。
        """
        return self._brittle.get(key, 0.0) <= 0.0

    def tick_brittle(self, dt: float) -> None:
        """③ 推进所有计时器，到期的恢复。

        ⛔⛔ **绝对不许在这里把角色钉回平台**（派单 §4.1 的禁令）：
           她可能已经走到别处、或者掉到别的地方去了，钉回去会瞬移。
        ⭐ 只改「这块地存不存在」，不管角色在哪。
        """
        if not self._brittle:
            return
        for key in list(self._brittle.keys()):
            self._brittle[key] = self._brittle[key] - float(dt)
            if self._brittle[key] <= 0.0:
                del self._brittle[key]

    def brittle_debug(self, key) -> float:
        """给自测用：查某块地的剩余恢复秒数（不改变状态）。"""
        return float(self._brittle.get(key, 0.0))

    def brittle_force_recover(self, key) -> None:
        """给自测用：立刻恢复某块地（⛔ 别用来实现玩法，只给判据注入用）。"""
        self._brittle.pop(key, None)


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
        # ⭐⭐ 2026-10-05 PR-03：横向镜头。cam_y **刻意不存在** ——
        #   派单说"纵向镜头逻辑已实测通过"，实测是**代码里根本没有纵向相机**
        #   （全文件无 cam_y/p.translate(0,-cam_y)）⇒ 纵向本来就是固定的。
        #   ⇒ 这里保持纵向不动，只加横向。不凭空引入未验证的纵向跟随。
        self.cam_x = 0.0
        # ⭐ 2026-10-05 三档合一档 ⇒ 默认 0。⛔ 原来写 1（那时有 3 档），
        #   留1 会在只有 1 个元素时**启动就 IndexError**。
        self.night_idx = 0
        self.room = Room(NIGHTS[self.night_idx])
        # ⭐⭐⭐ PR13：读 room.spawn_luna（默认 = (NEST_X0+70, FLOOR_Y)，逐字相同）
        self.luna = Luna(self.room.spawn_luna[0], self.room.spawn_luna[1],
                         sneak_ok=self._can_play("sneak"))
        # ⭐⭐⭐ PR13：传 room.mw_patrol（**激活那个死字段**）
        self.mw = Microwave(NIGHTS[self.night_idx], patrol=self.room.mw_patrol)
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
        # ⭐⭐ 2026-10-05 PR-03：三张 1280 切片（scene_bg_0/1/2.png）。
        #   ⚠️ BG-02b 的G1 已判废，切片**目前还不存在** ⇒ 这里做**渐进降级**：
        #     3张齐 → 用切片拼；不齐 → 用旧的 scene_bg.png 画在 x=0（其余区渐变）。
        #   ⛔ 绝不能因为图没到就白屏/崩 —— 美术件的到位时间不该阻塞玩法。
        self.bg_slices = []
        for _i in range(3):
            _p = os.path.join(GAME_ASSETS, "scene_bg_%d.png" % _i)
            _im = QImage(_p) if os.path.isfile(_p) else QImage()
            self.bg_slices.append(None if _im.isNull() else _im)
        print("[夜间] 背景切片 %d/3 张%s"
              % (sum(1 for s in self.bg_slices if s is not None),
                 "" if all(self.bg_slices) else "（不齐 ⇒ 回退单图 scene_bg.png）"))
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

        # ---- 🎵 音频（PR-03 第三批）----
        # ⛔ 2026-10-05 Ronny「环境音不要了」⇒ **开窗不再起环境音循环**。
        #   ⛔ 别加回来 —— 那条环境音素材已连同增益表项一起删除，
        #   加回来会让 Audio 每开机找一次不存在的文件、报一条错。
        #   ⇒ 现在**没有任何循环底噪**，只有 BGM（在 start_night 里起）。
        self.snd = _make_audio(self)
        if self.snd is not None and not self.snd.ok:
            # ⛔ 加载失败要**看得见**：素材没进包 / 文件坏了 / 插件漏了，三种都长这样。
            print("[夜间] ⚠️ 音频有缺失，见上面的 [音频] 报错（游戏可继续，将部分无声）")
        # ⭐ 离开窗口必须停掉还在响的东西（BGM 等）—— ⛔ 否则退出了还在响。
        self.destroyed.connect(self._on_destroyed)

        # ---- 循环 ----
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self._last = None

        # ---------------- PR12 · 自定义地形编辑器 ----------------
        # ⭐ 三态（派单 §3.2）：play / edit / play_custom
        #   ⛔ play_custom 必须有 —— 否则改完得重启才知道对不对（派单原话）。
        self.mode = "play"
        self.custom_terrains = []        # ⭐ 只放**自定义层**，默认 4 平台永远不进来
        # ⭐⭐⭐ PR16 · B 段：默认 4 平台（PLATFORMS）的**编辑副本**。
        #   None = **未接管**（用常量本身，导出不会被冻结）；list = 已接管（带 builtin:True）。
        #   ⛔ 为什么不按派单 §B.2「进 edit 就 copy 进 custom_terrains」：
        #      实测会撞翻 4 条既有判据（⑨-4 / ⑨-9 / ⑨-11 / ⑮-10），
        #      而 §D 明令 `_自测_*.py` 一个字不许改 ⇒ 改成**懒接管**：
        #      Ronny 真动手改默认平台时才落盘，没动过就与 PLATFORMS 常量保持同步。
        self.builtin_terrains = None
        self.edit_tool = "rect"# rect | line | select | food | fridge
                                            # | luna_spawn | mw_patrol | nest
        self.edit_kind = "solid"          # 当前要画的类型
        # ⭐ PR17 · P2-1：PR16 之后下标是**统一列表** `_edit_all()` 的
        #   （自定义层在前、默认 4 条在后），⛔ 不再是 `custom_terrains` 的下标。
        self.edit_sel = -1                # 选中项在 `_edit_all()` 里的下标， -1 = 没选
        # ⭐⭐⭐ PR13 · 五类可编辑对象的编辑器态（派单 §2.1）
        #   ⭐ 全是 None = **不覆盖**（null 语义，§4.1）。
        #   ⛔ 别把它们初始化成"默认值的副本"—— 那就分不清
        #      「用户没设」与「用户设成了默认值」，而 §4.2 的导出 v1/v2 正是靠这个区分。
        self.custom_stashes = None# list[dict] | None
        self.custom_fridge = None         # list[dict] | None
        self.custom_spawn = None          # tuple(x, y) | None
        self.custom_patrol = None         # (p0, p1) | None
        self.custom_nest = None           # (x0, x1) | None
        # ⭐⭐ PR23：关卡边界（单实例）。None = 不覆盖 ⇒ 用关卡默认。
        #   ⛔ 它是**微波炉的行为边界**（越界才"看见/追"露娜），⛔ **不限制露娜移动**。
        self.custom_border = None                 # float | None
        # ⭐ 选中态：食物用 ("food", 下标) / 单实例用 ("spawn", -1) 之类
        #   ⛔ 用元组而不是裸下标 —— 否则"第 3 个地形"和"第 3 个食物"分不清。
        self.edit_sel_obj = None
        self._drag = None                 # 拖拽中：(x0,y0,x1,y1) 屏幕->世界
        self._drag_shift = False          # ⭐ 按下那一刻的 Shift 状态（直线轴对齐用）
        # ⭐⭐ PR16 · 拖动**已有**地形（与 `_drag`=画新地形 是两条独立路径）
        self._move_from = None            # 按下时的世界坐标 (wx, wy)
        self._move_orig = None            # 按下时该块地形的**拷贝**（⛔ 不存引用，否则改的就是源）
        self._move_snap = False           # 这次拖动是否已进过撤销栈（⛔ 一次拖动只存一份）
        self._confirm_clear = False        # ⛔ 清空二次确认：按一下只提示，再按才真删
        self._undo = []                   # 撤销栈（每次改动前push 一份快照）
        # ⭐ 存档路径（派单 §六 Q6「你定，报我」）—— 放在引擎根的 assets_game 下，
        #   ⛔ 不写进 dist/_internal（那是打包产物，重打包会被覆盖）。
        self.terrain_path = os.path.join(GAME_ASSETS, "custom_terrain.json")
        # ⭐⭐⭐ PR17 · P0：启动时**自动导入**上次存下来的自定义地形。
        #   ⛔ 根因（派单 §0.1，我复核过）：导出一直是好的，坏的是"读" ——
        #      文件写下来了，但启动时从不加载 ⇒ Ronny 关掉游戏再开 = 白干。
        #   ⛔⛔⛔ 为什么**必须放 `__init__`**（派单 §P0.1 是对的，我一度想挪走）：
        #      真实入口有三条 —— ① `night.start()` ② **`gamehub.py:271` 直接
        #      `w = W(self.pack)`**（从 LunaPet 主界面点「深夜厨房」走这条）
        #      ③ `pet_launcher.py` 的 `--selftest-game`。
        #      ② 那个文件是**六把锁之一，一个字不许改** ⇒ 只有 `__init__`
        #      能同时覆盖①②③。挪到 `start()` 会让主界面进游戏时读不到存档。
        #
        #   ⛔⛔ 但**无头环境（offscreen）必须跳过** —— 这是测试隔离，实测过：
        #      自测全都直接 `NightWindow(pack)` 构造窗口，若这里读用户存档，
        #      Ronny 一旦存了地形，_自测_自定义地形.py 的 ⑨-2/⑨-4/⑨-5/⑨-6/⑨-9/⑨-11
        #      与 _自测_夜间.py 的 2 条会一起变红（数字见回执 PR17）。
        #      ⭐ 真机是**窗口模式**，一定会加载（判据 ⑲-10 用伪造
        #      QT_QPA_PLATFORM=windows 验证过）。
        #      ⛔ 无头环境（offscreen）恒跳过 —— 这是测试隔离，别删。
        #      ⛔⛔ 本条件是 **AND**（设计端 PR20 实测指出，原注释在骗人）：
        #         `NIGHT_AUTOLOAD=1` 也**不能**在无头下强制加载
        #         —— 两个条件必须同时成立。它只能用来**关掉**（=0），不能用来打开。
        #      ⛔⚠️ 真机必须在【启动 bat】里 `set QT_QPA_PLATFORM=windows`：
        #         `gamehub.py:27` 与 `hundred.py:69` 在 **import 时**就
        #         `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`。
        #         实测：`启动游戏.bat` / `启动桌宠.bat` / `直接开玩.bat` 都设了 windows ✅；
        #         `_启动游戏主界面.py` 自己 pop 掉再设 windows ✅；
        #         ⛔ 但 **`打包.bat` 没有设** ⇒ 打包后的 LunaPet.exe 走 gamehub 延迟 import
        #         那条路时，本闸门**恒假 ⇒ 存档不会自动加载**（未处理，见回执 PR20）。
        # ⭐⭐⭐ PR21 · A1：存档加载状态。**四态**，⛔ 不许用"有没有 loaded 字段"两态——
        #   「根本没有存档文件」和「有存档但这次没载入」是两件事，混起来
        #   Ronny 永远不知道自己是不是"没加载"（PR21 §0.1 的原始困惑）。
        #   absent=没有存档文件 / present=有但没载入 / loaded=已载入 / bad=读坏了
        self._save_state = ("present" if os.path.isfile(self.terrain_path)
                            else "absent")
        self._warned_save = False         # A1-2 的"只提示一次"闸
        if (os.environ.get("NIGHT_AUTOLOAD") != "0"
                and os.environ.get("QT_QPA_PLATFORM", "") != "offscreen"):
            self._autoload_terrain()
        # ============ PR14 · 攻击特效 ============
        # ⭐ 特效列表挂在窗口上，⛔ **不用全局变量**（多窗口/重入会互相污染）。
        self.fx = []

    # ---------------- PR13 · overrides 汇总 ----------------

    def _collect_overrides(self) -> dict:
        """把编辑器的 5 类状态汇总成 `Room(overrides=...)` 要的 dict。

        ⭐⭐ **None 一律不写进 dict** —— 这是 §4.1 null 语义的实现：
           「键不在」= 不覆盖；`[]` = 显式清空。两者靠"键在不在"区分。
        """
        ov = {}
        if self.custom_stashes is not None:
            ov["stashes"] = [dict(s) for s in self.custom_stashes]
        if self.custom_fridge is not None:
            ov["fridge_foods"] = [dict(f) for f in self.custom_fridge]
        if self.custom_spawn is not None:
            ov["spawn"] = {"luna": tuple(self.custom_spawn)}
        if self.custom_patrol is not None:
            ov["mw_patrol"] = tuple(self.custom_patrol)
        if self.custom_nest is not None:
            ov["nest"] = tuple(self.custom_nest)
        if self.custom_border is not None:      # ⭐⭐ PR23
            ov["border_x"] = float(self.custom_border)
        return ov

    # ---------------- PR13 · 编辑器 · 5 类新对象的放置 / 删除 ----------------
    #⭐ 统一入口：鼠标按下时按当前工具分派。
    #   ⛔ 不写在 mousePressEvent 里 —— 那里已经装了 PR12 的拖拽/选中，
    #      再堆 5 个分支会让"按下"这个动作变成一坨if。
    def _edit_place(self, wx, wy) -> bool:
        """按当前工具在 (wx,wy) 放置/移动对象。⇒ 是否改动了状态。"""
        t = self.edit_tool
        if t in ("rect", "line", "select"):
            return False                # 这三个走PR12 的路径
        if t == "food":
            return self._edit_add_food(wx, wy)
        if t == "fridge":
            return self._edit_add_fridge(wx, wy)
        if t == "luna_spawn":
            return self._edit_set_spawn(wx, wy)
        if t in EDIT_LINE_TOOLS:
            # ⭐ 巡逻段/窝区要**拖**一条线，单击时 x1==x0 ⇒ 退化成一个点 ⇒ 拒。
            #   真的放置在 mouseReleaseEvent 里做（那里才有两端坐标）。
            return False
        return False

    def _edit_add_food(self, wx, wy) -> bool:
        """放一个地面/台面容器。⇒ 是否成功。

        ⛔⛔ 边界必须卡（派单 §2.3）：画到画面外 = 废数据，
           而这份数据**会导出给下游生成脚本**，脏数据会一路走下去。
        ⭐ 越界不抛异常、只返回 False + 给一行提示 ——
           编辑器是交互式工具，抛异常会把整个游戏带崩。
        """
        x, y = float(wx), float(wy)
        if not (0.0 <= x <= float(WORLD_W)):
            return self._edit_refuse("食物要放在世界里（x 0~%d）" % int(WORLD_W))
        if not (0.0 <= y <= float(FLOOR_Y)):
            return self._edit_refuse("食物不能低于地板 y=%d" % int(FLOOR_Y))
        self.edit_snapshot()
        if self.custom_stashes is None:
            self.custom_stashes = []
        self.custom_stashes.append({"x": x, "y": y,
                                    "icon": DEFAULT_FOOD["icon"],
                                    "kind": DEFAULT_FOOD["kind"]})
        # ⭐ 放完自动选中（派单 §2.2）—— 不选中就没法接着按 [ ] 改 icon
        self.edit_sel_obj = ("food", len(self.custom_stashes) - 1)
        self._apply_overrides_now()
        self.update()
        return True

    def _edit_add_fridge(self, wx, wy) -> bool:
        """放一个冰箱内食物。⇒ 是否成功。

        ⛔⛔ x/y 必须落在冰箱矩形内（派单 §2.3）：
           画在冰箱外 = 视觉上食物飘在墙上，玩家会以为游戏坏了。
           冰箱坐标**不写死** —— 从 FRIDGE 常量读，跟着关卡数据走。
        """
        x, y = float(wx), float(wy)
        if not FRIDGE_ENABLED:
            return self._edit_refuse("这个关卡没有冰箱")
        fx0, fy = float(FRIDGE["x"]), float(FRIDGE["y"])
        fx1 = fx0 + float(FRIDGE["w"])
        fy0 = fy - float(FRIDGE["h"])
        if not (fx0 <= x <= fx1):
            return self._edit_refuse("冰箱食物要横向落在冰箱内（x %d~%d）"
                                     % (int(fx0), int(fx1)))
        if not (fy0 <= y <= fy):
            return self._edit_refuse("冰箱食物要纵向落在冰箱内（y %d~%d）"
                                     % (int(fy0), int(fy)))
        self.edit_snapshot()
        if self.custom_fridge is None:
            self.custom_fridge = []
        self.custom_fridge.append({"x": x, "y": y, "icon": DEFAULT_FOOD["icon"]})
        self.edit_sel_obj = ("fridge", len(self.custom_fridge) - 1)
        self._apply_overrides_now()
        self.update()
        return True

    def _edit_set_spawn(self, wx, wy) -> bool:
        """设露娜起点（单实例，再点即移动）。⇒ 是否成功。

        ⭐⭐ **不夹取 y**（交接包 §4.3 Q13 裁定）：
           夹取要回答"哪里能站"，那等于把落地判定逻辑复制一份，
           而且会和 `_clamp_x` 打架。起点设在空中是**合法且有用**的
           （可以做"从吊柜开局"），她掉到地板即可。
           ⇒ 只做世界边界检查（防止放到画面外找不回来）。
        """
        x, y = float(wx), float(wy)
        if not (0.0 <= x <= float(WORLD_W)):
            return self._edit_refuse("起点要放在世界里（x 0~%d）" % int(WORLD_W))
        if not (0.0 <= y <= float(FLOOR_Y)):
            return self._edit_refuse("起点不能低于地板 y=%d" % int(FLOOR_Y))
        self.edit_snapshot()
        self.custom_spawn = (x, y)
        # ⭐ 用工具名 "luna_spawn" 当选中标签（与 _edit_hit_obj / EDIT_SINGLE_TOOLS 同源）
        self.edit_sel_obj = ("luna_spawn", -1)
        self._apply_overrides_now()
        self.update()
        return True

    def _edit_set_line(self, tool, wx0, _wy0, wx1) -> bool:
        """设巡逻段 / 窝区（拖拽水平线段）。⇒ 是否成功。

        ⭐ 形参是 `(tool, wx0, _wy0, wx1)` —— **与 `self._drag` 的四元组同序**，
           调用方直接 `_edit_set_line(tool, *self._drag)` 即可，
           ⛔ 不要写成 3 参数：调用点是`_edit_set_line(tool, x0, x1)`，
           少传一个会得到「一个坐标当成两个用」的静默错位，
           实测直接TypeError 才没酿成事故。
        ⭐ y **一律忽略**（形参写成 `_wy0` 就是提醒"这个位置故意不用"）：
           这两样只需要 x 区间。
           ⛔ 不是偷懒 —— 微波炉 `self.y = FLOOR_Y` 是硬编码（他永远在地板上），
              窝区判定也只比 x。存一个 y 进去就是废数据，还会误导下游脚本。
        ⛔ p0 >= p1 ⇒ 拒（退化成点 = 无意义）。
        """
        a, b = sorted((float(wx0), float(wx1)))
        # ⭐⭐ PR23 · 关卡边界：**竖直**拖一条线，只取 x（y 一律忽略）。
        #   ⛔ 与巡逻段/窝区分开 —— 它们要"有长度的水平线段"，边界只要一个 x。
        #   ⭐ 夹取口径（派单 §4② 默认建议，未收到异议）：[露娜半宽+8, WORLD_W]
        #      下限理由：边界小于身体半宽时露娜一出生就在界外 ⇒ 微波炉立刻警觉。
        if tool == "border":
            _x = float(wx0)
            _lo = BODY_W * 0.5 + 8.0
            _hi = float(WORLD_W)
            if not (_lo <= _x <= _hi):
                return self._edit_refuse(
                    "边界要落在 %.0f ~ %d 之间（太小会让露娜一出生就在界外）"
                    % (_lo, int(_hi)))
            self.edit_snapshot()
            self.custom_border = _x
            self.edit_sel_obj = ("border", -1)
            self._apply_overrides_now()
            self.update()
            return True
        if abs(b - a) < 4.0:
            return self._edit_refuse("要拖出一条**有长度**的线段（现在几乎是点）")
        if not (0.0 <= a and b <= float(WORLD_W)):
            return self._edit_refuse("线段要完全落在世界里（0~%d）" % int(WORLD_W))
        self.edit_snapshot()
        if tool == "mw_patrol":
            self.custom_patrol = (a, b)
        else:
            self.custom_nest = (a, b)
        self.edit_sel_obj = (tool, -1)
        self._apply_overrides_now()
        self.update()
        return True

    def _edit_refuse(self, why: str) -> bool:
        """拒绝一次放置：给一行提示，**不改任何状态**。⇒ 恒为False。

        ⭐ 只提示不抛：编辑器的每次鼠标按下都会走到这里，
           抛异常 = 点歪一下整个游戏崩掉。
        """
        self.msg, self.msg_t = why, 2.5
        self.update()
        return False

    def _apply_overrides_now(self) -> None:
        """把当前 overrides 立刻灌进 self.room（并让微波炉跟着走）。

        ⭐⭐ **为什么必须有这个**：判定读的是 `self.room.*`，不是编辑器状态。
           改了 `custom_stashes` 却不重建 room ⇒ 画面上没变、试跑也没变，
           用户会以为功能坏了。PR12 的地形靠 `_edit_add` 每次重建，
           这里必须同样对待 5 类对象。
        ⭐⭐⭐ **微波炉必须一起挪**（实测踩到的真bug，判据 ⑮-6 抓出来的）：
           `Microwave.__init__` 是按 patrol 中点算 x 的（`:1779`），
           只换 room 不动 mw ⇒ `room.mw_patrol` 已经是 [2000,2400]，
           而画面上的微波炉还站在老中点 ⇒ **试跑时他会自己走回老位置**，
           也就是"巡逻段工具看起来没生效"。
           ⛔ 这正是派单 §1.3 警告的坑：只改起点不改 patrol 等于没改。
           ✅ 所以这里不重建整个对象（会丢 alert/state 等运行时状态），
              只按新 patrol 重算他的**初始 x/y**。
        ⭐ `mw` 可能还不存在（构造早期就调了本函数）⇒ getattr 兜底。
        """
        self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                         overrides=self._collect_overrides())
        _mw = getattr(self, "mw", None)
        if _mw is not None:
            _mw.x = (self.room.mw_patrol[0] + self.room.mw_patrol[1]) / 2.0
            _mw.y = FLOOR_Y

    def _edit_cycle_sel_prop(self, which: str) -> bool:
        """`[` `]` 换选中食物的 icon；`,` `.` 换 kind。⇒ 是否改动了。

        ⛔ 只作用于**选中**的食物（派单 §2.2「改选中项」而不是「改当前配方」）：
           少一个编辑器状态，且符合"放→选中→调属性"的直觉。
        ⛔ 循环里只在白名单内转（FOOD_ICONS / FOOD_KINDS）——
           越界会让 `self.icons.get()` 取到 None ⇒ 绘制崩。

        ⭐⭐ PR27（2026-10-10 Ronny）：`.` `,` **也能改选中地形的 kind**。
        ⛔ 为什么必须能：攀爬面**只认 `kind="climb"`**（`Room.__init__` 只把 climb
        收进 `ladder_zones`）⇒ 画的时候选了 solid 的竖条，事后改不了 kind 就
        **永远爬不了**。Ronny 实测：19 条全是 solid，`ladder_zones` 里一条 climb 都没有。
        """
        sel = self.edit_sel_obj
        # ⭐⭐ 地形分支（选中的是地形，不是食物）
        if not sel and 0 <= self.edit_sel < len(self._edit_all()):
            if which != "kind":
                return self._edit_refuse("地形只能改 kind（, . 键）")
            i = self.edit_sel
            _t = self._edit_all()[i]
            if self._is_floor_sel(i):
                return self._edit_refuse("默认地板不能改 kind（PR16 R3）")
            self.edit_snapshot()
            _seq = list(TERRAIN_KINDS)
            _j = _seq.index(plat_kind(_t)) if plat_kind(_t) in _seq else 0
            _nk = _seq[(_j + 1) % len(_seq)]
            _nt = dict(_t)
            _nt["kind"] = _nk
            self._edit_write_at(i, _nt)
            self._apply_overrides_now()
            self.msg, self.msg_t = "第 %d 块地形 kind → %s" % (i, _nk), 3.0
            self.update()
            return True
        if not sel or sel[0] != "food":
            return self._edit_refuse("先选中一个食物（用 6 选择工具点它）")
        i = sel[1]
        if self.custom_stashes is None or not (0 <= i < len(self.custom_stashes)):
            return self._edit_refuse("选中的食物已不存在")
        # ⭐⭐ 属性改动**也要进撤销栈**（派单 §3.3 的本意）。
        #   ⛔ 快照存的是"改动前"的状态 ⇒ 所以**先拍快照再改**，
        #   Ctrl+Z 才能把这次属性变更退回去。
        self.edit_snapshot()
        s = self.custom_stashes[i]
        if which == "icon":
            seq = list(FOOD_ICONS)
            j = seq.index(s["icon"]) if s["icon"] in seq else 0
            s["icon"] = seq[(j + 1) % len(seq)]
        else:
            seq = list(FOOD_KINDS)
            j = seq.index(s["kind"]) if s["kind"] in seq else 0
            s["kind"] = seq[(j + 1) % len(seq)]
        self._apply_overrides_now()
        self.msg, self.msg_t = ("选中食物：%s / %s"
                                % (s["icon"], FOOD_KIND_CN.get(s["kind"], s["kind"]))), 2.0
        self.update()
        return True

    # ---------------- PR12 · 编辑器 · 状态切换 ----------------

    def set_mode(self, m: str) -> None:
        """切 play / edit / play_custom。

        ⛔ 只认这三个值，别的地方 ⛔ 不许直接写 `self.mode = ...`——
           漏了「把编辑中的地形塞进 room」这一步会让改了不生效（很难查）。
        """
        if m not in ("play", "edit", "play_custom"):
            raise ValueError("mode 只能是 play / edit / play_custom，收到 %r" % m)
        prev = self.mode
        self.mode = m
        # ⭐⭐⭐ PR13：Room 一律带上 overrides（5 类对象的覆盖值）。
        #   ⛔ `play` 模式**也要带** —— 否则 Ronny 在编辑态设好起点，
        #   一切回 play 就回到 80（他以为设好了）。
        #   ⭐ `overrides` 空 dict ⇒ Room 各字段取默认值 ⇒ 与改动前逐字相同。
        _ov = self._collect_overrides()
        if m == "play":
            # ⭐⭐⭐ PR18（设计端签字）：`play` **也吃**自定义地形 —— 与 `start_night`
            #   / `play_custom` 三条路径口径**完全一致**。
            #   ⛔ 改前是 `Room(..., overrides=_ov)`（不带 custom）⇒ 从编辑器按 F2
            #      退出，露娜眼前的地形**当场消失**（就是 Ronny 报的「存了但没了」）。
            #   ⛔⛔ 必须用 `self._room_custom()`（含已接管的 `builtin_terrains`），
            #      ⛔ 不是 `self.custom_terrains` —— 后者会漏掉被 Ronny 改过的默认平台
            #      （比如他把桌布 y1 从 599 改成 520），改了就白改。
            self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                             overrides=_ov)
            self.luna.x, self.luna.y = self.room.spawn_luna
            self.luna.vy = 0.0
            self.luna.on_ground = True
        elif m == "play_custom":
            # ⭐ 用自定义地形试跑：编辑中的地形**立刻在画面上呈现**（派单 §3.2）
            self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                             overrides=_ov)
            self.luna.x, self.luna.y = self.room.spawn_luna
            self.luna.vy = 0.0
            self.luna.on_ground = True
        elif m == "edit":
            # 编辑态：地形常驻可见，但**不跑物理**（_tick 里按 mode 分流）
            self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                             overrides=_ov)
        self.phase = "menu" if m == "edit" else self.phase
        self.update()

    def edit_snapshot(self) -> None:
        """改动前存一份快照（撤销栈）。⭐ 每次改动前必须调。

        ⭐⭐⭐ PR13：快照从「只有地形」扩成**6 类全存**
          （派单 §3.3：否则 Ctrl+Z 只撤地形、撤不掉食物）。
        ⭐ 存的是 None / list / tuple 的**原样**，所以"不覆盖"与"显式空"都能还原。
        """
        self._undo.append({
            "terrains": [dict(t) for t in self.custom_terrains],
            # ⭐⭐ PR16 · B 段：默认平台也要能撤（改了桌布 y1 之后 Ctrl+Z 要退得回去）
            "builtins": None if self.builtin_terrains is None
                        else [dict(t) for t in self.builtin_terrains],
            # ⭐⭐ PR23：关卡边界也要能撤
            "border": self.custom_border,
            "stashes": None if self.custom_stashes is None
            else [dict(s) for s in self.custom_stashes],
            "fridge": None if self.custom_fridge is None
            else [dict(f) for f in self.custom_fridge],
            "spawn": None if self.custom_spawn is None
            else tuple(self.custom_spawn),
            "patrol": None if self.custom_patrol is None
            else tuple(self.custom_patrol),
            "nest": None if self.custom_nest is None
            else tuple(self.custom_nest),
        })
        if len(self._undo) > 64:              # ⛔ 别无限涨
            self._undo.pop(0)

    def edit_undo(self) -> bool:
        """Ctrl+Z。⇒ True=撤销了一次，False=没得撤。"""
        if not self._undo:
            return False
        snap = self._undo.pop()
        self.custom_terrains = snap["terrains"]
        # ⭐ PR16 · B 段：`.get` 而不是 `[]` —— 老快照（PR12/13 存的）没有这个键
        self.builtin_terrains = snap.get("builtins")
        # ⭐⭐ PR23 · `.get` 兼容 PR16 之前的老快照（没有这个键）
        self.custom_border = snap.get("border")
        self.custom_stashes = snap["stashes"]
        self.custom_fridge = snap["fridge"]
        self.custom_spawn = snap["spawn"]
        self.custom_patrol = snap["patrol"]
        self.custom_nest = snap["nest"]
        if self.mode in ("edit", "play_custom"):
            self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                             overrides=self._collect_overrides())
        self.update()
        return True

    # ---------------- PR13 · 清空 / 导出 / 导入 ----------------

    def edit_clear(self) -> None:
        """清空全部自定义（调用方负责二次确认）。

        ⭐⭐⭐ PR13：地形 **+ 5 类新对象**一起清（交接包 §4.3 裁定）。
           ⛔⛔ 为什么必须一起清：只清地形的话，用户按C 以为"全清了"，
           结果食物还挂在台面上、窝还在老位置 —— **比不清更坏**
           （他会以为是自己记错了，而不是有 bug）。
        ⭐ 5 类新对象复位成 `None`（= 不覆盖，走关卡默认），
           **不是** `[]`（= 显式清空）：「回到出厂」和「这关一个容器都没有」
           是两件不同的事，不能混。
        """
        self.edit_snapshot()
        self.custom_terrains = []
        # ⭐ PR16 · B 段：清空 = **回到出厂默认** ⇒ 默认平台也放弃接管
        self.builtin_terrains = None
        self.custom_stashes = None
        self.custom_fridge = None
        self.custom_spawn = None
        self.custom_patrol = None
        self.custom_nest = None
        # ⭐⭐ PR23：清空 = 边界也回到关卡默认（None = 不覆盖）
        self.custom_border = None
        if self.mode in ("edit", "play_custom"):
            self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                             overrides=self._collect_overrides())
        self.update()

    def export_terrain(self, path=None):
        """导出 JSON（派单 §五 定死格式）。⇒ 实际写出的路径。"""
        p = path or self.terrain_path
        os.makedirs(os.path.dirname(p), exist_ok=True)
        # ⭐⭐⭐ PR13：必须传 overrides —— 不传的话 `terrain_to_json` 会走
        #   「全 None ⇒ 导 v1 四键」分支，**用户在编辑器里放的食物会被丢掉**，
        #   而且⛔ **不报错**（文件照样生成，只是少几个键）。
        #   这就是「静默丢数据」：用户以为存下来了，重新打开是空的。
        data = terrain_to_json(self._room_custom(), overrides=self._collect_overrides())
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return p

    def import_terrain(self, path=None) -> int:
        """导入 JSON ⇒ 地形条数。

        ⛔ 非法文件抛异常（不静默忽略）—— 静默 = 用户以为导入了，其实现地形没变。

        ⭐⭐⭐ PR13：v1 / v2 都要能读。
           ⛔⛔ `overrides_from_json(data)` 必须在**快照之后**调：
              它会抛（白名单外的icon / 类型不对 / p0>=p1），
              先快照再解析 ⇒ 解析失败时编辑器状态**一点没变**，
              不会留下"快照被白白吃掉"的副作用。
           ⛔ 漏掉这一句 = v2 文件里的 5 类字段被**静默丢弃**，
              用户导入完发现食物没了、也不会有任何报错。
        """
        p = path or self.terrain_path
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = terrain_from_json(data)
        ov = overrides_from_json(data)      # ⛔ 非法就抛，抛在改动之前
        self.edit_snapshot()
        # ⭐⭐ PR16 · B 段：v3 里的 builtin 条目**分桶**进 `builtin_terrains`，
        #   其余进 `custom_terrains`。⛔ 没有 builtin ⇒ 设回 None（= 未接管，
        #   v1/v2 老文件行为**逐字不变**）。
        _bl = [t for t in ts if platform_get(t, "builtin")]
        self.builtin_terrains = _bl if _bl else None
        self.custom_terrains = [t for t in ts if not platform_get(t, "builtin")]
        # ⭐ v1 文件 ⇒ overrides_from_json 返回全 None 的 dict
        #   ⇒ 5 类字段复位成 None（不是覆盖，是「回到关卡默认」），与 PR12 行为一致。
        self.custom_stashes = ov.get("stashes")
        self.custom_fridge = ov.get("fridge_foods")
        _sp = ov.get("spawn")
        self.custom_spawn = tuple(_sp["luna"]) if _sp else None
        self.custom_patrol = ov.get("mw_patrol")
        self.custom_nest = ov.get("nest")
        # ⭐⭐ PR23：⛔ 只有 v4 才会带 border_x（`overrides_from_json` 已按版本过滤）
        _bd = ov.get("border_x")
        self.custom_border = None if _bd is None else float(_bd)
        if self.mode in ("edit", "play_custom"):
            self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                             overrides=self._collect_overrides())
        self.update()
        return len(ts)

    # ⭐⭐⭐ PR17 · P0 · 启动时自动导入
    def _save_status_cn(self) -> str:
        """PR21 · A1：存档状态的中文说明（工具栏那行用）。⇒ 四态各有各的话。

        ⭐ 为什么要「四态」而不是「载入 / 没载入」两态（PR21 §0.1 的原始困惑）：
           「压根没有存档文件」和「有存档但这次没加载」在画面上**长得一样**
           （都是那 4 条出厂默认平台）⇒ 混成两态时 Ronny 分不清自己是不是"没加载"。
        """
        if self._save_state == "loaded":
            return "存档 √ 已载入 %d 条" % len(self._room_custom())
        if self._save_state == "bad":
            return "存档 ⚠ 读不出来（已按出厂默认继续）"
        if self._save_state == "present":
            return ("存档 ⚠ 未载入（当前显示出厂默认 4 条，"
                    "改完记得按 S 导出）")
        return "存档 —（还没有存档文件，按 S 导出）"

    def _warn_save_not_loaded(self) -> None:
        """PR21 · A1-2：进游戏时若「有存档但这次没载入」⇒ 提示一次（只一次）。

        ⛔ 为什么要这条：编辑器工具栏那个提示只在 F2 之后才看得见，
           而 Ronny 的原话是「**进游戏**看到旧地形」⇒ 不在游戏里说一声，他永远不知道。
        ⛔ 只提示一次（`_warned_save`）：否则每次 `start_night` 都弹，烦到要屏蔽。
        """
        if self._warned_save or self._save_state != "present":
            return
        self._warned_save = True
        self.msg = ("⚠️ 自定义地形存档没载入，本次按出厂默认 4 条玩"
                    "（编辑器里按 O 可手动载入）")
        self.msg_t = 6.0

    def _autoload_terrain(self):
        """启动时读一次 `custom_terrain.json`（= 上次按 S 存下来的）。

        ⛔⛔ **必须 try/except 包住并 print**：`import_terrain` 是「非法就抛」的设计
           （PR13 定的，理由是「静默 = 用户以为导入了其实没有」），
           而**启动时抛异常 = 游戏直接打不开** ⇒ 只能在**调用点**包，不能改它的语义。

        | 情况 | 处理 | 理由 |
        |---|---|---|
        | 文件不存在 | **静默**跳过（不 print） | 首次运行本来就没有，每次启动刷一行报错很烦 |
        | 解析失败 | **print 告警** + 复位成空状态 | ⛔ 不许静默（Ronny 铁律）；也不许留半截数据 |
        | 成功 | 不弹提示、不重建 Room | 启动时 `mode == "play"`，`import_terrain` 本来就不重建 |

        ⭐⭐ 成功后**清空撤销栈**：否则 Ronny 一进编辑器按 Ctrl+Z，
           会把刚自动加载进来的地形全撤掉（看起来像"存档丢了"）。
        """
        if not os.path.exists(self.terrain_path):
            self._save_state = "absent"
            return
        try:
            self.import_terrain(self.terrain_path)
        except Exception as e:                       # noqa: BLE001
            print("[夜间] ⚠️ 自定义地形存档读不出来，已按「空」继续"
                  "（不影响正常开局）：%s: %s" % (type(e).__name__, e))
            # ⛔ 解析失败 ⇒ 复位成**空状态**（不是留着半截数据）
            self.custom_terrains = []
            self.builtin_terrains = None
            self.custom_stashes = None
            self.custom_fridge = None
            self.custom_spawn = None
            self.custom_patrol = None
            self.custom_nest = None
            self._undo = []
            self._save_state = "bad"
            # ⭐ PR20 · B3：光 print 不够 —— Ronny 看不到控制台。
            #   ⛔ 不弹模态框（会挡游戏）；⭐ 6 秒（默认 2~3 秒读不完）。
            self.msg = "⚠️ 自定义地形存档读不出来，本次按默认关卡玩"
            self.msg_t = 6.0
            return
        self._undo = []                              # ⭐ 见上面的理由
        self._save_state = "loaded"

    def _edit_add(self, x0, y0, x1, y1, kind=None, line=False, shift=False) -> bool:
        """加一块自定义地形。⇒ 是否成功。

        ⛔⛔ 拒绝的条件（每条都有理由，不是洁癖）：
           · 反向/零面积 ⇒ 拖拽方向可能相反，规范成 x0<x1
           · 低于地板 599 ⇒ 玩家站不到，等于废数据（会导出给下游生成脚本）
           · 高于 y=0   ⇒ 同上，画到画面外
        ⭐ `line=True` 时是**直线工具**（Ronny 2026-10-08）：
             shift=True  ⇒ 强制轴对齐，取 |dx| / |dy| 较大者作为主轴，
                           生成**零厚**地形（水平线 y0==y1 / 垂直线 x0==x1）
             shift=False ⇒ 自由，仍是有厚度的矩形（见 EDIT_LINE_ANGLE_LOCK 注释：
                           斜线会破坏落地判定的顶面假设，本版不支持）
        """
        k = kind or self.edit_kind
        if line:
            dx = abs(float(x1) - float(x0))
            dy = abs(float(y1) - float(y0))
            # ⭐⭐ PR21 · A2：直线工具**默认就画零厚线**（⛔ 不再按 shift 分叉）。
            #   理由三条（设计端裁定）：① 工具名叫「直线」画出来不是直线 = 命名与行为不符；
            #   ② 3px 渲染像线、物理是矩形 ⇒ 会误导落地判定，不只是不好看；
            #   ③ 零厚线是本项目**已验证**的机制（桌布/挂毯攀爬面）。
            #   ⭐ Shift 的**新语义 = 强制另一轴**（不自然，但想画就按）。
            #   ⛔⛔ **幂等**（实测踩过）：鼠标路径上 `mouseMoveEvent` 的预览**已经翻过一次**
            #      ⇒ `_drag` 送进来已经是轴对齐的。这里若再翻一次 ⇒ 零长
            #      （主轴 0 < 4）⇒ `_edit_add` 返回 False ⇒ **「直线+Shift 拖了却什么都没画」**。
            #      ⇒ 输入已是零厚时**不再翻转**，只按原朝向采用。
            _already_thin = (dx < _THIN_EPS or dy < _THIN_EPS)
            _horiz = (dx >= dy)
            if shift and not _already_thin:
                _horiz = not _horiz
            if _horiz:
                # ⭐ 水平线：y 相同（零厚）。y 取**起点** y（不是平均）
                #   —— 直线是"一条"，没有厚度，取起点才与手画的位置一致。
                xa, xb = min(float(x0), float(x1)), max(float(x0), float(x1))
                ya = yb = float(y0)
            else:
                # ⭐ 垂直线：x 相同（零厚）⇒ 天然是「攀爬面」（Ronny 原话）
                xa = xb = float(x0)
                ya, yb = min(float(y0), float(y1)), max(float(y0), float(y1))
        else:
            xa, xb = (min(x0, x1), max(x0, x1))
            ya, yb = (min(y0, y1), max(y0, y1))
        # ⛔⛔ **主轴不做任何补齐** —— 零厚必须真的是零厚（理由见 EDIT_MIN 处的注释）
        # ⭐ 只做**边界夹取**：直线可能被拖到地板线以下/世界外
        # ⭐ PR21 · A2：零厚判据也跟着改成 `line` 即可（⛔ 不再 `line and shift`）
        _thin = bool(line)
        xa = max(0.0, min(xa, float(WORLD_W)))
        xb = max(0.0, min(xb, float(WORLD_W)))
        ya = max(0.0, min(ya, FLOOR_Y))
        yb = max(0.0, min(yb, FLOOR_Y))
        # ⛔⛔ 零厚线与矩形**必须用不同的宽度判据**（我第一版共用一条 ⇒ 全被拒）：
        #   矩形下限 4px（太小的块没意义）；
        #   零厚线只要求**主轴**够长，副轴本来就是 0 ——
        #   若套用矩形那条"两边都 ≥4px"，水平线（高 0）永远被拒 ⇒ 直线工具完全不可用。
        if _thin:
            # 主轴长度：水平线看 x跨度，垂直线看 y 跨度
            _main = (xb - xa) if abs(yb - ya) < _THIN_EPS else (yb - ya)
            if _main < 4.0:
                return False
        else:
            if xb - xa < 4.0 or yb - ya < 4.0:
                return False
        self.edit_snapshot()
        self.custom_terrains.append(
            {"kind": k, "x0": float(xa), "y0": float(ya),
             "x1": float(xb), "y1": float(yb)})
        self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom())
        self.update()
        return True

    # ---------------- PR16 · B 段 · 默认平台的「统一列表」 ----------------

    def _edit_all(self) -> list:
        """编辑器里**全部可编辑的地形** ⇒ 自定义层在前，默认 4 条在后。

        ⛔⛔ 顺序**不能反**：既有判据 ⑨-9 断言「点中第一块自定义地形 ⇒ 下标 0」，
            默认层放前面的话那块就变成下标 4，判据红。
        ⛔ 未接管时返回的是 PLATFORMS 的**临时副本**（带 builtin 标记），
           只用于命中/读取；要写回必须先 `_edit_takeover()`。
        """
        bl = self.builtin_terrains
        if bl is None:
            bl = [dict(t) for t in platform_dicts(PLATFORMS)]
            for t in bl:
                t["builtin"] = True
        return self.custom_terrains + bl

    def _room_custom(self) -> list:
        """传给 `Room(custom=...)` 的列表。⛔ builtin 排**前面**
           ⇒ `Room.platforms` 的顺序与默认 PLATFORMS 一致（下游按坐标判贴图，别乱序）。"""
        if self.builtin_terrains is None:
            return self.custom_terrains
        return self.builtin_terrains + self.custom_terrains

    def _edit_takeover(self) -> bool:
        """接管默认 4 条（把它们 copy 进 `builtin_terrains`）。⇒ 是否**刚**接管。

        ⭐ 懒接管：Ronny 没动过默认平台 ⇒ 一直是 None ⇒ 导出仍是 v1/v2，
           PLATFORMS 常量以后改了，他的存档**会跟着更新**（派单方案 1 的缺点被绕开）。
        """
        if self.builtin_terrains is not None:
            return False
        self.builtin_terrains = [dict(t) for t in platform_dicts(PLATFORMS)]
        for t in self.builtin_terrains:
            t["builtin"] = True
        return True

    def _is_floor_sel(self, i: int) -> bool:
        """统一列表第 i 项是不是**默认地板**？⇒ R3（Ronny 拍板）：禁删、禁改 kind。

        ⭐ 判据 = 「默认层的**第一条**」：接管时按 PLATFORMS 顺序 copy，地板是 `[0]`，
           而地板又**不许删** ⇒ 它永远是默认层的第一条 ⇒ 判据恒成立。
        ⛔ 手改 JSON 把顺序调乱的话这条会认错（已记在回执 §未验证）。
        """
        return i == len(self.custom_terrains)

    def _edit_write_at(self, i: int, t: dict) -> None:
        """把改动写回正确的列表。⛔ 写 builtin 段之前调用方必须先 `_edit_takeover()`。"""
        n = len(self.custom_terrains)
        if i < n:
            self.custom_terrains[i] = t
        else:
            self.builtin_terrains[i - n] = t

    def _edit_del_at(self, i: int) -> None:
        """从正确的列表里删掉第 i 项。"""
        n = len(self.custom_terrains)
        if i < n:
            self.custom_terrains.pop(i)
        else:
            self.builtin_terrains.pop(i - n)

    def _edit_hit(self, wx, wy) -> int:
        """点选：命中哪一块地形？⇒ 下标，-1 = 没中。

        ⭐⭐ PR16 · B 段：从「只遍历 custom_terrains」扩成**统一列表**
           （自定义层 + 默认 4 条）⇒ 默认平台现在点得中、拖得动、删得掉。

        ⭐ 命中判据用**顶面下方即算**（x 在区间内且 y >= y0），
           因为玩家关心的是"我点的是它的顶面还是身子里" —— 都算同一块。
        ⭐⭐ 零厚地形（直线工具）**上下都扩 8px**：
           高度只有 0 的话，用户瞄准那条线时点上去会"差一点没中"，
           而"差一点没中"在编辑器里体验极差（看起来像坏了）。
        """
        for i, t in enumerate(self._edit_all()):
            x0, y0, x1, y1 = plat_fields(t)
            _zero_h = abs(float(y1) - float(y0)) < _THIN_EPS
            _zero_w = abs(float(x1) - float(x0)) < _THIN_EPS
            _padx = 10.0 if _zero_w else 0.0
            _pady = 10.0 if _zero_h else 0.0
            if (x0 - _padx) <= wx <= (x1 + _padx) \
                    and (y0 - _pady) <= wy <= (y1 + _pady):
                return i
        return -1

    def _edit_del(self) -> bool:
        # ⭐⭐ PR13：先看有没有选中**新对象**（起点/巡逻/窝/食物）。
        #   ⛔ 顺序不能反 —— 新对象的删除是"恢复默认"，
        #      拿旧的地形删除逻辑去处理会删错东西（或什么都不删）。
        if self.edit_sel_obj and self._edit_del_obj():
            return True
        # ⭐⭐ PR16 · B 段：从「只删自定义层」扩成**统一列表**（默认平台也能删）
        if not (0 <= self.edit_sel < len(self._edit_all())):
            return False
        # ⛔⛔ R3（Ronny 拍板）：**默认地板不可删** —— 删了露娜开局直接掉出世界。
        if self._is_floor_sel(self.edit_sel):
            return self._edit_refuse("默认地板不能删（删了露娜会掉出世界）")
        self.edit_snapshot()
        self._edit_takeover()            # ⭐ 删默认平台 ⇒ 必须先接管
        self._edit_del_at(self.edit_sel)
        self.edit_sel = -1
        self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                         overrides=self._collect_overrides())
        self.update()
        return True

    # ---------------- PR13 · 命中测试 / 删除 ----------------

    # ⭐ 点击判定半径（逻辑px）。⭐ 别设太小：食物就是个小方块，
    #   半径给 14 相当于 34px 的命中圈，远大于视觉尺寸—— 编辑器要的是"好点中"，
    #   不是"像素级精确"。
    _EDIT_OBJ_HIT_R = 14.0

    def _edit_hit_obj(self, wx, wy):
        """点中新对象了吗？⇒ ("food", i) / ("fridge", i) / ("spawn",-1) / None。

        ⭐⭐ **渲染顺序 = 命中顺序**（交接包 §4.3 裁定：
        食物 → 冰箱 → 地形 → 起点/巡逻/窝，起点类最后画）。
           ⛔ 命中测试必须**从后往前**判（先测最后画的那层），
              否则"起点压在食物上"时点中的是下面那个食物 ——
              用户看到起点在上面、点它却改食物，是最难查的一类"界面骗人"。
        """
        r = self._EDIT_OBJ_HIT_R

        def _near(px, py):
            return abs(float(px) - wx) <= r and abs(float(py) - wy) <= r

        # ---- 第 1 层（最后画）：起点/ 巡逻段 / 窝区 ----
        #⛔ 这三个都要**判 None**：用户还没设过时它是 None，
        #   直接解包会TypeError（这正是 PR13 半改的坑）。
        if self.custom_spawn is not None:
            if _near(self.custom_spawn[0], self.custom_spawn[1]):
                #⛔⛔ 返回 "luna_spawn"（**工具名**），不是 "spawn"（**JSON 键名**）。
                #   这两个名字长得一样但不能混：`_edit_del_obj` 拿这个值去比对
                #   EDIT_SINGLE_TOOLS（里面是 "luna_spawn"）⇒ 写成 "spawn"
                #   会静默走进 else 分支，**删除什么都不发生、也不报错**。
                #   ⚠️ 实测踩过：`("spawn",-1)` ⇒ _edit_del() 恒返回 False。
                return ("luna_spawn", -1)
        for nm, val in (("mw_patrol", self.custom_patrol),
                        ("nest", self.custom_nest)):
            if val is None:
                continue
            a, b = float(val[0]), float(val[1])
            # ⭐ 线段命中：x 在 [a,b] 内，且 y 离线的y 够近。
            #   ⛔ 巡逻段/窝区是**水平线段**，用户是横向拖出来的，
            #      按"离线的竖直距离"判才符合直觉。
            yline = (float(FLOOR_Y) if nm == "mw_patrol"
                     else self._nest_draw_y())
            if a - r <= wx <= b + r and abs(wy - yline) <= r:
                return (nm, -1)
        # ⭐⭐ PR23 · 关卡边界：**竖直线**，⛔ 判据与上面两个水平线段不同 ——
        #   它"整高"都可点（没有 y 概念），只要 x 够近就算命中。
        if self.custom_border is not None and abs(float(self.custom_border) - wx) <= r:
            return ("border", -1)
        # ---- 第 2 层：食物 / 冰箱食物 ----
        # ⛔ 从后往前（画在上面的先测）
        if self.custom_fridge is not None:
            for i in range(len(self.custom_fridge) - 1, -1, -1):
                f = self.custom_fridge[i]
                if _near(f["x"], f["y"]):
                    return ("fridge", i)
        if self.custom_stashes is not None:
            for i in range(len(self.custom_stashes) - 1, -1, -1):
                s = self.custom_stashes[i]
                if _near(s["x"], s["y"]):
                    return ("food", i)
        return None

    def _nest_draw_y(self) -> float:
        """窝区在画面上占的**竖直中心 y**（命中测试用）。

        ⛔⛔ 必须跟`_draw_nest` 的画法一致（:4577 `drawRoundedRect(x0, FLOOR_Y-26,
           ..., 30)` ⇒ 占y ∈ [FLOOR_Y-26, FLOOR_Y+4]）。
           ⚠️ 命中判据与画面判据不一致 = 最难查的一类 bug：
              用户照着自己看到的窝点下去，却说"点不中"。
        """
        return float(FLOOR_Y) - 11.0

    def _edit_del_obj(self) -> bool:
        """删掉选中的新对象。⇒ 是否改动了。

        ⭐⭐ **单实例对象（起点/巡逻/窝）的"删除"=恢复默认（置None）**，
           不是"删了就没了"（派单 §2.1）。
           ⛔ 为什么：`custom_spawn = None` 的语义是"不覆盖，用关卡默认"
             （§4.1 的 null 语义）。若删掉就变成"永远没有起点"，
             游戏会崩或走一个从没被设计过的分支。
        """
        sel = self.edit_sel_obj
        if not sel:
            return False
        kind, i = sel
        if kind == "food":
            if self.custom_stashes is None or not (0 <= i < len(self.custom_stashes)):
                return False
            self.edit_snapshot()
            self.custom_stashes.pop(i)
            self.edit_sel_obj = None
        elif kind == "fridge":
            if self.custom_fridge is None or not (0 <= i < len(self.custom_fridge)):
                return False
            self.edit_snapshot()
            self.custom_fridge.pop(i)
            self.edit_sel_obj = None
        elif kind in EDIT_SINGLE_TOOLS:
            self.edit_snapshot()
            # ⭐ 起点对应 `custom_spawn`（字段名去掉了 luna），其余同名
            if kind == "luna_spawn":
                self.custom_spawn = None
            elif kind == "border":                    # ⭐⭐ PR23
                self.custom_border = None
            elif kind == "mw_patrol":
                self.custom_patrol = None
            else:
                self.custom_nest = None
            self.edit_sel_obj = None
        else:
            return False
        self._apply_overrides_now()
        self.update()
        return True

    def _on_destroyed(self):
        """窗口销毁：停音频。⛔ 不断的话进程退不出（QSoundEffect 持有音频线程）。"""
        if getattr(self, "snd", None) is not None:
            self.snd.stop_all()

    # ------------------------------------------------------------ 输入
    def keyPressEvent(self, ev):
        k = ev.key()
        # ⭐⭐ PR12 编辑器按键**最先处理**（在 self.keys.add 之前）。
        #   ⛔⛔ 必须在 `self.keys.add(k)` **之前**返回 —— 否则编辑器按的
        #     Delete/C/Z 会进"按住不放"集合，游戏里被当移动/技能键反复响应。
        #   ⛔ 而 QTE 分支同理（1880 行）也在吃方向键 —— 编辑器优先级最高。
        if self.mode != "play" or k in (Qt.Key_F2, Qt.Key_F4):
            if self._edit_key(k):
                return
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
            # ⭐⭐⭐ PR14：J **不再立即出招**，改为蓄力模型。
            #   ⛔ 别在这里调 try_attack —— 那样"按住"和"点按"没区别。
            #   ⭐ 按下只做两件事：记 charge_t=0、置 charging=True。
            #   出招由两处触发：① `fx_tick` 里达到 ATK_CHARGE2（蓄满自动放）
            #                ② `keyReleaseEvent` 里松手时按 charge_t 定档
            # ⚠️ QTE **不吞 J**（实测：QTE 只吃方向键，见 keyPressEvent 的 QTE 分支）
            #   ⇒ 蓄罐子时可以蓄力攻击 ⛔ 但那是既有行为，本单不改。
            l = self.luna
            # ⛔ 先问三道闸门：冷却/攻击中/冲刺中 → 按了没反应。
            #   ⛔ 不 ask 就直接进charging ⇒ 会出现"冷却中按住 J，
            #   冷却一好自动放招"这种玩家没主动按却打出的一招。
            if l.can_attack() and not l.charging:
                l.charging = True
                l.charge_t = 0.0
                l.atk_fired = False
                # ⭐ 蓄力粒子**立刻**起来（白色聚拢），不等0.30s
                self.fx_spawn("charge", l.x, l.y - 60.0, ATK_TAP,
                              dur=9.9, r=90.0, color=(235, 240, 245))
        elif k == Qt.Key_K:
            # ⭐ 冲刺方向：读当前按着的左右键，没有就沿当前朝向
            d = 0
            if self.keys & {Qt.Key_Left, Qt.Key_A}:
                d = -1
            elif self.keys & {Qt.Key_Right, Qt.Key_D}:
                d = 1
            # 🎵 冲刺声。⭐ 用 `try_dash` 的**返回值**判（冷却中/攻击三段中都会返回
            #   False）⇒ 冲刺没起手就不响，不会"按了键没反应却有声音"。
            #   ⛔ 别在这里无条件播 —— 那会让冷却期的狂按变成机关枪。
            if self.luna.try_dash(d) and self.snd is not None:
                self.snd.play("sfx_dash")

    def keyReleaseEvent(self, ev):
        # ⭐⭐⭐ PR14：J 松手 = 蓄力结算的**第二个触发点**（派单 §4.2）。
        #   charge_t < 0.35 ⇒ 普攻（点按）
        #   已达到阈值      ⇒ ⛔ 什么都不做（招在达到阈值时就放出去了）
        # ⚠️ 顺序很重要：⛔ 必须在 `self.keys.discard` **之前**读 charge_t ——
        #   discard 只清键集不清 charge_t，但反过来写会让人以为这里依赖 keys。
        if ev.key() == Qt.Key_J and self.luna.charging:
            l = self.luna
            if l.atk_fired:
                # 已经放过招了（蓄满自动放的那一次）⇒ 只清蓄力态
                self._fx_stop_charge()
            elif l.charge_t < ATK_CHARGE1:
                # ⭐ 点按 = 普攻。这条是「默认行为不变」的关键：
                #   老版本按一下 J 立刻普攻，现在必须**还是**普攻。
                self._fx_fire(ATK_TAP)
            else:
                # 0.35 ≤ charge_t < 0.70 ⇒ 蓄力 1
                # ⚠️ 若 charge_t >= 0.70，fx_tick 早就自动放了并置 atk_fired，
                #   所以能走到这里的只有 < 0.70。⛔ 不许在这里判"再升一档"。
                self._fx_fire(ATK_C1)
            return
        self.keys.discard(ev.key())

    # ---------------- PR12 · 编辑器 · 鼠标 ----------------
    # ⭐ 世界坐标换算：屏幕像素 → 逻辑 VW×VH → 加 cam_x。
    #   ⛔ 必须除以 self.k（窗口缩放），否则在放大窗口上画出来会整体偏移。
    def _to_world(self, px, py):
        return (px / self.k + self.cam_x, py / self.k)

    def mousePressEvent(self, ev):
        if self.mode != "edit":
            # ⛔ 非编辑态不抢鼠标 —— 游戏里左键不该有任何效果
            return
        wx, wy = self._to_world(float(ev.position().x()), float(ev.position().y()))
        if ev.button() == Qt.LeftButton:
            if self.edit_tool in ("rect", "line"):
                # ⭐ 记录**按下那一刻**的 Shift 状态：Ronny 要求「按下 Shift 时直线只能
                #   垂直或水平」，所以中途松手不该改变这条线的画法。
                self._drag_shift = bool(ev.modifiers() & Qt.ShiftModifier)
                self._drag = (wx, wy, wx, wy)
            elif self.edit_tool in EDIT_LINE_TOOLS:
                # ⭐ 巡逻段/窝区：拖一条水平线段。单点不做事（退化成一个点）。
                self._drag = (wx, wy, wx, wy)
            elif self.edit_tool in ("food", "fridge", "luna_spawn"):
                # ⭐ 点击即放置（单实例工具再点= 移动）。
                #   ⛔ 不进self._drag —— 这些对象没有"两端"概念。
                self._edit_place(wx, wy)
            else:
                # ⭐ select工具：⛔ 必须**先判新对象**再判地形，
                #   否则 custom_stashes=None 时（还没放食物）会 AttributeError。
                hit = self._edit_hit_obj(wx, wy)
                if hit is not None:
                    self.edit_sel_obj = hit
                    self.edit_sel = -1
                    self._move_from = None      # 选中的是「对象」不是地形 ⇒ 不启动地形拖动
                    self._move_orig = None
                    self._move_snap = False
                else:
                    self.edit_sel_obj = None
                    self.edit_sel = self._edit_hit(wx, wy)
                    # ⭐⭐ PR16 · 选中地形 ⇒ 记住拖动起点，之后 mouseMove 就能整体平移它。
                    #   ⛔ 只在这里记**起点**，不在这里 edit_snapshot()：
                    #     「点一下选中但没动」也会 push 撤销栈 ⇒ Ctrl+Z 撤了个寂寞。
                    # ⭐⭐ PR16 · B 段：默认平台也能选中 ⇒ 用**统一列表**的下标
                    if 0 <= self.edit_sel < len(self._edit_all()):
                        self._move_from = (wx, wy)
                        self._move_orig = dict(self._edit_all()[self.edit_sel])
                        self._move_snap = False
                    else:
                        self._move_from = None
                        self._move_orig = None
                        self._move_snap = False
                self.update()

    def mouseMoveEvent(self, ev):
        if self.mode != "edit":
            return
        wx, wy = self._to_world(float(ev.position().x()), float(ev.position().y()))
        # ⭐⭐ PR16 · 拖**已有**地形（F9：原来 `_drag is None` 时第一行就 return，
        #   选中了也拖不动）。
        #   ⛔ 判定顺序：`_drag` 优先（画新地形），`_move_from` 次之（拖旧的）。
        #   ⛔ 只在 select 工具下生效 —— 否则在 rect 工具下"点中了旧块想画新的"会变成拖旧的。
        if self._drag is None:
            if self.edit_tool == "select" and self._move_from is not None \
                    and self._move_orig is not None \
                    and 0 <= self.edit_sel < len(self._edit_all()):
                dx = wx - self._move_from[0]
                dy = wy - self._move_from[1]
                # ⭐⭐ PR20 · B1（Ronny 拍板：地板**可改 y、不可改 x**）：
                #   `LADDERS=(565,488,FLOOR_Y)` 是独立常量，不随平台走。
                #   ⛔ 地板一旦被拖到 `x0 > 0`，左边就没地板了 ⇒ 露娜从最左走会掉出世界；
                #   而且不锁 x 就得手工维护"地板 x 区间 ⊇ 梯子 x"，这正是
                #   「深夜厨房坐标反复推翻」的同一根因 ⇒ 直接锁死。
                if self._is_floor_sel(self.edit_sel):
                    dx = 0.0
                if not self._move_snap:
                    # ⭐ 真的动了才进撤销栈（一次拖动一份，不是每帧一份）
                    #   ⛔ 必须在 `_edit_takeover()` **之前**拍：
                    #      快照里 builtin_terrains=None ⇒ Ctrl+Z 回到"未接管"= 出厂默认。
                    self.edit_snapshot()
                    self._move_snap = True
                self._edit_takeover()     # ⭐ 拖的是默认平台 ⇒ 先接管，再改
                o = self._move_orig
                t = dict(o)
                # ⭐ 四个坐标**同位移** ⇒ 宽高不变（C4 判据）
                t["x0"], t["y0"] = o["x0"] + dx, o["y0"] + dy
                t["x1"], t["y1"] = o["x1"] + dx, o["y1"] + dy
                self._edit_write_at(self.edit_sel, t)
                self.update()
            return
        x0, y0, x1, y1 = self._drag
        # ⭐⭐ PR21 · A2：直线工具的**预览必须与落笔结果一致**（所见即所得）。
        #   ⛔ 改之前只在按 Shift 时才轴对齐预览，不按 Shift 就画斜线预览 ——
        #      而 A2 之后落笔**永远**是轴对齐的 ⇒ 不改这里就是"预览斜、结果直"。
        #   ⭐ Shift = 强制另一轴（与 `_edit_add` 同一判据，两边必须同源）。
        if self.edit_tool == "line":
            _horiz = (abs(wx - x0) >= abs(wy - y0))
            if self._drag_shift:
                _horiz = not _horiz
            x1, y1 = (wx, y0) if _horiz else (x0, wy)
        else:
            x1, y1 = wx, wy
        self._drag = (x0, y0, x1, y1)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self.mode != "edit" or ev.button() != Qt.LeftButton:
            return
        # ⭐⭐ PR16 · 结束「拖旧地形」：把改完的地形重新灌进 Room。
        #   ⛔ 拖动过程中**不重建** Room：重建会换掉 platforms 里的 dict 对象，
        #      而 brittle 状态是用 `id(plat)` 当键存的 ⇒ 每帧重建 = 每帧丢状态。
        #      编辑器的覆盖层画的是 `custom_terrains`，拖的过程中画面本来就是对的。
        if self._move_snap:
            self.room = Room(NIGHTS[self.night_idx], custom=self._room_custom(),
                             overrides=self._collect_overrides())
            self.update()
        self._move_from = None
        self._move_orig = None
        self._move_snap = False
        if self._drag is None:
            return
        x0, y0, x1, y1 = self._drag
        sh = self._drag_shift
        tool = self.edit_tool
        self._drag = None
        # ⭐⭐ 三个分支各走各的：⭐ 顺序不能反 ——
        #   EDIT_LINE_TOOLS 必须**先判**，否则"拖一条线段"会被当成 rect 画出一块地形。
        if tool in EDIT_LINE_TOOLS:
            # ⭐⭐ 顺序不能反 —— EDIT_LINE_TOOLS 必须**先判**，
            #   否则"拖一条线段"会被当成 rect 画出一块地形。
            #⭐ 用 `*self._drag` 解包（不是 `tool, x0, x1`）——
            #   少传一个坐标会 TypeError，比"坐标错位到不知哪"好发现。
            self._edit_set_line(tool, x0, y0, x1)
        else:
            self._edit_add(x0, y0, x1, y1, line=(tool == "line"), shift=sh)

    def mouseDoubleClickEvent(self, ev):
        if self.mode == "edit" and ev.button() == Qt.LeftButton:
            wx, wy = self._to_world(float(ev.position().x()), float(ev.position().y()))
            i = self._edit_hit(wx, wy)
            if i >= 0:
                self.edit_sel = i
                self._edit_del()

    # ---------------- PR12 · 编辑器 · 快捷键 ----------------

    def _edit_key(self, k) -> bool:
        """编辑器按键。⇒ 是否吃掉了这次按键（True=吃掉，别传给游戏）。"""
        # ⛔ 三态：F2↔F3 切 edit/play，F4 = play_custom
        if k == Qt.Key_F2:
            self.set_mode("edit" if self.mode != "edit" else "play")
            return True
        if k == Qt.Key_F4:
            self.set_mode("play_custom")
            return True
        if self.mode != "edit":
            return False
        if k == Qt.Key_Escape:
            self.set_mode("play")
            return True
        # ⭐⭐ PR16 · 视角跳转（一次性动作 ⇒ 走 _edit_key 吃掉，不进 self.keys）
        #   ⛔ 键位冲突已核：`1/2/3`（kind）、`4/5/6/7/8/9/0/-`（工具）、
        #      `S/O/C/Z/Del/Esc/F2/F4/[ ]/, .` 已占用；Home/End/PageUp/PageDown 全空闲。
        if self._edit_pan_jump(k):
            return True
        if k == Qt.Key_Z:                          # Ctrl+Z 撤销
            self.edit_undo()
            return True
        if k == Qt.Key_Delete or k == Qt.Key_Backspace:
            self._edit_del()
            return True
        if k == Qt.Key_1:
            self.edit_kind = "solid";  return True
        if k == Qt.Key_2:
            self.edit_kind = "brittle"; return True
        if k == Qt.Key_3:
            self.edit_kind = "climb";   return True
        # ⭐⭐⭐ PR13：4/5/6 与 7/8/9/0/- 走**同一张表**（EDIT_TOOL_BY_KEY）。
        #   ⛔ 不写成两段 if：PR13 半改时新键位就是因为"没人写"被整体漏掉，
        #      一张表漏一个 key 一眼能看出来，八段 if 漏一个只能靠 grep 才发现。
        if k in EDIT_TOOL_BY_KEY:
            self.edit_tool = EDIT_TOOL_BY_KEY[k]
            # ⭐ 换工具 ⇒ 旧选中态失效（否则在 select 工具下选的食物，
            #    切到rect 再按 [ 还会改它 —— 那是"看不见的操作"）。
            self.edit_sel_obj = None
            self.edit_sel = -1
            return True
        # ---- PR13 · 属性调整（派单 §2.2）：[ ] 换 icon，, . 换 kind ----
        if k in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            self._edit_cycle_sel_prop("icon");  return True
        if k in (Qt.Key_Comma, Qt.Key_Period):
            self._edit_cycle_sel_prop("kind");  return True
        if k == Qt.Key_S:
            try:
                self.export_terrain()
                # ⭐⭐ PR26：文案带条数 + 时长 5 秒
                #   （原来 2.5 秒 + 一整条绝对路径 ⇒ 几百字符顶出屏幕，读不完就消失）
                _n = len(self._room_custom())
                self.msg, self.msg_t = (
                    "✔ 已导出 %d 块地形到 custom_terrain.json" % _n), 5.0
            except OSError as e:
                self.msg, self.msg_t = "导出失败：%s" % e, 3.0
            return True
        if k == Qt.Key_O:
            try:
                n = self.import_terrain()
                self.msg, self.msg_t = "已导入 %d 块" % n, 2.5
            except (OSError, ValueError) as e:
                self.msg, self.msg_t = "导入失败：%s" % e, 3.0
            return True
        if k == Qt.Key_C:
            # ⛔⛔ 清空必须**二次确认**（派单 §3.5）：第一下只提示，再按一次才真删。
            if self._confirm_clear:
                self.edit_clear()
                self._confirm_clear = False
                self.msg, self.msg_t = "已清空自定义地形", 2.0
            else:
                self._confirm_clear = True
                self.msg, self.msg_t = "⚠ 再按一次 C 才真的清空全部", 3.0
            return True
        return False

    # ------------------------------------------------------------ 开一局
    def start_night(self, idx: int):
        cfg = NIGHTS[idx]
        self.night_idx = idx
        # ⭐⭐⭐ PR17 · 乙（Ronny 2026-10-10 拍板）：**正式开局也吃**自定义地形 + 5 类覆盖。
        #   ⛔ 改之前这里是 `Room(cfg)`：不吃 `custom`、不吃 `overrides`
        #      ⇒ 下面那句 `Luna(self.room.spawn_luna...)` 是**死代码**
        #      （`spawn_luna` 恒等于默认 (80, 599)），
        #      ⇒ Ronny 在编辑器里设了起点 2000，点「重新开始」就静默弹回 80。
        #   ⛔ 用的必须是 `_room_custom()`（含已接管的默认平台），
        #      ⛔ 不是 `custom_terrains`（会漏掉 builtin ⇒ 改过的桌布不生效）。
        self.room = Room(cfg, custom=self._room_custom(),
                         overrides=self._collect_overrides())
        # ⭐⭐⭐ PR13：读 room.spawn_luna。⛔ 这一处原来**漏改了**，
        #   它是 start_night() ⇒ 每次开新一局都从这儿构造 Luna
        #   ⇒ 只改 __init__ 的话，Ronny 设了起点 2000、
        #   点「重新开始」就静默弹回80（不报错，只是位置不对）。
        #   ⭐ PR17：上面补上 overrides 之后，这行才**真的**开始生效。
        self.luna = Luna(self.room.spawn_luna[0], self.room.spawn_luna[1],
                         sneak_ok=self._can_play("sneak"))
        # ⭐ PR-06：把「落地」这个事件接给音频。
        #   ⛔ Luna 自己不碰 audio（它拿不到窗口，同 `sneak_ok` 的纪律），
        #     由窗口注入一个回调，物理层只在正确的那一帧喊一声。
        self.luna.on_land = self._on_luna_land
        self.mw = Microwave(cfg, patrol=self.room.mw_patrol)
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
        # ⭐ 潜行 BGM：进档就起，loop=True。
        #   ⛔ 换档要重起（同一实例改loopCount 不等于换曲子）⇒ 先停再起。
        #
        # ⭐⭐ 2026-10-06 PR-05：白天/夜间两套 BGM。
        #   ⚠️ **当前 `NIGHTS` 只剩一档、名字叫「正午」**（见上面 510-524的裁决）
        #      ⇒ 白天关卡就是它。而这里原本起的是**夜间** BGM `bgm_steal`，
        #      ⇒ 设定与音频对不上。
        #   ⇒ 按关卡名分流：`is_day` 为真起 `BGM_DAY_LOOP`（= A 案预拼的无缝循环件），
        #      否则起 `bgm_steal`。⛔ `bgm_steal` 的起播逻辑**一个字都没删**，
        #      夜间档（或以后新增的夜档）照样走原路径。
        #   ⏳ 「白天关卡要不要也叠夜间 BGM」**待 Ronny 拍板**（team-lead 倾向不叠）。
        #      现在的实现是**不叠**（二选一），⛔ 别自己改成叠加。
        #⭐ 白天 BGM 要用哪一条：⛔ 逻辑在模块级 `_level_bgm_name()` 里
        #   （`start_night` 与"押送回窝结束"两处共用一份，见该函数注释）。
        day_bgm = _level_bgm_name(cfg)
        if self.snd is not None:
            #⭐ PR-05：停掉**全部** bgm_*（白天 + 夜间两套共存 ⇒ 枚举停，别列举）
            _stop_level_bgm(self.snd)
            if day_bgm:
                #⭐ 白天 BGM：起的是**离线预拼的无缝循环件**，⛔ 不是源件
                #   （源件硬切会有 14~29 dB 的接缝台阶 —— 实测，见 `audio.py` BGM_DAY_LOOP）
                self.snd.loop(day_bgm)
            else:
                #⭐ 夜间 BGM：原逻辑，⛔ 一行没改
                self.snd.loop("bgm_steal")
        print(f"[夜间] 开局：{cfg['name']}　赃物 {len(self.room.stashes)} 样"
              f"　边界 x={cfg['border_x']:.0f}　追速 {cfg['chase_speed']:.0f}"
              f"　BGM {'白天 ' + day_bgm if day_bgm else '夜间 bgm_steal'}")
        # ⭐⭐ PR21 · A1-2：进游戏时提示一次"存档没载入"。
        #   ⛔⛔ **必须放在最后**（实测踩过）：放前面会被 `self._narrate("enter")`
        #      立刻覆盖成开场旁白 ⇒ 提示在真实游戏里**根本看不见**。
        self._warn_save_not_loaded()

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
        if l.x < self.room.nest[1] + 40 and self.loot_stash:
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
        ⭐⭐ 攻击取走 vs 键取走：只有**动画**不同（攻击在播 attack，见 `pick_action`），
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
        # 🎵 拿容器的声音：**按 kind 选**（loose/plate/jar 三档各有自己的音）。
        #   ⭐ 放在 _make_noise 之后、判fury 之前 —— 三个分支（进frenzy/ 没进 / 攻击拿）
        #   都要听到这一声，所以不能塞进任何一个分支里。
        #   ⛔ 别按容器**离微波炉多远**改音量（那是玩法信息，会变成"听得见的距离"）。
        if self.snd is not None:
            self.snd.sfx_pick(kind)
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

    # ---------------- PR14 · 攻击特效 ----------------

    def fx_spawn(self, kind, x, y, lvl=ATK_TAP, dur=None, r=None, color=None):
        """生成一个特效并挂进 `self.fx`。⇒ 那个 Effect。

        ⭐⭐ **上限保护**：超过 `FX_MAX`(24) 就**丢最旧的**（派单 §3.2）。
           ⛔ 为什么要这个：连点 J 会每帧生成刀光+冲击，不封顶的话
           列表无限涨（内存泄漏）而且旧特效还留在屏幕上互相叠成一团糊。
        ⭐ 只丢一个（`pop(0)`）而不是清空：一次多生成 2~3 个很正常，
           丢一个就够腾出位置，全清会让玩家看到"特效突然消失"。
        """
        _dur = FX_DUR[int(lvl)] if dur is None else float(dur)
        # ⭐ 半径按档位放大（派单 §3.4 的 r0）：档越高冲击范围越大。
        _r = r if r is not None else (26.0 + 12.0 * int(lvl))
        _col = color if color is not None else FX_CLAW_COLOR[int(lvl)]
        e = Effect(kind, x, y, _dur, getattr(self.luna, "face", 1), _r, _col, lvl)
        self.fx.append(e)
        while len(self.fx) > FX_MAX:
            self.fx.pop(0)
        return e

    def fx_tick(self, dt):
        """推进全部特效 + 回收死掉的。⛔ 必须在每个 phase 的绘制之前都跑。

        ⭐ 回收用列表推导一行搞定（派单 §3.2）：`update()` 返回 False 即该移除。
        ⚠️ **蓄力粒子（kind="charge"）是持续的**，它的移除靠 `_fx_stop_charge`
           在松手/出招时显式做——⛔ 不能靠 update 判死，否则按住 J 时
           粒子会在 0.30s 处凭空消失。
        """
        l = self.luna
        # ---- 蓄力推进（⛔ 必须在读 J 之前：先累加，再判阈值）----
        j_held = Qt.Key_J in self.keys
        if l.charging and j_held and not l.atk_fired:
            # ⭐ 封顶在 ATK_CHARGE2：超过就锁住（判据 ⑤「按住 1.5s 只放一次」）
            l.charge_t = min(ATK_CHARGE2, l.charge_t + dt)
            if l.charge_t >= ATK_CHARGE2:
                # ⭐⭐ 达到 2 档**立刻出招并锁定**（不再等松手）——
                #   否则"按住不放永远不出招"是最糟的手感。
                self._fx_fire(ATK_C2)
        # ---- 回收 ----
        if self.fx:
            self.fx = [e for e in self.fx if e.update(dt)]

    def _fx_fire(self, lvl:int):
        """真正放一招（分档）。⇒ 是否成功起手。

        ⭐ 这是**唯一**放招入口（普攻/蓄力1/蓄力2 都走它）⇒
           档位相关的表现与数值**只在这里决定一次**，
           ⛔ 别在别处再判一次档位（两处判必然漂移）。
        """
        l = self.luna
        if not l.try_attack(lvl):
            return False
        l.atk_fired = True
        self._fx_stop_charge()
        # ⭐ 刀光在**出招瞬间**生成（跟着爪子轨迹，不是命中帧）
        self.fx_spawn("claw", l.x + l.face * 30.0, l.y - 60.0, lvl)
        # ⭐蓄力 2 的"炸开"冲击在**命中帧**才生成（见 _resolve_attack_hit）
        return True

    def _fx_stop_charge(self):
        """结束蓄力态 + 清掉蓄力粒子。

        ⭐ 出招 / 松手 / 进入别的情况都要走这里 —— ⛔ 别各自写一遍
           `self.fx = [e for e in self.fx if e.kind != "charge"]`，
           漏一处就有粒子永久挂在屏幕上。
        """
        self.luna.charging = False
        self.luna.charge_t = 0.0
        self.luna.atk_fired = False
        if self.fx:
            self.fx = [e for e in self.fx if e.kind != "charge"]

    def _resolve_attack_hit(self):
        """在攻击的**命中窗口**内结算一次。⛔ 每次攻击只结算一次（atk_hit_done）。

        ⭐⭐ 一次挥击可能同时够到【容器】和【守卫】—— 玩家自己选的站位，
           两个都结算（代价一起付）。这让"贴着罐子站在它面前打"变成一个
           高风险高回报的选项，而不是"只有守卫被打"。
        """
        l = self.luna
        if l.atk_hit_done or not l.in_atk_window():
            return
        # 🎵 挥击声。⭐ 放在**结算之前**（不是"打中才响"）——
        #   挥空也该有反馈音，否则玩家分不清"没打中"和"没出手"。
        if self.snd is not None:
            self.snd.play("sfx_attack")
        # ⭐ 判定是**身前单向**：|dx| <= ATK_REACH 且方向一致
        #   （⛔ 别用圆形范围 —— 那意味着她能打到背后，潜行的"绕后"就没意义了）
        hit_any = False
        # --- ① 守卫 ---
        mw = self.mw
        if (abs(l.x - mw.x) <= ATK_REACH + mw.w * 0.5
                and abs(l.y - mw.y) <= ATK_DY
                and (mw.x - l.x) * l.face >= -18.0):
            # ⭐⭐ PR14：击退按档位取（普攻 260 / 蓄力1 312 / 蓄力2 338）。
            #   ⛔ **只改击退数值，不改作用对象**（实测全文件只有这一处
            #   消费 ATK_KNOCK ⇒ 他一直是"击退微波炉"，不是击退露娜）。
            #   ⛔ 别顺手也把容器那边改了：容器是"撬开"，没有位移。
            mw.hit_by(l.x, ATK_KNOCK_TABLE[l.atk_lvl], ATK_STUN)
            hit_any = True
            self._say("啪！")
            # ⭐ 冲击特效在**命中帧**生成（不是出招帧）——
            #   挥空不该有冲击波，命中了才有"打到了"的实感。
            _gold = (l.atk_lvl == ATK_C2)
            self.fx_spawn("impact", mw.x, mw.y - 90.0, l.atk_lvl,
                          r=(26.0 + 12.0 * l.atk_lvl) * (1.6 if _gold else 1.0),
                          color=FX_IMPACT_GOLD if _gold else (255, 236, 200))
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
        if not FRIDGE_ENABLED:
            return False          # ⭐ 冰箱没了 ⇒ 永远不触发开冰箱 QTE
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
        # ⛔ 2026-10-05 Ronny「冰箱音效**彻底移除**」⇒ 这里曾播 sfx_fridge_open，
        #   现已连同素材一起删除（`assets_audio/` 下也没有了）。
        #   ⛔ 别把它加回来 —— QTE 仍有 `sfx_qte_tick`（每按键）与 `sfx_qte_fail`
        #   提供反馈，**开冰箱那一下是静音的**，这是有意的。
        #   ⛔ 别动下面这行 `_make_noise`：**守卫听觉**与**玩家听觉**是两套系统，
        #   删音效不影响他听不听得见撬门声。
        self._make_noise(FRIDGE["x"], NOISE_MAX * 0.55)   # 撬门本身有点响（比敲容器轻）

    def _qte_step(self, key):
        """按一个键。返回 True 表示这次输入被 QTE 吃掉了。"""
        q = self.qte
        if not q:
            return False
        # 🎵 QTE 每按一下都响。⛔ 用 008 版（0.08s那条）——
        #   0.48s 那条在 0.95s 的时限里会盖住下一个键的反馈。
        if self.snd is not None:
            self.snd.sfx_qte_tick()
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
        # 🎵 QTE 失败
        if self.snd is not None:
            self.snd.play("sfx_qte_fail")
        # ⛔ 惩罚是"微波炉警觉 + 噪音"，⛔ 不是直接失败/丢命（玩法文档：惩罚要轻）
        self.mw.alert = min(1.0, self.mw.alert + QTE_FAIL_ALERT)
        self.mw.hear_x = FRIDGE["x"]
        if self.mw.alert >= 1.0:
            self.mw.state = "chase"
        self._make_noise(FRIDGE["x"], NOISE_MAX * 0.8)
        self._say("哐——！")

    def _on_luna_land(self):
        """露娜从空中落到实地（唯一的落地音入口，PR-06）。

        ⭐ 由 `Luna.update` 的落点判定在「空中→地面」那一帧调用一次。
        ⛔ **爬梯落地不进来**：爬梯那三处（爬到台面沿 / 爬到顶 / 爬到底）
           各自把`on_ground` 置True 后直接返回，走不到这个落点分支。
        """
        if self.snd is not None:
            self.snd.play("sfx_land")

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
        # 🎵 结算 sting。⭐ **只播一次**。
        #   ⚠️ 旧版是"播完循环同一段" —— sting 换成 3.5 秒短件后，
        #      那个循环每 3.5 秒重播一次，短动机很明显（设计端 2026-10-05 拍板改掉）。
        #   ⭐ 面板**不限时**（玩家可以一直看）⇒ 面板上**只有这一声 sting**，
        #      没有循环底音（原先的"降环境音当底音"那一路已随 PR-06 删干净）。
        #   ⭐ 潜行 BGM 在这里让位：结算已经是"这一趟结束了"，两段音乐叠着会像没结束。
        if self.snd is not None:
            # ⭐ PR-05：白天 BGM 也要让位，⛔ 否则它在**不限时**的结算面板上继续响
            _stop_level_bgm(self.snd)
            self.snd.sting("bgm_win")
        self._narrate("finish" if left == 0 else "home")
        print(f"[夜间] 结算：带回 {n} 件（价值 {vsum}）剩 {left} 被抓 {self.caught_cnt} "
              f"用时 {self.night_t:.0f}s → {rank}（{self.result['score']}）")

    # ------------------------------------------------------------ 循环
    def _step_cam(self, dt):
        """⭐⭐ 2026-10-05 PR-03：横向镜头跟随。**只平移不缩放**。

        规格（派单 §三，按图实现不自己发挥）：
            want = clamp(露娜.x - 640, 0, 2560)
            cam_x += (want - cam_x) * min(1.0, dt * CAM_X_LAG)

        ⭐ 死区：露娜在 cam_x+640 ± CAM_X_DEAD 内移动 ⇒ **镜头一帧都不动**
          （不是减速，是完全不动 —— 派单 §三明确要求）
        ⛔ 不做预测式/前瞻式跟随：露娜急停时画面会往前甩一下，很廉价。

        ⚠️ 独立成方法（不内联在 _tick 里）的理由：自测要能用**假时钟**逐帧驱动它，
          offscreen 下真实 dt≈0.0001s，混在 _tick 里根本没法验「无跳变」。
        """
        want = self.luna.x - CAM_X_CENTER
        want = 0.0 if want < 0.0 else (CAM_X_MAX if want > CAM_X_MAX else want)
        # ⭐ 死区：完全不动
        if abs(self.luna.x - CAM_X_CENTER - self.cam_x) < CAM_X_DEAD:
            return
        self.cam_x += (want - self.cam_x) * min(1.0, dt * CAM_X_LAG)
        # ⛔ 收敛后必须**夹回**区间。指数逼近不会越界，但浮点会留下 2560.0000001
        #   这种尾巴，而「cam_x ∈ [0,2560]」是硬验收线（逐帧断言 5000 帧）。
        if self.cam_x < 0.0:
            self.cam_x = 0.0
        elif self.cam_x > CAM_X_MAX:
            self.cam_x = float(CAM_X_MAX)

    # ⭐⭐⭐ PR16 · 编辑态手动平移（⛔ 与 _step_cam 完全独立，互不相干）
    def _edit_pan_cam(self, dt):
        """编辑态「按住 A/D 或 ←/→ 挪视野」。

        ⛔⛔ 为什么**不写在 `_edit_key` 里**（派单 §A.3 的重点）：
            `_edit_key` 返回 True 会在 `self.keys.add(k)` **之前** return
            （keyPressEvent 里 `:3381-3388` 的注释明写）
            ⇒ A/D 根本进不了 `self.keys` ⇒ 做不出「按住持续平移」，只能一格一格点。
            ⇒ 所以 A/D、←/→ **故意不写进 `_edit_key`**，让它们正常进 `self.keys`，
              由本方法每帧读。

        ⛔ 只 clamp 到 [0, CAM_X_MAX]，与 play 的硬验收线同一区间。
        ⛔ 必须自己 `self.update()`：edit 分支在 `self.update()`（_tick 末）**之前**
           就 return 了 ⇒ 不主动请求重绘，画面一帧都不动。
        """
        d = 0.0
        if Qt.Key_A in self.keys or Qt.Key_Left in self.keys:
            d -= 1.0
        if Qt.Key_D in self.keys or Qt.Key_Right in self.keys:
            d += 1.0
        if d:
            self.cam_x = max(0.0, min(float(CAM_X_MAX),
                                      self.cam_x + d * EDIT_CAM_SPEED * dt))
            self.update()

    def _edit_pan_jump(self, k) -> bool:
        """PR16 · 跳转键（Home / End / PageUp / PageDown）⇒ 是否吃掉。

        ⭐⭐ 这些**走 `_edit_key`**（return True 吃掉）：它们是一次性动作，
            不需要「按住持续」，所以不必进 `self.keys`
            （进去了反而会在 play 里被当移动键残留）。
        ⛔ 全部 clamp 到 [0, CAM_X_MAX] —— 与 C1 判据同一区间。
        """
        if k == Qt.Key_Home:
            self.cam_x = 0.0
        elif k == Qt.Key_End:
            self.cam_x = float(CAM_X_MAX)
        elif k == Qt.Key_PageUp:
            self.cam_x = max(0.0, self.cam_x - float(VW))
        elif k == Qt.Key_PageDown:
            self.cam_x = min(float(CAM_X_MAX), self.cam_x + float(VW))
        else:
            return False
        self.update()
        return True

    def _tick(self):
        import time
        now = time.perf_counter()
        dt = 0.016 if self._last is None else min(0.033, now - self._last)
        self._last = now

        # ⭐⭐ PR12 编辑态：**不跑物理**（露娜/微波炉/容器都不动）。
        #   ⛔ 为什么必须分流：编辑时她还在往地形里走，玩家以为在改图，
        #     结果她被自己刚画的平台顶到空中 ⇒ 画面乱、还以为是 bug。
        #   ⭐ 但计时器（msg_t 之类）照跑，否则提示语永远不消失。
        if self.mode == "edit":
            if self.msg_t > 0:
                self.msg_t -= dt
            # ⭐⭐ PR16 · 编辑态手动平移镜头。
            #   ⛔ 必须放在这里：`_tick` 的 play 路径才调 `_step_cam`，
            #      而 edit 在上面就 return 了 ⇒ 不在这儿调，编辑态 cam_x 永远冻结
            #      （实测根因 F1/F2）。
            self._edit_pan_cam(dt)
            return

        l, mw = self.luna, self.mw
        # ⭐⭐ PR14：特效推进 + 蓄力判定。
        #   ⭐ 位置很讲究：在 `edit` 早退**之后**（编辑态不跑特效），
        #     在 `l.update` **之前**（蓄力累加要赶在这一帧的物理之前，
        #     否则玩家松手判定会晚一帧）。
        self.fx_tick(dt)
        # ⭐⭐ PR12：brittle 计时器每帧推进（③ 恢复）。
        #   ⛔ 放在物理之前：这样「这一帧踩上去」用的是本帧开始时的状态，
        #     不会出现"踩的同一帧就立刻恢复"的时间穿越。
        # ⛔ 放在 menu 态不跑 ⇒ 没开局时地形不动（避免编辑器改完看到地面自己变）。
        if self.phase != "menu":
            self.room.tick_brittle(dt)
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
            # ⭐ PR-03：镜头必须在**角色位置更新之后**推进，否则会慢一帧。
            self._step_cam(dt)
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
            if l.x < self.room.nest[1] and l.carrying:
                self.loot_stash.extend(l.carrying)
                l.carrying = []
                self._narrate("drop")
            elif mw.caught(l) and l.x > self.room.border_x:
                self.phase = "meowed"
                self.phase_t = 0.0
                self.caught_cnt += 1
                self.qte = None             # ⭐ 被抓时 QTE 必须作废（否则按键还在喂一个死 QTE）
                # 🎵 被抓：mw_alert（他发现了）+ caught（她被逮住）+ sting（被抓底音）
                #   ⚠️ 三条同时响是**故意的**：这是全局最戏剧的一帧，
                #   压掉任何一条都会让"被抓"听起来像"普通事件"。
                #   ⭐ BGM 要让位—— 不让的话潜行曲会盖住这三声。
                #   ⭐ sting 走 `sting()` 而不是 `play()`：它保证只响一次、
                #     不会在押送动画里被叠成第二层（旧的"降环境音当底音"已删）。
                if self.snd is not None:
                    #⭐ PR-05：⛔ 原先这里只停 `bgm_steal`，
                    #   加了白天 BGM 之后会**漏停白天那条**（⛔ 它会盖住这三声）。
                    #⭐⭐ 2026-10-06 BGM 起播修复：停完之后**必须重起**，
                    #   否则这一局剩下的时间**永远没有 BGM**（见 hauled→play 那处）。
                    _stop_level_bgm(self.snd)
                    self.snd.play("sfx_mw_alert")
                    self.snd.play("sfx_caught")
                    self.snd.sting("bgm_caught")
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
            tx, ty = min(self.room.nest[0] + 70, self.room.nest[1]), float(FLOOR_Y)
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
                # ⭐⭐ 2026-10-06 BGM 起播修复（verifier 实测挖出的既存bug）。
                #   病征：`meowed` 分支里 `_stop_level_bgm()` 把这一档的 BGM 停了，
                #   而**从 hauled 回到 play 的这条路径上没有任何地方重起它**
                #   ⇒ 玩家被抓一次之后，这一局**剩下的时间永远没有 BGM**，
                #     而且它**不报错、不崩、也没有任何自测会红**（没有判据守它）。
                #   ✅ 修法：回到 play 的瞬间按同一份分流重起。
                #   ⭐ 走 `_level_bgm_name()`（与 `start_night` 同一份逻辑），
                #   ⛔ 别在这里再写一遍"白天起白天/夜里起夜里" ——
                #     两处各写一份的代价就是本bug 本身。
                #   ⚠️ 停在meowed 的那一声 `bgm_caught` sting 是**一次性**播放，
                #      不在 `_loops` 里 ⇒ 这里重起**不会**把它叠成两层。
                if self.snd is not None:
                    _bgm = _level_bgm_name(NIGHTS[self.night_idx])
                    if _bgm:
                        self.snd.loop(_bgm)
                    else:
                        self.snd.loop("bgm_steal")

        # 动作推进
        a = l.pick_action()
        if a != l.act:
            l.act, l.t = a, 0.0
        act = self.pack.actions.get(a)
        # ⭐ GAME_FPS 优先（夜间覆盖），没配的才用桌宠动作自带的 fps。
        #   ⛔ 别写反：`GAME_FPS.get(a, act.fps if act else 10.0)` ——
        #   那样"配了但取不到"会静默回退到桌宠值，改了 GAME_FPS 却毫无反应，
        #   那是最难查的一种"改了没生效"。
        _fps = GAME_FPS.get(a)
        fps = _fps if _fps is not None else (act.fps if act else 10.0)
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

        # ⭐⭐ 2026-10-05 PR-03：菜单态**不跟随**（她固定在窝里等着，镜头没意义）。
        #   ⛔ 菜单不跟 = 玩家看不到"地图有多大"，但菜单本来就是选档界面。
        if self.phase == "menu":
            # ⭐⭐⭐ PR19 · 编辑态走**美术底图**（与游戏态同源）⇒ 所见即所得。
            #   ⛔ 改之前这里画的是 `_draw_bg` —— 那是**程序画的渐变 + 一只写死的假窗户**，
            #      而游戏态画的是 `_draw_bg_slices`（3 张美术切片）⇒ **两套完全不同的底图**
            #      ⇒ 在编辑器里对的位置，进了游戏必然偏。
            #   ⛔ 下面这串调用的**顺序与 translate 方式必须与游戏态逐字一致**
            #      （都是 `translate(-cam_x)` 包住整条链）⇒ 否则二次偏移，历史踩过。
            #   ⛔ `_draw_bg` 一个字都没改（menu 选关界面靠它做氛围）。
            #   ⛔⛔ **刻意不画 `_draw_platforms`**（派单 §3）：它在游戏态会按
            #      `which_part()` 程序贴家具图，而美术底图里家具已经画好了 ⇒ 游戏态有重影。
            #      编辑态不贴 ⇒ Ronny 看到的是干净的美术底图（见回执 §4 的实测与提醒）。
            if self.mode == "edit":
                p.save()
                p.translate(-self.cam_x, 0.0)
                self._draw_zone(p)
                self._draw_bg_slices(p)
                if self.bg_img is not None:
                    self._draw_nest(p)
                    self._draw_stashes(p)
                    self._draw_fridge(p)
                    # ⭐ PR19 §2：编辑态**必须**看得见微波炉 —— Ronny 要设巡逻段，
                    #   看不见它就画不准。编辑态 `_tick` 早退 ⇒ 它不会动，正好当参照物。
                    # ⭐⭐ PR20 · A2：画在**巡逻段中点**（没设巡逻段才退回 `self.mw.x`）
                    _pat = self._collect_overrides().get("mw_patrol")
                    self._draw_mw(p, x_override=((_pat[0] + _pat[1]) / 2.0)
                                  if _pat else None)
                    self._draw_fx_behind(p)
                    self._draw_luna(p)
                    self._draw_fx_front(p)
                self._draw_edit_overlay(p)
                p.restore()
                self._draw_edit_toolbar(p)
                p.end()
                return
            self._draw_bg(p)
            self._draw_nest(p)
            self._draw_fx_behind(p)
            self._draw_luna(p)
            self._draw_fx_front(p)
            self._draw_menu(p)
            # ⭐⭐ PR12 编辑态：**画在 menu 之后**（盖在上面），但镜头 translate 还没开始，
            #   所以要自己平移。地形必须**立即可见**（派单 §3.2 明确要求）。
            if self.mode == "edit":
                p.save()
                p.translate(-self.cam_x, 0.0)
                self._draw_edit_overlay(p)
                p.restore()
                self._draw_edit_toolbar(p)
            p.end()
            return

        # ⭐⭐ 横向相机：世界坐标 → 视口坐标。**只平移不缩放**（缩放跟随会让
        #   按 1cm=3.3px 算死的地形/跳跃/巡逻数值全部失效 —— 派单硬约束）。
        #   ⛔ 背景在最底层**不进这个 translate**：它是固定在视口上的，
        #      否则会出现"背景跟着一起滑、再叠加三层背景"的二次偏移。
        p.save()
        p.translate(-self.cam_x, 0.0)
        self._draw_zone(p)
        # ⭐⭐⭐ 背景板：3 张 1280 切片按 cam_x 选可见的那两张。
        #   ⛔ 切片尚未回传（BG-02bG1 判废）⇒ 有几张画几张，绝不崩。
        self._draw_bg_slices(p)
        if self.bg_img is not None:
            self._draw_nest(p)
            self._draw_stashes(p)
            self._draw_fridge(p)
            self._draw_mw(p)
            self._draw_fx_behind(p)
            self._draw_luna(p)
            self._draw_fx_front(p)
            p.restore()
            # ⭐ HUD 画在相机之外（固定在视口）—— 否则血条会跟着世界滑走
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
        self._draw_fx_behind(p)
        self._draw_luna(p)
        self._draw_fx_front(p)
        p.restore()
        self._draw_hud(p)
        if self.phase == "meowed":
            self._draw_meowed(p, self.phase_t)
        if self.phase == "result":
            self._draw_result(p)
        p.end()

    # ============================ PR12 · 编辑器绘制 ============================
    # ⭐ 三种地形三色（派单 §3.4「不同颜色预览」）：
    #     solid= 木色 / brittle= 橙红（醒目，因为它会消失）/ climb= 青蓝（能爬）
    #   ⛔ 颜色只在**编辑器**里用；游戏里地形是贴图/程序画，不受影响。
    _EDIT_COLOR = {"solid": (150, 190, 230), "brittle": (236, 140, 96),
                   "climb": (120, 220, 170)}
    _EDIT_KIND_CN = {"solid": "永久", "brittle": "短暂消失", "climb": "攀爬"}

    def _draw_edit_overlay(self, p):
        """画全部可编辑地形 + 拖拽预览（已在translate(-cam_x) 的坐标系里）。

        ⭐⭐ PR16 · B 段（Ronny 拍板「方案 1」）：默认 4 平台**接管后**也画成
           可编辑的彩色块（带「默认」标签）；**未接管**时仍是 PR12 的只读虚线参照。
        """
        _n_c = len(self.custom_terrains)
        _bl = self.builtin_terrains
        # ---- 统一遍历 `_edit_all()`（自定义在前、默认 4 条在后）----
        #   ⛔⛔ 两处坑（都是我实测读出来的，派单没列）：
        #     ① PR16 方案 1 全集模式下 `Room.platforms` 只剩 custom ⇒ 原来那句
        #        `platforms[:len(PLATFORMS)]` 会把 custom 前 4 条**再画一层只读虚线框**
        #        ⇒ 重影。所以只读参照层**不再单独画**，统一在这里按条目画。
        #     ② PR17 · P2-2：未接管时原来只遍历 `custom_terrains`
        #        ⇒ 选中默认平台**画面完全没高亮**（能删能拖，但看不出选中了）。
        #        ⇒ 现在一律遍历统一列表，未接管的默认条用**灰蓝虚线**表示"只读参照"，
        #          但选中时**照样加粗高亮**。
        for i, t in enumerate(self._edit_all()):
            _pending = (_bl is None and i >= _n_c)   # 未接管的默认平台
            x0, y0, x1, y1 = plat_fields(t)
            c = self._EDIT_COLOR.get(plat_kind(t), (200, 200, 200))
            if _pending:
                c = (128, 138, 158)                  # 灰蓝 = 只读参照（PR12 的观感）
            sel = (i == self.edit_sel)
            # ⭐ brittle 正在消失 ⇒ 画成半透明（游戏里也一样，这里是编辑期预览）
            alive = True
            if plat_kind(t) == "brittle":
                # ⛔ 编辑态下 room 可能是旧实例（没重建），查不到就当活着
                # ⭐ PR16 · B 段：全集模式下 platforms 里**没有**默认 4 条前缀，
                #   偏移量要跟着变（否则查到的是错的那块地）
                _off = len(_bl) if _bl is not None else len(PLATFORMS)
                try:
                    alive = self.room.brittle_active(
                        id(self.room.platforms[_off + (i - _n_c)]))
                except (AttributeError, IndexError):
                    alive = True
            a = 200 if alive else 70
            # ⭐⭐ 零厚地形（直线工具画的水平线/垂直线）必须**单独画**：
            #   drawRect 高度 0 时什么都不画 ⇒ 用户画完「看不见」，
            #   会以为工具坏了。零厚画成 3px 宽的实心条。
            _th = max(3.0, float(y1) - float(y0))
            _ty = y0 if abs(float(y1) - float(y0)) >= _THIN_EPS else (y0 - _th / 2.0)
            # ⭐ PR17 · P2-2：未接管的默认条画**虚线**（= 只读参照的观感），
            #   但**选中时照样加粗到 3px** ⇒ Ronny 点它时看得见自己选中了。
            p.setPen(QPen(QColor(c[0], c[1], c[2], 150 if _pending else a),
                          3 if sel else (1 if _pending else 2),
                          Qt.DotLine if _pending else Qt.SolidLine))
            p.setBrush(Qt.NoBrush if _pending
                       else QColor(c[0], c[1], c[2], 70 if alive else 24))
            p.drawRect(QRectF(x0, _ty, max(3.0, float(x1) - float(x0)), _th))
            # ⭐ 名字标在块内（左上），删了名字就不知道选中的是哪块
            p.setPen(QColor(c[0], c[1], c[2], a))
            p.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            _cn = self._EDIT_KIND_CN.get(plat_kind(t), "?")
            # ⭐ PR16 · B 段：默认平台标「默认」⇒ Ronny 一眼分清哪条是 PLATFORMS 里的
            # ⭐ PR17：未接管的加「未接管」⇒ 他知道自己一动就会把它固化进存档
            if i >= _n_c:
                _cn = ("默认(未接管) " if _pending else "默认 ") + _cn
            p.drawText(QPointF(x0 + 4, y0 + 14), _cn)
        # ---- 拖拽中的预览 ----
        if self._drag is not None:
            x0, y0, x1, y1 = self._drag
            xa, xb = min(x0, x1), max(x0, x1)
            ya, yb = min(y0, y1), max(y0, y1)
            c = self._EDIT_COLOR.get(self.edit_kind, (200, 200, 200))
            p.setPen(QPen(QColor(c[0], c[1], c[2], 230), 2, Qt.DashLine))
            p.setBrush(QColor(c[0], c[1], c[2], 46))
            p.drawRect(QRectF(xa, ya, xb - xa, yb - ya))
            # ⭐ 实时尺寸：拖的时候就知道多大，不用事后量
            p.setPen(QColor(240, 240, 240))
            p.setFont(QFont("Microsoft YaHei", 10))
            p.drawText(QPointF(xa + 4, ya - 4),
                       "%d × %d" % (int(xb - xa), int(yb - ya)))

        # ---------------- PR13 · 5 类新对象 ----------------
        # ⭐⭐ **渲染顺序 = 交接包 §4.3 裁定的顺序**（也是命中测试的逆序）：
        #    食物 → 冰箱食物 → 地形 → 起点/巡逻/窝
        # ⭐⭐⭐ **起点类必须最后画** —— 它是"关卡开局位置"，最需要永远可见；
        #    若先画就会被自定义地形盖住，用户会以为没放成功。
        self._draw_edit_foods(p)
        self._draw_edit_fridge(p)
        self._draw_edit_lines(p)
        self._draw_edit_spawn(p)
        # ---- 拖拽中的预览（巡逻段 / 窝区）----
        if self._drag is not None and self.edit_tool in EDIT_LINE_TOOLS:
            x0, _y0, x1, _y1 = self._drag
            a, b = sorted((float(x0), float(x1)))
            c = (150, 190, 255) if self.edit_tool == "mw_patrol" else (255, 170, 200)
            yline = (float(FLOOR_Y) if self.edit_tool == "mw_patrol"
                     else self._nest_draw_y())
            p.setPen(QPen(QColor(c[0], c[1], c[2], 230), 2, Qt.DashLine))
            p.drawLine(QPointF(a, yline), QPointF(b, yline))
            p.setPen(QColor(c[0], c[1], c[2]))
            p.setFont(QFont("Microsoft YaHei", 10))
            p.drawText(QPointF((a + b) / 2 - 20, yline - 8),
                       "%d" % int(b - a))

    def _draw_edit_foods(self, p):
        """地面/台面容器：小方块（按 kind 三色）+ icon 名（派单 §2.4）。"""
        if not self.custom_stashes:
            return
        for i, s in enumerate(self.custom_stashes):
            c = FOOD_KIND_COLOR.get(s["kind"], (200, 200, 200))
            x, y = float(s["x"]), float(s["y"])
            sel = (self.edit_sel_obj == ("food", i))
            a = 255 if sel else 200
            p.setPen(QPen(QColor(c[0], c[1], c[2], a), 3 if sel else 2))
            p.setBrush(QColor(c[0], c[1], c[2], 90 if sel else 55))
            p.drawRect(QRectF(x - 11, y - 11, 22, 22))
            # ⭐ 名字标在下方：icon 名太长会盖住方块本体
            p.setPen(QColor(c[0], c[1], c[2], a))
            p.setFont(QFont("Microsoft YaHei", 9))
            p.drawText(QPointF(x - 26, y + 26), s["icon"])

    def _draw_edit_fridge(self, p):
        """冰箱内食物：菱形（派单 §2.4「另一种形状」）。

        ⭐ 形状必须与地面食物**明显不同** —— 两者都是"食物"，
           只靠颜色区分在低分辨率下分不出来。
        ⭐ 顺带把冰箱轮廓画出来：否则自定义食物放在冰箱外时，
           用户根本不知道自己在往哪放。
        """
        fx0, fy = float(FRIDGE["x"]), float(FRIDGE["y"])
        fx1, fy0 = fx0 + float(FRIDGE["w"]), fy - float(FRIDGE["h"])
        p.setPen(QPen(QColor(120, 170, 220, 90), 1, Qt.DotLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(fx0, fy0, fx1 - fx0, fy - fy0))
        if not self.custom_fridge:
            return
        for i, f in enumerate(self.custom_fridge):
            c = (150, 220, 255)
            x, y = float(f["x"]), float(f["y"])
            sel = (self.edit_sel_obj == ("fridge", i))
            a = 255 if sel else 200
            p.setPen(QPen(QColor(c[0], c[1], c[2], a), 3 if sel else 2))
            p.setBrush(QColor(c[0], c[1], c[2], 90 if sel else 55))
            # ⭐ 菱形 = 两个等腰三角形拼，Qt 没有 drawPolygon 简化写法
            p.drawPolygon(QPolygonF([QPointF(x, y - 13), QPointF(x + 13, y),
                                     QPointF(x, y + 13), QPointF(x - 13, y)]))
            p.setPen(QColor(c[0], c[1], c[2], a))
            p.setFont(QFont("Microsoft YaHei", 9))
            p.drawText(QPointF(x - 26, y + 28), f["icon"])

    def _draw_edit_lines(self, p):
        """巡逻段 + 窝区：水平线段 + 两端刻度（派单 §2.4）。"""
        for nm, val, col, label in (
                ("mw_patrol", self.custom_patrol, (150, 190, 255), "巡逻段"),
                ("nest", self.custom_nest, (255, 170, 200), "NEST")):
            if val is None:
                continue
            a, b = float(val[0]), float(val[1])
            yline = float(FLOOR_Y) if nm == "mw_patrol" else self._nest_draw_y()
            sel = (self.edit_sel_obj == (nm, -1))
            al = 255 if sel else 190
            p.setPen(QPen(QColor(col[0], col[1], col[2], al), 3 if sel else 2))
            p.drawLine(QPointF(a, yline), QPointF(b, yline))
            # ⭐ 两端刻度：让"这段的左右端在哪"一眼可见
            for xx in (a, b):
                p.drawLine(QPointF(xx, yline - 9), QPointF(xx, yline + 9))
            p.setPen(QColor(col[0], col[1], col[2], al))
            p.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            p.drawText(QPointF((a + b) / 2 - 22, yline - 14), label)
            # ⭐ 巡逻段额外画中点小方块 = 微波炉的起点（派单 §2.4）：
            #   让"他站在哪"和"他走哪"在一张图里同时可见。
            if nm == "mw_patrol":
                mid = (a + b) / 2.0
                p.setPen(QPen(QColor(col[0], col[1], col[2], al), 2))
                p.setBrush(QColor(col[0], col[1], col[2], 120))
                p.drawRect(QRectF(mid - 7, yline - 40, 14, 14))

        # ⭐⭐ PR23 · 关卡边界：一条**竖直虚线**（整高）。
        #   ⛔ 未设时也画一条淡的"关卡默认" ⇒ Ronny 能看见边界本来在哪，
        #      才知道自己把它拖到了哪（不然会以为"边界没生效"）。
        _bx = (self.room.border_x if self.custom_border is None
               else float(self.custom_border))
        _bsel = (self.edit_sel_obj == ("border", -1))
        _bset = (self.custom_border is not None)
        # ⭐⭐ PR28（Ronny：「安全区域不太会用」）：**禁区染色**。
        #   ⛔ 为什么必须画：边界线只说明"在这儿"，却没说"哪边是禁区"，
        #   而 `border_x` 的真实语义是**微波炉的行为开关**（越界才追她），
        #   ⛔ 不是一堵墙 ⇒ Ronny 看不出染色就会以为"边界和地形一样能撞"。
        #   ⇒ 禁区盖一层**半透明红**，安全区盖一层**半透明青**，一眼分清。
        #   ⚠️ 必须在 translate(-cam_x) 之内（此处已在）⇒ 与地形同一坐标系。
        _vis_x0 = float(self.cam_x) - 4.0
        _vis_x1 = float(self.cam_x) + float(VW) + 4.0
        _safe_w = max(0.0, min(_bx, _vis_x1) - _vis_x0)
        if _safe_w > 0.0:
            p.fillRect(QRectF(_vis_x0, 0.0, _safe_w, float(VH)),
                       QColor(40, 150, 190, 26))      # 安全区（可安心行动）
        _risk_x0 = max(_bx, _vis_x0)
        _risk_w = _vis_x1 - _risk_x0
        if _risk_w > 0.0:
            p.fillRect(QRectF(_risk_x0, 0.0, _risk_w, float(VH)),
                       QColor(220, 60, 50, 34))        # 禁区（微波炉会追）
        _bcol = (255, 170, 120) if _bset else (140, 150, 170)
        p.setPen(QPen(QColor(_bcol[0], _bcol[1], _bcol[2],
                                255 if _bsel else (170 if _bset else 90)),
                      3 if _bsel else 2, Qt.DashLine))
        p.drawLine(QPointF(_bx, 0.0), QPointF(_bx, float(VH)))
        p.setPen(QColor(_bcol[0], _bcol[1], _bcol[2], 255))
        p.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        p.drawText(QPointF(_bx + 6, 18),
                   ("边界 %d" % int(_bx)) if _bset else "边界默认 %d" % int(_bx))

    def _draw_edit_spawn(self, p):
        """露娜起点：三角旗 + `L`（派单 §2.4）。⛔ None 时不画。

        ⭐⭐ 起点是**最后画的一层**（在 `_draw_edit_overlay` 末尾调用）——
           它最需要永远可见，不能被自定义地形盖住。
        """
        if self.custom_spawn is None:
            return
        x, y = float(self.custom_spawn[0]), float(self.custom_spawn[1])
        sel = (self.edit_sel_obj == ("luna_spawn", -1))
        c = (255, 226, 120)
        al = 255 if sel else 200
        p.setPen(QPen(QColor(c[0], c[1], c[2], al), 3 if sel else 2))
        p.setBrush(QColor(c[0], c[1], c[2], 90))
        p.drawLine(QPointF(x, y), QPointF(x, y - 46))          # 旗杆
        p.drawPolygon(QPolygonF([QPointF(x, y - 46), QPointF(x + 30, y - 35),
                                 QPointF(x, y - 24)]))          # 旗面
        p.setPen(QColor(c[0], c[1], c[2], al))
        p.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        p.drawText(QPointF(x + 6, y - 52), "L")
        if sel:
            p.drawText(QPointF(x - 30, y + 24), "起点 x=%d y=%d"
                       % (int(x), int(y)))

    def _draw_edit_toolbar(self, p):
        """编辑器工具栏（画在视口坐标，**不跟随镜头**）。"""
        # ⭐⭐ PR26（2026-10-10）：编辑态**从来没有**画过 self.msg。
        #   实测根因：`_tick` 的 edit 早退分支只让 msg_t 递减（`:4704`），
        #   ⛔ 全文件没有任何地方在编辑态把 msg 画出来
        #   ⇒ Ronny 按 S 导出成功（文件确实写了 18 块），但**屏幕上一点反应都没有**，
        #      看起来像"导出坏了"。提示连同内容一起被丢掉了。
        if self.msg_t > 0 and self.msg:
            _a = int(205 * min(1.0, max(0.0, self.msg_t)))
            _bad = self.msg.startswith("⚠") or self.msg.startswith("导出失败")
            p.setPen(Qt.NoPen)
            # ⛔ 别写 QColor((a,b,c,d) if cond else (e,f,g,d)) ——
            #   PySide6 报 "QVariant must be holding a QColor"（三元表达式先算出元组再进构造）。
            #   ✅ 必须两条显式分支。
            if _bad:
                p.setBrush(QColor(150, 40, 40, _a))
            else:
                p.setBrush(QColor(24, 110, 70, _a))
            p.drawRect(QRectF(0, 46, VW, 30))
            p.setPen(QColor(255, 255, 255, min(255, _a + 40)))
            p.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
            p.drawText(QPointF(12, 66), self.msg)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(14, 16, 24, 205))
        p.drawRect(QRectF(0, 0, VW, 46))
        p.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        x = 14.0
        p.setPen(QColor(240, 226, 196))
        p.drawText(QPointF(x, 20), "地形编辑器")
        x += 92
        # ⭐ 三种类型：当前选中的高亮（派单 §3.4）
        for i, k in enumerate(TERRAIN_KINDS, start=1):
            c = self._EDIT_COLOR[k]
            on = (self.edit_kind == k)
            p.setPen(QPen(QColor(c[0], c[1], c[2], 255 if on else 110), 2 if on else 1))
            p.setBrush(QColor(c[0], c[1], c[2], 70 if on else 20))
            p.drawRoundedRect(QRectF(x, 8, 84, 24), 5, 5)
            p.setPen(QColor(c[0], c[1], c[2], 255 if on else 150))
            p.drawText(QPointF(x + 8, 24),
                       "%d %s" % (i, self._EDIT_KIND_CN[k]))
            x += 90
        # ---------------- PR13 · 8 个工具（4/5/6 + 7/8/9/0/-）----------------
        # ⭐ 用 EDIT_TOOLS 表驱动，不是手写一串 drawRoundedRect：
        #   加一个工具只需要在表里加一行，**不可能出现"键位加了但按钮没加"**。
        p.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
        for name, cn, key in EDIT_TOOLS:
            on = (self.edit_tool == name)
            # ⭐ PR13 新工具用固定的青/紫色系，⛔ 不复用 _EDIT_COLOR
            #   （那是 solid/brittle/climb 的语义色，混用会让"红色的东西"
            #     到底是脆化地形还是 jar 食物说不清）。
            c = ((120, 220, 255) if name in ("food", "fridge")
                 else (255, 190, 240) if name in ("luna_spawn", "mw_patrol", "nest")
                 else (200, 200, 210))
            p.setPen(QPen(QColor(c[0], c[1], c[2], 255 if on else 100),
                          2 if on else 1))
            p.setBrush(QColor(c[0], c[1], c[2], 70 if on else 18))
            p.drawRoundedRect(QRectF(x, 8, 74, 24), 5, 5)
            p.setPen(QColor(c[0], c[1], c[2], 255 if on else 140))
            p.drawText(QPointF(x + 6, 24), "%s %s" % (key, cn))
            x += 78
        # ---- 工具 + 快捷键提示 ----
        p.setPen(QColor(150, 156, 172))
        p.setFont(QFont("Microsoft YaHei", 9))
        p.drawText(QPointF(14, 40),
                   "直线工具 = 零厚线（可站/可爬，Shift 强制另一轴）   "
                   "要斜的薄板请用矩形工具   "
                   "Shift+直线 强制另一轴   [ ]换 icon   , . 换 kind   "
                   "Delete 删除选中（起点/巡逻/窝 = 恢复默认）   Ctrl+Z 撤销   "
                   "C 清空全部   S 导出   O 导入   F4 试跑   F2 返回   "
                   "A/D 或 ←/→ 平移视角   Home/End 跳两端   PageUp/Dn 跳一屏")
        # ⭐ 巡逻段不拦"进冰箱体"（§2.3）：只提示，这是关卡设计约束，
        #   编辑器不该替Ronny 决定。
        p.setPen(QColor(210, 170, 120))
        p.drawText(QPointF(14, VH - 30),
                   "⚠ 微波炉 `self.y = FLOOR_Y` 是硬编码，他永远在地板上；"
                   "巡逻段拖进冰箱范围不会被拦（那是关卡约束，不是编辑器的事）"
                   # ⭐⭐ PR20 · B4：贴图归属只吃 **y0（顶面）**，不吃 y1
                   #   （实测 `which_part`）⇒ 只改高度不影响；
                   #   ⛔ 但把平台挪到**别的高度区间**就可能贴错图 —— 必须让他知道。
                   "　｜　贴图按平台顶面判归属，只改高度不影响；挪到别的高度区间可能贴错图")
        # ---- 底部：数量 + 直线工具的留白说明（Q3 未拍板，必须让人看见）----
        p.setPen(QColor(200, 200, 210))
        p.setFont(QFont("Microsoft YaHei", 10))
        # ⭐ 数量行必须把 5 类新对象的计数全列出来 ——
        #   否则"我放了 3 个食物，界面只说地形 0 块"会让人以为没放成功。
        p.drawText(QPointF(14, VH - 14),
                   "自定义地形 %d 块 ｜ 食物 %d ｜ 冰箱食物 %d ｜ 起点 %s ｜ 巡逻段 %s ｜ 窝区 %s ｜ "
                   # ⭐⭐ PR23：把「关卡边界」也列进计数行 —— 未设时显示关卡默认值
                   "边界 %s ｜ "
                   "拖左键画 / 选中 ｜ 双击删除"
                   " ｜ 默认平台 %s"
                   " ｜ 视角 %d / %d（可见 %d~%d）"
                   # ⭐⭐ PR21 · A1：把存档加载状态画在工具栏上 ——
                   #   「未接管」状态下画面和「已载入」几乎一样，Ronny 分不出来。
                   " ｜ %s"
                   % (len(self.custom_terrains),
                      len(self.custom_stashes or []),
                      len(self.custom_fridge or []),
                      "已设" if self.custom_spawn else "默认",
                      "%d~%d" % self.custom_patrol if self.custom_patrol else "默认",
                      "%d~%d" % self.custom_nest if self.custom_nest else "默认",
                      # ⭐⭐ PR23 · None = 不覆盖 ⇒ 显示关卡默认
                      ("%d" % int(self.custom_border)) if self.custom_border
                      is not None else ("默认%d" % int(self.room.border_x)),
                      # ⭐ PR16 · B 段：默认平台是否被接管（接管了 ⇒ 导出会升 v3）
                      ("已改 %d 条" % len(self.builtin_terrains)
                       if self.builtin_terrains else "默认"),
                      int(self.cam_x), int(CAM_X_MAX),
                      int(self.cam_x), int(self.cam_x) + VW,
                      self._save_status_cn()))
        # ---- 二次确认提示 ----
        if self._confirm_clear:
            p.setPen(QColor(255, 120, 100))
            p.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
            p.drawText(QPointF(VW / 2 - 190, VH - 52),
                       "⚠ 再按一次 C 确认清空全部（地形 + 食物 + 起点 + 巡逻段 + 窝区）")

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
    def _draw_bg_slices(self, p):
        """⭐ 2026-10-05 PR-03：画三张背景切片（世界坐标 0 / 1280 / 2560）。

        ⛔ **这里必须画「世界坐标」，不能画「视口坐标」。**
           本方法在 `p.save(); p.translate(-cam_x, 0)` **之内**被调用，
           外层那一次 translate 已经是"世界 → 视口"的**唯一**映射。
           ⇒ 若在这里再写 sx = wx - cam_x，就是**减两次**（二次偏移，画面整体错 cam_x）。
           ⭐ 与其它_draw_*（_draw_luna 等）保持一致：它们也都用世界坐标。
        """
        # ⭐ 画在最底层：先把整片世界铺满底色，避免切片之间的空隙透出黑底
        p.fillRect(QRectF(self.cam_x, 0, VW, VH), QColor(18, 20, 34))
        _any = False
        for i, im in enumerate(self.bg_slices):
            if im is None:
                continue
            _any = True
            # 世界坐标里的左缘= i * VW；1:1 贴，不缩放。越界由 QPainter 裁掉。
            p.drawImage(QRectF(i * VW, 0, VW, VH), im,
                        QRectF(0,0, im.width(), im.height()))
        if not _any and self.bg_img is not None:
            # ⛔⛔ 切片一张都没有（BG-02e 长图未出）⇒ 用旧的单图**横向平铺**铺满整个世界。
            #   ⚠️ **旧版只把它顶在世界最左（x=0）** ⇒ 镜头跟到 x>1280 就是**纯底色空白**，
            #   Ronny 玩的时候会以为程序坏了（2026-10-05 阻塞项）。
            #   ⭐ 为什么平铺而不是 `scaled()` 拉宽：那张图里有家具（茶几/台面/冰箱/吊柜），
            #   横向拉宽 3 倍 ⇒ **家具被拉成 3 倍宽**，一眼假。
            #   平铺则每段都是原尺寸 ⇒ 看不出变形（它本来就是"一整间厨房"的重复感）。
            #   ⛔ 平铺的代价：x=1280 与 x=0 处会看到同一面墙/同一扇窗。
            #   那比"空白"或"变形"都可用。
            #   ⚠️ 2026-10-05 撤压暗后接缝**可能变得可见**（压暗时接缝被暗色藏了，
            #   现在亮了就藏不住）—— 实机看一眼镜头走过 x=1280 时接缝明不明显。
            _tw = self.bg_img.width()
            if _tw <= 0:                      # ⛔ 兜底：0 宽会死循环
                _tw = VW
            # 从 cam_x 所在的那一段开始画，⛔ 只画视口内的段（省掉 3 倍无用绘制）
            _i0 = int(self.cam_x // _tw)
            _i1 = int((self.cam_x + VW) // _tw) + 1
            for _i in range(_i0, _i1 + 1):
                p.drawImage(QRectF(_i * _tw, 0, _tw, VH), self.bg_img,
                            QRectF(0, 0, self.bg_img.width(), self.bg_img.height()))

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
        # ✅ 现在：**色相照实拍**（暖白 + 木色）。
        # ⭐⭐ 2026-10-05 Ronny 20:44 改为「白天大中午偷」设定 ⇒ **撤掉压暗**。
        #   旧值 0.42（白天 #ECEDE8 → 夜里 #63635F 的暖灰白）是**为半夜定的**，
        #   白天设定下会把整个厨房拉暗 ⇒ 视觉上"还是晚上"，与设定冲突。
        #   ⇒ `_D = 1.0` = **不压暗**，直接用实拍原色。
        # ⛔ 只改 `_D` 这一个数 —— 下面 `dk(...)` 里的**具体色值本来就是实拍色相**，
        #   ⛔ 别"顺便"调它们（那会把配色改回凭感觉）。
        # ⏳ 若 Ronny 之后说"太亮/要暖调"，改 `_D` 成 0.85~0.95 即可，⛔ 别动色值。
        _D = 1.0
        def dk(r, g, b):
            return QColor(int(r * _D), int(g * _D), int(b * _D))
        parts = self.sparts
        # ⭐⭐ PR12：`i` 不再决定「画什么家具」，改成按**内容**决定。
        #   ⛔⛔ 为什么必须改：原来靠 `i==1 餐桌 / i==2 料理台 / i==3 吊柜` 的
        #     **书写序号**取贴图/程序画。自定义地形一进来，序号与家具的对应关系
        #     立刻失效⇒ 第2 项会贴上"料理台"、第 3 项贴"吊柜"，重影换个形式复活。
        #   ✅ 改法：`i==0`（地板）保留 —— 它是"全图铺底"，语义上就是第一项；
        #     家具贴图改为**按 y0 高低 + x 区间**判定（见下`which`），
        #     自定义地形默认**不贴家具图**（除非它正好压在某个家具 x 区间上）。
        for i, _p in enumerate(self.room.platforms):
            x0, y0, x1, y1 = plat_fields(_p)
            _kind = plat_kind(_p)
            if i == 0:      # 地板：暖木色（实拍 #7D6A59）
                p.setBrush(dk(125, 106, 89))                    # 白天的木地板
                p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                p.setPen(QPen(dk(152, 139, 123), 2))              # 墙脚线
                p.drawLine(QPointF(x0, y0 + 1), QPointF(x1, y0 + 1))
                p.setPen(Qt.NoPen)
                continue
            # ⭐ PR12：brittle 已触发的画成半透明虚框（视觉上"它不在了"）
            if _kind == "brittle" and not self.room.brittle_active(id(_p)):
                _d = QColor(190, 200, 215, 110)
                p.setPen(QPen(_d, 2, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
                continue
            _pw, _ph = x1 - x0, y1 - y0
            _img = None
            # ⭐⭐ 改成按「内容」取贴图，不再按下标：
            #   ⛔ 判据必须是**可判定的客观量**，不能靠"我以为这是灶台"。
            #   这里用「x 区间落在哪个家具的 x 区间内」—— 与 _draw_platforms
            #   同一份 TABLE_*/旧坐标常量，不引入新数字。
            if _kind == "solid":
                _img = parts.get(which_part(x0, x1, y0))
            if _img is not None:
                # ⭐ 保持宽高比贴入框中（⛔ 不拉伸变形：旧贴图是按 1.8m 宽的料理台出的，
                #   新布局的厨房桌只有 0.76m 宽，直接拉会把柜门压成竖条）
                _tw, _th2 = _img.width(), _img.height()
                _s = min(_pw / float(_tw), _ph / float(_th2))
                _dw, _dh = _tw * _s, _th2 * _s
                p.drawImage(QRectF(x0 + (_pw - _dw) / 2.0, y0 + (_ph - _dh) / 2.0, _dw, _dh),
                            _img, QRectF(0, 0, _tw, _th2))
                continue
            if which_part(x0, x1, y0) == "table":
                # ⭐ 餐桌程序绘制：纯几何形（矩形台面 + 两条矩形腿），AI 画不准，程序画反而更准
                #   配色照实拍木色：台面 #6B5B4B，白天不压暗
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
        # ⭐⭐⭐ PR13（Q12批准）：x0,x1 读 room.nest，**画法一个数都不动**。
        #   ⛔⛔ 为什么必须跟着走：判定已改成读 room.nest，而画面上的窝还留在x=10
        #     ⇒ 玩家看到判定在 1500、画面上窝还在 10 ⇒ **必被当 bug，且不报错**。
        #   ⭐ 默认 `room.nest = (NEST_X0, NEST_X1) = (10, 200)` ⇒ 与旧值逐字相同。
        x0, x1 = self.room.nest
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
            near = self.luna.x < self.room.nest[1] + 90
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
        if not FRIDGE_ENABLED:
            return                 # ⭐ 冰箱没了 ⇒ 什么都不画
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

    def _draw_mw(self, p, x_override=None):
        m = self.mw
        # ⭐⭐ PR20 · A2：编辑态要画**巡逻段中点**，而不是 `self.mw.x`（初始位置）
        #   —— 否则 Ronny 设完巡逻段，编辑态的微波炉不动 ⇒ 拿它对坐标反而误导。
        #   ⛔⛔ 用**参数**传，⛔ 不改 `self.mw.x` 再还原（那路容易漏、且会污染游戏状态）。
        #   ⛔ 只改这一处就够：下面视野锥 / 本体 / `_draw_mw_box` 全用这个局部 `x`。
        x = m.x if x_override is None else float(x_override)
        y = m.y
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

    # ---------------- PR14 · 攻击特效绘制 ----------------
    # ⚠️⚠️ **绘制顺序就是打击感**（派单 §3.3），⛔ 别调换：
    #   behind（刀光，角色**后面**）→ 角色 → front（冲击 + 蓄力粒子，角色**前面**）
    #   冲击挡住角色 = 格斗游戏标准做法，是"打到了"的主要来源。

    def _draw_fx_behind(self, p):
        """角色**后面**：刀光 claw。"""
        for e in self.fx:
            if e.kind == "claw":
                self._draw_fx_claw(p, e)

    def _draw_fx_front(self, p):
        """角色**前面**：命中冲击 impact + 蓄力粒子 charge。"""
        for e in self.fx:
            if e.kind == "impact":
                self._draw_fx_impact(p, e)
        for e in self.fx:
            if e.kind == "charge":
                self._draw_fx_charge(p, e)

    def _draw_fx_claw(self, p, e):
        """刀光：3 道弧（普攻 1 道 / 蓄力 2~3 道），由小扫到大、末端收尖。

        ⭐ 沿用既有范式（`_draw_stashes` 的 scratched 分支）：
          `QPen(QColor(...,a), w, Qt.SolidLine, Qt.RoundCap)` —— ⛔ 不自造画法。
        ⭐⭐ `a(t) = (1-t)**1.4`：末端淡出；`w(t) = 7*sin(pi*t)`：先增后减收成尖。
          ⛔ 这两条别"优化"成线性 —— 线性收尾会看起来像被切断，而不是挥空。
        """
        t = e.t
        n = FX_CLAW_N[e.lvl]
        for i in range(n):
            _off = i * 15.0                   # ⭐ 多道弧向下叠（不是三道一样）
            # ⭐ 每道弧错开一点相位 ⇒ 是"叠上去的刀气"
            _ph = (t - i * 0.055) / max(1e-6, (1.0 - i * 0.055))
            _ph = max(0.0, min(1.0, _ph))
            r = e.r * (0.35 + 0.65 * _ph) * (1.0 - 0.13 * i)
            w = 7.0 * math.sin(math.pi * _ph)
            if w <= 0.2:
                continue
            a = int(255 * ((1.0 - _ph) ** 1.4))
            if a <= 2:
                continue
            c = e.color
            # ⚠️ `drawArc` 的角度单位是 **1/16 度**，且⛔ 传负跨度不会"镜像"——
            #   镜像的正确做法是「换起点 + 反向跨度」。这是 Qt 的老坑。
            p.setPen(QPen(QColor(c[0], c[1], c[2], a), w,
                         Qt.SolidLine, Qt.RoundCap))
            _a0 = -50.0 + _off              # ⭐ 多道弧向下叠
            if e.facing >= 0:
                p.drawArc(QRectF(e.x - r, e.y - r, 2 * r, 2 * r),
                          int(_a0 * 16), int(100.0 * 16))
            else:
                p.drawArc(QRectF(e.x - r, e.y - r, 2 * r, 2 * r),
                          int((80.0 - _off - 100.0) * 16), -int(100.0 * 16))

    def _draw_fx_impact(self, p, e):
        """命中冲击：6~8 条放射线 + 1 个圆环。

        ⭐ 放射线**起始角错开 22.5°** ⇒ 不会左右对称得像特效图。
        ⛔ 别改成"均匀 8 条从 0° 开始"—— 那看起来像 UI 图标，不像挥击。
        """
        t = e.t
        c = e.color
        al = int(255 * ((1.0 - t) ** 1.6))
        if al <= 2:
            return
        _n = 6 + 2 * e.lvl               # 档越高线越多
        _L = 10.0 + 46.0 * t
        _w = max(0.4, 3.5 * (1.0 - t))
        p.setPen(QPen(QColor(c[0], c[1], c[2], al), _w,
                     Qt.SolidLine, Qt.RoundCap))
        for i in range(_n):
            ang = math.radians(22.5 + i * (360.0 / _n))
            dx, dy = math.cos(ang), math.sin(ang)
            # ⭐ 放射线只画"身前"那一半（另一半在角色背后，看不见也不该看）
            if dx * e.facing < -0.25:
                continue
            p.drawLine(QPointF(e.x + dx * _L * 0.35, e.y + dy * _L * 0.35),
                       QPointF(e.x + dx * _L, e.y + dy * _L))
        # ---- 圆环 ----
        _r = 6.0 + 30.0 * t
        _rw = max(0.4, 4.0 * (1.0 - t))
        p.setPen(QPen(QColor(c[0], c[1], c[2], int(al * 0.85)), _rw,
                     Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(e.x, e.y), _r, _r)

    def _draw_fx_charge(self, p, e):
        """蓄力粒子 —— ⭐ **蓄力指示器**（Ronny：要粒子变化作为指示）。

        ⭐⭐⭐ **三阶段，颜色 + 数量 + 脉动幅度三个维度同时变**
           （派单 §3.4）：只变色的话快速操作时眼睛来不及看。
             聚拢中（白 14 粒）→蓄力1 就绪（**红** 14 粒）→ 蓄力2 就绪（**蓝** 26 粒）
        ⚠️ **阶段用 `charge_t` 判，脉动用 `e.t` 算** ——⛔ 阶段切换时绝不重置 e.t，
           否则粒子会跳一下。
        ⭐ 每个粒子有随机相位偏移 `i*0.37` ⇒⛔ 否则 14 个粒子同步移动，
           看起来像一坨整体在动而不是一堆粒子。
        """
        ct = max(0.0, min(ATK_CHARGE2, self.luna.charge_t))
        # ---- 选阶段（⛔ 阶段切换时⛔ 不重置 e.t）----
        st = FX_CHARGE_STAGES[0]
        for _s in FX_CHARGE_STAGES:
            if ct >= _s[0]:
                st = _s
        _t0, col, n, amp, ring = st
        # ⭐ 脉动：e.t 是全局进度，阶段切换时连续 ⇒ 不会跳
        pulse = amp * math.sin(e.t * 18.0)
        cx, cy = e.x, e.y
        # ⭐ 聚拢中：粒子从 90px 外圈**向内吸**（用 charge_t 映射 1→0）
        if st is FX_CHARGE_STAGES[0]:
            _p = max(0.0, min(1.0, ct / max(1e-6, ATK_HINT)))
            ring_now = ring * (1.0 - 0.35 * _p)
        else:
            ring_now = ring
        p.setBrush(QColor(col[0], col[1], col[2], 220))
        p.setPen(QPen(QColor(col[0], col[1], col[2], 235), 1.4))
        for i in range(n):
            ang = i * (360.0 / n) + i * 0.37          # ⭐ 相位偏移
            rad = ring_now + pulse
            a = math.radians(ang)
            px = cx + math.cos(a) * rad
            py = cy + math.sin(a) * rad * 0.62# ⭐ 压扁成椭圆（贴合身体）
            p.setBrush(QColor(col[0], col[1], col[2],
                               170 + int(70 * (0.5 + 0.5 * math.sin(e.t * 6.0 + i)))))
            p.drawEllipse(QPointF(px, py), 2.6 + 0.9 * e.lvl, 2.6 + 0.9 * e.lvl)

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
        # ============ PR15 · attack / attack_charge 走游戏帧 ============
        # ⭐⭐⭐ **这是「大小问题」的修复点**（Ronny 实机反馈"又复发了"）。
        #
        # ⚠️⚠️⚠️ 为什么必须是这一处，根因在这里：
        #   桌宠分支的画布是 packs 的 640×640，绘制时**乘 s**
        #   （`s = ACTOR_H / body_h`）⇒ 角色高约 501px；
        #   游戏帧的画布是**归一化后的** 178 高（本体 132px），**⛔ 不乘 s**。
        #   ⇒ 两张图走**两条不同的缩放路径**。
        #   ⇒ 只要攻击动作还落在桌宠分支（tease），就必然大 3.8 倍。
        #   ⚠️ 这不是"数值没调好"——把 s 调小去凑 attack 帧会**反过来弄坏桌宠动作**。
        #   ✅ 唯一正确的修法：让 attack 走游戏帧，和 run_carry 同一条路。
        #
        # ⛔ 三条硬要求（照抄 run_carry 分支的写法）：
        #   ① 必须 return —— ⛔ 不许落回桌宠分支（那才是"大小又复发"的直接原因）
        #   ② 帧列表为空时 **print 告警** —— ⛔ 不许静默兜底画 idle
        #      （同一个坑不能踩第二次：tease 那次就是静默兜底了整整两轮）
        #   ③ 用 `GAME_FPS[l.act]` 查表，⛔ 不写死帧率
        if l.act in ("attack", "attack_charge"):
            _af = self.gframes.get(l.act) or []
            if not _af:
                # ⛔⛔ 静默兜底 = Ronny 实机看到"攻击没动画"，而代码"看起来没问题"
                print("[夜间] ⚠️ 游戏帧缺 %s（大小会回退成桌宠比例）" % l.act)
            else:
                _k = int(l.t * GAME_FPS[l.act]) % len(_af)
                _pm, _cw, _ch, _ax, _ay = _af[_k]
                p.save()
                p.translate(l.x, l.y)
                # ⭐ 规则与 run_carry 一致：「与素材原始朝向不一致才镜像」
                if l.face != GAME_SRC_FACE[l.act]:
                    p.scale(-1.0, 1.0)
                # ⛔⛔ 不乘 s：_cw/_ch 已经是归一化后的成品尺寸
                p.drawImage(QRectF(-_ax, -_ay, _cw, _ch), _pm, QRectF(0, 0, _cw, _ch))
                p.restore()
                for i, nm in enumerate(l.carrying):
                    ic = self.icons.get(_loot_split(nm)[1])
                    if ic is not None:
                        p.drawImage(QRectF(l.x - 9 + i * 18, l.y - 118 - i * 6,
                                            18, 18), ic, QRectF(0, 0, ic.width(), ic.height()))
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
