# -*- coding: utf-8 -*-
"""audio.py —— 夜间冒险的音频引擎（PR-03 第三批）

⭐ 为什么用 `QSoundEffect` 而不是 `QMediaPlayer`
   `QSoundEffect` 专攻**短音效**，延迟最低；`QMediaPlayer` 是播放器，起播有额外开销。
   本项目里全是"敲一下""按一下"这种瞬时反馈 + 两条循环底噪，用不上播放器的功能。

⭐ 为什么单独一个模块（而不是塞进 night.py）
   ① night.py 已经3000 行，再加 200 行音频会把玩法逻辑埋掉；
   ② 音频要能在**没有游戏窗口**的情况下单独实例化自测（见`_自测_音频.py`）；
   ③ ⛔ **打包必须同步**：`LunaPet.spec` 的 `hiddenimports` 里要加 `"audio"`
      —— 漏了的症状和`night` 那次一模一样（源码能玩、打包后点游戏机毫无反应）。

⛔⛔ **三条接线纪律（本项目栽过的）**
   ① **绝不写绝对路径**。素材来自项目外，复制进 `自研引擎/assets_audio/`。
      ⛔ 打包后 CWD / 源码目录都可能不存在 ⇒ 只用 `__file__` 推出来的相对路径。
   ② **加载失败必须报错，不许静默**。`QSoundEffect` 构造成功但 `status()==Error`
      时**不抛异常、不打日志**（实测），症状就是"游戏跑得好好的但一点声音都没有"。
      ⇒ `_load()` 逐个校验并把失败收进 `self.errors`。
   ③ **中文路径**：项目目录全中文。实测 `QSoundEffect` 能正常加载中文名文件
      （`Status.Ready`），但 `QUrl.fromLocalFile` 必须用**绝对路径**才稳。
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QUrl, QTimer

try:                                    # QtMultimedia 是可选依赖，缺了要能降级
    from PySide6.QtMultimedia import QSoundEffect
    _HAVE_QTMM = True
except Exception:                        # pragma: no cover - 打包漏插件时走这里
    QSoundEffect = None
    _HAVE_QTMM = False


# ============================================================================
# ① 素材目录 —— ⛔ 零绝对路径
# ============================================================================

def _assets_dir() -> str:
    """音频素材目录。**唯一真源是 `__file__`**，⛔ 不看 CWD、不看环境变量。

    ⚠️ 打包（PyInstaller onedir）后 `__file__` 指向 exe 旁的 `_internal/`，
       `datas` 里的 `assets_audio/` 正好落在这个位置 ⇒ 同一段代码两边都对。
    兜底再试 `sys._MEIPASS`（onefile 模式）。
    """
    here = os.path.dirname(os.path.abspath(__file__))       # .../自研引擎/pet_engine
    cands = [os.path.join(os.path.dirname(here), "assets_audio")]
    if getattr(sys, "_MEIPASS", None):
        cands.append(os.path.join(sys._MEIPASS, "assets_audio"))
    for d in cands:
        if os.path.isdir(d):
            return d
    return cands[0]            # ⛔ 不 raise：返回"期望路径"，让 _load() 去报错


AUDIO_DIR = _assets_dir()


# ============================================================================
# ② ⭐ 混音增益（SND_GAIN）—— **参数化，⛔ 别写死**
# ============================================================================
# ⭐ 为什么必须参数化：这批素材的**峰值差 27.3 dB**（当时的环境音 −28.81
#   vs sfx_pick_jar −1.50）。不配增益的话，环境音永远听不见、
#   反馈音永远是刺耳的 ==> 混音就退化成了"能不能听见"。
#
# ⚠️ 增益是**线性倍率**，`10^(dB/20)`。我把每条的目标峰值写在注释里，
#   改的时候照着算，别拍脑袋填浮点数。
#
# ⭐ `SND_GAIN_DB` 是给人看的（改这个），`SND_GAIN` 是给代码用的（自动算）。
#   两条对应，改一条另一条自动跟着变 ⇒ 不会"改了 dB 忘了同步倍率"。
#
# 目标峰值（dBFS，素材原始峰值 → 目标峰值）：
#   sfx_pick_jar     −1.50 → −2.0反馈音要突出，但留一点余量避免叠加削顶
#   sfx_attack       −1.50 → −2.0
#   sfx_land         −1.50 → −3.5  ⭐ PR-06 落地反馈，与 sfx_dash 同档（Ronny 授权定案）
#   sfx_dash         −3.00 → −3.5
#   sfx_caught       −2.00 → −2.0
#   sfx_qte_tick_008 −1.50 → −4.0QTE 按键很密，压一点免得连续三个键糊成一片
#   sfx_qte_fail     −6.00 → −6.0
#   sfx_mw_alert     −6.00 → −7.0
#   sfx_pick_plate   −8.13 → −7.0
#   sfx_pick_loose  −24.41 → −9.0  ⭐ 同上，偏轻 15 dB
#   bgm_steal−9.00 → −13.0 BGM 要在音效**下面**，抢了就毁潜行节奏
#   bgm_caught      −8.00 → −6.0   sting，允许突出
#   bgm_win         −8.00 → −6.0
SND_GAIN_DB = {
    "sfx_pick_jar":-0.5,
    "sfx_attack":        -0.5,
    # ⭐⭐ 2026-10-06 PR-06：落地音。原始峰值 −1.50 dBFS（`wave` 直读实测，
    #   时长 0.35s / 44.1kHz / 单声道）。
    #   ✅ 增益 **−2.00 dB** —— **Ronny 2026-10-06 授权按程序端建议值定案**。
    #   目标峰值 **−3.50 dBFS**，与 `sfx_dash` 同档。
    #   理由：落地是**常规反馈**，attack/caught 才是"出事了"；
    #   落地音盖过高潮会把高潮吃掉。
    #   ⚠️ 曾经一度回滚成`0.0` 等拍板 ⇒ 目标峰值会变成原始的 −1.50 dBFS，
    #      **比 sfx_attack(−2.00) 还响 0.5 dB，当上整条混音里最响的一条**。
    #      ⇒ 「留白等拍板」的代价是一条明显错误的混音状态，所以特批直接定案。
    #      ⛔ 以后遇到同类留白（增益 / 音量）别机械地等：先量出"留白时的实际值"，
    #        如果那个值本身就是错的（响度反超、削顶），要主动报"要么定、要么给临时授权"。
    "sfx_land":          -2.0,
    "sfx_dash":          -0.5,
    "sfx_caught":         0.0,
    "sfx_qte_tick_008":  -2.5,
    "sfx_qte_fail":       0.0,
    "sfx_qte_tick":      -0.5,       # ⛔ 这条**不接进游戏**（QTE 用 008 版）。
    #                它仍要在表里：素材随包交付，自测要逐条验加载，
    #                万一以后要换回长音，增益已经备好。
    "sfx_mw_alert":      -1.0,
    "sfx_pick_plate":     1.1,
    "sfx_pick_loose":    15.4,
    "bgm_steal":         -4.0,
    "bgm_caught":         2.0,
    "bgm_win":            2.0,
    # ⭐⭐ 2026-10-06 PR-05：白天 BGM 增益。
    #   ⭐ **口径**：照 `bgm_steal` 的目标峰值 −13 dBFS反推（`_量_BGM峰值.py`）。
    #   ⛔ **绝不能不给** —— `_vol()` 对未知素材返回 **1.0**（audio.py:410），
    #   那比 `bgm_steal` 的 0.6309 还大 **4.0 dB** ⇒ 白天 BGM 会盖过
    #   −2 dBFS 的反馈音，潜行节奏（靠"听得见脚步"）就毁了。
    #   原始峰值 −6.00 dBFS ⇒ 目标 −13 dBFS 需增益 **−7.00 dB**。
    #   ⭐⭐ 2026-10-06 **绝对音量已拍板 = −13 dBFS**（Ronny / 设计端）。
    #   ⛔ 不许改：这一档 −13 dBFS 保证白天 BGM 在 −2 dBFS 的反馈音**之下** 11 dB，
    #     潜行节奏（靠"听得见脚步"）才成立。改响了就毁玩法，不是改口味。
    "bgm_day_cute3_loop":       -7.0,
    "bgm_day_cute_15s_loop":    -7.0,
    "bgm_day_cute_alt15s_loop": -7.0,
    # ⛔ 三个**源件**（非循环）也登记增益，但⛔ 不该被起播 ——
    #   它们尾部比头部安静 14~29 dB，`setLoopCount(-2)` 硬切会"塌一下"。
    #   登记是为了让增益口径完整、且自测能逐条验加载。
    "bgm_day_cute3":       -7.0,
    "bgm_day_cute_15s":    -7.0,
    "bgm_day_cute_alt15s": -7.0,
}

# 自动换算：dB → 线性倍率。⛔ 别手动填这一份。
SND_GAIN = {k: (10.0 ** (db / 20.0)) for k, db in SND_GAIN_DB.items()}

#:素材**原始峰值**（dBFS，实测：音乐端 `_probe_final.json`，008 我自己量的）。
#: ⭐ 这张表存在的理由：**光看增益倍数会判错**。
#   （历史）厨房环境音增益 ×3.467看着比 `sfx_pick_jar` 的 ×0.944 大 3.7倍，
#   但它的原始峰值是 −28.81、jar 是 −1.50 ⇒ **实际响度差11.3 dB，jar 仍然更响**。
#   ⇒ 比较"谁更响"必须比 `SND_GAIN_DB + SND_PEAK_DB`（= 目标峰值），
#   ⛔ 拿 `SND_GAIN` 直接比大小是错的（我第一版的自测就栽在这，报了假红）。
#   ⚠️ 2026-10-06 PR-06：Ronny 判「环境音不要了」⇒ 那条素材与表项已全部移除，
#      这里保留数字只是留一条"别只看倍数"的教训，⛔ 别把它加回表里。
SND_PEAK_DB = {
    "bgm_caught": -8.00, "bgm_steal": -9.00, "bgm_win": -8.00,
    # ⭐⭐ 2026-10-06 PR-05：白天 BGM 的峰值（`_量_BGM峰值.py` 实测，⛔ 不是抄派单的数）。
    #   三个 `_loop` 件是A 案离线预拼产物；交叉淡化是**加权和**
    #   ⇒ 峰值只会略降、不会升（实测 0.50119 → 0.50101），故同填 −6.00。
    "bgm_day_cute3": -6.00, "bgm_day_cute_15s": -6.00, "bgm_day_cute_alt15s": -6.00,
    "bgm_day_cute3_loop": -6.00, "bgm_day_cute_15s_loop": -6.00,
    "bgm_day_cute_alt15s_loop": -6.00,
    "sfx_attack": -1.50, "sfx_caught": -2.00, "sfx_dash": -3.00,
    # ⭐ PR-06：`wave` 直读实测（⛔ 不是抄派单的数）。
    "sfx_land": -1.50,
    "sfx_mw_alert": -6.00,
    "sfx_pick_jar": -1.50, "sfx_pick_loose": -24.41, "sfx_pick_plate": -8.13,
    "sfx_qte_fail": -6.00, "sfx_qte_tick": -13.76, "sfx_qte_tick_008": -1.50,
    # ⛔ 2026-10-05 Ronny「冰箱音效彻底移除」⇒ sfx_fridge_open 已从三张表里删除。
    #   ⛔ 别加回来 —— 素材文件（assets_audio/sfx_fridge_open.wav）也一起删了，
    #   加回表里会让 Audio 去找一个不存在的文件 ⇒ 每次开机都报一条错。
}

#: 混音后的**目标峰值**（dBFS）= 原始峰值 + 增益。自测按这张表判"谁更响"。
SND_TARGET_DB = {k: SND_PEAK_DB[k] + SND_GAIN_DB.get(k, 0.0) for k in SND_PEAK_DB}

# ============================================================================
# 🎚 循环播放的哨兵值
# ============================================================================
#: 循环播放的哨兵值。⭐ **实测只有 −2 是无限循环**：
#: `QSoundEffect.Infinite` 是 `Loop` 枚举（值 −2），而 `setLoopCount(int)` 只收 int，
#: 传枚举会 TypeError，传 −1 / 0 / 1 都会**只播一次**就停。
#:
#: ⭐⭐ 2026-10-06 Ronny / 设计端**拍板**：白天关卡 BGM = **无限循环**
#:   （这就是 PR-05 派单 §六第 4 项「循环圈数」那个留白，已拍成这一个值）。
#:   ⛔ 别改成"播若干次换曲" —— 那会把潜行时长和曲序绑死在一起。
SND_LOOP_FOREVER = -2



# ============================================================================
# ③ 事件 → 文件映射
# ============================================================================
# ⭐ 拿容器按 kind 选：`loose/plate/jar` 三档各有自己的音，
#   玩家能"听出拿到的是哪一档"—— 这正是分档设计的一部分。
PICK_BY_KIND = {
    "loose": "sfx_pick_loose",
    "plate": "sfx_pick_plate",
    "jar":   "sfx_pick_jar",
    # ⛔ 2026-10-05 Ronny「冰箱音效彻底移除」：原先fridge 指向 sfx_fridge_open。
    #   ⭐ 删掉这一项**不会**让 QTE 拿到东西时静音：`sfx_pick()` 走
    #   `PICK_BY_KIND.get(kind, "sfx_pick_plate")`，而 fridge 那一档
    #   （`_qte_win` 里直接写 carrying）**从不经过 sfx_pick()** ——
    #   只有 `_take_stash()` 会调它，那里拿到的永远是 loose/plate/jar。
}

#: 素材原始时长（秒），**实测值**（音乐端`_probe_final.json` + 我自己量的008）。
#: ⛔ 用途只有一个：结算 sting 播完之后再开始低音量循环
#   —— 先播一次、再循环，面板期听到的就是"持续的结算底音"。
#   ⛔ 别用它做节流/超时判断（那是玩法数值，不归这批）。
#:   ⛔ 别用它做节流/超时判断（那是玩法数值，不归这批）。
#:
#: ⭐⭐ **换素材后必须同步这张表**（2026-10-05 实测踩过）。
#:   音乐端重出了 3.5 秒版 sting，这张表还留着 12 秒的旧值 ⇒
#:   面板期会**多等 8.5 秒**才起循环 ⇒ 玩家盯着面板前 8.5 秒是静音的，
#:   而这**不报错、不崩、也不会被任何行为判据发现**。
#:   ⇒ `_自测_音频.py` ①b 会用 `wave` 直读文件时长逐条比对这张表，
#:     **换完素材先跑那一条自测**，红了就是该改这里。
SND_LEN = {
    "bgm_steal": 180.0, "bgm_caught": 3.50, "bgm_win": 3.50,
    # ⭐⭐ 2026-10-06 PR-05 白天 BGM。⛔ **全部是 `wave` 直读的实测值**
    #   （源：`_量_素材时长.py`），⛔ 不是抄派单/ 抄音乐端的数。
    #⭐⭐ 2026-10-06 PR-08：`bgm_day_cute_15s` 的切点又改了（Ronny 拍板 **14.620s**）
    #   ⇒ **15.50000 这个值已经作废**。AU-05 换了切点之后：
    #     · 源件 `bgm_day_cute_15s.wav`     14.62000s（644742 帧）
    #     · 循环件 `bgm_day_cute_15s_loop.wav` **13.82000s**（609462 帧，重拼过）
    #   ⚠️ **源件改了、循环件没重拼 ⇒ 两者的XF 关系就断了**（本单修的就是这个）。
    #   ⚠️ 14.620 不是全段最深的间隙（13.710s 深到 −53.72 dBFS、
    #     14.415s 深到 −44.82，而 14.620 只有 −29.27，**停在斜坡中段**）。
    #     但那是 Ronny 拍的值，⛔ 程序端不擅自改；要改得**裁源件 + 重拼 + 同步本表**三件一起。
    #   ⛔ 本表每个值都必须 `wave` 直读，⛔ 不要用"源长 − 0.8"心算填（心算不会发现源件被换过）。
    "bgm_day_cute3": 15.14000, "bgm_day_cute_15s": 14.62000,
    "bgm_day_cute_alt15s": 15.33000,
    # ⭐ 三个 `_loop` 件 = A 案离线预拼的无缝循环件，XF = 0.8s（**已拍板**）。
    #   时长 = 源长 − XF（等功率交叉淡化把尾部 XF 帧换成了头部 XF 帧）。
    #   ⚠️ **改 XF 或改源件，就必须同步改这三行** ⇒ 改完跑 `_自测_音频.py` ①b
    #   （它 `wave` 直读比对）⇒ 这是本表最容易踩的静默坑（同 172-183 的坑）。
    #⭐ PR-08：`bgm_day_cute_15s_loop` 由 14.70000 改成 **13.82000**
    #   （源件 14.620 重拼而来；`wave` 直读 609462 帧 / 44100Hz）。
    "bgm_day_cute3_loop": 14.34000, "bgm_day_cute_15s_loop": 13.82000,
    "bgm_day_cute_alt15s_loop": 14.53000,
    "sfx_attack": 0.48, "sfx_caught": 1.20, "sfx_dash": 0.48,
    # ⭐ PR-06：落地音，`wave` 直读 = 0.35000s（⛔ 不是估的）。
    "sfx_land": 0.35,
    "sfx_mw_alert": 0.60,
    "sfx_pick_jar": 0.50, "sfx_pick_loose": 0.48, "sfx_pick_plate": 0.48,
    "sfx_qte_fail": 0.50, "sfx_qte_tick": 0.48, "sfx_qte_tick_008": 0.080,
}

#: ⭐⭐ 2026-10-06 PR-05：**白天关卡**要起的那一条 BGM。
#:
#: ⚠️ 为什么起 `_loop` 件而不起源件：源件尾部比头部安静 **14~29 dB**
#:   （实测 `_量_BGM峰值.py`），而 `loop()` 走 `setLoopCount(-2)` **硬切**回卷
#:   ⇒ 玩家会听到节奏"塌一下"。`_loop` 件是 A 案离线预拼的，
#:   回卷处采样级连续（实测 ⑥ 比值 1.70）。
#:
#: ⭐⭐ 2026-10-06 **XF = 0.8s 已拍板**（Ronny / 设计端，PR-05 派单 §六第 1 项）。
#:   ⛔ **不许改这个数** —— 三个 `_loop` 件的时长是按它预拼的
#:   （时长 = 源长 − XF），改了 XF 就必须重新预拼 + 同步 `SND_LEN` 上面那三行
#:   + 重跑 `_自测_音频.py` ①b（它 `wave` 直读比对）。
#:   完整推导、候选区间与换 XF 的命令见 `回传PR05-程序端-20261006.md`。
BGM_DAY_LOOP = "bgm_day_cute3_loop"

#: 白天关卡候选 BGM（⏔ 备用，⏳「接不接 / 用哪条」待 Ronny 拍板）。
#:   Ronny 11:00 已拍板主力件 = `bgm_day_cute3`（可爱风），
#:   `alt15s` 建议接但**不作主力**（备用机位）。
BGM_DAY_ALTS = ("bgm_day_cute_15s_loop", "bgm_day_cute_alt15s_loop")

#: 本批要用到的全部素材（自测按这张表逐个验加载）
ALL_SOUNDS = tuple(sorted(SND_LEN.keys()))


# ============================================================================
# ④ 引擎
# ============================================================================

class Audio:
    """夜间冒险的音频引擎。**一个实例 = 一套混音**。

    ⭐ 构造时就**把全部素材加载完**（而不是用到才加载）：
       加载是异步的（`status()==Loading`），"第一次敲罐子没声音、第二次有了"
       是最难看的一种 bug。构造时统一加载 + 校验，失败立刻可见。
    """

    def __init__(self, parent=None, load_timeout_ms: int = 3000):
        self.dir = AUDIO_DIR
        self.errors = []              # [(name, reason)] —— ⛔ 非空就是有问题
        self.loaded = {}              # name -> QSoundEffect
        self._loops = {}              # name -> QSoundEffect（循环中的底噪/面板音）
        self._parent = parent
        self.ok = False
        if not _HAVE_QTMM:
            self.errors.append(("<QtMultimedia>", "PySide6.QtMultimedia 不可用（打包漏插件？）"))
            print("[音频] ⛔ QtMultimedia 不可用 —— 全部静音。源码能响而打包后无声，"
                  "十有八九是 spec 的 excludes里还留着 QtMultimedia。")
            return
        self._load_all(load_timeout_ms)
        self.ok = (len(self.errors) == 0)

    # ------------------------------------------------------------------
    def _load_one(self, name: str, timeout_ms: int,
                  parent=None) -> "QSoundEffect | None":
        """加载一条。⛔ 任何一步不对都往 `self.errors` 记，**不许静默**。"""
        fn = name + ".wav"
        path = os.path.join(self.dir, fn)
        if not os.path.isfile(path):
            self.errors.append((name, f"文件不存在: {path}"))
            print(f"[音频] ⛔ 缺素材 {fn}（期望在 {self.dir}）")
            return None
        try:
            eff = QSoundEffect(parent)
            # ⭐ 绝对路径：QUrl.fromLocalFile 对相对路径的解析依赖 CWD，
            #   而打包后 CWD 是 exe 所在目录 ⇒ 相对路径会指向别处。
            eff.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        except Exception as e:
            self.errors.append((name, f"构造失败: {type(e).__name__}: {e}"))
            print(f"[音频] ⛔ {fn} 构造失败: {type(e).__name__}: {e}")
            return None
        # ⭐ 同步等加载完成。QSoundEffect 没有 loaded 信号（实测 PySide6 6.x
        #   只有 statusChanged / playingChanged），所以只能轮询 status()。
        #   ⛔ 别用 `while eff.status()==Loading: pass` —— 那是死循环（要跑事件循环）。
        waited = 0
        step = 20
        while eff.status() == QSoundEffect.Status.Loading and waited < timeout_ms:
            _pump(step)
            waited += step
        st = eff.status()
        if st == QSoundEffect.Status.Error or not eff.isLoaded():
            #⛔ 这一支是本批最关键的一行：`QSoundEffect` 加载失败**不抛异常**，
            #   症状就是"游戏正常跑但没声音"，极难查。所以必须显式判。
            self.errors.append((name, f"加载失败 status={st}（文件可能不是真 wav）"))
            print(f"[音频] ⛔ {fn} 加载失败 status={st}")
            return None
        eff.setVolume(0.0)             # ⛔ 静音直到真正 play（offscreen 自测不许出声）
        return eff

    def _load_all(self, timeout_ms: int) -> None:
        for name in ALL_SOUNDS:
            eff = self._load_one(name, timeout_ms, parent=self._parent)
            if eff is not None:
                self.loaded[name] = eff
        if self.errors:
            print(f"[音频] ⚠️ {len(self.errors)}/{len(ALL_SOUNDS)} 条加载失败："
                  + "、".join(n for n, _ in self.errors))
        else:
            print(f"[音频] ✓ {len(self.loaded)}/{len(ALL_SOUNDS)} 条已加载"
                  f"（{self.dir}）")

    # ------------------------------------------------------------------
    # 播放
    # ------------------------------------------------------------------
    def play(self, name: str, gain: float = 1.0, loop: bool = False) -> bool:
        """播一条。返回是否真的播了（失败一律 False + 已记进 errors）。

        ⭐ `loop=True` 用**独立实例**：同一条既要"播一次"又要"循环"时
          （结算 sting）必须是两个对象 —— 一个 QSoundEffect 只有一个播放头。
        """
        if name not in self.loaded:
            if name and not any(n == name for n, _ in self.errors):
                self.errors.append((name, "未加载（不在素材表里？）"))
            return False
        eff = self.loaded[name]
        try:
            eff.setLoopCount(SND_LOOP_FOREVER if loop else 1)
            eff.setVolume(_vol(name) * gain)
            eff.play()
        except Exception as e:
            self.errors.append((name, f"播放失败: {type(e).__name__}: {e}"))
            print(f"[音频] ⛔ 播 {name} 失败: {type(e).__name__}: {e}")
            return False
        return True

    def loop(self, name: str, gain: float = 1.0) -> bool:
        """起一条**循环**底噪。同一name 重复调用不会重起（幂等）。"""
        if name in self._loops:
            eff = self._loops[name]
            eff.setVolume(_vol(name) * gain)
            if not eff.isPlaying():
                eff.play()
            return True
        if name not in self.loaded:
            return False
        eff = QSoundEffect()
        try:
            eff.setSource(self.loaded[name].source())
            eff.setLoopCount(SND_LOOP_FOREVER)
            eff.setVolume(_vol(name) * gain)
            eff.play()
        except Exception as e:
            self.errors.append((name, f"循环失败: {type(e).__name__}: {e}"))
            print(f"[音频] ⛔ 循环 {name} 失败: {type(e).__name__}: {e}")
            return False
        self._loops[name] = eff
        return True

    def stop_loop(self, name: str) -> None:
        eff = self._loops.pop(name, None)
        if eff is not None:
            try:
                eff.stop()
            except Exception:
                pass

    def stop_all(self) -> None:
        """离场（关窗口 / 回菜单）必须停掉循环底噪，
        ⛔ 否则菜单里还响着厨房环境音。"""
        for name in list(self._loops.keys()):
            self.stop_loop(name)
        for eff in self.loaded.values():
            try:
                eff.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 语义封装（接线处只认这些，不认文件名）
    # ------------------------------------------------------------------
    def sfx_pick(self, kind: str) -> bool:
        """拿容器。⭐ 按 kind 选音 ⇒ 玩家听得出手上拿的是哪一档。"""
        return self.play(PICK_BY_KIND.get(kind, "sfx_pick_plate"))

    def sfx_qte_tick(self) -> bool:
        """QTE 每按一下。⛔ 用008 版（0.08s），⛔ 不是 0.48s 那条。"""
        return self.play("sfx_qte_tick_008")

    def sting(self, name: str) -> bool:
        """结算/被抓 sting。⭐ **只播一次**（⛔ 不循环、不新建循环实例）。

        ## ⭐⭐ 2026-10-05 设计端拍板（量测结论，不是风格偏好）
        旧版的 `loop_in_panel` 参数已被**删除**。它会： sting 播完 → 起一个
        同名**循环实例** ⇒ 3.5 秒的短动机**每 3.5 秒重播一次**
        ⇒ 玩家听到「咚—(轻 3.5s)—咚—(轻 3.5s)—」。
        实测证明**短动机比 12 秒长乐句更容易被听出循环**。

        ## ⭐⭐ 2026-10-06 PR-06：「面板期底音」那一路（把厨房环境音降音量当底音）
        ##   连同它的两个常量**一起删干净**了——
        ##   Ronny 2026-10-05 已判「环境音不要了」，那条环境音素材与增益表项
        ##   早已全部移除 ⇒ 那个函数早已是个**永远返回 False 的空函数**
        ##   （它只去找那条环境音的循环实例，而那个实例已不存在）。
        ##   ⇒ 留着它就是留一段死代码 + 两个没人读的常量。
        ⛔ 本函数⛔ 不建任何循环实例（自测按"新建 loop 实例数==0"守这条）。
        """
        return self.play(name)

    # ------------------------------------------------------------------
    def status_line(self) -> str:
        if not self.loaded and not self.errors:
            return "[音频] 未初始化"
        base = f"[音频] {len(self.loaded)}/{len(ALL_SOUNDS)} 条就绪"
        if self.errors:
            base += "  ⛔ 失败：" + "、".join(n for n, _ in self.errors)
        return base


def _vol(name: str) -> float:
    """该素材的线性音量。未知素材给1.0（不静默失声）。"""
    return float(SND_GAIN.get(name, 1.0))


def _pump(ms: int) -> None:
    """跑 ms 毫秒的事件循环（加载要等 Qt 解码线程，故必须让出主线程）。"""
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
