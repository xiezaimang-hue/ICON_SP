@echo off
rem ================================================================
rem  双击此文件即可运行 4×4 图标批量切分器（Windows）
rem ================================================================
rem  首次运行会自动：
rem    1) 在脚本目录下创建 .venv 虚拟环境
rem    2) 安装 requirements.txt 中的依赖（含 easyocr，约 100MB）
rem    3) 调用 splitter.py 处理 inputs/ 下所有目的地
rem  完成后窗口不会自动关闭，方便查看日志。
rem ================================================================

setlocal EnableDelayedExpansion
chcp 65001 >nul

rem 切到脚本所在目录（处理双击时 CWD 不在脚本目录的问题）
cd /d "%~dp0"

echo.
echo ============================================================
echo            4x4 图标批量切分器（独立离线版）
echo ============================================================
echo.
echo   工作目录: %CD%
echo.

rem ---- 1. 检测 python（优先 py launcher，回退 python） ----
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%i in ('py -3 --version 2^>nul') do (
        set "PY_VERSION=%%i"
        set "PYCMD=py -3"
    )
)
if "!PYCMD!"=="" (
    where python >nul 2>nul
    if not errorlevel 1 (
        for /f "delims=" %%i in ('python --version 2^>nul') do (
            set "PY_VERSION=%%i"
            set "PYCMD=python"
        )
    )
)
if "!PYCMD!"=="" (
    echo [X] 未找到 Python。
    echo.
    echo     请先安装 Python 3.9+：
    echo       · 访问 https://www.python.org/downloads/windows/
    echo       · 安装时务必勾选 "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)
echo [OK] 检测到 Python：!PY_VERSION!

rem ---- 2. 创建 venv（首次） ----
set "VENV_DIR=.venv"
if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo.
    echo [Setup] 首次运行：创建虚拟环境 %VENV_DIR% ...
    !PYCMD! -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [X] 创建虚拟环境失败。
        pause
        exit /b 1
    )
    echo [OK] 虚拟环境创建完成
)

rem ---- 3. 用 venv 里的 python（无需 activate） ----
set "VPY=%CD%\%VENV_DIR%\Scripts\python.exe"

rem ---- 4. 安装/升级依赖 ----
set "FLAG=%VENV_DIR%\.deps_installed"
set "NEED_INSTALL=0"
if not exist "%FLAG%" set "NEED_INSTALL=1"
if exist "%FLAG%" (
    rem requirements.txt 比 flag 新就重装
    for %%f in (requirements.txt) do set "REQ_TIME=%%~tf"
    for %%f in ("%FLAG%") do set "FLAG_TIME=%%~tf"
    if "!REQ_TIME!" gtr "!FLAG_TIME!" set "NEED_INSTALL=1"
)
if "!NEED_INSTALL!"=="1" (
    echo.
    echo [Setup] 安装依赖（首次较慢，包含 easyocr 模型可能需要几分钟）...
    "%VPY%" -m pip install --upgrade pip >nul 2>nul
    "%VPY%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [X] 依赖安装失败。
        echo     提示：如果是 easyocr 安装失败，可以临时编辑 requirements.txt
        echo           将 easyocr 那一行删除，再次双击此文件运行（不去文字）。
        pause
        exit /b 1
    )
    echo. > "%FLAG%"
    echo [OK] 依赖安装完成
)

rem ---- 5. 跑切分主流程 ----
echo.
echo ------------------------------------------------------------
echo   开始切分...
echo ------------------------------------------------------------
"%VPY%" splitter.py %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo ------------------------------------------------------------
if "%EXIT_CODE%"=="0" (
    echo [OK] 完成！请到 outputs\ 目录查看切片结果。
) else (
    echo [!] 脚本异常退出（exit=%EXIT_CODE%），请查看上方日志。
)
echo ------------------------------------------------------------
echo.

pause
endlocal
