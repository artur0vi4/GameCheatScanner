"""
build.py — кроссплатформенная сборка GameCheatScanner.exe.
Альтернатива build.bat: запускается напрямую через Python и обходит
проблемы с выполнением .bat (SmartScreen, заглушки Microsoft Store и т.п.).

Запуск (нужен установленный Python 3.10+):
    python build.py

Результат: один автономный dist/GameCheatScanner.exe.
Запускать собранный .exe на Windows от имени администратора.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    req = HERE / "requirements.txt"
    if not req.exists():
        print("[ОШИБКА] Не найден requirements.txt рядом с build.py.")
        print("         Распакуйте архив .zip в папку и запускайте из неё.")
        sys.exit(1)

    print("[1/3] Установка зависимостей (numpy + pyinstaller)...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
        cwd=HERE,
    )

    print("[2/3] Сборка .exe через PyInstaller...")
    subprocess.check_call(
        [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean",
            "--onefile",          # один автономный .exe
            "--windowed",         # без окна консоли
            "--uac-admin",        # готовый .exe запросит права администратора
            "--name", "GameCheatScanner",
            "--collect-all", "numpy",
            "main.py",
        ],
        cwd=HERE,
    )

    exe = HERE / "dist" / "GameCheatScanner.exe"
    print("[3/3] Готово!")
    print(f"   .exe: {exe}")
    print('   Запуск: правый клик на .exe -> "Запуск от имени администратора".')


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\n[ОШИБКА] Шаг завершился с кодом {e.returncode}.")
        sys.exit(e.returncode)
