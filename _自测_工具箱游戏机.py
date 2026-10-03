# -*- coding: utf-8 -*-
"""_自测_工具箱游戏机.py —— 验证「工具箱 → 游戏机入口」这条链路

⭐ 纪律：驱动真实 ToolBar 的方法（_open_entry / _slot_taken / paintEvent），
   ⛔ 不复刻一份点击逻辑。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))   # 模拟 run.py 的 sys.path

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from core import load_pack
import ui_toolbar as UT
import night as N

pack = load_pack(os.path.join(HERE, "packs", "luna"))

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


class _FakePet:
    """ToolBar 只用到 pet_window 的 pack / screen() / _held_tool"""
    def __init__(self, pack):
        self.pack = pack
        self._held_tool = None

    def screen(self):
        return QApplication.primaryScreen()

    def hold_tool(self, n):
        self._held_tool = n

    def update(self):
        pass


print("=" * 72)
print("① 槽位表")
print("=" * 72)
keys = [k for k, _ in UT.SLOTS]
chk("gamepad 已在槽位里", "gamepad" in keys, f"{keys}")
chk("展开高度按槽位数自适应", UT.H_OPEN == UT.H_CLOSED + UT.SLOT_H * len(UT.SLOTS) + 6,
    f"H_OPEN={UT.H_OPEN} 槽位 {len(UT.SLOTS)} 个")
chk("gamepad 被标为入口类", "gamepad" in UT._ENTRY_SLOTS)

print()
print("=" * 72)
print("② 入口类不该进「手持」状态")
print("=" * 72)
pet = _FakePet(pack)
bar = UT.ToolBar(pet)
chk("构造成功", bar is not None)
chk("gamepad 永不画成空槽", bar._slot_taken("gamepad") is False)
pet._held_tool = "gamepad"
chk("即使 _held_tool==gamepad 也不画空槽", bar._slot_taken("gamepad") is False)
pet._held_tool = "wand"
chk("普通道具照旧会画空槽", bar._slot_taken("wand") is True)
pet._held_tool = None

print()
print("=" * 72)
print("③ 点 gamepad → 开夜间冒险")
print("=" * 72)
bar.open = True
bar.setGeometry(bar._home.x(), bar._home.y(), UT.W_OPEN, UT.H_OPEN)
gi = keys.index("gamepad")
r = bar._slot_rect(gi)
chk("gamepad 槽位矩形在窗口内", r.bottom() <= UT.H_OPEN,
    f"槽位 y[{r.top()},{r.bottom()}] 窗口高 {UT.H_OPEN}")

bar._open_entry("gamepad")
nw = getattr(bar, "_night", None)
chk("窗口已创建", nw is not None)
chk("是 NightWindow", isinstance(nw, N.NightWindow) if nw else False,
    f"type={type(nw).__name__ if nw else None}")
chk("工具栏进游戏时藏起来了", not bar.isVisible())

first = nw
bar._open_entry("gamepad")
chk("重复点复用同一个窗口（不叠开）", getattr(bar, "_night", None) is first)

print()
print("=" * 72)
print("④ 关掉游戏 → 工具栏回来")
print("=" * 72)
try:
    first.close()
    chk("关闭不抛异常", True)
except Exception as e:
    chk("关闭不抛异常", False, f"{type(e).__name__}: {e}")
app.processEvents()
chk("_night 引用已清", getattr(bar, "_night", None) is None)
chk("工具栏恢复显示", bar.isVisible())

# ⭐ 关掉之后再点一次：C++ 对象已析构，必须能重建而不是抛 RuntimeError
try:
    bar._open_entry("gamepad")
    chk("析构后能重建（不抛 RuntimeError）", getattr(bar, "_night", None) is not None)
except RuntimeError as e:
    chk("析构后能重建（不抛 RuntimeError）", False, f"{e}")

print()
print("=" * 72)
print("⑤ 绘制（真实 paintEvent，含新画的手柄）")
print("=" * 72)
bar.open = True
bar._hover_slot = gi
try:
    pm = QPixmap(bar.size())
    pm.fill(Qt.transparent)
    bar.render(pm)
    chk("展开态能画（含 gamepad 图标）", True)
except Exception as e:
    chk("展开态能画（含 gamepad 图标）", False, f"{type(e).__name__}: {e}")

pm.save(os.path.join(HERE, "_work", "工具箱-游戏机槽位.png"))
print("   写出 _work/工具箱-游戏机槽位.png")

bar.open = False
try:
    pm = QPixmap(UT.W_CLOSED, UT.H_CLOSED)
    pm.fill(Qt.transparent)
    bar.render(pm)
    chk("收起态能画", True)
except Exception as e:
    chk("收起态能画", False, f"{type(e).__name__}: {e}")

print()
print("=" * 72)
print(f"通过 {len(OK)} / {len(OK)+len(BAD)}")
if BAD:
    print("未通过： " + "、".join(BAD))
print("=" * 72)
