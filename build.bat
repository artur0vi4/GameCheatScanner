@echo off
REM ============================================================
REM  Сборка GameCheat Scanner в один .exe (Windows)
REM
REM  ВАЖНО:
REM   1. СНАЧАЛА распакуйте архив .zip в обычную папку (не запускайте
REM      build.bat изнутри .zip — Windows извлечёт во временную папку,
REM      и готовый .exe потеряется).
REM   2. Нужен установленный Python 3.10+ (https://www.python.org/downloads/,
REM      при установке отметьте "Add python.exe to PATH").
REM ============================================================
setlocal enableextensions
cd /d "%~dp0"

REM --- Выбор интерпретатора: сначала py-launcher, потом python ---
set "PY="
where py >nul 2>nul && set "PY=py"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo.
    echo [ОШИБКА] Python не найден.
    echo   Установите Python 3.10+ с https://www.python.org/downloads/
    echo   и при установке отметьте "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

REM --- Проверка, что это настоящий Python, а не заглушка Microsoft Store ---
%PY% --version 2>nul | findstr /R /C:"Python" >nul
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Команда "%PY%" не запускает настоящий Python.
    echo   Скорее всего, сработала заглушка Microsoft Store.
    echo   Откройте: Параметры -^> Приложения -^> "Псевдонимы выполнения
    echo   приложений" и выключите "python.exe" и "python3.exe",
    echo   либо установите Python с https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM --- Проверка, что мы в правильной (распакованной) папке ---
if not exist "requirements.txt" (
    echo.
    echo [ОШИБКА] Рядом с build.bat не найден requirements.txt.
    echo   Распакуйте архив .zip в папку и запускайте build.bat из неё,
    echo   а НЕ изнутри архива.
    echo.
    pause
    exit /b 1
)

echo [1/4] Python найден:
%PY% --version
echo.

echo [2/4] Установка зависимостей...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Не удалось установить зависимости (numpy / pyinstaller).
    pause
    exit /b 1
)

echo [3/4] Сборка .exe через PyInstaller...
REM --onefile        : один автономный .exe
REM --windowed        : без чёрного окна консоли
REM --uac-admin       : готовый .exe сам запросит права администратора
REM --collect-all numpy : гарантия, что numpy целиком попадёт в сборку
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin ^
    --name "GameCheatScanner" ^
    --collect-all numpy ^
    main.py
if errorlevel 1 (
    echo.
    echo [ОШИБКА] Сборка не удалась.
    pause
    exit /b 1
)

echo.
echo [4/4] Готово!
echo   .exe лежит в:  dist\GameCheatScanner.exe
echo.
echo   Запуск: правый клик на .exe -^> "Запуск от имени администратора".
echo.
pause
endlocal
