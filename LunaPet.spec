# -*- mode: python ; coding: utf-8 -*-
"""LunaPet.spec —— 桌面宠物（PySide6）打包配置

重打方式（在项目根目录执行）：
    pyinstaller --noconfirm --clean LunaPet.spec
或者直接双击/运行 `打包.bat`。

⭐ 为什么选 --onedir 而不是 --onefile（两种都真打出来量过，不是猜的）：

               体积        冷启动(同机热缓存)      距 5 秒判定线的余量
    onedir     98.6 MB 目录    0.84 s              6 倍
    onefile    50.7 MB 单文件  3.11 ~ 3.54 s       1.4 倍

    onefile 确实更小、更方便发一个文件，但它**每次启动**都要把包里那 ~98MB
    解压到 %TEMP% 再跑，实测光解压就占掉 2.4~2.8 秒；这点余量在慢机械盘或
    被杀软实时扫描的机器上很容易破线。onedir 只有第一次读盘稍慢（3.49 秒），
    之后稳定 0.9 秒左右。所以交付用 onedir。
    想换成 onefile：把下面 EXE() 的 exclude_binaries 改成 False、把 a.binaries /
    a.datas 直接传给 EXE()，并删掉 COLLECT()。
"""
import os

ROOT = SPECPATH          # PyInstaller 注入：spec 所在目录（= 项目根）

NAME = "LunaPet"

# ① 是否保留控制台窗口
#    True  → 双击后会带一个黑窗口，能看到 [引擎]/[轮廓]/[帧] 等日志（排查问题用）
#    False → 干净的纯宠物窗口，但看不到任何 print
CONSOLE = True

# ② 是否保留 Qt 的软件 OpenGL 兜底库 opengl32sw.dll（19.7MB，占整包 ~18%）
#    本程序是纯 2D 光栅绘制（QPainter 画到半透明 QWidget 上），从不创建 OpenGL 上下文，
#    实测删掉后正常启动。⚠️ 若在「没装显卡驱动 / 远程桌面 / 虚拟机」上出现白屏或
#    "Failed to create OpenGL context"，把这里改回 True 重打即可。
KEEP_SOFTWARE_OPENGL = False


# ============================================================================
# ⛔ 排除清单 —— 本程序只用到 PySide6 的 QtCore / QtGui / QtWidgets
# ============================================================================
EXCLUDES = [
    # ---- 体积最大、且和本程序完全无关的 Qt 模块 ----
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtWebView",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSpatialAudio",
    # ---- QML / Quick 家族：被 QtGui 的插件目录连带拖进来的（见下方说明）----
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtQuickControls2", "PySide6.QtVirtualKeyboard",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    # ---- 其他用不上的 ----
    "PySide6.QtNetwork", "PySide6.QtNetworkAuth",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtXml",
    "PySide6.QtPrintSupport",
    # ---- 标准库里的网络/加密栈：宠物是纯本地窗口程序，不联网 ----
    #    省下 libcrypto-3-x64.dll(5.5MB) + libssl-3-x64.dll(1.0MB)。
    #    注意：这里**只排 _hashlib/_ssl 这两个 C 扩展**，Python 层的 hashlib 仍然保留，
    #    它会自动退回到内置的 _sha2/_md5/_sha3，import hashlib 不会失败。
    "ssl", "_ssl", "_hashlib",
    "charset_normalizer",
]

# ============================================================================
# ⛔ 要单独剔掉的 Qt 插件（Analysis 之后从 TOC 里删）
#
# 为什么必须手工删：PyInstaller 的 PySide6 hook 是按【整目录】收集插件的
# （QtGui 会收下 imageformats / platforminputcontexts / platforms 等整个目录），
# 于是两个几十 KB 的插件把一大串 Qt 库连带拖了进来：
#     imageformats/qpdf.dll                (40KB) → Qt6Pdf → Qt6Quick + Qt6Qml  ≈ 16MB
#     platforminputcontexts/qtvirtualkeyboardplugin.dll (23KB) → Qt6VirtualKeyboard → Qt6Quick + Qt6Qml
# 实测这两个插件一删，Qt6Qml/Quick/Pdf 一共约 17MB 就整条断掉了。
# ============================================================================
DROP_PLUGINS = {
    # 本程序只读 PNG，而 Qt6 里 PNG 解码是内建在 QtGui 里的（没有 qpng 插件），
    # 下面这些图片格式一个都用不上
    "PySide6/plugins/imageformats/qgif.dll",
    "PySide6/plugins/imageformats/qicns.dll",
    "PySide6/plugins/imageformats/qjpeg.dll",
    "PySide6/plugins/imageformats/qpdf.dll",
    "PySide6/plugins/imageformats/qsvg.dll",
    "PySide6/plugins/imageformats/qtga.dll",
    "PySide6/plugins/imageformats/qtiff.dll",
    "PySide6/plugins/imageformats/qwbmp.dll",
    "PySide6/plugins/imageformats/qwebp.dll",
    # 没有 svg 图标
    "PySide6/plugins/iconengines/qsvgicon.dll",
    # 软键盘输入法（就是它拖进了 Qt6VirtualKeyboard/Qml/Quick）
    "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
    # 只保留默认的 windows 平台插件；direct2d/minimal/offscreen 都是特殊场景
    "PySide6/plugins/platforms/qdirect2d.dll",
    "PySide6/plugins/platforms/qminimal.dll",
    "PySide6/plugins/platforms/qoffscreen.dll",
    # 触摸屏虚拟鼠标
    "PySide6/plugins/generic/qtuiotouchplugin.dll",
    # QtNetwork 的插件（已排除 QtNetwork 模块）
    "PySide6/plugins/tls/qcertonlybackend.dll",
    "PySide6/plugins/tls/qopensslbackend.dll",
    "PySide6/plugins/tls/qschannelbackend.dll",
    "PySide6/plugins/networkinformation/qnetworklistmanager.dll",
}

# 上表的插件删掉后，这些 Qt 库就没有任何调用方了（已用 pefile 扫过导入表确认）
DROP_QT_LIBS = {
    "PySide6/Qt6Pdf.dll",
    "PySide6/Qt6Svg.dll",
    "PySide6/Qt6VirtualKeyboard.dll",
    "PySide6/Qt6Quick.dll",
    "PySide6/Qt6Qml.dll",
    "PySide6/Qt6QmlMeta.dll",
    "PySide6/Qt6QmlModels.dll",
    "PySide6/Qt6QmlWorkerScript.dll",
    "PySide6/Qt6Network.dll",
    "PySide6/QtNetwork.pyd",
    # 无人引用的死重：QtOpenGL 只被 Qt6OpenGLWidgets / Qt6Quick 用，这两个都已排除
    # （已用 pefile 连延迟导入表一起扫过：包内没有第二个文件引用它）
    "PySide6/Qt6OpenGL.dll",
}

# 整目录删
DROP_PREFIXES = [
    "PySide6/translations/",     # Qt 界面翻译 .qm，6.7MB。本程序不用 QTranslator
]
if not KEEP_SOFTWARE_OPENGL:
    DROP_QT_LIBS.add("PySide6/opengl32sw.dll")


# ============================================================================
# Analysis
# ============================================================================
a = Analysis(
    [os.path.join(ROOT, "pet_launcher.py")],          # 打包入口（不动 run.py/core.py/ui.py）
    pathex=[os.path.join(ROOT, "pet_engine")],        # 让 core / ui 能被找到
    binaries=[],
    # ⭐ 角色包整个塞进包里 → 用户双击 exe 就能看到宠物，不需要额外放文件
    # ⭐ 角色素材不随仓库发布 → 存在才打包；缺了也能构建
    datas=([(os.path.join(ROOT, "packs"), "packs")]
           if os.path.isdir(os.path.join(ROOT, "packs")) else []),
    # core.py / ui.py 在 pet_engine/ 下，是被 run.py 以顶层模块名导入的，静态分析看不到
    hiddenimports=["ui", "core", "pet_engine.console", "console"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

# ---- 体积裁剪：从 TOC 里剔掉上面列的插件 / 库 / 翻译 ----
_drop_all = DROP_PLUGINS | DROP_QT_LIBS


def _trim(toc):
    kept = []
    for entry in toc:
        dest = entry[0].replace("\\", "/")
        if dest in _drop_all or any(dest.startswith(p) for p in DROP_PREFIXES):
            continue
        kept.append(entry)
    return kept


a.binaries = _trim(a.binaries)
a.datas = _trim(a.datas)

# ============================================================================
# 打包
# ============================================================================
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # 不压 UPX：压过的 Exe 容易被杀软误报，且拖慢启动
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # ⭐ 图标是角色资产，不随仓库发布 → 没有就不带图标
    icon=os.path.join(ROOT, "app_icon.ico")
    if os.path.exists(os.path.join(ROOT, "app_icon.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=NAME,
)
