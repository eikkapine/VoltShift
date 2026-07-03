# PyInstaller spec for VoltShift.
#
# Build from the repo root:
#   py -3.12 -m PyInstaller build/VoltShift.spec
# or use build/build_exe_py312.bat, which also builds the bridge first.
#
# The C++ bridge (voltshift_bridge.exe) is bundled next to the GUI so
# paths.bridge_path() finds it at runtime.

import os

repo_root = os.path.abspath(os.getcwd())
src_dir = os.path.join(repo_root, "src")
bridge_exe = os.path.join(repo_root, "bridge", "build", "Release", "voltshift_bridge.exe")
icon = os.path.join(repo_root, "assets", "icon.ico")

binaries = []
if os.path.isfile(bridge_exe):
    binaries.append((bridge_exe, "."))

a = Analysis(
    [os.path.join(src_dir, "voltshift_gui.py")],
    pathex=[src_dir],
    binaries=binaries,
    datas=[(os.path.join(repo_root, "assets", "icon.ico"), "assets")],
    hiddenimports=["customtkinter", "win32evtlog", "win32timezone", "psutil"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "PIL.ImageQt", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoltShift",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # windowed GUI app
    icon=icon if os.path.isfile(icon) else None,
    uac_admin=True,          # voltage writes need elevation
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="VoltShift",
)
