# -*- coding: utf-8 -*-
"""PR-30 白天档验收：真的把窗口起起来画一帧，把画出来的东西录下来看。

⭐ 不是「读源码猜它应该画什么」，是 monkeypatch 住 QPainter 的调用、报**真实参数**。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import (QPainter, QPen, QBrush, QColor, QFont, QRadialGradient,
                           QLinearGradient, QPixmap)
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet_engine.core import load_pack
from pet_engine import night as N

pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = N.NightWindow(pack)

FAILS = []

_pm = QPixmap(1280, 720)


def _draw(fn):
    """起一个离屏 QPainter 喂给 fn，画完立刻 end()。

    ⛔ 必须 end —— 同一设备上的第二个 QPainter 起不来，spy 会录到空。
    """
    p = QPainter(_pm)
    try:
        fn(p)
    finally:
        p.end()


def chk(name, ok, detail=""):
    print(("  OK   " if ok else " FAIL  ") + name + ("   " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


print("=" * 72)
print("PR-30 · ① _day 三处赋值是否都拿到真值")
print("=" * 72)
chk("__init__ 后 self._day 为 True（NIGHTS[0].name=正午）", w._day is True,
    f"_day={w._day}")
w.start_night(0)
chk("start_night(0) 后 self._day 为 True", w._day is True, f"_day={w._day}")
w._day = False                      # 先污染，看 set_mode 能不能纠正回来
w.set_mode("play")
chk("set_mode('play') 后 self._day 被重新赋真（污染后能自愈）", w._day is True,
    f"_day={w._day}")
chk("_is_day_level 走的是函数不是写死", N._is_day_level({"name": "凌晨三点"}) is False,
    "拿夜档名试：False")

print()
print("=" * 72)
print("PR-30 · ② 菜单真实画出来的标题字符串")
print("=" * 72)
w.phase = "menu"
_texts = []
_orig_drawText = QPainter.drawText


def _spy_drawText(self, *a, **kw):
    for arg in a:
        if isinstance(arg, str):
            _texts.append(arg)
    return _orig_drawText(self, *a, **kw)


QPainter.drawText = _spy_drawText
# ⛔ offscreen 下 `repaint()` 不真的画 —— 必须 `render()` 才会走 paintEvent。
_draw(lambda p: w.render(p, QPoint(0, 0)))
QPainter.drawText = _orig_drawText

hits = [t for t in _texts if "猫猫公寓" in t]
print("  实际 drawText 出来的「猫猫公寓…」标题：", hits)
chk("白天档标题 = 猫猫公寓 · 正午厨房", "猫猫公寓 · 正午厨房" in hits)
chk("副标 = 阳光正好，他在打盹。我来看看屋里有什么吃的~",
    "阳光正好，他在打盹。我来看看屋里有什么吃的~" in _texts)
chk("标题只画了一遍（原来重复画两遍）", hits.count("猫猫公寓 · 正午厨房") == 1,
    f"出现 {hits.count('猫猫公寓 · 正午厨房')} 次")
chk("菜单里不再出现「夜间冒险」", not any("夜间冒险" in t for t in _texts))
chk("菜单里不再出现「深夜的公共区域」",
    not any("深夜的公共区域" in t for t in _texts))

print()
print("=" * 72)
print("PR-30 · ③ 视野锥：白天档到底 setBrush 了没有")
print("=" * 72)
_brush = []
_pen = []
_orig_setBrush = QPainter.setBrush
_orig_setPen = QPainter.setPen


def _spy_setBrush(self, b):
    if isinstance(b, QColor):
        _brush.append(("QColor", b.red(), b.green(), b.blue(), b.alpha()))
    elif isinstance(b, QBrush):
        # ⚠️ 渐变笔刷 `b.color()` 恒为黑 —— 得去 gradient 的 stop 里取色。
        gr = b.gradient()
        if gr is not None:
            stops = [(s[1].red(), s[1].green(), s[1].blue(), s[1].alpha())
                     for s in gr.stops()]
            _brush.append(("Gradient",) + tuple(stops))
        else:
            c = b.color()
            _brush.append(("QBrush", c.red(), c.green(), c.blue(), c.alpha()))
    else:
        _brush.append((type(b).__name__,))
    return _orig_setBrush(self, b)


def _spy_setPen(self, pn):
    if isinstance(pn, QPen):
        c = pn.color()
        _pen.append((pn.style(), pn.widthF(), c.red(), c.green(), c.blue(), c.alpha()))
    else:
        _pen.append((str(pn),))
    return _orig_setPen(self, pn)


QPainter.setBrush = _spy_setBrush
QPainter.setPen = _spy_setPen

w.start_night(0)
w.mw.state = "patrol"
w.mw.alert = 0.0
_brush.clear(); _pen.clear()
_draw(w._draw_mw)
b_patrol, p_patrol = list(_brush), list(_pen)

w.mw.state = "chase"
_brush.clear(); _pen.clear()
_draw(w._draw_mw)
b_chase, p_chase = list(_brush), list(_pen)

QPainter.setBrush = _orig_setBrush
QPainter.setPen = _orig_setPen

print("  [patrol] setBrush 调用：", b_patrol)
print("  [patrol] setPen   调用：", p_patrol)
print("  [chase ] setBrush 调用：", b_chase)
print("  [chase ] setPen   调用：", p_chase)

_chk_brush = [b for b in b_patrol if len(b) == 5]
chk("白天档 patrol：没有橙色填充（不再 setBrush(255,170,80,*)）",
    not any(b[1] == 255 and b[2] == 170 and b[3] == 80 for b in _chk_brush),
    f"setBrush 了 {len(_chk_brush)} 次：{_chk_brush}")
_dash = [p for p in p_patrol if p[0] == Qt.DashLine]      
chk("白天档 patrol：走了虚线轮廓 Qt.DashLine", len(_dash) >= 1, f"{_dash}")
chk("白天档 patrol：虚线颜色 (120,110,96,70)",
    any(p[0] == Qt.DashLine and (p[2], p[3], p[4], p[5]) == (120, 110, 96, 70) for p in p_patrol))

_chk_brush_c = [b for b in b_chase if len(b) == 5]
chk("白天档 chase：也没有填充", not any(b[1] == 255 and b[2] == 170 and b[3] == 80
                                        for b in _chk_brush_c), f"{_chk_brush_c}")
chk("白天档 chase：虚线 alpha 提到 130",
    any(p[0] == Qt.DashLine and (p[2], p[3], p[4], p[5]) == (120, 110, 96, 130) for p in p_chase),
    f"{[p for p in p_chase if p[0] == Qt.DashLine]}")

print()
print("=" * 72)
print("PR-30 · ④ 夜间档视野锥必须原样保留（_day=False 时仍有橙色渐变填充）")
print("=" * 72)
w._day = False
QPainter.setBrush = _spy_setBrush
QPainter.setPen = _spy_setPen
_brush.clear(); _pen.clear()
w.mw.state = "patrol"
w.mw.alert = 0.5
_draw(w._draw_mw)
QPainter.setBrush = _orig_setBrush
QPainter.setPen = _orig_setPen
print("  [夜间 patrol] setBrush：", _brush)
chk("夜间档仍有橙色 (255,170,80) 渐变填充",
    any(b[0] == "Gradient" and any(s[0] == 255 and s[1] == 170 and s[2] == 80
                                   for s in b[1:]) for b in _brush),
    f"{_brush}")
w._day = True

print()
print("=" * 72)
print("PR-30 · ④b 菜单底图 _draw_bg：白天档真画出来的颜色")
print("=" * 72)
def _has(colors, rgb):
    for b in colors:
        if b[0] == "Gradient":
            if any(s[:3] == rgb for s in b[1:]):
                return True
        elif len(b) == 5 and b[1:4] == rgb:
            return True
    return False


# ⚠️ _draw_bg 的渐变走 `fillRect(rect, QBrush(g))` 而不是 setBrush ⇒ 得单独录。
_orig_fillRect = QPainter.fillRect


def _spy_fillRect(self, rect, b):
    if isinstance(b, QBrush):
        gr = b.gradient()
        if gr is not None:
            _brush.append(("Gradient",) + tuple(
                (s[1].red(), s[1].green(), s[1].blue(), s[1].alpha())
                for s in gr.stops()))
        else:
            c = b.color()
            _brush.append(("QBrush", c.red(), c.green(), c.blue(), c.alpha()))
    elif isinstance(b, QColor):
        _brush.append(("QColor", b.red(), b.green(), b.blue(), b.alpha()))
    return _orig_fillRect(self, rect, b)


QPainter.setBrush = _spy_setBrush
QPainter.fillRect = _spy_fillRect
w._day = True
_brush.clear()
_draw(w._draw_bg)
day_bg = list(_brush)
w._day = False
_brush.clear()
_draw(w._draw_bg)
night_bg = list(_brush)
QPainter.setBrush = _orig_setBrush
QPainter.fillRect = _orig_fillRect
w._day = True

print("  [白天] 画出来的颜色：", day_bg)
print("  [夜间] 画出来的颜色：", night_bg)


chk("白天底图渐变顶 (232,222,205)", _has(day_bg, (232, 222, 205)))
chk("白天底图渐变底 (198,184,164)", _has(day_bg, (198, 184, 164)))
chk("白天窗外框 (237,230,216)", _has(day_bg, (237, 230, 216)))
chk("白天玻璃亮天光 (203,224,240)", _has(day_bg, (203, 224, 240)))
chk("白天家具剪影 (150,138,120)", _has(day_bg, (150, 138, 120)))
chk("白天底图里不再有夜蓝 (18,20,34)",
    not _has(day_bg, (18, 20, 34)), f"{day_bg}")
chk("夜间底图仍保留夜蓝 (18,20,34)", _has(night_bg, (18, 20, 34)))
chk("夜间底图仍保留月光蓝 (150,170,220)", _has(night_bg, (150, 170, 220)))

print()
print("=" * 72)
print("PR-30 · ⑤ 窗口标题 + 旁白文案")
print("=" * 72)
chk("窗口标题 = 猫猫公寓 · 正午厨房",
    w.windowTitle() == "猫猫公寓 · 正午厨房", repr(w.windowTitle()))
chk('NARRATION["enter"] 三条全换',
    N.NARRATION["enter"] == ["中午，他在打盹。", "阳光太亮了。正好，看得清。",
                             "这个点没人进厨房。"], str(N.NARRATION["enter"]))
chk('NARRATION["cross"][0] = 规矩我懂。但今天例外。',
    N.NARRATION["cross"][0] == "规矩我懂。但今天例外。", repr(N.NARRATION["cross"][0]))
chk('NARRATION["home"][1] = 今天就到这儿。',
    N.NARRATION["home"][1] == "今天就到这儿。", repr(N.NARRATION["home"][1]))
_all_narr = [s for v in N.NARRATION.values() for s in v]
chk("旁白里没有残留「今晚」", not any("今晚" in s for s in _all_narr),
    str([s for s in _all_narr if "今晚" in s]))

print()
print("=" * 72)
print(("失败 %d 项" % len(FAILS)) if FAILS else "PR-30 全部通过")
for f in FAILS:
    print("   ✗ " + f)
print("=" * 72)
sys.exit(1 if FAILS else 0)
