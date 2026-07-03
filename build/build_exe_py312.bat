@echo off
setlocal EnableDelayedExpansion
title VoltShift - Build Executable

echo.
echo  ========================================================
echo   VoltShift - Build Executable
echo  ========================================================
echo.

:: Run from the repo root (parent of build\).
cd /d "%~dp0\.."

if not exist "src\voltshift_gui.py" (
    echo  [ERROR] Run this from the repo root or double-click from build\
    pause & exit /b 1
)

:: --- Python 3.12 check -----------------------------------------------------
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python 3.12 not found.
    echo          Install from https://python.org/downloads/release/python-3128/
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('py -3.12 --version 2^>^&1') do set PYVER=%%v
echo  [OK] !PYVER!

:: --- Bridge -----------------------------------------------------------------
if not exist "bridge\build\Release\voltshift_bridge.exe" (
    echo  [INFO] Bridge not built yet - building it now...
    if not exist "third_party\ADLX\SDK\ADLXHelper\Windows\Cpp\ADLXHelper.h" (
        echo  [INFO] Cloning ADLX SDK...
        git clone --depth 1 https://github.com/GPUOpen-LibrariesAndSDKs/ADLX third_party\ADLX
    )
    pushd bridge
    cmake -B build -A x64
    cmake --build build --config Release
    popd
)
if not exist "bridge\build\Release\voltshift_bridge.exe" (
    echo  [ERROR] Bridge build failed - see messages above.
    pause & exit /b 1
)
echo  [OK] Bridge ready.

:: --- Python deps ------------------------------------------------------------
echo  [INFO] Installing Python dependencies...
py -3.12 -m pip install --quiet customtkinter psutil pywin32 pyinstaller

:: --- PyInstaller ------------------------------------------------------------
echo  [INFO] Building VoltShift.exe...
py -3.12 -m PyInstaller --noconfirm --clean --distpath build\dist --workpath build\work build\VoltShift.spec

if exist "build\dist\VoltShift\VoltShift.exe" (
    echo.
    echo  ========================================================
    echo   BUILD COMPLETE
    echo   Output: build\dist\VoltShift\VoltShift.exe
    echo   Right-click the exe and Run as Administrator.
    echo  ========================================================
) else (
    echo  [ERROR] Build failed - see messages above.
)
echo.
pause
