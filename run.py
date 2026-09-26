# -*- coding: utf-8 -*-
"""run.py —— 启动桌面宠物

用法：
    python run.py                      # 用默认角色包（packs/luna）
    python run.py <角色包目录>
    python run.py --preset 轻|中|重    # ⭐ 试手感预设（不用改文件就能 A/B）
    python run.py --tuner              # ⭐ 打开手感调试台（滑杆实时调 + 预设存/取 + A/B 对比）

⭐ 操作：
    · 左键拖拽 —— 拖动宠物（有倾斜和惯性）
    · 松手     —— 下落、落地、回正
    · 托盘图标 —— 显示/隐藏、退出
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))

from ui import run   # noqa: E402

def apply_preset(folder, name):
    """⭐ 把 pet.json 里 _预设 的某一档写到实际参数上（内存里改，不写盘）"""
    import json
    cfg_path = os.path.join(folder, "pet.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    presets = cfg.get("behaviour", {}).get("_预设", {})
    if name not in presets:
        print(f"⛔ 没有这个预设：{name}　可选：{list(presets)}")
        return False
    cfg["behaviour"].update(presets[name])
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[手感] 已切到「{name}」档：{presets[name]}")
    return True


if __name__ == "__main__":
    args = sys.argv[1:]
    preset = None
    if "--preset" in args:
        i = args.index("--preset")
        preset = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    tuner = "--tuner" in args          # ⭐ 必须在解析路径之前摘掉
    if tuner:
        args.remove("--tuner")
    pack = args[0] if args else os.path.join(HERE, "packs", "luna")
    if not os.path.isdir(pack):
        print(f"⛔ 角色包不存在：{pack}")
        sys.exit(1)
    if preset and not apply_preset(pack, preset):
        sys.exit(1)
    sys.exit(run(pack, tuner=tuner))
