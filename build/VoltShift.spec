# PyInstaller spec for VoltShift.
#
# Build from the repo root:
#   py -3.12 -m PyInstaller build/VoltShift.spec
# or use build/build_exe_py312.bat, which also builds the bridge first.
#
# The C++ bridge (voltshift_bridge.exe) is bundled next to the GUI so
# paths.bridge_path() finds it at runtime. PresentMon, if it has been
# fetched, is bundled the same way.

import os

repo_root = os.path.abspath(os.getcwd())
src_dir = os.path.join(repo_root, "src")
bridge_exe = os.path.join(repo_root, "bridge", "build", "Release", "voltshift_bridge.exe")
presentmon_exe = os.path.join(repo_root, "third_party", "presentmon", "PresentMon.exe")
icon = os.path.join(repo_root, "assets", "icon.ico")

binaries = []
if os.path.isfile(bridge_exe):
    binaries.append((bridge_exe, "."))
# Optional: frame-pacing telemetry. Absent, VoltShift falls back to RTSS or
# to hardware-only tuning, so a build without it is still functional.
if os.path.isfile(presentmon_exe):
    binaries.append((presentmon_exe, "."))

a = Analysis(
    [os.path.join(src_dir, "voltshift_gui.py")],
    pathex=[src_dir],
    binaries=binaries,
    datas=[(os.path.join(repo_root, "assets", "icon.ico"), "assets")],
    hiddenimports=[
        "customtkinter", "win32evtlog", "win32timezone", "psutil",
        # Foreground-window game detection.
        "win32gui", "win32process",
        # numpy backs the Gaussian-process optimiser; sqlite3 backs the
        # knowledge store. Both are required by Auto-Tune, so neither may be
        # excluded from the frozen build.
        "numpy", "sqlite3",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "PIL.ImageQt", "pytest"],
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
