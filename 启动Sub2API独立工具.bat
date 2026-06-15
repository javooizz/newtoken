@echo off
setlocal
cd /d "%~dp0"

set "CODEX_PYTHON=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%CODEX_PYTHON%" (
    "%CODEX_PYTHON%" "%~dp0sub2api_standalone_tool.py"
    goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
    py "%~dp0sub2api_standalone_tool.py"
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0sub2api_standalone_tool.py"
    goto :end
)

echo 未找到可用的 Python 运行时。
echo 请先安装 Python，或者保留 Codex 自带运行时目录。
pause

:end
endlocal
