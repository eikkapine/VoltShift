@echo off
setlocal
title VoltShift - Build ADLX Bridge

:: Builds voltshift_bridge.exe. Run from anywhere; paths are repo-relative.
cd /d "%~dp0\.."

if not exist "third_party\ADLX\SDK\ADLXHelper\Windows\Cpp\ADLXHelper.h" (
    echo [INFO] Cloning ADLX SDK into third_party\ADLX ...
    git clone --depth 1 https://github.com/GPUOpen-LibrariesAndSDKs/ADLX third_party\ADLX
    if errorlevel 1 (
        echo [ERROR] Failed to clone ADLX SDK. Is git installed?
        pause & exit /b 1
    )
)

pushd bridge
cmake -B build -A x64
if errorlevel 1 ( echo [ERROR] CMake configure failed. & popd & pause & exit /b 1 )
cmake --build build --config Release
popd

if exist "bridge\build\Release\voltshift_bridge.exe" (
    echo.
    echo [OK] Bridge built: bridge\build\Release\voltshift_bridge.exe
    echo      Quick test: bridge\build\Release\voltshift_bridge.exe info
) else (
    echo [ERROR] Bridge build failed - see messages above.
)
pause
