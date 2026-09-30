@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

REM Проверяем наличие Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [!] ОШИБКА: Python не найден в переменной PATH.
    exit /b 1
)

python build_release.py %*
if %errorlevel% neq 0 (
    echo [!] ОШИБКА: Сборка завершилась с ошибкой ^(код %errorlevel%^).
    exit /b %errorlevel%
)

echo [+] Сборка успешно завершена.
exit /b 0
