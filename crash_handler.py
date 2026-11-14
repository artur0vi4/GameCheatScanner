"""
crash_handler.py
Логирование и перехват ошибок GameCheat Scanner.

Что делает:
  1. setup_logging() — пишет подробный лог в gamecheat.log рядом с программой
     (и дублирует в консоль, если запущено из командной строки).
  2. install_excepthooks() — перехватывает все необработанные исключения
     (в главном потоке и в фоновых потоках сканера/заморозки) и пишет их в лог.
  3. show_crash_dialog() — показывает окно с текстом ошибки и кнопкой
     «Скопировать лог», чтобы пользователь мог прислать его разработчику.

Цель: если программа «вылетает», всегда остаётся gamecheat.log с полным
traceback — больше никаких «ничего не произошло, окно просто закрылось».
"""

from __future__ import annotations
import sys
import os
import logging
import traceback
import threading
import platform
from pathlib import Path

# Лог лежит рядом с программой (там же, где main.py / собранный .exe).
if getattr(sys, "frozen", False):
    # Запущен собранный .exe — кладём лог рядом с экзешником.
    LOG_PATH = Path(sys.executable).resolve().parent / "gamecheat.log"
else:
    LOG_PATH = Path(__file__).resolve().parent / "gamecheat.log"

LOGGER_NAME = "gamecheat"


def setup_logging() -> logging.Logger:
    """Настроить логгер: файл + консоль. Безопасно вызывать повторно."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)
    except Exception as e:
        # Если файл недоступен — хотя бы консоль.
        print(f"[crash_handler] не удалось открыть лог-файл {LOG_PATH}: {e}",
              file=sys.stderr)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(ch)

    logger.info("=" * 60)
    logger.info("GameCheat Scanner запущен")
    logger.info("Python %s", sys.version.replace("\n", " "))
    logger.info("Платформа: %s | %s", sys.platform, platform.platform())
    logger.info("Лог-файл: %s", LOG_PATH)
    try:
        if sys.platform == "win32":
            import ctypes
            logger.info("Права администратора: %s",
                        bool(ctypes.windll.shell32.IsUserAnAdmin()))
    except Exception as e:
        logger.info("Не удалось определить права админа: %s", e)
    logger.info("=" * 60)
    return logger


def install_excepthooks():
    """Перехват необработанных исключений в главном и фоновых потоках."""
    logger = logging.getLogger(LOGGER_NAME)

    def _main_hook(exc_type, exc, tb):
        # KeyboardInterrupt не логируем как ошибку.
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("Программа прервана (Ctrl+C).")
            sys.exit(0)
        tb_str = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.error("Необработанная ошибка (главный поток):\n%s", tb_str)
        # Диалог показываем только из главного потока (Tk не потокобезопасен).
        if threading.current_thread() is threading.main_thread():
            try:
                show_crash_dialog(exc, tb_str)
            except Exception as dlg_err:
                logger.error("Не удалось показать окно ошибки: %s", dlg_err)

    def _thread_hook(args):
        tb_str = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
        logger.error("Ошибка в фоновом потоке %s:\n%s",
                     args.thread.name if args.thread else "?", tb_str)
        # Из фонового потока Tk-диалог не показываем — только лог.

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook


def show_crash_dialog(exc, tb_str: str):
    """Показать окно с ошибкой. Вызывать из главного потока, ПОСЛЕ
    уничтожения предыдущего Tk-root (если был)."""
    import tkinter as tk
    from tkinter import ttk, scrolledtext

    root = tk.Tk()
    root.title("GameCheat Scanner — ошибка")
    root.geometry("760x460")
    root.minsize(560, 320)
    BG, PANEL, FG, DIM, ACCENT, GREEN, RED = (
        "#16162a", "#1e1e36", "#e8e8f5", "#9a9ac0",
        "#7c5cff", "#22d3a6", "#ef5b6b")

    # Шапка.
    head = tk.Frame(root, bg=PANEL, height=54)
    head.pack(fill=tk.X)
    head.pack_propagate(False)
    tk.Label(head, text="⚠  Программа завершилась с ошибкой", bg=PANEL, fg=RED,
             font=("Segoe UI", 13, "bold")).pack(padx=14, pady=14, anchor=tk.W)

    body = tk.Frame(root, bg=BG)
    body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(8, 4))
    tk.Label(body, text="Подробный лог сохранён в файл:", bg=BG, fg=DIM,
             font=("Segoe UI", 9)).pack(anchor=tk.W)
    path_lbl = tk.Label(body, text=str(LOG_PATH), bg=BG, fg=GREEN,
                        font=("Consolas", 9))
    path_lbl.pack(anchor=tk.W, pady=(0, 8))

    txt = scrolledtext.ScrolledText(body, bg=PANEL, fg=FG, insertbackground=FG,
                                   font=("Consolas", 9), wrap=tk.WORD,
                                   relief="flat", bd=0)
    txt.pack(fill=tk.BOTH, expand=True)
    txt.insert("1.0", tb_str)
    txt.configure(state=tk.DISABLED)

    btns = tk.Frame(root, bg=BG)
    btns.pack(fill=tk.X, padx=12, pady=8)

    def copy_all():
        root.clipboard_clear()
        root.clipboard_append(tb_str + "\n\n-- лог: " + str(LOG_PATH))
        btn_copy.config(text="✓ Скопировано в буфер")

    btn_copy = ttk.Button(btns, text="Скопировать лог", command=copy_all)
    btn_copy.pack(side=tk.LEFT)

    def open_folder():
        try:
            if sys.platform == "win32":
                os.startfile(str(LOG_PATH))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(LOG_PATH)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(LOG_PATH)])
        except Exception as e:
            logger.error("Не удалось открыть лог: %s", e)

    ttk.Button(btns, text="Открыть лог-файл", command=open_folder
               ).pack(side=tk.LEFT, padx=6)
    ttk.Button(btns, text="Закрыть", command=root.destroy).pack(side=tk.RIGHT)

    root.mainloop()
