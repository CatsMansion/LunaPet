# -*- coding: utf-8 -*-
# drag hang 实装自测 v2：用 step() 推进（与真实渲染循环一致）
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
# ⛔ 原来这里是写死的本机绝对路径 —— 别人克隆下来直接跑必然报"角色包不存在"。
#    改成按脚本位置推（和 _自测_core.py / _自测_睡眠.py 一致）。
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pet_engine.core import load_pack, Pet

pack = load_pack(os.path.join(HERE, "packs", "luna"))
pet = Pet(pack, (0, 0, 1920, 1080))
fails = []
def check(name, cond, detail=""):
    tag = "✅" if cond else "⛔"
    print(f"  {tag} {name}  {detail}")
    if not cond: fails.append(name)

print("== 1. 配置 ==")
act = pack.actions["drag"]
check("frames=16 / loop=pingpong / anchor", act.frames==16 and act.loop=="pingpong"
      and pack.anchor_of("drag")==(256,190), f"{act.frames},{act.loop},{pack.anchor_of('drag')}")
check("idle anchor 不受影响", pack.anchor_of("idle")==(256,512), f"{pack.anchor_of('idle')}")

print("== 2. 状态机 ==")
pet.play("idle"); pet.step(0.016, (0,0,512,512))
pet.begin_drag(pet.body.x, pet.body.y)          # 与 ui.py 相同：begin 不搬 body
check("state==drag", pet.state=="drag")
pet.move_drag(960, 540)                          # 鼠标移动 → body 跟
check("body 跟光标", abs(pet.body.x-960)<1 and abs(pet.body.y-540)<1,
      f"body=({pet.body.x:.0f},{pet.body.y:.0f})")
seq=[]
for _ in range(60):                              # 60 步 × 1/12s = 5s，pingpong 应来回
    pet.step(1.0/12.0, (0,0,512,512))
    seq.append(pet.anim.seq[pet.anim.i])
uniq=sorted(set(seq))
check("帧在 0~15 且在动", all(0<=i<=15 for i in uniq) and len(uniq)>1, f"{uniq}")
# pingpong 往复：序列里应出现「增后减」
up = any(seq[i+1]-seq[i]==1 for i in range(len(seq)-1))
down = any(seq[i+1]-seq[i]==-1 for i in range(len(seq)-1))
check("pingpong 往复（有增有减）", up and down)

print("== 3. 倾斜（阻尼单摆）==")
thetas=[]
for k in range(30):                              # 快速右移 30 帧
    pet.move_drag(960+k*25, 540)
    pet.step(1.0/60.0, (0,0,512,512))
    thetas.append(pet._theta)
# ⛔ 原写法标着 "rad" 却乘 57.3 当度用 —— `_theta` 本来就是【度】
#    （core 里直接 clamp 到 drag_tilt_max=45）。标签写反了，改成直读。
check("右移产生正倾角", max(thetas)>0.05, f"θmax={max(thetas):.1f}°")
for k in range(30):                              # 快速左移
    pet.move_drag(960+750-k*25, 540)
    pet.step(1.0/60.0, (0,0,512,512))
    thetas.append(pet._theta)
check("左移倾角变负", min(thetas)<-0.05, f"θmin={min(thetas):.1f}°")

print("== 4. 松手 ==")
states=[]
pet.end_drag(); states.append(pet.state)
sil=(0,0,512,512)
for _ in range(120):
    pet.step(1.0/60.0, sil); states.append(pet.state)
check("经过 fall", "fall" in states, f"{set(states)}")
check("松手后 dragging=False", not pet.dragging)

print("== 5. 渲染路径 ==")
pet.begin_drag(pet.body.x, pet.body.y)
p=pet.current_frame_path()
check("渲染指向新素材", p and "drag_" in os.path.basename(p), p)

print()
# ⛔ 原来这里只 print 不 exit —— 失败也是退出码 0，等于没进 CI、不成契约。
if fails:
    print(f"⛔ 失败 {len(fails)} 项：{fails}")
else:
    print("✅ 全部通过")
sys.exit(1 if fails else 0)
