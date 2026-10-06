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

# ⭐ 2026-10-05：判据改验「游戏主界面」后需要 gamehub 的类型。
#   ⛔ 但 gamehub 在函数内 import night / hundred，存在成环风险
#   （ui → ui_toolbar → night → ui，见 ui_toolbar.py:127 的注释）。
#   ⇒ 这里放在**模块顶层但在 ui_toolbar 之后**导入，与 ui_toolbar 自身的做法一致；
#     若真成环，脚本会当场ImportError 而不是静默假绿（这是可接受的失败方式）。
import gamehub as HUB

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
# ⭐ 2026-10-05 程序端更新判据（⛔ 不是改绿，是接线语义变了：10-05 加了游戏主界面）
#   旧断言：点 gamepad ⇒ bar._night 是 NightWindow。
#   现实现：点 gamepad ⇒ 先开 **GameHubWindow**（游戏主界面），
#           由主界面再仲裁到具体游戏窗口。⇒ 旧断言必然红，但**实现是对的**。
#   ⇒ 判据改成守"新的不变式"：主界面起来、且不是直开 night。
hw = getattr(bar, "_hub", None)
chk("窗口已创建", hw is not None)
chk("是游戏主界面 GameHubWindow", isinstance(hw, HUB.GameHubWindow) if hw else False,
    f"type={type(hw).__name__ if hw else None}")
chk("⛔ 不再直开 night（游戏选择归主界面仲裁）", getattr(bar, "_night", None) is None,
    f"_night={getattr(bar, '_night', None)}")
chk("工具栏进游戏时藏起来了", not bar.isVisible())

first = hw
bar._open_entry("gamepad")
chk("重复点复用同一个窗口（不叠开）", getattr(bar, "_hub", None) is first)

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
chk("_hub 引用已清", getattr(bar, "_hub", None) is None)
chk("工具栏恢复显示", bar.isVisible())

# ⭐ 关掉之后再点一次：C++ 对象已析构，必须能重建而不是抛 RuntimeError
try:
    bar._open_entry("gamepad")
    chk("析构后能重建（不抛 RuntimeError）", getattr(bar, "_hub", None) is not None)
except RuntimeError as e:
    chk("析构后能重建（不抛 RuntimeError）", False, f"{e}")

#⭐⭐ 补一条**旧判据根本问不到**的不变式（10-05 接线变更新引入的风险点）：
#   开了主界面**没进游戏**就退桌宠时，主界面必须一起收口，
#   否则桌宠没了、主界面还飘在屏上 —— 看起来像程序卡住。
#   ⛔ 这就是旧判据"只关_night 会漏"的那个坑，现已由 ui_toolbar.closeEvent 双收口修掉。
bar3 = UT.ToolBar(_FakePet(pack))
bar3._open_entry("gamepad")
_hub3 = getattr(bar3, "_hub", None)
_night3 = getattr(bar3, "_night", None)
chk("复核用：主界面已开、且确实没进游戏", _hub3 is not None and _night3 is None,
    f"_hub={_hub3 is not None} _night={_night3}")
bar3.close()          # 触发工具箱 closeEvent
app.processEvents()
chk("⛔ 退出桌宠时主界面被一起收口（不留屏上幽灵窗口）",
    getattr(bar3, "_hub", None) is None, f"_hub={getattr(bar3, '_hub', None)}")
try:
    del bar3
except Exception:
    pass

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
# ⛔ 2026-10-05 补退出码：原来失败也返回 0⇒ 挂CI / 批量脚本里发现不了。
sys.exit(1 if BAD else 0)
