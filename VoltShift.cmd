@echo off
REM VoltShift launcher — runs the GUI from source.
REM
REM Points at src\ rather than a frozen build so the shortcut always launches
REM the current code. Rebuild the standalone .exe with build\build_exe_py312.bat
REM if you want a version that runs without Python installed.
REM
REM Elevation comes from the shortcut's run-as-administrator flag; tuning
REM writes go through ADLX and fail without it.

setlocal
cd /d "%~dp0"

py -3.12 "src\voltshift_gui.py" %*
set EXITCODE=%ERRORLEVEL%

REM Elevated windows close instantly on error, taking the traceback with them.
if not "%EXITCODE%"=="0" (
    echo.
    echo VoltShift exited with code %EXITCODE%.
    echo.
    pause
)

exit /b %EXITCODE%
