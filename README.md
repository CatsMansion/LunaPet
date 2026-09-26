# LunaPet

一个桌面宠物引擎。角色在桌面上走来走去、能被拖着甩、松手会掉下来、落地会回正，点多了还会自己朝你的光标走。

引擎是自研的，**不基于 DyberPet**。依赖只有 PySide6 和 numpy。

> ⚠️ **仓库里没有角色素材。**
> `packs/` 下面的每一帧都是角色资产，不随代码发布 —— 这里面也没有。
> 想跑起来得自己做一份角色包：格式见 [docs/PACK_FORMAT.md](docs/PACK_FORMAT.md)，
> 起手直接把 `packs/_template/pet.json` 复制过去改。

---

## 为什么单独分一层

`pet_engine/core.py` 是**纯逻辑**，一行 UI 代码都没有，也不 import PySide6。
状态机、物理、屏幕限位、拖拽手感全在这一层 —— 因为只有它能够无头测试（`_自测_core.py` 就是这么跑的）。

`pet_engine/ui.py` 只管窗口、绘制、鼠标、定时器，不判断任何业务。

分开的收益很实在：**将来换壳（Godot / Electron / 别的）只需要重写 ui.py，素材和参数一个字不动。**

| 文件 | 干什么 |
|---|---|
| `run.py` | 启动入口（`--preset 轻/中/重` 试手感，`--tuner` 开调试台）|
| `pet_engine/core.py` | 逻辑层：角色包加载 / 动作状态机 / 阻尼单摆 / 屏幕边界 |
| `pet_engine/ui.py` | 渲染层：窗口 / 绘制 / 鼠标 / 托盘 |
| `pet_engine/console.py` | 手感调试台（滑杆实时生效 + 预设存取 + A/B 秒切）|
| `pet_launcher.py` | 打包专用入口，只做路径决策，渲染与逻辑一行不改 |

---

## 跑起来

```bash
pip install -r requirements.txt

python run.py <你的角色包目录>     # 例：python run.py packs/mycat
python run.py <包> --preset 重     # 试手感：轻 / 中 / 重
python run.py <包> --tuner         # 开调试台，边拖边看参数效果
```

操作就两条：**左键拖拽**（有倾斜，有惯性），**松手**（下落、落地、回正）。托盘图标切换显示和退出。

---

## 两个设计决定，值得单独说

### ① 拖拽手感用阻尼单摆，不是插值公式

```
θ'' = −ω0²·sinθ − 2ζω0·θ' + F(鼠标速度)
```

鼠标速度是力，重力把它拉回，ζ<1 所以会晃过头 —— 那个"惯性感"就是从这来的。

麻烦的地方在于 `tilt_omega0`（回正快慢）、`tilt_zeta`（晃不晃）、`tilt_drive`（甩多猛才倾）**三个参数是耦合的**，光看公式推不出好看的手感。所以配了三档预设，外加一个滑杆调试台 —— ⛔ 别靠猜，拧出来。

### ② 走路不许太空步，这件事在格式层面解决

DyberPet 的动作配置里只有 `frame_move`（每帧位移）。它没有推导依据，所以只能手调，试窄了永远搜不到正确周期。

这里的 `pet.json` 要求填两个字段：

| 字段 | 含义 |
|---|---|
| `cycle_frames` | 一个完整循环跨多少帧（走路的两步就填这里）|
| `stride_px` | 一个循环前进多少像素 |

引擎自己算 `move_per_frame = stride_px / cycle_frames`。**填进去的就是"两步走多远"，不需要反推。**

---

## 自测

```bash
python _自测_core.py     # 无头，纯逻辑：状态机 / 物理 / 边界 / 步幅
python _自测_互动.py     # 合成真实鼠标事件，验证"点她真的有反应"
python _自测_手感.py     # 量化三档预设的峰值角度 / 滞后 / 回正时间
```

前两个要读 `packs/luna`，所以**克隆下来直接跑会报"角色包不存在"** —— 指到你自己那份包就行。

---

## 打包

```bash
python -m PyInstaller --noconfirm --clean LunaPet.spec
```

为什么排除掉一大堆 Qt 模块、为什么入口要另开一个 `pet_launcher.py`、中文日志在 exe 里的编码坑，都写在 [docs/BUILD.md](docs/BUILD.md)。

---

## 许可

代码 MIT。

**角色素材、角色设计和角色本身不在授权范围内** —— 仓库里本来也没有。
