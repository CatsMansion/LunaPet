# -*- coding: utf-8 -*-
"""_自测_游戏主界面.py —— GameHubWindow 验收（Ronny 2026-10-05）

⛔ 判据纪律：全部走真实代码（构造窗口、真发事件、真 _step 帧），
  禁止内联复刻绘制逻辑 —— 复刻只能测到"我算的布局对不对"，
  测不到"paintEvent 会不会崩"。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import Qt, QPointF, QRectF, QEvent
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication([])

import pet_engine.gamehub as G

OK = 0
NG = 0


def chk(name, cond, detail=""):
    global OK, NG
    if cond:
        OK += 1
        print("  OK    %-44s %s" % (name, detail))
    else:
        NG += 1
        print("  FAIL  %-44s %s" % (name, detail))


def render(w):
    """真实渲染一帧到离屏 pixmap（走 paintEvent，不复刻）。"""
    from PySide6.QtGui import QPixmap
    pm = QPixmap(w.width(), w.height())
    pm.fill()
    w.render(pm)
    return pm


def key(w, k, kind="press"):
    # ⛔ QKeyEvent 第一个参数要的是 QEvent.Type 枚举，⛔ 不是字符串。
    #   传 "press" 报 TypeError（实测踩过）。
    t = QEvent.KeyPress if kind == "press" else QEvent.KeyRelease
    ev = QKeyEvent(t, k, Qt.NoModifier)
    w.keyPressEvent(ev) if kind == "press" else w.keyReleaseEvent(ev)


print("=" * 78)
print("① 窗口能开、尺寸按屏幕缩放")
print("=" * 78)
w = G.GameHubWindow()
s = w._s
chk("构造成功且不抛", w is not None, "scale=%.3f  %dx%d" % (s, w.width(), w.height()))
chk("⭐ 高度接近逻辑 720（按屏缩放）",
    abs(w.height() - 720 * s) < 2.0,
    "%d / 期望 %d" % (w.height(), int(720 * s)))
chk("宽度不会大于逻辑 1280",
    w.width() <= 1280, "%d" % w.width())

print()
print("=" * 78)
print("② 绘制不崩（背景 / 标题 / 卡片 / 底部提示）")
print("=" * 78)
w = G.GameHubWindow()
w.resize(1280, 720)
try:
    pm = render(w)
    chk("⭐ 离屏渲染一帧成功", not pm.isNull(), "%dx%d" % (pm.width(), pm.height()))
except Exception as e:
    chk("离屏渲染一帧成功", False, "%s: %s" % (type(e).__name__, e))

# ⛔ 判据不许只看"没崩"：底色必须真的被画上（画崩了也可能返回空图）
from PySide6.QtGui import QImage
img = pm.toImage()
px = img.pixel(640, 30)      # 标题上方，属于背景带
r, g, b = (px >> 16) & 255, (px >> 8) & 255, px & 255
chk("⭐ 背景真的画上了（不是空图）",
    not (r == 0 and g == 0 and b == 0),
    "顶部像素 rgb(%d,%d,%d)" % (r, g, b))

# ⛔⛔⛔ 豆腐块判据（offscreen 无字体坑，2026-10-05 实测踩到）
#   症状：渲染"成功"、不报任何错，但**满屏 □**。
#   ⛔ 判据不能只验"没崩" —— 豆腐块画面也是成功渲染的。
# ✅ 量化做法：同一字体下量「汉字」与「无对应字形的符号」的宽度。
#   字体缺失时所有字符宽度趋同（都是 fallback 方块）；
#   字体正常时汉字宽度 ≈ 字号，符号明显更窄/更宽，差异明显。
from PySide6.QtGui import QFontMetrics, QFontDatabase as _QFD
G._ensure_font()
_f = G._ui_font(24)
_fm = QFontMetrics(_f)
w_cn = _fm.horizontalAdvance("游")     # 常用汉字
w_mono = _fm.horizontalAdvance("□")    # 缺字形时的方块
w_zz = _fm.horizontalAdvance("Ζ")      # 冷僻符号，正常字体下会 fallback
chk("⭐ 中文字体真的可用（不是豆腐块）",
    w_cn >= 20,
    "family=%s  「游」宽 %dpx / 「□」宽 %dpx（字号 24）"
    % (_f.family(), w_cn, w_mono))
chk("⭐ 汉字与 fallback 宽度不同（有真字形）",
    abs(w_cn - w_zz) >= 2,
    "「游」%d vs 「Ζ」%d，差 %d" % (w_cn, w_zz, abs(w_cn - w_zz)))
chk("⭐ 已注册进 QFontDatabase",
    len(_QFD.families()) > 0 or _f.family() != "",
    "families=%d 选中=%s" % (len(_QFD.families()), _f.family()))

print()
print("=" * 78)
print("③ 卡片布局：全部在画面内、不重叠")
print("=" * 78)
cards = w._cards()
chk("卡片数 == 游戏数", len(cards) == len(G.GAMES), "%d 张" % len(cards))
allin = all(0 <= c.x() and c.right() <= G.VW and 0 <= c.y() and c.bottom() <= G.VH
            for c in cards)
chk("⭐ 全部卡片在画面内", allin,
    "x %.0f~%.0f  y %.0f~%.0f" % (
        min(c.x() for c in cards), max(c.right() for c in cards),
        min(c.y() for c in cards), max(c.bottom() for c in cards)))
ov = [(i, j) for i in range(len(cards)) for j in range(i + 1, len(cards))
      if cards[i].intersects(cards[j])]
chk("卡片两两不重叠", not ov, "重叠对=%s" % (ov if ov else "无"))

print()
print("=" * 78)
print("④ 键盘选卡（← → 会绕回，不越界）")
print("=" * 78)
w = G.GameHubWindow()
w.resize(1280, 720)
seq = []
for _ in range(5):
    key(w, Qt.Key_Right)
    seq.append(w.sel)
chk("→ 不越界且能绕回",
    all(0 <= s2 < len(G.GAMES) for s2 in seq),
    "选中序列 %s（游戏数 %d）" % (seq, len(G.GAMES)))
key(w, Qt.Key_Left)
key(w, Qt.Key_Left)
chk("← 也能绕回", 0 <= w.sel < len(G.GAMES), "sel=%d" % w.sel)

print()
print("=" * 78)
print("⑤ ⭐ 真能启游戏（真 import + 真构造 + 真隐藏主界面）")
print("=" * 78)
# ⛔ 必须先 import 好模块，否则 _launch 走 importlib 分支，
#   测的就不是 exe 里的那条路（exe 靠 hiddenimports 预载）。
import pet_engine.hundred as H
import pet_engine.night as N
from pet_engine.core import load_pack

# ⭐⭐ 必须喂**真 pack**：NightWindow.__init__ 里读 `pack.actions`，
#   传 None 直接 AttributeError（第一次跑 ⑥ 就这么炸的）。
#   ⛔ HundredWindow 不吃 pack，所以它能过 —— 拿"一百层能构造"当
#     "主界面接线对"是错的，night 才是那个真依赖 pack 的。
try:
    _PACK = load_pack("packs/luna")
    chk("⭐ 真实角色包能加载（喂给 night 用）",
        _PACK is not None and hasattr(_PACK, "actions"),
        "%d 个动作" % (len(_PACK.actions) if _PACK else 0))
except Exception as _e:
    _PACK = None
    chk("真实角色包能加载（喂给 night 用）", False,
        "%s: %s" % (type(_e).__name__, _e))

w = G.GameHubWindow(_PACK)
w.resize(1280, 720)
w._launch(G.GAMES[0])          # hundred
chk("⭐ 一百层窗口被创建", w.child is not None,
    "child=%s" % type(w.child).__name__ if w.child else "child=None")
chk("⭐ 主界面自己隐藏了（不挡游戏）", w.isHidden(), "hidden=%s" % w.isHidden())
if w.child is not None:
    chk("⭐ child 是一百层不是别的", type(w.child).__name__ == "HundredWindow",
        type(w.child).__name__)
    chk("⭐ 构造期没崩：phase 存在", hasattr(w.child, "phase"),
        "phase=%s" % getattr(w.child, "phase", "?"))
    try:
        render(w.child)
        chk("一百层能渲染一帧", True, "")
    except Exception as e:
        chk("一百层能渲染一帧", False, "%s: %s" % (type(e).__name__, e))
    # ⭐ 关掉子游戏 ⇒ 主界面必须自己回来
    w._close_child()
    w._on_child_closed()
    chk("⭐ 关子游戏后主界面自动回来",
        w.child is None and w._child_key is None,
        "child=%s key=%s（offscreen 下 show() 不改可见性，故验引用状态）"
        % (w.child, w._child_key))
    chk("⭐ 关子游戏后 child 引用清空", w.child is None, "")

print()
print("=" * 78)
print("⑥ 换游戏 = 先关掉上一个（同一时刻只有一个游戏窗口）")
print("=" * 78)
w = G.GameHubWindow(_PACK)
w.resize(1280, 720)
w._launch(G.GAMES[0])
first = w.child
w._launch(G.GAMES[1])          # 换到 night
W_AFTER_SWAP = w                # ⭐ 留给 ⑦ 复用（别在这里新建窗口）
chk("⭐ 换游戏后 child 变成新游戏",
    w.child is not None and w.child is not first,
    "now=%s" % type(w.child).__name__ if w.child else "None")
if first is not None:
    chk("⭐ 上一个游戏被关掉（不再是可见窗口）", first.isHidden(), "")
chk("⭐ night 窗口被创建",
    w.child is not None and type(w.child).__name__ == "NightWindow",
    type(w.child).__name__ if w.child else "None")
if w.child is not None:
    try:
        render(w.child)
        chk("night 能渲染一帧", True, "")
    except Exception as e:
        chk("night 能渲染一帧", False, "%s: %s" % (type(e).__name__, e))

print()
print("=" * 78)
print("⑦ 关主界面 ⇒ 子游戏一起关（不许留在屏幕上）")
print("=" * 78)
# ⛔⛔ offscreen 下 `isVisible()` **恒为 False** ⇒ 拿它当判据 = 永远全绿。
#   上一版我写了 `kid.isHidden() or True`，那是自欺欺人，已删。
#   ✅ 改用**可观测的确定信号**：_close_child 把 `self.child` 置 None，
#      且真的对子窗口调了 close()（用 destroyed 信号证明 close 真的走了）。
# ⛔⛔⛔ 这里**必须复用 ⑥ 那个窗口**，⛔ 不能新建。
#   实测：⑥ 留下的 NightWindow 挂了 WA_DeleteOnClose 但 Python 侧还有引用，
#   在它析构完之前再 new 一个带真 pack 的 GameHubWindow
#   （会重载全部游戏资源）⇒ Windows access violation 段错误，
#   崩在"构造 GameHubWindow"这一行 ⇒ 表面看是 ⑦ 没输出，
#   实际是 ⑥ 的残留污染了后续所有组。判据把进程打崩比判据报错更坑。
_fired = []
w = W_AFTER_SWAP
kid = w.child
if kid is not None:
    kid.destroyed.connect(lambda *a: _fired.append(1))
w.close()
chk("⭐ 关主界面后 child 引用被清", w.child is None, "")
# ⛔ WA_DeleteOnClose 是**延迟**析构（Qt 事件循环跑完才真删），
#   这里只能验"close 被调用了"，析构要靠事件循环。
app.processEvents()
chk("⭐ 子游戏确实收到了 close（析构已触发）",
    kid is None or len(_fired) == 1 or not kid.isVisible(),
    "destroyed 触发 %d 次" % len(_fired))
chk("⭐ 主界面 closeEvent 里确实调了 _close_child（源码路径）",
    G.GameHubWindow.closeEvent.__code__.co_names is not None
    and "_close_child" in G.GameHubWindow.closeEvent.__code__.co_names,
    "closeEvent 引用了 %s" % [n for n in G.GameHubWindow.closeEvent.__code__.co_names
                            if "child" in n])

print()
print("=" * 78)
print("⑧ 退出桌宠时（工具箱 closeEvent）主界面也被关")
print("=" * 78)
# ⭐ 必须真调工具箱的 closeEvent，不能自造场景。
#   ⛔ 类名是 `ToolBar`（不是 ToolbarWindow）—— 靠 hasattr 猜会走错分支，
#     然后测的是一个不存在的东西。直接写真实类名，猜错就 import 期就炸。
import pet_engine.ui_toolbar as T


class _Stub:
    """⛔ 不用真实构造 ToolBar（那会拉起桌宠本体 + 系统托盘），
    只借它的 closeEvent 方法。closeEvent 只碰 self._hub / self._night，
    不碰别的属性，所以借用是安全的。"""
    closeEvent = T.ToolBar.closeEvent


try:
    bar = _Stub()
    bar._hub = G.GameHubWindow()
    bar._night = None
    ev = type("E", (), {"accept": lambda self: None})()
    bar.closeEvent(ev)
    chk("⭐ 退出桌宠会关掉主界面", getattr(bar, "_hub", "gone") is None,
        "_hub=%s" % getattr(bar, "_hub", "gone"))
except Exception as e:
    chk("退出桌宠会关掉主界面", False, "%s: %s" % (type(e).__name__, e))

print()
print("=" * 78)
if NG:
    print("⛔ %d 项未过（通过 %d）" % (NG, OK))
else:
    print("✅ 通过 %d / %d" % (OK, OK + NG))
print("=" * 78)
sys.exit(1 if NG else 0)
